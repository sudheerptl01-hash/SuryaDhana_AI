from __future__ import annotations

import pandas as pd
import numpy as np


def add_trend_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds SMA, EMA, MACD, and crossover ratio indicators. Input must have 'close' column."""
    close = df["close"]

    df["sma_10"] = close.rolling(10).mean()
    df["sma_20"] = close.rolling(20).mean()
    df["sma_50"] = close.rolling(50).mean()
    df["sma_200"] = close.rolling(200).mean()

    df["ema_12"] = close.ewm(span=12, adjust=False).mean()
    df["ema_26"] = close.ewm(span=26, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()

    df["sma_ratio_20_50"] = df["sma_20"] / df["sma_50"]
    df["ema_ratio_12_26"] = df["ema_12"] / df["ema_26"]

    # MACD
    df["macd"] = df["ema_12"] - df["ema_26"]
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Price relative to MAs
    df["price_vs_sma20"] = (close - df["sma_20"]) / df["sma_20"]
    df["price_vs_sma50"] = (close - df["sma_50"]) / df["sma_50"]
    df["price_vs_sma200"] = (close - df["sma_200"]) / df["sma_200"]

    # Trend direction flags
    df["uptrend_20_50"] = (df["sma_20"] > df["sma_50"]).astype(int)
    df["uptrend_50_200"] = (df["sma_50"] > df["sma_200"]).astype(int)

    return df
