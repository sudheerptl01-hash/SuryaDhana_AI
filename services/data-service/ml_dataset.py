"""
Single ML dataset pipeline: ohlcv → ml_features + ml_labels.

Runs inside data-service (the only process allowed to write DuckDB), so there is no
parquet hand-off, no cross-service import timeout and no competing writer. The new
dataset is swapped in with one transaction (``DuckDBStore.replace_ml_dataset``).

Only instruments with ``ml_eligible`` (NSE-listed operating companies) are used.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

from shared.logging import get_logger

_FE_PATH = str(Path(__file__).resolve().parents[1] / "feature-service")
if _FE_PATH not in sys.path:
    sys.path.insert(0, _FE_PATH)

from feature_engine import (  # noqa: E402
    FEATURE_VERSION,
    build_labels_v2,
    build_ticker_features,
    compute_macro_features,
    compute_market_breadth,
)

logger = get_logger(__name__)

MIN_BARS = 260  # need ~1y of history for sma_200 + a usable sample


class DatasetBuildError(RuntimeError):
    pass


def _write_parquet_snapshots(data_dir: Path, features: pd.DataFrame, labels: pd.DataFrame) -> None:
    """Mirror the committed dataset to parquet for ui-api's read-only explorers.

    Written to a temp file then renamed, so readers never see a partial file, and only
    AFTER the DuckDB swap committed, so parquet can never be newer than the database.
    """
    for df, name in ((features, "computed_features.parquet"), (labels, "computed_labels.parquet")):
        out = df.copy()
        out["date"] = out["date"].dt.strftime("%Y-%m-%d")
        tmp = data_dir / f"{name}.tmp"
        try:
            out.to_parquet(tmp, index=False)
            os.replace(tmp, data_dir / name)
        except Exception as exc:  # snapshot is best-effort; DuckDB is the source of truth
            logger.warning("Parquet snapshot failed", file=name, error=str(exc))
            tmp.unlink(missing_ok=True)


def build_ml_dataset(store, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    tickers = store.get_ml_eligible_tickers()
    if not tickers:
        raise DatasetBuildError("No ml_eligible instruments — classify the universe first")

    nifty = store.get_index_daily("NIFTY50")
    vix = store.get_index_daily("INDIAVIX")
    if nifty.empty or vix.empty:
        raise DatasetBuildError(
            "market_index_daily has no NIFTY50/INDIAVIX rows — run the index refresh "
            "(part of POST /jobs/refresh-universe) before building features"
        )

    ohlcv = store.get_ohlcv_for_tickers(tickers)
    if ohlcv.empty:
        raise DatasetBuildError("No OHLCV rows for eligible tickers")
    ohlcv["date"] = pd.to_datetime(ohlcv["date"])

    macro = compute_macro_features(nifty.assign(date=pd.to_datetime(nifty["date"])),
                                   vix.assign(date=pd.to_datetime(vix["date"])))
    breadth = compute_market_breadth(ohlcv[["date", "ticker", "close"]])
    macro = macro.merge(breadth, on="date", how="left")

    empty_fund = pd.DataFrame()
    feats: list[pd.DataFrame] = []
    labels: list[pd.DataFrame] = []
    skipped_short = 0
    errors: list[dict] = []
    groups = ohlcv.groupby("ticker", sort=True)
    total = groups.ngroups

    for i, (ticker, g) in enumerate(groups):
        try:
            g = g.drop(columns=["ticker"]).sort_values("date").reset_index(drop=True)
            if len(g) < MIN_BARS:
                skipped_short += 1
                continue
            f = build_ticker_features(ticker, g, empty_fund, macro)
            if not f.empty:
                num = f.select_dtypes(include=["float64"]).columns
                f[num] = f[num].astype("float32")  # halves peak memory for ~1.5M rows
                feats.append(f)
            lb = build_labels_v2(g)
            lb = lb[lb["label_return_pct"].notna()]
            if not lb.empty:
                lb.insert(0, "ticker", ticker)
                labels.append(lb)
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)[:200]})
        if progress and (i % 25 == 0 or i == total - 1):
            progress(i + 1, total)

    if not feats or not labels:
        raise DatasetBuildError(f"Nothing built (errors={len(errors)}, short={skipped_short})")

    features = pd.concat(feats, ignore_index=True)
    features["date"] = pd.to_datetime(features["date"])
    label_df = pd.concat(labels, ignore_index=True)
    label_df["date"] = pd.to_datetime(label_df["date"])
    for col in ("label_direction", "label_barrier", "horizon_days"):
        label_df[col] = label_df[col].astype("Int64")

    n_feat, n_lbl = store.replace_ml_dataset(features, label_df)
    store.checkpoint()
    _write_parquet_snapshots(Path(store._db_path).parent, features, label_df)

    lr = label_df["label_return_pct"]
    summary = {
        "feature_version": FEATURE_VERSION,
        "tickers_used": int(features["ticker"].nunique()),
        "tickers_skipped_short_history": skipped_short,
        "feature_rows": n_feat,
        "label_rows": n_lbl,
        "feature_date_range": [str(features["date"].min().date()), str(features["date"].max().date())],
        "label_date_range": [str(label_df["date"].min().date()), str(label_df["date"].max().date())],
        "label_up_pct": round(float(label_df["label_direction"].mean() * 100), 2),
        "label_return_std_pct": round(float(lr.std()), 3),
        "label_return_p001_p999": [round(float(lr.quantile(0.001)), 2), round(float(lr.quantile(0.999)), 2)],
        "barrier_distribution": {str(k): int(v) for k, v in label_df["label_barrier"].value_counts().items()},
        "macro_null_pct": round(float(features["india_vix"].isna().mean() * 100), 2),
        "errors": errors[:50],
    }
    logger.info("ML dataset built", **{k: v for k, v in summary.items() if k != "errors"})
    return summary
