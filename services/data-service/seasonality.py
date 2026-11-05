"""
SEAG for NSE: seasonality of a stock or index from its daily closes (Bloomberg SEAG).

Monthly returns are close-to-close on the last session of each month (split/bonus-adjusted closes for stocks; NSE
index closes for indices). The current month is reported separately as "so far" and is left out of the averages.
Descriptive only: a month's average over ~10 years is a handful of observations, so the hit rate and the spread
matter more than the mean.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def seasonality(closes: pd.Series, today: date | None = None) -> dict[str, Any]:
    """`closes`: daily closes indexed by date. Returns the year × month grid of returns (%), per-month statistics
    over completed months, and the current month so far."""
    c = closes.dropna().sort_index()
    c.index = pd.to_datetime(c.index)
    if len(c) < 40:
        return {"grid": [], "months": [], "current": None, "years": 0, "from": None, "to": None}
    today = today or c.index[-1].date()
    month_end = c.groupby(c.index.to_period("M")).last()
    rets = month_end.pct_change() * 100
    first_period = c.index[0].to_period("M")
    rets = rets[rets.index > first_period]              # the first month is partial: no full return for it
    cur_period = pd.Period(today, "M")
    current = None
    if len(rets) and rets.index[-1] == cur_period and c.index[-1].to_period("M") == cur_period:
        current = {"month": MONTHS[cur_period.month - 1], "year": cur_period.year, "ret": round(float(rets.iloc[-1]), 2),
                   "asof": c.index[-1].date().isoformat()}
        rets = rets.iloc[:-1]
    grid: dict[int, dict[str, float | None]] = {}
    for p, v in rets.items():
        grid.setdefault(p.year, {m: None for m in MONTHS})[MONTHS[p.month - 1]] = round(float(v), 2)
    if current:
        grid.setdefault(current["year"], {m: None for m in MONTHS})
    months = []
    for i, m in enumerate(MONTHS, 1):
        v = rets[[p.month == i for p in rets.index]]
        if len(v):
            months.append({"month": m, "n": int(len(v)), "avg": round(float(v.mean()), 2), "median": round(float(v.median()), 2),
                           "pct_up": round(float((v > 0).mean() * 100)), "best": round(float(v.max()), 2),
                           "worst": round(float(v.min()), 2)})
        else:
            months.append({"month": m, "n": 0, "avg": None, "median": None, "pct_up": None, "best": None, "worst": None})
    years = sorted(grid)
    yearly = {}
    for y in years:
        yc = c[c.index.year == y]
        prev = c[c.index.year < y]
        if len(yc) and len(prev):
            yearly[y] = round(float((yc.iloc[-1] / prev.iloc[-1] - 1) * 100), 2)
    return {"grid": [{"year": y, "months": grid[y], "year_ret": yearly.get(y)} for y in reversed(years)],
            "months": months, "current": current, "years": len(years),
            "from": c.index[0].date().isoformat(), "to": c.index[-1].date().isoformat()}
