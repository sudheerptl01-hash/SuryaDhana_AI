"""OSTR — options strategy analyzer (W3) + real SPAN margin (Terminal v2 PLAN 1.3, B3). PRICES only; never places orders.

POST /api/options/strategy/analyze: up to 4 legs (buy/sell · CE/PE/FUT · strike · lots), seeded by the UI from the
cached EOD chain (GET /api/market/option-chain/{symbol}) — no broker calls, so it works at any hour regardless of
the ICICI session. All math lives in services/ui-api/options_math.py (pure, unit-tested): Black-76 on the forward
(r = 6.5% default), exact piecewise-linear breakevens, bounded/unbounded max P&L, ₹/day theta, and margin + NSE-cost
figures that are always labelled ESTIMATE.

POST /api/options/margin (PLAN 1.3 "Real SPAN margin on OSTR"): the fallback chain, in order —
  1. BREEZE          `breeze.margin_calculator(legs, "NFO")` when the ICICI session is live, through the Breeze budget
                     ledger (shared/breeze_budget.py; refused past the cap → next source);
  2. NSE_SPAN_FILE   the NSE/NCL SPAN risk-parameter file (`nsearchives.nseindia.com/archives/nsccl/span/nsccl.YYYYMMDD.s.zip`,
                     EOD ≈ 17:02 IST; no scheduled job fetches it yet — a file placed in data/nse_archive/span/ (SPAN_ARCHIVE_DIR) is parsed here: the 16-scenario
                     risk arrays per contract → scanning risk, the intra-commodity (calendar) spread charge, the short
                     option minimum; exposure (non-SPAN) margin is NSE's published percentage, labelled as such;
  3. HEURISTIC       options_math.margin_estimate (12 % of notional per short leg + premium) — kept as the last resort
                     WITH its measured error printed: 4.8× over Breeze SPAN on the NIFTY 09-Nov-2026 iron condor
                     (₹3.9 L vs ₹81,497.07; R-OPTIONS §3.3).
The ticket shows `span_margin_required`, `non_span_margin_required` and the source chip BREEZE / NSE SPAN FILE / HEURISTIC.
Badge `arithmetic`; `paper_only: true`; nothing here routes an order.

OSTR v2 (Terminal v2 PLAN 2.2 / review M39, W2-BOOK, 6 Nov 2026) — still PRICES ONLY:
  * multi-expiry books (calendars, diagonals): each leg may carry its own `days`, `expiry` and `forward` (that expiry's
    chain forward). A spot scenario x moves every leg's forward by the same factor (F_leg · x / F_ref: the basis held
    as a ratio — stated); the "at expiry" curve of a mixed book is the NEAREST expiry, later legs valued by Black-76;
  * `scenario_days` (T+n) and `iv_shift` (vol points, parallel) → a third payoff curve `payoff[].scenario`;
  * `grid=true` → the 2-D P&L grid: spot −5 … +5 % × IV −10 … +10 pts, at a few dates up to the nearest expiry;
  * `pop` — probability of profit at the nearest expiry from the risk-neutral LOGNORMAL at one IV (no skew), badge
    `heuristic`: it restates the market's pricing — describes, does not predict;
  * costs: the itemised round trip with display items that ADD UP (stamp + SEBI + IPFT listed), the exercise STT if
    held to expiry (0.125 % of intrinsic on long ITM legs at the current forward), a bid–ask input (the chain served
    carries no bid / ask), shares (`kind: "EQ"`, a covered call on holdings) costed by shared/trading_costs.py;
  * GET / POST / DELETE /strategy/saved — save and name a structure (fo_book_store.fo_saved_structures; not a booking).
Booking legs into the PAPER F&O book is routers/fo_book.py; nothing here routes an order.

Event-loop purity: the analyzer is sync `def` (threadpool, microseconds of arithmetic); the margin route is async and
runs the Breeze call and the file parse on worker threads.
"""
from __future__ import annotations

import asyncio
import io
import math
import os
import re
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # services/ui-api
for _p in (Path(__file__).resolve().parents[3],):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from errors import fail                                        # noqa: E402
import options_math as om                                      # noqa: E402

from shared.breeze_budget import BudgetExceeded, ledger        # noqa: E402

router = APIRouter()

MAX_LEGS = 4
IST = ZoneInfo("Asia/Kolkata")
BADGE_ARITH, BADGE_HEURISTIC = "arithmetic", "heuristic"
HEURISTIC_ERROR_FACTOR = 4.8          # measured: ₹3.9 L heuristic vs ₹81,497.07 Breeze SPAN, NIFTY 09-Nov-2026 condor (R-OPTIONS §3.3)
HEURISTIC_EVIDENCE = ("measured 4.8× too high vs Breeze SPAN on the NIFTY 09-Nov-2026 iron condor (₹3.9 L vs ₹81,497.07; "
                      "R-OPTIONS §3.3) — a trader sizing from this number is under-levered by that factor")
SPAN_SCENARIOS = 16
INDEX_UNDERLYINGS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"})
EXPOSURE_PCT_INDEX, EXPOSURE_PCT_STOCK = 2.0, 3.5   # NSE exposure (non-SPAN) margin on short options / futures notional: a published rule, not the file
BREEZE_CALLER = "ui-api.margin"
SPAN_DIR_ENV = "SPAN_ARCHIVE_DIR"
SPAN_FILE_RE = re.compile(r"^nsccl\.(\d{8})\.s\.zip$")
_SPAN_PARSE_LOCK = threading.Lock()
_SPAN_CACHE: dict[tuple[str, str], Any] = {}        # (file path, pfCode) → SpanProduct (one parse per product per file)

# FINAL ROUND P0-8 ("40 s of nothing is forbidden"): the last successful BREEZE margin answer per
# (underlying, exchange, legs shape — premiums excluded: SPAN is about the contracts, and the age is always shown).
# Served instantly to `cached_only` probes and, with `stale_ok`, when Breeze fails or times out. In-process only;
# every cached serve carries `served_from_cache: true`, `cache_age_s` and the ORIGINAL `as_of` — never re-stamped.
_MARGIN_ANSWER_LOCK = threading.Lock()
_MARGIN_ANSWER_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}     # key → {"at": epoch s, "answer": response dict}
MARGIN_ANSWER_CACHE_MAX = 64


def margin_cache_key(body: "MarginIn") -> tuple[Any, ...]:
    legs = tuple(sorted((lg.side, lg.kind, float(lg.strike or 0.0), lg.expiry.isoformat(), lg.lots, lg.lot_size)
                        for lg in body.legs))
    return (body.symbol.upper(), body.exchange_code, legs)


def _margin_cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    with _MARGIN_ANSWER_LOCK:
        entry = _MARGIN_ANSWER_CACHE.get(key)
        return dict(entry) if entry else None


def _margin_cache_put(key: tuple[Any, ...], answer: dict[str, Any]) -> None:
    with _MARGIN_ANSWER_LOCK:
        if key not in _MARGIN_ANSWER_CACHE and len(_MARGIN_ANSWER_CACHE) >= MARGIN_ANSWER_CACHE_MAX:
            oldest = min(_MARGIN_ANSWER_CACHE, key=lambda k: _MARGIN_ANSWER_CACHE[k]["at"])
            _MARGIN_ANSWER_CACHE.pop(oldest, None)
        _MARGIN_ANSWER_CACHE[key] = {"at": time.time(), "answer": answer}


def reset_margin_answer_cache() -> None:
    """Tests only."""
    with _MARGIN_ANSWER_LOCK:
        _MARGIN_ANSWER_CACHE.clear()


def _cached_margin_answer(entry: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """The cached answer re-served honestly: original as_of kept, age in seconds on the face of the payload."""
    age = max(0, int(time.time() - float(entry["at"])))
    ans = dict(entry["answer"])
    ans["served_from_cache"] = True
    ans["cache_age_s"] = age
    ans["attempts"] = attempts
    ans["note"] = (str(entry["answer"].get("note", ""))
                   + " · served from this ui-api's cache of the last Breeze answer for these legs (age shown) — not re-asked")
    return ans


# ── OSTR v2 constants ─────────────────────────────────────────────────────────────────────────────────────────────
IV_FLOOR_PCT = 1.0                    # an IV shift never takes a leg's vol below 1 %
BASIS_SLOPE_TOL = 0.05                # a tail slope under 5 % of a leg's units is basis drift, not an open-ended position
EXERCISE_STT_PCT = 0.125              # STT on the intrinsic (settlement) value of a long ITM option exercised at expiry
GRID_SPOT_PCTS = (-5.0, -4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
GRID_IV_SHIFTS = (-10.0, -7.5, -5.0, -2.5, 0.0, 2.5, 5.0, 7.5, 10.0)
TIME_CONVENTION = ("each leg is valued at the days to its own expiry as sent: OSTR sends the chain's t_days (calendar time to 15:30 IST on "
                   "expiry ÷ 365, whole days at end of day, fractional intraday, no half-day: the app-wide rule, review M04); theta per calendar day")
POP_NOTE = ("Probability that the book is in profit at the nearest expiry under a risk-neutral lognormal at one IV (no skew, "
            "no fat tails). A fairly priced structure has an expected P&L of about minus its costs whatever this number is: a "
            "high probability pairs with a large loss when it fails. It restates the market's pricing: it describes, does not predict.")
SPOT_BASIS_NOTE = ("a spot move of x % moves every leg's reference (each expiry's forward, the future, the shares) by x %: "
                   "the basis is held as a ratio")


class LegIn(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["CE", "PE", "FUT", "EQ"] = Field(..., description="EQ = shares (a covered call on holdings): payoff S − entry")
    strike: float | None = Field(None, gt=0)
    premium: float = Field(..., ge=0, description="option premium / futures entry price / share price, ₹ per unit")
    lots: int = Field(1, ge=1, le=10_000)
    lot_size: int = Field(..., ge=1, le=100_000, description="from the chain payload — never hardcoded")
    iv: float | None = Field(None, gt=0, le=500, description="percent, e.g. 12.5")
    days: float | None = Field(None, ge=0, le=2000, description="this leg's days to expiry")
    forward: float | None = Field(None, gt=0, description="this leg's reference level: its expiry's chain forward (options), "
                                                          "the future's price (FUT), spot (EQ); default = the book's forward")
    expiry: date | None = Field(None, description="this leg's expiry (labels; the margin route needs it)")


class AnalyzeIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30)
    forward: float = Field(..., gt=0, description="chain forward (put-call parity) or future/spot")
    days_to_expiry: float = Field(..., ge=0, le=2000)
    default_iv: float = Field(..., gt=0, le=500, description="fallback IV %, usually the chain's ATM IV")
    r: float = Field(0.065, ge=0, le=0.25)
    legs: list[LegIn] = Field(..., min_length=1, max_length=MAX_LEGS)
    fut_margin_pct: float | None = Field(None, gt=0, le=100, description="margin heuristic override")
    is_index: bool = True
    brokerage_per_order: float = Field(20.0, ge=0, le=500)
    scenario_days: float = Field(0.0, ge=0, le=2000, description="T+n: days from now for the scenario curve")
    iv_shift: float = Field(0.0, ge=-50, le=50, description="parallel IV shift in vol points for the scenario curve")
    grid: bool = Field(False, description="add the 2-D P&L grid (spot ±5 % × IV ±10 pts × dates)")
    pop_iv: float | None = Field(None, gt=0, le=500, description="IV % for the probability of profit (default: default_iv)")
    slippage_per_unit: float = Field(0.0, ge=0, le=10_000, description="your bid–ask assumption, ₹ per unit per side")


# ── OSTR v2 valuation (pure; Black-76 from options_math) ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VLeg:
    """One leg for scenario valuation: the options_math leg (EQ carried as FUT: payoff S − entry, delta ±qty), its
    reference level as a ratio of the book's forward, its days to expiry and its IV (percent)."""
    leg: om.Leg
    ratio: float
    days: float
    iv: float
    equity: bool = False


def vlegs_from(legs: list[LegIn], ref_forward: float, default_days: float, default_iv: float) -> list[VLeg]:
    out = []
    for leg_in in legs:
        kind = "FUT" if leg_in.kind == "EQ" else leg_in.kind
        leg = om.Leg(side=leg_in.side, kind=kind, strike=leg_in.strike if kind != "FUT" else None, premium=leg_in.premium,
                     lots=leg_in.lots, lot_size=leg_in.lot_size, iv=leg_in.iv, days=leg_in.days)
        ratio = (leg_in.forward / ref_forward) if leg_in.forward and ref_forward > 0 else 1.0
        days = leg_in.days if leg_in.days is not None else default_days
        iv = leg_in.iv if leg_in.iv is not None and leg_in.iv > 0 else default_iv
        out.append(VLeg(leg, ratio, float(days), float(iv), equity=leg_in.kind == "EQ"))
    return out


def _intrinsic(kind: str, level: float, k: float) -> float:
    return max(level - k, 0.0) if kind == "CE" else max(k - level, 0.0)


def leg_pnl(v: VLeg, x: float, days_fwd: float = 0.0, iv_shift: float = 0.0, r: float = om.R_DEFAULT) -> float:
    """₹ P&L of one leg if the book's reference moves to ``x``, ``days_fwd`` days from now, IV shifted ``iv_shift`` pts."""
    lg = v.leg
    level = x * v.ratio
    if lg.kind == "FUT":
        return lg.sign * (level - lg.premium) * lg.qty
    residual = max(v.days - days_fwd, 0.0)
    if residual <= 1e-9:
        unit = _intrinsic(lg.kind, level, lg.k)
    else:
        sigma = max(v.iv + iv_shift, IV_FLOOR_PCT) / 100.0
        unit = om.black76(lg.kind, level, lg.k, residual / om.DAYS_IN_YEAR, sigma, r).price  # type: ignore[arg-type]
    return lg.sign * (unit - lg.premium) * lg.qty


def book_pnl(vlegs: list[VLeg], x: float, days_fwd: float = 0.0, iv_shift: float = 0.0, r: float = om.R_DEFAULT) -> float:
    return sum(leg_pnl(v, x, days_fwd, iv_shift, r) for v in vlegs)


def nearest_days(vlegs: list[VLeg], default_days: float) -> float:
    opts = [v.days for v in vlegs if v.leg.kind != "FUT"]
    return min(opts) if opts else float(default_days)


def is_uniform(vlegs: list[VLeg]) -> bool:
    return all(abs(v.ratio - 1.0) < 1e-12 for v in vlegs)


def tail_slope(vlegs: list[VLeg]) -> float:
    """d(P&L)/dx as x → ∞ at the nearest expiry: calls (expired or not) and futures / shares count, puts vanish."""
    return sum(v.leg.sign * v.leg.qty * v.ratio for v in vlegs if v.leg.kind in ("CE", "FUT"))


def find_roots(f: Any, lo: float, hi: float, n: int = 600) -> list[float]:
    """Every sign change of ``f`` on [lo, hi], each bisected to 1e-12 relative (a root-find, never a sampled guess)."""
    xs = [lo + (hi - lo) * i / n for i in range(n + 1)]
    vals = [f(x) for x in xs]
    roots: list[float] = []
    for i in range(n):
        a, b, fa, fb = xs[i], xs[i + 1], vals[i], vals[i + 1]
        if fa == 0.0:
            roots.append(a)
            continue
        if fa * fb < 0:
            x0, x1, f0 = a, b, fa
            for _ in range(200):
                mid = (x0 + x1) / 2
                fm = f(mid)
                if f0 * fm <= 0:
                    x1 = mid
                else:
                    x0, f0 = mid, fm
                if x1 - x0 <= 1e-12 * max(1.0, x1):
                    break
            roots.append((x0 + x1) / 2)
    out: list[float] = []
    for rt in sorted(roots):
        if not out or abs(rt - out[-1]) > 1e-6 * max(1.0, rt):
            out.append(rt)
    return out


def leg_greeks_v(v: VLeg, x: float, r: float = om.R_DEFAULT) -> dict[str, float | None]:
    """Signed ₹ Greeks of one leg with respect to the BOOK's reference x (delta × ratio, gamma × ratio²)."""
    lg = v.leg
    q = lg.sign * lg.qty
    if lg.kind == "FUT":
        return {"delta": float(q * v.ratio), "gamma": 0.0, "theta_day": 0.0, "vega": 0.0, "rho": 0.0, "price": None}
    g = om.black76(lg.kind, x * v.ratio, lg.k, max(v.days, 0.0) / om.DAYS_IN_YEAR, v.iv / 100.0, r)  # type: ignore[arg-type]
    return {"delta": g.delta * v.ratio * q, "gamma": g.gamma * v.ratio * v.ratio * q, "theta_day": g.theta_day * q,
            "vega": g.vega * q, "rho": g.rho * q, "price": g.price}


def grid_days(t_near: float) -> list[float]:
    """The dates of the 2-D grid: today, +1, +2 sessions-ish, the quarter points, and the nearest expiry."""
    if t_near <= 0.25:
        return [0.0, round(max(t_near, 0.0), 2)] if t_near > 0 else [0.0]
    mids = [float(d) for d in (1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90, 180, 365) if d <= t_near - max(0.5, 0.1 * t_near)]
    if len(mids) > 5:                                   # keep five evenly spaced interior dates
        mids = [mids[round(i * (len(mids) - 1) / 4)] for i in range(5)]
    return [0.0, *sorted(set(mids)), round(t_near, 2)]


def pnl_grid(vlegs: list[VLeg], f_ref: float, days_list: list[float], r: float = om.R_DEFAULT,
             spot_pcts: tuple[float, ...] = GRID_SPOT_PCTS, iv_shifts: tuple[float, ...] = GRID_IV_SHIFTS) -> dict[str, Any]:
    """P&L (₹) on spot % × IV shift × date — pnl[d][i][j] = date d, spot step i, IV step j."""
    pnl = [[[round(book_pnl(vlegs, f_ref * (1 + p / 100.0), d, s, r), 2) for s in iv_shifts] for p in spot_pcts] for d in days_list]
    return {"spot_pct": list(spot_pcts), "spot": [round(f_ref * (1 + p / 100.0), 2) for p in spot_pcts], "iv_shift": list(iv_shifts),
            "days": days_list, "pnl": pnl, "badge": BADGE_ARITH,
            "note": "Black-76 revaluation of every leg; " + SPOT_BASIS_NOTE + "; IV shifted in parallel, floored at 1 %; costs excluded"}


def prob_of_profit(vlegs: list[VLeg], f_ref: float, iv_pct: float, t_days: float, r: float = om.R_DEFAULT) -> dict[str, Any]:
    """P(book P&L at the nearest expiry > 0) for a reference level X ~ lognormal(mean F, vol iv over t_days)."""
    t = max(t_days, 0.25) / om.DAYS_IN_YEAR
    s = max(iv_pct, IV_FLOOR_PCT) / 100.0 * math.sqrt(t)
    lo, hi = f_ref * math.exp(-6.0 * s), f_ref * math.exp(6.0 * s)

    def g(x: float) -> float:
        return book_pnl(vlegs, x, t_days, 0.0, r)

    def above(k: float) -> float:                       # P(X > k) = N(d2(k)), d2 = (ln(F/k) − s²/2) / s
        if k <= 0:
            return 1.0
        if math.isinf(k):
            return 0.0
        return om.norm_cdf((math.log(f_ref / k) - s * s / 2.0) / s)

    roots = find_roots(g, lo, hi)
    bounds = [0.0, *roots, math.inf]
    p = 0.0
    for a, b in zip(bounds, bounds[1:], strict=False):
        probe = (max(a, lo) + min(b, hi)) / 2.0
        if g(probe) > 0:
            p += above(a) - above(b)
    return {"value": round(max(0.0, min(1.0, p)) * 100.0, 1), "unit": "%", "iv_used": round(iv_pct, 2),
            "horizon_days": round(t_days, 2), "profit_bounds": [round(x, 2) for x in roots], "badge": BADGE_HEURISTIC,
            "method": "risk-neutral lognormal at one IV, nearest expiry", "note": POP_NOTE}


def _x_values(anchors: list[float], f: float, days: float, iv: float, points: int = 101) -> list[float]:
    sd = f * max(0.02, iv / 100.0 * math.sqrt(max(days, 1.0) / om.DAYS_IN_YEAR))
    lo, hi = min(f - 2.5 * sd, f * 0.88), max(f + 2.5 * sd, f * 1.12)
    for a in anchors:
        lo, hi = min(lo, a * 0.96), max(hi, a * 1.04)
    lo = max(lo, 0.01)
    base = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
    return sorted({round(x, 6) for x in base + [a for a in anchors if lo <= a <= hi]})


def exercise_stt(vlegs: list[VLeg], f_ref: float) -> dict[str, Any]:
    """If held to expiry and settled at today's forward: 0.125 % of the intrinsic value of each LONG in-the-money option."""
    value = 0.0
    for v in vlegs:
        lg = v.leg
        if lg.kind in ("CE", "PE") and lg.side == "buy":
            value += _intrinsic(lg.kind, f_ref * v.ratio, lg.k) * lg.qty * EXERCISE_STT_PCT / 100.0
    return {"value": round(value, 2), "rate_pct": EXERCISE_STT_PCT, "at_forward": round(f_ref, 2), "badge": BADGE_ARITH,
            "note": "only if long in-the-money options are held to expiry and exercised (STT on the settlement value); "
                    "squaring off before expiry pays the 0.1 % sell-side STT already in the round trip instead"}


def cost_display(round_trip: dict[str, float]) -> dict[str, Any]:
    """Display items that ADD UP (review m061): each rounded to ₹1, the total their sum; the exact total beside it."""
    other = round_trip.get("stamp", 0.0) + round_trip.get("sebi", 0.0) + round_trip.get("ipft", 0.0)
    items = [("brokerage", round_trip.get("brokerage", 0.0)), ("STT", round_trip.get("stt", 0.0)), ("txn", round_trip.get("txn", 0.0)),
             ("GST", round_trip.get("gst", 0.0)), ("stamp + SEBI + IPFT", other)]
    shown = [[k, int(round(v))] for k, v in items]
    return {"items": shown, "total": sum(v for _, v in shown), "exact_total": round(round_trip.get("total", 0.0), 2),
            "note": "each item rounded to ₹1; the total is the sum of the items shown"}


def equity_costs(vlegs: list[VLeg]) -> dict[str, Any] | None:
    """Shares legs (EQ): the delivery round trip from shared/trading_costs.py (COST_PROFILE), never the F&O schedule."""
    eq = [v for v in vlegs if v.equity]
    if not eq:
        return None
    from shared.trading_costs import default_model
    model = default_model()
    total: dict[str, float] = {}
    for v in eq:
        d = model.round_trip(v.leg.premium * v.leg.qty, "delivery").as_dict()
        for k, val in d.items():
            total[k] = total.get(k, 0.0) + float(val)
    return {"round_trip": {k: round(val, 2) for k, val in total.items()}, "source": "shared/trading_costs.py (COST_PROFILE)",
            "note": "shares already in the demat cost nothing to enter here; this is the delivery round trip if bought for the "
                    "structure. A call assigned at expiry is physically settled: the shares are delivered"}


@router.post("/strategy/analyze")
def analyze(body: AnalyzeIn) -> dict:
    """Payoff at expiry + today (+ a T+n / IV-shift scenario), exact breakevens, max P&L, Greeks, probability of profit
    (heuristic), the optional 2-D grid, margin & cost ESTIMATES."""
    try:
        vlegs = vlegs_from(body.legs, body.forward, body.days_to_expiry, body.default_iv)
    except ValueError as exc:
        fail(400, "invalid", str(exc), "check each leg's strike, lots and premium")
    legs = [v.leg for v in vlegs]
    fno = [v.leg for v in vlegs if not v.equity]

    days = body.days_to_expiry
    iv = body.default_iv
    single = om.is_single_expiry(legs, days)
    uniform = is_uniform(vlegs)
    t_near = nearest_days(vlegs, days)

    if single and uniform:
        profit, loss = om.max_profit_loss(legs)
        bes = om.breakevens_any(legs, days, iv, body.r)
        grid = om.payoff_grid(legs, body.forward, days, iv, body.r)
        per_leg = [om.leg_greeks(lg, body.forward, days, iv, body.r) for lg in legs]
        sampled_extremes = False
    else:
        anchors = [v.leg.k / v.ratio for v in vlegs if v.leg.kind != "FUT"]
        xs0 = _x_values(anchors, body.forward, t_near, iv)
        bes = find_roots(lambda x: book_pnl(vlegs, x, t_near, 0.0, body.r), xs0[0], xs0[-1])
        be_set = {round(b, 6) for b in bes}
        xs = sorted(set(xs0) | be_set)
        # a breakeven IS a root: its expiry P&L is 0 exactly (the chart cuts the green / red curve there)
        grid = [{"s": round(x, 2), "expiry": 0.0 if x in be_set else round(book_pnl(vlegs, x, t_near, 0.0, body.r), 2),
                 "now": round(book_pnl(vlegs, x, 0.0, 0.0, body.r), 2)} for x in xs]
        vals = [(p["expiry"], p["s"]) for p in grid] + [(round(book_pnl(vlegs, 0.01, t_near, 0.0, body.r), 2), 0.0)]
        slope = tail_slope(vlegs)
        if abs(slope) < BASIS_SLOPE_TOL * max(v.leg.qty for v in vlegs):
            slope = 0.0                                 # a calendar's basis drift (ratio ≈ 1.002), not a naked unit
        best, worst = max(vals), min(vals)
        profit = om.Extreme(None, True) if slope > 1e-9 else om.Extreme(best[0], False, best[1])
        loss = om.Extreme(None, True) if slope < -1e-9 else om.Extreme(worst[0], False, worst[1])
        per_leg = [leg_greeks_v(v, body.forward, body.r) for v in vlegs]
        sampled_extremes = True
    net = {k: sum(float(p[k] or 0.0) for p in per_leg) for k in om.GREEK_KEYS}
    lot = next((v.leg.lot_size for v in vlegs if not v.equity), vlegs[0].leg.lot_size)
    net_units = {"delta_lots": net["delta"] / lot if lot else None,
                 "delta_inr_per_1pct": net["delta"] * body.forward * 0.01,
                 "gamma_pnl_1pct_inr": 0.5 * net["gamma"] * (body.forward * 0.01) ** 2,
                 "lot_size": lot}
    for p in grid:                                    # the T+n / IV-shift curve (equals "now" at 0 days, 0 pts)
        p["scenario"] = round(book_pnl(vlegs, p["s"], body.scenario_days, body.iv_shift, body.r), 2)

    fut_pct = body.fut_margin_pct or (om.FUT_MARGIN_PCT_INDEX if body.is_index else om.FUT_MARGIN_PCT_STOCK)
    margin = om.margin_estimate(fno, body.forward, fut_pct, loss) if fno else om.MarginEstimate(total=0.0)
    cash = om.entry_cashflow(legs)
    costs = om.costs_estimate(fno, body.brokerage_per_order) if fno else om.costs_estimate([], body.brokerage_per_order)
    spread = sum(v.leg.qty for v in vlegs) * body.slippage_per_unit * 2.0
    costs["note"] = str(costs.get("note", "")).replace("exercise STT at expiry (0.125% of intrinsic) not included",
                                                       "the exercise STT at expiry is shown separately (only if held)")
    costs["display"] = cost_display(costs["round_trip"])
    costs["exercise_stt"] = exercise_stt(vlegs, body.forward)
    costs["spread"] = {"value": round(spread, 2), "per_unit_per_side": body.slippage_per_unit, "badge": "input",
                       "note": "your bid–ask assumption × units × 2 sides; the chain served (EOD bhavcopy / NSE live) carries no bid or ask"}
    costs["equity"] = equity_costs(vlegs)
    pop = prob_of_profit(vlegs, body.forward, body.pop_iv or iv, t_near, body.r) if any(v.leg.kind != "FUT" for v in vlegs) else None

    # T-07b: breakevens net of the computed cost split — the underlying levels at expiry where the P&L equals the
    # round-trip costs (itemised F&O round trip + the bid–ask input; exercise STT shown separately, not included).
    cost_total = round(float(costs["round_trip"].get("total", 0.0)) + spread, 2)
    lo_x, hi_x = float(grid[0]["s"]), float(grid[-1]["s"])
    bes_net = (find_roots(lambda x: book_pnl(vlegs, x, t_near, 0.0, body.r) - cost_total, lo_x, hi_x)
               if cost_total > 0 else list(bes))

    out: dict[str, Any] = {
        "symbol": body.symbol.upper(),
        "forward": body.forward,
        "days_to_expiry": days,
        "r": body.r,
        "single_expiry": single,
        "multi_expiry": not single,
        "nearest_expiry_days": round(t_near, 4),
        "time_convention": TIME_CONVENTION,
        "entry_cashflow": round(cash, 2),               # + credit · − debit, option premiums only
        "net_label": "CREDIT" if cash > 0 else "DEBIT" if cash < 0 else "FLAT",
        "breakevens": [round(b, 2) for b in bes],
        "breakevens_net_of_costs": {
            "values": [round(b, 2) for b in bes_net],
            "costs_inr": cost_total,
            "badge": BADGE_ARITH,
            "note": "underlying levels at expiry where the P&L equals the round-trip costs shown (itemised round trip "
                    "+ your bid–ask input; the exercise STT is listed separately and not included) — arithmetic on the "
                    "same payoff curve within the plotted range",
        },
        "max_profit": {"value": profit.value, "unbounded": profit.unbounded, "at": profit.at},
        "max_loss": {"value": loss.value, "unbounded": loss.unbounded, "at": loss.at},
        "extremes_basis": ("the nearest-expiry curve on the plotted range (later legs by Black-76); the upside tail from "
                           "the net call / futures slope") if sampled_extremes else "exact, at expiry",
        "greeks": {
            "per_leg": [{k: (round(v, 6) if v is not None else None) for k, v in p.items()}
                        for p in per_leg],
            "net": {k: round(v, 6) for k, v in net.items()},
            "net_units": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in net_units.items()},
            "note": "Black-76 on each leg's forward · delta = futures-equivalent N(d1) on the book's reference · theta ₹/day · "
                    "vega ₹/vol-pt · rho ₹ per +1% rate · futures and shares legs: delta only (carry ignored)",
        },
        "payoff": grid,
        "scenario": {"days_forward": body.scenario_days, "iv_shift": body.iv_shift, "badge": BADGE_ARITH,
                     "note": f"P&L {body.scenario_days:g} days from now with IV {body.iv_shift:+g} pts; " + SPOT_BASIS_NOTE},
        "pop": pop,
        "margin": {
            "estimate": True,
            "total": margin.total,
            "per_leg": margin.per_leg,
            "premium_outflow": margin.premium_outflow,
            "defined_risk_floor": margin.defined_risk_floor,
            "fut_margin_pct": fut_pct,
            "note": margin.note,
            "error_factor_measured": HEURISTIC_ERROR_FACTOR,
            "real_margin": "POST /api/options/margin (Breeze SPAN when live → NSE SPAN file → this heuristic)",
            "excludes_shares": any(v.equity for v in vlegs),
        },
        "costs": costs,
        "paper_only": True,
    }
    if body.grid:
        out["grid"] = pnl_grid(vlegs, body.forward, grid_days(t_near), body.r)
    return out


# ── saved structures (OSTR: save / name a structure; NOT a booking — booking is routers/fo_book.py) ────────────────

class SavedLegIn(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["CE", "PE", "FUT", "EQ"]
    strike: float | None = Field(None, gt=0)
    expiry: date | None = None
    premium: float = Field(..., ge=0)
    iv: float | None = Field(None, gt=0, le=500)
    lots: int = Field(1, ge=1, le=10_000)
    lot_size: int = Field(..., ge=1, le=100_000)
    price_source: str | None = Field(None, max_length=120)


class SaveIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    symbol: str = Field(..., min_length=1, max_length=30)
    legs: list[SavedLegIn] = Field(..., min_length=1, max_length=MAX_LEGS)
    note: str | None = Field(None, max_length=300)


def _store() -> Any:
    import fo_book_store
    return fo_book_store.get_store()


@router.get("/strategy/saved")
def saved_list(symbol: str | None = None) -> dict:
    """Named structures saved from OSTR (newest first), with the premiums and their source as saved."""
    rows = _store().saved_list(symbol.upper() if symbol else None)
    return {"rows": rows, "count": len(rows), "badge": BADGE_ARITH, "paper_only": True,
            "note": "saved structures keep the premiums they were saved with; re-price them on the current chain before reading a P&L"}


@router.post("/strategy/saved")
def saved_save(body: SaveIn) -> dict:
    """Save (or overwrite by name + symbol) a structure. Writes the OSTR store only; books nothing."""
    name = body.name.strip()
    if not name:
        fail(422, "invalid", "a saved structure needs a name")
    legs = [leg.model_dump(mode="json") for leg in body.legs]
    return {"saved": _store().save_structure(name=name, symbol=body.symbol.upper(), legs=legs, note=body.note), "paper_only": True}


@router.delete("/strategy/saved/{saved_id}")
def saved_delete(saved_id: int) -> dict:
    if not _store().delete_saved(saved_id):
        fail(404, "not_found", f"saved structure {saved_id} does not exist")
    return {"deleted": saved_id, "paper_only": True}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# POST /margin — Breeze → NSE SPAN file → heuristic (PLAN 1.3)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


class MarginLegIn(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["CE", "PE", "FUT"]
    strike: float | None = Field(None, gt=0)
    expiry: date = Field(..., description="contract expiry, YYYY-MM-DD (read from the chain / the file, never assumed)")
    premium: float = Field(0.0, ge=0, description="option premium / futures price, ₹ per unit (the heuristic's input)")
    lots: int = Field(1, ge=1, le=10_000)
    lot_size: int = Field(..., ge=1, le=100_000, description="from the chain payload — never hardcoded")


class MarginIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30, description="NSE underlying (NIFTY, RELIANCE, …)")
    legs: list[MarginLegIn] = Field(..., min_length=1, max_length=MAX_LEGS)
    exchange_code: Literal["NFO"] = "NFO"
    forward: float | None = Field(None, gt=0, description="for the heuristic and the exposure estimate (default: the file's settlement price)")
    stock_code: str | None = Field(None, max_length=20, description="ICICI stock code when it differs from the NSE symbol (INFTEC for INFY)")
    sources: str = Field("breeze,span_file,heuristic", max_length=60, description="comma list to restrict the fallback chain (tests)")
    cached_only: bool = Field(False, description="serve the cached last successful Breeze answer for this (symbol, legs shape) "
                                                 "instantly and call NOTHING; {'hit': false} when none exists (P0-8 fast probe)")
    stale_ok: bool = Field(False, description="when Breeze fails or times out, serve the cached last Breeze answer with its age "
                                              "before falling to the SPAN file / heuristic (P0-8; the UI sends true)")
    breeze_timeout_s: float = Field(8.0, ge=1, le=30, description="give up waiting on the Breeze call after this long; the "
                                                                  "ladder (cache / SPAN file / heuristic) answers instead")


@dataclass
class RiskArray:
    kind: str                  # "C" | "P" | "F"
    expiry: str                # YYYYMMDD
    strike: float
    price: float               # settlement price per unit
    delta: float               # the contract's delta
    composite_delta: float     # the <d> inside <ra>
    losses: list[float]        # 16 scenario losses for ONE LONG UNIT (positive = loss), ₹


@dataclass
class SpanProduct:
    pf_code: str
    file_date: str
    settlement: bool
    arrays: dict[tuple[str, str, float], RiskArray] = field(default_factory=dict)   # (kind, expiry, strike)
    calendar_spreads: list[dict[str, Any]] = field(default_factory=list)            # {rate, legs:[(expiry, side)]}
    som_rate: float = 0.0                                                            # short option minimum per unit
    scan_ranges: dict[str, float] = field(default_factory=dict)                      # expiry → price scan range


def _tag(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>\s*([^<]*?)\s*</{tag}>", text)
    return m.group(1) if m else None


def _block(text: str, tag: str, locator: str) -> str | None:
    """The first ``<tag> … </tag>`` block whose head contains ``locator`` (e.g. ``<pfCode>NIFTY</pfCode>``)."""
    start = 0
    while True:
        i = text.find(f"<{tag}>", start)
        if i < 0:
            return None
        j = text.find(f"</{tag}>", i)
        if j < 0:
            return None
        head = text[i:i + 400]
        if locator in head:
            return text[i:j + len(tag) + 3]
        start = j


_OPT_RE = re.compile(r"<opt>(.*?)</opt>", re.S)
_FUT_RE = re.compile(r"<fut>(.*?)</fut>", re.S)
_SERIES_RE = re.compile(r"<series>(.*?)</series>", re.S)
_A_RE = re.compile(r"<a>\s*([-\d.]+)\s*</a>")
_DSPREAD_RE = re.compile(r"<dSpread>(.*?)</dSpread>", re.S)
_PLEG_RE = re.compile(r"<pLeg>(.*?)</pLeg>", re.S)


def _risk_array(body: str, kind: str, expiry: str, strike: float) -> RiskArray | None:
    ra = re.search(r"<ra>(.*?)</ra>", body, re.S)
    if not ra:
        return None
    losses = [float(x) for x in _A_RE.findall(ra.group(1))]
    if len(losses) != SPAN_SCENARIOS:
        return None
    price = float(_tag(body, "p") or 0.0)
    delta = float(_tag(body, "d") or (1.0 if kind == "F" else 0.0))
    cd = _tag(ra.group(1), "d")
    return RiskArray(kind, expiry, strike, price, delta, float(cd) if cd else delta, losses)


def parse_span_product(text: str, pf_code: str) -> SpanProduct | None:
    """Parse one underlying out of an NSE/NCL SPAN file (CME SPAN 'expanded XML' format 4.00): the futures block
    (`futPf`), the options block (`oopPf`, one `series` per expiry, one `opt` per strike × C/P, each with its 16-scenario
    risk array in ₹ per unit for a long position — positive = loss) and the combined-commodity block (`ccDef`: the
    calendar-spread charges `dSpread` and the short-option-minimum tiers). Verified on nsccl.20261104.s.spn."""
    file_date = _tag(text[:4000], "date") or ""
    settlement = (_tag(text[:4000], "isSetl") or "0").strip() == "1"
    out = SpanProduct(pf_code=pf_code, file_date=file_date, settlement=settlement)
    found = False
    fut_pf = _block(text, "futPf", f"<pfCode>{pf_code}</pfCode>")
    if fut_pf:
        for m in _FUT_RE.finditer(fut_pf):
            body = m.group(1)
            exp = _tag(body, "pe") or ""
            ra = _risk_array(body, "F", exp, 0.0)
            if ra:
                out.arrays[("F", exp, 0.0)] = ra
                found = True
            ps = _tag(body, "priceScan")
            if ps:
                out.scan_ranges.setdefault(exp, float(ps))
    oop_pf = _block(text, "oopPf", f"<pfCode>{pf_code}</pfCode>")
    if oop_pf:
        for sm in _SERIES_RE.finditer(oop_pf):
            series = sm.group(1)
            exp = _tag(series, "pe") or ""
            ps = _tag(series, "priceScan")
            if ps:
                out.scan_ranges[exp] = float(ps)
            for om_ in _OPT_RE.finditer(series):
                body = om_.group(1)
                kind = (_tag(body, "o") or "").upper()
                strike = float(_tag(body, "k") or 0.0)
                ra = _risk_array(body, kind, exp, strike)
                if ra and kind in ("C", "P"):
                    out.arrays[(kind, exp, strike)] = ra
                    found = True
    cc = _block(text, "ccDef", f"<cc>{pf_code}</cc>")
    if cc:
        som = re.search(r"<somTiers>.*?<val>\s*([-\d.]+)\s*</val>", cc, re.S)
        if som:
            out.som_rate = float(som.group(1))
        for dm in _DSPREAD_RE.finditer(cc):
            d = dm.group(1)
            rate = _tag(d, "val")
            legs = [((_tag(pl.group(1), "pe") or ""), (_tag(pl.group(1), "rs") or "A").upper()) for pl in _PLEG_RE.finditer(d)]
            if rate and len(legs) >= 2:
                out.calendar_spreads.append({"rate": float(rate), "method": _tag(d, "chargeMeth") or "F", "legs": legs})
    return out if found else None


def span_margin(product: SpanProduct, legs: list[MarginLegIn]) -> dict[str, Any]:
    """SPAN initial margin for the book from the file's arrays: scanning risk (max over the 16 scenarios of the net
    loss, long = +array, short = −array, × units), + the calendar-spread charge (flat ₹ per spread formed between a net
    long delta in one expiry and a net short delta in another), with the short-option-minimum floor. No
    inter-commodity credit (none is defined for NSE's single-underlying combined commodities)."""
    totals = [0.0] * SPAN_SCENARIOS
    missing: list[str] = []
    net_delta: dict[str, float] = {}
    short_units = 0
    settle_value = 0.0
    for leg in legs:
        exp = leg.expiry.strftime("%Y%m%d")
        kind = {"CE": "C", "PE": "P", "FUT": "F"}[leg.kind]
        key = (kind, exp, float(leg.strike or 0.0))
        ra = product.arrays.get(key)
        if ra is None:
            missing.append(f"{leg.kind} {leg.strike or ''} {leg.expiry.isoformat()}".strip())
            continue
        units = leg.lots * leg.lot_size
        sign = 1.0 if leg.side == "buy" else -1.0
        for s in range(SPAN_SCENARIOS):
            totals[s] += sign * ra.losses[s] * units
        net_delta[exp] = net_delta.get(exp, 0.0) + sign * ra.composite_delta * units
        if leg.side == "sell" and kind in ("C", "P"):
            short_units += units
        settle_value += sign * ra.price * units
    if missing:
        return {"ok": False, "missing": missing}
    worst = max(range(SPAN_SCENARIOS), key=lambda s: totals[s])
    scanning = max(0.0, totals[worst])
    spread_charge = 0.0
    spreads_formed: list[dict[str, Any]] = []
    longs = {e: d for e, d in net_delta.items() if d > 0}
    shorts = {e: -d for e, d in net_delta.items() if d < 0}
    for sp in product.calendar_spreads:
        exps = [e for e, _ in sp["legs"]]
        if len(exps) < 2:
            continue
        a, b = exps[0], exps[1]
        pairs = ((a, b), (b, a))
        for lo, sh in pairs:
            n = min(longs.get(lo, 0.0), shorts.get(sh, 0.0))
            if n > 0:
                longs[lo] -= n
                shorts[sh] -= n
                spread_charge += sp["rate"] * n
                spreads_formed.append({"long": lo, "short": sh, "spreads": round(n, 2), "charge": round(sp["rate"] * n, 2)})
    som = product.som_rate * short_units
    span = max(scanning + spread_charge, som)
    return {"ok": True, "scanning_risk": round(scanning, 2), "worst_scenario": worst + 1, "scenario_losses": [round(t, 2) for t in totals],
            "calendar_spread_charge": round(spread_charge, 2), "spreads": spreads_formed, "short_option_minimum": round(som, 2),
            "span_margin": round(span, 2), "net_delta_by_expiry": {e: round(d, 2) for e, d in net_delta.items()},
            "net_option_value": round(settle_value, 2), "file_date": product.file_date, "settlement_file": product.settlement}


def exposure_estimate(legs: list[MarginLegIn], symbol: str, forward: float | None, product: SpanProduct | None) -> dict[str, Any]:
    """NSE's exposure (non-SPAN) margin: a published percentage of the notional of short options and futures (index 2 %,
    stocks 3.5 % or 1.5 σ, whichever is higher — the σ leg is NOT computed here). Labelled heuristic: it is a rule, not
    the file."""
    pct = EXPOSURE_PCT_INDEX if symbol in INDEX_UNDERLYINGS else EXPOSURE_PCT_STOCK
    notional = 0.0
    ref = forward
    if ref is None and product is not None:
        futs = sorted((k for k in product.arrays if k[0] == "F"), key=lambda k: k[1])
        ref = product.arrays[futs[0]].price if futs else None
    for leg in legs:
        if leg.kind == "FUT" or leg.side == "sell":
            notional += (ref or 0.0) * leg.lots * leg.lot_size
    return {"pct_of_notional": pct, "reference_price": ref, "value": round(notional * pct / 100, 2) if ref else None,
            "badge": BADGE_HEURISTIC, "note": f"NSE exposure margin rule ({pct} % of short/futures notional); not read from the file"}


def _span_dir() -> Path:
    env = os.environ.get(SPAN_DIR_ENV, "").strip()
    if env:
        return Path(env)
    for root in (Path(__file__).resolve().parents[3] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "nse_archive" / "span"
    return Path("data/nse_archive/span")


def latest_span_file(directory: Path | None = None) -> Path | None:
    d = directory or _span_dir()
    if not d.is_dir():
        return None
    files = sorted((p for p in d.iterdir() if SPAN_FILE_RE.match(p.name)), key=lambda p: p.name)
    return files[-1] if files else None


def load_span_product(path: Path, pf_code: str) -> SpanProduct | None:
    """Read the zip (or a bare .spn/.xml), parse ONE underlying, memoise per (file, underlying)."""
    key = (str(path), pf_code)
    with _SPAN_PARSE_LOCK:
        if key in _SPAN_CACHE:
            return _SPAN_CACHE[key]
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith((".spn", ".xml"))] or z.namelist()
            text = io.TextIOWrapper(z.open(names[0]), encoding="utf-8", errors="ignore").read()
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
    product = parse_span_product(text, pf_code)
    with _SPAN_PARSE_LOCK:
        _SPAN_CACHE[key] = product
        while len(_SPAN_CACHE) > 64:
            _SPAN_CACHE.pop(next(iter(_SPAN_CACHE)))
    return product


def breeze_positions(body: MarginIn, stock_code: str) -> list[dict[str, str]]:
    """The SDK's `list_of_positions` rows (the shape ICICI documents; INFY future sample in reports/breeze_catalog)."""
    rows = []
    for leg in body.legs:
        rows.append({
            "strike_price": f"{leg.strike:g}" if leg.kind != "FUT" and leg.strike else "0",
            "quantity": str(leg.lots * leg.lot_size),
            "right": {"CE": "Call", "PE": "Put", "FUT": "Others"}[leg.kind],
            "product": "Options" if leg.kind != "FUT" else "Futures",
            "action": "Buy" if leg.side == "buy" else "Sell",
            "price": f"{leg.premium:g}",
            "expiry_date": leg.expiry.strftime("%d-%b-%Y"),
            "stock_code": stock_code,
        })
    return rows


def _num(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_breeze_margin(resp: Any) -> dict[str, Any] | None:
    """`{Success: {span_margin_required, non_span_margin_required, order_value, …}, Status, Error}` → numbers."""
    if not isinstance(resp, dict):
        return None
    ok = resp.get("Success")
    if not isinstance(ok, dict) or resp.get("Error"):
        return None
    span, non_span = _num(ok.get("span_margin_required")), _num(ok.get("non_span_margin_required"))
    if span is None:
        return None
    return {"span_margin_required": span, "non_span_margin_required": non_span or 0.0,
            "order_value": _num(ok.get("order_value")), "trade_margin": _num(ok.get("trade_margin")),
            "legs_echo": len(ok.get("margin_calulation") or [])}


def _breeze_margin_sync(body: MarginIn) -> tuple[dict[str, Any] | None, str]:
    """(parsed, reason) — the Breeze leg: session check, budget ledger, the SDK call on this worker thread."""
    from routers import positions as pos
    breeze, err = pos._get_breeze_client()
    if breeze is None:
        return None, f"no live Breeze session ({err or 'not configured'})"
    code = (body.stock_code or "").strip().upper()
    if not code:
        sym = body.symbol.upper()
        if sym in INDEX_UNDERLYINGS:
            code = sym
        else:
            try:
                rev = {v: k for k, v in pos.isec_to_nse().items()}
                code = rev.get(sym, sym)
            except Exception:  # noqa: BLE001 — the master may be unavailable; try the NSE symbol as the code
                code = sym
    try:
        with ledger().guard(BREEZE_CALLER, "margin_calculator"):
            resp = breeze.margin_calculator(breeze_positions(body, code), body.exchange_code)
    except BudgetExceeded as exc:
        return None, f"Breeze budget: {exc}"
    except Exception as exc:  # noqa: BLE001 — SDK / network errors: fall through to the file
        return None, f"Breeze margin_calculator failed: {type(exc).__name__}: {str(exc)[:80]}"
    parsed = parse_breeze_margin(resp)
    if parsed is None:
        err_txt = str((resp or {}).get("Error") if isinstance(resp, dict) else resp)[:80]
        return None, f"Breeze answered without a margin ({err_txt})"
    return parsed, "ok"


def _span_file_sync(body: MarginIn) -> tuple[dict[str, Any] | None, str, SpanProduct | None]:
    path = latest_span_file()
    if path is None:
        return None, f"no SPAN file under {_span_dir()} (the 20:30 pass fetches nsccl.YYYYMMDD.s.zip)", None
    try:
        product = load_span_product(path, body.symbol.upper())
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        return None, f"SPAN file {path.name} unreadable: {type(exc).__name__}", None
    if product is None:
        return None, f"{body.symbol.upper()} not in SPAN file {path.name}", None
    res = span_margin(product, body.legs)
    if not res["ok"]:
        return None, f"contracts not in SPAN file {path.name}: {', '.join(res['missing'])}", product
    res["file"] = path.name
    return res, "ok", product


def heuristic_margin(body: MarginIn, forward: float | None) -> dict[str, Any]:
    legs = [om.Leg(side=l.side, kind=l.kind, strike=l.strike, premium=l.premium, lots=l.lots, lot_size=l.lot_size)
            for l in body.legs]
    ref = forward or max((l.strike or 0.0) for l in body.legs) or 1.0
    is_index = body.symbol.upper() in INDEX_UNDERLYINGS
    pct = om.FUT_MARGIN_PCT_INDEX if is_index else om.FUT_MARGIN_PCT_STOCK
    _, loss = om.max_profit_loss(legs)
    est = om.margin_estimate(legs, ref, pct, loss)
    return {"total": est.total, "per_leg": est.per_leg, "premium_outflow": est.premium_outflow,
            "defined_risk_floor": est.defined_risk_floor, "fut_margin_pct": pct,
            "error_factor_measured": HEURISTIC_ERROR_FACTOR, "evidence": HEURISTIC_EVIDENCE, "note": est.note}


@router.post("/margin")
async def margin(body: MarginIn) -> dict:
    """Real margin for a book of up to 4 NFO legs: Breeze SPAN when the session is live (through the budget ledger) →
    the NSE SPAN risk-parameter file parsed offline → the 12 % heuristic as the last resort with its measured 4.8× error
    printed. The source chip says which one answered; `attempts` lists why the earlier ones did not."""
    chain = [s.strip().lower() for s in body.sources.split(",") if s.strip()]
    attempts: list[dict[str, Any]] = []
    symbol = body.symbol.upper()
    cache_key = margin_cache_key(body)
    if body.cached_only:
        # the P0-8 fast probe: the UI renders this instantly while the full ask runs behind — never a Breeze call
        entry = _margin_cache_get(cache_key)
        if entry is None:
            return {"hit": False, "served_from_cache": False, "paper_only": True,
                    "note": "no cached Breeze answer for these legs on this ui-api yet"}
        age = max(0, int(time.time() - float(entry["at"])))
        out = _cached_margin_answer(entry, [{"source": "CACHE", "ok": True,
                                             "reason": f"the Breeze answer cached {age} s ago; the full ask refreshes it"}])
        out["hit"] = True
        return out
    source, span_req, non_span, order_value, detail = "HEURISTIC", None, None, None, {}
    product: SpanProduct | None = None
    if "breeze" in chain:
        # asyncio.wait (not wait_for): a worker thread cannot be cancelled, so a timeout ABANDONS the wait instead
        # of blocking on the cancellation; the SDK call finishes on its thread and is discarded
        task = asyncio.ensure_future(asyncio.to_thread(_breeze_margin_sync, body))
        done, _pending = await asyncio.wait({task}, timeout=body.breeze_timeout_s)
        if done:
            parsed, reason = task.result()
        else:
            task.add_done_callback(lambda t: t.cancelled() or t.exception())   # retrieve, never warn
            parsed, reason = None, f"Breeze did not answer within {body.breeze_timeout_s:g} s"
        attempts.append({"source": "BREEZE", "ok": parsed is not None, "reason": reason})
        if parsed is not None:
            source, span_req, non_span, order_value, detail = "BREEZE", parsed["span_margin_required"], parsed["non_span_margin_required"], parsed["order_value"], parsed
    if source == "HEURISTIC" and body.stale_ok:
        # Breeze failed or timed out: the last successful Breeze answer for these legs, age on its face (P0-8)
        entry = _margin_cache_get(cache_key)
        if entry is not None:
            age = max(0, int(time.time() - float(entry["at"])))
            attempts.append({"source": "CACHED_BREEZE", "ok": True,
                             "reason": f"the last successful Breeze answer for these legs, {age} s old"})
            return _cached_margin_answer(entry, attempts)
    if source == "HEURISTIC" and "span_file" in chain:
        res, reason, product = await asyncio.to_thread(_span_file_sync, body)
        attempts.append({"source": "NSE_SPAN_FILE", "ok": res is not None, "reason": reason})
        if res is not None:
            source, span_req, detail = "NSE_SPAN_FILE", res["span_margin"], res
            expo = exposure_estimate(body.legs, symbol, body.forward, product)
            non_span = expo["value"]
            detail = {**res, "exposure": expo}
    heuristic = heuristic_margin(body, body.forward)
    if source == "HEURISTIC":
        attempts.append({"source": "HEURISTIC", "ok": True, "reason": "last resort — " + HEURISTIC_EVIDENCE})
        span_req, non_span = heuristic["total"], 0.0
    total = (span_req or 0.0) + (non_span or 0.0)
    chip = {"BREEZE": "BREEZE", "NSE_SPAN_FILE": "NSE SPAN FILE", "HEURISTIC": "HEURISTIC"}[source]
    resp = _margin_response(body, symbol, source, chip, span_req, non_span, order_value, total, detail, heuristic, attempts)
    if source == "BREEZE":
        _margin_cache_put(cache_key, resp)
    return resp


def _margin_response(body: MarginIn, symbol: str, source: str, chip: str, span_req: float | None, non_span: float | None,
                     order_value: float | None, total: float, detail: dict[str, Any], heuristic: dict[str, Any],
                     attempts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "symbol": symbol, "exchange_code": body.exchange_code, "legs": len(body.legs),
        "source": source, "source_chip": chip, "served_from_cache": False,
        "span_margin_required": span_req, "non_span_margin_required": non_span, "total_margin": round(total, 2),
        "order_value": order_value,
        "as_of": (detail.get("file_date") and f"{detail['file_date'][:4]}-{detail['file_date'][4:6]}-{detail['file_date'][6:8]}")
        if source == "NSE_SPAN_FILE" else datetime.now(IST).isoformat(timespec="seconds"),
        "detail": detail, "heuristic": heuristic, "attempts": attempts,
        # per-field badges (check:B3-API minor): on the NSE SPAN FILE answer the exposure leg is NSE's published rule
        # (heuristic), so the total is only as strong as its weaker part; the UI prints total_margin OR heuristic.total, never both
        "badges": {"span_margin_required": BADGE_ARITH if source != "HEURISTIC" else BADGE_HEURISTIC,
                   "non_span_margin_required": BADGE_ARITH if source == "BREEZE" else BADGE_HEURISTIC,
                   "total_margin": BADGE_ARITH if source == "BREEZE" else BADGE_HEURISTIC},
        "badge": BADGE_ARITH if source == "BREEZE" else BADGE_HEURISTIC,
        "note": {"BREEZE": "ICICI's margin calculator (exchange SPAN + exposure as ICICI applies them); 0.3 s; one Breeze call through the budget ledger",
                 "NSE_SPAN_FILE": "scanning risk + calendar-spread charge with the short-option-minimum floor from NCL's EOD risk-parameter file; "
                                  "exposure margin by NSE's published rule (labelled heuristic); intraday files are not fetched",
                 "HEURISTIC": HEURISTIC_EVIDENCE}[source],
        "paper_only": True,
    }

