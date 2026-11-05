"""
SuryaDhana — Execution Scheduler (G9)

Institutional order execution: a parent order is never dropped into the market as a
single naive fill at one price. It is sliced into child orders over a horizon
(TWAP / VWAP / POV), each child fills against finite per-bucket liquidity (so large
orders fill *partially* and carry a remainder), and every fill pays volume-scaled
slippage. The realised execution VWAP is reconciled against the arrival (decision)
price to produce the **implementation shortfall** — the true cost of trading that a
flat-friction backtest hides.

Design:
  - Pure, dependency-free (stdlib `math` only) → unit-testable in isolation and keeps
    the execution-service image lean.
  - Deterministic by default (no RNG) so audits and tests are reproducible; an optional
    `liquidity_factor` lets the caller inject realised bucket volume for live reconcile.
  - Adverse-only slippage: buys always pay up, sells always receive less. There is no
    "favourable slippage" free lunch.

Microstructure model:
  - Temporary impact per child (√-law, Almgren-style):
        slip_bps = impact_coef · σ_bps · √(participation_rate)
    where participation_rate = child_qty / bucket_volume. Trading a larger slice of a
    bucket's volume moves the price more against you — the core of why size erodes edge.
  - Partial fills: a child can take at most `max_participation · bucket_volume` shares;
    anything beyond carries to the next slice (POV) or is left unfilled at horizon end.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExecutionAlgo(str, Enum):
    IMMEDIATE = "IMMEDIATE"   # single slice — the naive baseline (kept for A/B)
    TWAP = "TWAP"             # equal-size slices, uniform in time
    VWAP = "VWAP"             # slices proportional to the expected intraday volume curve
    POV = "POV"               # participation-of-volume: each slice = cap · bucket volume


# Canonical U-shaped intraday volume curve (fractions per bucket, sums to 1.0): heavy
# at the open and close, light at midday. Used by VWAP/POV when the caller supplies no
# empirical curve. 13 buckets ≈ a 6.5h session in 30-minute slices.
_U_SHAPE = [0.130, 0.090, 0.070, 0.058, 0.050, 0.045, 0.043,
            0.045, 0.050, 0.058, 0.070, 0.091, 0.150]

# A full trading day ≈ this many liquidity buckets (30-min slices over 6.5h). Liquidity
# ACCRUES with the execution horizon: a schedule spanning k buckets can access at most
# k/REFERENCE_BUCKETS of the day's ADV. This is why dumping an order IMMEDIATELY (one
# bucket) hits far thinner liquidity — and pays far more impact — than spreading it.
REFERENCE_BUCKETS = 13


def default_volume_curve(n: int) -> list[float]:
    """A length-`n` normalised U-shaped volume curve (open/close heavy)."""
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    # Resample the canonical curve onto n buckets, then renormalise.
    src = _U_SHAPE
    out = [src[int(i * (len(src) - 1) / (n - 1))] for i in range(n)]
    s = sum(out)
    return [v / s for v in out]


@dataclass
class ChildOrder:
    """One scheduled slice of a parent order."""
    slice_idx: int
    symbol: str
    side: str                 # "BUY" | "SELL"
    quantity: int             # shares this slice intends to execute
    time_offset: float        # fraction of the horizon [0,1) when this slice releases
    target_participation: float = 0.0   # intended share of the bucket's volume


@dataclass
class ChildFill:
    """The realised fill of a child order (may be partial)."""
    slice_idx: int
    requested_qty: int
    filled_qty: int
    fill_price: float
    slippage_bps: float
    participation_rate: float

    @property
    def is_partial(self) -> bool:
        return self.filled_qty < self.requested_qty


@dataclass
class ExecutionReport:
    """Parent-order execution outcome, reconciled against the arrival price."""
    symbol: str
    side: str
    algo: str
    requested_qty: int
    filled_qty: int
    arrival_price: float
    avg_fill_price: float
    implementation_shortfall_bps: float   # signed cost vs arrival (positive = cost)
    slippage_bps: float                   # quantity-weighted child slippage
    notional: float
    n_slices: int
    n_partial: int
    fills: list[ChildFill] = field(default_factory=list)
    notes: str = ""

    @property
    def fill_ratio(self) -> float:
        return (self.filled_qty / self.requested_qty) if self.requested_qty else 0.0


def build_schedule(
    symbol: str,
    side: str,
    quantity: int,
    algo: ExecutionAlgo = ExecutionAlgo.TWAP,
    n_slices: int = 6,
    volume_curve: Optional[list[float]] = None,
    participation_cap: float = 0.10,
    adv: Optional[float] = None,
) -> list[ChildOrder]:
    """Slice a parent order into child orders per the chosen algorithm.

    TWAP  — equal share counts, uniform time offsets (last slice absorbs the rounding
            remainder so Σ child qty == parent qty exactly).
    VWAP  — child sizes track `volume_curve` (defaults to a U-shape), so the schedule
            trades more when the market trades more (minimises tracking error to VWAP).
    POV   — each slice caps at `participation_cap · bucket_volume` (bucket volume =
            curve_fraction · adv); slices accumulate until the parent is exhausted, so a
            large order naturally stretches over more buckets instead of forcing size.
    IMMEDIATE — a single slice (the naive baseline).
    """
    quantity = int(quantity)
    if quantity <= 0:
        return []
    side = side.upper()

    if algo == ExecutionAlgo.IMMEDIATE or n_slices <= 1:
        return [ChildOrder(0, symbol, side, quantity, 0.0, 1.0)]

    n = max(1, int(n_slices))
    curve = volume_curve if volume_curve else default_volume_curve(n)
    # Guard: align curve length to n and renormalise.
    if len(curve) != n:
        curve = default_volume_curve(n)
    csum = sum(curve) or 1.0
    curve = [c / csum for c in curve]

    children: list[ChildOrder] = []

    if algo == ExecutionAlgo.TWAP:
        base = quantity // n
        rem = quantity - base * n
        for i in range(n):
            q = base + (1 if i >= n - rem else 0)   # back-load the remainder
            if q <= 0:
                continue
            children.append(ChildOrder(i, symbol, side, q, i / n, 1.0 / n))

    elif algo == ExecutionAlgo.VWAP:
        # Proportional allocation with largest-remainder rounding to conserve total qty.
        raw = [quantity * f for f in curve]
        floors = [int(math.floor(r)) for r in raw]
        deficit = quantity - sum(floors)
        order = sorted(range(n), key=lambda i: raw[i] - floors[i], reverse=True)
        for i in order[:deficit]:
            floors[i] += 1
        for i in range(n):
            if floors[i] <= 0:
                continue
            children.append(ChildOrder(i, symbol, side, floors[i], i / n, curve[i]))

    elif algo == ExecutionAlgo.POV:
        # Cap each slice at participation_cap · bucket volume; carry the remainder.
        remaining = quantity
        for i in range(n):
            if remaining <= 0:
                break
            bucket_vol = (adv or quantity) * curve[i]
            cap = max(1, int(participation_cap * bucket_vol))
            q = min(remaining, cap)
            children.append(ChildOrder(i, symbol, side, q, i / n, participation_cap))
            remaining -= q
        # If horizon exhausted with shares left, append a final clean-up slice (it will
        # over-participate and pay for it via slippage — surfaced in the report).
        if remaining > 0 and children:
            children.append(ChildOrder(n, symbol, side, remaining, 1.0, participation_cap))

    return children


def slippage_bps(participation_rate: float, volatility_bps: float,
                 impact_coef: float = 1.0) -> float:
    """Square-root temporary market impact in basis points (always adverse).

    slip = impact_coef · σ_bps · √(participation_rate). Clamped non-negative; a child
    that takes a larger share of the bucket's volume pays disproportionately more.
    """
    p = max(0.0, float(participation_rate))
    return max(0.0, float(impact_coef) * float(volatility_bps) * math.sqrt(p))


def simulate_execution(
    symbol: str,
    side: str,
    quantity: int,
    arrival_price: float,
    algo: ExecutionAlgo = ExecutionAlgo.TWAP,
    n_slices: int = 6,
    adv: Optional[float] = None,
    volatility_bps: float = 80.0,
    impact_coef: float = 1.0,
    participation_cap: float = 0.10,
    max_participation: float = 0.25,
    volume_curve: Optional[list[float]] = None,
    liquidity_factor: float = 1.0,
) -> ExecutionReport:
    """Simulate scheduled execution of a parent order and reconcile vs arrival price.

    Liquidity accrues with the horizon: the schedule spans k = #buckets, accessing
    k/REFERENCE_BUCKETS of the day's ADV in total. Each child fills against
    `max_participation · bucket_vol` (bucket_vol = adv · curve_fraction · coverage).
    Demand above that fills *partially*; the remainder carries to the next slice. Every
    filled child pays √-law slippage on its own participation rate. `liquidity_factor`
    (<1 thins the book, e.g. a stress day) scales realised bucket volume for live reconcile.

    Returns an ExecutionReport with the executed VWAP, fill ratio, per-child fills and
    the implementation shortfall (signed: positive = the schedule cost you money vs the
    arrival price). With `adv=None` the participation rate is unknown, so slippage is
    zero and the order fills fully at arrival — the honest naive baseline.
    """
    side = side.upper()
    sign = 1.0 if side == "BUY" else -1.0
    children = build_schedule(symbol, side, quantity, algo, n_slices,
                              volume_curve, participation_cap, adv)
    if not children:
        return ExecutionReport(symbol, side, algo.value, int(quantity), 0,
                               arrival_price, arrival_price, 0.0, 0.0, 0.0, 0, 0,
                               notes="empty schedule")

    n = len(children)
    curve = default_volume_curve(n) if not volume_curve or len(volume_curve) != n else volume_curve
    csum = sum(curve) or 1.0
    curve = [c / csum for c in curve]
    # Horizon coverage: a 1-slice (IMMEDIATE) dump can only touch one bucket of the day's
    # liquidity; spreading over more buckets unlocks proportionally more ADV.
    coverage = min(1.0, n / REFERENCE_BUCKETS)

    fills: list[ChildFill] = []
    carry = 0                       # shares carried from a partially-filled prior slice
    filled_total = 0
    notional = 0.0
    slip_qty_weighted = 0.0

    for pos, c in enumerate(children):
        want = c.quantity + carry
        carry = 0
        if want <= 0:
            continue
        # Realised bucket liquidity available to us this slice.
        if adv and adv > 0:
            bucket_vol = max(1.0, adv * curve[pos] * coverage * max(0.0, liquidity_factor))
            avail = max(1, int(max_participation * bucket_vol))
            filled = min(want, avail)
            part_rate = filled / bucket_vol if bucket_vol > 0 else 0.0
        else:
            bucket_vol = float(want)              # no ADV → participation unknown
            filled = want                         # naive full fill at arrival
            part_rate = 0.0                       # → zero slippage (honest baseline)
        if filled < want:
            carry = want - filled                 # partial: push the shortfall forward
        slip = slippage_bps(part_rate, volatility_bps, impact_coef)
        fill_price = arrival_price * (1.0 + sign * slip / 1e4)
        fills.append(ChildFill(c.slice_idx, want, filled, round(fill_price, 4), round(slip, 3), round(part_rate, 5)))
        filled_total += filled
        notional += filled * fill_price
        slip_qty_weighted += filled * slip

    # Any residual carry at horizon end is left UNFILLED (honest: you didn't get the size).
    avg_fill = (notional / filled_total) if filled_total else arrival_price
    is_bps = sign * (avg_fill - arrival_price) / arrival_price * 1e4 if arrival_price > 0 else 0.0
    slip_w = (slip_qty_weighted / filled_total) if filled_total else 0.0
    n_partial = sum(1 for f in fills if f.is_partial)

    return ExecutionReport(
        symbol=symbol, side=side, algo=algo.value,
        requested_qty=int(quantity), filled_qty=int(filled_total),
        arrival_price=round(arrival_price, 4), avg_fill_price=round(avg_fill, 4),
        implementation_shortfall_bps=round(is_bps, 3), slippage_bps=round(slip_w, 3),
        notional=round(notional, 2), n_slices=n, n_partial=n_partial, fills=fills,
        notes=(f"{filled_total}/{quantity} filled across {n} slices"
               + (f"; {quantity - filled_total} unfilled" if filled_total < quantity else "")),
    )
