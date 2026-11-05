"""Realised-volatility estimators (R-IV §4.2; label ``arithmetic``): close-to-close, Parkinson (high / low) and Yang-Zhang
(open / high / low / close with the overnight gap), annualised by √252 (trading sessions), in vol points (× 100).

Input: a frame ordered by date with ``open, high, low, close, prev_close`` (NaN allowed where a file lacks OHLC — then only
the estimators whose inputs exist are returned). A session whose |close / prev_close − 1| exceeds ``JUMP`` is a corporate
action in an unadjusted series and is dropped from every estimator (the ``nse_bhavcopy.prev_close`` trap).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

ANNUALISE = math.sqrt(252.0)
JUMP = 0.25


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in ("open", "high", "low", "close", "prev_close"):
        if c not in d.columns:
            d[c] = np.nan
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["close"])
    if "prev_close" in d and d["prev_close"].isna().all():
        d["prev_close"] = d["close"].shift(1)
    ratio = d["close"] / d["prev_close"]
    d = d[(ratio - 1).abs().fillna(0) <= JUMP]
    return d


def close_to_close(df: pd.DataFrame, n: int = 20) -> float | None:
    d = _clean(df)
    r = np.log(d["close"] / d["prev_close"]).replace([np.inf, -np.inf], np.nan).dropna().tail(n)
    if len(r) < max(5, n // 2):
        return None
    return float(r.std(ddof=1) * ANNUALISE * 100.0)


def parkinson(df: pd.DataFrame, n: int = 20) -> float | None:
    d = _clean(df).dropna(subset=["high", "low"]).tail(n)
    d = d[(d["high"] > 0) & (d["low"] > 0) & (d["high"] >= d["low"])]
    if len(d) < max(5, n // 2):
        return None
    hl = np.log(d["high"] / d["low"]) ** 2
    return float(math.sqrt(hl.mean() / (4.0 * math.log(2.0))) * ANNUALISE * 100.0)


def yang_zhang(df: pd.DataFrame, n: int = 20) -> float | None:
    d = _clean(df).dropna(subset=["open", "high", "low", "close", "prev_close"]).tail(n)
    d = d[(d["open"] > 0) & (d["high"] > 0) & (d["low"] > 0) & (d["prev_close"] > 0)]
    m = len(d)
    if m < max(5, n // 2):
        return None
    o = np.log(d["open"] / d["prev_close"])              # overnight
    c = np.log(d["close"] / d["open"])                   # open-to-close
    u, dn = np.log(d["high"] / d["open"]), np.log(d["low"] / d["open"])
    rs = (u * (u - c) + dn * (dn - c)).mean()            # Rogers-Satchell
    vo, vc = o.var(ddof=1), c.var(ddof=1)
    k = 0.34 / (1.34 + (m + 1) / (m - 1))
    var = vo + k * vc + (1 - k) * rs
    return float(math.sqrt(max(var, 0.0)) * ANNUALISE * 100.0)


def all_three(df: pd.DataFrame, n: int = 20) -> dict[str, float | None]:
    return {"rv20_cc": close_to_close(df, n), "rv20_parkinson": parkinson(df, n), "rv20_yz": yang_zhang(df, n)}
