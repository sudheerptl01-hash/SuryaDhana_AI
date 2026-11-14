"""
CMDT desks — MCX SILVER and CRUDE families from the MCXG/GOLD template (FINAL ROUND R5-CMDTY).

Scope (the rating's named 9-bar item, "non-gold commodities remain thin by design"):
  * contract family selector — SILVER / SILVERM / SILVERMIC and CRUDEOIL / CRUDEOILM
  * session clock           — shared/mcx_specs (the MCX calendar is exchange-wide; silver and crude
                              are non-agri and trade the same 09:00 → 23:30/23:55 session as gold)
  * live LTP                — ICICI Breeze through the SAME degrade-first path MCXG uses
                              (routers.mcx._breeze_quote: session-aware, broken shapes remembered
                              10 min, the 1-minute-bar fallback after the open — never a retry storm)
  * specs + expiries        — static specs cross-checked against ICICI's public security master
                              (gold_preopen.mcx_master — the shared, cached loader; MCX's own site is
                              NEVER fetched, O-8), band-midpoint settlement labelled with its session
  * daily chart             — STORED rows only: data-service /db/gold/mcx/daily (gold_mcx_daily is
                              keyed (trade_date, family, expiry) and family-generic). Until the
                              gold_breeze_daily family extension is approved (patch request
                              02_breeze_daily_families), the store has no silver/crude bars and this
                              endpoint degrades honestly — it never fetches anything itself.
  * paper ticket            — the MCXG ticket mechanics (notional, indicative margin, round-trip MCX
                              costs, breakeven). PAPER: it prices the trade, records nothing, and no
                              order API is imported here.

NO fair-value model: gold's COMEX-parity machinery is gold-only (purity/duty legs). These desks show
prices and context — badges context / arithmetic / heuristic, no verdicts, no direction words.
Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.

Specs provenance (all cross-checked against the ICICI MCXScripMaster of 13 Nov 2026 — lot, quotation
unit and tick per FUTURE row; cycles read off the observed expiry rows):
  SILVER     30 kg,  ₹/kg,  tick ₹1 = ₹30/lot,  Mar/May/Jul/Sep/Dec, expiry 5th   (obs. 04-Dec-2026, 03-Sep-2027)
  SILVERM     5 kg,  ₹/kg,  tick ₹1 = ₹5/lot,   Feb/Apr/Jun/Aug/Nov, month-end    (obs. 30-Nov-2026, 26-Feb-2027)
  SILVERMIC   1 kg,  ₹/kg,  tick ₹1 = ₹1/lot,   Feb/Apr/Jun/Aug/Nov, month-end    (obs. 30-Nov-2026)
  CRUDEOIL  100 bbl, ₹/bbl, tick ₹1 = ₹100/lot, monthly, expiry 19th              (obs. 19-Nov-2026, 18-Dec-2026)
  CRUDEOILM  10 bbl, ₹/bbl, tick ₹1 = ₹10/lot,  monthly, expiry 19th              (obs. 19-Nov-2026)
Expiries move to the PREVIOUS business day when MCX is closed (shared/mcx_specs._back_to_business —
the same observed rule as gold). The exchange circular is the legal source; 'observed' rows win.
Margins: NO stored NRML mirror exists for these families (the Zerodha parser is gold-only), so the
margin is an INDICATIVE constant and is labelled heuristic everywhere it prints.
"""
from __future__ import annotations

import asyncio
import calendar as _cal
import csv
import io
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import os

from fastapi import APIRouter, Body, Query

from cache import TTLCache
from errors import degraded, fail
from routers import gold_preopen as gp
from routers import mcx as mcxr

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared import mcx_specs as specs  # noqa: E402
from shared.http_client import UpstreamError, get_json  # noqa: E402

router = APIRouter()
IST = specs.IST
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
_DB_TIMEOUT = httpx.Timeout(8.0)
_cache = TTLCache("commodity_desk", max_items=64, default_ttl=600)
QUOTE_TTL_S = 15                 # UI polls every 30 s; concurrent viewers share one broker call
DAILY_TTL_S = 300                # stored EOD bars move once a day

DESCRIBES = "describes, does not predict"
NO_FAIR_VALUE_NOTE = ("No fair-value model on this desk: gold's COMEX-parity machinery is gold-only. "
                      "Prices and context — no verdicts.")

Group = Literal["SILVER", "CRUDE"]


@dataclass(frozen=True)
class FamilySpec:
    """One MCX futures family of this desk. `multiplier` = ₹ of P&L per lot for a ₹1 quote move."""
    code: str
    name: str
    group: Group
    lot_label: str
    multiplier: float
    tick_rupees: float
    quote_unit: str
    delivery: str
    purity: str | None                 # silver 999; crude has none
    expiry_day: int | Literal["month_end"]
    months: tuple[int, ...]
    margin_pct_indicative: float       # INDICATIVE constant; no NRML mirror stored for these families
    notes: str

    @property
    def tick_value(self) -> float:
        return self.tick_rupees * self.multiplier

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "name": self.name, "group": self.group, "lot": self.lot_label,
            "multiplier": self.multiplier, "tick_rupees": self.tick_rupees,
            "tick_value": round(self.tick_value, 2), "quotation": self.quote_unit,
            "delivery_unit": self.delivery, "purity": self.purity,
            "expiry_rule": (("last calendar day of the contract month" if self.expiry_day == "month_end"
                             else f"{self.expiry_day}th of the contract month")
                            + " (previous business day if closed)"),
            "cycle": "monthly" if self.months == ALL_MONTHS else "/".join(_cal.month_abbr[m] for m in self.months),
            "span_margin_pct_indicative": self.margin_pct_indicative,
            "margin_source": MARGIN_SOURCE_LABEL,
            "notes": self.notes,
        }


ALL_MONTHS = tuple(range(1, 13))
MARGIN_SOURCE_LABEL = "indicative constant (no NRML mirror stored for this family)"

FAMILIES: dict[str, FamilySpec] = {
    "SILVER": FamilySpec("SILVER", "Silver (30 kg)", "SILVER", "30 kg", 30, 1.0, "₹ per kg", "30 kg", "999",
                         5, (3, 5, 7, 9, 12), 10.0, "The benchmark silver contract; ₹1 move = ₹30 per lot."),
    "SILVERM": FamilySpec("SILVERM", "Silver Mini (5 kg)", "SILVER", "5 kg", 5, 1.0, "₹ per kg", "5 kg", "999",
                          "month_end", (2, 4, 6, 8, 11), 10.0, "Feb/Apr/Jun/Aug/Nov, month-end expiry."),
    "SILVERMIC": FamilySpec("SILVERMIC", "Silver Micro (1 kg)", "SILVER", "1 kg", 1, 1.0, "₹ per kg", "1 kg", "999",
                            "month_end", (2, 4, 6, 8, 11), 10.0, "One-thirtieth of SILVER; month-end expiry."),
    "CRUDEOIL": FamilySpec("CRUDEOIL", "Crude Oil (100 bbl)", "CRUDE", "100 bbl", 100, 1.0, "₹ per bbl", "100 bbl", None,
                           19, ALL_MONTHS, 15.0, "Monthly; ₹1 move = ₹100 per lot. Cash-settled off the NYMEX WTI-linked DSP."),
    "CRUDEOILM": FamilySpec("CRUDEOILM", "Crude Oil Mini (10 bbl)", "CRUDE", "10 bbl", 10, 1.0, "₹ per bbl", "10 bbl", None,
                            19, ALL_MONTHS, 15.0, "One-tenth of CRUDEOIL; monthly."),
}
GROUPS: dict[Group, tuple[str, ...]] = {
    "SILVER": ("SILVER", "SILVERM", "SILVERMIC"),
    "CRUDE": ("CRUDEOIL", "CRUDEOILM"),
}

# ICICI's MCXScripMaster truncates ShortName to 6 characters (13 Nov 2026 copy): map both directions.
MASTER_ALIASES = {"SILVER": "SILVER", "SILMIN": "SILVERM", "SILMIC": "SILVERMIC",
                  "CRUDE": "CRUDEOIL", "CRUDMI": "CRUDEOILM"}
# Breeze stock_code for MCX = ICICI's short name, NOT the MCX symbol (the gold desk's verified rule).
# From the 13 Nov 2026 master; LIVE-VERIFY after the ~08:00 login, like the gold minis were (O-8).
BREEZE_CODE = {"SILVER": "SILVER", "SILVERM": "SILMIN", "SILVERMIC": "SILMIC",
               "CRUDEOIL": "CRUDE", "CRUDEOILM": "CRUDMI"}


# ── expiries (computed; observed master rows win) ─────────────────────────────────

def active_expiries(code: str, today: date, count: int = 3) -> list[date]:
    """The next `count` computed expiry dates for `code` on/after `today` (day-N or month-end, moved to
    the previous business day by the same rule as gold — shared/mcx_specs._back_to_business)."""
    spec = FAMILIES[code]
    out: list[date] = []
    y, m = today.year, today.month
    for _ in range(30):
        if m in spec.months:
            raw = (date(y, m, _cal.monthrange(y, m)[1]) if spec.expiry_day == "month_end"
                   else date(y, m, int(spec.expiry_day)))
            exp = specs._back_to_business(raw)
            if exp >= today:
                out.append(exp)
                if len(out) >= count:
                    return out
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


# ── ICICI security master (the shared cached loader; never the MCX site) ─────────

def parse_desk_families(master_text: str) -> dict[str, list[dict[str, Any]]]:
    """FUTURE rows for every family of this desk, settlement = band midpoint (ICICI's daily price band
    is symmetric around an earlier session's settlement — the same reading as the gold desk)."""
    out: dict[str, list[dict[str, Any]]] = {code: [] for code in FAMILIES}
    for r in csv.DictReader(io.StringIO(master_text), skipinitialspace=True):
        code = MASTER_ALIASES.get((r.get("ShortName") or "").strip())
        if code is None or r.get("Series") != "FUTURE":
            continue
        try:
            lo, hi = float(r["LowPriceRange"]), float(r["HighPriceRange"])
            expiry = datetime.strptime(r["ExpiryDate"], "%d-%b-%Y").date()  # noqa: DTZ007 — a calendar expiry date in the ICICI master carries no zone, and .date() drops time anyway
        except (KeyError, ValueError):
            continue
        out[code].append({"expiry": expiry, "band_low": lo, "band_high": hi,
                          "settlement": round((lo + hi) / 2, 2),
                          # ICICI's header is shifted: "MarginPercentage" carries open interest (lots)
                          "open_interest": float(r.get("MarginPercentage") or 0)})
    for rows in out.values():
        rows.sort(key=lambda c: c["expiry"])
    return out


def _master_families() -> tuple[dict[str, list[dict[str, Any]]], date] | None:
    """Parsed master + its publish date, or None (the desk still works on computed specs)."""
    try:
        master = gp.mcx_master()           # shared, stale-while-revalidate (C-PERF-01); ICICI public file
    except Exception:  # noqa: BLE001 — public file server down: degrade to computed
        return None
    hit = _cache.get("desk_families")
    if hit and hit[1] == master[1]:
        return hit[0], master[1]
    fams = parse_desk_families(master[0])
    _cache.set("desk_families", (fams, master[1]), ttl=600)
    return fams, master[1]


def _resolve_expiry(code: str, today: date, asked: date | None,
                    family: dict[str, list[dict[str, Any]]] | None) -> tuple[date, str, dict[str, Any] | None]:
    """(expiry, 'observed'|'computed'|'requested', master row if any) — the gold desk's rule."""
    rows = (family or {}).get(code) or []
    if asked:
        row = next((r for r in rows if r["expiry"] == asked), None)
        return asked, "requested", row
    live = [r for r in rows if r["expiry"] >= today]
    if live:
        best = max(live, key=lambda r: (r["open_interest"], -r["expiry"].toordinal()))
        return best["expiry"], "observed", best
    return active_expiries(code, today, count=1)[0], "computed", None


def _band_block(row: dict[str, Any] | None, published: date | None) -> dict[str, Any] | None:
    """The ICICI band-midpoint settlement, labelled with the session it really belongs to (band_proxy)."""
    if not row:
        return None
    b_sess = gp.band_session(published) if published else None
    return {"settlement": row["settlement"], "band_low": row["band_low"], "band_high": row["band_high"],
            "open_interest_lots": row["open_interest"],
            "session": b_sess.isoformat() if b_sess else None,
            "session_label": gp.session_label(b_sess) if b_sess else None,
            "band_applies_to": gp.band_applies_to(published).isoformat() if published else None,
            "quality": "band_proxy",
            "source": f"ICICI price-band midpoint ({published.isoformat() if published else '—'} master)"}


# ── costs (shared/mcx_specs rate card — CTT 0.01 % sell side applies to non-agri futures) ──

def round_trip_costs(code: str, price: float, lots: int,
                     brokerage_per_order: float = specs.DEFAULT_BROKERAGE_PER_ORDER) -> dict[str, Any]:
    spec = FAMILIES[code]
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
            "assumptions": ("both legs at the same price; squared off before expiry (CTT 0.01% sell side, "
                            f"non-agri futures); brokerage ₹{brokerage_per_order:g}/order flat; "
                            "GST on brokerage + txn + SEBI fee")}


# ── endpoints ─────────────────────────────────────────────────────────────────────

@router.get("/families")
async def desk_families(group: str | None = Query(None, description="SILVER or CRUDE; default both")) -> dict[str, Any]:
    """The desk board: session clock (shared MCX calendar), per-family specs, observed expiries with the
    band-midpoint settlement and OI ladder from ICICI's master, computed expiries, indicative margin.
    Everything labelled: context / arithmetic / heuristic — nothing here is a signal."""
    g = group.upper() if group else None
    if g is not None and g not in GROUPS:
        fail(422, "invalid", f"Unknown group '{group}'", hint="SILVER or CRUDE")
    now = datetime.now(IST)
    got = await asyncio.to_thread(_master_families)
    family, published = got if got else ({}, None)
    rows: list[dict[str, Any]] = []
    for code in (GROUPS[g] if g else [c for grp in GROUPS.values() for c in grp]):
        spec = FAMILIES[code]
        d = spec.as_dict()
        d["breeze_code"] = BREEZE_CODE[code]
        d["computed_expiries"] = [x.isoformat() for x in active_expiries(code, now.date(), count=3)]
        observed = [r for r in family.get(code, []) if r["expiry"] >= now.date()]
        d["observed_expiries"] = [{"expiry": r["expiry"].isoformat(), "open_interest_lots": r["open_interest"],
                                   "band": _band_block(r, published)} for r in observed[:4]] or None
        front = observed[0] if observed else None
        if front:
            d["front"] = _band_block(front, published) | {"expiry": front["expiry"].isoformat()}
            d["indicative_margin_rupees"] = round(front["settlement"] * spec.multiplier
                                                  * spec.margin_pct_indicative / 100, 0)
        rows.append(d)
    state = specs.session_state(now)
    state["upcoming_holidays"] = specs.upcoming_holidays(now.date(), count=6)
    return {
        "as_of": now.isoformat(timespec="seconds"),
        "group": g,
        "families": rows,
        "session": state,
        "session_note": ("Shared MCX calendar (shared/mcx_specs): silver and crude are non-agri and trade the "
                         "same 09:00 → 23:30/23:55 IST session as gold; partial holidays apply exchange-wide."),
        "master": {"available": bool(got), "published": published.isoformat() if published else None,
                   "source": "ICICI MCXScripMaster.txt (public, ~07:00 IST) — MCX's own site is never fetched"},
        "margin_note": ("SPAN+exposure margins are revised daily by MCX; the % here is an indicative constant "
                        "(heuristic) — no NRML mirror is stored for these families. For paper sizing only."),
        "fair_value_note": NO_FAIR_VALUE_NOTE,
        "badge_note": f"context / arithmetic / heuristic only — this desk {DESCRIBES}",
    }


@router.get("/quote")
async def desk_quote(contract: str = Query(...),
                     expiry: str | None = Query(None, description="YYYY-MM-DD; default = front by OI")) -> dict[str, Any]:
    """Live MCX quote via Breeze when the account can serve it (the gold desk's degrade-first path);
    otherwise an honest degrade with the one fallback that always works: the ICICI band midpoint,
    labelled with its real session. No fair-value model exists for this desk."""
    code = contract.upper()
    if code not in FAMILIES:
        fail(422, "invalid", f"Unknown desk contract '{contract}'", hint=f"One of {', '.join(FAMILIES)}")
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

    got = await asyncio.to_thread(_master_families)
    family, published = got if got else (None, None)
    exp, exp_source, row = _resolve_expiry(code, now.date(), asked, family)
    win_today = specs.trading_window(now.date())
    after_open = bool(win_today and now >= win_today[0])
    # the SAME degrade-first Breeze path as MCXG (routers.mcx._breeze_quote): session-aware, broken
    # shapes remembered 10 min, 1-minute-bar fallback after the open. The short code passes through
    # its BREEZE_CODE.get(code, code) fallback untouched.
    breeze = await asyncio.to_thread(mcxr._breeze_quote, BREEZE_CODE[code], exp, now.date(), after_open)

    spec = FAMILIES[code]
    band = _band_block(row, published)
    best = None
    if breeze["available"] and breeze["quote"].get("ltp"):
        best = {"price": breeze["quote"]["ltp"], "source": breeze["quote"]["source"]}
    elif band:
        best = {"price": band["settlement"], "source": f"{band['session_label']} (band proxy)"}
    payload: dict[str, Any] = {
        "as_of": now.isoformat(timespec="seconds"),
        "contract": code, "breeze_code": BREEZE_CODE[code],
        "expiry": exp.isoformat(), "expiry_source": exp_source,
        "tick_value": spec.tick_value, "lot": spec.lot_label, "quote_unit": spec.quote_unit,
        "available": breeze["available"], "quote": breeze["quote"],
        "fallbacks": {"band": band},
        "best": best,
        "fair_value_note": NO_FAIR_VALUE_NOTE,
    }
    if breeze["available"]:
        _cache.set(cache_key, payload, ttl=QUOTE_TTL_S)
        return payload
    payload["reason"] = breeze["reason"]
    out = degraded(payload, "degraded", breeze["reason"] or "MCX quote unavailable",
                   hint="The fallback shown is the ICICI price-band midpoint, labelled with its session")
    _cache.set(cache_key, out, ttl=QUOTE_TTL_S)
    return out


@router.get("/daily")
async def desk_daily(family: str = Query(...), expiry: str | None = Query(None),
                     days: int = Query(180, ge=10, le=400)) -> dict[str, Any]:
    """STORED daily bars of one family (data-service gold_mcx_daily — broker bars, point-in-time).
    Honest empty when the store has none: the gold_breeze_daily family extension is a PENDING patch
    request; this endpoint reads, it never fetches."""
    code = family.upper()
    if code not in FAMILIES:
        fail(422, "invalid", f"Unknown desk family '{family}'", hint=f"One of {', '.join(FAMILIES)}")
    cache_key = f"daily:{code}:{expiry or 'all'}:{days}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return hit
    params: dict[str, Any] = {"family": code,
                              "from": (datetime.now(IST).date() - timedelta(days=days)).isoformat()}
    if expiry:
        params["expiry"] = expiry
    base = {"family": code, "expiry": expiry, "quote_unit": FAMILIES[code].quote_unit,
            "source": "gold_mcx_daily (ICICI Breeze daily bars, stored by data-service)", "quality": "broker"}
    # the SHARED client (one per process, breaker + stale-serve + metrics), as fut_book.py does — F5 found this
    # handler building a fresh AsyncClient per request, which bypasses all three.
    try:
        body = await get_json(f"{DATA_SVC}/db/gold/mcx/daily", route="read", params=params)
    except UpstreamError as exc:
        status = getattr(exc, "status", None) or 503
        if status == 503:
            return degraded({**base, "rows": [], "count": 0}, "upstream_down", "data-service unreachable")
        # a 422 from a data-service whose family pattern is gold-only (by design), or any other refusal
        return degraded({**base, "rows": [], "count": 0}, "degraded",
                        f"data-service cannot serve {code} daily bars yet (HTTP {status})",
                        hint="The gold_breeze_daily family extension is a pending patch request; "
                             "the desk's quote, specs and ticket panels stand on their own")
    if not isinstance(body, dict):
        return degraded({**base, "rows": [], "count": 0}, "degraded", "data-service sent a non-JSON body")
    rows = body.get("rows") or []
    out = {**base, "rows": rows, "count": len(rows), "note": body.get("note")}
    if not rows:
        out = degraded(out, "degraded",
                       f"no stored daily bars for {code} yet",
                       hint="The gold_breeze_daily family extension (patch request) fills this table; "
                            "nothing is fetched on this path")
    _cache.set(cache_key, out, ttl=DAILY_TTL_S)
    return out


@router.post("/ticket")
async def desk_paper_ticket(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:  # noqa: B008 — FastAPI's documented body idiom, as in routers/mcx.py
    """PAPER pricing only — notional, tick value, indicative margin and round-trip MCX costs for
    {contract, lots, price[, brokerage_per_order]}. The MCXG ticket mechanics with this desk's specs:
    it records nothing and no order API is ever imported here. Arithmetic only — no view on direction."""
    code = str(payload.get("contract") or "").upper()
    if code not in FAMILIES:
        fail(422, "invalid", f"Unknown desk contract '{payload.get('contract')}'",
             hint=f"One of {', '.join(FAMILIES)}")
    try:
        lots = int(payload.get("lots") or 0)
        price = float(payload.get("price") or 0)
        brokerage = float(payload.get("brokerage_per_order", specs.DEFAULT_BROKERAGE_PER_ORDER))
    except (TypeError, ValueError):
        fail(422, "invalid", "lots must be an integer; price and brokerage_per_order numbers")
    if not (math.isfinite(price) and math.isfinite(brokerage)):
        fail(422, "invalid", "price and brokerage_per_order must be finite numbers")
    if lots < 1 or lots > 1000:
        fail(422, "invalid", "lots must be between 1 and 1000")
    if price <= 0:
        fail(422, "invalid", "price must be positive — use the price the desk shows",
             hint="Breeze LTP when live, else the band-midpoint fallback")
    if brokerage < 0 or brokerage > 10_000:
        fail(422, "invalid", "brokerage_per_order out of range")
    spec = FAMILIES[code]
    costs = round_trip_costs(code, price, lots, brokerage_per_order=brokerage)
    notional = price * spec.multiplier * lots
    margin_pct = spec.margin_pct_indicative
    return {
        "paper": True, "recorded": False,
        "contract": code, "lot": spec.lot_label, "lots": lots, "price": price,
        "quote_unit": spec.quote_unit,
        "notional": round(notional, 2),
        "tick_value_per_lot": spec.tick_value,
        "tick_value_position": round(spec.tick_value * lots, 2),
        "indicative_margin": round(notional * margin_pct / 100, 0),
        "margin_pct_indicative": margin_pct,
        "margin_source": MARGIN_SOURCE_LABEL,
        "margin_basis": "indicative % × notional (heuristic — exchange margins move daily)",
        "round_trip": costs,
        "note": ("Indicative: exchange margins move daily; costs assume a squared-off trade "
                 "(CTT 0.01% sell side, non-agri futures), flat brokerage, GST 18% on brokerage+txn+SEBI. "
                 "This ticket prices the trade — nothing is sent anywhere."),
    }
