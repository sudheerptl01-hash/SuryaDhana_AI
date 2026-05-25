from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from shared.logging import get_logger

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
    df = df.dropna(subset=feature_cols + [target_col])

    result = WalkForwardResult()
    total_days = len(df)

    # Calculate fold boundaries in rows (approximate months → rows)
    train_rows = int(train_months * 21)  # ~21 trading days/month
    test_rows = int(test_months * 21)
    step_rows = test_rows

    fold_start = 0
    for fold_idx in range(n_folds):
        train_end_idx = fold_start + train_rows
        test_end_idx = train_end_idx + test_rows

        if test_end_idx > total_days:
            logger.warning("Not enough data for fold", fold=fold_idx + 1, remaining=total_days - fold_start)
            break

        train_df = df.iloc[fold_start:train_end_idx]
        test_df = df.iloc[train_end_idx:test_end_idx]

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

        fold_start += step_rows

    logger.info("Walk-forward complete", **result.summary())
    return result
