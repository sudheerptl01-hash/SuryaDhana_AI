"""
C6 — backtest↔live parity tests for scheduled market impact.

Covers:
  • scheduled_impact module: scheduler reuse, multi-session work, partial-fill residual,
    small-order ⇒ identical to the legacy single-hit, graceful fallback.
  • simulate_portfolio wiring: at-scale block routes through the scheduler, small order is
    bit-for-bit identical to legacy, a raising scheduler falls back cleanly, slippage_sink
    receives one telemetry row per scheduled fill.
  • Parity with the live path: the engine's realised price reconciles with what
    execution_scheduler.simulate_execution produces for the same parent order.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_engine as be  # noqa: E402
import scheduled_impact as si  # noqa: E402


# ── Shared fixtures (mirror tests/test_backtest_engine.py helpers) ─────────────────
def _dates(n):
    import pandas as pd
    return [pd.Timestamp("2024-01-01") + pd.Timedelta(days=i) for i in range(n + 5)]


def _flat_price(idx, ticker):
    return 1000.0


def _entry(ticker, ret, exit_idx=2, atr_pct=2.0, adv=None, entry_price=1000.0):
    e = {
        "ticker": ticker,
        "entry_price": entry_price,
        "exit_idx": exit_idx,
        "net_return_pct": ret,
        "gross_return_pct": ret,
        "exit_price": entry_price * (1 + ret / 100.0),
        "exit_reason": "time_stop",
        "entry_date": "2024-01-01",
        "exit_date": "2024-01-03",
        "holding_days": exit_idx,
        "win_threshold": 0.0,
        "atr_pct": atr_pct,
    }
    if adv is not None:
        e["adv"] = adv
    return e


# ── Module: scheduler availability + single-hit reference ──────────────────────────
def test_scheduler_is_available_in_test_env():
    # The import shim must resolve execution_scheduler in the local-dev layout.
    assert si.SCHEDULER_AVAILABLE is True
    assert si.REFERENCE_BUCKETS == 13


def test_single_hit_matches_engine_formula():
    # The module's legacy reference must equal the engine's inline √-law round-trip.
    alloc, adv, atr, y = 200_000.0, 1_000_000.0, 2.0, 1.0
    expected = 2.0 * y * atr * (alloc / adv) ** 0.5
    assert si._single_hit_impact_pct(alloc, adv, atr, y) == pytest.approx(expected, rel=1e-12)


def test_single_hit_degenerate_inputs_return_zero():
    assert si._single_hit_impact_pct(0.0, 1e6, 2.0, 1.0) == 0.0
    assert si._single_hit_impact_pct(1e5, 0.0, 2.0, 1.0) == 0.0
    assert si._single_hit_impact_pct(1e5, 1e6, 0.0, 1.0) == 0.0


# ── Module: at-scale block is worked over multiple sessions, partial fill ──────────
def test_large_block_is_worked_over_multiple_sessions_with_residual():
    # ₹20Cr into a ₹18.37Cr-ADV name = 108.9% of ADV — impossible in one bar. At a 10%
    # daily cap over <=5 sessions it cannot fully fill; an honest residual remains.
    adv, alloc, atr, px = 18.37e7, 20e7, 3.24, 1000.0
    fill = si.schedule_block_impact(alloc, adv, atr, px, y_i=1.0)
    assert fill.scheduled is True
    assert fill.n_sessions > 1                     # spread across sessions
    assert fill.n_slices > si.REFERENCE_BUCKETS     # more than one session of slices
    assert 0.0 < fill.fill_ratio < 1.0              # partial — cannot complete in horizon
    assert fill.unfilled_notional > 0.0             # honest residual
    assert fill.impact_pct > 0.0
    assert math.isfinite(fill.impact_pct)


def test_scheduled_cost_is_far_below_the_instantaneous_fiction():
    # The whole point of C6: the single-hit charges a huge cost on a fill that is
    # physically impossible; the scheduled path charges the realised cost on what
    # actually fills against thinning liquidity — materially smaller, and honest.
    adv, alloc, atr, px = 18.37e7, 20e7, 3.24, 1000.0
    old = si._single_hit_impact_pct(alloc, adv, atr, 1.0)
    new = si.schedule_block_impact(alloc, adv, atr, px, y_i=1.0).impact_pct
    assert old > 5.0                                # the old single-hit fiction
    assert new < old                                # scheduled realised cost is lower
    assert new > 0.0


def test_small_block_scheduled_collapses_to_a_single_session_fill():
    # A small order (well under one session's 10% ADV cap) fills in one session, fully.
    adv, alloc, atr, px = 1e9, 1e6, 2.0, 1000.0     # 0.1% of ADV
    fill = si.schedule_block_impact(alloc, adv, atr, px, y_i=1.0)
    assert fill.scheduled is True
    assert fill.n_sessions == 1
    assert fill.fill_ratio == pytest.approx(1.0, abs=1e-6)
    assert fill.unfilled_notional == 0.0


def test_degenerate_inputs_fall_back_to_single_hit():
    # Zero ADV / zero alloc / zero price → not schedulable → legacy single-hit, scheduled=False.
    f1 = si.schedule_block_impact(1e7, 0.0, 2.0, 1000.0, y_i=1.0)
    assert f1.scheduled is False
    f2 = si.schedule_block_impact(0.0, 1e8, 2.0, 1000.0, y_i=1.0)
    assert f2.scheduled is False
    f3 = si.schedule_block_impact(1e7, 1e8, 2.0, 0.0, y_i=1.0)
    assert f3.scheduled is False


def test_scheduled_reconciles_with_simulate_execution_for_same_parent():
    # Parity proof: the module's realised one-way impact for a one-session block must
    # equal what execution_scheduler.simulate_execution returns directly (same VWAP),
    # proving the backtest now agrees with the live scheduler.
    from execution_scheduler import ExecutionAlgo, simulate_execution

    adv, alloc, atr, px = 5e8, 2e7, 3.0, 1000.0     # 4% of ADV — completes in one session
    fill = si.schedule_block_impact(alloc, adv, atr, px, y_i=1.0, algo="VWAP")
    assert fill.n_sessions == 1

    adv_shares = adv / px
    block_shares = int(round(alloc / px))
    report = simulate_execution(
        symbol="BLOCK", side="BUY", quantity=block_shares, arrival_price=px,
        algo=ExecutionAlgo.VWAP, n_slices=si.REFERENCE_BUCKETS, adv=adv_shares,
        volatility_bps=atr * 100.0, impact_coef=1.0,
        participation_cap=0.10, max_participation=0.10,
    )
    # Same realised VWAP → same one-way impact %.
    expected_pct = (report.avg_fill_price - px) / px * 100.0
    assert fill.realised_vwap == pytest.approx(report.avg_fill_price, rel=1e-9)
    assert fill.impact_pct == pytest.approx(max(0.0, expected_pct), rel=1e-9)


# ── Engine wiring: regression + parity ────────────────────────────────────────────
def test_engine_small_order_identical_with_or_without_scheduler():
    # alloc/ADV below SCHEDULED_IMPACT_TRIGGER (1%) ⇒ scheduler skipped ⇒ identical cost.
    adv = 1e11                                        # huge ADV → 200k alloc is 2e-4% of ADV
    entries = {0: [_entry("X", 5.0, adv=adv, atr_pct=2.0)]}
    _, t_legacy = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                        starting_capital=1_000_000, max_positions=5,
                                        impact_coef=1.0)
    _, t_sched = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                       starting_capital=1_000_000, max_positions=5,
                                       impact_coef=1.0,
                                       scheduled_impact_fn=si.schedule_block_impact)
    assert t_sched[0]["impact_pct"] == pytest.approx(t_legacy[0]["impact_pct"], rel=1e-9)


def test_engine_at_scale_block_routes_through_scheduler_and_lowers_impact():
    # A ₹2Cr fill into a ₹1Cr-ADV name (200% of ADV) → the single hit is a huge fiction;
    # routing through the scheduler charges the realised multi-session cost (lower, honest).
    adv = 1e7                                         # ₹1Cr ADV (in rupees)
    entries = {0: [_entry("THIN", 5.0, adv=adv, atr_pct=3.0, entry_price=1000.0)]}
    # No ADV cap so the full 2e7 alloc lands → 200% participation, deliberately at scale.
    _, t_legacy = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                        starting_capital=1e8, max_positions=5,
                                        impact_coef=1.0)
    _, t_sched = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                       starting_capital=1e8, max_positions=5,
                                       impact_coef=1.0,
                                       scheduled_impact_fn=si.schedule_block_impact)
    assert t_legacy[0]["impact_pct"] > t_sched[0]["impact_pct"]
    assert t_sched[0]["impact_pct"] > 0.0


def test_engine_raising_scheduler_falls_back_to_single_hit():
    # A scheduler callable that raises must NOT crash the sim — it falls back to the
    # inline single-hit, producing exactly the legacy impact.
    def _boom(**kwargs):
        raise RuntimeError("scheduler exploded")

    adv = 1e7
    entries = {0: [_entry("X", 5.0, adv=adv, atr_pct=3.0)]}
    _, t_legacy = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                        starting_capital=1e8, max_positions=5,
                                        impact_coef=1.0)
    _, t_boom = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1e8, max_positions=5,
                                      impact_coef=1.0, scheduled_impact_fn=_boom)
    assert t_boom[0]["impact_pct"] == pytest.approx(t_legacy[0]["impact_pct"], rel=1e-9)


def test_engine_slippage_sink_receives_one_row_per_scheduled_fill():
    captured = []
    adv = 1e7
    entries = {0: [_entry("THIN", 5.0, adv=adv, atr_pct=3.0)]}
    be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                          starting_capital=1e8, max_positions=5, impact_coef=1.0,
                          scheduled_impact_fn=si.schedule_block_impact,
                          slippage_sink=captured.append)
    assert len(captured) == 1
    row = captured[0]
    for key in ("ticker", "arrival_price", "realised_vwap", "participation",
                "n_slices", "n_sessions", "fill_ratio", "is_bps", "y_i"):
        assert key in row
    assert row["ticker"] == "THIN"
    assert row["n_slices"] >= 1


def test_engine_none_scheduler_is_exact_legacy_default():
    # The default (no scheduler) path must be byte-for-byte the pre-C6 behaviour.
    adv = 1e7
    entries = {0: [_entry("X", 5.0, adv=adv, atr_pct=3.0)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1e8, max_positions=5,
                                      impact_coef=1.0)
    expected = 2.0 * 1.0 * 3.0 * (trades[0]["capital_allocated"] / adv) ** 0.5
    # impact_pct is persisted rounded to 4dp in the trade record (round(impact_pct, 4)).
    assert trades[0]["impact_pct"] == pytest.approx(expected, abs=1e-4)
