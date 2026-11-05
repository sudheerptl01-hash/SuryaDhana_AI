"""Unit tests for the ML workspace's leakage-control split (pure, no DB / xgboost)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routers.ml_workspace as mlw  # noqa: E402


def test_purged_split_inserts_embargo_gap():
    udates = np.arange(100)                       # 100 sequential trading "dates"
    split_date, purge_date, cut_i, purge_i = mlw._purged_split(
        udates, valid_fraction=0.25, horizon=5, embargo=5)
    assert cut_i == 75                            # validation = most recent 25%
    assert split_date == udates[75]
    # Purge removes horizon+embargo = 10 trading days before the split.
    assert purge_i == 65
    assert purge_date == udates[65]
    # Training (date < purge_date) and validation (date >= split_date) never touch.
    assert purge_date < split_date
    assert (split_date - purge_date) == 10


def test_purged_split_no_gap_when_horizon_and_embargo_zero():
    udates = np.arange(100)
    split_date, purge_date, cut_i, purge_i = mlw._purged_split(
        udates, valid_fraction=0.25, horizon=0, embargo=0)
    assert purge_date == split_date               # zero gap → classic seam
    assert purge_i == cut_i


def test_purged_split_clamps_to_zero_on_short_history():
    udates = np.arange(8)                          # tiny history; gap would underflow
    split_date, purge_date, cut_i, purge_i = mlw._purged_split(
        udates, valid_fraction=0.25, horizon=5, embargo=5)
    assert purge_i == 0                            # clamped, never negative
    assert purge_date == udates[0]


def test_purged_split_clamps_valid_fraction():
    udates = np.arange(50)
    # valid_fraction above the 0.5 cap must not push the validation fold past half.
    _, _, cut_i, _ = mlw._purged_split(udates, valid_fraction=0.9, horizon=5, embargo=5)
    assert cut_i == 25                             # clamped to 0.5 → 50 * 0.5


def test_train_request_leakage_defaults():
    req = mlw.TrainRequest(mode="sample")
    assert req.label_horizon == 5
    assert req.embargo_days == 5
    assert req.weight_halflife_days == 0           # decay weighting off by default
    assert req.label_kind == "direction"           # G7 defaults
    assert req.meta_labeling is False
    assert req.robust_eval is False                # G8 default off


# ── G8: purged K-fold bounds ──────────────────────────────────────────────────────

def test_purged_kfold_bounds_partition_and_gap():
    bounds = mlw._purged_kfold_bounds(n_dates=100, k=5, gap=10)
    assert len(bounds) == 5
    # Test blocks tile the whole range with no overlap.
    assert bounds[0][:2] == (0, 20) and bounds[-1][1] == 100
    for lo, hi, plo, phi in bounds:
        assert plo <= lo < hi <= phi              # purge zone brackets the test block
        assert plo == max(0, lo - 10) and phi == min(100, hi + 10)


def test_purged_kfold_bounds_handles_indivisible_and_small_k():
    bounds = mlw._purged_kfold_bounds(n_dates=53, k=4, gap=3)
    assert len(bounds) == 4 and bounds[-1][1] == 53   # last fold absorbs the remainder
    assert mlw._purged_kfold_bounds(7, 2, 1)[-1][1] == 7


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_features_explorer_v2_param():
    """v=2 reads the v2 matrix when present; absent -> honest degrade naming the build script."""
    import asyncio
    from routers import pipeline
    body = asyncio.run(pipeline.features_explorer(page=1, page_size=10, ticker="RELIANCE",
                                                  sort_by="date", sort_dir="desc", v=2))
    text = str(body)
    if "error" in text and "build_features_v2" in text:
        return                                            # honest degrade before the first build
    assert "carry_ann" in text and "y_rank_20d" in text   # v2 columns reach the grid
    body1 = asyncio.run(pipeline.features_explorer(page=1, page_size=10, ticker="RELIANCE",
                                                   sort_by="date", sort_dir="desc", v=1))
    assert "carry_ann" not in str(body1)                  # default v1 unchanged
