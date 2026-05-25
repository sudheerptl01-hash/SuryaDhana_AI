from __future__ import annotations

import pandas as pd
import numpy as np


def _true_range(high: pd.Series, low: pd.Series, prev_close: pd.Series) -> pd.Series:
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def add_volatility_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds Bollinger Bands, ATR, and historical volatility. Requires high/low/close."""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Bollinger Bands (20-period, 2 std)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_lower"] = sma20 - 2 * std20
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma20
    df["bb_pct"] = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-9)

    # ATR (14-period)
    prev_close = close.shift(1)
    tr = _true_range(high, low, prev_close)
    df["atr_14"] = tr.rolling(14).mean()
    df["atr_14_pct"] = df["atr_14"] / close  # normalised ATR

    # Historical volatility (20-day annualised)
    log_returns = np.log(close / close.shift(1))
    df["hist_vol_20"] = log_returns.rolling(20).std() * np.sqrt(252) * 100  # annualised %

    # Normalised price range
    df["high_low_ratio"] = (high - low) / close
    df["close_position"] = (close - low) / (high - low + 1e-9)  # where close sits in day's range

    # Gap (open vs prior close)
    df["gap_pct"] = (df["open"] - close.shift(1)) / close.shift(1) * 100

    return df
