"""Realised-volatility estimators (R-IV §4.2; label ``arithmetic``): close-to-close, Parkinson (high / low) and Yang-Zhang
(open / high / low / close with the overnight gap), annualised by √252 (trading sessions), in vol points (× 100).

Input: a frame ordered by date with ``open, high, low, close, prev_close`` (NaN allowed where a file lacks OHLC — then only
the estimators whose inputs exist are returned). A session whose |close / prev_close − 1| exceeds ``JUMP`` is a corporate
action in an unadjusted series and is dropped from every estimator (the ``nse_bhavcopy.prev_close`` trap).

Range outliers (M06, review 5 Nov 2026): INFY's 23 Oct 2026 bar carries a low of ₹1,038.05 while its three futures never
traded below ₹1,130.70 and the session closed at ₹1,153.80 — one bad print. Its Rogers-Satchell term was 73× the usual,
and it alone lifted RV20 Yang-Zhang from ≈ 38 % to 53.7 % and Parkinson from ≈ 30 % to 41 % for twenty sessions (the
open was fine; the low was not). A session is a RANGE OUTLIER when its Rogers-Satchell term exceeds ``RANGE_OUTLIER_X``
× the median of the previous ``RANGE_REF_N`` sessions AND its wick reaches more than ``RANGE_OUTLIER_WICK`` beyond
max / min(open, close, previous close). Such a session leaves the RANGE estimators only (Parkinson and the
Rogers-Satchell part of Yang-Zhang); its close-to-close, overnight and open-to-close returns stay. A trend day (the
close near the extreme) has a small Rogers-Satchell term and is never caught. Measured 1 Jan 2025 → 5 Nov 2026 (re-measured
6 Nov with the trailing-60 reference): the 218 of 5 Nov's 224 F&O names with EQ rows, 16 of 98,557 sessions (0.02 %) qualify,
INFY 23 Oct at 73× / a 10.5 % wick among them, 5 of them the 1 Feb 2026 budget session's genuine spike-and-revert bars,
which also leave the range estimators (close-to-close keeps them); over all 298 names ever stored, 39 of 132,317.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

ANNUALISE = math.sqrt(252.0)
JUMP = 0.25
RANGE_OUTLIER_X = 40.0
RANGE_OUTLIER_WICK = 0.05
RANGE_REF_N = 60
RANGE_REF_MIN = 10


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


def rs_terms(d: pd.DataFrame) -> pd.Series:
    """Per-session Rogers-Satchell term u(u − c) + d(d − c) on log(high / open), log(low / open), log(close / open)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        u, dn, c = np.log(d["high"] / d["open"]), np.log(d["low"] / d["open"]), np.log(d["close"] / d["open"])
    return (u * (u - c) + dn * (dn - c)).replace([np.inf, -np.inf], np.nan)


def range_outliers(d: pd.DataFrame) -> pd.Series:
    """True for a range-outlier session (module docstring) in a ``_clean``-ed frame ordered by date; False where unknown."""
    rs = rs_terms(d)
    ref = rs.shift(1).rolling(RANGE_REF_N, min_periods=RANGE_REF_MIN).median()
    top = np.fmax(np.fmax(d["open"], d["close"]), d["prev_close"])
    bot = np.fmin(np.fmin(d["open"], d["close"]), d["prev_close"])
    with np.errstate(divide="ignore", invalid="ignore"):
        wick = np.fmax(np.log(d["high"] / top), np.log(bot / d["low"]))
    out = (rs > RANGE_OUTLIER_X * ref) & (wick > RANGE_OUTLIER_WICK)
    return out.fillna(False).astype(bool)


def outlier_dates(df: pd.DataFrame, n: int = 20) -> list:
    """The range-outlier sessions inside the last ``n`` rows (for a quality flag / the repair report)."""
    d = _clean(df).reset_index(drop=True)
    if d.empty or "date" not in d:
        return []
    flags = range_outliers(d).tail(n)
    return [d.loc[i, "date"] for i in flags[flags].index]


def close_to_close(df: pd.DataFrame, n: int = 20) -> float | None:
    d = _clean(df)
    r = np.log(d["close"] / d["prev_close"]).replace([np.inf, -np.inf], np.nan).dropna().tail(n)
    if len(r) < max(5, n // 2):
        return None
    return float(r.std(ddof=1) * ANNUALISE * 100.0)


def _flagged(df: pd.DataFrame) -> pd.DataFrame:
    """``_clean`` + the ``range_outlier`` column, computed over the WHOLE frame (the reference median needs history)."""
    d = _clean(df).reset_index(drop=True)
    d["range_outlier"] = range_outliers(d) if not d.empty else pd.Series(dtype=bool)
    return d


def parkinson(df: pd.DataFrame, n: int = 20) -> float | None:
    d = _flagged(df).dropna(subset=["high", "low"]).tail(n)
    d = d[(d["high"] > 0) & (d["low"] > 0) & (d["high"] >= d["low"]) & ~d["range_outlier"]]
    if len(d) < max(5, n // 2):
        return None
    hl = np.log(d["high"] / d["low"]) ** 2
    return float(math.sqrt(hl.mean() / (4.0 * math.log(2.0))) * ANNUALISE * 100.0)


def yang_zhang(df: pd.DataFrame, n: int = 20) -> float | None:
    d = _flagged(df).dropna(subset=["open", "high", "low", "close", "prev_close"]).tail(n)
    d = d[(d["open"] > 0) & (d["high"] > 0) & (d["low"] > 0) & (d["prev_close"] > 0)]
    m = len(d)
    if m < max(5, n // 2):
        return None
    o = np.log(d["open"] / d["prev_close"])              # overnight
    c = np.log(d["close"] / d["open"])                   # open-to-close
    keep = ~d["range_outlier"]
    if not keep.any():
        return None
    rs = rs_terms(d[keep]).mean()                        # Rogers-Satchell, range outliers out
    vo, vc = o.var(ddof=1), c.var(ddof=1)
    k = 0.34 / (1.34 + (m + 1) / (m - 1))
    var = vo + k * vc + (1 - k) * rs
    return float(math.sqrt(max(var, 0.0)) * ANNUALISE * 100.0)


def all_three(df: pd.DataFrame, n: int = 20) -> dict[str, float | None]:
    return {"rv20_cc": close_to_close(df, n), "rv20_parkinson": parkinson(df, n), "rv20_yz": yang_zhang(df, n)}
