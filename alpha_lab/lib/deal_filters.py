"""
Bulk-deal filters shared by research (scripts/held_overnight_study.py), the momentum
backtest (scripts/phase_b_allocator.py, scripts/desk_filter_backtest.py) and the live
Decision Desk (via shared.momentum.compute_targets).

Evidence (reports/held_overnight/FINDINGS.md, 2026-09-28): stocks that a non-institutional
client net-bought through a bulk deal lagged same-date random picks by 2.2% (2019–23) and
1.2% (2024–26) over the next 20 sessions; mutual-fund / insurer buying did not.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

INSTITUTION_RE = re.compile(r"MUTUAL\s*FUND|\bMF\b|INSURANCE|ASSURANCE|PENSION|PROVIDENT", re.I)


def net_bulk_deals(deals: pd.DataFrame) -> pd.DataFrame:
    """Net each client's buys and sells per stock per day. Clients who bought and sold about
    the same amount (intraday round trips) drop out; the rest are tagged buy or sell."""
    d = deals.dropna(subset=["qty"]).copy()
    d["signed"] = np.where(d["side"].astype(str).str.upper() == "BUY", d["qty"], -d["qty"])
    d["gross"] = d["qty"]
    g = d.groupby(["date", "symbol", "client_name"], as_index=False).agg(net=("signed", "sum"), gross=("gross", "sum"))
    g = g[g["net"].abs() >= 0.5 * g["gross"]]
    g["institution"] = g["client_name"].fillna("").str.contains(INSTITUTION_RE)
    g["direction"] = np.where(g["net"] > 0, "buy", "sell")
    return g


def non_institutional_buy_events(deals: pd.DataFrame) -> pd.DataFrame:
    """(date, symbol) of every bulk-deal net BUY by a client that is not a mutual fund or insurer.
    `deals` holds bulk rows with date, symbol, client_name, side, qty."""
    if deals is None or deals.empty:
        return pd.DataFrame(columns=["date", "symbol"])
    net = net_bulk_deals(deals)
    ev = net[(~net["institution"]) & (net["direction"] == "buy")][["date", "symbol"]].drop_duplicates()
    ev["date"] = pd.to_datetime(ev["date"])
    return ev.reset_index(drop=True)
