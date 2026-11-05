"""
Tradable, cross-sectional labels for stock-ranking models (label set v3).

Why these replace the v2 labels (services/feature-service/feature_engine.build_labels_v2):
  * entry at the NEXT open, exit at an open h sessions later: a signal computed after the
    close of day t cannot buy at that close, and the overnight gap it would capture is not
    tradable (the Decision Desk executes at the next session's open);
  * excess over the same-date universe mean: an absolute return is mostly the market's move
    that week, so a model trained on it learns market timing, not stock selection;
  * percentile rank of that excess per date: bounded, outlier-proof, identical in bull and
    bear years, and directly what a top-N book needs;
  * h = 20 sessions matches the monthly Desk; at 5 sessions the ≈0.95% round trip swamps
    any predictable difference between stocks.

All inputs are wide frames (date × symbol) from shared.nse_panel.load_panel (adjusted for
splits/bonuses, survivorship-free). These labels use FUTURE prices by construction and must
never be used as features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# A window containing a one-day move beyond any NSE price band signals a data break
# (unadjusted corporate action, relisting), not a tradable outcome.
MAX_DAILY_LOG_MOVE = float(np.log(1.5))


def forward_open_returns(open_: pd.DataFrame, h: int) -> pd.DataFrame:
    """Return from the open after signal day t to the open h sessions later:
    open[t+1+h] / open[t+1] − 1. If the stock stops trading inside the window (suspension,
    delisting), the exit is its last traded open, not a dropped sample."""
    entry = open_.shift(-1)
    exit_ = open_.ffill(limit=h).shift(-1 - h)
    return exit_ / entry - 1


def clean_windows(close: pd.DataFrame, h: int) -> pd.DataFrame:
    """True where the h+1 sessions after t contain no daily move beyond MAX_DAILY_LOG_MOVE."""
    jump = np.log(close / close.shift(1)).abs() > MAX_DAILY_LOG_MOVE
    bad_ahead = jump.astype(float)[::-1].rolling(h + 1, min_periods=1).max()[::-1].shift(-1)
    return bad_ahead.fillna(0).eq(0)


def excess_returns(fwd: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """fwd minus the equal-weight mean of the universe on the same signal date; NaN outside."""
    f = fwd.where(universe)
    return f.sub(f.mean(axis=1), axis=0)


def rank_label(excess: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank in (0, 1] of the excess return among labelled universe members."""
    return excess.rank(axis=1, pct=True)


def legacy_direction_label(close: pd.DataFrame, h: int = 5, hurdle_pct: float = 0.15) -> pd.DataFrame:
    """The v2 production label, for comparison: close[t+h] / close[t] − 1 > hurdle (1/0)."""
    ret = close.shift(-h) / close - 1
    return (ret * 100 > hurdle_pct).astype(float).where(ret.notna())
