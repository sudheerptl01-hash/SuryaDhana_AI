"""
Download NSE's official equity and ETF symbol lists into data/reference/.

These files drive instrument classification (services/data-service/instruments.py).
nse_industry.csv (Nifty Total Market constituents, ~750 names with NSE's industry)
feeds the 40% sector cap of the monthly momentum strategy (shared/momentum.py).
Re-run occasionally (new listings / ETF launches), then restart data-service or call
POST /admin/reclassify-instruments.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/refresh_instrument_reference.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

SOURCES = {
    "nse_equity_list.csv": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "nse_etf_list.csv": "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv",
    "nse_industry.csv": "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
}
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "reference"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*", "Referer": "https://www.nseindia.com/"}
    for name, url in SOURCES.items():
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        if len(lines) < 50:
            print(f"refusing to overwrite {name}: only {len(lines)} lines returned", file=sys.stderr)
            return 1
        (OUT_DIR / name).write_text(resp.text)
        print(f"{name}: {len(lines) - 1} symbols")
    return 0


if __name__ == "__main__":
    sys.exit(main())
