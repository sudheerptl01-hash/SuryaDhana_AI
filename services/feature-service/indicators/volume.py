from __future__ import annotations

import pandas as pd
import numpy as np


def add_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds OBV, volume ratio, and VWAP. Requires close/volume."""
    close = df["close"]
    volume = df["volume"]

    # Volume moving averages
    df["volume_sma_20"] = volume.rolling(20).mean()
    df["volume_ratio"] = volume / df["volume_sma_20"].replace(0, np.nan)

    # On-Balance Volume
    direction = np.sign(close.diff())
    df["obv"] = (direction * volume).cumsum()
    df["obv_sma_20"] = df["obv"].rolling(20).mean()

    # Volume price trend
    df["vpt"] = (volume * close.pct_change()).cumsum()

    # Money Flow Index (14-period)
    typical_price = (df["high"] + df["low"] + close) / 3
    raw_mf = typical_price * volume
    tp_delta = typical_price.diff()
    pos_mf = raw_mf.where(tp_delta > 0, 0).rolling(14).sum()
    neg_mf = raw_mf.where(tp_delta < 0, 0).rolling(14).sum()
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    df["mfi_14"] = 100 - (100 / (1 + mfr))

    # Chaikin Money Flow (20-period)
    clv = ((close - df["low"]) - (df["high"] - close)) / (df["high"] - df["low"] + 1e-9)
    df["cmf_20"] = (clv * volume).rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)

    # Volume spike flag
    df["volume_spike"] = (df["volume_ratio"] > 2.0).astype(int)

    return df
