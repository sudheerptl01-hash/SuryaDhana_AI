"""
Equity vs bonds for India: NIFTY 50's earnings yield (100 ÷ NSE's published P/E) minus the 10-year government bond
yield, monthly. The bond yield is the OECD monthly series on FRED (INDIRLTLT01STM, monthly average, published with a
lag of about three months): there is no free daily India 10-year yield. A higher gap = equities cheaper vs bonds.

NSE moved index P/E to consolidated earnings on 31 Mar 2021 (earnings yield jumped ~20% overnight), so percentiles
compare only months on the same basis (from April 2021); earlier months are shown but not compared.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES = "INDIRLTLT01STM"
BASIS_FROM = "2021-04"


def india_10y(cache_dir: Path, max_age_s: int = 86_400) -> pd.Series:
    """Monthly India 10-year yield (%), indexed by month start. Cached in `cache_dir`; refreshed once a day."""
    path = cache_dir / "india_10y_fred.csv"
    if not path.exists() or time.time() - path.stat().st_mtime > max_age_s:
        try:
            # FRED stalls browser-like user agents; a plain client is fast
            r = httpx.get(FRED_URL, params={"id": SERIES}, timeout=20)
            if r.status_code == 200 and r.text.startswith("observation_date"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(r.text, encoding="utf-8")
        except httpx.HTTPError:
            pass                                   # keep serving the cached copy
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    s = pd.to_numeric(df[SERIES], errors="coerce")
    return pd.Series(s.to_numpy(), index=pd.to_datetime(df["observation_date"]).dt.to_period("M")).dropna()


def yield_gap(nifty: pd.DataFrame, y10: pd.Series) -> dict[str, Any]:
    """`nifty`: daily rows with date, pe (NIFTY 50) · `y10`: monthly yields indexed by Period('M').
    Returns the monthly series (earnings yield, bond yield, gap) and same-basis statistics of the gap."""
    if nifty.empty or y10.empty:
        return {"points": [], "stats": None, "basis_from": BASIS_FROM}
    n = nifty[nifty["pe"] > 0].copy()
    n["month"] = pd.to_datetime(n["date"]).dt.to_period("M")
    ey = (100 / n.groupby("month")["pe"].mean()).rename("ey")
    df = pd.concat([ey, y10.rename("y10")], axis=1, join="inner").dropna()
    df["gap"] = df["ey"] - df["y10"]
    points = [{"month": str(m), "ey": round(float(r.ey), 2), "y10": round(float(r.y10), 2), "gap": round(float(r.gap), 2)}
              for m, r in df.iterrows()]
    same = df[df.index >= pd.Period(BASIS_FROM, "M")]["gap"]
    stats = None
    if len(same) >= 12:
        now = float(same.iloc[-1])
        stats = {"month": str(same.index[-1]), "gap": round(now, 2), "pctl": round(float((same < now).mean() * 100)),
                 "median": round(float(same.median()), 2), "p25": round(float(same.quantile(0.25)), 2),
                 "p75": round(float(same.quantile(0.75)), 2), "months": int(len(same))}
    return {"points": points, "stats": stats, "basis_from": BASIS_FROM,
            "bond_through": str(y10.index[-1]) if len(y10) else None}
