"""
Spot-check the 2010–2019 part of the NSE panel (classic CM bhavcopy era) against
Yahoo's own daily history for a sample of liquid stocks, fetched live (the DuckDB
Yahoo table only starts in 2020).

Yahoo adjusts for dividends as well as splits, so ex-dividend days differ by the
dividend (a few %); only gaps > 5 points are counted as disagreements.

Usage:  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/nse_panel_qa_old.py
Output: reports/data_quality/NSE_PANEL_QA_2010_2019.md
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import httpx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from nse_panel import load_panel  # noqa: E402

START, END = "2010-01-01", "2019-09-30"
SAMPLE = 60


def yahoo_adjclose(sym: str, client: httpx.Client) -> pd.Series | None:
    p1 = int(pd.Timestamp(START).timestamp())
    p2 = int(pd.Timestamp(END).timestamp()) + 86400
    for host in ("query1", "query2"):
        try:
            r = client.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}.NS",
                           params={"period1": p1, "period2": p2, "interval": "1d"})
            if r.status_code != 200:
                continue
            res = r.json()["chart"]["result"][0]
            ts = pd.to_datetime(res["timestamp"], unit="s") + pd.Timedelta(hours=5, minutes=30)
            adj = res["indicators"]["adjclose"][0]["adjclose"]
            return pd.Series(adj, index=ts.normalize(), dtype=float).dropna()
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
            continue
    return None


def main() -> None:
    db = ROOT / "data" / "market.duckdb"
    tmp = Path(tempfile.mkdtemp(prefix="qa_old_"))
    shutil.copy2(db, tmp / "s.duckdb")
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", tmp / "s.duckdb.wal")
    con = duckdb.connect(str(tmp / "s.duckdb"))
    try:
        panel = load_panel(con, start=START, end=END)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)

    close = panel["close"]
    liq = panel["turnover_cr"].median()
    present = close.notna().sum()
    cands = liq[(present > 1500)].sort_values(ascending=False).index[:400]
    rng = np.random.default_rng(11)
    sample = list(rng.choice(cands, size=min(SAMPLE, len(cands)), replace=False))
    ev = panel["corporate_actions"]
    ev_old = ev[(ev["date"] >= START) & (ev["date"] <= END)]

    rows, bad = [], []
    with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0 (SuryaDhana-QA)"}) as client:
        for sym in sample:
            y = yahoo_adjclose(sym, client)
            time.sleep(0.3)
            if y is None or y.empty:
                continue
            n = close[sym].dropna()
            common = n.index.intersection(y.index)
            if len(common) < 250:
                continue
            rn, ry = n.loc[common].pct_change(), y.loc[common].pct_change()
            d = (rn - ry).abs().dropna()
            rows.append({"symbol": sym, "days": len(d), "gt5pts": int((d > 0.05).sum()),
                         "gt20pts": int((d > 0.2).sum()),
                         "total_return_nse": float(n.loc[common].iloc[-1] / n.loc[common].iloc[0] - 1),
                         "total_return_yahoo": float(y.loc[common].iloc[-1] / y.loc[common].iloc[0] - 1)})
            for dt in d[d > 0.2].index:
                bad.append((sym, dt.date(), round(float(rn[dt]), 3), round(float(ry[dt]), 3)))
    df = pd.DataFrame(rows)
    days = int(df["days"].sum()) if len(df) else 0
    lines = ["# NSE panel spot-check 2010–2019 (classic CM bhavcopy era)", "",
             f"Panel {START} → {END}: {close.shape[0]:,} sessions × {close.shape[1]:,} symbols; "
             f"corporate actions applied in this era: {len(ev_old):,} ({ev_old['source'].value_counts().to_dict()})", "",
             f"Sample: {len(df)} liquid stocks compared with Yahoo's live history ({days:,} daily returns).",
             f"- Days differing by > 5 points: **{int(df['gt5pts'].sum()) if len(df) else 0}** "
             f"({(df['gt5pts'].sum() / max(days, 1)):.3%})",
             f"- Days differing by > 20 points (missed or wrong split/bonus): **{int(df['gt20pts'].sum()) if len(df) else 0}**",
             f"- Median total-return gap NSE vs Yahoo over the decade: "
             f"{(df['total_return_yahoo'] - df['total_return_nse']).median():.1%} (Yahoo includes dividends)", "",
             "Large disagreements (symbol, date, NSE return, Yahoo return):", ""]
    lines += [f"- {b}" for b in bad[:40]]
    out = ROOT / "reports" / "data_quality"
    out.mkdir(parents=True, exist_ok=True)
    (out / "NSE_PANEL_QA_2010_2019.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
