from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from shared.logging import get_logger

from .splits import date_folds

logger = get_logger(__name__)


@dataclass
class FoldResult:
    fold: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    accuracy: float
    precision: float
    recall: float
    f1: float
    n_train: int
    n_test: int


@dataclass
class WalkForwardResult:
    folds: list[FoldResult] = field(default_factory=list)

    @property
    def mean_accuracy(self) -> float:
        return float(np.mean([f.accuracy for f in self.folds]))

    @property
    def mean_precision(self) -> float:
        return float(np.mean([f.precision for f in self.folds]))

    @property
    def std_accuracy(self) -> float:
        return float(np.std([f.accuracy for f in self.folds]))

    def summary(self) -> dict:
        return {
            "n_folds": len(self.folds),
            "mean_accuracy": round(self.mean_accuracy, 4),
            "std_accuracy": round(self.std_accuracy, 4),
            "mean_precision": round(self.mean_precision, 4),
            "min_accuracy": round(min(f.accuracy for f in self.folds), 4),
            "max_accuracy": round(max(f.accuracy for f in self.folds), 4),
            "target_met_55pct": self.mean_accuracy >= 0.55,
        }


def walk_forward_validation(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    date_col: str,
    model_factory,
    train_months: int = 24,
    test_months: int = 3,
    n_folds: int = 8,
    purge: int = 5,
) -> WalkForwardResult:
    """
    Performs walk-forward validation — the only valid validation method for time-series data.

    Strategy:
        - Train on 24 months, test on next 3 months
        - Slide forward by 3 months, repeat 8 times
        - NEVER shuffle data, NEVER use test data for training

    Args:
        model_factory: callable that returns a fresh untrained model instance
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    # ── Pre-flight validation (Pillar 4) ──────────────────────────────────────
    missing_cols = [c for c in feature_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing feature columns: {missing_cols[:5]}{'…' if len(missing_cols) > 5 else ''}")

    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' not found in dataframe")

    # Report NaN rates and drop them
    nan_rates = df[feature_cols].isna().mean()
    high_nan = nan_rates[nan_rates > 0.3]
    if len(high_nan):
        logger.warning("Features with >30% NaN will be affected", features=high_nan.to_dict())

    df = df.dropna(subset=feature_cols + [target_col])

    # Replace inf/-inf silently
    df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=feature_cols)

    n_dates = df[date_col].nunique()
    if n_dates < (train_months + test_months) * 21:
        raise ValueError(
            f"Insufficient history: {n_dates} distinct dates after cleaning. "
            f"Need at least {(train_months + test_months) * 21} dates for one fold."
        )

    class_counts = df[target_col].value_counts()
    if len(class_counts) < 2:
        raise ValueError(
            f"Target column has only one class ({class_counts.index.tolist()}). "
            "Check label generation — need both UP (1) and DOWN (0) labels."
        )
    # ─────────────────────────────────────────────────────────────────────────

    result = WalkForwardResult()

    # Folds are measured in trading DATES (~21/month), not rows: the frame is a panel
    # with hundreds of tickers per date. A purge gap equal to the label horizon keeps
    # training labels from overlapping the test window.
    folds = date_folds(df[date_col], train_dates=int(train_months * 21),
                       test_dates=int(test_months * 21), n_folds=n_folds, purge=purge)
    if not folds:
        raise ValueError("Not enough history for a single walk-forward fold")

    for fold_idx, (tr_idx, te_idx) in enumerate(folds):
        train_df = df.iloc[tr_idx]
        test_df = df.iloc[te_idx]

        X_train = train_df[feature_cols]
        y_train = train_df[target_col]
        X_val = test_df[feature_cols]
        y_val = test_df[target_col]

        model = model_factory()
        model.fit(X_train, y_train, X_val, y_val)
        y_pred = model.predict(X_val)

        fold_result = FoldResult(
            fold=fold_idx + 1,
            train_start=train_df[date_col].iloc[0].date(),
            train_end=train_df[date_col].iloc[-1].date(),
            test_start=test_df[date_col].iloc[0].date(),
            test_end=test_df[date_col].iloc[-1].date(),
            accuracy=float(accuracy_score(y_val, y_pred)),
            precision=float(precision_score(y_val, y_pred, zero_division=0)),
            recall=float(recall_score(y_val, y_pred, zero_division=0)),
            f1=float(f1_score(y_val, y_pred, zero_division=0)),
            n_train=len(train_df),
            n_test=len(test_df),
        )
        result.folds.append(fold_result)

        logger.info(
            "Walk-forward fold complete",
            fold=fold_result.fold,
            accuracy=round(fold_result.accuracy, 3),
            n_test=fold_result.n_test,
        )

    logger.info("Walk-forward complete", **result.summary())
    return result
