"""Options strategy math for OSTR (W3): Black-76 pricing/Greeks, exact piecewise-linear
breakevens, max profit/loss with honest bounded/unbounded flags, payoff grids, and
clearly-labelled margin + cost ESTIMATES for NSE F&O.

Pure module: no FastAPI, no I/O, no globals mutated — unit-tested in
services/ui-api/tests/test_options_math.py. Mirrors ui/lib/black76.ts (the model behind
OMON's implied vols): price on the put-call-parity forward, r = 6.5% default, delta is the
undiscounted hedge ratio N(d1) (futures-equivalent, → 1 deep ITM), theta per calendar day,
vega per 1 vol point, rho per +1% rate (Black-76: ∂V/∂r = −T·V, forward held fixed).

Cost model gap, stated honestly: shared/trading_costs.py covers CASH EQUITY only
(delivery/intraday Product literals — no F&O legs). The statutory NSE F&O rates are
therefore encoded here (FY 2025-26: STT options 0.1% sell premium / futures 0.02% sell,
NSE txn 0.03503% premium / 0.00173% futures, SEBI ₹10/cr, stamp 0.003%/0.002% buy,
IPFT ₹50/cr options / ₹10/cr futures, GST 18% on brokerage+txn+SEBI) and every figure is
labelled ESTIMATE. Exercise/assignment STT at expiry (0.125% of intrinsic) is NOT included —
the estimate assumes square-off before expiry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

R_DEFAULT = 0.065          # annualized risk-free rate, same as OMON / ui/lib/black76.ts
DAYS_IN_YEAR = 365.0

Side = Literal["buy", "sell"]
Kind = Literal["CE", "PE", "FUT"]

# ── normal distribution (stdlib erf: exact to double precision, no scipy needed) ──────────


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


# ── Black-76 on the forward ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class B76:
    price: float
    delta: float        # undiscounted N(d1) hedge ratio (call), N(d1)−1 (put)
    gamma: float        # per ₹1 move
    theta_day: float    # ₹ per calendar day (negative = decay)
    vega: float         # ₹ per 1 implied-vol point
    rho: float          # ₹ per +1% rate (Black-76: −T·V/100)
    prob_itm: float     # risk-neutral N(d2) / N(−d2)


def black76(kind: Literal["CE", "PE"], f: float, k: float, t_years: float, sigma: float,
            r: float = R_DEFAULT) -> B76:
    """European option on the forward. sigma decimal (0.15), t in years."""
    if f <= 0 or k <= 0:
        raise ValueError("forward and strike must be positive")
    if t_years <= 0 or sigma <= 0:                      # at expiry: intrinsic only
        intrinsic = max(f - k, 0.0) if kind == "CE" else max(k - f, 0.0)
        delta = (1.0 if f > k else 0.0) if kind == "CE" else (-1.0 if f < k else 0.0)
        return B76(intrinsic, delta, 0.0, 0.0, 0.0, 0.0, 1.0 if intrinsic > 0 else 0.0)
    df = math.exp(-r * t_years)
    s_t = sigma * math.sqrt(t_years)
    d1 = (math.log(f / k) + sigma * sigma * t_years / 2.0) / s_t
    d2 = d1 - s_t
    if kind == "CE":
        price = df * (f * norm_cdf(d1) - k * norm_cdf(d2))
        delta, prob = norm_cdf(d1), norm_cdf(d2)
    else:
        price = df * (k * norm_cdf(-d2) - f * norm_cdf(-d1))
        delta, prob = norm_cdf(d1) - 1.0, norm_cdf(-d2)
    gamma = norm_pdf(d1) / (f * s_t)
    vega = f * df * norm_pdf(d1) * math.sqrt(t_years) / 100.0
    theta_year = -f * df * norm_pdf(d1) * sigma / (2.0 * math.sqrt(t_years)) + r * price
    return B76(price, delta, gamma, theta_year / DAYS_IN_YEAR, vega, -t_years * price / 100.0, prob)


# ── strategy legs ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Leg:
    """One leg. `premium` is the entry price per unit: option premium for CE/PE, the
    futures entry price for FUT. `iv` in percent (12.5). `days` to this leg's expiry."""
    side: Side
    kind: Kind
    strike: float | None
    premium: float
    lots: int = 1
    lot_size: int = 1
    iv: float | None = None
    days: float | None = None

    def __post_init__(self) -> None:
        if self.kind in ("CE", "PE") and (self.strike is None or self.strike <= 0):
            raise ValueError(f"{self.kind} leg needs a positive strike")
        if self.lots <= 0 or self.lot_size <= 0:
            raise ValueError("lots and lot_size must be positive")
        if self.premium < 0:
            raise ValueError("premium cannot be negative")

    @property
    def k(self) -> float:
        """The strike, typed: __post_init__ guarantees option legs always carry one."""
        assert self.strike is not None
        return float(self.strike)

    @property
    def sign(self) -> int:
        return 1 if self.side == "buy" else -1

    @property
    def qty(self) -> int:
        """Units of underlying this leg controls (unsigned)."""
        return self.lots * self.lot_size


def expiry_payoff(legs: list[Leg], s: float) -> float:
    """₹ P&L of the whole book at the terminal underlying level `s` (all legs at expiry)."""
    total = 0.0
    for leg in legs:
        if leg.kind == "CE":
            unit = max(s - leg.k, 0.0) - leg.premium
        elif leg.kind == "PE":
            unit = max(leg.k - s, 0.0) - leg.premium
        else:                                            # FUT: premium = entry price
            unit = s - leg.premium
        total += leg.sign * unit * leg.qty
    return total


def _slope(legs: list[Leg], s: float) -> float:
    """d(payoff)/dS at a non-kink point s (piecewise-linear expiry payoff)."""
    m = 0.0
    for leg in legs:
        if leg.kind == "FUT":
            m += leg.sign * leg.qty
        elif leg.kind == "CE" and s > leg.k:
            m += leg.sign * leg.qty
        elif leg.kind == "PE" and s < leg.k:
            m -= leg.sign * leg.qty
    return m


def kink_points(legs: list[Leg]) -> list[float]:
    return sorted({leg.k for leg in legs if leg.strike is not None})


def breakevens(legs: list[Leg]) -> list[float]:
    """Exact breakevens of the piecewise-linear payoff AT EXPIRY — solved on each linear
    segment (root of a line), never sampled. Domain S ∈ [0, ∞)."""
    if not legs:
        return []
    kinks = kink_points(legs)
    pts = [0.0] + kinks
    vals = [expiry_payoff(legs, p) for p in pts]
    roots: list[float] = []
    eps = 1e-9 * max([abs(v) for v in vals] + [1.0])

    for i in range(len(pts) - 1):                       # bounded segments [0,k1],[k1,k2]…
        a, b, pa, pb = pts[i], pts[i + 1], vals[i], vals[i + 1]
        if abs(pa) <= eps:
            if a > 0:                                   # S=0 is a boundary, not a breakeven
                roots.append(a)
            continue
        if pa * pb < 0:
            roots.append(a - pa * (b - a) / (pb - pa))  # exact: the payoff is linear here

    last, p_last = pts[-1], vals[-1]                    # half-open segment [k_max, ∞)
    m = _slope(legs, last + max(1.0, last) )            # slope anywhere above the last kink
    if abs(p_last) <= eps:
        if last > 0:
            roots.append(last)
    elif m != 0 and (p_last < 0) != (m < 0):            # heading back through zero
        roots.append(last - p_last / m)

    out: list[float] = []                               # dedupe (kink touching zero twice)
    for r in sorted(roots):
        if not out or abs(r - out[-1]) > 1e-6 * max(1.0, r):
            out.append(r)
    return out


@dataclass(frozen=True)
class Extreme:
    value: float | None          # ₹; None when unbounded
    unbounded: bool
    at: float | None = None      # underlying level where the bounded extreme is reached


def max_profit_loss(legs: list[Leg]) -> tuple[Extreme, Extreme]:
    """(max_profit, max_loss) of the expiry payoff over S ∈ [0, ∞).

    The downside is always bounded at S = 0 (stocks stop at zero — a short put's worst
    case is strike − premium). Only the S → ∞ tail can be unbounded, governed by the net
    slope above the highest strike: > 0 → unlimited profit, < 0 → unlimited loss.
    """
    if not legs:
        return Extreme(0.0, False, None), Extreme(0.0, False, None)
    pts = [0.0] + kink_points(legs)
    vals = [expiry_payoff(legs, p) for p in pts]
    m_right = _slope(legs, pts[-1] + max(1.0, pts[-1]))
    best_i = max(range(len(vals)), key=lambda i: vals[i])
    worst_i = min(range(len(vals)), key=lambda i: vals[i])
    profit = (Extreme(None, True) if m_right > 0
              else Extreme(round(vals[best_i], 2), False, pts[best_i]))
    loss = (Extreme(None, True) if m_right < 0
            else Extreme(round(vals[worst_i], 2), False, pts[worst_i]))
    return profit, loss


# ── value today (Black-76 per leg) ───────────────────────────────────────────────────────


def book_value_now(legs: list[Leg], s: float, default_days: float, default_iv: float,
                   r: float = R_DEFAULT) -> float:
    """₹ P&L of the book TODAY if the underlying (forward proxy) moved to `s`:
    each option valued with Black-76 at its own residual time and IV, futures at
    (s − entry) — basis treated as constant (stated approximation)."""
    total = 0.0
    for leg in legs:
        if leg.kind == "FUT":
            total += leg.sign * (s - leg.premium) * leg.qty
            continue
        days = leg.days if leg.days is not None else default_days
        iv = (leg.iv if leg.iv is not None and leg.iv > 0 else default_iv) / 100.0
        model = black76(leg.kind, s, leg.k, max(days, 0.0) / DAYS_IN_YEAR, iv, r)
        total += leg.sign * (model.price - leg.premium) * leg.qty
    return total


def nearest_expiry_payoff(legs: list[Leg], s: float, default_days: float, default_iv: float,
                          r: float = R_DEFAULT) -> float:
    """₹ P&L at the NEAREST expiry in the book. Same-expiry legs pay intrinsic; a leg with
    more days left (calendar spread) is valued with Black-76 at its residual time."""
    t_star = min((leg.days if leg.days is not None else default_days)
                 for leg in legs if leg.kind != "FUT") if any(l.kind != "FUT" for l in legs) else 0.0
    total = 0.0
    for leg in legs:
        if leg.kind == "FUT":
            total += leg.sign * (s - leg.premium) * leg.qty
            continue
        days = leg.days if leg.days is not None else default_days
        residual = max(days - t_star, 0.0)
        if residual <= 1e-9:
            unit = (max(s - leg.k, 0.0) if leg.kind == "CE"
                    else max(leg.k - s, 0.0)) - leg.premium
        else:
            iv = (leg.iv if leg.iv is not None and leg.iv > 0 else default_iv) / 100.0
            unit = black76(leg.kind, s, leg.k, residual / DAYS_IN_YEAR, iv, r).price - leg.premium
        total += leg.sign * unit * leg.qty
    return total


def is_single_expiry(legs: list[Leg], default_days: float) -> bool:
    days = {round(leg.days if leg.days is not None else default_days, 4)
            for leg in legs if leg.kind != "FUT"}
    return len(days) <= 1


def breakevens_any(legs: list[Leg], default_days: float, default_iv: float,
                   r: float = R_DEFAULT) -> list[float]:
    """Breakevens: exact piecewise-linear roots for single-expiry books; for a calendar
    book (mixed expiries) the nearest-expiry curve is smooth, so bisect each sign change
    to 1e-7 relative — still a root-find, never a sampled guess."""
    if is_single_expiry(legs, default_days):
        return breakevens(legs)
    anchors = kink_points(legs)                         # a calendar book always has strikes
    lo = max(min(anchors) * 0.4, 0.01)
    hi = max(anchors) * 1.8

    def f(x: float) -> float:
        return nearest_expiry_payoff(legs, x, default_days, default_iv, r)

    xs = [lo + (hi - lo) * i / 400 for i in range(401)]
    roots: list[float] = []
    for a, b in zip(xs, xs[1:]):
        fa, fb = f(a), f(b)
        if fa == 0.0:
            roots.append(a)
        elif fa * fb < 0:
            x0, x1 = a, b
            for _ in range(80):
                mid = (x0 + x1) / 2
                if f(x0) * f(mid) <= 0:
                    x1 = mid
                else:
                    x0 = mid
                if (x1 - x0) <= 1e-7 * max(1.0, x1):
                    break
            roots.append((x0 + x1) / 2)
    return roots


# ── Greeks per leg + net ─────────────────────────────────────────────────────────────────


GREEK_KEYS = ("delta", "gamma", "theta_day", "vega", "rho")


def leg_greeks(leg: Leg, f: float, default_days: float, default_iv: float,
               r: float = R_DEFAULT) -> dict[str, float | None]:
    """Signed ₹-space Greeks of one leg at forward f. delta/gamma in underlying units,
    theta ₹/day, vega ₹/vol-point, rho ₹ per +1% rate. `price` is the Black-76 model value
    per unit (None for FUT). FUT: delta ±qty, all else 0 (carry ignored — stated)."""
    if leg.kind == "FUT":
        return {"delta": float(leg.sign * leg.qty), "gamma": 0.0, "theta_day": 0.0,
                "vega": 0.0, "rho": 0.0, "price": None}
    days = leg.days if leg.days is not None else default_days
    iv = (leg.iv if leg.iv is not None and leg.iv > 0 else default_iv) / 100.0
    g = black76(leg.kind, f, leg.k, max(days, 0.0) / DAYS_IN_YEAR, iv, r)
    q = leg.sign * leg.qty
    return {"delta": g.delta * q, "gamma": g.gamma * q, "theta_day": g.theta_day * q,
            "vega": g.vega * q, "rho": g.rho * q, "price": g.price}


def net_greeks(legs: list[Leg], f: float, default_days: float, default_iv: float,
               r: float = R_DEFAULT) -> dict[str, float]:
    per = [leg_greeks(leg, f, default_days, default_iv, r) for leg in legs]
    return {k: sum(float(p[k] or 0.0) for p in per) for k in GREEK_KEYS}


# ── entry cashflow ───────────────────────────────────────────────────────────────────────


def entry_cashflow(legs: list[Leg]) -> float:
    """₹ at entry from option premiums only (positive = net credit). Futures carry no
    premium cashflow (margin, handled separately)."""
    return sum(-leg.sign * leg.premium * leg.qty for leg in legs if leg.kind != "FUT")


# ── margin ESTIMATE (SPAN-like heuristic — labelled, never exchange truth) ───────────────

FUT_MARGIN_PCT_INDEX = 12.0   # ≈ NSE index futures initial margin (SPAN+exposure), Oct 2026
FUT_MARGIN_PCT_STOCK = 20.0   # single stocks run higher; both are heuristics, not SPAN files


@dataclass(frozen=True)
class MarginEstimate:
    total: float                 # ₹ — the headline estimate
    per_leg: list[float] = field(default_factory=list)
    premium_outflow: float = 0.0  # long-option premium paid (part of total)
    defined_risk_floor: float | None = None  # |max loss| when bounded: SPAN can't ask less
    note: str = ""


def margin_estimate(legs: list[Leg], f: float, fut_margin_pct: float,
                    max_loss: Extreme) -> MarginEstimate:
    """ESTIMATE only. Long option = premium paid. Short option ≈ futures-margin% of
    notional + premium received. Future ≈ futures-margin% of notional. Real SPAN gives
    spread benefit a heuristic cannot see — for a defined-risk book the |max loss| floor
    is shown so the over-estimate is visible."""
    per: list[float] = []
    outflow = 0.0
    for leg in legs:
        notional = f * leg.qty
        if leg.kind == "FUT":
            per.append(fut_margin_pct / 100.0 * notional)
        elif leg.side == "buy":
            paid = leg.premium * leg.qty
            per.append(paid)
            outflow += paid
        else:
            per.append(fut_margin_pct / 100.0 * notional + leg.premium * leg.qty)
    floor = None if max_loss.unbounded or max_loss.value is None else abs(min(max_loss.value, 0.0))
    note = ("ESTIMATE — SPAN-like heuristic (futures margin % of notional + premium for shorts; "
            "premium for longs). Exchange SPAN nets spreads: a defined-risk book usually needs "
            "far less, never less than its max loss.")
    return MarginEstimate(total=round(sum(per), 2), per_leg=[round(p, 2) for p in per],
                          premium_outflow=round(outflow, 2),
                          defined_risk_floor=None if floor is None else round(floor, 2), note=note)


# ── NSE F&O transaction-cost ESTIMATE (statutory rates FY 2025-26, encoded here because
#    shared/trading_costs.py models cash equity only — that gap is stated in the payload) ──

OPT_STT_SELL_PCT = 0.1        # of sell-side premium (raised 1 Oct 2024)
OPT_TXN_PCT = 0.03503         # NSE transaction charge, % of premium, both sides
OPT_IPFT_PCT = 0.0005         # ₹50 per crore of premium
FUT_STT_SELL_PCT = 0.02      # of sell-side notional (raised 1 Oct 2024)
FUT_TXN_PCT = 0.00173         # % of notional, both sides
FUT_IPFT_PCT = 0.0001         # ₹10 per crore
SEBI_PCT = 0.0001             # ₹10 per crore, both products, both sides
STAMP_BUY_OPT_PCT = 0.003     # of buy-side premium
STAMP_BUY_FUT_PCT = 0.002     # of buy-side notional
GST_PCT = 18.0                # on brokerage + txn + SEBI


def _one_side(kind: Kind, side: Side, value: float, brokerage: float) -> dict[str, float]:
    """Charges for one side (entry or exit) of one leg. `value` = premium×qty for options,
    notional for futures."""
    opt = kind != "FUT"
    stt = value * (OPT_STT_SELL_PCT if opt else FUT_STT_SELL_PCT) / 100.0 if side == "sell" else 0.0
    txn = value * (OPT_TXN_PCT if opt else FUT_TXN_PCT) / 100.0
    ipft = value * (OPT_IPFT_PCT if opt else FUT_IPFT_PCT) / 100.0
    sebi = value * SEBI_PCT / 100.0
    stamp = value * (STAMP_BUY_OPT_PCT if opt else STAMP_BUY_FUT_PCT) / 100.0 if side == "buy" else 0.0
    gst = (brokerage + txn + sebi) * GST_PCT / 100.0
    total = brokerage + stt + txn + ipft + sebi + stamp + gst
    return {"brokerage": brokerage, "stt": stt, "txn": txn, "ipft": ipft, "sebi": sebi,
            "stamp": stamp, "gst": gst, "total": total}


def costs_estimate(legs: list[Leg], brokerage_per_order: float = 20.0) -> dict:
    """Round-trip (entry + square-off at the same price) cost ESTIMATE in ₹, itemised.
    Exercise STT at expiry (0.125% of intrinsic, ITM) is NOT modelled — stated in the note."""
    buckets = {"brokerage": 0.0, "stt": 0.0, "txn": 0.0, "ipft": 0.0, "sebi": 0.0,
               "stamp": 0.0, "gst": 0.0, "total": 0.0}
    entry = exit_ = 0.0
    for leg in legs:
        # options: premium value; futures: notional (premium holds the entry price)
        value = leg.premium * leg.qty
        flip: Side = "sell" if leg.side == "buy" else "buy"
        a = _one_side(leg.kind, leg.side, value, brokerage_per_order)
        b = _one_side(leg.kind, flip, value, brokerage_per_order)
        entry += a["total"]
        exit_ += b["total"]
        for k in buckets:
            buckets[k] += a[k] + b[k]
    return {"estimate": True,
            "entry": round(entry, 2), "exit": round(exit_, 2),
            "round_trip": {k: round(v, 2) for k, v in buckets.items()},
            "brokerage_per_order": brokerage_per_order,
            "note": ("ESTIMATE — NSE F&O statutory rates FY25-26, square-off assumed at entry "
                     "prices; exercise STT at expiry (0.125% of intrinsic) not included. "
                     "shared/trading_costs.py covers cash equity only (gap stated)."),
            }


# ── payoff grid ──────────────────────────────────────────────────────────────────────────


def payoff_grid(legs: list[Leg], f: float, default_days: float, default_iv: float,
                r: float = R_DEFAULT, points: int = 101) -> list[dict[str, float]]:
    """To-scale grid of {s, expiry, now}: ±max(2.5σ, 12%) around the forward, stretched to
    cover every strike and breakeven with 4% head-room; kinks and breakevens are grid
    points themselves so the chart's corners and zero-crossings are exact."""
    sd = f * max(0.02, default_iv / 100.0 * math.sqrt(max(default_days, 1.0) / DAYS_IN_YEAR))
    lo, hi = f - 2.5 * sd, f + 2.5 * sd
    lo = min(lo, f * 0.88)
    hi = max(hi, f * 1.12)
    bes = breakevens_any(legs, default_days, default_iv, r)
    for anchor in kink_points(legs) + bes:
        lo = min(lo, anchor * 0.96)
        hi = max(hi, anchor * 1.04)
    lo = max(lo, 0.01)
    base = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
    s_values = sorted(set(round(s, 6) for s in base
                          + [k for k in kink_points(legs) if lo <= k <= hi]
                          + [b for b in bes if lo <= b <= hi]))
    single = is_single_expiry(legs, default_days)
    out = []
    for s in s_values:
        at_exp = expiry_payoff(legs, s) if single else nearest_expiry_payoff(
            legs, s, default_days, default_iv, r)
        out.append({"s": round(s, 2),
                    "expiry": round(at_exp, 2),
                    "now": round(book_value_now(legs, s, default_days, default_iv, r), 2)})
    return out
