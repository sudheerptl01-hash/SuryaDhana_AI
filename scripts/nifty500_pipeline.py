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

STATE_FILE  = ROOT / "data" / ".pipeline_state.json"
UNIVERSE_CSV = ROOT / "data" / "nifty500_universe.csv"
DB_PATH     = ROOT / "data" / "market.duckdb"

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
    import pandas as pd
    if not UNIVERSE_CSV.exists():
        print("[ERROR] nifty500_universe.csv not found. Run --mode universe first.")
        sys.exit(1)
    return pd.read_csv(UNIVERSE_CSV)


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

def mode_universe():
    import requests, pandas as pd
    print("\n  Fetching Nifty 500 constituents from niftyindices.com...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.niftyindices.com/",
    }
    url = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df = df[df["Series"] == "EQ"][["Symbol", "Company Name", "Industry", "ISIN Code"]].copy()
        df.columns = ["ticker", "company_name", "sector", "isin"]
        df["ticker"] = df["ticker"].str.strip()
        df = df.drop_duplicates("ticker").reset_index(drop=True)
        df.to_csv(UNIVERSE_CSV, index=False)
        print(f"  [OK] Saved {len(df)} tickers to {UNIVERSE_CSV.name}")
        print(f"  Sectors: {df['sector'].value_counts().head(5).to_dict()}")
    except Exception as exc:
        print(f"  [ERROR] Failed to fetch universe: {exc}")
        sys.exit(1)


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

    universe = _load_universe() if UNIVERSE_CSV.exists() else None
    total = len(universe) if universe is not None else "?"

    print("\n" + "=" * 60)
    print("  NIFTY 500 PIPELINE STATUS")
    print("=" * 60)
    print(f"  Universe          : {total} tickers")
    print(f"  OHLCV downloaded  : {done} ✅  |  {failed} ❌  |  {pending} ⏳")
    print(f"  Enriched          : {enriched} fundamentals")

    if UNIVERSE_CSV.exists():
        import os
        sz = os.path.getsize(UNIVERSE_CSV) / 1024
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
        choices=["initial", "daily", "enrich", "filter", "status", "universe", "reset"],
        help="Pipeline mode")
    parser.add_argument("--tickers", nargs="+", help="Specific tickers to process")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint (default: on)")
    parser.add_argument("--force", action="store_true", help="Re-process even if already done")
    parser.add_argument("--years", type=int, default=5, help="Years of history for initial load")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Nifty 500 Pipeline  |  mode={args.mode}  |  {date.today()}")
    print(f"{'='*60}")

    if args.mode == "universe":   mode_universe()
    elif args.mode == "initial":  mode_initial(args)
    elif args.mode == "daily":    mode_daily(args)
    elif args.mode == "enrich":   mode_enrich(args)
    elif args.mode == "filter":   mode_filter(args)
    elif args.mode == "status":   mode_status()
    elif args.mode == "reset":    mode_reset(args)


if __name__ == "__main__":
    main()
