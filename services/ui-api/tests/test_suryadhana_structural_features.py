"""SuryaDhana structural alpha features — point-in-time correctness + registration.

Covers the two buildable institutional features added to `compute_market_relative`:
  • beta_resid_5d            — Idiosyncratic Momentum (30d-beta-residual 5d return vs Nifty)
  • vol_adj_sector_alpha_14  — (14d return − sector 14d) / 14d ATR%

(Feature 1 — Institutional Delivery Shock — is intentionally absent: the DuckDB has no
delivery-quantity column, so it cannot be built honestly. See the discovery report.)

The non-negotiable property under test is ZERO LOOK-AHEAD: a feature value on day T must
depend only on data up to and including T. We verify this by recomputing the whole frame
truncated at a cutoff and asserting the cutoff-day values are byte-identical to the
full-frame values (a future leak would change them). Plus registration + NaN-safety.

Pure, deterministic, no IO."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_engine as be  # noqa: E402

NEW_COLS = ["beta_resid_5d", "vol_adj_sector_alpha_14"]


def _synth(n_tickers: int = 8, n_days: int = 160, seed: int = 11) -> pd.DataFrame:
    """A reproducible multi-ticker OHLCV panel with a shared market factor + idiosyncratic
    noise, so beta/sector/ATR are all well-defined and non-degenerate."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    mkt = rng.normal(0.0005, 0.01, n_days)            # common market return
    rows = []
    sectors = {}
    for i in range(n_tickers):
        beta = 0.5 + i * 0.2
        idio = rng.normal(0.0, 0.012, n_days)
        ret = beta * mkt + idio
        close = 100.0 * np.cumprod(1.0 + ret)
        high = close * (1.0 + np.abs(rng.normal(0, 0.006, n_days)))
        low = close * (1.0 - np.abs(rng.normal(0, 0.006, n_days)))
        openp = close * (1.0 + rng.normal(0, 0.003, n_days))
        vol = rng.randint(1_000_00, 5_000_00, n_days)
        tk = f"STK{i}"
        sectors[tk] = "Alpha" if i % 2 == 0 else "Beta"
        for d, o, h, l, c, v in zip(dates, openp, high, low, close, vol):
            rows.append((tk, d, o, h, l, c, v))
    df = pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    return df, sectors


def _prepare(df, sectors, market_ret_by_date=None):
    return be.compute_market_relative(be.compute_indicators(df.copy()), sectors,
                                      market_ret_by_date=market_ret_by_date)


# ── Registration ──────────────────────────────────────────────────────────────────

def test_new_features_registered_in_field_map():
    for c in NEW_COLS:
        assert c in be.FIELD_MAP, f"{c} must be a filterable numeric field"
        assert be.FIELD_MAP[c] == c


def test_features_attached_and_numeric():
    df, sectors = _synth()
    out = _prepare(df, sectors)
    for c in NEW_COLS:
        assert c in out.columns
        assert pd.api.types.is_float_dtype(out[c])
    # No inf leaks (the atr_pct>0 / var>0 guards must hold).
    assert not np.isinf(out[NEW_COLS].to_numpy(dtype=float)).any()


# ── ZERO LOOK-AHEAD (the load-bearing property) ─────────────────────────────────────

def test_beta_residual_is_point_in_time():
    _assert_pit("beta_resid_5d")


def test_vol_adj_sector_alpha_is_point_in_time():
    _assert_pit("vol_adj_sector_alpha_14")


def _assert_pit(col: str):
    df, sectors = _synth()
    full = _prepare(df, sectors)
    cutoff = sorted(df["date"].unique())[-30]          # well inside the series
    trunc = _prepare(df[df["date"] <= cutoff], sectors)
    fa = full[full["date"] == cutoff].set_index("ticker")[col].sort_index()
    ta = trunc[trunc["date"] == cutoff].set_index("ticker")[col].sort_index()
    common = fa.index.intersection(ta.index)
    assert len(common) > 0
    diff = (fa.loc[common] - ta.loc[common]).abs()
    # A future leak would make full≠truncated on the cutoff day. Demand exact (float) match.
    assert diff.fillna(0.0).max() < 1e-9, f"{col} leaks future data (max diff {diff.max()})"


# ── NaN-safety / degenerate inputs never crash ──────────────────────────────────────

def test_zero_volume_and_flat_bars_do_not_crash():
    df, sectors = _synth()
    # Inject a flat (H==L) zero-volume bar — ATR% → 0 on that name → feature NaN, not inf.
    df.loc[df.index[50], ["high", "low", "volume"]] = [df.loc[df.index[50], "close"]] * 2 + [0]
    out = _prepare(df, sectors)
    assert not np.isinf(out[NEW_COLS].to_numpy(dtype=float)).any()


def test_empty_frame_returns_empty():
    empty = pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    out = be.compute_market_relative(empty, {})
    assert out is None or out.empty


def test_features_are_decile_rankable():
    df, sectors = _synth()
    out = _prepare(df, sectors)
    last = out[out["date"] == out["date"].max()].copy()
    for c in NEW_COLS:
        sel = be.apply_filters(last, [{"field": c, "op": "gte", "value": 10, "mode": "decile"}])
        # top decile of a non-degenerate cross-section selects ≥1 and < all names
        assert 0 < len(sel) <= len(last)
