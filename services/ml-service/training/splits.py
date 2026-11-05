"""
Time-ordered train/validation splitting for panel data (many tickers per date).

Rules (Lopez de Prado, AFML ch. 7):
  * split on DATES, never on row positions — a panel has ~1,400 rows per date, so a
    row-based 80/20 cut either leaks the same dates into both sides or mixes tickers;
  * purge: a label at date t uses prices up to t+h, so training rows within ``purge``
    trading dates before the validation start would overlap the validation labels and
    are dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TimeSplit:
    train_idx: np.ndarray
    val_idx: np.ndarray
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    purged_dates: int

    def describe(self) -> dict:
        return {
            "train_period": [self.train_start, self.train_end],
            "val_period": [self.val_start, self.val_end],
            "purged_dates": self.purged_dates,
            "n_train": int(len(self.train_idx)),
            "n_val": int(len(self.val_idx)),
        }


def purged_time_split(dates: pd.Series, val_frac: float = 0.2, purge: int = 5) -> TimeSplit:
    """Last ``val_frac`` of unique dates → validation; ``purge`` dates before it dropped."""
    d = pd.to_datetime(dates).reset_index(drop=True)
    uniq = np.sort(d.unique())
    if len(uniq) < 20:
        raise ValueError(f"Need at least 20 distinct dates for a time split, got {len(uniq)}")
    val_start_i = int(len(uniq) * (1 - val_frac))
    train_end_i = val_start_i - purge - 1
    if train_end_i < 5:
        raise ValueError("Not enough dates left for training after purging")
    val_start, train_end = uniq[val_start_i], uniq[train_end_i]
    train_idx = np.flatnonzero((d <= train_end).to_numpy())
    val_idx = np.flatnonzero((d >= val_start).to_numpy())
    fmt = lambda x: str(pd.Timestamp(x).date())  # noqa: E731
    return TimeSplit(train_idx, val_idx, fmt(uniq[0]), fmt(train_end),
                     fmt(val_start), fmt(uniq[-1]), purge)


def date_folds(dates: pd.Series, train_dates: int, test_dates: int, n_folds: int,
               purge: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    """Rolling walk-forward folds measured in trading DATES (not rows), purged."""
    d = pd.to_datetime(dates).reset_index(drop=True)
    uniq = np.sort(d.unique())
    folds = []
    start = 0
    for _ in range(n_folds):
        tr_end = start + train_dates
        te_start = tr_end + purge
        te_end = te_start + test_dates
        if te_end > len(uniq):
            break
        tr_mask = (d >= uniq[start]) & (d < uniq[tr_end])
        te_mask = (d >= uniq[te_start]) & (d <= uniq[te_end - 1])
        folds.append((np.flatnonzero(tr_mask.to_numpy()), np.flatnonzero(te_mask.to_numpy())))
        start += test_dates
    return folds
