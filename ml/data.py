#!/usr/bin/env python3
"""Shared modeling dataset builder for the SuryaDhana ML evaluation.

Single source of truth for WHAT the models see. Every modeling agent
consumes the parquet + manifest + splits produced here; nobody re-derives
features or labels on their own, so results stay comparable.

Inputs
------
DuckDB ``equity_features`` built by ``nse_historical_ingest.build_features``
(the repo's existing feature logic). This module:

1. keeps the repo's scale-free swing features (RSI, ATR%, SMA distances,
   momentum, vol, volume/delivery z-scores, gaps, 52-week distances);
2. adds production-v2-convention features computable from EOD bhavcopy:
   rsi_2, ret_63/126/252d, 12-1 momentum, 200-DMA distance + flag,
   52w-low flag, split/extreme-move flag, log turnover, cross-sectional
   percentile ranks (carry and announcement flags need F&O/announcement
   feeds that this repo does not ingest -- documented out of scope);
3. builds labels:
   * PRIMARY  ``label_beat_mkt_20d`` -- 20-session NEXT-OPEN excess return
     vs the cross-sectional universe median (production v3 label logic),
     with ``y_excess_20d`` / ``y_rank_20d`` / ``y_clean_20d`` mask;
   * SECONDARY ``label_up_5d`` / ``fwd_ret_5d`` -- the repo's existing
     5-day close-to-close swing label, taken from equity_features as-is.
4. applies a point-in-time liquidity universe filter (no survivorship);
5. writes purged, embargoed walk-forward splits.

Labels use FUTURE prices: train targets only, never features.

Outputs (ml/data/, gitignored)
------------------------------
model_dataset.parquet   one row per (ticker, date) in the universe
manifest.json           feature list, label columns, build stats
splits.json             walk-forward folds + holdout, embargo in sessions
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED = 108

# Point-in-time universe filter: tradable, liquid names only.
MIN_PRICE = 10.0            # drop penny stocks (distorted microstructure)
MIN_MED_TURNOVER = 1e7      # >= Rs 1 crore median turnover over trailing 20d
DATASET_START = "2025-06-01"  # ~60 sessions of warm-up before first row

LABEL_COLS = [
    "fwd_ret_5d", "label_up_5d",
    "y_raw_20d", "y_excess_20d", "y_rank_20d", "label_beat_mkt_20d",
    "y_clean_20d",
]
ID_COLS = ["date", "ticker"]

# Extreme 1-day move on unadjusted prices ~ corporate action / circuit event.
SPLIT_MOVE_THRESHOLD = 0.22
FWD_SESSIONS = 20           # label horizon: 20 sessions, next-open entry
EMBARGO_SESSIONS = 22       # purge gap between train end and test start


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _fwd_window_max(s: pd.Series, w: int) -> pd.Series:
    """max(s[t+1 .. t+w]) within one ticker's positional series."""
    rev = s.iloc[::-1].rolling(w, min_periods=1).max().iloc[::-1]
    return rev.shift(-1)


def build_dataset(db_path: str = str(REPO / "nse_market.duckdb"),
                  rebuild_features: bool = True,
                  dataset_start: str = DATASET_START,
                  fold_months: list[tuple[int, int]] | None = None,
                  holdout_start: str = "2026-08-01",
                  out_dir: Path = DATA_DIR) -> dict:
    """Build the modeling dataset. Defaults reproduce the pilot (6-month window);
    the 5-year run passes an earlier start, a long list of monthly folds and its
    own out_dir so the pilot artifacts stay intact."""
    out_dir = Path(out_dir)
    import duckdb
    import nse_historical_ingest as nhi

    con = duckdb.connect(db_path)
    if rebuild_features:
        n = nhi.build_features(con, ca_csv=None)  # repo's existing feature/label logic
        print(f"equity_features rebuilt: {n} rows")

    df = con.execute(
        """
        SELECT date, ticker, open, high, low, close, volume, turnover,
               ret_1d, log_ret_1d, gap_pct, range_pct, close_pos_in_range,
               dist_sma_5, dist_sma_10, dist_sma_20, dist_sma_50, macd,
               mom_5, mom_10, mom_20, vol_5, vol_10, vol_20,
               rsi_14, atr_pct, vol_ratio_20, vol_z_20,
               deliv_pct, deliv_pct_sma_20, deliv_pct_z_20,
               dist_52w_high, dist_52w_low,
               fwd_ret_5d, label_up_5d
        FROM equity_features
        ORDER BY ticker, date
        """
    ).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    print(f"loaded equity_features: {len(df):,} rows, {df['ticker'].nunique():,} tickers")

    g = df.groupby("ticker", group_keys=False)

    # ---- v2-convention additions (per-ticker time series) ------------------
    df["macd_norm"] = df["macd"] / df["close"]
    df["rsi_2"] = g["close"].transform(lambda s: _rsi(s, 2))
    for w in (63, 126, 252):
        df[f"ret_{w}d"] = g["close"].transform(lambda s, w=w: s / s.shift(w) - 1)
    df["mom_12_1"] = g["close"].transform(lambda s: s.shift(21) / s.shift(252) - 1)
    sma200 = g["close"].transform(lambda s: s.rolling(200, min_periods=120).mean())
    df["dist_200dma"] = df["close"] / sma200 - 1
    df["flag_below_200dma"] = (df["dist_200dma"] < 0).astype("float32")
    df["flag_near_52w_low"] = (df["dist_52w_low"] < 0.05).astype("float32")
    absret = df["ret_1d"].abs()
    df["flag_split_20d"] = (
        absret.groupby(df["ticker"]).transform(
            lambda s: s.rolling(20, min_periods=1).max())
        > SPLIT_MOVE_THRESHOLD
    ).astype("float32")
    df["log_turnover"] = np.log1p(df["turnover"])

    # ---- 20-session next-open labels (production v3 convention) ------------
    entry_open = g["open"].shift(-1)
    exit_open = g["open"].shift(-(FWD_SESSIONS + 1))
    df["y_raw_20d"] = exit_open / entry_open - 1
    entry_date = g["date"].shift(-1)
    exit_date = g["date"].shift(-(FWD_SESSIONS + 1))
    span_days = (exit_date - entry_date).dt.days
    fwd_absmax = absret.groupby(df["ticker"]).transform(
        lambda s: _fwd_window_max(s, FWD_SESSIONS + 1))
    df["y_clean_20d"] = (
        df["y_raw_20d"].notna()
        & (entry_open > 0) & (exit_open > 0)
        & (span_days <= 45)                       # no long suspension inside window
        & (fwd_absmax <= SPLIT_MOVE_THRESHOLD)    # no split/circuit poisoning the label
    )

    # ---- point-in-time universe filter --------------------------------------
    med_turn = g["turnover"].transform(lambda s: s.rolling(20, min_periods=10).median())
    universe = (df["close"] >= MIN_PRICE) & (med_turn >= MIN_MED_TURNOVER)
    df = df[universe & (df["date"] >= dataset_start)].copy()
    print(f"after universe filter: {len(df):,} rows, {df['ticker'].nunique():,} tickers")

    # ---- cross-sectional pieces (computed on the universe only) -------------
    mkt = df.groupby("date")["y_raw_20d"].transform("median")
    df["y_excess_20d"] = df["y_raw_20d"] - mkt
    df["y_rank_20d"] = df.groupby("date")["y_excess_20d"].rank(pct=True)
    df["label_beat_mkt_20d"] = np.where(
        df["y_excess_20d"].notna(), (df["y_excess_20d"] > 0).astype(float), np.nan)

    for src, dst in [("mom_20", "cs_rank_mom_20"), ("ret_126d", "cs_rank_ret_126"),
                     ("vol_20", "cs_rank_vol_20"), ("turnover", "cs_rank_turnover"),
                     ("deliv_pct_z_20", "cs_rank_deliv_z")]:
        df[dst] = df.groupby("date")[src].rank(pct=True)

    features = [
        # repo layer-4 (scale-free)
        "ret_1d", "log_ret_1d", "gap_pct", "range_pct", "close_pos_in_range",
        "dist_sma_5", "dist_sma_10", "dist_sma_20", "dist_sma_50", "macd_norm",
        "mom_5", "mom_10", "mom_20", "vol_5", "vol_10", "vol_20",
        "rsi_14", "atr_pct", "vol_ratio_20", "vol_z_20",
        "deliv_pct", "deliv_pct_sma_20", "deliv_pct_z_20",
        "dist_52w_high", "dist_52w_low",
        # v2-convention additions
        "rsi_2", "ret_63d", "ret_126d", "ret_252d", "mom_12_1",
        "dist_200dma", "flag_below_200dma", "flag_near_52w_low",
        "flag_split_20d", "log_turnover",
        "cs_rank_mom_20", "cs_rank_ret_126", "cs_rank_vol_20",
        "cs_rank_turnover", "cs_rank_deliv_z",
    ]

    # NaN indicators for features that are genuinely unavailable early
    # (e.g. ret_252d before a stock has a year of history) -- PIT information.
    for c in features.copy():
        miss = df[c].isna().mean()
        if miss > 0.02:
            ind = f"{c}_isnan"
            df[ind] = df[c].isna().astype("float32")
            features.append(ind)

    out = df[ID_COLS + features + LABEL_COLS].reset_index(drop=True)
    out = out.sort_values(["date", "ticker"]).reset_index(drop=True)

    # ---- purged walk-forward splits -----------------------------------------
    dates = pd.DatetimeIndex(sorted(out["date"].unique()))
    labeled_dates = pd.DatetimeIndex(
        sorted(out.loc[out["label_beat_mkt_20d"].notna(), "date"].unique()))
    last_labeled = labeled_dates.max()

    def month_fold(year: int, month: int) -> dict | None:
        in_m = dates[(dates.year == year) & (dates.month == month)]
        if len(in_m) == 0:
            return None
        test_start, test_end = in_m.min(), in_m.max()
        pos = dates.get_loc(test_start)
        train_end = dates[max(pos - EMBARGO_SESSIONS, 0)]
        return {"name": f"{year}-{month:02d}",
                "train_end": str(train_end.date()),
                "test_start": str(test_start.date()),
                "test_end": str(min(test_end, last_labeled).date())}

    if fold_months is None:
        fold_months = [(2026, m) for m in (4, 5, 6, 7)]
    folds = [f for f in (month_fold(y, m) for y, m in fold_months) if f]
    ho_start = pd.Timestamp(holdout_start)
    pos = dates.get_loc(dates[dates >= ho_start][0])
    holdout = {"name": "holdout",
               "train_end": str(dates[pos - EMBARGO_SESSIONS].date()),
               "test_start": str(dates[pos].date()),
               "test_end": str(last_labeled.date())}

    splits = {"folds": folds, "holdout": holdout,
              "embargo_sessions": EMBARGO_SESSIONS,
              "note": "train = labeled rows with date <= train_end; "
                      "embargo covers the 20-session forward label window"}

    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_dir / "model_dataset.parquet", index=False)
    (out_dir / "splits.json").write_text(json.dumps(splits, indent=1))

    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "rows": int(len(out)),
        "tickers": int(out["ticker"].nunique()),
        "date_min": str(out["date"].min().date()),
        "date_max": str(out["date"].max().date()),
        "last_labeled_date_20d": str(last_labeled.date()),
        "features": features,
        "label_cols": LABEL_COLS,
        "primary_task": "beat_mkt_20d (20-session next-open excess vs universe median)",
        "secondary_task": "up_5d (repo's existing 5d close-to-close label)",
        "universe": {"min_price": MIN_PRICE, "min_median_turnover_20d": MIN_MED_TURNOVER},
        "label_balance": {
            "beat_mkt_20d": float(out["label_beat_mkt_20d"].mean()),
            "up_5d": float(pd.to_numeric(out["label_up_5d"]).mean()),
            "y_clean_20d_pct": float(out["y_clean_20d"].mean()),
        },
        "label_warning": "y_*/fwd_*/label_* use FUTURE prices -- train targets only, never features",
        "known_gaps": "prices unadjusted (no CA feed in sandbox): y_clean_20d masks "
                      "split-contaminated 20d labels; carry/announcement features need "
                      "F&O/announcement feeds not present in this repo",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps({k: manifest[k] for k in
                      ("rows", "tickers", "date_min", "date_max", "label_balance")}, indent=1))
    return manifest


if __name__ == "__main__":
    build_dataset()
