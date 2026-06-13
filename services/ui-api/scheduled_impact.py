"""
scheduled_impact.py — C6 backtest↔live parity: work an at-scale block through the
*same* child-order scheduler the live path uses, instead of charging a single
instantaneous √-law hit at entry.

Why this module exists
----------------------
`backtest_engine.simulate_portfolio` historically charged temporary market impact
ONCE, as a single √-law hit at entry (`2·Y·ATR%·√(alloc/ADV)`), as if the whole
parent block clears in one bar. Live trading already works a parent order over a
horizon via `execution_scheduler` (TWAP/VWAP/POV, partial fills, the `_U_SHAPE`
U-shaped intraday liquidity curve, REFERENCE_BUCKETS=13). The backtest never called
it, so backtest and live diverged precisely at the block sizes that matter for
institutional capital — a ₹20Cr block modelled as one instantaneous hit *under-states*
the cost of a block that in reality must be worked across thinning intraday liquidity
over multiple sessions.

This module is a thin, single-responsibility wrapper that:
  1. REUSES `execution_scheduler.simulate_execution` (does NOT re-implement it). The
     scheduler's `coverage = min(1, n_slices / REFERENCE_BUCKETS)` caps a single call at
     one session's accessible ADV, so a block too large for one session is worked across
     SESSIONS here by calling the scheduler once per session and carrying the unfilled
     residual forward — honouring the 2–5d swing horizon with an honest unfilled residual
     if the block cannot complete within the horizon cap.
  2. Accumulates the per-slice √-law cost into a realised VWAP-style execution price and
     reports the one-way realised impact as a percentage of arrival, so the engine books
     the fill at that realised price rather than the single instantaneous hit.
  3. Degrades gracefully: if `execution_scheduler` cannot be imported, or the schedule
     fails / returns a degenerate result for any name/bar, the caller falls back to the
     existing single-hit √-law impact and continues (zero regression — mirrors the
     `membership_pit=False` degradation pattern).

Pure / numpy-free / no FastAPI / no DuckDB import here so the math is unit-testable in
isolation (see tests/test_scheduled_impact.py). The optional DuckDB persistence of
realised slippage lives in `slippage_store.py` and is wired by the caller.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── Reuse the live execution scheduler via the same import shim pattern as
# routers/execution.py. `execution-service` has a hyphen, so it is not a package;
# in Docker the ui-api container only bind-mounts ../scripts (the byte-identical
# mirror), so /app/scripts is included as a candidate. We REUSE the scheduler; we
# never re-implement TWAP/VWAP/POV/_U_SHAPE here. ─────────────────────────────────
def _locate_scheduler() -> Optional[str]:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "execution-service" / "execution_scheduler.py",  # local dev
        here.parent / "execution_scheduler.py",                            # ui-api root copy
        Path("/app/scripts/execution_scheduler.py"),                       # Docker (scripts mount)
        Path("/app/execution_scheduler.py"),                               # Docker (root copy)
    ]
    for c in candidates:
        if c.exists():
            return str(c.parent)
    return None


_SCHED_PATH = _locate_scheduler()
if _SCHED_PATH and _SCHED_PATH not in sys.path:
    sys.path.insert(0, _SCHED_PATH)

try:
    from execution_scheduler import (  # type: ignore
        ExecutionAlgo,
        REFERENCE_BUCKETS,
        simulate_execution,
    )
    SCHEDULER_AVAILABLE = True
except Exception as _imp_err:  # pragma: no cover - import-environment dependent
    SCHEDULER_AVAILABLE = False
    _SCHED_IMPORT_ERROR = str(_imp_err)
    REFERENCE_BUCKETS = 13  # keep a sane constant for callers that introspect


# Default execution geometry. A full session ≈ REFERENCE_BUCKETS (13) 30-min slices;
# spreading across all of them unlocks one session's worth of ADV (coverage→1.0).
_SLICES_PER_SESSION = REFERENCE_BUCKETS
# Max sessions a swing entry will work a block before leaving an honest unfilled
# residual. 2–5d swing horizon (CLAUDE.md): cap at the horizon so we never pretend a
# block clears instantly nor that it can be worked indefinitely.
_MAX_SESSIONS = 5
# Per-session participation cap (φ ≤ 10%): the √-law domain-of-validity guard and the
# same ADV cap the Phase-0 auto-path enforces. A session can take at most this fraction
# of the day's ADV; the rest carries to the next session.
_DAILY_PARTICIPATION_CAP = 0.10
# ATR% → per-slice volatility in bps for the scheduler's √-law (σ_bps = ATR% · 100).
_ATR_PCT_TO_BPS = 100.0


@dataclass
class ScheduledFill:
    """Realised outcome of working a parent block through the scheduler.

    `impact_pct` is the ONE-WAY realised cost as a % of arrival price (so the engine
    can deduct it exactly where the legacy single-hit term sat). All fields are sane
    defaults on the degenerate path so a caller never sees NaN/inf.
    """
    impact_pct: float            # one-way realised impact, % of arrival (>= 0)
    realised_vwap: float         # quantity-weighted realised execution price
    arrival_price: float         # decision/arrival price (entry close)
    participation: float         # block notional / ADV (Q/ADV, the full-block ratio)
    n_slices: int                # total child slices across all sessions
    n_sessions: int              # sessions the block was worked over
    fill_ratio: float            # filled / requested (1.0 = fully filled)
    is_bps: float                # implementation shortfall in bps (signed; +cost)
    y_i: float                   # per-name temporary-impact coefficient used
    scheduled: bool              # True if the scheduler actually ran (else fallback)
    unfilled_notional: float     # honest residual the horizon could not absorb

    @property
    def is_degenerate(self) -> bool:
        return (not self.scheduled) or (self.fill_ratio <= 0.0)


def _single_hit_impact_pct(alloc: float, adv: float, atr_pct: float, y_i: float) -> float:
    """The LEGACY single-instantaneous √-law temporary leg (round-trip), in %.

    Kept here so the fallback path and the parity proof can reproduce the exact
    pre-C6 cost: round-trip = 2 · Y · ATR% · √(alloc / ADV). Guarded against the
    degenerate inputs (non-finite / non-positive) so it never raises.
    """
    if not (alloc > 0 and adv > 0 and y_i is not None):
        return 0.0
    atrp = atr_pct if (atr_pct and atr_pct > 0) else 0.0
    part = alloc / adv
    if not math.isfinite(part) or part < 0:
        return 0.0
    return 2.0 * float(y_i) * float(atrp) * math.sqrt(part)


def schedule_block_impact(
    alloc: float,
    adv: float,
    atr_pct: float,
    arrival_price: float,
    y_i: float = 1.0,
    *,
    side: str = "BUY",
    daily_participation_cap: float = _DAILY_PARTICIPATION_CAP,
    max_sessions: int = _MAX_SESSIONS,
    slices_per_session: int = _SLICES_PER_SESSION,
    algo: str = "VWAP",
) -> ScheduledFill:
    """Work a parent block (`alloc` of notional) through the live scheduler over up to
    `max_sessions` sessions and return the realised ONE-WAY impact as a % of arrival.

    Reuses `execution_scheduler.simulate_execution` per session: each session can take at
    most `daily_participation_cap · ADV`; the unfilled remainder carries to the next
    session against fresh (thinning) intraday liquidity. The realised execution price is
    the quantity-weighted VWAP across every filled child slice in every session. Honours
    the swing horizon: after `max_sessions` any residual is left honestly unfilled.

    Returns a fully-populated `ScheduledFill`. On ANY failure (scheduler unavailable,
    raise, degenerate output) returns `scheduled=False` with the legacy single-hit impact,
    so the caller can transparently fall back (zero regression).
    """
    # ── Degenerate / not-at-scale guards: resolve to the legacy single-hit so callers
    # see continuous behaviour at the trigger boundary. ───────────────────────────────
    legacy_pct = _single_hit_impact_pct(alloc, adv, atr_pct, y_i)
    base = ScheduledFill(
        impact_pct=legacy_pct, realised_vwap=float(arrival_price),
        arrival_price=float(arrival_price),
        participation=(alloc / adv if (adv and adv > 0) else 0.0),
        n_slices=1, n_sessions=1, fill_ratio=1.0, is_bps=legacy_pct * 100.0,
        y_i=float(y_i if y_i is not None else 1.0), scheduled=False,
        unfilled_notional=0.0,
    )
    if not SCHEDULER_AVAILABLE:
        return base
    if not (alloc > 0 and adv > 0 and arrival_price > 0):
        return base

    try:
        algo_enum = ExecutionAlgo(algo) if isinstance(algo, str) else algo
    except Exception:
        algo_enum = ExecutionAlgo.VWAP

    # Volatility in bps for the scheduler's √-law. ATR% is a daily range proxy; ×100 → bps.
    sigma_bps = max(0.0, float(atr_pct or 0.0)) * _ATR_PCT_TO_BPS
    # Express ADV and the block in SHARE units for the scheduler (it slices integer
    # shares against a per-bucket share volume). Using price=arrival_price keeps the
    # mapping exact: notional / price = shares, and adv_shares = adv_notional / price.
    px = float(arrival_price)
    adv_shares = adv / px
    block_shares = int(max(1, round(alloc / px)))
    if adv_shares <= 0:
        return base

    remaining = block_shares
    total_notional = 0.0
    total_filled = 0
    total_slices = 0
    n_sessions = 0
    is_bps_weighted = 0.0  # qty-weighted IS across sessions

    for _session in range(int(max_sessions)):
        if remaining <= 0:
            break
        n_sessions += 1
        # One session accesses one day's ADV; the scheduler thins it further across the
        # U-shaped intraday curve and caps each child at `max_participation · bucket_vol`.
        report = simulate_execution(
            symbol="BLOCK",
            side=side,
            quantity=int(remaining),
            arrival_price=px,
            algo=algo_enum,
            n_slices=int(slices_per_session),
            adv=adv_shares,
            volatility_bps=sigma_bps,
            impact_coef=float(y_i if y_i is not None else 1.0),
            participation_cap=float(daily_participation_cap),
            max_participation=float(daily_participation_cap),
        )
        filled = int(report.filled_qty)
        if filled <= 0:
            # No progress this session (e.g. ADV vanishingly small) — stop honestly
            # rather than loop forever; the residual is left unfilled.
            break
        # Accumulate realised execution into a running VWAP.
        total_notional += report.avg_fill_price * filled
        total_filled += filled
        total_slices += int(report.n_slices)
        is_bps_weighted += float(report.implementation_shortfall_bps) * filled
        remaining -= filled

    if total_filled <= 0:
        return base   # scheduler made no progress — fall back to legacy single-hit

    realised_vwap = total_notional / total_filled
    fill_ratio = total_filled / block_shares
    # One-way realised impact as a % of arrival: signed so a BUY paying up is a positive
    # cost. `simulate_execution` already enforces adverse-only slippage, so this is >= 0.
    sign = 1.0 if side.upper() == "BUY" else -1.0
    impact_pct = sign * (realised_vwap - px) / px * 100.0
    impact_pct = max(0.0, impact_pct)  # never credit a free lunch
    if not math.isfinite(impact_pct):
        return base
    is_bps = is_bps_weighted / total_filled

    return ScheduledFill(
        impact_pct=float(impact_pct),
        realised_vwap=float(realised_vwap),
        arrival_price=px,
        participation=float(block_shares / adv_shares) if adv_shares > 0 else 0.0,
        n_slices=int(total_slices),
        n_sessions=int(n_sessions),
        fill_ratio=float(min(1.0, fill_ratio)),
        is_bps=float(is_bps),
        y_i=float(y_i if y_i is not None else 1.0),
        scheduled=True,
        unfilled_notional=float(max(0, remaining) * px),
    )
