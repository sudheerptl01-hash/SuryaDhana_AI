"""
DEAL page: market-wide bulk and block deals, netted per client per stock per day (the same netting and
institution tag as the research in shared/deal_filters.py), with the deal's share of the day's volume and the
move since the deal day's close.

Research context (reports/held_overnight/FINDINGS.md): stocks net-bought by a non-institutional client through a
bulk deal lagged random picks over the next 20 sessions; mutual-fund / insurer buying did not. This page shows
the events; it does not trade them.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from shared.deal_filters import INSTITUTION_RE


def build_deals(deals: pd.DataFrame, px: pd.DataFrame, min_value: float = 0.0) -> list[dict[str, Any]]:
    """One row per (date, kind, symbol, client) with |net| ≥ half the gross (intraday round trips drop out)."""
    if deals is None or deals.empty:
        return []
    d = deals.dropna(subset=["qty", "price"]).copy()
    d["date"] = pd.to_datetime(d["date"])
    d["buy"] = d["side"].astype(str).str.upper().str.startswith("B")
    d["signed"] = np.where(d["buy"], d["qty"], -d["qty"])
    d["notional"] = d["qty"] * d["price"]
    g = d.groupby(["date", "kind", "symbol", "client_name"], as_index=False, dropna=False).agg(
        security_name=("security_name", "first"), net=("signed", "sum"), gross=("qty", "sum"),
        notional=("notional", "sum"))
    g = g[(g["gross"] > 0) & (g["net"].abs() >= 0.5 * g["gross"])].copy()
    g["avg_price"] = g["notional"] / g["gross"]
    g["value"] = g["net"].abs() * g["avg_price"]
    g = g[g["value"] >= min_value]
    if g.empty:
        return []
    # NSE also lists a block deal in the bulk file when it crosses 0.5% of equity: the same trade (date, stock, client,
    # net quantity) would count twice. Keep the block row.
    g["_rank"] = np.where(g["kind"] == "block", 0, 1)
    g = g.sort_values("_rank").drop_duplicates(["date", "symbol", "client_name", "net"], keep="first").drop(columns="_rank")
    g["direction"] = np.where(g["net"] > 0, "buy", "sell")
    g["institution"] = g["client_name"].fillna("").str.contains(INSTITUTION_RE)

    if px is not None and not px.empty:
        p = px.copy()
        p["date"] = pd.to_datetime(p["date"])
        day = p[["symbol", "date", "close", "volume"]].rename(columns={"close": "deal_close", "volume": "day_volume"})
        g = g.merge(day, on=["symbol", "date"], how="left")
        last = p.sort_values("date").groupby("symbol").tail(1)[["symbol", "close", "date"]].rename(
            columns={"close": "last_close", "date": "last_date"})
        g = g.merge(last, on="symbol", how="left")
        g["pct_of_volume"] = np.where(g["day_volume"] > 0, g["net"].abs() / g["day_volume"] * 100, np.nan)
        g["since_pct"] = (g["last_close"] / g["deal_close"] - 1) * 100
    else:
        for c in ("deal_close", "day_volume", "last_close", "last_date", "pct_of_volume", "since_pct"):
            g[c] = np.nan

    g = g.sort_values(["date", "value"], ascending=[False, False])
    g["date"] = g["date"].dt.strftime("%Y-%m-%d")
    g["last_date"] = pd.to_datetime(g["last_date"]).dt.strftime("%Y-%m-%d")
    g["qty"] = g["net"].abs()
    cols = ["date", "kind", "symbol", "security_name", "client_name", "direction", "institution", "qty", "avg_price",
            "value", "pct_of_volume", "deal_close", "last_close", "last_date", "since_pct"]
    out = g[cols].astype(object).where(g[cols].notna(), None)
    return out.to_dict(orient="records")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Header numbers: deal count, buy / sell value, institutional share, the stocks with the biggest net flow."""
    if not rows:
        return {"deals": 0, "buy_value": 0.0, "sell_value": 0.0, "institution_value": 0.0, "top_net": []}
    df = pd.DataFrame(rows)
    signed = np.where(df["direction"] == "buy", df["value"], -df["value"])
    net = pd.Series(signed, index=df.index).groupby(df["symbol"]).sum().sort_values()
    top = pd.concat([net[net > 0].tail(5)[::-1], net[net < 0].head(5)])
    return {"deals": len(df), "buy_value": float(df.loc[df["direction"] == "buy", "value"].sum()),
            "sell_value": float(df.loc[df["direction"] == "sell", "value"].sum()),
            "institution_value": float(df.loc[df["institution"].astype(bool), "value"].sum()),
            "top_net": [{"symbol": s, "net_value": float(v)} for s, v in top.items()]}


def short_selling(shorts: pd.DataFrame, volume: pd.DataFrame) -> list[dict]:
    """Institutional short sales (NSE's daily disclosure) per stock over a window: quantity shorted, the number of
    days with a disclosure, the last one, and the shorted quantity as a share of all shares traded in the window.
    `shorts`: date, symbol, qty · `volume`: date, symbol, volume (equity series). Largest share of volume first."""
    if shorts.empty:
        return []
    s = shorts.groupby("symbol").agg(short_qty=("qty", "sum"), days=("date", "nunique"), last=("date", "max")).reset_index()
    v = volume.groupby("symbol")["volume"].sum().rename("window_volume") if not volume.empty else pd.Series(dtype=float, name="window_volume")
    s = s.merge(v, left_on="symbol", right_index=True, how="left")
    s["short_pct_of_volume"] = np.where(s["window_volume"] > 0, s["short_qty"] / s["window_volume"] * 100, np.nan)
    s = s.sort_values(["short_pct_of_volume", "short_qty"], ascending=False, na_position="last")
    out = []
    for r in s.itertuples(index=False):
        out.append({"symbol": r.symbol, "short_qty": float(r.short_qty), "days": int(r.days), "last": str(pd.Timestamp(r.last).date()),
                    "window_volume": None if pd.isna(r.window_volume) else float(r.window_volume),
                    "short_pct_of_volume": None if pd.isna(r.short_pct_of_volume) else round(float(r.short_pct_of_volume), 3)})
    return out
