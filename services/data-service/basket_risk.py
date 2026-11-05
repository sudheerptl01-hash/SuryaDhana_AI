"""
Risk profile of a basket (the Decision Desk's momentum watchlist, a watchlist, any list of NSE symbols): per-stock
annualised volatility, beta to NIFTY 50, 1-year return and max drawdown, and for the equal-weight basket its
volatility, beta, max drawdown, average pairwise correlation and diversification ratio.

Daily returns are close ÷ prev_close − 1 from the NSE bhavcopy: NSE adjusts prev_close on ex-dates, so splits and
bonuses do not show up as crashes. Descriptive statistics over the trailing window; no forecasts.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _max_drawdown(r: pd.Series) -> Optional[float]:
    r = r.dropna()
    if r.empty:
        return None
    wealth = (1 + r).cumprod()
    return float((wealth / wealth.cummax() - 1).min() * 100)


def tail_risk(r: pd.Series, level: float = 0.95) -> dict[str, Optional[float]]:
    """Historical one-day value-at-risk and expected shortfall (%, as positive losses) and the worst day, from the
    window's daily returns: the loss exceeded on 5% of days, and the average loss on those days."""
    r = r.dropna()
    if len(r) < 60:
        return {"var95": None, "es95": None, "worst_day": None}
    q = float(r.quantile(1 - level, interpolation="lower"))      # an observed day, not a blend with a gain
    return {"var95": round(-q * 100, 2), "es95": round(float(-r[r <= q].mean() * 100), 2), "worst_day": round(float(-r.min() * 100), 2)}


def basket_risk(rets: pd.DataFrame, nifty: pd.Series, min_obs: int = 60,
                weights: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """`rets`: dates × symbols daily returns; `nifty`: daily returns indexed by date. `weights` (e.g. holding values)
    makes the basket value-weighted, renormalised each day over the stocks with a return; default equal weight."""
    rets = rets.sort_index()
    nifty = nifty.reindex(rets.index)
    stocks = []
    for sym in rets.columns:
        r = rets[sym].dropna()
        if len(r) < min_obs:
            stocks.append({"symbol": sym, "obs": len(r), "vol": None, "beta": None, "ret": None, "max_dd": None})
            continue
        n = nifty.reindex(r.index)
        both = pd.concat([r, n], axis=1).dropna()
        beta = float(np.cov(both.iloc[:, 0], both.iloc[:, 1])[0, 1] / both.iloc[:, 1].var()) if len(both) >= min_obs else None
        stocks.append({"symbol": sym, "obs": len(r), "vol": float(r.std() * np.sqrt(TRADING_DAYS) * 100), "beta": beta,
                       "ret": float(((1 + r).prod() - 1) * 100), "max_dd": _max_drawdown(r)})
    ok = [s["symbol"] for s in stocks if s["vol"] is not None]
    out: dict[str, Any] = {"stocks": stocks, "window": {"start": str(rets.index.min())[:10] if len(rets) else None,
                                                      "end": str(rets.index.max())[:10] if len(rets) else None, "days": len(rets)}}
    if len(ok) >= 2:
        sub = rets[ok]
        if weights:
            w = pd.Series({k: max(float(weights.get(k, 0.0)), 0.0) for k in ok})
            if w.sum() <= 0:
                w = pd.Series(1.0, index=ok)
            mask = sub.notna()
            eq = (sub.fillna(0) * w).sum(axis=1) / (mask * w).sum(axis=1).replace(0, np.nan)
        else:
            eq = sub.mean(axis=1, skipna=True)                 # equal weight, rebalanced daily
        corr = sub.corr(min_periods=min_obs).values
        iu = np.triu_indices_from(corr, k=1)
        pairs = corr[iu]
        pairs = pairs[~np.isnan(pairs)]
        both = pd.concat([eq, nifty], axis=1).dropna()
        avg_vol = float(np.mean([s["vol"] for s in stocks if s["vol"] is not None]))
        bvol = float(eq.std() * np.sqrt(TRADING_DAYS) * 100)
        hi = np.unravel_index(np.nanargmax(np.where(np.triu(np.ones_like(corr), 1) > 0, corr, np.nan)), corr.shape)
        out["basket"] = {
            "n": len(ok), "weighting": "value" if weights else "equal", "vol": bvol, "avg_stock_vol": avg_vol, "diversification": avg_vol / bvol if bvol else None,
            "beta": float(np.cov(both.iloc[:, 0], both.iloc[:, 1])[0, 1] / both.iloc[:, 1].var()) if len(both) >= min_obs else None,
            "ret": float(((1 + eq).prod() - 1) * 100), "max_dd": _max_drawdown(eq), **tail_risk(eq),
            "avg_corr": float(pairs.mean()) if len(pairs) else None,
            "most_correlated": {"a": ok[hi[0]], "b": ok[hi[1]], "corr": float(corr[hi])} if len(pairs) else None,
        }
    nn = nifty.dropna()
    if len(nn) >= min_obs:                                  # NIFTY for comparison, also for a single stock
        out["nifty"] = {"vol": float(nn.std() * np.sqrt(TRADING_DAYS) * 100), "ret": float(((1 + nn).prod() - 1) * 100),
                        "max_dd": _max_drawdown(nn), **tail_risk(nn)}
    return out
