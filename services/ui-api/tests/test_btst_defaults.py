"""BTST Desk-like defaults (5 Nov review M20): the backtest request defaults to 20 names, a 21-session hold, no per-trade
stop and the real ICICI round trip from shared/trading_costs.py, never the failed legacy 5-name / 5-day / 2 % stop /
15 bps setup. Only defaults changed: explicit values still win. Negative controls included."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shared.trading_costs import default_model  # noqa: E402

import routers.analytics as an  # noqa: E402


def test_backtest_defaults_are_desk_like():
    r = an.BacktestRequest(from_date="2025-01-01", to_date="2026-01-01")
    assert r.max_positions == 20 and r.forward_days == 21
    assert r.atr_stop_mult is None and r.stop_loss_pct is None            # no per-trade stop by default
    real = round(default_model().round_trip_pct(r.starting_capital / r.max_positions) * 100, 1)
    assert r.friction_bps == pytest.approx(real) == an.DESK_LIKE_FRICTION_BPS
    assert 85 < r.friction_bps < 100                                       # ≈ 0.91 % at ₹5 L a name
    # negative controls: none of the legacy values survives as a default
    assert r.friction_bps != 15.0 and r.max_positions != 5 and r.forward_days != 5 and r.atr_stop_mult != 2.0


def test_factor_profile_and_wfo_inherit_the_real_cost():
    assert an.FactorProfileRequest(factor="rsi_14", from_date="a", to_date="b").friction_bps == an.DESK_LIKE_FRICTION_BPS
    w = an.WFOBacktestRequest(from_date="2021-01-01", to_date="2024-01-01")
    assert w.friction_bps == an.DESK_LIKE_FRICTION_BPS and w.max_positions == 20


def test_explicit_values_still_win_and_the_floor_stays():
    r = an.BacktestRequest(from_date="a", to_date="b", friction_bps=40, max_positions=5, forward_days=5, atr_stop_mult=2.0)
    assert (r.friction_bps, r.max_positions, r.forward_days, r.atr_stop_mult) == (40, 5, 5, 2.0)
    assert an.MIN_FRICTION_BPS == 15.0                                     # the compliance floor is a floor, not a default
