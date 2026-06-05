"""Unit tests for the vectorized Factor Decile Profiler math (pure, no IO)."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import factor_decile_engine as fde  # noqa: E402


# ── Forward-return labeling ───────────────────────────────────────────────────────

def test_forward_label_netting_and_window_edge():
    # Single ticker, 2-day forward horizon, 15 bps friction.
    df = pd.DataFrame({
        "ticker": ["A"] * 6,
        "date": pd.date_range("2025-01-01", periods=6, freq="D"),
        "close": [100.0, 101.0, 102.0, 103.0, 104.0, 110.0],
    })
    out = fde.compute_forward_labels(df, forward_days=2, win_threshold_pct=0.0, friction_bps=15.0)
    # row0: fwd close=102 -> gross +2.0%, net 1.85% -> win
    assert out.iloc[0]["fwd_net_return_pct"] == pytest.approx(1.85, abs=1e-6)
    assert out.iloc[0]["label"] == 1.0
    # row3: fwd close=110 -> strongly positive -> win
    assert out.iloc[3]["label"] == 1.0
    # last two rows have no full forward window -> NaN label (no fabricated future)
    assert np.isnan(out.iloc[4]["label"])
    assert np.isnan(out.iloc[5]["label"])


def test_friction_netting_decides_marginal_label():
    # Same win definition as backtest_engine (net > threshold, no epsilon):
    #   +0.10% gross - 0.15% friction = -0.05% net -> loss
    #   +0.30% gross - 0.15% friction = +0.15% net -> win
    df = pd.DataFrame({
        "ticker": ["A", "A", "A"],
        "date": pd.date_range("2025-01-01", periods=3, freq="D"),
        "close": [100.0, 100.10, 100.40],
    })
    out = fde.compute_forward_labels(df, forward_days=1, win_threshold_pct=0.0, friction_bps=15.0)
    assert out.iloc[0]["fwd_net_return_pct"] == pytest.approx(-0.05, abs=1e-6)
    assert out.iloc[0]["label"] == 0.0                          # below threshold -> loss
    assert out.iloc[1]["fwd_net_return_pct"] == pytest.approx(0.149700, abs=1e-4)
    assert out.iloc[1]["label"] == 1.0                          # clears threshold -> win


def test_forward_labels_isolated_per_ticker():
    # The shift must not bleed across tickers.
    df = pd.DataFrame({
        "ticker": ["A", "A", "B", "B"],
        "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-01", "2025-01-02"]),
        "close": [100.0, 200.0, 50.0, 25.0],
    })
    out = fde.compute_forward_labels(df, forward_days=1, friction_bps=0.0).sort_values(["ticker", "date"])
    a0 = out[(out.ticker == "A")].iloc[0]
    b0 = out[(out.ticker == "B")].iloc[0]
    assert a0["fwd_net_return_pct"] == pytest.approx(100.0)   # 100 -> 200
    assert b0["fwd_net_return_pct"] == pytest.approx(-50.0)   # 50 -> 25
    # second row of each ticker has no forward bar
    assert out[out.ticker == "A"].iloc[1]["label"] != out[out.ticker == "A"].iloc[1]["label"]  # NaN


# ── Decile bucketing — clean case ─────────────────────────────────────────────────

def test_ten_clean_deciles_equal_population():
    # 100 distinct values, perfectly separable label at v>=50.
    values = pd.Series(np.arange(100, dtype=float))
    labels = (values >= 50).astype(float)
    prof = fde.decile_profile(values, labels, n_deciles=10)

    assert prof["n_deciles_effective"] == 10
    assert prof["total_samples"] == 100
    assert all(d["samples"] == 10 for d in prof["deciles"])
    assert prof["global_base_rate"] == pytest.approx(50.0)
    # bottom five deciles all losers, top five all winners
    assert [d["event_rate"] for d in prof["deciles"]] == [0, 0, 0, 0, 0, 100, 100, 100, 100, 100]
    assert prof["best_decile"] in (6, 7, 8, 9, 10)
    assert prof["worst_decile"] in (1, 2, 3, 4, 5)
    assert not prof["degenerate"]


def test_strictly_monotonic_event_rate_gives_spearman_one():
    # Decile d (1-indexed) gets exactly (d-1) winners out of 10 -> rates 0,10,...,90.
    vals, labs = [], []
    for d in range(10):
        for i in range(10):
            vals.append(d * 10 + i)        # keeps deciles separable
            labs.append(1.0 if i < d else 0.0)
    prof = fde.decile_profile(pd.Series(vals, dtype=float), pd.Series(labs, dtype=float), 10)
    rates = [d["event_rate"] for d in prof["deciles"]]
    assert rates == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
    assert prof["monotonicity_spearman"] == pytest.approx(1.0)
    assert prof["global_base_rate"] == pytest.approx(45.0)


def test_decile_boundaries_are_ordered():
    values = pd.Series(np.random.default_rng(0).normal(size=5000))
    labels = pd.Series((np.random.default_rng(1).random(5000) > 0.5).astype(float))
    prof = fde.decile_profile(values, labels, 10)
    his = [d["hi"] for d in prof["deciles"]]
    los = [d["lo"] for d in prof["deciles"]]
    assert his == sorted(his)          # upper edges strictly increasing across deciles
    assert los == sorted(los)
    for d in prof["deciles"]:
        assert d["lo"] <= d["obs_lo"] <= d["obs_hi"] <= d["hi"] + 1e-9


# ── Degenerate / edge cases (the ones called out in the spec) ─────────────────────

def test_identical_repeated_values_single_bucket():
    # A constant factor must NOT raise; it collapses to one bucket spanning [v, v].
    values = pd.Series([42.0] * 200)
    labels = pd.Series(([1.0] * 60) + ([0.0] * 140))
    prof = fde.decile_profile(values, labels, n_deciles=10)
    assert prof["n_deciles_effective"] == 1
    assert prof["degenerate"] is True
    d = prof["deciles"][0]
    assert d["samples"] == 200
    assert d["lo"] == pytest.approx(42.0) and d["hi"] == pytest.approx(42.0)
    assert d["event_rate"] == pytest.approx(30.0)            # 60/200
    assert prof["global_base_rate"] == pytest.approx(30.0)
    assert d["lift"] == pytest.approx(0.0)                   # equal to base by construction


def test_few_uniques_collapse_below_requested_deciles():
    # Only 3 distinct values but 10 requested -> duplicates='drop' yields <=3 buckets.
    values = pd.Series([1.0, 1.0, 1.0, 5.0, 5.0, 9.0, 9.0, 9.0, 9.0, 1.0])
    labels = pd.Series([1, 0, 1, 0, 1, 1, 0, 1, 0, 0], dtype=float)
    prof = fde.decile_profile(values, labels, 10)
    assert 1 <= prof["n_deciles_effective"] <= 3
    assert sum(d["samples"] for d in prof["deciles"]) == 10

def test_empty_and_all_nan_input():
    assert fde.decile_profile(pd.Series([], dtype=float), pd.Series([], dtype=float), 10)["total_samples"] == 0
    nan_prof = fde.decile_profile(pd.Series([np.nan, np.nan]), pd.Series([np.nan, np.nan]), 10)
    assert nan_prof["degenerate"] is True
    assert nan_prof["n_deciles_effective"] == 0


def test_nan_pairs_dropped_before_bucketing():
    values = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0])
    labels = pd.Series([1.0, np.nan, 1.0, 0.0, 1.0])
    prof = fde.decile_profile(values, labels, 2)
    # rows with any NaN in (value,label) removed -> 3 clean pairs survive
    assert prof["total_samples"] == 3


# ── End-to-end convenience ────────────────────────────────────────────────────────

def test_profile_factor_respects_as_of_window():
    rng = pd.date_range("2025-01-01", periods=20, freq="D")
    df = pd.DataFrame({
        "ticker": ["A"] * 20,
        "date": rng,
        "close": np.linspace(100, 140, 20),
        "rsi_14": np.linspace(10, 90, 20),
    })
    # Restrict the study to the first half; forward labels still use later prices.
    mask = df["date"] <= rng[9]
    prof = fde.profile_factor(df, "rsi_14", forward_days=2, win_threshold_pct=0.0,
                              friction_bps=15.0, n_deciles=5, as_of_mask=mask)
    # Only in-window rows with a full forward window contribute.
    assert prof["total_samples"] <= 10
    assert prof["total_samples"] > 0
    assert prof["n_deciles_effective"] >= 1
