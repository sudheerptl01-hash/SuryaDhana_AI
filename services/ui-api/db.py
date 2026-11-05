"""Shared DuckDB connection helper for UI API routes.

Strategy: Open a SINGLE persistent read-only connection at module startup.
DuckDB 1.1+ allows multiple concurrent read-only connections even while a
write connection exists. The persistent connection avoids per-request locking
contention that caused "Conflicting lock is held in PID 0" crashes.
"""
from __future__ import annotations

import os
import time
import threading
from contextlib import contextmanager
from pathlib import Path
import duckdb

DB_PATH = os.environ.get(
    "DATABASE_URL",
    str(Path(__file__).resolve().parent.parent.parent / "data" / "market.duckdb"),
)

# Minimal schema for the stub in-memory DB (all reads return 0 rows)
_STUB_SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE,
    low DOUBLE, close DOUBLE, volume BIGINT, adjusted_close DOUBLE, source VARCHAR
);
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker VARCHAR, as_of_date DATE, market_cap DOUBLE, trailing_pe DOUBLE,
    forward_pe DOUBLE, price_to_book DOUBLE, enterprise_value DOUBLE,
    ev_to_revenue DOUBLE, ev_to_ebitda DOUBLE, total_revenue DOUBLE,
    revenue_growth DOUBLE, gross_margins DOUBLE, operating_margins DOUBLE,
    profit_margins DOUBLE, return_on_equity DOUBLE, return_on_assets DOUBLE,
    debt_to_equity DOUBLE, current_ratio DOUBLE, book_value DOUBLE,
    dividend_yield DOUBLE, payout_ratio DOUBLE, avg_volume DOUBLE,
    shares_outstanding DOUBLE, insider_hold_pct DOUBLE, inst_hold_pct DOUBLE,
    analyst_target_mean DOUBLE, analyst_target_high DOUBLE, analyst_target_low DOUBLE,
    analyst_recommendation VARCHAR, analyst_count DOUBLE,
    sector VARCHAR, industry VARCHAR, country VARCHAR
);
CREATE TABLE IF NOT EXISTS dividends  (ticker VARCHAR, date DATE, amount DOUBLE);
CREATE TABLE IF NOT EXISTS splits     (ticker VARCHAR, date DATE, ratio DOUBLE);
CREATE TABLE IF NOT EXISTS corporate_events (ticker VARCHAR, date DATE, event_type VARCHAR, description VARCHAR);
"""

_conn: duckdb.DuckDBPyConnection | None = None
_conn_lock = threading.Lock()
_using_stub = False


def _open_ro_conn(max_retries: int = 10, base_sleep: float = 0.3) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return duckdb.connect(DB_PATH, read_only=True)
        except duckdb.IOException as exc:
            if attempt < max_retries - 1:
                sleep = base_sleep * (2 ** attempt)
                time.sleep(min(sleep, 8.0))
            else:
                raise RuntimeError(
                    f"Cannot open DuckDB after {max_retries} retries: {exc}"
                ) from exc
    raise RuntimeError("Unreachable")


def _get_shared_conn() -> duckdb.DuckDBPyConnection:
    """Return (or create) the module-level persistent read-only connection."""
    global _conn, _using_stub
    with _conn_lock:
        if _conn is not None:
            # Verify the connection is still alive
            try:
                _conn.execute("SELECT 1")
                return _conn
            except Exception:
                _conn = None

        if not Path(DB_PATH).exists():
            stub = duckdb.connect(":memory:")
            stub.execute(_STUB_SCHEMA)
            _conn = stub
            _using_stub = True
            return _conn

        try:
            _conn = _open_ro_conn()
            _using_stub = False
        except RuntimeError:
            # Fall back to in-memory stub — API returns empty results instead of 500
            stub = duckdb.connect(":memory:")
            stub.execute(_STUB_SCHEMA)
            _conn = stub
            _using_stub = True

        return _conn


def db_exists() -> bool:
    return Path(DB_PATH).exists()


def is_using_stub() -> bool:
    return _using_stub


@contextmanager
def get_conn(read_only: bool = True):
    """
    Yield the shared read-only DuckDB connection.

    Thread-safe: each caller gets the same persistent connection.
    DuckDB read-only connections are safe for concurrent reads.
    Falls back to in-memory stub when the DB file is locked or missing.
    """
    conn = _get_shared_conn()
    try:
        yield conn
    except duckdb.IOException:
        # Connection died (DB was checkpointed/replaced) — reset and retry once
        global _conn
        with _conn_lock:
            _conn = None
        conn2 = _get_shared_conn()
        yield conn2


def reset_conn() -> None:
    """Force the next request to re-open the connection. Call after DB refresh."""
    global _conn
    with _conn_lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
