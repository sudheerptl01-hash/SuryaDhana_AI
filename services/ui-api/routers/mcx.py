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
from datetime import date, datetime, timedelta
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
# (gold_preopen); the four minis are from the master — LIVE-VERIFY after the 08:00 login (PLAN §i O-8). ONE table, kept in
# gold_preopen (its accuracy-log checks need it too).
BREEZE_CODE = gp.BREEZE_CODE

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
                # the day's range from the same bars (5 Nov review: HIGH / LOW printed '— / —' while the bars existed)
                highs = [h for h in (_num(b, "high") for b in bars) if h is not None]
                lows = [x for x in (_num(b, "low") for b in bars) if x is not None]
                quote = {"ltp": float(bars[-1]["close"]), "open": float(bars[0]["open"]) if bars[0].get("open") else None,
                         "high": max(highs) if highs else None, "low": min(lows) if lows else None,
                         "previous_close": None, "range_from": "today's 1-minute bars",
                         "time": bars[-1]["datetime"], "source": "ICICI Breeze (1-min bars)"}
                return {"available": True, "quote": quote, "reason": None, "attempted": True}
        except Exception:  # noqa: BLE001
            pass
    reason = (f"Breeze gave no MCX {code} quote ({sdk_err or 'no data'}) — commodity segment "
              "not verified for this account, or MCX futures unsupported by get_quotes "
              "(it answered HTTP 500 on 12 Oct 2026)")
    _cache.set(broken_key, reason, ttl=BREEZE_BROKEN_TTL_S)   # zero retry storms
    return {"available": False, "quote": None, "reason": reason, "attempted": True}


# ── the settlement every number divides by (wave 1d: gold_preopen.settlement_block) ──

SETTLE_KEYS = ("settlement", "settlement_source", "settlement_session", "settlement_session_label", "settlement_quality",
               "settlement_method", "settlement_note", "settlement_is_latest", "band_midpoint", "band_session",
               "band_session_label", "band_applies_to", "latest_session", "latest_session_label", "settlement_check", "vwap30")


def vwap30_series_id(code: str, expiry: date) -> str:
    """data-service's per-contract series id (gold/mcx_close.series_id): 'MCX_GOLD_202612_VWAP30'."""
    return f"MCX_{code}_{expiry:%Y%m}_VWAP30"


STORED_MISS_TTL_S = 300.0   # a (contract, session) data-service has not stored is asked again after 5 min, not per request


def stored_vwap_enabled() -> bool:
    """GOLD_STORED_VWAP=1/0 decides; unset, it is on except under pytest (a test never reads the live data-service)."""
    import os

    flag = os.environ.get("GOLD_STORED_VWAP", "").strip()
    if flag in ("0", "1"):
        return flag == "1"
    try:
        from shared.http_guard import in_test_mode
        if in_test_mode():
            return False
    except ImportError:
        pass
    return True


def _stored_point(series: dict[str, list[dict[str, Any]]], code: str, expiry: date, session: date) -> dict[str, Any] | None:
    """One stored VWAP30 point as a `gold_preopen.session_vwap` result, or None. Pure."""
    sid = vwap30_series_id(code, expiry)
    pt = next((p for p in reversed(series.get(sid) or []) if str(p.get("report_date"))[:10] == session.isoformat()), None)
    if pt is None or not pt.get("value"):
        return None
    lots = next((p for p in reversed(series.get(f"{sid}_LOTS") or []) if str(p.get("report_date"))[:10] == session.isoformat()),
                None)
    close_at = gp.session_close_at(session)
    return {"status": "ok", "value": round(float(pt["value"]), 1), "bars": None, "volume": (lots or {}).get("value"),
            "method": "volume-weighted", "window": f"{close_at - timedelta(minutes=gp.VWAP_WINDOW_MIN):%H:%M}–{close_at:%H:%M} IST",
            "last_close": None, "session": session.isoformat(), "source": "breeze_vwap30", "read_by": "data-service (stored)",
            "stock_code": BREEZE_CODE.get(code, code), "expiry": expiry.isoformat(), "window_complete": True}


async def fill_stored_vwaps(items: list[tuple[str, date, date]]) -> int:
    """ONE data-service read (`/db/gold/series`) for every (family, expiry, session) not known yet: each stored
    `MCX_<FAMILY>_<YYYYMM>_VWAP30` point (G-DATA's 23:58 job, point-in-time) is cached under the SAME key as ui-api's own
    Breeze read, so that session costs no call on any path; a key not stored is remembered for STORED_MISS_TTL_S. Returns
    how many were found. Never raises."""
    if not stored_vwap_enabled():
        return 0
    todo: list[tuple[str, date, date]] = []
    for code, expiry, session in dict.fromkeys(items):
        hit = gp.session_vwap_cached(BREEZE_CODE.get(code, code), expiry, session)
        if (hit is not None and hit.get("status") == "ok") or _cache.get(f"stored_vwap_miss:{code}:{expiry}:{session}"):
            continue
        todo.append((code, expiry, session))
    if not todo:
        return 0
    ids = sorted({vwap30_series_id(c, e) for c, e, _ in todo})
    oldest = min(s for _, _, s in todo)
    try:
        from routers import gold as goldr   # late import: gold imports this module
        days = max(10, (goldr._now_ist().date() - oldest).days + 3)
        series = await goldr.fetch_series(goldr.Reads(), ids + [f"{i}_LOTS" for i in ids], days=days)
    except Exception:  # noqa: BLE001 — the Breeze read is the fallback
        return 0
    found = 0
    for code, expiry, session in todo:
        res = _stored_point(series, code, expiry, session)
        if res is None:
            _cache.set(f"stored_vwap_miss:{code}:{expiry}:{session}", True, ttl=STORED_MISS_TTL_S)
            continue
        gp._settle_cache.set(gp._settle_key(BREEZE_CODE.get(code, code), expiry, session), res, ttl=gp.SETTLE_OK_TTL_S)
        found += 1
    return found


async def _stored_vwap30(code: str, expiry: date, session: date) -> dict[str, Any] | None:
    """The stored last-30-min VWAP of (contract, expiry, session) from data-service, as a `session_vwap` result; None when it
    is not stored (or the store is down)."""
    await fill_stored_vwaps([(code, expiry, session)])
    hit = gp.session_vwap_cached(BREEZE_CODE.get(code, code), expiry, session)
    return hit if hit and hit.get("read_by") == "data-service (stored)" else None


async def session_vwap_any(code: str, expiry: date, session: date, wait_s: float | None = None) -> dict[str, Any]:
    """One session's VWAP30 through the ONE path (round-2 checker: the desk, CONTRACTS and the MCX tape read the same way):
    the cache → data-service's stored value → ONE Breeze read (waited for at most `wait_s`)."""
    await fill_stored_vwaps([(code, expiry, session)])
    return await gp.session_vwap_async(BREEZE_CODE.get(code, code), expiry, session,
                                       gp._settle_wait() if wait_s is None else wait_s)


async def settlement_vwaps(code: str, expiry: date, latest: date, *, wait: bool = True,
                           wait_s: float | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(the latest session's VWAP30 result, the PREVIOUS session's when already known) for a settlement block — the cache,
    then data-service's stored values (both sessions in one read), then ONE Breeze read for the latest session (`wait=False`:
    queued on the background thread, never waited for). The previous session is never read from Breeze here: it only
    stands in, labelled with its own session, when it is known and the latest is not (fresher than a two-session-old band)."""
    stock = BREEZE_CODE.get(code, code)
    prev = gp.previous_session(latest)
    await fill_stored_vwaps([(code, expiry, latest), (code, expiry, prev)])
    vwap: dict[str, Any] | None
    if wait:
        vwap = await gp.session_vwap_async(stock, expiry, latest, gp._settle_wait() if wait_s is None else wait_s)
    else:
        vwap = gp.session_vwap_cached(stock, expiry, latest)
        if vwap is None:
            gp.prefetch_session_vwaps([(stock, expiry, latest)])
    return vwap, gp.session_vwap_cached(stock, expiry, prev)


async def resolve_settlement(code: str, expiry: date, row: dict[str, Any] | None, published: date | None,
                             now: datetime | None = None, wait: bool = True) -> dict[str, Any]:
    """The CONTRACT's settlement block for one MCX contract: the latest completed session's last-30-min VWAP of its Breeze
    1-minute bars (data-service's stored read first, else ONE call per contract per session, cached all night; `wait=False`
    reads the cache only and queues the call in the background), else the previous session's VWAP when known, else the ICICI
    band midpoint labelled with the session it really belongs to."""
    now = now or datetime.now(IST)
    latest = gp.latest_completed_session(now)
    vwap, prev_vwap = await settlement_vwaps(code, expiry, latest, wait=wait)
    return gp.settlement_block((row or {}).get("settlement"), published, vwap, latest, prev_vwap)


# ── COMEX × USD/INR fair value (gold_preopen's formula, lean inputs) ─────────────

async def _fair_value(code: str, expiry: date, settle: dict[str, Any] | None) -> dict[str, Any] | None:
    """COMEX + rupee legs from gold_preopen's ONE Yahoo fetcher (`_yahoo_bars_cached`: SWR 30/120 s, single flight —
    PLAN 0.1 #2; this used to be a second uncached fetcher), the landed conversion, the duty leg (SOURCES.md M5–M8) and
    — when a settlement exists — gold_preopen.fair_open scaled to this contract's quotation unit, with the COMEX / rupee
    references at THAT settlement session's close and the basis vs the landed price of the contract's purity. The COMEX
    leg is the LIQUID month (`comex_liquid_symbol`: GOLDTEN NOV-26 → GCZ26, never the thin serial GCX26 — 5 Nov review).
    Cached 60 s per (contract, expiry, settlement)."""
    s = settle or {}
    key = f"fair:{code}:{expiry.isoformat()}:{s.get('settlement_source')}:{s.get('settlement_session')}:{s.get('settlement')}"
    hit = _cache.get(key)
    if hit is not None:
        return hit or None
    comex_sym, comex_sub = gp.comex_liquid_symbol(expiry)
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
    fine = gp.fineness_of(code)
    landed = gp.landed_inr_per_10g(comex["price"], inr["price"], quote_g)
    duty_paid = landed * (1 + duty["pct"] / 100)
    out: dict[str, Any] = {
        "comex": {"symbol": comex_sym, "price": round(comex["price"], 2),
                  "as_of": comex["time"].isoformat() if comex.get("time") else None,
                  "calendar_symbol": gp.comex_symbol(expiry),
                  "matched_note": "nearest liquid COMEX month (Feb/Apr/Jun/Aug/Oct/Dec)" if comex_sub else None},
        "usdinr": {"symbol": "INR=X", "price": round(inr["price"], 4),
                   "as_of": inr["time"].isoformat() if inr.get("time") else None},
        "landed": round(landed, 0),
        "landed_note": (f"COMEX × USD/INR × {quote_g} g ÷ 31.1035 g/oz — ex-duty, no local premium, per FINE gold; the basis "
                        f"divides by it × {fine}/1000 (PM decision D1)"),
        "duty_pct": duty["pct"], "duty_effective": duty["effective"], "duty_note": duty["note"],
        "duty_paid_landed": round(duty_paid, 0),
        # the landed price of THIS contract's purity: landed × purity / 1000 (D1: 995 GOLD / GOLDM, 999 TEN / PETAL / GUINEA)
        "purity": fine,
        "basis_reference": gp.basis_reference(code),
        "landed_purity": round(landed * fine / gp.LANDED_FINENESS, 0),
        "duty_paid_landed_purity": round(duty_paid * fine / gp.LANDED_FINENESS, 0),
        "quote_unit": f"₹ per {quote_g} g",
        "source": "Yahoo GC×INR model (cached fetcher)",
    }
    for k in SETTLE_KEYS:
        out[k] = s.get(k)
    settlement = s.get("settlement")
    if settlement and s.get("settlement_session"):
        settle_day = date.fromisoformat(s["settlement_session"])
        close_at = gp.session_close_at(settle_day)
        comex_ref, _ = gp.reference_price(comex.get("bars") or [], close_at)
        inr_ref, _ = gp.reference_price(inr.get("bars") or [], close_at)
        if comex_ref and inr_ref:
            # fair_open works in ₹/10 g terms; the duty leg scales to this contract's quotation unit below
            model = gp.fair_open(settlement * 10 / quote_g, comex_ref, comex["price"], inr_ref, inr["price"], duty["pct"],
                                 fineness=fine)
            scale = quote_g / 10
            out["fair"] = round(model["fair_open"] * scale, 0)
            out["gap_vs_settlement"] = round(model["gap"] * scale, 0)
            out["basis_pct"] = model["basis_pct"]        # settlement vs duty-paid landed of its purity, at its close (M8)
            out["basis_clock"] = "settlement"
            out["duty_paid_landed_at_settlement"] = round(model["duty_paid_landed_purity"] * scale, 0)
            out["implied_premium_pct"] = model["implied_premium_pct"]   # deprecated alias (duty + carry + premium)
            out["comex_ref"] = round(comex_ref, 2)
            out["usdinr_ref"] = round(inr_ref, 4)
            out["ref_close_at"] = close_at.isoformat(timespec="minutes")
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
                       "comex_matched_note": fair["comex"].get("matched_note"),
                       "usdinr": fair["usdinr"]["price"], "landed": fair["landed"], "duty_pct": fair["duty_pct"],
                       "duty_paid_landed": fair["duty_paid_landed"], "fair": fair.get("fair"),
                       "settlement": fair.get("settlement"), "settlement_source": fair.get("settlement_source"),
                       "settlement_quality": fair.get("settlement_quality"),
                       "settlement_session_label": fair.get("settlement_session_label"),
                       "settlement_check": fair.get("settlement_check"), "live_vs_fair": live_vs_fair}}


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
            b_sess = gp.band_session(published) if published else None
            d["front"] = {"expiry": front["expiry"].isoformat(), "settlement": front["settlement"],
                          "settlement_source": "band_midpoint", "settlement_quality": "band_proxy",
                          "settlement_session": b_sess.isoformat() if b_sess else None,
                          "settlement_session_label": gp.session_label(b_sess) if b_sess else None,
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
    settle = await resolve_settlement(code, exp, row, published, now)
    fair = await _fair_value(code, exp, settle)

    spec = contract_specs()[code]
    b_sess = gp.band_session(published) if published else None
    band = ({"settlement": row["settlement"], "band_low": row["band_low"], "band_high": row["band_high"],
             "open_interest_lots": row["open_interest"],
             # the midpoint is the settlement of `session` (two sessions before the file); the band itself is the price band
             # MCX applied on `band_applies_to` — never "today's band" (wave 1d)
             "session": b_sess.isoformat() if b_sess else None,
             "session_label": gp.session_label(b_sess) if b_sess else None,
             "band_applies_to": gp.band_applies_to(published).isoformat() if published else None,
             "quality": "band_proxy",
             "source": f"ICICI price-band midpoint ({published.isoformat() if published else '—'} master)"}
            if row else None)
    quote = breeze["quote"]
    vw = settle.get("vwap30") or {}
    if (isinstance(quote, dict) and quote.get("previous_close") is None and vw.get("last_close")
            and settle.get("latest_session") == gp.previous_session(now.date()).isoformat()):
        # the previous session's last 1-minute close from the same Breeze read as the settlement (5 Nov review: '—')
        quote = {**quote, "previous_close": vw["last_close"],
                 "previous_close_source": f"last 1-minute close of the {settle.get('latest_session_label')} (Breeze)"}
    best = None
    if breeze["available"] and breeze["quote"].get("ltp"):
        best = {"price": breeze["quote"]["ltp"], "source": breeze["quote"]["source"]}
    elif fair and fair.get("fair"):
        best = {"price": fair["fair"], "source": "fair value (COMEX × USD/INR model)"}
    elif settle.get("settlement"):
        best = {"price": settle["settlement"],
                "source": f"{settle.get('settlement_session_label')} ({str(settle.get('settlement_quality')).replace('_', ' ')})"}
    payload: dict[str, Any] = {
        "as_of": now.isoformat(timespec="seconds"),
        "contract": code, "expiry": exp.isoformat(), "expiry_source": exp_source,
        "tick_value": spec.tick_value, "lot": spec.as_dict()["lot"],
        "available": breeze["available"], "quote": quote,
        "fallbacks": {"band": band, "fair_value": fair, "settlement": {k: settle.get(k) for k in SETTLE_KEYS}},
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
    now = datetime.now(IST)
    today = now.date()
    got = await asyncio.to_thread(_master_gold_family)
    family, published = got if got else (None, None)
    exp, _, row = _resolve_expiry(code, today, asked, family)
    fair = await _fair_value(code, exp, await resolve_settlement(code, exp, row, published, now))
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


def card_margin(spec: specs.ContractSpec, settle: float | None, m: dict[str, Any] | None) -> dict[str, Any]:
    """The ONE margin rule of the contract card AND the paper ticket (5 Nov review: ticket ₹8,664 at the 6 % constant vs the
    card's ₹13,287 NRML): the stored Zerodha NRML row's ₹ per lot and % (dated) when it exists, else the indicative constant
    of shared/mcx_specs on `settle`. {margin_inr (per lot), margin_pct, margin_source, margin_date, margin_ref_price}."""
    pct = _num(m or {}, "margin_pct")
    inr = _num(m or {}, "margin_ccy")
    ref = _num(m or {}, "ref_price")
    if inr is None and pct is not None and (ref or settle):
        inr = round((ref or settle or 0) * spec.multiplier * pct / 100, 0)
    if pct is not None:
        return {"margin_inr": inr, "margin_pct": pct, "margin_source": (m or {}).get("source") or "zerodha_nrml",
                "margin_date": str((m or {}).get("trade_date") or "")[:10] or None, "margin_ref_price": ref}
    pct = spec.span_margin_pct_indicative
    return {"margin_inr": round(settle * spec.multiplier * pct / 100, 0) if settle else None, "margin_pct": pct,
            "margin_source": "indicative constant (shared/mcx_specs)", "margin_date": None, "margin_ref_price": settle}


async def _stored_margin_row(code: str, expiry: date) -> dict[str, Any] | None:
    """The stored MCX margin row the contract card reads (data-service /db/gold/margins through routers.gold's store
    cache); None when the store has none or is down."""
    try:
        from routers import gold as goldr   # late import: gold imports this module
        return await goldr.mcx_margin_row(code, expiry)
    except Exception:  # noqa: BLE001 — the ticket falls back to the card's own fallback, the indicative constant
        return None


@router.post("/ticket")
async def mcx_paper_ticket(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """PAPER pricing only — notional, tick value, margin and round-trip MCX costs for {contract, lots, price[, expiry,
    brokerage_per_order]}. Records nothing; no order API exists in this module.

    GOLD program additions (PLAN §b/§d, SOURCES.md M69; every one optional and pure arithmetic): the margin is the CONTRACT
    CARD's (`card_margin`: the stored Zerodha NRML ₹ per lot × lots, dated, for the contract's expiry — `expiry` in the body,
    else the front by OI as /quote resolves it; the indicative constant only when nothing is stored); an explicit
    `margin_pct` (+ `margin_source`, `margin_date`) still overrides; `atr14_rupees` + `account_inr` + `risk_pct` →
    `max_lots_at_risk_pct` (account × risk % ÷ (1.5 × ATR₁₄ × multiplier)), `usdinr` → `hedge_usdinr_lots` (notional in $ ÷
    the $1,000 USDINR futures lot)."""
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
    asked: date | None = None
    if payload.get("expiry"):
        try:
            asked = date.fromisoformat(str(payload["expiry"])[:10])
        except ValueError:
            fail(422, "invalid", "expiry must be YYYY-MM-DD")
    spec = contract_specs()[code]
    costs = spec_costs(code, price, lots, brokerage_per_order=brokerage)
    notional = price * spec.multiplier * lots
    margin_ref: float | None = None
    if opt["margin_pct"] is not None:
        margin_pct = opt["margin_pct"]
        margin_source = str(payload.get("margin_source") or "zerodha_nrml")
        margin_date = payload.get("margin_date")
        margin_total = round(notional * margin_pct / 100, 0)
        margin_basis = "the margin % you entered × notional"
        exp = asked
    else:
        got = await asyncio.to_thread(_master_gold_family)
        family = got[0] if got else None
        exp, _, row = _resolve_expiry(code, datetime.now(IST).date(), asked, family)
        card = card_margin(spec, (row or {}).get("settlement") or price, await _stored_margin_row(code, exp))
        margin_pct, margin_source, margin_date = card["margin_pct"], card["margin_source"], card["margin_date"]
        margin_ref = card["margin_ref_price"]
        if card["margin_date"] and card["margin_inr"] is not None:
            margin_total = round(card["margin_inr"] * lots, 0)       # the card's ₹ per lot, exactly (one source)
            margin_basis = f"the contract card's NRML ₹ per lot × {lots} (at its reference price)"
        else:
            margin_total = round(notional * margin_pct / 100, 0)
            margin_basis = "indicative % × notional (no stored NRML margin)"
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
        "indicative_margin": margin_total,
        "margin_pct_indicative": margin_pct,
        "margin_source": margin_source,
        "margin_date": margin_date,
        "margin_expiry": exp.isoformat() if exp else None,
        "margin_ref_price": margin_ref,
        "margin_basis": margin_basis,
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
