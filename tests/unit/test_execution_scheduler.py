"""Unit tests for the G9 execution scheduler (pure: TWAP/VWAP/POV slicing, partial
fills, √-law slippage, implementation-shortfall reconciliation). No DB / asyncio."""
import sys
from pathlib import Path

import pytest

# execution-service has a hyphen → not an importable package; add it to the path directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "execution-service"))

from execution_scheduler import (  # noqa: E402
    ExecutionAlgo,
    build_schedule,
    default_volume_curve,
    simulate_execution,
    slippage_bps,
)


# ── Schedule construction ─────────────────────────────────────────────────────────

def test_twap_slices_conserve_quantity_and_are_uniform():
    children = build_schedule("X", "BUY", 1000, ExecutionAlgo.TWAP, n_slices=5)
    assert len(children) == 5
    assert sum(c.quantity for c in children) == 1000          # nothing lost in rounding
    assert all(c.quantity in (200,) for c in children)         # evenly split
    assert [round(c.time_offset, 2) for c in children] == [0.0, 0.2, 0.4, 0.6, 0.8]


def test_twap_backloads_rounding_remainder():
    children = build_schedule("X", "BUY", 1003, ExecutionAlgo.TWAP, n_slices=5)
    assert sum(c.quantity for c in children) == 1003
    # 1003 / 5 = 200 r3 → last three slices carry the +1.
    assert [c.quantity for c in children] == [200, 200, 201, 201, 201]


def test_vwap_tracks_volume_curve_and_conserves_quantity():
    curve = [0.4, 0.1, 0.1, 0.4]
    children = build_schedule("X", "BUY", 1000, ExecutionAlgo.VWAP, n_slices=4, volume_curve=curve)
    assert sum(c.quantity for c in children) == 1000
    q = {c.slice_idx: c.quantity for c in children}
    # Heavy buckets (0 and 3) get ~4× the shares of the light midday buckets.
    assert q[0] == 400 and q[3] == 400
    assert q[1] == 100 and q[2] == 100


def test_pov_caps_each_slice_to_participation_of_volume():
    # ADV 100k, U-curve, 10% participation cap → each slice ≤ 10% of its bucket volume.
    children = build_schedule("X", "BUY", 100_000, ExecutionAlgo.POV, n_slices=6,
                              participation_cap=0.10, adv=100_000)
    curve = default_volume_curve(6)
    for c in children[:6]:
        cap = 0.10 * 100_000 * curve[c.slice_idx]
        assert c.quantity <= cap + 1                          # never exceeds the POV cap
    # A parent larger than the horizon's capped capacity leaves a clean-up slice.
    assert sum(c.quantity for c in children) == 100_000


def test_immediate_is_single_slice():
    children = build_schedule("X", "SELL", 500, ExecutionAlgo.IMMEDIATE)
    assert len(children) == 1 and children[0].quantity == 500


def test_default_volume_curve_normalised_and_u_shaped():
    c = default_volume_curve(7)
    assert len(c) == 7
    assert sum(c) == pytest.approx(1.0, abs=1e-9)
    assert c[0] > c[3] and c[-1] > c[3]                       # open & close heavier than midday


# ── Slippage model ────────────────────────────────────────────────────────────────

def test_slippage_is_sqrt_law_and_nonnegative():
    # 4× the participation → 2× the slippage (√-law).
    s1 = slippage_bps(0.01, volatility_bps=100.0)
    s4 = slippage_bps(0.04, volatility_bps=100.0)
    assert s4 == pytest.approx(2 * s1, rel=1e-9)
    assert slippage_bps(-1.0, 100.0) == 0.0                   # clamped non-negative


# ── Full execution simulation ──────────────────────────────────────────────────────

def test_buy_pays_up_sell_receives_less():
    buy = simulate_execution("X", "BUY", 10_000, 100.0, adv=200_000, volatility_bps=100.0)
    sell = simulate_execution("X", "SELL", 10_000, 100.0, adv=200_000, volatility_bps=100.0)
    assert buy.avg_fill_price > 100.0                          # bought above arrival
    assert sell.avg_fill_price < 100.0                         # sold below arrival
    assert buy.implementation_shortfall_bps > 0               # both are costs (positive)
    assert sell.implementation_shortfall_bps > 0


def test_larger_order_has_worse_implementation_shortfall():
    small = simulate_execution("X", "BUY", 2_000, 100.0, adv=500_000, volatility_bps=120.0)
    large = simulate_execution("X", "BUY", 50_000, 100.0, adv=500_000, volatility_bps=120.0)
    assert large.implementation_shortfall_bps > small.implementation_shortfall_bps


def test_partial_fill_when_order_exceeds_liquidity():
    # Tiny ADV, 25% max participation → the parent cannot fully fill within the horizon.
    rep = simulate_execution("X", "BUY", 1_000_000, 100.0, adv=10_000, n_slices=6,
                             max_participation=0.25)
    assert rep.filled_qty < rep.requested_qty                 # left unfilled (honest)
    assert rep.fill_ratio < 1.0
    assert rep.n_partial >= 1
    assert "unfilled" in rep.notes


def test_naive_path_without_adv_fills_fully_at_arrival():
    # No ADV and IMMEDIATE → collapses to the naive full fill at arrival (zero IS).
    rep = simulate_execution("X", "BUY", 5_000, 250.0, algo=ExecutionAlgo.IMMEDIATE, adv=None)
    assert rep.filled_qty == 5_000
    assert rep.avg_fill_price == pytest.approx(250.0, abs=1e-9)
    assert rep.implementation_shortfall_bps == pytest.approx(0.0, abs=1e-9)


def test_twap_beats_immediate_on_impact_for_large_order():
    # Slicing a large order over time reduces per-slice participation → lower IS than
    # dumping it in one IMMEDIATE clip.
    big = 80_000
    twap = simulate_execution("X", "BUY", big, 100.0, algo=ExecutionAlgo.TWAP,
                              n_slices=10, adv=400_000, volatility_bps=100.0, max_participation=1.0)
    immediate = simulate_execution("X", "BUY", big, 100.0, algo=ExecutionAlgo.IMMEDIATE,
                                   adv=400_000, volatility_bps=100.0, max_participation=1.0)
    assert twap.implementation_shortfall_bps < immediate.implementation_shortfall_bps


def test_report_quantity_weighted_vwap_is_consistent():
    rep = simulate_execution("X", "BUY", 12_000, 100.0, adv=300_000, n_slices=4)
    recomputed = sum(f.filled_qty * f.fill_price for f in rep.fills) / rep.filled_qty
    assert rep.avg_fill_price == pytest.approx(recomputed, rel=1e-6)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
