"""Pillar A — daily cross-sectional decile filtering (adaptive thresholds).

Verifies that `apply_filters` in "decile" mode re-expresses a factor as its same-day
cross-sectional rank (1..10) and that the legacy "absolute" path is byte-identical, that
NaN factors are dropped (never crash), and that decile selection is order-invariant and
look-ahead-free. Pure, no IO."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_engine as be  # noqa: E402


def _day(n: int, factor_name: str = "vmi_ratio", vals=None) -> pd.DataFrame:
    """One day's cross-section of `n` names with a chosen factor column."""
    if vals is None:
        vals = list(range(1, n + 1))
    col = be.FIELD_MAP[factor_name]
    return pd.DataFrame({"ticker": [f"T{i}" for i in range(n)], col: vals})


# ── assign_decile primitive ──────────────────────────────────────────────────────

def test_assign_decile_ten_names_one_per_decile():
    s = pd.Series(np.arange(10, dtype=float))
    dec = be.assign_decile(s)
    # 10 strictly-increasing values → one per decile, 1..10
    assert sorted(dec.tolist()) == list(range(1, 11))


def test_assign_decile_top_and_bottom_extremes():
    s = pd.Series([100.0, 1.0, 50.0, 2.0, 99.0])
    dec = be.assign_decile(s)
    # highest value is always in the top decile; with only 5 names (< 10 deciles) the
    # ceil(rank_pct·10) mapping fills sparse deciles {2,4,6,8,10}, so the lowest value
    # occupies the SMALLEST present decile (not literally decile 1) — verify it is the min.
    assert dec.iloc[0] == be.DECILE_N            # 100.0 → top decile
    assert dec.iloc[1] == dec.min()              # 1.0 → smallest occupied decile
    assert dec.iloc[1] < dec.iloc[0]             # strict bottom-vs-top ordering preserved


def test_assign_decile_nan_stays_nan():
    s = pd.Series([1.0, np.nan, 3.0, 4.0])
    dec = be.assign_decile(s)
    assert np.isnan(dec.iloc[1])
    # NaN never crashes and never occupies a finite decile
    assert dec.dropna().between(1, be.DECILE_N).all()


def test_assign_decile_clipped_to_valid_range():
    s = pd.Series(np.random.RandomState(0).randn(137))
    dec = be.assign_decile(s).dropna()
    assert dec.min() >= 1 and dec.max() <= be.DECILE_N


# ── apply_filters decile mode ─────────────────────────────────────────────────────

def test_decile_top_selects_highest_tenth():
    df = _day(20)   # vmi 1..20
    filt = [{"field": "vmi_ratio", "op": "gte", "value": 10, "mode": "decile"}]
    out = be.apply_filters(df, filt)
    # top decile of 20 names = the 2 highest VMI values (19, 20)
    col = be.FIELD_MAP["vmi_ratio"]
    assert set(out[col]) == {19, 20}


def test_decile_bottom_selects_lowest_tenth():
    df = _day(20)
    filt = [{"field": "vmi_ratio", "op": "lte", "value": 1, "mode": "decile"}]
    out = be.apply_filters(df, filt)
    col = be.FIELD_MAP["vmi_ratio"]
    assert set(out[col]) == {1, 2}


def test_decile_is_relative_not_absolute():
    """Same op/value, two days with wildly different absolute levels: decile mode picks the
    relatively-strongest each day; absolute mode would over/under-select."""
    hi_day = _day(10, vals=[1000 + i for i in range(10)])   # all 'extended' in absolute terms
    lo_day = _day(10, vals=[i for i in range(10)])          # all 'cheap' in absolute terms
    filt = [{"field": "vmi_ratio", "op": "gte", "value": 10, "mode": "decile"}]
    out_hi = be.apply_filters(hi_day, filt)
    out_lo = be.apply_filters(lo_day, filt)
    # exactly one name (the top decile of 10) each day, regardless of absolute scale
    assert len(out_hi) == 1 and len(out_lo) == 1


def test_decile_drops_nan_factor_names():
    col = be.FIELD_MAP["vmi_ratio"]
    df = pd.DataFrame({"ticker": ["A", "B", "C", "D"], col: [5.0, np.nan, 1.0, 9.0]})
    filt = [{"field": "vmi_ratio", "op": "gte", "value": 10, "mode": "decile"}]
    out = be.apply_filters(df, filt)
    # B (NaN) is never selected; the top-decile name is D
    assert "B" not in set(out["ticker"])
    assert set(out["ticker"]) == {"D"}


def test_absolute_mode_is_byte_identical_to_legacy():
    """A filter WITHOUT `mode` and one WITH mode='absolute' must produce the same rows as
    the legacy {field,op,value} dict — zero regression."""
    df = _day(20)
    legacy = be.apply_filters(df, [{"field": "vmi_ratio", "op": "gt", "value": 15}])
    explicit = be.apply_filters(
        df, [{"field": "vmi_ratio", "op": "gt", "value": 15, "mode": "absolute"}])
    pd.testing.assert_frame_equal(legacy.reset_index(drop=True),
                                  explicit.reset_index(drop=True))


def test_decile_order_invariant():
    """Shuffling the day's rows must not change which names land in which decile."""
    df = _day(30, vals=list(np.random.RandomState(7).randn(30)))
    filt = [{"field": "vmi_ratio", "op": "gte", "value": 10, "mode": "decile"}]
    out1 = set(be.apply_filters(df, filt)["ticker"])
    out2 = set(be.apply_filters(df.sample(frac=1.0, random_state=1), filt)["ticker"])
    assert out1 == out2


def test_decile_empty_frame_does_not_crash():
    col = be.FIELD_MAP["vmi_ratio"]
    df = pd.DataFrame({"ticker": [], col: []})
    filt = [{"field": "vmi_ratio", "op": "gte", "value": 10, "mode": "decile"}]
    out = be.apply_filters(df, filt)
    assert out.empty


def test_decile_all_nan_factor_selects_nothing():
    col = be.FIELD_MAP["vmi_ratio"]
    df = pd.DataFrame({"ticker": ["A", "B"], col: [np.nan, np.nan]})
    filt = [{"field": "vmi_ratio", "op": "gte", "value": 1, "mode": "decile"}]
    out = be.apply_filters(df, filt)
    assert out.empty
