from __future__ import annotations

import pandas as pd
import numpy as np


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3) -> tuple[pd.Series, pd.Series]:
    lowest_low = low.rolling(k).min()
    highest_high = high.rolling(k).max()
    stoch_k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-9)
    stoch_d = stoch_k.rolling(d).mean()
    return stoch_k, stoch_d


def add_momentum_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds RSI, Stochastic, ROC, and Williams %R. Requires open/high/low/close."""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    df["rsi_14"] = _rsi(close, 14)
    df["rsi_28"] = _rsi(close, 28)
    df["rsi_7"] = _rsi(close, 7)

    df["stoch_k"], df["stoch_d"] = _stochastic(high, low, close)

    # Rate of change
    df["roc_5"] = close.pct_change(5) * 100
    df["roc_10"] = close.pct_change(10) * 100
    df["roc_20"] = close.pct_change(20) * 100

    # Williams %R
    h14 = high.rolling(14).max()
    l14 = low.rolling(14).min()
    df["williams_r"] = -100 * (h14 - close) / (h14 - l14 + 1e-9)

    # Momentum (price difference)
    df["momentum_10"] = close - close.shift(10)

    # Lagged daily returns
    for lag in [1, 2, 3, 5, 10]:
        df[f"return_lag_{lag}d"] = close.pct_change(lag) * 100

    # Green/red candle
    df["is_green_candle"] = (close > df["open"]).astype(int)

    return df
