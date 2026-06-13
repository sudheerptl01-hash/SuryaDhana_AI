#!/usr/bin/env python3
"""Phase 5 (D1) — corporate-actions backfill: splits + dividends from yfinance.

Closes the *achievable* half of D1 in BILLIONAIRE_SCALE_AUDIT.md: the `splits`
and `dividends` tables ship EMPTY in `data/market.duckdb`, which starves the
G7 split/dividend-adjustment mechanism. yfinance exposes the real, dated
corporate-action history for the surviving NSE universe (`Ticker.splits`,
`Ticker.dividends`), so this is genuinely backfillable from a free source.

WHAT THIS DOES NOT DO (honesty contract, per the audit):
  * It does NOT fabricate `index_membership` history or `delistings` returns —
    those have no honest free source (see `backfill_index_membership.py` for the
    wired-but-empty `delistings` table and the snapshot-only membership load).
  * It does NOT backdate `stock_metrics` into fake PIT fundamentals.

DESIGN NOTES (production discipline):
  * Single-writer safety: opens its OWN read-write DuckDB connection. The
    data-service holds the single-writer lock at runtime; the ui-api shared
    connection is read-only. Run this ONLY when no data-service writer is up
    (the script aborts cleanly if the write lock is held — it never crashes a
    reader). All reads in ui-api stay non-blocking.
  * Idempotent: `CREATE TABLE IF NOT EXISTS` + `INSERT OR REPLACE ... SELECT *`
    keyed on the PRIMARY KEY (ticker, date). Re-running converges to the same
    rows; no duplicates, no drift. Mirrors `duckdb_store.upsert_splits/_dividends`.
  * Look-ahead-safe: a split/dividend dated T is an *announced ex-date*. yfinance
    only returns it on/after T, and the backtest's as-of joins gate on `date`, so
    no future event leaks into a bar before its ex-date. We additionally clip any
    row dated AFTER `--max-date` (default: today) so a re-run on stale clocks can
    never inject a forward-dated phantom action.
  * Vectorised: per-ticker Series → DataFrame, concatenated and bulk-upserted.
    No DataFrame row loops. The only Python loop is the unavoidable per-ticker
    network fetch (yfinance is per-symbol for `.actions`).
  * Defensive: every network/parse failure is contained per-ticker; one bad
    symbol never aborts the run. Failures are tallied and reported, never raised
    into the writer transaction.

USAGE:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/backfill_corporate_actions.py \
        --db data/market.duckdb --universe data/NSE_1500.csv

    # dry-run (fetch + summarise, write nothing):
    ... --dry-run

    # limit for a smoke test:
    ... --limit 25
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

# pandas >= 3.0 infers a `str` (StringDtype) for object string columns, which
# duckdb 1.1.1 cannot scan via register()/local-df ("Data type 'str' not
# recognized"). Opt back into the legacy `object` dtype so the bulk upsert path
# (INSERT OR REPLACE ... SELECT * FROM df) works on this env's duckdb/pandas combo.
# Mirrors the object-cast intent in duckdb_store.upsert_*; no behavioural change.
try:
    pd.set_option("future.infer_string", False)
except Exception:  # pragma: no cover - older pandas without the option
    pass

try:
    import duckdb
except ImportError:  # pragma: no cover - environment guard
    print("FATAL: duckdb not importable in this environment", file=sys.stderr)
    raise

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    print("FATAL: yfinance not importable in this environment", file=sys.stderr)
    raise

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ImportError:  # pragma: no cover - degrade to no-retry if absent
    def retry(*_a, **_k):  # type: ignore
        def _wrap(fn):
            return fn
        return _wrap

    def stop_after_attempt(*_a, **_k):  # type: ignore
        return None

    def wait_exponential(*_a, **_k):  # type: ignore
        return None


NSE_SUFFIX = ".NS"

# Table DDL kept byte-compatible with services/data-service/storage/duckdb_store.py.
# Re-declared here so the script is runnable standalone (no service import / no
# event-loop / no FastAPI app boot needed for a data-eng backfill).
DDL_SPLITS = """
CREATE TABLE IF NOT EXISTS splits (
    ticker  VARCHAR NOT NULL,
    date    DATE    NOT NULL,
    ratio   DOUBLE  NOT NULL,
    PRIMARY KEY (ticker, date)
);
"""

DDL_DIVIDENDS = """
CREATE TABLE IF NOT EXISTS dividends (
    ticker  VARCHAR NOT NULL,
    date    DATE    NOT NULL,
    amount  DOUBLE  NOT NULL,
    PRIMARY KEY (ticker, date)
);
"""


def _to_nse_ticker(ticker: str) -> str:
    """Ensure the .NS suffix yfinance needs for NSE symbols.

    Mirrors services/data-service/providers/yfinance_provider._to_nse_ticker so
    the backfill maps the bare DuckDB symbols (e.g. RELIANCE) to yfinance
    symbols (RELIANCE.NS) identically to the OHLCV ingestion path.
    """
    t = ticker.strip().upper()
    return t if t.endswith(NSE_SUFFIX) else f"{t}{NSE_SUFFIX}"


def _from_nse_ticker(yf_ticker: str) -> str:
    """Strip the .NS / .BO suffix back to the bare DuckDB symbol."""
    return yf_ticker.upper().replace(".NS", "").replace(".BO", "")


@dataclass
class BackfillStats:
    universe: int = 0
    fetched_ok: int = 0
    fetch_failed: int = 0
    split_rows: int = 0
    dividend_rows: int = 0
    splits_before: int = 0
    splits_after: int = 0
    dividends_before: int = 0
    dividends_after: int = 0
    failed_tickers: list[str] = field(default_factory=list)
    max_date_seen_split: Optional[str] = None
    max_date_seen_div: Optional[str] = None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
def _fetch_actions(yf_ticker: str) -> tuple[pd.Series, pd.Series]:
    """Fetch (splits, dividends) Series for one yfinance ticker, with retry.

    Returns two pandas Series indexed by ex-date. Empty Series on no-action.
    Raised exceptions are retried up to 3x with exponential backoff; the caller
    catches the terminal failure so one dead symbol never aborts the run.
    """
    tk = yf.Ticker(yf_ticker)
    splits = tk.splits
    dividends = tk.dividends
    if splits is None:
        splits = pd.Series(dtype="float64")
    if dividends is None:
        dividends = pd.Series(dtype="float64")
    return splits, dividends


def _series_to_frame(
    series: pd.Series,
    bare_ticker: str,
    value_col: str,
    max_date: pd.Timestamp,
) -> pd.DataFrame:
    """Vectorised Series[ex_date]->value into a (ticker, date, <value_col>) frame.

    LOOK-AHEAD GUARD: drops any row dated strictly after `max_date`. A corporate
    action is only knowable at/after its ex-date; clipping future-dated rows means
    a re-run under a skewed clock can never inject a phantom forward action.
    Also drops NaN / non-positive values (a 0 ratio or NaN amount is degenerate).
    """
    if series is None or len(series) == 0:
        return pd.DataFrame(columns=["ticker", "date", value_col])

    s = series.copy()
    # yfinance indexes by tz-aware Timestamp; normalise to naive date-floored.
    idx = pd.to_datetime(s.index, errors="coerce")
    try:
        idx = idx.tz_localize(None)
    except (TypeError, AttributeError):
        pass  # already tz-naive
    s.index = idx

    df = pd.DataFrame({"date": s.index, value_col: s.to_numpy(dtype="float64")})
    df["ticker"] = bare_ticker
    # Vectorised cleaning: drop NaT dates, NaN/<=0 values, and future-dated rows.
    df = df.dropna(subset=["date", value_col])
    df = df[df[value_col] > 0.0]
    df = df[df["date"] <= max_date]
    df["date"] = df["date"].dt.normalize()
    # Collapse intra-day dupes (defensive): keep last value per (ticker, date).
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    return df[["ticker", "date", value_col]].reset_index(drop=True)


def load_universe(universe_csv: Path) -> list[str]:
    """Read bare NSE tickers from the universe CSV (column `ticker`)."""
    df = pd.read_csv(universe_csv)
    if "ticker" not in df.columns:
        raise ValueError(f"{universe_csv} has no 'ticker' column; got {list(df.columns)}")
    return (
        df["ticker"].dropna().astype(str).str.strip().str.upper().drop_duplicates().tolist()
    )


def backfill(
    db_path: str,
    universe_csv: str,
    limit: Optional[int] = None,
    dry_run: bool = False,
    max_date: Optional[date] = None,
    sleep_s: float = 0.0,
    only_in_ohlcv: bool = True,
) -> BackfillStats:
    """Backfill splits + dividends. Returns BackfillStats with before/after counts."""
    stats = BackfillStats()
    max_ts = pd.Timestamp(max_date or date.today()).normalize()

    universe = load_universe(Path(universe_csv))

    # Restrict to names that actually have OHLCV (so a split has price context to
    # adjust). Uses a short-lived read-only probe; never holds the write lock.
    if only_in_ohlcv:
        ro = duckdb.connect(db_path, read_only=True)
        try:
            ohlcv_tk = {
                r[0].upper() for r in ro.execute("SELECT DISTINCT ticker FROM ohlcv").fetchall()
            }
        finally:
            ro.close()
        universe = [t for t in universe if t.upper() in ohlcv_tk]

    if limit is not None:
        universe = universe[:limit]
    stats.universe = len(universe)

    split_frames: list[pd.DataFrame] = []
    div_frames: list[pd.DataFrame] = []

    for i, bare in enumerate(universe, 1):
        yf_t = _to_nse_ticker(bare)
        try:
            splits, dividends = _fetch_actions(yf_t)
            sdf = _series_to_frame(splits, bare, "ratio", max_ts)
            ddf = _series_to_frame(dividends, bare, "amount", max_ts)
            if len(sdf):
                split_frames.append(sdf)
            if len(ddf):
                div_frames.append(ddf)
            stats.fetched_ok += 1
        except Exception as exc:  # noqa: BLE001 - per-ticker containment by design
            stats.fetch_failed += 1
            stats.failed_tickers.append(bare)
            print(f"  [warn] {bare} ({yf_t}) fetch failed: {type(exc).__name__}: {str(exc)[:120]}")
        if sleep_s:
            time.sleep(sleep_s)
        if i % 100 == 0:
            print(f"  ... fetched {i}/{len(universe)} (ok={stats.fetched_ok}, fail={stats.fetch_failed})")

    splits_all = (
        pd.concat(split_frames, ignore_index=True)
        if split_frames
        else pd.DataFrame(columns=["ticker", "date", "ratio"])
    )
    divs_all = (
        pd.concat(div_frames, ignore_index=True)
        if div_frames
        else pd.DataFrame(columns=["ticker", "date", "amount"])
    )
    stats.split_rows = len(splits_all)
    stats.dividend_rows = len(divs_all)
    if len(splits_all):
        stats.max_date_seen_split = str(splits_all["date"].max().date())
    if len(divs_all):
        stats.max_date_seen_div = str(divs_all["date"].max().date())

    if dry_run:
        print("\n[dry-run] no writes performed.")
        # still report current table state
        ro = duckdb.connect(db_path, read_only=True)
        try:
            stats.splits_before = _count(ro, "splits")
            stats.dividends_before = _count(ro, "dividends")
        finally:
            ro.close()
        stats.splits_after = stats.splits_before
        stats.dividends_after = stats.dividends_before
        return stats

    # ── WRITE path: dedicated read-write connection. ──────────────────────────
    # Abort cleanly if the single-writer lock is held (data-service is up); never
    # crash a concurrent reader.
    try:
        con = duckdb.connect(db_path, read_only=False)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"ABORT: cannot acquire DuckDB write lock on {db_path} "
            f"(is data-service running?): {exc}"
        )
    try:
        con.execute(DDL_SPLITS)
        con.execute(DDL_DIVIDENDS)
        stats.splits_before = _count(con, "splits")
        stats.dividends_before = _count(con, "dividends")

        # Idempotent bulk upsert. Column order MUST match table schema for
        # `SELECT *`. INSERT OR REPLACE dedupes on the (ticker, date) PK.
        if len(splits_all):
            sdf = splits_all[["ticker", "date", "ratio"]].copy()
            sdf["date"] = pd.to_datetime(sdf["date"])
            con.register("splits_stage", sdf)
            con.execute("INSERT OR REPLACE INTO splits SELECT ticker, CAST(date AS DATE), ratio FROM splits_stage")
            con.unregister("splits_stage")
        if len(divs_all):
            ddf = divs_all[["ticker", "date", "amount"]].copy()
            ddf["date"] = pd.to_datetime(ddf["date"])
            con.register("div_stage", ddf)
            con.execute("INSERT OR REPLACE INTO dividends SELECT ticker, CAST(date AS DATE), amount FROM div_stage")
            con.unregister("div_stage")

        stats.splits_after = _count(con, "splits")
        stats.dividends_after = _count(con, "dividends")
    finally:
        con.close()

    return stats


def _count(con, table: str) -> int:
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception:
        return 0


def _print_report(stats: BackfillStats, dry_run: bool) -> None:
    print("\n" + "=" * 64)
    print("CORPORATE-ACTIONS BACKFILL REPORT" + ("  (DRY-RUN)" if dry_run else ""))
    print("=" * 64)
    print(f"  universe (with OHLCV)      : {stats.universe}")
    print(f"  fetched ok / failed        : {stats.fetched_ok} / {stats.fetch_failed}")
    print(f"  split rows collected       : {stats.split_rows}  (max ex-date {stats.max_date_seen_split})")
    print(f"  dividend rows collected    : {stats.dividend_rows}  (max ex-date {stats.max_date_seen_div})")
    print(f"  splits    table: {stats.splits_before:>7} -> {stats.splits_after:>7}")
    print(f"  dividends table: {stats.dividends_before:>7} -> {stats.dividends_after:>7}")
    if stats.failed_tickers:
        head = ", ".join(stats.failed_tickers[:15])
        more = f" (+{len(stats.failed_tickers) - 15} more)" if len(stats.failed_tickers) > 15 else ""
        print(f"  failed tickers             : {head}{more}")
    print("=" * 64)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 5 (D1) splits+dividends backfill from yfinance")
    ap.add_argument("--db", default="data/market.duckdb", help="DuckDB path")
    ap.add_argument("--universe", default="data/NSE_1500.csv", help="universe CSV (column 'ticker')")
    ap.add_argument("--limit", type=int, default=None, help="cap tickers (smoke test)")
    ap.add_argument("--dry-run", action="store_true", help="fetch + summarise, write nothing")
    ap.add_argument("--max-date", default=None, help="ISO date; drop actions dated after it (default: today)")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between fetches (rate-limit politeness)")
    ap.add_argument("--all", action="store_true", help="include tickers with no OHLCV too")
    args = ap.parse_args()

    max_d = date.fromisoformat(args.max_date) if args.max_date else None
    stats = backfill(
        db_path=args.db,
        universe_csv=args.universe,
        limit=args.limit,
        dry_run=args.dry_run,
        max_date=max_d,
        sleep_s=args.sleep,
        only_in_ohlcv=not args.all,
    )
    _print_report(stats, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
