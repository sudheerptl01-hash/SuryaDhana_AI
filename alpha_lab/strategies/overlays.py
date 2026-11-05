"""Derivatives overlays for alpha_lab — MODELED analytics, never gated (PLAN §S1 variant P).

No market option prices exist in our store, so puts are priced Black-Scholes with
sigma = India VIX / 100 × `skew` (default 1.1) and r = 6%. Known bias, stated up front:
BS with a flat VIX×1.1 understates crash-skew payoffs (real 5%-OTM puts carry more skew in
calm markets and explode harder in crashes) and misprices short-dated wings. Treat every
number here as a shape, not a price.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402


def bs_put(s: float, k: float, t: float, sigma: float, r: float = 0.06) -> float:
    """Black-Scholes European put, no dividends."""
    if t <= 0 or sigma <= 0 or s <= 0 or k <= 0:
        return max(k - s, 0.0)
    d1 = (math.log(s / k) + (r + sigma * sigma / 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    nd = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    return k * math.exp(-r * t) * nd(-d2) - s * nd(-d1)


def month_end_dates(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(idx.to_series().groupby(idx.to_period("M")).max().to_numpy())


def put_overlay(nifty: pd.Series, vix: pd.Series, start: str, end: str, otm: float = 0.05,
                skew: float = 1.1, r: float = 0.06, stance: str = "always") -> dict:
    """Index position + rolled 1-month ~`otm` OTM put (MODELED). Returns the monthly path and
    the premium ledger. stance: 'always' | 'regime' (hedge only when NIFTY < its 200-DMA) | 'never'."""
    nifty = nifty.dropna()
    ma200 = nifty.rolling(200, min_periods=180).mean()
    vix = vix.reindex(nifty.index).ffill()
    rolls = [d for d in month_end_dates(nifty.index) if start <= str(d.date()) <= end]
    rows = []
    level = 1.0
    for a, b in zip(rolls[:-1], rolls[1:]):
        s0, s1 = float(nifty[a]), float(nifty[b])
        hedged = stance == "always" or (stance == "regime" and np.isfinite(ma200[a]) and s0 < ma200[a])
        t = (b - a).days / 365.0
        prem = payoff = 0.0
        if hedged and np.isfinite(vix[a]):
            k = s0 * (1 - otm)
            prem = bs_put(s0, k, t, vix[a] / 100 * skew, r)
            payoff = max(k - s1, 0.0)
        ret = (s1 + payoff) / (s0 + prem) - 1
        level *= 1 + ret
        rows.append({"roll": a, "next": b, "hedged": hedged, "prem_pct": prem / s0 * 100,
                     "payoff_pct": payoff / s0 * 100, "index_ret": s1 / s0 - 1, "ret": ret, "level": level})
    df = pd.DataFrame(rows).set_index("roll")
    eq = df["level"]
    yrs = (df["next"].iloc[-1] - df.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    path = pd.concat([pd.Series([1.0], index=[df.index[0]]), df.set_index("next")["level"]])
    dd = (path / path.cummax() - 1).min()
    prem_by_year = df.groupby(df.index.year)["prem_pct"].sum()
    return {"df": df, "cagr": cagr * 100, "max_dd": dd * 100, "prem_by_year": prem_by_year,
            "months_hedged": int(df["hedged"].sum()), "months": len(df)}
