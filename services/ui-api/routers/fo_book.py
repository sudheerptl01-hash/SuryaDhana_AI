"""The PAPER F&O book (Terminal v2 PLAN 2.2 / review M40, W2-BOOK, 6 Nov 2026): legs → positions → marks → Greeks → risk.

Routes (mounted at ``/api/options/book``):
  GET  ""  (alias ``/list``)   structures + positions with their latest mark and P&L
  POST ""                      "Book paper" from OSTR: write the legs as one named structure (PAPER ONLY)
  POST /close                  close positions (or a whole structure) at the current mark (or a typed price, labelled)
  POST /roll                   roll positions to another expiry (± a strike shift) at the target chain's prices;
                               ``preview: true`` prices it and writes nothing
  GET  /marks                  each open position's mark: NSE's live chain in session, else the stored EOD chain (the
                               F&O bhavcopy close the IV surface is computed from); EOD marks are stored, append-only
  POST /mark                   store today's EOD marks (idempotent; for the evening scheduler)
  GET  /greeks                 net Δ Γ Θ ν per underlying and total, in units, lots, ₹ per 1 % and ₹ per vol point
  GET  /journal                the append-only action log
The RSK F&O section reads ``risk_payload`` through ``GET /api/risk/fo`` (routers/riskdash.py).

PAPER ONLY (PLAN §0.9 — binding): nothing in this module, in ``fo_book_store`` or in the OSTR router names a broker order
method; the only broker call reachable from here is ``breeze.margin_calculator`` (a read-only margin calculator, inside the
budget ledger) through ``routers.options_strategy.margin`` for the RSK margin-utilisation figure. The store's
``CHECK (mode = 'paper')`` refuses anything else at the database level, the request models accept ``mode: "paper"``
only, and ``EXECUTION_LIVE_ALLOWED`` is irrelevant here because there is no live mode to enable
(tests/test_fo_book.py proves all three, with negative controls). Nothing here feeds the Decision Desk, the S1 shadow, a
directional alert or a ticket price.

Marks (point-in-time): the price is the chain's (bhavcopy close, or NSE's settlement price where the contract did not
trade; in session NSE's live chain, ≈ 1 min behind, never called LIVE); the IV is implied from that price by Black-76 on
the chain's put-call-parity forward at the book's time convention (calendar time to the expiry's 15:30 IST close / 365);
a strike outside the chain's window is a `model` mark (Black-76 at the nearest strike's IV, badge heuristic). An expired
contract is valued at NSE's final settlement, point-in-time: intrinsic on the underlying's close ON the expiry day (the
expiry-day chain's underlying price, kept with the stored EOD marks, else the underlying's stored close on that date),
never a later spot; until that close is stored it shows its last stored mark as `expired-unsettled` and cannot be closed
at it (review, 6 Nov). POST /mark settles such legs (status closed, exit source "NSE final settlement …"). Every read is
data-service over 127.0.0.1; no Yahoo. In session the live chain read reaches NSE through data-service's paced client
(cached 30 s there, 60 s here); after the close only stored data is read.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # services/ui-api
for _p in (Path(__file__).resolve().parents[3],):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import fo_book_store as fbs                                    # noqa: E402
import options_math as om                                      # noqa: E402
import risk_math as rm                                         # noqa: E402
from cache import TTLCache                                     # noqa: E402
from errors import fail                                        # noqa: E402
from routers import options_strategy as osr                    # noqa: E402

from shared.http_client import UpstreamError, get_json         # noqa: E402

router = APIRouter()

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
EXPIRY_CLOSE = time(15, 30)
R_DEFAULT = om.R_DEFAULT
CAPITAL_ENV = "PAPER_FO_CAPITAL"
DEFAULT_CAPITAL = 1_000_000.0
BADGE_ARITH, BADGE_HEURISTIC, BADGE_CONTEXT = "arithmetic", "heuristic", "context"
# Review M04 (settled 6 Nov by V-VOL): ONE time convention app-wide, data-service fo_iv.black76.TIME_CONVENTION
# 'cal365-1530' (mirrored by options_math.TIME_CONVENTION / options_math.t_years): T = calendar time from the mark to
# 15:30 IST on the expiry day ÷ 365, no half-day. An EOD mark values at its session's own 15:30 close (whole days, the
# chain's `t_days`); a session mark at the live chain's clock (fractional). The book's IV for a contract is then the
# chain's IV (the same number once per page). OSTR sends the chain's `t_days` (ui/components/fobook/ostrModel.ts legDays).
TIME_CONVENTION = (f"{om.TIME_CONVENTION}: calendar time from the mark to the expiry's 15:30 IST close ÷ 365, no half-day "
                   "(review M04: the app-wide rule of the IV store, the OMON chain and OSTR)")
VAR_LOOKBACK = 750
IV_SHOCKS = (-5.0, -2.0, 2.0, 5.0, 10.0)
GAPS = (-10.0, -5.0, -3.0, -2.0, 2.0, 3.0, 5.0)
COMBINED = ((-5.0, 5.0), (-10.0, 10.0), (5.0, -2.0))      # (spot %, IV pts): a gap with the vol move that usually comes with it
INDEX_HISTORY = {"NIFTY": ("NIFTY 50", "NIFTY50"), "BANKNIFTY": ("NIFTY BANK", "NIFTYBANK"),
                 "FINNIFTY": ("NIFTY FINANCIAL SERVICES", None), "MIDCPNIFTY": ("NIFTY MIDCAP SELECT", None),
                 "NIFTYNXT50": ("NIFTY NEXT 50", None)}
PAPER_NOTE = "PAPER ONLY: a paper book in ui-api's SQLite; no order route exists for F&O and none is reachable from here"
DESCRIBES = "describes, does not predict"
SETTLEMENT = "settlement"                     # an expired contract at NSE's final settlement (expiry-day underlying close)
UNSETTLED = "expired-unsettled"               # expired, its expiry-day close not stored yet: shown, never closed at

_chain_cache = TTLCache("fo_book.chain", max_items=64, default_ttl=60.0)
_margin_cache = TTLCache("fo_book.margin", max_items=64, default_ttl=600.0)
_history_cache = TTLCache("fo_book.history", max_items=64, default_ttl=1800.0)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# request models
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


class BookLegIn(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["CE", "PE", "FUT", "EQ"]
    strike: float | None = Field(None, gt=0)
    expiry: date = Field(..., description="the contract's expiry, from the chain (never assumed)")
    premium: float = Field(..., ge=0, description="the paper fill: option premium / futures price, ₹ per unit")
    iv: float | None = Field(None, gt=0, le=500)
    lots: int = Field(1, ge=1, le=10_000)
    lot_size: int = Field(..., ge=1, le=100_000)
    forward: float | None = Field(None, gt=0, description="the chain forward of this leg's expiry at booking")
    price_source: str = Field("OSTR legs as shown", max_length=160, description="where the fill came from (chain + date / edited)")


class BookIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30)
    name: str | None = Field(None, max_length=80)
    legs: list[BookLegIn] = Field(..., min_length=1, max_length=osr.MAX_LEGS)
    note: str | None = Field(None, max_length=300)
    source: str = Field("OSTR", max_length=40)
    mode: str = Field("paper", max_length=10, description="always 'paper' — the book has no live mode")


Price = Annotated[float, Field(ge=0, le=10_000_000)]


class PreviewFill(BaseModel):
    """A fill the preview showed, confirmed as shown (the page sends it back so CONFIRM fills at what the owner saw)."""
    price: Price
    source: str = Field(..., min_length=1, max_length=300)


class RollFill(BaseModel):
    close_at: Price
    close_source: str = Field(..., min_length=1, max_length=300)
    open_at: Price
    open_source: str = Field(..., min_length=1, max_length=300)


class CloseIn(BaseModel):
    position_ids: list[int] | None = Field(None, max_length=200)
    structure_id: int | None = None
    prices: dict[int, Price] | None = Field(None, description="typed exit prices by position id, ≥ 0 (labelled 'edited')")
    confirm: dict[int, PreviewFill] | None = Field(None, description="the previewed fills, confirmed as shown (labelled)")
    previewed_at: str | None = Field(None, max_length=40, description="the preview's as_of (printed in the fill's source)")
    mark_mode: Literal["auto", "eod", "live"] = "auto"
    preview: bool = False
    mode: str = Field("paper", max_length=10)


class RollIn(BaseModel):
    position_ids: list[int] = Field(..., min_length=1, max_length=8)
    to_expiry: date
    strike_shift: float = Field(0.0, ge=-100_000, le=100_000, description="points added to each option strike")
    confirm: dict[int, RollFill] | None = Field(None, description="the previewed roll prices, confirmed as shown (labelled)")
    previewed_at: str | None = Field(None, max_length=40)
    mark_mode: Literal["auto", "eod", "live"] = "auto"
    preview: bool = True
    mode: str = Field("paper", max_length=10)


def _paper_only(mode: str) -> None:
    """The book has exactly one mode. Anything else is refused — EXECUTION_LIVE_ALLOWED does not open a live path here."""
    if (mode or "").strip().lower() != "paper":
        fail(422, "invalid", f"mode {mode!r} refused: {PAPER_NOTE}", "the paper F&O book only takes mode 'paper'")


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# pure helpers (time, IV, Greeks, P&L)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def now_ist() -> datetime:
    return datetime.now(IST)


def session_open(now: datetime) -> bool:
    n = now.astimezone(IST)
    return n.weekday() < 5 and SESSION_OPEN <= n.time() <= SESSION_CLOSE


def t_days(expiry: date | str, as_of: datetime) -> float:
    """Calendar days from ``as_of`` to 15:30 IST on the expiry day, never negative: exactly fo_iv.black76.t_years × 365
    (TIME_CONVENTION 'cal365-1530', no half-day); ``options_math.t_years`` turns it into years."""
    exp = date.fromisoformat(str(expiry)[:10])
    close = datetime.combine(exp, EXPIRY_CLOSE, IST)
    return max(0.0, (close - as_of.astimezone(IST)).total_seconds() / 86400.0)


def eod_as_of(d: str) -> datetime:
    return datetime.combine(date.fromisoformat(d[:10]), EXPIRY_CLOSE, IST)


def implied_vol(kind: str, price: float, f: float, k: float, t_years: float, r: float = R_DEFAULT) -> float | None:
    """Black-76 IV (percent) by bisection; None below the discounted intrinsic or at expiry."""
    if t_years <= 0 or price <= 0 or f <= 0 or k <= 0:
        return None
    df = math.exp(-r * t_years)
    intrinsic = df * (max(f - k, 0.0) if kind == "CE" else max(k - f, 0.0))
    if price <= intrinsic + 1e-9:
        return None
    lo, hi = 0.005, 5.0
    if om.black76(kind, f, k, t_years, hi, r).price < price:   # type: ignore[arg-type]
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if om.black76(kind, f, k, t_years, mid, r).price < price:  # type: ignore[arg-type]
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return round((lo + hi) / 2 * 100.0, 4)


def _sign(pos: dict[str, Any]) -> int:
    return 1 if pos["side"] == "buy" else -1


def _qty(pos: dict[str, Any]) -> int:
    return int(pos["lots"]) * int(pos["lot_size"])


def _om_leg(pos: dict[str, Any], premium: float | None = None) -> om.Leg:
    return om.Leg(side=pos["side"], kind=pos["kind"], strike=pos.get("strike") if pos["kind"] != "FUT" else None,
                  premium=float(pos["entry_price"] if premium is None else premium), lots=int(pos["lots"]), lot_size=int(pos["lot_size"]))


def leg_costs(pos: dict[str, Any], price: float, which: Literal["entry", "exit"]) -> float:
    """One side's statutory F&O cost for this leg at ``price`` (options_math's schedule, labelled estimate)."""
    return float(om.costs_estimate([_om_leg(pos, price)])[which])


def position_greeks(pos: dict[str, Any], mark: dict[str, Any] | None, r: float = R_DEFAULT) -> dict[str, float]:
    """Signed ₹-space Greeks of one position at its mark: delta / gamma in units of the underlying, theta ₹ per calendar
    day, vega ₹ per vol point; plus ₹ per 1 % move (delta × F × 1 %) and the gamma P&L of a 1 % move (½ Γ (F · 1 %)²)."""
    q = _sign(pos) * _qty(pos)
    f = float((mark or {}).get("forward") or pos.get("entry_forward") or (mark or {}).get("price") or 0.0)
    zero = {"delta": 0.0, "gamma": 0.0, "theta_day": 0.0, "vega": 0.0, "delta_inr_per_1pct": 0.0, "gamma_pnl_1pct_inr": 0.0}
    if (mark or {}).get("mark_method") in (SETTLEMENT, UNSETTLED):          # expired: settled in cash, no exposure left
        return zero
    if pos["kind"] == "FUT":
        ref = float((mark or {}).get("price") or f or pos["entry_price"])
        return {**zero, "delta": float(q), "delta_inr_per_1pct": q * ref * 0.01}
    t = float((mark or {}).get("t_days") or 0.0)
    iv = (mark or {}).get("iv") or pos.get("entry_iv")
    if f <= 0 or t <= 0 or not iv:
        intrinsic_delta = 0.0
        if f > 0:
            k = float(pos["strike"])
            intrinsic_delta = (1.0 if f > k else 0.0) if pos["kind"] == "CE" else (-1.0 if f < k else 0.0)
        return {**zero, "delta": intrinsic_delta * q, "delta_inr_per_1pct": intrinsic_delta * q * f * 0.01}
    g = om.black76(pos["kind"], f, float(pos["strike"]), om.t_years(t), float(iv) / 100.0, r)
    return {"delta": g.delta * q, "gamma": g.gamma * q, "theta_day": g.theta_day * q, "vega": g.vega * q,
            "delta_inr_per_1pct": g.delta * q * f * 0.01, "gamma_pnl_1pct_inr": 0.5 * g.gamma * q * (f * 0.01) ** 2}


GREEK_SUM_KEYS = ("delta", "gamma", "theta_day", "vega", "delta_inr_per_1pct", "gamma_pnl_1pct_inr")


def aggregate_greeks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per underlying (units are meaningful within one underlying) and a total in ₹ terms only (units of different
    underlyings never add)."""
    by: dict[str, dict[str, Any]] = {}
    for row in rows:
        u = by.setdefault(row["symbol"], {"symbol": row["symbol"], "lot_size": row["lot_size"], "positions": 0,
                                          **{k: 0.0 for k in GREEK_SUM_KEYS}, "forward": row.get("forward")})
        u["positions"] += 1
        for k in GREEK_SUM_KEYS:
            u[k] += float(row["greeks"][k])
    for u in by.values():
        u["delta_lots"] = u["delta"] / u["lot_size"] if u["lot_size"] else None
        for k in (*GREEK_SUM_KEYS, "delta_lots"):
            if u[k] is not None:
                u[k] = round(u[k], 6)
    total = {k: round(sum(u[k] for u in by.values()), 2) for k in ("theta_day", "vega", "delta_inr_per_1pct", "gamma_pnl_1pct_inr")}
    return {"by_underlying": sorted(by.values(), key=lambda u: u["symbol"]), "total": total,
            "total_note": "₹ terms only: ₹ per 1 % assumes every underlying moves 1 % together; vega assumes a parallel 1-pt IV move "
                          "across underlyings — units of different underlyings never add"}


def position_pnl(pos: dict[str, Any], mark_price: float | None) -> dict[str, Any]:
    q = _sign(pos) * _qty(pos)
    entry = float(pos["entry_price"])
    if pos["status"] == "open":
        gross = None if mark_price is None else q * (float(mark_price) - entry)
        costs = float(pos.get("entry_costs") or 0.0)
        return {"unrealised": None if gross is None else round(gross, 2), "realised": 0.0, "costs": round(costs, 2),
                "net": None if gross is None else round(gross - costs, 2)}
    gross = q * (float(pos["exit_price"]) - entry)
    costs = float(pos.get("entry_costs") or 0.0) + float(pos.get("exit_costs") or 0.0)
    return {"unrealised": 0.0, "realised": round(gross, 2), "costs": round(costs, 2), "net": round(gross - costs, 2)}


def structure_summary(struct: dict[str, Any], marks: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Entry credit / debit, P&L (gross, costs, net), max profit / loss at expiry for a single-expiry structure, the share of
    the max profit captured and the loss as a multiple of the credit (arithmetic; the review's adjustment frameworks read
    these, the page never acts on them)."""
    legs = struct["positions"]
    entry_cash = sum(-_sign(p) * float(p["entry_price"]) * _qty(p) for p in legs if p["kind"] != "FUT")
    unreal = real = costs = 0.0
    complete = True
    for p in legs:
        mk = marks.get(int(p["id"]))
        pnl = position_pnl(p, mk["price"] if mk else None)
        if pnl["unrealised"] is None:
            complete = False
        unreal += pnl["unrealised"] or 0.0
        real += pnl["realised"]
        costs += pnl["costs"]
    gross = unreal + real
    original = [p for p in legs if p.get("rolled_from") is None]
    expiries = {p["expiry"] for p in original if p["kind"] != "FUT"}
    max_p = max_l = None
    if original and len(expiries) <= 1:
        prof, loss = om.max_profit_loss([_om_leg(p) for p in original])
        max_p = {"value": prof.value, "unbounded": prof.unbounded}
        max_l = {"value": loss.value, "unbounded": loss.unbounded}
    captured = (round(gross / max_p["value"] * 100.0, 1) if max_p and not max_p["unbounded"] and max_p["value"]
                and max_p["value"] > 0 else None)
    loss_x_credit = round(-gross / entry_cash, 2) if entry_cash > 0 and gross < 0 else None
    open_legs = [p for p in legs if p["status"] == "open"]
    near = min((p["expiry"] for p in open_legs), default=None)
    return {"entry_cashflow": round(entry_cash, 2), "net_label": "CREDIT" if entry_cash > 0 else "DEBIT" if entry_cash < 0 else "FLAT",
            "pnl_gross": round(gross, 2), "pnl_unrealised": round(unreal, 2), "pnl_realised": round(real, 2),
            "costs": round(costs, 2), "pnl_net": round(gross - costs, 2), "marks_complete": complete,
            "max_profit": max_p, "max_loss": max_l, "pct_of_max_profit": captured, "loss_x_credit": loss_x_credit,
            "nearest_expiry": near, "open_legs": len(open_legs), "badge": BADGE_ARITH}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# chains and marks (data-service over 127.0.0.1 only)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


async def fetch_chain(symbol: str, expiry: str, live: bool) -> dict[str, Any]:
    """The stored EOD chain (F&O bhavcopy) or NSE's live chain through data-service, cached 60 s / 600 s."""
    key = f"{'live' if live else 'eod'}|{symbol}|{expiry}"
    hit = _chain_cache.get(key)
    if hit is not None:
        return hit
    path = f"/db/option-chain-live/{symbol}" if live else f"/db/option-chain/{symbol}"
    body = await get_json(f"{DATA_SVC}{path}", route="read", params={"expiry": expiry})
    if not isinstance(body, dict):
        raise UpstreamError(502, f"{path}: not a JSON object")
    _chain_cache.set(key, body, ttl=60.0 if live else 600.0)
    return body


def _parse_live_as_of(raw: Any, fallback: datetime) -> datetime:
    s = str(raw or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:20], fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=IST)
    except ValueError:
        return fallback


def monthly_expiries(expiries: list[str]) -> list[str]:
    """The last listed expiry of each calendar month (NSE's monthly contracts, the futures' expiries)."""
    by_month: dict[str, str] = {}
    for e in sorted(expiries):
        by_month[e[:7]] = e
    return sorted(by_month.values())


def _chain_t_days(pos: dict[str, Any], chain: dict[str, Any], when: datetime) -> float:
    """The chain's own T for ITS expiry (`t_days`, cal365-1530: whole days at end of day, fractional in session) when it
    carries one, else the same rule computed here — so the book's IV for a contract is the chain's."""
    ct = chain.get("t_days")
    if isinstance(ct, (int, float)) and not isinstance(ct, bool) and math.isfinite(ct) and ct >= 0:
        return float(ct)
    return t_days(pos["expiry"], when)


def settlement_value(kind: str, strike: float | None, underlying_close: float) -> float:
    """NSE's final settlement per unit on the expiry day: an option's intrinsic value on the underlying's closing price
    (index options: the index close; stock options settle physically, the same value in cash terms), a future at that
    closing price."""
    if kind == "FUT":
        return float(underlying_close)
    k = float(strike or 0.0)
    return max(underlying_close - k, 0.0) if kind == "CE" else max(k - underlying_close, 0.0)


def settlement_costs(pos: dict[str, Any], price: float) -> float:
    """Costs of settling at expiry: STT on the settlement (intrinsic) value of a LONG in-the-money option exercised
    (0.125 %, options_strategy.EXERCISE_STT_PCT); nothing for a short or worthless option or a future."""
    if pos["kind"] == "FUT" or pos["side"] != "buy" or price <= 0:
        return 0.0
    return round(price * _qty(pos) * osr.EXERCISE_STT_PCT / 100.0, 2)


def settlement_mark(pos: dict[str, Any], close: float, source: str) -> dict[str, Any]:
    """The settled mark of an expired contract: valued at its expiry day's 15:30 close (point-in-time), t = 0."""
    exp = str(pos["expiry"])[:10]
    what = "the underlying close" if pos["kind"] == "FUT" else "intrinsic on the underlying close"
    return {"position_id": int(pos["id"]), "kind": "eod", "as_of": eod_as_of(exp).isoformat(timespec="seconds"), "mark_date": exp,
            "price": round(settlement_value(pos["kind"], pos.get("strike"), float(close)), 2), "iv": None, "forward": float(close),
            "spot": float(close), "t_days": 0.0, "mark_method": SETTLEMENT, "settled": True,
            "price_source": f"NSE final settlement {exp}: {what} {float(close):,.2f} ({source})"}


def mark_from_chain(pos: dict[str, Any], chain: dict[str, Any], *, live: bool, as_of: datetime) -> dict[str, Any] | None:
    """One position's mark from a chain payload of ITS expiry (None when the chain is for another expiry). The end-of-day
    chain dated the expiry day itself values the contract at NSE's final settlement on that chain's underlying price."""
    if not chain.get("found", True) or str(chain.get("expiry") or "")[:10] != str(pos["expiry"])[:10]:
        return None
    fwd = chain.get("forward") or chain.get("future") or chain.get("spot")
    spot = chain.get("spot")
    when = as_of if live else eod_as_of(str(chain.get("date")))
    td = _chain_t_days(pos, chain, when)
    if not live and str(chain.get("date") or "")[:10] == str(pos["expiry"])[:10] and spot:     # the expiry day's own file
        return settlement_mark(pos, float(spot), f"NSE F&O bhavcopy {chain.get('date')}: the underlying price on the expiry day")
    src = (f"NSE option chain in session (≈1 min behind) {when.strftime('%H:%M:%S')} IST" if live
           else f"NSE F&O bhavcopy {chain.get('date')} (close; settlement price where untraded)")
    base = {"position_id": int(pos["id"]), "kind": "session" if live else "eod",
            "as_of": when.isoformat(timespec="seconds"), "mark_date": when.date().isoformat(),
            "forward": fwd, "spot": spot, "t_days": round(td, 6), "price_source": src}
    if pos["kind"] == "FUT":
        monthlies = monthly_expiries(list(chain.get("expiries") or []))
        near_monthly = monthlies[0] if monthlies else None
        if chain.get("future") and str(pos["expiry"])[:10] == near_monthly:
            return {**base, "price": float(chain["future"]), "iv": None, "mark_method": "future"}
        if fwd:
            return {**base, "price": float(fwd), "iv": None, "mark_method": "parity-forward",
                    "price_source": src + " · the expiry's put-call-parity forward (no traded future for it in the payload)"}
        return None
    rows = chain.get("rows") or []
    k = float(pos["strike"])
    side = "ce" if pos["kind"] == "CE" else "pe"
    row = next((r for r in rows if abs(float(r.get("strike") or 0) - k) < 1e-6), None)
    price = (row or {}).get(side, {}).get("price") if row else None
    if price is not None and fwd:
        iv = implied_vol(pos["kind"], float(price), float(fwd), k, om.t_years(td))
        if iv is None:
            iv = (row or {}).get(side, {}).get("iv")
        return {**base, "price": float(price), "iv": iv, "mark_method": "close" if not live else "live"}
    if not fwd or not rows:
        return None
    near_row = min(rows, key=lambda r: abs(float(r.get("strike") or 0) - k))
    near_iv = (near_row.get(side) or {}).get("iv") or (near_row.get("ce" if side == "pe" else "pe") or {}).get("iv") or chain.get("atm_iv")
    if not near_iv:
        return None
    model = om.black76(pos["kind"], float(fwd), k, om.t_years(td), float(near_iv) / 100.0).price
    return {**base, "price": round(model, 2), "iv": float(near_iv), "mark_method": "model",
            "price_source": src + f" · strike outside the chain's window: Black-76 at the nearest strike's IV ({near_iv} %)"}


async def underlying_close_on(symbol: str, day: str) -> tuple[float | None, str | None]:
    """The underlying's close ON ``day`` and never another day (the final settlement price of an expiry): NSE's daily
    index file for the indices (market_index_daily as the fallback), the bhavcopy close for stocks. data-service only;
    a hit is cached 30 min, a miss 5 min."""
    key = f"close|{symbol}|{day}"
    hit = _history_cache.get(key)
    if hit is not None:
        return hit
    span = max(15, (now_ist().date() - date.fromisoformat(day)).days + 10)
    attempts: list[tuple[str, dict[str, Any], str]] = []
    if symbol in INDEX_HISTORY:
        nse_name, legacy = INDEX_HISTORY[symbol]
        attempts.append((f"/db/index-ohlc/{nse_name}", {"days": span}, f"index_ohlc_daily {nse_name}"))
        if legacy:
            attempts.append(("/db/index-daily", {"symbol": legacy, "days": span}, f"market_index_daily {legacy}"))
    else:
        attempts.append((f"/db/security/{symbol}/history", {"days": min(span, 3700)}, "NSE bhavcopy close"))
    for path, params, src in attempts:
        try:
            body = await get_json(f"{DATA_SVC}{path}", route="read", params=params)
        except UpstreamError:
            continue
        for r in (body.get("rows") or []) if isinstance(body, dict) else []:
            if str(r.get("date"))[:10] == day and r.get("close"):
                out: tuple[float | None, str | None] = (float(r["close"]), f"{src} {day}")
                _history_cache.set(key, out)
                return out
    _history_cache.set(key, (None, None), ttl=300.0)
    return None, None


async def settle_expired(positions: list[dict[str, Any]], meta: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Expired, unclosed contracts that no chain lists any more, valued point-in-time at NSE's final settlement — the
    underlying's close ON the expiry day, never a later spot:
      1. the expiry-day chain's underlying price, kept with any stored EOD mark of that underlying dated the expiry day;
      2. else the underlying's close on the expiry date from data-service (``underlying_close_on``);
      3. else no settlement yet: the last stored mark on or before the expiry is shown as ``expired-unsettled``
         (heuristic) and a close at it is refused (type the price, or retry once the close is stored)."""
    store = fbs.get_store()
    out: dict[int, dict[str, Any]] = {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in positions:
        groups.setdefault((p["symbol"], str(p["expiry"])[:10]), []).append(p)
    for (sym, exp), plist in groups.items():
        stored = await asyncio.to_thread(store.eod_spot_on, sym, exp)
        close, src = (stored["spot"], f"NSE F&O bhavcopy {exp}: the underlying price, from the stored expiry-day mark") if stored else (None, None)
        if close is None:
            close, src = await underlying_close_on(sym, exp)
        if close:
            for p in plist:
                out[int(p["id"])] = {**settlement_mark(p, close, str(src)), "derived": True}
            continue
        meta["notes"].append(f"{sym} {exp}: expired, and the underlying's close on {exp} is not stored yet — no settlement; "
                             "a close needs a typed price")
        last = await asyncio.to_thread(store.latest_eod_marks, [int(p["id"]) for p in plist], through=exp)
        for p in plist:
            m = last.get(int(p["id"]))
            if m:
                out[int(p["id"])] = {**m, "mark_method": UNSETTLED, "settled": False, "derived": True,
                                     "price_source": f"expired {exp}: settlement not available yet — the last stored mark "
                                                     f"{m['mark_date']} ({m['price_source']}), not a settlement"}
    return out


async def compute_marks(positions: list[dict[str, Any]], mode: str = "auto", now: datetime | None = None,
                        ) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Marks for ``positions`` (open ones): live chain in session (auto / live), else the stored EOD chain; a failed live
    read falls back to EOD with the reason; an expired contract no chain lists is settled (``settle_expired``). Returns
    (marks by position id, meta)."""
    now = now or now_ist()
    want_live = mode == "live" or (mode == "auto" and session_open(now))
    meta: dict[str, Any] = {"requested": mode, "used": "live" if want_live else "eod", "notes": [], "chains": []}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in positions:
        if p["status"] == "open":
            groups.setdefault((p["symbol"], str(p["expiry"])[:10]), []).append(p)
    marks: dict[int, dict[str, Any]] = {}
    for (sym, exp), plist in groups.items():
        chain, live_used = None, False
        if want_live:
            try:
                chain = await fetch_chain(sym, exp, True)
                as_of = _parse_live_as_of(chain.get("as_of"), now)
                if as_of.date() != now.date():
                    meta["notes"].append(f"{sym} {exp}: the live chain is dated {as_of.date()} — NSE is not trading; end of day used")
                    chain = None
                else:
                    live_used = True
            except UpstreamError as exc:
                meta["notes"].append(f"{sym} {exp}: live chain unavailable ({str(exc)[:80]}); end of day used")
                chain = None
        if chain is None:
            try:
                chain = await fetch_chain(sym, exp, False)
            except UpstreamError as exc:
                meta["notes"].append(f"{sym} {exp}: stored chain unavailable ({str(exc)[:80]})")
                continue
        meta["chains"].append({"symbol": sym, "expiry": exp, "served_expiry": chain.get("expiry"), "date": chain.get("date"),
                               "live": live_used, "as_of": chain.get("as_of")})
        as_of = _parse_live_as_of(chain.get("as_of"), now) if live_used else now
        for p in plist:
            m = mark_from_chain(p, chain, live=live_used, as_of=as_of)
            if m is not None:
                marks[int(p["id"])] = m
    expired = [p for p in positions if p["status"] == "open" and int(p["id"]) not in marks
               and date.fromisoformat(str(p["expiry"])[:10]) < now.date()]
    if expired:
        marks.update(await settle_expired(expired, meta))
    if want_live and not any(c["live"] for c in meta["chains"]):
        meta["used"] = "eod"
    return marks, meta


async def marks_with_fallback(positions: list[dict[str, Any]], mode: str = "auto", *, store_eod: bool = True,
                              now: datetime | None = None) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """compute_marks + the stored EOD marks for live contracts the chains could not mark; chain marks (EOD, and session
    marks throttled) are appended to the store (point-in-time, idempotent). Settlements derived from stored data are
    recomputed on read, never stored; an expired contract never falls back to a mark dated after its expiry."""
    store = fbs.get_store()
    now = now or now_ist()
    marks, meta = await compute_marks(positions, mode, now)
    persist = [m for m in marks.values() if not m.get("derived") and (store_eod or m["kind"] == "session")]
    if persist:
        meta["stored"] = await asyncio.to_thread(store.add_marks, persist)
    missing = [int(p["id"]) for p in positions if p["status"] == "open" and int(p["id"]) not in marks
               and date.fromisoformat(str(p["expiry"])[:10]) >= now.date()]
    if missing:
        stored = await asyncio.to_thread(store.latest_eod_marks, missing)
        for pid, m in stored.items():
            marks[pid] = {**m, "price_source": f"{m['price_source']} (stored mark: the chain did not answer now)"}
    unmarked = [int(p["id"]) for p in positions if p["status"] == "open" and int(p["id"]) not in marks]
    if unmarked:
        meta["notes"].append(f"no mark for position(s) {', '.join(map(str, unmarked))}: P&L shows — until a chain answers")
    return marks, meta


def mark_source_chip(meta: dict[str, Any]) -> dict[str, Any]:
    """The SourceChip inputs for the book's marks: DELAYED · NSE (live chain, never LIVE) or CLOSE · <bhavcopy date>."""
    dates = sorted({str(c.get("date")) for c in meta.get("chains", []) if c.get("date")})
    live = any(c.get("live") for c in meta.get("chains", []))
    return {"state": "delayed" if live else "closed" if dates else "offline",
            "source": "NSE option chain (session)" if live else "NSE F&O bhavcopy", "as_of": dates[-1] if dates else None}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# the book payload (list / greeks)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _capital() -> dict[str, Any]:
    raw = os.environ.get(CAPITAL_ENV, "").strip()
    try:
        val = float(raw) if raw else DEFAULT_CAPITAL
    except ValueError:
        val = DEFAULT_CAPITAL
    return {"value": val, "source": f"{CAPITAL_ENV} env" if raw else f"default ₹{DEFAULT_CAPITAL:,.0f} ({CAPITAL_ENV} unset — the owner sets it)"}


def _enrich(positions: list[dict[str, Any]], marks: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in positions:
        mk = marks.get(int(p["id"])) if p["status"] == "open" else None
        g = position_greeks(p, mk) if p["status"] == "open" else {k: 0.0 for k in GREEK_SUM_KEYS}
        out.append({**p, "mark": mk, "pnl": position_pnl(p, mk["price"] if mk else None),
                    "greeks": {k: round(v, 6) for k, v in g.items()}, "forward": (mk or {}).get("forward"),
                    "days_to_expiry": round(float(mk["t_days"]), 3) if mk and mk.get("t_days") is not None else None})
    return out


async def book_payload(status: str = "open", mode: str = "auto", now: datetime | None = None) -> dict[str, Any]:
    store = fbs.get_store()
    structures = await asyncio.to_thread(store.structures, status=None if status == "all" else status)
    all_pos = [p for s in structures for p in s["positions"]]
    marks, meta = await marks_with_fallback(all_pos, mode, now=now)
    rows_by_struct = []
    for s in structures:
        legs = _enrich(s["positions"], marks)
        rows_by_struct.append({**{k: v for k, v in s.items() if k != "positions"}, "positions": legs,
                               "summary": structure_summary(s, marks)})
    open_rows = [p for s in rows_by_struct for p in s["positions"] if p["status"] == "open"]
    greeks = aggregate_greeks(open_rows)
    totals = {k: round(sum(s["summary"][k] for s in rows_by_struct), 2) for k in ("pnl_gross", "pnl_unrealised", "pnl_realised", "costs", "pnl_net")}
    return {"as_of": (now or now_ist()).isoformat(timespec="seconds"), "structures": rows_by_struct, "open_positions": len(open_rows),
            "greeks": greeks, "totals": totals, "marks_meta": meta, "mark_source": mark_source_chip(meta),
            "time_convention": TIME_CONVENTION, "capital": _capital(),
            "badges": {"pnl": BADGE_ARITH, "greeks": BADGE_ARITH, "model_marks": BADGE_HEURISTIC},
            "paper_only": True, "note": PAPER_NOTE}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# routes
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


@router.get("")
async def book_list(status: Literal["open", "closed", "all"] = "open", mode: Literal["auto", "eod", "live"] = "auto") -> dict:
    """The paper F&O book: structures, positions with their marks and P&L, net Greeks."""
    return await book_payload(status, mode)


@router.get("/list")
async def book_list_alias(status: Literal["open", "closed", "all"] = "open", mode: Literal["auto", "eod", "live"] = "auto") -> dict:
    return await book_payload(status, mode)


@router.post("")
async def book(body: BookIn) -> dict:
    """"Book paper" from OSTR: the legs become one named structure in the PAPER book (no order is placed anywhere)."""
    _paper_only(body.mode)
    if any(leg.kind == "EQ" for leg in body.legs):
        fail(422, "invalid", "shares live in the cash book (Desk / demat), not the F&O book",
             "book the option / futures legs only; the covered-call shares stay where they are")
    sym = body.symbol.strip().upper()
    legs: list[dict[str, Any]] = []
    for leg in body.legs:
        if leg.kind != "FUT" and leg.strike is None:
            fail(422, "invalid", f"a {leg.kind} leg needs a strike")
        pos = {"side": leg.side, "kind": leg.kind, "strike": leg.strike if leg.kind != "FUT" else None, "lots": leg.lots,
               "lot_size": leg.lot_size, "entry_price": leg.premium}
        legs.append({**pos, "expiry": leg.expiry.isoformat(), "entry_iv": leg.iv, "entry_forward": leg.forward,
                     "entry_price_source": leg.price_source, "entry_costs": round(leg_costs(pos, leg.premium, "entry"), 2)})
    name = (body.name or "").strip() or f"{sym} {len(legs)}-leg {min(leg['expiry'] for leg in legs)}"
    store = fbs.get_store()
    struct = await asyncio.to_thread(store.book, name=name, symbol=sym, legs=legs, source=body.source, note=body.note)
    return {"structure": struct, "paper_only": True, "note": PAPER_NOTE, "badge": BADGE_ARITH}


def _hhmm(raw: str | None) -> str:
    """'2026-11-06T10:02:31+05:30' → '10:02' (the preview's clock, IST); '' when it does not parse."""
    try:
        return datetime.fromisoformat(str(raw)).astimezone(IST).strftime("%H:%M") if raw else ""
    except ValueError:
        return ""


def _exit_price_for(pos: dict[str, Any], marks: dict[int, dict[str, Any]], typed: dict[int, float] | None,
                    confirm: dict[int, PreviewFill] | None = None, previewed_at: str | None = None) -> tuple[float, str, str]:
    """(price, source, basis): a typed price (labelled edited) > the previewed fill confirmed as shown (labelled) > the
    mark now. An expired contract whose settlement is not stored yet is never closed at its last pre-expiry mark."""
    pid = int(pos["id"])
    if typed and pid in typed:
        return float(typed[pid]), "edited by hand at close", "typed"
    if confirm and pid in confirm:
        c = confirm[pid]
        when = _hhmm(previewed_at)
        return float(c.price), f"{c.source} · confirmed as previewed{f' at {when} IST' if when else ''}", "preview"
    mk = marks.get(pid)
    if mk is None:
        fail(409, "state", f"position {pid} has no mark to close at", "type an exit price, or retry once the chain answers")
    if mk.get("mark_method") == UNSETTLED:
        fail(409, "state", f"position {pid} expired on {str(pos['expiry'])[:10]} and its settlement (the underlying's close that "
             "day) is not stored yet", "type the exit price, or retry once the expiry-day close is stored")
    return float(mk["price"]), str(mk["price_source"]), str(mk.get("mark_method") or "")


def _exit_costs(pos: dict[str, Any], price: float, basis: str, mark: dict[str, Any] | None = None) -> float:
    """An expired contract can only settle (no trade exists after expiry): only the exercise STT of a long ITM option
    applies, whatever the price basis (the mark, a confirmed preview, a typed price). Otherwise the exit side of the F&O
    statutory schedule."""
    expired = (basis == SETTLEMENT or (mark or {}).get("mark_method") in (SETTLEMENT, UNSETTLED)
               or date.fromisoformat(str(pos["expiry"])[:10]) < now_ist().date())
    return settlement_costs(pos, price) if expired else round(leg_costs(pos, price, "exit"), 2)


async def _store_write(fn: Any, *args: Any) -> Any:
    """A book write off the event loop; a refused state change (BookError: already closed by another window, unknown
    position, a negative exit price) is a 409, never a 500."""
    try:
        return await asyncio.to_thread(fn, *args)
    except fbs.BookError as exc:
        fail(409, "state", str(exc), "reload the book: another window may have closed or rolled it")


@router.post("/close")
async def close(body: CloseIn) -> dict:
    """Close positions (or a whole structure) at the current mark, or at typed prices (labelled). PAPER ONLY."""
    _paper_only(body.mode)
    store = fbs.get_store()
    if body.structure_id is not None:
        targets = await asyncio.to_thread(store.positions, status="open", structure_id=body.structure_id)
    elif body.position_ids:
        targets = await asyncio.to_thread(store.positions, status="open", ids=body.position_ids)
    else:
        fail(422, "invalid", "name the positions (position_ids) or the structure (structure_id) to close")
    if not targets:
        fail(404, "not_found", "no open position matches")
    marks, meta = await marks_with_fallback(targets, body.mark_mode)
    fills = []
    for p in targets:
        price, src, basis = _exit_price_for(p, marks, body.prices, body.confirm, body.previewed_at)
        exit_costs = _exit_costs(p, price, basis, marks.get(int(p["id"])))
        fills.append({"position_id": int(p["id"]), "exit_price": price, "exit_price_source": src, "exit_costs": exit_costs,
                      "basis": basis, "pnl": position_pnl({**p, "status": "closed", "exit_price": price, "exit_costs": exit_costs}, None)})
    as_of = now_ist().isoformat(timespec="seconds")
    if body.preview:
        return {"preview": True, "as_of": as_of, "fills": fills, "marks_meta": meta, "paper_only": True, "note": PAPER_NOTE}
    closed = await _store_write(store.close, [{k: f[k] for k in ("position_id", "exit_price", "exit_price_source", "exit_costs")}
                                              for f in fills])
    return {"preview": False, "as_of": as_of, "fills": fills, "closed": closed, "marks_meta": meta, "paper_only": True, "note": PAPER_NOTE}


@router.post("/roll")
async def roll(body: RollIn) -> dict:
    """Roll: close each position at its mark and open the same side / kind / lots on ``to_expiry`` (strike + shift) at the
    target chain's price. ``preview`` (default) prices the roll and writes nothing. PAPER ONLY."""
    _paper_only(body.mode)
    store = fbs.get_store()
    targets = await asyncio.to_thread(store.positions, status="open", ids=body.position_ids)
    if len(targets) != len(set(body.position_ids)):
        fail(404, "not_found", "every position to roll must exist and be open")
    if len({p["symbol"] for p in targets}) != 1:
        fail(422, "invalid", "roll one underlying at a time")
    sym = targets[0]["symbol"]
    to_exp = body.to_expiry.isoformat()
    if any(str(p["expiry"])[:10] == to_exp for p in targets):
        fail(422, "invalid", f"a position already expires on {to_exp}: pick another expiry to roll to")
    gone = [p for p in targets if date.fromisoformat(str(p["expiry"])[:10]) < now_ist().date()]
    if gone:
        fail(422, "invalid", f"position {gone[0]['id']} expired on {str(gone[0]['expiry'])[:10]}: it settles, it cannot be rolled",
             "close it at the settlement (POST /close), then book the new expiry from OSTR")
    marks, meta = await marks_with_fallback(targets, body.mark_mode)
    want_live = meta.get("used") == "live"
    try:
        target_chain = await fetch_chain(sym, to_exp, want_live)
    except UpstreamError as exc:
        fail(503, "upstream_down", f"the {to_exp} chain is unavailable: {str(exc)[:120]}")
    if str(target_chain.get("expiry") or "")[:10] != to_exp:
        fail(422, "invalid", f"{to_exp} is not a listed {sym} expiry", f"listed: {', '.join((target_chain.get('expiries') or [])[:8])}")
    as_of = _parse_live_as_of(target_chain.get("as_of"), now_ist()) if want_live else now_ist()
    closes: list[dict[str, Any]] = []
    opens: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    when = _hhmm(body.previewed_at)
    tag = f" · confirmed as previewed{f' at {when} IST' if when else ''}"
    for p in targets:
        exit_px, exit_src, _ = _exit_price_for(p, marks, None)
        new_strike = None if p["kind"] == "FUT" else float(p["strike"]) + body.strike_shift
        probe = {**p, "id": 0, "expiry": to_exp, "strike": new_strike}
        mk = mark_from_chain(probe, target_chain, live=want_live, as_of=as_of)
        if mk is None:
            fail(422, "invalid", f"{p['kind']} {new_strike or ''} {to_exp} is not priced by the chain")
        if mk["mark_method"] == "model":
            fail(422, "invalid", f"strike {new_strike:g} is outside the {to_exp} chain's window: no traded price to roll into")
        open_px, open_src = float(mk["price"]), str(mk["price_source"])
        seen = (body.confirm or {}).get(int(p["id"]))
        if seen is not None:                          # CONFIRM fills at the prices the preview showed, labelled as such
            exit_px, exit_src = float(seen.close_at), seen.close_source + tag
            open_px, open_src = float(seen.open_at), seen.open_source + tag
        entry_costs = round(leg_costs(probe, open_px, "entry"), 2)
        exit_costs = round(leg_costs(p, exit_px, "exit"), 2)
        q = _sign(p) * _qty(p)
        closes.append({"position_id": int(p["id"]), "exit_price": exit_px, "exit_price_source": f"roll · {exit_src}", "exit_costs": exit_costs})
        opens.append({"side": p["side"], "kind": p["kind"], "strike": new_strike, "expiry": to_exp, "lots": p["lots"],
                      "lot_size": p["lot_size"], "entry_price": open_px, "entry_iv": mk.get("iv") if seen is None else None,
                      "entry_forward": mk.get("forward"), "entry_price_source": f"roll · {open_src}", "entry_costs": entry_costs})
        rows.append({"position_id": int(p["id"]), "close_at": exit_px, "close_source": exit_src, "open_at": open_px, "open_source": open_src,
                     "new_strike": new_strike, "cash": round(q * exit_px - q * open_px, 2), "costs": round(entry_costs + exit_costs, 2)})
    net_cash = round(sum(r["cash"] for r in rows), 2)
    out = {"preview": body.preview, "as_of": now_ist().isoformat(timespec="seconds"), "symbol": sym, "to_expiry": to_exp,
           "strike_shift": body.strike_shift, "legs": rows,
           "net_cash": net_cash, "net_label": "CREDIT" if net_cash > 0 else "DEBIT" if net_cash < 0 else "FLAT",
           "costs": round(sum(r["costs"] for r in rows), 2), "marks_meta": meta, "badge": BADGE_ARITH,
           "paper_only": True, "note": PAPER_NOTE}
    if body.preview:
        return out
    done = await _store_write(store.roll, closes, opens)
    return {**out, **done}


@router.get("/marks")
async def marks(mode: Literal["auto", "eod", "live"] = "auto", history: bool = False) -> dict:
    """Each open position's current mark (and, with ``history=true``, the stored marks)."""
    store = fbs.get_store()
    positions = await asyncio.to_thread(store.positions, status="open")
    mk, meta = await marks_with_fallback(positions, mode)
    out: dict[str, Any] = {"as_of": now_ist().isoformat(timespec="seconds"), "marks": [mk[int(p["id"])] for p in positions if int(p["id"]) in mk],
                           "unmarked": [int(p["id"]) for p in positions if int(p["id"]) not in mk], "marks_meta": meta,
                           "mark_source": mark_source_chip(meta), "time_convention": TIME_CONVENTION,
                           "badges": {"close": BADGE_ARITH, "live": BADGE_ARITH, "model": BADGE_HEURISTIC, SETTLEMENT: BADGE_ARITH,
                                      UNSETTLED: BADGE_HEURISTIC},
                           "paper_only": True}
    if history:
        out["history"] = await asyncio.to_thread(store.marks, [int(p["id"]) for p in positions])
    return out


@router.post("/mark")
async def mark_eod(settle: bool = Query(True, description="close expired legs at NSE's final settlement (status closed)")) -> dict:
    """Store the EOD marks of every open position from the stored chain (idempotent: an unchanged mark is not re-written,
    a revised close is a new row) and, with ``settle`` (default), close every expired leg at NSE's final settlement — the
    exchange settles it whether or not anyone looks (exit source "NSE final settlement <expiry> …", exercise STT on a long
    ITM option). An expired leg whose expiry-day close is not stored yet stays open. For the evening scheduler after the
    20:30 chain pass; PAPER book only."""
    store = fbs.get_store()
    positions = await asyncio.to_thread(store.positions, status="open")
    mk, meta = await compute_marks(positions, "eod")
    rows = [m for m in mk.values() if not m.get("derived")]
    written = await asyncio.to_thread(store.add_marks, rows) if rows else 0
    settled: list[dict[str, Any]] = []
    if settle:
        fills = [{"position_id": int(p["id"]), "exit_price": float(mk[int(p["id"])]["price"]),
                  "exit_price_source": str(mk[int(p["id"])]["price_source"]),
                  "exit_costs": settlement_costs(p, float(mk[int(p["id"])]["price"]))}
                 for p in positions if (mk.get(int(p["id"])) or {}).get("mark_method") == SETTLEMENT]
        if fills:
            settled = await _store_write(lambda f: store.close(f, action="settle"), fills)
    return {"positions": len(positions), "marked": len(rows), "written": written, "settled": settled, "marks_meta": meta,
            "paper_only": True}


@router.get("/greeks")
async def greeks(mode: Literal["auto", "eod", "live"] = "auto") -> dict:
    """Net Δ Γ Θ ν per underlying and total (₹ terms) for the open paper book."""
    p = await book_payload("open", mode)
    return {"as_of": p["as_of"], "greeks": p["greeks"], "open_positions": p["open_positions"], "mark_source": p["mark_source"],
            "marks_meta": p["marks_meta"], "time_convention": TIME_CONVENTION, "badge": BADGE_ARITH, "paper_only": True}


@router.get("/journal")
async def journal(limit: int = Query(50, ge=1, le=500)) -> dict:
    rows = await asyncio.to_thread(fbs.get_store().journal, limit)
    return {"rows": rows, "paper_only": True}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# risk (RSK › F&O): Greeks exposure, delta-gamma VaR, vega, IV shocks, gaps, SPAN margin utilisation
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


async def underlying_returns(symbol: str, sessions: int = VAR_LOOKBACK) -> tuple[dict[str, float], str | None, str | None]:
    """Daily close-to-close returns {date: r} for an underlying: NSE's index file (index_ohlc_daily) for the indices
    (market_index_daily as the fallback), the split-adjusted bhavcopy change for stocks. (returns, source, error)."""
    key = f"{symbol}|{sessions}"
    hit = _history_cache.get(key)
    if hit is not None:
        return hit
    out: tuple[dict[str, float], str | None, str | None] = ({}, None, None)
    if symbol in INDEX_HISTORY:
        nse_name, legacy = INDEX_HISTORY[symbol]
        closes: dict[str, float] = {}
        src = None
        try:
            body = await get_json(f"{DATA_SVC}/db/index-ohlc/{nse_name}", route="read", params={"days": sessions + 5})
            closes = {str(r["date"])[:10]: float(r["close"]) for r in (body.get("rows") or []) if r.get("close")}
            src = f"index_ohlc_daily ({nse_name})"
        except UpstreamError:
            closes = {}
        if len(closes) < 60 and legacy:
            try:
                body = await get_json(f"{DATA_SVC}/db/index-daily", route="read", params={"symbol": legacy, "days": sessions + 5})
                closes = {str(r["date"])[:10]: float(r["close"]) for r in (body.get("rows") or []) if r.get("close")}
                src = f"market_index_daily ({legacy})"
            except UpstreamError as exc:
                out = ({}, None, f"{symbol}: index history unavailable ({str(exc)[:60]})")
        ds = sorted(closes)
        rets = {ds[i]: closes[ds[i]] / closes[ds[i - 1]] - 1.0 for i in range(1, len(ds)) if closes[ds[i - 1]] > 0}
        if rets:
            out = (rets, src, None)
        elif out[2] is None:
            out = ({}, None, f"{symbol}: no index history stored")
    else:
        try:
            body = await get_json(f"{DATA_SVC}/db/security/{symbol}/history", route="read", params={"days": int(sessions * 1.5) + 10})
            rets = {str(r["date"])[:10]: float(r["change_pct"]) / 100.0 for r in (body.get("rows") or []) if r.get("change_pct") is not None}
            out = (rets, "NSE bhavcopy (split-adjusted change)", None) if rets else ({}, None, f"{symbol}: no bhavcopy history")
        except UpstreamError as exc:
            out = ({}, None, f"{symbol}: bhavcopy history unavailable ({str(exc)[:60]})")
    _history_cache.set(key, out)
    return out


def revalue(rows: list[dict[str, Any]], spot_moves: dict[str, float], iv_shift: float = 0.0, days_fwd: float = 0.0,
            r: float = R_DEFAULT) -> float:
    """Full Black-76 revaluation of the open rows: each underlying's forward × (1 + move), IV + shift (floor 1 %), time
    − days_fwd. Returns the ₹ change in value against the rows' current marks."""
    pnl = 0.0
    for p in rows:
        mk = p.get("mark")
        if not mk or mk.get("mark_method") in (SETTLEMENT, UNSETTLED):   # expired: its value is fixed at the settlement
            continue
        q = _sign(p) * _qty(p)
        mv = spot_moves.get(p["symbol"], 0.0)
        if p["kind"] == "FUT":
            pnl += q * float(mk["price"]) * mv
            continue
        f = float(mk.get("forward") or 0.0)
        iv = mk.get("iv") or p.get("entry_iv")
        t_now = float(mk.get("t_days") or 0.0)
        if f <= 0 or not iv:
            continue
        k = float(p["strike"])
        t_new = max(t_now - days_fwd, 0.0)
        f_new = f * (1.0 + mv)
        if t_new <= 1e-9:
            new = max(f_new - k, 0.0) if p["kind"] == "CE" else max(k - f_new, 0.0)
        else:
            new = om.black76(p["kind"], f_new, k, om.t_years(t_new), max(float(iv) + iv_shift, 1.0) / 100.0, r).price
        if t_now <= 1e-9:
            old = max(f - k, 0.0) if p["kind"] == "CE" else max(k - f, 0.0)
        else:
            old = om.black76(p["kind"], f, k, om.t_years(t_now), float(iv) / 100.0, r).price
        pnl += q * (new - old)
    return pnl


def var_block(pnls: list[float], label: str) -> dict[str, Any]:
    v95, es95 = rm.hist_var_es(pnls, 0.95)
    v99, es99 = rm.hist_var_es(pnls, 0.99)
    rnd = (lambda x: None if x is None else round(x, 0))  # noqa: E731
    return {"method": label, "var95_1d_inr": rnd(v95), "es95_1d_inr": rnd(es95), "var99_1d_inr": rnd(v99), "es99_1d_inr": rnd(es99),
            "sessions": len(pnls)}


def margin_cache_key(symbol: str, legs: list[dict[str, Any]]) -> str:
    """The margin cache key: the contracts and their quantity only (a moving mark never busts it)."""
    ident = [[p["side"], p["kind"], p.get("strike"), str(p["expiry"])[:10], int(p["lots"]), int(p["lot_size"])] for p in legs]
    return hashlib.sha256(json.dumps([symbol.upper(), sorted(ident, key=str)]).encode()).hexdigest()


async def _margin_for(symbol: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """POST /api/options/margin's chain for this underlying's open legs, in chunks of ≤ 4 (per structure; no offset across
    chunks — stated), cached 10 min per CONTRACT SET (symbol, side, kind, strike, expiry, lots, lot size — never the mark,
    which moves with every 60 s chain refresh in session), so an RSK refresh spends at most one Breeze margin call per
    chunk every 10 minutes; the premium sent on a miss is the mark at that moment."""
    chunks: list[list[dict[str, Any]]] = []
    by_struct: dict[int, list[dict[str, Any]]] = {}
    for p in rows:
        by_struct.setdefault(int(p["structure_id"]), []).append(p)
    for legs in by_struct.values():
        for i in range(0, len(legs), osr.MAX_LEGS):
            chunks.append(legs[i:i + osr.MAX_LEGS])
    total, sources, answers = 0.0, set(), []
    for chunk in chunks:
        legs_in = [osr.MarginLegIn(side=p["side"], kind=p["kind"], strike=p.get("strike"), expiry=date.fromisoformat(str(p["expiry"])[:10]),
                                   premium=float((p.get("mark") or {}).get("price") or p["entry_price"]), lots=int(p["lots"]),
                                   lot_size=int(p["lot_size"])) for p in chunk]
        fwd = next(((p.get("mark") or {}).get("forward") for p in chunk if (p.get("mark") or {}).get("forward")), None)
        key = margin_cache_key(symbol, chunk)
        ans = _margin_cache.get(key)
        if ans is None:
            ans = await osr.margin(osr.MarginIn(symbol=symbol, legs=legs_in, forward=fwd, stock_code=None, sources="breeze,span_file,heuristic"))
            _margin_cache.set(key, ans)
        total += float(ans.get("total_margin") or 0.0)
        sources.add(str(ans.get("source_chip")))
        answers.append({"legs": [int(p["id"]) for p in chunk], "total_margin": ans.get("total_margin"), "source_chip": ans.get("source_chip"),
                        "badge": ans.get("badge"), "as_of": ans.get("as_of")})
    worst_badge = BADGE_ARITH if sources == {"BREEZE"} else BADGE_HEURISTIC
    return {"symbol": symbol, "total_margin": round(total, 2), "sources": sorted(sources), "chunks": answers, "badge": worst_badge,
            "note": "per structure, ≤ 4 legs per margin call; no SPAN offset across structures (an over-statement when they hedge)"
            if len(chunks) > 1 else "one margin call for the underlying's open legs"}


async def risk_payload(mode: str = "auto", with_margin: bool = True, now: datetime | None = None) -> dict[str, Any]:
    """RSK › F&O: Greeks exposure, delta-gamma VaR (hist-sim of the underlyings' daily moves, IV held, one day of theta)
    with the full-revaluation VaR beside it, vega, IV-shock and gap scenarios, and SPAN margin utilisation."""
    book_p = await book_payload("open", mode, now)
    rows = [p for s in book_p["structures"] for p in s["positions"] if p["status"] == "open"]
    base = {"as_of": book_p["as_of"], "open_positions": len(rows), "greeks": book_p["greeks"], "mark_source": book_p["mark_source"],
            "marks_meta": book_p["marks_meta"], "capital": book_p["capital"], "paper_only": True, "note": PAPER_NOTE,
            "badges": {"greeks": BADGE_ARITH, "var": BADGE_ARITH, "scenarios": BADGE_ARITH, "margin": BADGE_HEURISTIC}}
    if not rows:
        return {**base, "empty": True, "var": None, "scenarios": None, "margin": None,
                "message": "The paper F&O book is empty: book a structure from OSTR (\"Book paper\") to see its risk here."}
    syms = sorted({p["symbol"] for p in rows})
    hist: dict[str, dict[str, float]] = {}
    hist_src: dict[str, str | None] = {}
    notes: list[str] = []
    for s in syms:
        rets, src, err = await underlying_returns(s)
        if err:
            notes.append(err)
        if rets:
            hist[s], hist_src[s] = rets, src
    covered = [s for s in syms if s in hist]
    dates = sorted(set.intersection(*(set(hist[s]) for s in covered)))[-VAR_LOOKBACK:] if covered else []
    by_u = {u["symbol"]: u for u in book_p["greeks"]["by_underlying"]}
    theta = sum(float(u["theta_day"]) for u in by_u.values())
    dg, full = [], []
    for d in dates:
        moves = {s: hist[s][d] for s in covered}
        pnl = theta
        for s in covered:
            u = by_u[s]
            fwd = float(u.get("forward") or 0.0) or next((float((p.get("mark") or {}).get("forward") or 0) for p in rows if p["symbol"] == s), 0.0)
            dS = fwd * moves[s]
            pnl += float(u["delta"]) * dS + 0.5 * float(u["gamma"]) * dS * dS
        dg.append(pnl)
        full.append(revalue(rows, moves, 0.0, 1.0))
    var = None
    if dates:
        var = {"delta_gamma": var_block(dg, "delta-gamma: Δ·dS + ½Γ·dS² per underlying on each historical day, IV held, plus one day of theta"),
               "full_revaluation": var_block(full, "full Black-76 revaluation on each historical day, IV held, one day closer to expiry"),
               "from": dates[0], "to": dates[-1], "covered": covered, "excluded": [s for s in syms if s not in covered],
               "history_source": hist_src, "badge": BADGE_ARITH,
               "note": "historical simulation of the underlyings' daily moves (no IV history replayed): " + DESCRIBES}
    elif syms:
        notes.append("no common return history for the book's underlyings: VaR not computed")
    zero = {s: 0.0 for s in syms}
    scenarios = {
        "iv_shock": [{"iv_shift": sh, "pnl_inr": round(revalue(rows, zero, sh), 0)} for sh in IV_SHOCKS],
        "gap": [{"spot_pct": g, "pnl_inr": round(revalue(rows, {s: g / 100.0 for s in syms}), 0)} for g in GAPS],
        "combined": [{"spot_pct": g, "iv_shift": sh, "pnl_inr": round(revalue(rows, {s: g / 100.0 for s in syms}, sh), 0)} for g, sh in COMBINED],
        "theta_1d_inr": round(revalue(rows, zero, 0.0, 1.0), 0),
        "badge": BADGE_ARITH,
        "note": "instant full revaluation (every underlying gaps by the same %, IV parallel): what-if arithmetic, " + DESCRIBES,
    }
    margin: dict[str, Any] | None = None
    # an expired leg (settled, or awaiting its settlement) carries no margin: only live contracts are margined
    live_rows = [p for p in rows if (p.get("mark") or {}).get("mark_method") not in (SETTLEMENT, UNSETTLED)]
    live_syms = sorted({p["symbol"] for p in live_rows})
    if with_margin and live_syms:
        per = [await _margin_for(s, [p for p in live_rows if p["symbol"] == s]) for s in live_syms]
        total = round(sum(m["total_margin"] for m in per), 2)
        cap = float(book_p["capital"]["value"])
        margin = {"by_underlying": per, "total_margin": total, "capital": cap,
                  "utilisation_pct": round(total / cap * 100.0, 2) if cap > 0 else None,
                  "badge": BADGE_ARITH if all(m["badge"] == BADGE_ARITH for m in per) else BADGE_HEURISTIC,
                  "note": "POST /api/options/margin per underlying (BREEZE when a session is live → NSE SPAN file → the 12 % "
                          "heuristic, measured 4.8× high); utilisation = margin ÷ the paper F&O capital"}
    return {**base, "empty": False, "var": var, "scenarios": scenarios, "margin": margin, "notes": notes,
            "vega_total_inr": book_p["greeks"]["total"]["vega"], "theta_total_inr": book_p["greeks"]["total"]["theta_day"]}


__all__ = ["router", "risk_payload", "book_payload", "compute_marks", "mark_from_chain", "position_greeks", "implied_vol",
           "aggregate_greeks", "t_days", "session_open"]
