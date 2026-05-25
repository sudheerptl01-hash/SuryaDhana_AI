#!/usr/bin/env python
"""
ICICI Breeze — Bulk Historical OHLCV Ingestion
===============================================
Standalone script: no FastAPI server needed.
Reads credentials from .env, fetches via Breeze v2, stores in DuckDB.

Usage:
    # Fetch all 100 stocks (5 years default)
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/fetch_all_icici.py

    # Fetch specific tickers
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/fetch_all_icici.py --tickers RELIANCE TCS HDFCBANK

    # Custom date range
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/fetch_all_icici.py --start 2022-01-01 --end 2024-12-31

    # Dry run (no DB writes)
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/fetch_all_icici.py --dry-run --tickers RELIANCE

    # Resume (skip tickers already in DB)
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/fetch_all_icici.py --resume
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

# ── Env loader ─────────────────────────────────────────────────────────────────

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


# ── Progress display ───────────────────────────────────────────────────────────

def _bar(done: int, total: int, width: int = 30) -> str:
    filled = int(width * done / total) if total else 0
    return f"[{'█' * filled}{'░' * (width - filled)}] {done}/{total}"


def _print_summary(results: dict[str, int], errors: dict[str, str], elapsed: float) -> None:
    print("\n" + "=" * 60)
    print(f"  INGESTION COMPLETE  ({elapsed:.1f}s)")
    print("=" * 60)
    ok = len(results)
    failed = len(errors)
    total_rows = sum(results.values())
    print(f"  Succeeded : {ok} tickers  ({total_rows:,} rows total)")
    print(f"  Failed    : {failed} tickers")
    if results:
        top = sorted(results.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"  Top tickers by rows: {', '.join(f'{t}={r}' for t, r in top)}")
    if errors:
        print(f"\n  Errors:")
        for ticker, err in list(errors.items())[:10]:
            print(f"    {ticker}: {err}")
    print("=" * 60 + "\n")


# ── Main ingestion ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV from ICICI Breeze v2")
    parser.add_argument("--tickers", nargs="+", help="Specific tickers (default: all from FINAL_100_STOCKS.csv)")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD (default: 5 years ago)")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--years", type=int, default=5, help="Years of history if --start not set (default: 5)")
    parser.add_argument("--exchange", default="NSE", choices=["NSE", "BSE"], help="Exchange (default: NSE)")
    parser.add_argument("--delay", type=float, default=0.4, help="Seconds between API calls (default: 0.4)")
    parser.add_argument("--resume", action="store_true", help="Skip tickers already present in DuckDB")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write to DuckDB")
    args = parser.parse_args()

    env = _read_env()
    api_key = env.get("ICICI_API_KEY", "")
    api_secret = env.get("ICICI_API_SECRET", "")
    session_token = env.get("ICICI_SESSION_TOKEN", "")
    db_path = env.get("DUCKDB_PATH", "data/market.duckdb")
    stock_universe = env.get("STOCK_UNIVERSE_PATH", "data/FINAL_100_STOCKS.csv")

    if not api_key or not api_secret or not session_token:
        print("[ERROR] ICICI credentials missing in .env (ICICI_API_KEY / ICICI_API_SECRET / ICICI_SESSION_TOKEN)")
        sys.exit(1)

    # ── Date range ─────────────────────────────────────────────────────────────
    end_date = date.fromisoformat(args.end) if args.end else date.today()
    start_date = (
        date.fromisoformat(args.start)
        if args.start
        else end_date - timedelta(days=args.years * 365 + 10)
    )

    # ── Ticker list ────────────────────────────────────────────────────────────
    import pandas as pd
    csv_path = ROOT / stock_universe
    if not csv_path.exists():
        print(f"[ERROR] Stock universe not found: {csv_path}")
        sys.exit(1)
    df_stocks = pd.read_csv(csv_path)

    if args.tickers:
        requested = {t.upper() for t in args.tickers}
        df_stocks = df_stocks[df_stocks["ticker"].str.upper().isin(requested)]
        if df_stocks.empty:
            print(f"[ERROR] None of the requested tickers found in {csv_path}")
            sys.exit(1)

    # Build ticker → isec_code map (pre-resolved; avoids per-ticker get_names() calls)
    if "isec_code" in df_stocks.columns:
        ticker_map: dict[str, str] = dict(zip(df_stocks["ticker"], df_stocks["isec_code"]))
    else:
        ticker_map = {t: t for t in df_stocks["ticker"]}

    tickers = df_stocks["ticker"].str.strip().tolist()

    print("\n" + "=" * 60)
    print("  ICICI Breeze v2 — Bulk OHLCV Ingestion")
    print("=" * 60)
    print(f"  Exchange  : {args.exchange}")
    print(f"  Tickers   : {len(tickers)}")
    print(f"  Range     : {start_date} → {end_date}")
    print(f"  DuckDB    : {db_path}")
    print(f"  Dry run   : {args.dry_run}")
    print(f"  Resume    : {args.resume}")
    print("=" * 60)

    # ── Connect to ICICI ───────────────────────────────────────────────────────
    from providers.icici_breeze_provider import ICICIBreezeProvider
    provider = ICICIBreezeProvider(api_key, api_secret, session_token)
    provider.connect()
    print(f"\n  [OK] ICICI Breeze connected\n")

    # ── Connect to DuckDB ──────────────────────────────────────────────────────
    if not args.dry_run:
        from storage.duckdb_store import DuckDBStore
        store = DuckDBStore(str(ROOT / db_path))
    else:
        store = None

    # ── Resume: find already-ingested tickers ──────────────────────────────────
    skip_tickers: set[str] = set()
    if args.resume and store:
        import duckdb
        conn = duckdb.connect(str(ROOT / db_path))
        try:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM ohlcv WHERE source = 'icici_breeze_v2'"
            ).fetchall()
            skip_tickers = {r[0] for r in rows}
        except Exception:
            pass
        finally:
            conn.close()
        if skip_tickers:
            print(f"  [RESUME] Skipping {len(skip_tickers)} tickers already in DB\n")
        tickers = [t for t in tickers if t not in skip_tickers]

    if not tickers:
        print("  [DONE] No tickers left to fetch.")
        sys.exit(0)

    # ── Fetch loop ─────────────────────────────────────────────────────────────
    import pandas as pd
    results: dict[str, int] = {}
    errors: dict[str, str] = {}
    start_ts = time.time()

    for i, ticker in enumerate(tickers, 1):
        isec_code = ticker_map.get(ticker, ticker)
        prefix = f"  [{i:3d}/{len(tickers)}] {ticker:<15} ({isec_code:<8})"
        try:
            # Pre-seed the provider's code cache so it skips get_names() API call
            provider._code_cache[ticker] = isec_code

            batch = provider.get_daily_ohlcv_v2(
                ticker=ticker,
                start=start_date,
                end=end_date,
                exchange_code=args.exchange,
            )

            if not batch.records:
                print(f"{prefix} — no data returned")
                errors[ticker] = "no data returned"
            else:
                rows_count = len(batch.records)

                if not args.dry_run and store:
                    df = pd.DataFrame([r.model_dump() for r in batch.records])
                    df["source"] = "icici_breeze_v2"
                    store.upsert_ohlcv(df, source="icici_breeze_v2")

                results[ticker] = rows_count
                pct_done = i / len(tickers) * 100
                print(f"{prefix} {rows_count:>5} rows  {_bar(i, len(tickers))}  {pct_done:.0f}%")

        except Exception as exc:
            short_err = str(exc)[:80]
            print(f"{prefix} ERROR: {short_err}")
            errors[ticker] = str(exc)

        # Rate limit
        if i < len(tickers):
            time.sleep(args.delay)

    _print_summary(results, errors, elapsed=time.time() - start_ts)

    if args.dry_run:
        print("  [DRY RUN] No data was written to DuckDB.\n")


if __name__ == "__main__":
    main()
