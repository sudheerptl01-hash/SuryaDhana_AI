#!/usr/bin/env python
"""
Nifty 500 Data Pipeline
=======================
Complete data management pipeline for 500 NSE stocks.
Handles initial load, daily updates, fundamentals, filtering, and resume.

MODES:
  initial    One-time 5yr OHLCV download for all 500 stocks (~30 min)
  daily      Daily 6 PM update — today's candle for all 500 stocks
  enrich     Download fundamentals, dividends, splits for all stocks
  filter     Apply conditions and show/export filtered stock list
  status     Show pipeline state and database stats
  universe   Refresh nifty500_universe.csv from NSE live data
  reset      Reset failed/pending tickers so they retry on next run

USAGE:
  # One-time initial load (run once, resumes if interrupted)
  python scripts/nifty500_pipeline.py --mode initial

  # Resume an interrupted initial load
  python scripts/nifty500_pipeline.py --mode initial --resume

  # Force re-download specific tickers
  python scripts/nifty500_pipeline.py --mode initial --tickers RELIANCE TCS --force

  # Daily update (add to cron: 0 18 * * 1-5)
  python scripts/nifty500_pipeline.py --mode daily

  # Enrich with fundamentals + dividends + splits
  python scripts/nifty500_pipeline.py --mode enrich

  # Filter stocks and show top candidates
  python scripts/nifty500_pipeline.py --mode filter

  # Database + pipeline status
  python scripts/nifty500_pipeline.py --mode status

  # Refresh Nifty 500 universe from NSE
  python scripts/nifty500_pipeline.py --mode universe
"""
from __future__ import annotations

import argparse
import json
import time
import sys
import io
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

STATE_FILE       = ROOT / "data" / ".pipeline_state.json"
UNIVERSE_CSV     = ROOT / "data" / "nifty500_universe.csv"
UNIVERSE_1000_CSV = ROOT / "data" / "NSE_1000_MIDCAP_500.csv"
UNIVERSE_1500_CSV = ROOT / "data" / "NSE_1500.csv"
DB_PATH          = ROOT / "data" / "market.duckdb"

BATCH_SIZE   = 20    # yfinance batch download size
BATCH_DELAY  = 1.5   # seconds between batches (yfinance rate limit)
TICKER_DELAY = 0.3   # seconds between individual tickers


# ── Helpers ────────────────────────────────────────────────────────────────────

def _coerce_df_for_duckdb(df):
    """Convert pandas StringDtype columns to object so DuckDB 1.1.x accepts them."""
    import pandas as pd
    df = df.copy()
    for col in df.select_dtypes(include=["string"]).columns:
        df[col] = df[col].astype(object)
    return df


def _read_env() -> dict[str, str]:
    env_file = ROOT / ".env"
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _load_state() -> dict[str, dict]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _mark(state: dict, ticker: str, status: str, **kwargs) -> None:
    state[ticker] = {"status": status, "updated": str(date.today()), **kwargs}
    _save_state(state)


def _bar(done: int, total: int, width: int = 25) -> str:
    filled = int(width * done / total) if total else 0
    pct = done / total * 100 if total else 0
    return f"[{'█' * filled}{'░' * (width - filled)}] {done}/{total} {pct:.0f}%"


def _load_universe() -> "pd.DataFrame":
    """Load the most comprehensive universe CSV available (1500 > 1000 > 500)."""
    import pandas as pd
    for csv_path, label in [
        (UNIVERSE_1500_CSV, "universe1500 (NSE_1500.csv)"),
        (UNIVERSE_1000_CSV, "universe1000 (NSE_1000_MIDCAP_500.csv)"),
        (UNIVERSE_CSV,      "universe500 (nifty500_universe.csv)"),
    ]:
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            print(f"  [Universe] Using {label}: {len(df)} tickers")
            return df
    print("[ERROR] No universe CSV found. Run --mode universe (or universe1000/universe1500) first.")
    sys.exit(1)


def _get_store():
    from storage.duckdb_store import DuckDBStore
    return DuckDBStore(str(DB_PATH))


def _get_last_dates() -> dict[str, "date"]:
    """
    Query DuckDB and return {ticker: last_stored_date} for every ticker.
    Used by both initial and daily modes to decide how much to fetch.
    """
    import duckdb
    if not DB_PATH.exists():
        return {}
    try:
        conn = duckdb.connect(str(DB_PATH))
        rows = conn.execute(
            "SELECT ticker, MAX(date) AS last_date FROM ohlcv GROUP BY ticker"
        ).fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows if r[1] is not None}
    except Exception:
        return {}


def _fetch_and_store(
    tickers_with_ranges: list[tuple[str, "date", "date"]],
    store,
    label: str = "",
) -> tuple[dict[str, int], list[str]]:
    """
    Core fetch loop: download OHLCV from yfinance for each (ticker, start, end)
    and upsert into DuckDB.

    Batches tickers that share the same date range for efficiency.
    Returns (results: {ticker: rows}, errors: [ticker]).
    """
    import pandas as pd
    import yfinance as yf
    from collections import defaultdict

    # Group by (start, end) so we can batch-download where possible
    range_groups: dict[tuple, list[str]] = defaultdict(list)
    for ticker, start, end in tickers_with_ranges:
        range_groups[(start, end)].append(ticker)

    results: dict[str, int] = {}
    errors: list[str] = []
    total = len(tickers_with_ranges)
    done_count = 0

    for (start, end), group_tickers in range_groups.items():
        batches = [group_tickers[i:i + BATCH_SIZE] for i in range(0, len(group_tickers), BATCH_SIZE)]

        for bi, batch in enumerate(batches):
            yf_syms = [f"{t}.NS" for t in batch]
            try:
                raw = yf.download(
                    tickers=yf_syms,
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
            except Exception as exc:
                for t in batch:
                    errors.append(t)
                    done_count += 1
                time.sleep(BATCH_DELAY)
                continue

            is_multi = isinstance(raw.columns, pd.MultiIndex)

            for ticker in batch:
                yf_sym = f"{ticker}.NS"
                done_count += 1
                try:
                    if is_multi:
                        df = raw.xs(yf_sym, axis=1, level=1) \
                            if yf_sym in raw.columns.get_level_values(1) \
                            else pd.DataFrame()
                    else:
                        df = raw

                    if df.empty or df.dropna(subset=["Close"]).empty:
                        errors.append(ticker)
                        print(f"  {ticker:<15} no data returned          {_bar(done_count, total)}")
                        continue

                    df = df.dropna(subset=["Close"])
                    df.index = pd.to_datetime(df.index).date
                    rows_data = []
                    for row_date, row in df.iterrows():
                        try:
                            rows_data.append({
                                "ticker": ticker,
                                "date": row_date,
                                "open": float(row["Open"]),
                                "high": float(row["High"]),
                                "low": float(row["Low"]),
                                "close": float(row["Close"]),
                                "volume": int(row["Volume"]),
                                "adjusted_close": float(row["Close"]),
                            })
                        except Exception:
                            continue

                    if not rows_data:
                        errors.append(ticker)
                        continue

                    out_df = pd.DataFrame(rows_data)
                    rows = store.upsert_ohlcv(out_df, source="yfinance")
                    results[ticker] = rows
                    tag = label or f"{start}→{end}"
                    print(f"  {ticker:<15} {rows:>5} rows  [{tag}]  {_bar(done_count, total)}")

                except Exception as exc:
                    errors.append(ticker)
                    print(f"  {ticker:<15} ERROR: {str(exc)[:50]}")

            time.sleep(BATCH_DELAY)

    return results, errors


# ── NSE Universe Refresh ───────────────────────────────────────────────────────

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/",
}
NSE_BASE = "https://niftyindices.com/IndexConstituent"

UNIVERSE_1000_CSV = ROOT / "data" / "NSE_1000_MIDCAP_500.csv"


def _fetch_nse_index(filename: str, index_label: str) -> "pd.DataFrame | None":
    """Fetch one official NSE index constituent CSV from niftyindices.com."""
    import requests, pandas as pd
    url = f"{NSE_BASE}/{filename}"
    try:
        r = requests.get(url, headers=NSE_HEADERS, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df = df[df["Series"] == "EQ"][["Symbol", "Company Name", "Industry", "ISIN Code"]].copy()
        df.columns = ["ticker", "company_name", "sector", "isin"]
        df["ticker"] = df["ticker"].str.strip()
        df["index"] = index_label
        df = df.drop_duplicates("ticker").reset_index(drop=True)
        print(f"  [OK] {filename}: {len(df)} stocks")
        return df
    except Exception as exc:
        print(f"  [WARN] {filename} failed: {exc}")
        return None


def mode_universe():
    """Refresh nifty500_universe.csv from NSE (Nifty 500 only)."""
    import pandas as pd
    print("\n  Fetching Nifty 500 constituents from niftyindices.com...")
    df = _fetch_nse_index("ind_nifty500list.csv", "NIFTY500")
    if df is None:
        print("  [ERROR] Failed to fetch Nifty 500 universe")
        sys.exit(1)
    df_out = df[["ticker", "company_name", "sector", "isin"]]
    df_out.to_csv(UNIVERSE_CSV, index=False)
    print(f"  [OK] Saved {len(df_out)} tickers to {UNIVERSE_CSV.name}")
    print(f"  Sectors: {df_out['sector'].value_counts().head(5).to_dict()}")


def _fetch_nse_bhavcopy_tickers() -> "list[str]":
    """
    Download NSE daily bhavcopy to get ALL equity stock symbols.
    Returns list of tickers traded on NSE (EQ series only).
    """
    import requests, io, pandas as pd
    from datetime import date, timedelta

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.nseindia.com/",
    }

    for days_back in range(1, 10):
        d = date.today() - timedelta(days=days_back)
        if d.weekday() >= 5:  # skip weekends
            continue
        dstr = d.strftime("%d%m%Y")
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{dstr}.csv"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200 and "SYMBOL" in r.text[:500]:
                df = pd.read_csv(io.StringIO(r.text))
                series_col = [c for c in df.columns if "SERIES" in c.upper()][0]
                eq = df[df[series_col].str.strip() == "EQ"]
                tickers = eq["SYMBOL"].str.strip().tolist()
                print(f"  [OK] NSE bhavcopy {dstr}: {len(tickers)} EQ stocks")
                return tickers
        except Exception as exc:
            print(f"  [WARN] Bhavcopy {dstr}: {exc}")
    print("  [WARN] Could not fetch bhavcopy")
    return []


def mode_universe_1000():
    """
    Build real NSE 1000 + Midcap 300 universe from official NSE sources only.

    Strategy:
    1. Nifty 500 (504 stocks) — from niftyindices.com with real company names/sectors/ISINs
    2. Midcap indices (150+50) — from niftyindices.com, tagged as NIFTYMIDCAP
    3. Extended universe (top 1000 by rank) — from NSE daily bhavcopy
       For stocks beyond Nifty 500: company name/sector fetched via yfinance in batches.

    Saves to data/NSE_1000_MIDCAP_500.csv
    """
    import pandas as pd
    import yfinance as yf

    print("\n  Building NSE 1000 + Midcap universe from official NSE sources...")
    print("  Step 1: Fetching named indices from niftyindices.com...")

    # ── Layer 1: Named indices (get company name + sector + ISIN) ─────────────
    index_frames = []
    for fname, label in [
        ("ind_nifty500list.csv",            "NIFTY500"),
        ("ind_niftylargemidcap250list.csv",  "NIFTYLARGEMIDCAP250"),
        ("ind_niftymidcap150list.csv",       "NIFTYMIDCAP150"),
        ("ind_niftymidcap50list.csv",        "NIFTYMIDCAP50"),
        ("ind_niftysmallcap250list.csv",     "NIFTYSMALLCAP250"),
        ("ind_niftysmallcap100list.csv",     "NIFTYSMALLCAP100"),
        ("ind_niftysmallcap50list.csv",      "NIFTYSMALLCAP50"),
    ]:
        df = _fetch_nse_index(fname, label)
        if df is not None:
            index_frames.append(df)

    if not index_frames:
        print("  [ERROR] Could not fetch any NSE index data.")
        sys.exit(1)

    # Combine all named-index stocks, build index label map
    all_named = pd.concat(index_frames, ignore_index=True)
    idx_map: dict[str, list[str]] = {}
    info_map: dict[str, dict] = {}
    for _, row in all_named.iterrows():
        t = row["ticker"]
        idx_map.setdefault(t, [])
        if row["index"] not in idx_map[t]:
            idx_map[t].append(row["index"])
        if t not in info_map:
            info_map[t] = {
                "company_name": row["company_name"],
                "sector": row["sector"],
                "isin": row["isin"],
            }

    print(f"  Named indices: {len(info_map)} unique stocks tagged")

    # ── Layer 2: NSE bhavcopy for broader universe ─────────────────────────────
    print("\n  Step 2: Fetching NSE bhavcopy for broader universe...")
    bhavcopy_tickers = _fetch_nse_bhavcopy_tickers()

    # Find tickers in bhavcopy but NOT yet in named indices (truly extended)
    new_tickers = [t for t in bhavcopy_tickers if t not in info_map]
    total_to_check = len(new_tickers)
    print(f"  Extended tickers beyond named indices: {total_to_check}")
    print(f"  Enriching ALL {total_to_check} via yfinance (mktcap > ₹100 Cr filter)...")

    enriched = []
    batch_size = 20
    for i in range(0, total_to_check, batch_size):
        batch = new_tickers[i:i + batch_size]
        for ticker in batch:
            try:
                t = yf.Ticker(f"{ticker}.NS")
                info = t.info or {}
                mc = info.get("marketCap", 0) or 0
                if mc >= 1_000_000_000:  # ₹100 Cr minimum
                    enriched.append({
                        "ticker": ticker,
                        "company_name": (info.get("longName") or info.get("shortName") or ticker).strip(),
                        "sector": (info.get("sector") or "Unknown").strip(),
                        "isin": None,
                        "market_cap": mc,
                    })
            except Exception:
                pass
        time.sleep(BATCH_DELAY)
        done = min(i + batch_size, total_to_check)
        pct = done / total_to_check * 100
        if done % 100 == 0 or done == total_to_check:
            print(f"  yfinance enrichment: {done}/{total_to_check} ({pct:.0f}%)  found {len(enriched)} valid")

    # Sort by market cap descending — no artificial cap
    enriched.sort(key=lambda x: x["market_cap"], reverse=True)
    for e in enriched:
        t = e["ticker"]
        mc_cr = e["market_cap"] / 1e7
        if mc_cr >= 20000:
            idx_map[t] = ["NIFTYLARGECAP"]
        elif mc_cr >= 5000:
            idx_map[t] = ["NIFTYMIDCAP"]
        elif mc_cr >= 500:
            idx_map[t] = ["NIFTYSMALLCAP"]
        else:
            idx_map[t] = ["NIFTYMICROCAP"]
        info_map[t] = {"company_name": e["company_name"], "sector": e["sector"], "isin": e.get("isin"),
                       "market_cap": mc_cr}

    def _cap_category(labels: list[str], mc_cr: float | None) -> str:
        """Derive market-cap category from index labels or actual market cap."""
        if mc_cr is not None:
            if mc_cr >= 20000: return "Large Cap"
            if mc_cr >= 5000:  return "Mid Cap"
            if mc_cr >= 500:   return "Small Cap"
            return "Micro Cap"
        joined = " ".join(labels)
        if "MIDCAP" in joined:   return "Mid Cap"
        if "SMALLCAP" in joined: return "Small Cap"
        return "Large Cap"

    # ── Build final DataFrame ─────────────────────────────────────────────────
    all_tickers = sorted(set(list(info_map.keys())))
    rows = []
    for t in all_tickers:
        info = info_map[t]
        labels = idx_map.get(t, ["NSE"])
        mc_cr = info.get("market_cap")
        rows.append({
            "ticker": t,
            "company_name": info.get("company_name") or t,
            "sector": info.get("sector") or "Unknown",
            "isin": info.get("isin"),
            "index": "|".join(labels),
            "cap_category": _cap_category(labels, mc_cr),
        })

    combined = pd.DataFrame(rows)
    combined.to_csv(UNIVERSE_1000_CSV, index=False)

    named_count = len(info_map) - len(enriched)
    print(f"\n  ✅ Saved {len(combined)} real stocks to {UNIVERSE_1000_CSV.name}")
    print(f"     From named NSE indices : {named_count} stocks (with ISINs)")
    print(f"     From yfinance extended : {len(enriched)} stocks (mktcap > ₹100Cr)")
    print(f"     Total unique           : {len(combined)} stocks")
    cats = combined['cap_category'].value_counts().to_dict()
    print(f"     Cap categories: {cats}")
    print(f"     Sectors: {combined['sector'].value_counts().head(5).to_dict()}")


# ── NSE 1500 Universe Build ────────────────────────────────────────────────────

def mode_universe_1500():
    """
    Build a comprehensive NSE ~1500-stock universe from official NSE sources.

    Strategy:
    1. Pull ALL available named NSE index constituent CSVs (Nifty 500, LargeMidcap 250,
       Midcap 150/50, Smallcap 250/100/50, Microcap 250, Nifty 1000 if published).
       These give real company names, sectors, and ISINs.
    2. Supplement from NSE daily bhavcopy — EQ-series stocks NOT yet in named indices.
    3. Enrich bhavcopy extras via yfinance; keep only stocks with market cap >= ₹200 Cr.
    4. Sort by market cap descending, keep top 1500 (or all if fewer qualify).
    5. Save to data/NSE_1500.csv.
    """
    import pandas as pd
    import yfinance as yf

    print("\n  Building NSE 1500 universe from official NSE sources...")

    # ── Layer 1: All official NSE index constituent files ─────────────────────
    print("  Step 1: Fetching constituent CSVs from niftyindices.com...")
    nse_index_files = [
        ("ind_nifty500list.csv",            "NIFTY500"),
        ("ind_niftylargemidcap250list.csv",  "NIFTYLARGEMIDCAP250"),
        ("ind_niftymidcap150list.csv",       "NIFTYMIDCAP150"),
        ("ind_niftymidcap50list.csv",        "NIFTYMIDCAP50"),
        ("ind_niftysmallcap250list.csv",     "NIFTYSMALLCAP250"),
        ("ind_niftysmallcap100list.csv",     "NIFTYSMALLCAP100"),
        ("ind_niftysmallcap50list.csv",      "NIFTYSMALLCAP50"),
        ("ind_niftymicrocap250list.csv",     "NIFTYMICROCAP250"),
        ("ind_nifty1000list.csv",            "NIFTY1000"),
    ]

    index_frames = []
    for fname, label in nse_index_files:
        df = _fetch_nse_index(fname, label)
        if df is not None:
            index_frames.append(df)

    if not index_frames:
        print("  [ERROR] Could not fetch any NSE index data.")
        sys.exit(1)

    # Build canonical info map + index label map from named indices
    all_named = pd.concat(index_frames, ignore_index=True)
    idx_map: dict[str, list[str]] = {}
    info_map: dict[str, dict] = {}
    for _, row in all_named.iterrows():
        t = row["ticker"]
        idx_map.setdefault(t, [])
        if row["index"] not in idx_map[t]:
            idx_map[t].append(row["index"])
        if t not in info_map:
            info_map[t] = {
                "company_name": row["company_name"],
                "sector": row["sector"],
                "isin": row["isin"],
            }

    print(f"  Named indices: {len(info_map)} unique stocks")

    # ── Layer 2: NSE bhavcopy for stocks not yet in any named index ───────────
    print("\n  Step 2: Fetching NSE bhavcopy for broader universe...")
    bhavcopy_tickers = _fetch_nse_bhavcopy_tickers()
    new_tickers = [t for t in bhavcopy_tickers if t not in info_map]
    print(f"  Bhavcopy extras (not in named indices): {len(new_tickers)}")

    # ── Layer 3: Enrich bhavcopy extras via yfinance ──────────────────────────
    # Minimum ₹200 Cr market cap — lower than the 1000-mode to capture more smallcap
    MC_THRESHOLD = 2_000_000_000  # ₹200 Cr in ₹
    print(f"  Enriching via yfinance (mktcap >= ₹200 Cr)...")
    enriched: list[dict] = []
    for i in range(0, len(new_tickers), 20):
        batch = new_tickers[i:i + 20]
        for ticker in batch:
            try:
                info = yf.Ticker(f"{ticker}.NS").info or {}
                mc = info.get("marketCap", 0) or 0
                if mc >= MC_THRESHOLD:
                    enriched.append({
                        "ticker": ticker,
                        "company_name": (info.get("longName") or info.get("shortName") or ticker).strip(),
                        "sector": (info.get("sector") or "Unknown").strip(),
                        "isin": None,
                        "market_cap": mc,
                    })
            except Exception:
                pass
        time.sleep(BATCH_DELAY)
        done = min(i + 20, len(new_tickers))
        if done % 200 == 0 or done == len(new_tickers):
            print(f"  yfinance: {done}/{len(new_tickers)} checked, {len(enriched)} qualify")

    enriched.sort(key=lambda x: x["market_cap"], reverse=True)

    def _cap_cat(labels: list[str], mc_cr: float | None) -> str:
        if mc_cr is not None:
            if mc_cr >= 20000: return "Large Cap"
            if mc_cr >= 5000:  return "Mid Cap"
            if mc_cr >= 500:   return "Small Cap"
            return "Micro Cap"
        joined = " ".join(labels)
        if "MIDCAP" in joined:    return "Mid Cap"
        if "SMALLCAP" in joined:  return "Small Cap"
        if "MICROCAP" in joined:  return "Micro Cap"
        return "Large Cap"

    for e in enriched:
        t = e["ticker"]
        mc_cr = e["market_cap"] / 1e7
        if mc_cr >= 20000:   idx_map[t] = ["NIFTYLARGECAP"]
        elif mc_cr >= 5000:  idx_map[t] = ["NIFTYMIDCAP"]
        elif mc_cr >= 500:   idx_map[t] = ["NIFTYSMALLCAP"]
        else:                idx_map[t] = ["NIFTYMICROCAP"]
        info_map[t] = {"company_name": e["company_name"], "sector": e["sector"],
                       "isin": None, "market_cap": mc_cr}

    # ── Layer 4: Assign market cap to named-index stocks missing it ───────────
    # Named-index stocks don't have market cap from the CSV; fetch it lazily from yfinance
    # for the purpose of sorting. We do this in bulk for stocks missing market_cap.
    named_no_mc = [t for t in info_map if "market_cap" not in info_map[t]]
    print(f"\n  Step 3: Fetching market cap for {len(named_no_mc)} named-index stocks...")
    for i in range(0, len(named_no_mc), 20):
        batch = named_no_mc[i:i + 20]
        yf_syms = [f"{t}.NS" for t in batch]
        try:
            raw = yf.download(yf_syms, period="1d", progress=False, threads=True, auto_adjust=True)
        except Exception:
            raw = None
        for ticker in batch:
            try:
                info = yf.Ticker(f"{ticker}.NS").info or {}
                mc = info.get("marketCap", 0) or 0
                info_map[ticker]["market_cap"] = mc / 1e7 if mc else None
            except Exception:
                info_map[ticker]["market_cap"] = None
        time.sleep(BATCH_DELAY)
        done = min(i + 20, len(named_no_mc))
        if done % 200 == 0 or done == len(named_no_mc):
            print(f"  Market cap fetch: {done}/{len(named_no_mc)}")

    # ── Build final DataFrame, sort by market cap, keep top 1500 ─────────────
    rows = []
    for t, info in info_map.items():
        labels = idx_map.get(t, ["NSE"])
        mc_cr = info.get("market_cap")
        rows.append({
            "ticker": t,
            "company_name": info.get("company_name") or t,
            "sector": info.get("sector") or "Unknown",
            "isin": info.get("isin"),
            "index": "|".join(labels),
            "cap_category": _cap_cat(labels, mc_cr),
            "market_cap_cr": mc_cr or 0,
        })

    combined = pd.DataFrame(rows).sort_values("market_cap_cr", ascending=False)
    # Keep top 1500 — but keep ALL named-index stocks regardless of count
    named_set = set(all_named["ticker"].unique())
    named_rows = combined[combined["ticker"].isin(named_set)]
    extra_rows = combined[~combined["ticker"].isin(named_set)].head(max(0, 1500 - len(named_rows)))
    combined = pd.concat([named_rows, extra_rows], ignore_index=True) \
                 .sort_values("market_cap_cr", ascending=False) \
                 .drop(columns=["market_cap_cr"])
    combined = combined.drop_duplicates("ticker").reset_index(drop=True)

    combined.to_csv(UNIVERSE_1500_CSV, index=False)
    cats = combined["cap_category"].value_counts().to_dict()
    print(f"\n  ✅ Saved {len(combined)} stocks to {UNIVERSE_1500_CSV.name}")
    print(f"     Named NSE indices : {len(named_rows)} stocks (with ISINs)")
    print(f"     Bhavcopy extended : {len(enriched)} stocks (mktcap >= ₹200Cr)")
    print(f"     Cap categories    : {cats}")
    print(f"     Sectors (top 5)   : {combined['sector'].value_counts().head(5).to_dict()}")


# ── Initial / Sync OHLCV Load (smart incremental) ─────────────────────────────

def mode_initial(args):
    """
    Smart incremental load:
      - Checks DuckDB for the last stored date per ticker
      - New tickers (no data): fetches full 5yr history
      - Existing tickers with stale data: fetches only the delta
      - Tickers already current (last date = yesterday): skipped

    This means running --mode initial again tomorrow will only pull 1 day
    for each ticker, not re-download 5 years.
    """
    universe = _load_universe()
    all_tickers = universe["ticker"].str.strip().tolist()

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        tickers = all_tickers

    store = _get_store()
    today = date.today()
    yesterday = today - timedelta(days=1)
    full_start = today - timedelta(days=args.years * 365 + 30)

    # ── Query DuckDB: what date is the last row we have per ticker? ────────────
    last_dates = {} if args.force else _get_last_dates()

    # ── Classify each ticker ───────────────────────────────────────────────────
    to_fetch: list[tuple[str, date, date]] = []   # (ticker, fetch_from, fetch_to)
    skipped = []

    for ticker in tickers:
        last = last_dates.get(ticker)
        if args.force or last is None:
            # No data at all → full 5yr download
            to_fetch.append((ticker, full_start, today))
        elif last >= yesterday:
            # Already current (has yesterday's or today's close)
            skipped.append(ticker)
        else:
            # Has some data but stale → only fetch the missing delta
            fetch_from = last + timedelta(days=1)
            to_fetch.append((ticker, fetch_from, today))

    # ── Summary of what will happen ────────────────────────────────────────────
    new_tickers  = [(t, s, e) for t, s, e in to_fetch if last_dates.get(t) is None or args.force]
    delta_tickers = [(t, s, e) for t, s, e in to_fetch if t not in [x[0] for x in new_tickers]]

    print(f"\n  {'─'*55}")
    print(f"  Total universe      : {len(tickers)} tickers")
    print(f"  Already current     : {len(skipped)} (skipped ✓)")
    print(f"  New (full 5yr load) : {len(new_tickers)}")
    print(f"  Stale (delta only)  : {len(delta_tickers)}")
    print(f"  {'─'*55}")

    if not to_fetch:
        print("\n  ✅ All data is current. Nothing to fetch.")
        print("  Run with --force to re-download everything.\n")
        return

    if delta_tickers:
        print("\n  Stale tickers (fetching delta only):")
        for t, s, e in delta_tickers[:10]:
            last = last_dates.get(t)
            gap = (e - s).days
            print(f"    {t:<15} last={last}  fetch {gap} day(s): {s} → {e}")
        if len(delta_tickers) > 10:
            print(f"    ... and {len(delta_tickers)-10} more")

    print(f"\n  Starting fetch for {len(to_fetch)} tickers...\n")

    results, errors = _fetch_and_store(to_fetch, store)

    # Update state
    state = _load_state()
    for t, rows in results.items():
        _mark(state, t, "done", rows=rows, latest=str(today))
    for t in errors:
        _mark(state, t, "failed")

    total_rows = sum(results.values())
    print(f"\n  ✅ {len(results)} tickers | {total_rows:,} rows written | ❌ {len(errors)} errors")
    if errors:
        print(f"  Failed: {errors[:15]}")
        print(f"  Retry:  --mode initial --tickers {' '.join(errors[:5])} --force")


# ── Daily Update (smart delta) ─────────────────────────────────────────────────

def mode_daily(args):
    """
    Same as --mode initial but intended for the daily 6 PM cron job.
    Checks DuckDB for the last stored date per ticker and only downloads
    the missing days — so running it multiple times per day is safe (idempotent).
    """
    universe = _load_universe()
    tickers = universe["ticker"].str.strip().tolist()

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]

    store = _get_store()
    today = date.today()
    yesterday = today - timedelta(days=1)

    last_dates = _get_last_dates()

    to_fetch: list[tuple[str, date, date]] = []
    already_current = 0

    for ticker in tickers:
        last = last_dates.get(ticker)
        if last is None:
            # No history at all — tell user to run --mode initial first
            continue
        elif last >= yesterday:
            already_current += 1
        else:
            fetch_from = last + timedelta(days=1)
            to_fetch.append((ticker, fetch_from, today))

    print(f"\n  Daily sync | {today}")
    print(f"  Already current : {already_current}")
    print(f"  Need update     : {len(to_fetch)}")
    if to_fetch:
        gaps = [(today - s).days for _, s, _ in to_fetch]
        print(f"  Gap range       : {min(gaps)}–{max(gaps)} days")
    print()

    if not to_fetch:
        print("  ✅ All data is current.\n")
        return

    results, errors = _fetch_and_store(to_fetch, store, label="delta")

    total_rows = sum(results.values())
    print(f"\n  ✅ {len(results)} tickers updated | {total_rows:,} rows | ❌ {len(errors)} errors")


# ── Enrich (Fundamentals + Dividends + Splits) ─────────────────────────────────

def mode_enrich(args):
    import pandas as pd
    import yfinance as yf

    universe = _load_universe()
    tickers = universe["ticker"].str.strip().tolist()

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]

    state = _load_state()
    store = _get_store()
    today = date.today()

    # Skip tickers enriched today unless --force
    if not args.force:
        tickers = [t for t in tickers
                   if state.get(f"{t}_enrich", {}).get("updated") != str(today)]
        if not tickers:
            print("  All tickers already enriched today. Use --force to re-enrich.")
            return

    print(f"\n  Enriching {len(tickers)} tickers (fundamentals + dividends + splits)")

    fund_rows, div_rows, split_rows, event_rows = [], [], [], []
    errors = []

    for i, ticker in enumerate(tickers, 1):
        try:
            t = yf.Ticker(f"{ticker}.NS")
            info = t.info or {}
            today_dt = date.today()

            # ── Fundamentals ───────────────────────────────────────────────────
            fund_rows.append({
                "ticker": ticker, "as_of_date": today_dt,
                "market_cap": info.get("marketCap"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "price_to_book": info.get("priceToBook"),
                "enterprise_value": info.get("enterpriseValue"),
                "ev_to_revenue": info.get("enterpriseToRevenue"),
                "ev_to_ebitda": info.get("enterpriseToEbitda"),
                "total_revenue": info.get("totalRevenue"),
                "revenue_growth": info.get("revenueGrowth"),
                "gross_margins": info.get("grossMargins"),
                "operating_margins": info.get("operatingMargins"),
                "profit_margins": info.get("profitMargins"),
                "return_on_equity": info.get("returnOnEquity"),
                "return_on_assets": info.get("returnOnAssets"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "book_value": info.get("bookValue"),
                "dividend_yield": info.get("dividendYield"),
                "payout_ratio": info.get("payoutRatio"),
                "avg_volume": info.get("averageVolume"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "insider_hold_pct": info.get("heldPercentInsiders"),
                "inst_hold_pct": info.get("heldPercentInstitutions"),
                "analyst_target_mean": info.get("targetMeanPrice"),
                "analyst_target_high": info.get("targetHighPrice"),
                "analyst_target_low": info.get("targetLowPrice"),
                "analyst_recommendation": info.get("recommendationKey"),
                "analyst_count": info.get("numberOfAnalystOpinions"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "country": info.get("country"),
            })

            # ── Dividends ──────────────────────────────────────────────────────
            divs = t.dividends
            if divs is not None and not divs.empty:
                for dt, amt in divs.items():
                    div_date = dt.date() if hasattr(dt, "date") else dt
                    div_rows.append({"ticker": ticker, "date": div_date, "amount": float(amt)})

            # ── Splits ─────────────────────────────────────────────────────────
            splits_data = t.splits
            if splits_data is not None and not splits_data.empty:
                for dt, ratio in splits_data.items():
                    sp_date = dt.date() if hasattr(dt, "date") else dt
                    split_rows.append({"ticker": ticker, "date": sp_date, "ratio": float(ratio)})

            # ── Upcoming events ────────────────────────────────────────────────
            cal = t.calendar or {}
            if cal:
                earnings_dates = cal.get("Earnings Date", [])
                ed = earnings_dates[0] if earnings_dates else None
                event_rows.append({
                    "ticker": ticker, "event_type": "earnings",
                    "event_date": ed if isinstance(ed, date) else (ed.date() if ed else None),
                    "earnings_high": cal.get("Earnings High"),
                    "earnings_low": cal.get("Earnings Low"),
                    "earnings_avg": cal.get("Earnings Average"),
                    "revenue_high": cal.get("Revenue High"),
                    "revenue_low": cal.get("Revenue Low"),
                    "revenue_avg": cal.get("Revenue Average"),
                    "updated_at": datetime.now(),
                })
                ex_div = cal.get("Ex-Dividend Date")
                if ex_div:
                    event_rows.append({
                        "ticker": ticker, "event_type": "dividend",
                        "event_date": ex_div if isinstance(ex_div, date) else ex_div.date(),
                        "earnings_high": None, "earnings_low": None, "earnings_avg": None,
                        "revenue_high": None, "revenue_low": None, "revenue_avg": None,
                        "updated_at": datetime.now(),
                    })

            _mark(state, f"{ticker}_enrich", "done")
            print(f"  [{i:3d}/{len(tickers)}] {ticker:<15} ✓  {_bar(i, len(tickers))}")

        except Exception as exc:
            errors.append(ticker)
            print(f"  [{i:3d}/{len(tickers)}] {ticker:<15} ERROR: {str(exc)[:50]}")

        # Flush to DB every 50 tickers
        if i % 50 == 0:
            _flush_enrich(store, fund_rows, div_rows, split_rows, event_rows)
            fund_rows, div_rows, split_rows, event_rows = [], [], [], []

        time.sleep(TICKER_DELAY)

    # Final flush
    _flush_enrich(store, fund_rows, div_rows, split_rows, event_rows)
    print(f"\n  ✅ Enriched {len(tickers) - len(errors)} tickers | ❌ {len(errors)} errors")


def mode_enrich_quarterly(args):
    """
    Fetch quarterly financial metrics from yfinance for all universe tickers.
    Stores in DuckDB table 'stock_metrics' with:
      cmp, pe_ratio, mktcap_cr, div_yld_pct,
      np_qtr_cr, qtr_pft_var, sales_qtr_cr, qtr_sal_var, roce_pct
    """
    import pandas as pd
    import duckdb
    import yfinance as yf

    universe = _load_universe()

    tickers = universe["ticker"].str.strip().tolist()
    if args.tickers:
        tickers = [t.upper() for t in args.tickers]

    state = _load_state()
    today = date.today()

    if not args.force:
        tickers = [t for t in tickers
                   if state.get(f"{t}_qtr", {}).get("updated") != str(today)]
        if not tickers:
            print("  All tickers already enriched today. Use --force to re-enrich.")
            return

    # Ensure stock_metrics table exists
    conn = duckdb.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_metrics (
            ticker        VARCHAR PRIMARY KEY,
            as_of_date    DATE,
            cmp           DOUBLE,
            pe_ratio      DOUBLE,
            mktcap_cr     DOUBLE,
            div_yld_pct   DOUBLE,
            np_qtr_cr     DOUBLE,
            qtr_pft_var   DOUBLE,
            sales_qtr_cr  DOUBLE,
            qtr_sal_var   DOUBLE,
            roce_pct      DOUBLE
        )
    """)
    conn.close()

    print(f"\n  Enriching {len(tickers)} tickers with quarterly metrics (yfinance)...")
    print("  Fields: CMP, P/E, Mkt Cap, Div Yld, NP Qtr, Sales Qtr, ROCE")

    rows = []
    errors = []

    def _safe(val):
        """Return float or None — never NaN."""
        try:
            f = float(val)
            return None if (f != f) else f  # NaN check
        except Exception:
            return None

    def _qtr_val(stmt, row_label, col_idx=0):
        try:
            return _safe(stmt.loc[row_label].iloc[col_idx])
        except Exception:
            return None

    def _qtr_var(stmt, row_label):
        try:
            curr = float(stmt.loc[row_label].iloc[0])
            prev = float(stmt.loc[row_label].iloc[1])
            if prev == 0 or (curr != curr) or (prev != prev):
                return None
            return _safe((curr / prev - 1) * 100)
        except Exception:
            return None

    for i, ticker in enumerate(tickers, 1):
        try:
            t = yf.Ticker(f"{ticker}.NS")
            info = t.info or {}

            cmp        = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))
            pe         = _safe(info.get("trailingPE"))
            mktcap_cr  = _safe((info.get("marketCap") or 0) / 1e7) or None
            div_yld    = _safe((info.get("dividendYield") or 0) * 100) or None

            # Quarterly income statement
            q_inc = None
            try:
                q_inc = t.quarterly_income_stmt
            except Exception:
                pass

            np_qtr = qtr_pft_var = sales_qtr = qtr_sal_var = None
            if q_inc is not None and not q_inc.empty:
                np_qtr      = _qtr_val(q_inc, "Net Income")
                if np_qtr:
                    np_qtr  = _safe(np_qtr / 1e7)
                qtr_pft_var = _qtr_var(q_inc, "Net Income")
                sales_qtr   = _qtr_val(q_inc, "Total Revenue")
                if sales_qtr:
                    sales_qtr = _safe(sales_qtr / 1e7)
                qtr_sal_var = _qtr_var(q_inc, "Total Revenue")

            # ROCE from income + balance sheet
            roce = None
            try:
                q_bs   = t.quarterly_balance_sheet
                ebit   = _qtr_val(q_inc, "EBIT") if q_inc is not None else None
                if ebit is None and q_inc is not None:
                    ebit = _qtr_val(q_inc, "Operating Income")
                ta     = _qtr_val(q_bs, "Total Assets")
                cl     = _qtr_val(q_bs, "Current Liabilities")
                if ebit and ta and cl and (ta - cl) != 0:
                    roce = _safe(ebit / (ta - cl) * 100)
            except Exception:
                pass

            rows.append({
                "ticker": ticker, "as_of_date": today,
                "cmp": cmp, "pe_ratio": pe, "mktcap_cr": mktcap_cr,
                "div_yld_pct": div_yld, "np_qtr_cr": np_qtr,
                "qtr_pft_var": qtr_pft_var, "sales_qtr_cr": sales_qtr,
                "qtr_sal_var": qtr_sal_var, "roce_pct": roce,
            })

            _mark(state, f"{ticker}_qtr", "done")
            print(f"  [{i:4d}/{len(tickers)}] {ticker:<15} ✓  CMP={cmp}  PE={pe}  ROCE={roce:.1f}%" if roce else
                  f"  [{i:4d}/{len(tickers)}] {ticker:<15} ✓  CMP={cmp}  PE={pe}")

        except Exception as exc:
            errors.append(ticker)
            print(f"  [{i:4d}/{len(tickers)}] {ticker:<15} ERROR: {str(exc)[:60]}")

        # Flush to DB every 50 tickers
        if len(rows) >= 50:
            _flush_quarterly(rows)
            rows = []

        if i % BATCH_SIZE == 0:
            time.sleep(BATCH_DELAY)
        else:
            time.sleep(TICKER_DELAY)

    if rows:
        _flush_quarterly(rows)

    print(f"\n  ✅ Enriched {len(tickers) - len(errors)} tickers | ❌ {len(errors)} errors")


def _flush_quarterly(rows: list[dict]):
    """Upsert quarterly metric rows into DuckDB stock_metrics table."""
    import duckdb
    if not rows:
        return
    conn = duckdb.connect(str(DB_PATH))
    tickers = [r["ticker"] for r in rows]
    placeholders = ",".join(["?" for _ in tickers])
    conn.execute(f"DELETE FROM stock_metrics WHERE ticker IN ({placeholders})", tickers)
    conn.executemany(
        """INSERT INTO stock_metrics
           (ticker, as_of_date, cmp, pe_ratio, mktcap_cr, div_yld_pct,
            np_qtr_cr, qtr_pft_var, sales_qtr_cr, qtr_sal_var, roce_pct)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (r["ticker"], r["as_of_date"], r.get("cmp"), r.get("pe_ratio"),
             r.get("mktcap_cr"), r.get("div_yld_pct"), r.get("np_qtr_cr"),
             r.get("qtr_pft_var"), r.get("sales_qtr_cr"), r.get("qtr_sal_var"),
             r.get("roce_pct"))
            for r in rows
        ]
    )
    conn.close()


def _flush_enrich(store, fund_rows, div_rows, split_rows, event_rows):
    import pandas as pd
    if fund_rows:
        store.upsert_fundamentals(pd.DataFrame(fund_rows))
    if div_rows:
        store.upsert_dividends(pd.DataFrame(div_rows))
    if split_rows:
        store.upsert_splits(pd.DataFrame(split_rows))
    if event_rows:
        store.upsert_corporate_events(pd.DataFrame(event_rows))


# ── Filter ─────────────────────────────────────────────────────────────────────

# Default filter conditions — edit these to customise your watchlist
DEFAULT_FILTERS = {
    "min_market_cap_cr":   500,    # Market cap > ₹500 Cr
    "min_avg_volume_cr":   1,      # Avg daily volume > ₹1 Cr
    "max_debt_to_equity":  5.0,    # Exclude extremely leveraged firms
    "min_roe":             0.0,    # Positive return on equity
    "max_pe":              150.0,  # Exclude loss-making / extreme PE
    "min_pe":              0.0,    # PE must be positive (profitable)
    "min_revenue_growth": -0.30,   # Revenue not collapsing
    "price_above_sma50":   False,  # Optional momentum filter
}

def mode_filter(args):
    import pandas as pd
    import duckdb

    conn = duckdb.connect(str(DB_PATH))

    print("\n  Loading data from DuckDB...")

    # Latest OHLCV close price + 50-day MA
    ohlcv_sql = """
        WITH ranked AS (
            SELECT ticker, date, close, volume,
                   AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS 49 PRECEDING) AS sma50,
                   AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS 199 PRECEDING) AS sma200,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM ohlcv
        )
        SELECT ticker, date, close, volume, sma50, sma200 FROM ranked WHERE rn = 1
    """
    prices = conn.execute(ohlcv_sql).df()

    # Latest fundamentals
    fund_sql = """
        SELECT * FROM fundamentals
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY as_of_date DESC) = 1
    """
    try:
        funds = conn.execute(fund_sql).df()
    except Exception:
        funds = pd.DataFrame()
        print("  [WARN] No fundamentals data. Run --mode enrich first.")

    conn.close()

    # Load universe for metadata
    universe = _load_universe()

    # Merge
    df = prices.merge(universe[["ticker", "company_name", "sector"]], on="ticker", how="left")
    if not funds.empty:
        df = df.merge(funds.drop(columns=["as_of_date", "sector", "industry", "country"], errors="ignore"),
                      on="ticker", how="left")

    print(f"  Total stocks before filtering: {len(df)}")

    f = DEFAULT_FILTERS
    filtered = df.copy()

    # Market cap filter
    if "market_cap" in filtered.columns:
        min_mc = f["min_market_cap_cr"] * 1e7  # Cr → ₹
        filtered = filtered[filtered["market_cap"].isna() | (filtered["market_cap"] >= min_mc)]
        print(f"  After market_cap > ₹{f['min_market_cap_cr']}Cr: {len(filtered)}")

    # Volume filter (avg daily value ₹ = close × volume)
    filtered["daily_value_cr"] = (filtered["close"] * filtered["volume"]) / 1e7
    min_val = f["min_avg_volume_cr"]
    filtered = filtered[filtered["daily_value_cr"] >= min_val]
    print(f"  After daily_value > ₹{min_val}Cr: {len(filtered)}")

    # Debt/equity filter
    if "debt_to_equity" in filtered.columns:
        max_de = f["max_debt_to_equity"]
        filtered = filtered[filtered["debt_to_equity"].isna() | (filtered["debt_to_equity"] <= max_de)]
        print(f"  After debt_to_equity < {max_de}: {len(filtered)}")

    # ROE filter
    if "return_on_equity" in filtered.columns:
        min_roe = f["min_roe"]
        filtered = filtered[filtered["return_on_equity"].isna() | (filtered["return_on_equity"] >= min_roe)]
        print(f"  After ROE >= {min_roe}: {len(filtered)}")

    # PE filter
    if "trailing_pe" in filtered.columns:
        filtered = filtered[
            filtered["trailing_pe"].isna() |
            ((filtered["trailing_pe"] >= f["min_pe"]) & (filtered["trailing_pe"] <= f["max_pe"]))
        ]
        print(f"  After PE in [{f['min_pe']}, {f['max_pe']}]: {len(filtered)}")

    # Revenue growth filter
    if "revenue_growth" in filtered.columns:
        min_rg = f["min_revenue_growth"]
        filtered = filtered[filtered["revenue_growth"].isna() | (filtered["revenue_growth"] >= min_rg)]
        print(f"  After revenue_growth >= {min_rg}: {len(filtered)}")

    # Optional: price above SMA50 (momentum)
    if f["price_above_sma50"] and "sma50" in filtered.columns:
        filtered = filtered[filtered["close"] >= filtered["sma50"]]
        print(f"  After price > SMA50: {len(filtered)}")

    # Sort by market cap descending
    if "market_cap" in filtered.columns:
        filtered = filtered.sort_values("market_cap", ascending=False)

    # Display
    cols = ["ticker", "company_name", "sector", "close", "market_cap",
            "trailing_pe", "return_on_equity", "debt_to_equity",
            "revenue_growth", "daily_value_cr"]
    display_cols = [c for c in cols if c in filtered.columns]
    print(f"\n  === FILTERED UNIVERSE: {len(filtered)} stocks ===\n")
    pd.set_option("display.max_rows", 50)
    pd.set_option("display.width", 120)
    pd.set_option("display.float_format", "{:.2f}".format)
    print(filtered[display_cols].head(50).to_string(index=False))

    # Export
    out_path = ROOT / "data" / "today_filtered_stocks.csv"
    filtered[display_cols].to_csv(out_path, index=False)
    print(f"\n  Saved to {out_path.name}")

    # Sector breakdown
    if "sector" in filtered.columns:
        print("\n  Sector breakdown:")
        print(filtered["sector"].value_counts().head(15).to_string())


# ── Status ─────────────────────────────────────────────────────────────────────

def mode_status():
    import duckdb

    state = _load_state()
    ohlcv_keys = {k: v for k, v in state.items() if "_enrich" not in k}
    enrich_keys = {k: v for k, v in state.items() if "_enrich" in k}

    done   = sum(1 for v in ohlcv_keys.values() if v.get("status") == "done")
    failed = sum(1 for v in ohlcv_keys.values() if v.get("status") == "failed")
    pending = sum(1 for v in ohlcv_keys.values() if v.get("status") == "pending")
    enriched = sum(1 for v in enrich_keys.values() if v.get("status") == "done")

    # Detect which universe CSV exists and report it
    import os
    universe_path = None
    for csv_path in [UNIVERSE_1500_CSV, UNIVERSE_1000_CSV, UNIVERSE_CSV]:
        if csv_path.exists():
            universe_path = csv_path
            break
    try:
        import pandas as pd
        universe = pd.read_csv(universe_path) if universe_path else None
    except Exception:
        universe = None
    total = len(universe) if universe is not None else "?"

    print("\n" + "=" * 60)
    print("  NSE PIPELINE STATUS")
    print("=" * 60)
    print(f"  Universe          : {total} tickers  ({universe_path.name if universe_path else 'none'})")
    print(f"  OHLCV downloaded  : {done} ✅  |  {failed} ❌  |  {pending} ⏳")
    print(f"  Enriched          : {enriched} fundamentals")

    if universe_path and universe_path.exists():
        sz = os.path.getsize(universe_path) / 1024
        print(f"  Universe CSV      : {sz:.1f} KB")

    if DB_PATH.exists():
        import os
        sz = os.path.getsize(DB_PATH) / (1024 * 1024)
        print(f"  DuckDB size       : {sz:.1f} MB")

    # DB stats
    try:
        conn = duckdb.connect(str(DB_PATH))
        tables = ["ohlcv", "fundamentals", "dividends", "splits", "corporate_events"]
        print(f"\n  {'Table':<22} {'Rows':>10}  {'Tickers':>10}")
        print(f"  {'-'*44}")
        for t in tables:
            try:
                row_count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                try:
                    ticker_count = conn.execute(f"SELECT COUNT(DISTINCT ticker) FROM {t}").fetchone()[0]
                except Exception:
                    ticker_count = "-"
                print(f"  {t:<22} {row_count:>10,}  {str(ticker_count):>10}")
            except Exception:
                print(f"  {t:<22} {'N/A':>10}")

        dr = conn.execute("SELECT MIN(date), MAX(date) FROM ohlcv").fetchone()
        print(f"\n  OHLCV date range  : {dr[0]} → {dr[1]}")
        conn.close()
    except Exception as exc:
        print(f"  [WARN] Could not read DB stats: {exc}")

    if failed:
        failed_tickers = [k for k, v in ohlcv_keys.items() if v.get("status") == "failed"]
        print(f"\n  Failed tickers ({len(failed_tickers)}): {failed_tickers[:15]}")
        print(f"  Retry: python scripts/nifty500_pipeline.py --mode initial --tickers {' '.join(failed_tickers[:5])} --force")

    print("=" * 60 + "\n")


# ── Reset ──────────────────────────────────────────────────────────────────────

def mode_reset(args):
    state = _load_state()
    if args.tickers:
        for t in args.tickers:
            state.pop(t.upper(), None)
            state.pop(f"{t.upper()}_enrich", None)
        print(f"  Reset state for: {args.tickers}")
    else:
        # Only reset failed/pending
        reset_keys = [k for k, v in state.items() if v.get("status") in ("failed", "pending")]
        for k in reset_keys:
            del state[k]
        print(f"  Reset {len(reset_keys)} failed/pending tickers")
    _save_state(state)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Nifty 500 Data Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", required=True,
        choices=["initial", "daily", "enrich", "enrich-quarterly", "filter", "status",
                 "universe", "universe1000", "universe1500", "reset"],
        help="Pipeline mode")
    parser.add_argument("--tickers", nargs="+", help="Specific tickers to process")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint (default: on)")
    parser.add_argument("--force", action="store_true", help="Re-process even if already done")
    parser.add_argument("--years", type=int, default=5, help="Years of history for initial load")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Nifty 500 Pipeline  |  mode={args.mode}  |  {date.today()}")
    print(f"{'='*60}")

    if args.mode == "universe":          mode_universe()
    elif args.mode == "universe1000":   mode_universe_1000()
    elif args.mode == "universe1500":   mode_universe_1500()
    elif args.mode == "initial":        mode_initial(args)
    elif args.mode == "daily":          mode_daily(args)
    elif args.mode == "enrich":         mode_enrich(args)
    elif args.mode == "enrich-quarterly": mode_enrich_quarterly(args)
    elif args.mode == "filter":         mode_filter(args)
    elif args.mode == "status":         mode_status()
    elif args.mode == "reset":          mode_reset(args)
    else:
        print(f"  [ERROR] Unknown mode: {args.mode}")
        print("  Available modes: universe, universe1000, initial, daily, enrich,")
        print("                   enrich-quarterly, filter, status, reset")


if __name__ == "__main__":
    main()
