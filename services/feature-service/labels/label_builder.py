from __future__ import annotations

import pandas as pd
import numpy as np

from shared.logging import get_logger

logger = get_logger(__name__)

HORIZON = 5  # days


def build_labels(df: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    """
    Creates 5-day forward return labels from OHLCV data.

    Critical: uses shift(-horizon) on close price — this is intentional look-ahead
    for label creation only. Features must NEVER use this shifted column.

    Returns df with two new columns:
        label_direction  : int  — 1 if close[t+horizon] > close[t], else 0
        label_return_pct : float — actual % return over horizon days
    """
    close = df["close"]

    # Future price (only valid for training — never use as a feature)
    future_close = close.shift(-horizon)

    df["label_return_pct"] = ((future_close - close) / close) * 100
    df["label_direction"] = (future_close > close).astype(int)

    # The last `horizon` rows have no label — mark clearly
    invalid_mask = df["label_return_pct"].isna()
    df.loc[invalid_mask, "label_direction"] = np.nan
    df.loc[invalid_mask, "label_return_pct"] = np.nan

    n_valid = (~invalid_mask).sum()
    n_up = df["label_direction"].sum()
    logger.info(
        "Labels built",
        ticker=df["ticker"].iloc[0] if "ticker" in df.columns else "unknown",
        horizon=horizon,
        valid_rows=n_valid,
        up_pct=round(n_up / n_valid * 100, 1) if n_valid else 0,
    )

    return df


def validate_no_lookahead(feature_cols: list[str]) -> None:
    """Raises ValueError if any forbidden future-data column names are present."""
    forbidden = {"future_close", "label_return_pct", "label_direction"}
    leaked = forbidden.intersection(set(feature_cols))
    if leaked:
        raise ValueError(
            f"LOOK-AHEAD BIAS DETECTED: feature columns contain future data: {leaked}. "
            "Remove these from your feature set immediately."
        )


def get_train_features_and_labels(
    df: pd.DataFrame,
    feature_cols: list[str],
    target: str = "label_direction",
    dropna: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Separates X (features) and y (labels) for model training.
    Enforces look-ahead bias check before returning.
    """
    validate_no_lookahead(feature_cols)

    if dropna:
        df = df.dropna(subset=feature_cols + [target])

    X = df[feature_cols].copy()
    y = df[target].copy()

    return X, y
