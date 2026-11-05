#!/usr/bin/env python
"""
Backfill index valuation history (P/E, P/B, dividend yield) from NSE's daily index close files:

    nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv

    PYTHONPATH=. python scripts/backfill_index_valuation.py [--since 2012-01-01]
    PYTHONPATH=. python scripts/backfill_index_valuation.py --recent 10      # nightly top-up (scheduler, 19:15)

Writes data/nse_archive/derived/index_valuation_history.csv (date, index, close, pe, pb, dy) for the main and
sector indices (NSE serves these files from about mid-2012). Incremental: dates already in the file are skipped. Session dates come from our NSE bhavcopy, read
through a snapshot copy of the DuckDB file (safe while data-service runs); `--recent N` skips the database and tries
the weekdays of the last N days instead (a holiday is just a 404), which is what the nightly job uses.
"""
from __future__ import annotations

import argparse
import io
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "services" / "data-service"))
from bhavcopy import HEADERS  # noqa: E402
from results_drift_study import snapshot_connect  # noqa: E402

KEEP = {"Nifty 50", "Nifty Next 50", "Nifty 500", "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty Bank", "Nifty IT",
        "Nifty FMCG", "Nifty Pharma", "Nifty Auto", "Nifty Metal", "Nifty Realty", "Nifty Energy", "Nifty Midcap 100",
        "Nifty Smallcap 100"}
# pre-2016 files use the CNX-era names; map them onto today's (CNX Midcap / Smallcap were renamed Midcap 100 / Smallcap 100)
ALIASES = {"S&P CNX Nifty": "Nifty 50", "CNX Nifty": "Nifty 50", "CNX Nifty Junior": "Nifty Next 50",
           "S&P CNX 500": "Nifty 500", "CNX 500": "Nifty 500", "CNX Midcap": "Nifty Midcap 100",
           "CNX Smallcap": "Nifty Smallcap 100", **{f"CNX {s}": f"Nifty {s}" for s in
                                                    ("Auto", "Bank", "Energy", "FMCG", "IT", "Metal", "Pharma", "Realty")}}
OUT = ROOT / "data" / "nse_archive" / "derived" / "index_valuation_history.csv"
URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"


def parse(content: bytes, day: pd.Timestamp) -> pd.DataFrame:
    """One daily file → rows for the kept indices (index names upper-cased as allIndices spells them)."""
    df = pd.read_csv(io.BytesIO(content))
    df.columns = [c.strip() for c in df.columns]
    df["Index Name"] = df["Index Name"].astype(str).str.strip().replace(ALIASES)
    df = df[df["Index Name"].isin(KEEP)]
    num = lambda s: pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")  # noqa: E731
    return pd.DataFrame({"date": day.date().isoformat(), "index": df["Index Name"].str.strip().str.upper(),
                         "close": num(df["Closing Index Value"]), "pe": num(df["P/E"]), "pb": num(df["P/B"]),
                         "dy": num(df["Div Yield"])})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2012-01-01")
    ap.add_argument("--sleep", type=float, default=0.35)
    ap.add_argument("--recent", type=int, default=0, help="only the weekdays of the last N days (no database needed)")
    args = ap.parse_args()
    if args.recent:
        days = list(pd.bdate_range(pd.Timestamp.now().normalize() - pd.Timedelta(days=args.recent), pd.Timestamp.now().normalize()))
    else:
        tmp = Path(tempfile.mkdtemp(prefix="ivh_"))
        try:
            con = snapshot_connect(tmp)
            days = [pd.Timestamp(d) for (d,) in con.execute(
                "SELECT DISTINCT date FROM nse_bhavcopy WHERE date >= ?::DATE ORDER BY date", [args.since]).fetchall()]
            con.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    have = set(pd.read_csv(OUT)["date"]) if OUT.exists() else set()
    todo = [d for d in days if d.date().isoformat() not in have]
    print(f"{len(days)} {'weekdays' if args.recent else 'sessions'} since {days[0].date() if days else args.since}; {len(todo)} to fetch", flush=True)
    client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
    frames, misses = [], 0
    for i, d in enumerate(todo, 1):
        try:
            r = client.get(URL.format(d=d))
            if r.status_code == 200 and r.content[:10].lower().startswith(b"index name"):
                frames.append(parse(r.content, d))
            else:
                misses += 1
        except (httpx.HTTPError, ValueError, KeyError):
            misses += 1
        if i % 100 == 0 or i == len(todo):
            if frames:                                   # flush progress so an interruption keeps what was read
                OUT.parent.mkdir(parents=True, exist_ok=True)
                new = pd.concat(frames, ignore_index=True)
                old = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame(columns=new.columns)
                pd.concat([old, new], ignore_index=True).drop_duplicates(["date", "index"]).sort_values(["date", "index"]).to_csv(OUT, index=False)
                frames = []
            print(f"{i}/{len(todo)} · misses {misses}", flush=True)
        time.sleep(args.sleep)


if __name__ == "__main__":
    main()
