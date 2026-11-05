"""
FII/FPI and DII cash-market flows from NSE (`/api/fiidiiTradeReact`: NSE + BSE + MSEI combined, provisional,
₹ crore). The API serves only the latest trading day, so the terminal collects it every evening; history in
`nse_fii_dii_cash` starts on 12 Oct 2026.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

import httpx
import pandas as pd

PAGE = "https://www.nseindia.com/reports/fii-dii"
API = "https://www.nseindia.com/api/fiidiiTradeReact"


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(records: list[dict]) -> pd.DataFrame:
    """[{category, date '09-Oct-2026', buyValue, sellValue, netValue}] → date, category (FII | DII), buy/sell/net ₹ cr."""
    rows = []
    for r in records or []:
        raw = str(r.get("category", "")).upper()
        cat = "FII" if raw.startswith("FII") or "FPI" in raw else "DII" if raw.startswith("DII") else None
        try:
            day = datetime.strptime(str(r.get("date")), "%d-%b-%Y").date()
        except ValueError:
            continue
        if cat is None:
            continue
        rows.append({"date": day, "category": cat, "buy_cr": _num(r.get("buyValue")),
                     "sell_cr": _num(r.get("sellValue")), "net_cr": _num(r.get("netValue"))})
    return pd.DataFrame(rows, columns=["date", "category", "buy_cr", "sell_cr", "net_cr"])


def fetch(headers: dict[str, str]) -> pd.DataFrame:
    with httpx.Client(headers={**headers, "Accept": "application/json,*/*", "Referer": PAGE},
                      timeout=20, follow_redirects=True) as client:
        client.get(PAGE)                      # cookie warm-up
        time.sleep(0.5)
        r = client.get(API)
        r.raise_for_status()
        return parse(r.json())


def summarize(rows: list[dict]) -> dict[str, Any]:
    """Latest day per category plus 5-session and month-to-date sums (over what has been collected)."""
    if not rows:
        return {"latest_date": None, "latest": {}, "sum_5d": {}, "mtd": {}, "sessions": 0}
    df = pd.DataFrame(rows)
    dates = sorted(df["date"].unique())
    last = dates[-1]
    last5 = set(dates[-5:])
    month = last[:7]
    by = lambda d: {c: round(float(v), 2) for c, v in d.groupby("category")["net_cr"].sum().items()}  # noqa: E731
    return {"latest_date": last, "latest": by(df[df["date"] == last]), "sum_5d": by(df[df["date"].isin(last5)]),
            "mtd": by(df[df["date"].str.startswith(month)]), "sessions": len(dates),
            "sessions_5d": len(last5), "sessions_mtd": int(sum(1 for d in dates if d.startswith(month)))}
