"""
MCXG — the MCX gold desk (worldclass program W4). Session clock, contract specs,
live quotes with honest degradation, COMEX/USDINR overlay and a paper ticket.

Builds ON gold_preopen.py (never duplicates it): the ICICI security-master loader,
Yahoo bar fetcher, reference-window and fair-open formula are imported from there.
Reference data (holidays, specs, expiries, costs) lives in shared/mcx_specs.py.

Degrade-first (the ICICI session is invalid until the ~08:00 IST login, and Breeze
get_quotes answered MCX futures with HTTP 500 on 12 Oct 2026):
  * /quote ALWAYS answers 200. When Breeze cannot serve it the payload carries
    {"available": false, "reason": ...} via the errors.degraded envelope, plus the
    fallbacks that do work: the ICICI price-band settlement (public file, no session)
    and the COMEX × USD/INR fair value (Yahoo, works now).
  * a failed Breeze shape is remembered for 10 minutes per contract — zero retry storms
    (the session-invalid case is NOT remembered: positions._get_breeze_client already
    rate-limits failed logins, and the session can come alive any minute).

Purity: async handlers never block — Breeze/master work goes through asyncio.to_thread,
Yahoo through the async client. /session, /specs and /ticket are sync def (threadpool).

PAPER ONLY: /ticket prices a trade (notional, margin, round-trip costs); it records
nothing and no order API is ever imported here.
"""
from __future__ import annotations

import asyncio
import csv
import io
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import math

from fastapi import APIRouter, Body, Query

from cache import TTLCache
from errors import degraded, fail
from routers import gold_preopen as gp

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared import mcx_specs as specs  # noqa: E402

router = APIRouter()
IST = specs.IST
_TIMEOUT = httpx.Timeout(15.0)
_cache = TTLCache("mcx", max_items=64, default_ttl=600)
QUOTE_TTL_S = 15          # UI polls every 30 s; concurrent viewers share one broker call
BREEZE_BROKEN_TTL_S = 600


def _num(row: dict[str, Any], key: str) -> float | None:
    try:
        v = row.get(key)
        return float(v) if v not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        return None


# ── ICICI security master: all four gold contracts (gold_preopen parses GOLD only) ──

# ICICI's MCXScripMaster truncates ShortName to 6 characters (checked 15 Oct 2026:
# GOLD / GOLDMI / GOLDPE / GOLDGU / GOLDTE). Map both spellings to the MCX codes. GOLDTEN (10 g, 999,
# month-end expiry; Oct-26 OI 25,655 on 23 Oct — SOURCES.md F1) joined with the GOLD program.
MASTER_ALIASES = {"GOLD": "GOLD", "GOLDM": "GOLDM", "GOLDMI": "GOLDM",
                  "GOLDTEN": "GOLDTEN", "GOLDTE": "GOLDTEN",
                  "GOLDPETAL": "GOLDPETAL", "GOLDPE": "GOLDPETAL",
                  "GOLDGUINEA": "GOLDGUINEA", "GOLDGU": "GOLDGUINEA"}
# Breeze stock_code for MCX = ICICI's short name, NOT the MCX symbol. GOLD is verified
# (gold_preopen); the four minis are from the master — LIVE-VERIFY after the 08:00 login (PLAN §i O-8).
BREEZE_CODE = {"GOLD": "GOLD", "GOLDM": "GOLDMI", "GOLDTEN": "GOLDTE", "GOLDPETAL": "GOLDPE", "GOLDGUINEA": "GOLDGU"}

# GOLDTEN until shared/mcx_specs.CONTRACTS carries it (B3 patch request; the shared row wins once it exists):
# 10 g lot, quoted ₹ per 10 g, 999 purity, monthly, month-end expiry, tick ₹1 = ₹1 per lot (SOURCES.md F1, G-INDIA §4).
GOLDTEN_FALLBACK = specs.ContractSpec("GOLDTEN", "Gold Ten (10 g)", 10, 10, 1.0, "10 g", "999",
                                      "month_end", specs.ALL_MONTHS, 6.0,
                                      "Quoted per 10 g like GOLD, one-hundredth of its lot; 999 purity, month-end expiry.")
FAMILY_ORDER = ("GOLD", "GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL")


def contract_specs() -> dict[str, specs.ContractSpec]:
    """shared/mcx_specs.CONTRACTS plus GOLDTEN (from the shared module when it has it, else the fallback above),
    in the family order the selector shows."""
    merged = {**specs.CONTRACTS}
    merged.setdefault("GOLDTEN", GOLDTEN_FALLBACK)
    return {code: merged[code] for code in FAMILY_ORDER if code in merged} | {
        code: spec for code, spec in merged.items() if code not in FAMILY_ORDER}


def parse_gold_family(master_text: str) -> dict[str, list[dict[str, Any]]]:
    """FUTURE rows for every contract in contract_specs(), settlement = band midpoint
    (ICICI's daily price band is ±3% around the previous settlement — gold_preopen)."""
    out: dict[str, list[dict[str, Any]]] = {code: [] for code in contract_specs()}
    for r in csv.DictReader(io.StringIO(master_text), skipinitialspace=True):
        code = MASTER_ALIASES.get(r.get("ShortName") or "")
        if code is None or code not in out or r.get("Series") != "FUTURE":
            continue
        try:
            lo, hi = float(r["LowPriceRange"]), float(r["HighPriceRange"])
            expiry = datetime.strptime(r["ExpiryDate"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        settle = (lo + hi) / 2
        out[code].append({"expiry": expiry, "band_low": lo, "band_high": hi,
                          "settlement": round(settle, 2),
                          # ICICI's header is shifted: "MarginPercentage" carries open interest (lots)
                          "open_interest": float(r.get("MarginPercentage") or 0)})
    for rows in out.values():
        rows.sort(key=lambda c: c["expiry"])
    return out


def _master_gold_family() -> tuple[dict[str, list[dict[str, Any]]], date] | None:
    """Parsed master + its publish date, or None (desk still works on computed specs)."""
    try:
        master = gp.mcx_master()          # shared, stale-while-revalidate within 10 min (C-PERF-01)
    except Exception:  # noqa: BLE001 — public file server down: degrade to computed
        return None
    hit = _cache.get("gold_family")
    if hit and hit[1] == master[1]:
        return hit[0], master[1]
    family = parse_gold_family(master[0])
    _cache.set("gold_family", (family, master[1]), ttl=600)
    return family, master[1]


def _resolve_expiry(code: str, today: date, asked: date | None,
                    family: dict[str, list[dict[str, Any]]] | None) -> tuple[date, str, dict[str, Any] | None]:
    """(expiry, 'observed'|'computed'|'requested', master row if any)."""
    rows = (family or {}).get(code) or []
    if asked:
        row = next((r for r in rows if r["expiry"] == asked), None)
        return asked, "requested", row
    live = [r for r in rows if r["expiry"] >= today]
    if live:
        best = max(live, key=lambda r: (r["open_interest"], -r["expiry"].toordinal()))
        return best["expiry"], "observed", best
    computed = active_expiries(code, today, count=1)
    return computed[0], "computed", None


def active_expiries(code: str, today: date, count: int = 3) -> list[date]:
    """specs.active_expiries for the shared contracts; the same rule applied to the GOLDTEN fallback spec."""
    if code in specs.CONTRACTS:
        return specs.active_expiries(code, today, count=count)
    spec = contract_specs()[code]
    import calendar as _cal
    out: list[date] = []
    y, m = today.year, today.month
    for _ in range(30):
        if m in spec.months:
            raw = date(y, m, 5) if spec.expiry_kind == "day5" else date(y, m, _cal.monthrange(y, m)[1])
            exp = specs._back_to_business(raw)
            if exp >= today:
                out.append(exp)
                if len(out) >= count:
                    return out
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def spec_costs(code: str, price: float, lots: int,
               brokerage_per_order: float = specs.DEFAULT_BROKERAGE_PER_ORDER) -> dict[str, Any]:
    """specs.round_trip_costs, also for the GOLDTEN fallback (same rate card, its own multiplier)."""
    if code in specs.CONTRACTS:
        return specs.round_trip_costs(code, price, lots, brokerage_per_order=brokerage_per_order)
    spec = contract_specs()[code]
    turnover = price * spec.multiplier * lots
    buy = specs._side_costs(turnover, "buy", brokerage_per_order)
    sell = specs._side_costs(turnover, "sell", brokerage_per_order)
    total = round(buy["total"] + sell["total"], 2)
    return {"contract": code, "price": price, "lots": lots, "turnover_per_side": round(turnover, 2),
            "buy": buy, "sell": sell, "total": total,
            "pct_of_notional": round(total / turnover * 100, 4) if turnover else None,
            "breakeven_ticks": round(total / (spec.tick_value * lots), 2) if lots else None,
            "breakeven_price_move": round(total / (spec.multiplier * lots), 2) if lots else None,
            "rates_pct": specs.RATES_PCT, "indicative": True,
            "assumptions": ("both legs at the same price; squared off before expiry (CTT 0.01% sell side); "
                            f"brokerage ₹{brokerage_per_order:g}/order flat; GST on brokerage + txn + SEBI fee")}


# ── Breeze (degrade-first; see module docstring) ─────────────────────────────────

def _breeze_quote(code: str, expiry: date, today: date, after_open: bool) -> dict[str, Any]:
    """Sync — call via asyncio.to_thread. Never raises; never retries a broken shape."""
    broken_key = f"breeze_broken:{code}:{expiry.isoformat()}"
    remembered = _cache.get(broken_key)
    if remembered:
        return {"available": False, "quote": None, "reason": remembered, "attempted": False}
    try:
        from routers.positions import _get_breeze_client
        breeze, err = _get_breeze_client()
    except Exception as exc:  # noqa: BLE001 — import/build failure is a session problem
        breeze, err = None, str(exc)[:80]
    if breeze is None:
        return {"available": False, "quote": None, "attempted": True,
                "reason": f"ICICI session invalid: {(err or 'not connected').rstrip('. ')}. Live after the ~08:00 IST login"}
    expiry_arg = f"{expiry.isoformat()}T06:00:00.000Z"
    stock_code = BREEZE_CODE.get(code, code)
    sdk_err: str | None = None
    try:
        q = breeze.get_quotes(stock_code=stock_code, exchange_code="MCX", product_type="futures",
                              expiry_date=expiry_arg, right="others", strike_price="0")
        rows = q.get("Success") if isinstance(q, dict) and q.get("Status") == 200 else None
        if rows:
            row = rows[0]
            quote = {"ltp": _num(row, "ltp"), "open": _num(row, "open"), "high": _num(row, "high"),
                     "low": _num(row, "low"), "previous_close": _num(row, "previous_close"),
                     "time": row.get("ltt"), "source": "ICICI Breeze"}
            if quote["ltp"] is not None:
                return {"available": True, "quote": quote, "reason": None, "attempted": True}
        if isinstance(q, dict):
            sdk_err = str(q.get("Error") or "empty Success")[:80]
    except Exception as exc:  # noqa: BLE001 — the broker is optional here
        sdk_err = str(exc)[:80]
    if after_open:  # get_quotes failed; 1-min bars worked on 12 Oct where get_quotes 500'd
        try:
            h = breeze.get_historical_data_v2(interval="1minute",
                                              from_date=f"{today.isoformat()}T09:00:00.000Z",
                                              to_date=f"{today.isoformat()}T23:59:00.000Z",
                                              stock_code=stock_code, exchange_code="MCX", product_type="futures",
                                              expiry_date=expiry_arg, right="others", strike_price="0")
            bars = h.get("Success") if isinstance(h, dict) and h.get("Status") == 200 else None
            bars = sorted((b for b in bars or [] if str(b.get("datetime", "")).startswith(today.isoformat())),
                          key=lambda b: b["datetime"])
            if bars and bars[-1].get("close"):
                quote = {"ltp": float(bars[-1]["close"]), "open": float(bars[0]["open"]) if bars[0].get("open") else None,
                         "high": None, "low": None, "previous_close": None,
                         "time": bars[-1]["datetime"], "source": "ICICI Breeze (1-min bars)"}
                return {"available": True, "quote": quote, "reason": None, "attempted": True}
        except Exception:  # noqa: BLE001
            pass
    reason = (f"Breeze gave no MCX {code} quote ({sdk_err or 'no data'}) — commodity segment "
              "not verified for this account, or MCX futures unsupported by get_quotes "
              "(it answered HTTP 500 on 12 Oct 2026)")
    _cache.set(broken_key, reason, ttl=BREEZE_BROKEN_TTL_S)   # zero retry storms
    return {"available": False, "quote": None, "reason": reason, "attempted": True}


# ── COMEX × USD/INR fair value (gold_preopen's formula, lean inputs) ─────────────

async def _fair_value(code: str, expiry: date, settlement: float | None,
                      published: date | None) -> dict[str, Any] | None:
    """COMEX + rupee legs from gold_preopen's ONE Yahoo fetcher (`_yahoo_bars_cached`: SWR 30/120 s, single flight —
    PLAN 0.1 #2; this used to be a second uncached fetcher), the landed conversion, the duty leg (SOURCES.md M5–M8) and
    — when a settlement exists — gold_preopen.fair_open scaled to this contract's quotation unit. Cached 60 s."""
    key = f"fair:{code}:{expiry.isoformat()}"
    hit = _cache.get(key)
    if hit is not None:
        return hit or None
    comex_sym = gp.comex_symbol(expiry)
    try:
        comex, inr = await asyncio.gather(asyncio.wait_for(gp._yahoo_bars_cached(comex_sym), 10),
                                          asyncio.wait_for(gp._yahoo_bars_cached("INR=X"), 10))
    except Exception:  # noqa: BLE001 — Yahoo down: the desk shows the band instead
        _cache.set(key, {}, ttl=60)
        return None
    if not (comex.get("price") and inr.get("price")):
        _cache.set(key, {}, ttl=60)
        return None
    spec = contract_specs()[code]
    quote_g = spec.quote_per_grams
    duty = gp.duty_rate()
    landed = gp.landed_inr_per_10g(comex["price"], inr["price"], quote_g)
    duty_paid = landed * (1 + duty["pct"] / 100)
    out: dict[str, Any] = {
        "comex": {"symbol": comex_sym, "price": round(comex["price"], 2),
                  "as_of": comex["time"].isoformat() if comex.get("time") else None},
        "usdinr": {"symbol": "INR=X", "price": round(inr["price"], 4),
                   "as_of": inr["time"].isoformat() if inr.get("time") else None},
        "landed": round(landed, 0),
        "landed_note": f"COMEX × USD/INR × {quote_g} g/oz — ex-duty, no local premium",
        "duty_pct": duty["pct"], "duty_effective": duty["effective"], "duty_note": duty["note"],
        "duty_paid_landed": round(duty_paid, 0),
        "source": "Yahoo GC×INR model (cached fetcher)",
    }
    if settlement:
        settle_day = gp.previous_session(published or datetime.now(IST).date())
        close_at = gp.mcx_close_time(settle_day)
        comex_ref, _ = gp.reference_price(comex.get("bars") or [], close_at)
        inr_ref, _ = gp.reference_price(inr.get("bars") or [], close_at)
        if comex_ref and inr_ref:
            # fair_open works in ₹/10 g terms; the duty leg scales to this contract's quotation unit below
            model = gp.fair_open(settlement * 10 / quote_g, comex_ref, comex["price"], inr_ref, inr["price"], duty["pct"])
            scale = quote_g / 10
            out["fair"] = round(model["fair_open"] * scale, 0)
            out["gap_vs_settlement"] = round(model["gap"] * scale, 0)
            out["basis_pct"] = model["basis_pct"]                   # settlement vs duty-paid landed (M8)
            out["implied_premium_pct"] = model["implied_premium_pct"]   # deprecated alias (duty + carry + premium)
            out["settlement_session"] = settle_day.isoformat()
            out["settlement_session_label"] = gp.session_label(settle_day)
            out["settlement"] = settlement
    _cache.set(key, out, ttl=60)
    return out


def overlay_line(code: str, expiry: date, fair: dict[str, Any] | None, mcx_price: float | None) -> dict[str, Any]:
    """The ONE-LINE overlay MCXG renders (PLAN §b): `COMEX GCZ26 $4,004.3 · ₹/$ 94.93 · duty-paid landed ₹1,40,348 ·
    fair ₹1,44,231 · live vs fair — · GOLD ›`. No implied-premium prose; the India ladder lives on GOLD › PHYSICAL."""
    if not fair:
        return {"line": f"MCX {code} {expiry:%b-%y}: COMEX × USD/INR unavailable · GOLD ›", "fields": None, "link": "GOLD"}
    live_vs_fair: dict[str, Any] | None = None
    if mcx_price and fair.get("fair"):
        live_vs_fair = {"rupees": round(mcx_price - fair["fair"], 0), "pct": round((mcx_price / fair["fair"] - 1) * 100, 2)}
    parts = [f"COMEX {fair['comex']['symbol'].replace('.CMX', '')} ${fair['comex']['price']:,.1f}",
             f"₹/$ {fair['usdinr']['price']:.2f}",
             f"duty-paid landed ₹{fair['duty_paid_landed']:,.0f}",
             f"fair ₹{fair['fair']:,.0f}" if fair.get("fair") else "fair —",
             (f"live vs fair {live_vs_fair['rupees']:+,.0f} ({live_vs_fair['pct']:+.2f} %)" if live_vs_fair
              else "live vs fair —"),
             "GOLD ›"]
    return {"line": " · ".join(parts), "link": "GOLD",
            "fields": {"comex_symbol": fair["comex"]["symbol"], "comex_price": fair["comex"]["price"],
                       "usdinr": fair["usdinr"]["price"], "landed": fair["landed"], "duty_pct": fair["duty_pct"],
                       "duty_paid_landed": fair["duty_paid_landed"], "fair": fair.get("fair"),
                       "settlement_session_label": fair.get("settlement_session_label"), "live_vs_fair": live_vs_fair}}


# ── endpoints ────────────────────────────────────────────────────────────────────

@router.get("/session")
def mcx_session() -> dict[str, Any]:
    """OPEN/CLOSED, time-to-close/open, today's closure reason, upcoming MCX holidays."""
    now = datetime.now(IST)
    state = specs.session_state(now)
    state["upcoming_holidays"] = specs.upcoming_holidays(now.date(), count=6)
    state["special_sessions"] = specs.SPECIAL_SESSIONS_2026
    state["calendar_source"] = ("MCX 2026 list via ICICI Direct iLearn / Kotak Neo / 5paisa "
                                "(mcxindia.com blocks non-browser clients) — see shared/mcx_specs.py")
    return state


@router.get("/specs")
def mcx_contract_specs() -> dict[str, Any]:
    """Static + computed specs for the gold family; expiries cross-checked against
    ICICI's public security master when it is available (no broker session needed)."""
    today = datetime.now(IST).date()
    got = _master_gold_family()
    family, published = got if got else ({}, None)
    rows = []
    for code, spec in contract_specs().items():
        d = spec.as_dict()
        d["computed_expiries"] = [x.isoformat() for x in active_expiries(code, today, count=3)]
        observed = [r for r in family.get(code, []) if r["expiry"] >= today]
        d["observed_expiries"] = [r["expiry"].isoformat() for r in observed[:3]] or None
        front = observed[0] if observed else None
        if front:
            d["front"] = {"expiry": front["expiry"].isoformat(), "settlement": front["settlement"],
                          "band_low": front["band_low"], "band_high": front["band_high"],
                          "open_interest_lots": front["open_interest"]}
            d["indicative_margin_rupees"] = round(front["settlement"] * spec.multiplier * spec.span_margin_pct_indicative / 100,
                                                  0)
        rows.append(d)
    return {
        "as_of": datetime.now(IST).isoformat(timespec="seconds"),
        "contracts": rows,
        "master": {"available": bool(got), "published": published.isoformat() if published else None,
                   "source": "ICICI MCXScripMaster.txt (public, ~07:00 IST)"},
        "margin_note": ("SPAN+exposure margins are revised daily by MCX (bullion typically ≈6–12%); "
                        "the % here is indicative for paper sizing only."),
        "expiry_note": ("Computed: GOLD = 5th of Feb/Apr/Jun/Aug/Oct/Dec, GOLDM = 5th monthly, "
                        "TEN/PETAL/GUINEA = month-end, each moved to the previous business day when MCX "
                        "is closed (morning closures included — observed 30 Mar 2026). The exchange "
                        "circular is the legal source; 'observed' rows come from ICICI's master."),
        "selector_note": "The contract selector (exchange × family × expiry, economics, OI ladder) is /api/gold/contracts.",
    }


@router.get("/quote")
async def mcx_quote(contract: str = Query("GOLD"),
                    expiry: str | None = Query(None, description="YYYY-MM-DD; default = front by OI")) -> dict[str, Any]:
    """Live MCX quote via Breeze when the account can serve it; otherwise an honest
    degrade with the two fallbacks that always work (price band, COMEX×INR fair value)."""
    code = contract.upper()
    if code not in contract_specs():
        fail(422, "invalid", f"Unknown MCX contract '{contract}'",
             hint=f"One of {', '.join(contract_specs())}")
    asked: date | None = None
    if expiry:
        try:
            asked = date.fromisoformat(expiry)
        except ValueError:
            fail(422, "invalid", "expiry must be YYYY-MM-DD")
    now = datetime.now(IST)
    cache_key = f"quote:{code}:{expiry or 'front'}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return hit

    got = await asyncio.to_thread(_master_gold_family)
    family, published = got if got else (None, None)
    exp, exp_source, row = _resolve_expiry(code, now.date(), asked, family)
    after_open = (now.hour, now.minute) >= (9, 0) and now.weekday() < 5
    breeze = await asyncio.to_thread(_breeze_quote, code, exp, now.date(), after_open)
    fair = await _fair_value(code, exp, (row or {}).get("settlement"), published)

    spec = contract_specs()[code]
    settle_day = gp.previous_session(published) if published else None
    band = ({"settlement": row["settlement"], "band_low": row["band_low"], "band_high": row["band_high"],
             "open_interest_lots": row["open_interest"],
             "session": settle_day.isoformat() if settle_day else None,
             "session_label": gp.session_label(settle_day) if settle_day else None,
             "quality": "proxy",
             "source": f"ICICI price-band midpoint ({published.isoformat() if published else '—'} master)"}
            if row else None)
    best = None
    if breeze["available"] and breeze["quote"].get("ltp"):
        best = {"price": breeze["quote"]["ltp"], "source": breeze["quote"]["source"]}
    elif fair and fair.get("fair"):
        best = {"price": fair["fair"], "source": "fair value (COMEX × USD/INR model)"}
    elif band:
        best = {"price": band["settlement"], "source": "previous settlement (price band)"}
    payload: dict[str, Any] = {
        "as_of": now.isoformat(timespec="seconds"),
        "contract": code, "expiry": exp.isoformat(), "expiry_source": exp_source,
        "tick_value": spec.tick_value, "lot": spec.as_dict()["lot"],
        "available": breeze["available"], "quote": breeze["quote"],
        "fallbacks": {"band": band, "fair_value": fair},
        "best": best,
    }
    if breeze["available"]:
        _cache.set(cache_key, payload, ttl=QUOTE_TTL_S)
        return payload
    payload["reason"] = breeze["reason"]
    payload["live_verify_pending"] = True
    out = degraded(payload, "degraded", breeze["reason"] or "MCX quote unavailable",
                   hint="Fallbacks shown are the ICICI price band and the COMEX×INR fair value")
    _cache.set(cache_key, out, ttl=QUOTE_TTL_S)
    return out


@router.get("/overlay")
async def mcx_overlay(contract: str = Query("GOLD"),
                      expiry: str | None = Query(None),
                      mcx_price: float | None = Query(None, gt=0, description="The MCX price the desk is showing"),
                      ) -> dict[str, Any]:
    """COMEX last, USD/INR, landed, duty-paid landed + model fair value as ONE LINE (`line`, `fields`; PLAN §b) with
    the legacy `overlay`/`premium` keys kept for one release; premium/discount of the MCX price vs fair when the
    caller has one (the UI passes the quote it displays)."""
    code = contract.upper()
    if code not in contract_specs():
        fail(422, "invalid", f"Unknown MCX contract '{contract}'")
    asked: date | None = None
    if expiry:
        try:
            asked = date.fromisoformat(expiry)
        except ValueError:
            fail(422, "invalid", "expiry must be YYYY-MM-DD")
    today = datetime.now(IST).date()
    got = await asyncio.to_thread(_master_gold_family)
    family, published = got if got else (None, None)
    exp, _, row = _resolve_expiry(code, today, asked, family)
    fair = await _fair_value(code, exp, (row or {}).get("settlement"), published)
    if fair is None:
        return degraded({"as_of": datetime.now(IST).isoformat(timespec="seconds"),
                         "contract": code, "expiry": exp.isoformat(), "overlay": None, "premium": None,
                         **overlay_line(code, exp, None, mcx_price)},
                        "upstream_down", "COMEX/USDINR unavailable from Yahoo right now",
                        hint="Retry in a minute; the specs and session clock still work")
    premium = None
    ref = fair.get("fair") or fair.get("landed")
    if mcx_price and ref:
        premium = {"vs": "fair model" if fair.get("fair") else "landed COMEX",
                   "rupees": round(mcx_price - ref, 0),
                   "pct": round((mcx_price / ref - 1) * 100, 2)}
    return {"as_of": datetime.now(IST).isoformat(timespec="seconds"),
            "contract": code, "expiry": exp.isoformat(), "overlay": fair,
            "mcx_price": mcx_price, "premium": premium, **overlay_line(code, exp, fair, mcx_price)}


@router.post("/ticket")
def mcx_paper_ticket(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """PAPER pricing only — notional, tick value, indicative margin and round-trip MCX
    costs for {contract, lots, price[, brokerage_per_order]}. Records nothing; no order
    API exists in this module.

    GOLD program additions (PLAN §b/§d, SOURCES.md M69; every one optional and pure arithmetic): `margin_pct` +
    `margin_source` + `margin_date` (the Zerodha NRML mirror the selector carries; default stays the indicative
    constant), `atr14_rupees` + `account_inr` + `risk_pct` → `max_lots_at_risk_pct` (account × risk % ÷ (1.5 × ATR₁₄
    × multiplier)), `usdinr` → `hedge_usdinr_lots` (notional in $ ÷ the $1,000 USDINR futures lot)."""
    code = str(payload.get("contract") or "").upper()
    if code not in contract_specs():
        fail(422, "invalid", f"Unknown MCX contract '{payload.get('contract')}'",
             hint=f"One of {', '.join(contract_specs())}")
    try:
        lots = int(payload.get("lots") or 0)
        price = float(payload.get("price") or 0)
        brokerage = float(payload.get("brokerage_per_order", specs.DEFAULT_BROKERAGE_PER_ORDER))
        opt = {k: (float(payload[k]) if payload.get(k) not in (None, "") else None)
               for k in ("margin_pct", "atr14_rupees", "account_inr", "risk_pct", "usdinr")}
    except (TypeError, ValueError):
        fail(422, "invalid", "lots must be an integer; price, brokerage_per_order and the sizing inputs numbers")
    if not (math.isfinite(price) and math.isfinite(brokerage)):   # C2 LOW: "NaN"/"Infinity"
        fail(422, "invalid", "price and brokerage_per_order must be finite numbers")
    if any(v is not None and (not math.isfinite(v) or v < 0) for v in opt.values()):
        fail(422, "invalid", "sizing inputs (margin_pct, atr14_rupees, account_inr, risk_pct, usdinr) must be finite and >= 0")
    if lots < 1 or lots > 1000:
        fail(422, "invalid", "lots must be between 1 and 1000")
    if price <= 0:
        fail(422, "invalid", "price must be positive — use the price the desk shows",
             hint="Breeze LTP when live, else the fair value / settlement fallback")
    if brokerage < 0 or brokerage > 10_000:
        fail(422, "invalid", "brokerage_per_order out of range")
    if opt["margin_pct"] is not None and opt["margin_pct"] > 100:
        fail(422, "invalid", "margin_pct is a percentage of notional")
    spec = contract_specs()[code]
    costs = spec_costs(code, price, lots, brokerage_per_order=brokerage)
    notional = price * spec.multiplier * lots
    margin_pct = opt["margin_pct"] if opt["margin_pct"] is not None else spec.span_margin_pct_indicative
    margin_source = (str(payload.get("margin_source") or "zerodha_nrml") if opt["margin_pct"] is not None
                     else "indicative constant (shared/mcx_specs)")
    risk_pct = opt["risk_pct"] if opt["risk_pct"] is not None else 1.0
    max_lots = None
    if opt["account_inr"] and opt["atr14_rupees"]:
        stop_per_lot = 1.5 * opt["atr14_rupees"] * spec.multiplier
        max_lots = int(opt["account_inr"] * risk_pct / 100 / stop_per_lot) if stop_per_lot > 0 else None
    hedge = round(notional / (opt["usdinr"] * 1000), 2) if opt["usdinr"] else None
    return {
        "paper": True, "recorded": False,
        "contract": code, "lot": spec.as_dict()["lot"], "lots": lots, "price": price,
        "notional": round(notional, 2),
        "tick_value_per_lot": spec.tick_value,
        "tick_value_position": round(spec.tick_value * lots, 2),
        "indicative_margin": round(notional * margin_pct / 100, 0),
        "margin_pct_indicative": margin_pct,
        "margin_source": margin_source,
        "margin_date": payload.get("margin_date") if opt["margin_pct"] is not None else None,
        "round_trip": costs,
        "atr14_rupees": opt["atr14_rupees"],
        "risk_pct": risk_pct,
        "max_lots_at_risk_pct": max_lots,
        "hedge_usdinr_lots": hedge,
        "sizing_note": ("max lots = account × risk % ÷ (1.5 × ATR₁₄ × ₹ per ₹1 move per lot); hedge lots = $ notional ÷ "
                        "$1,000 (one USDINR futures lot). Arithmetic only — no view on direction."),
        "note": ("Indicative: exchange margins move daily; costs assume a squared-off trade "
                 "(CTT 0.01% sell side), flat brokerage, GST 18% on brokerage+txn+SEBI. "
                 "This ticket prices the trade — nothing is sent anywhere."),
    }
