"""Regression: compute_metrics CAGR must stay real and never raise on a wipe-out.

A catastrophic backtest can drive terminal NAV to ≤ 0 (full destruction, or market-impact /
leverage pushing NAV negative). The geometric CAGR `ratio**(252/n)` then returns a COMPLEX
number in Python, and the downstream round() raised `TypeError: type complex doesn't define
__round__`, crashing the whole backtest. CAGR must clamp to -100% (you can lose at most
everything) and never raise. Pure, no IO."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_engine as be  # noqa: E402


def _eq(navs):
    return [{"date": f"2024-01-{i+1:02d}", "nav": float(v), "cash": float(v), "positions": 0}
            for i, v in enumerate(navs)]


def test_cagr_negative_nav_does_not_raise_and_is_minus_100():
    # NAV goes negative (impact/leverage wipe-out beyond -100%).
    m = be.compute_metrics(_eq([1_000_000, 500_000, -200_000]), [], [], 1_000_000.0)
    assert m["cagr_pct"] == -100.0
    assert isinstance(m["cagr_pct"], float)
    # total_return is allowed to be < -100% (it's arithmetic, not geometric)
    assert m["total_return_pct"] < -100.0


def test_cagr_zero_nav_is_minus_100():
    m = be.compute_metrics(_eq([1_000_000, 100_000, 0.0]), [], [], 1_000_000.0)
    assert m["cagr_pct"] == -100.0


def test_cagr_positive_path_unchanged():
    # A healthy doubling over ~252 bars ⇒ ~+100% CAGR, real-valued, untouched by the guard.
    navs = list(np.linspace(1_000_000, 2_000_000, 253))
    m = be.compute_metrics(_eq(navs), [], [], 1_000_000.0)
    assert m["cagr_pct"] > 90.0 and np.isfinite(m["cagr_pct"])


def test_cagr_all_metric_values_are_finite_real_on_wipeout():
    m = be.compute_metrics(_eq([1_000_000, 10, -1_000_000]), [], [], 1_000_000.0)
    for k, v in m.items():
        if isinstance(v, (int, float)):
            assert not isinstance(v, complex)
            assert np.isfinite(v) or k in ("profit_factor",)  # PF may be inf with no losses
