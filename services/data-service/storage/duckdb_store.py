from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Generator

import duckdb
import pandas as pd

from shared.logging import get_logger

logger = get_logger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    ticker          VARCHAR NOT NULL,
    date            DATE    NOT NULL,
    open            DOUBLE  NOT NULL,
    high            DOUBLE  NOT NULL,
    low             DOUBLE  NOT NULL,
    close           DOUBLE  NOT NULL,
    volume          BIGINT  NOT NULL,
    adjusted_close  DOUBLE  NOT NULL,
    source          VARCHAR NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS features (
    ticker      VARCHAR NOT NULL,
    date        DATE    NOT NULL,
    feature_set STRUCT(
        -- trend
        sma_10 DOUBLE, sma_20 DOUBLE, sma_50 DOUBLE, sma_200 DOUBLE,
        ema_12 DOUBLE, ema_26 DOUBLE,
        sma_ratio_20_50 DOUBLE,
        -- momentum
        rsi_14 DOUBLE, rsi_28 DOUBLE,
        macd DOUBLE, macd_signal DOUBLE, macd_hist DOUBLE,
        stoch_k DOUBLE, stoch_d DOUBLE,
        roc_5 DOUBLE, roc_10 DOUBLE, roc_20 DOUBLE,
        -- volatility
        bb_upper DOUBLE, bb_lower DOUBLE, bb_width DOUBLE, bb_pct DOUBLE,
        atr_14 DOUBLE,
        hist_vol_20 DOUBLE,
        -- volume
        volume_sma_20 DOUBLE, volume_ratio DOUBLE,
        obv DOUBLE,
        -- price action
        high_low_ratio DOUBLE, close_position DOUBLE,
        gap_pct DOUBLE,
        -- calendar
        day_of_week INT, month INT,
        -- lagged returns
        return_1d DOUBLE, return_2d DOUBLE, return_3d DOUBLE,
        return_5d DOUBLE, return_10d DOUBLE
    ),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS labels (
    ticker              VARCHAR NOT NULL,
    date                DATE    NOT NULL,
    label_direction     INTEGER NOT NULL,   -- 1=UP, 0=DOWN (5-day horizon)
    label_return_pct    DOUBLE  NOT NULL,   -- actual % return over 5 days
    horizon_days        INTEGER NOT NULL DEFAULT 5,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id           VARCHAR NOT NULL PRIMARY KEY,
    ticker              VARCHAR NOT NULL,
    generated_at        TIMESTAMP NOT NULL,
    signal_date         DATE NOT NULL,
    direction           VARCHAR NOT NULL,
    prob_up             DOUBLE NOT NULL,
    confidence          DOUBLE NOT NULL,
    expected_return_pct DOUBLE NOT NULL,
    model_version       VARCHAR NOT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    order_id            VARCHAR NOT NULL PRIMARY KEY,
    ticker              VARCHAR NOT NULL,
    side                VARCHAR NOT NULL,
    order_type          VARCHAR NOT NULL,
    quantity            INTEGER NOT NULL,
    limit_price         DOUBLE,
    stop_loss_price     DOUBLE,
    take_profit_price   DOUBLE,
    status              VARCHAR NOT NULL,
    created_at          TIMESTAMP NOT NULL,
    filled_at           TIMESTAMP,
    avg_fill_price      DOUBLE,
    signal_id           VARCHAR,
    broker_order_id     VARCHAR
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_at             TIMESTAMP NOT NULL PRIMARY KEY,
    total_value_inr         DOUBLE NOT NULL,
    cash_inr                DOUBLE NOT NULL,
    num_positions           INTEGER NOT NULL,
    daily_pnl_inr           DOUBLE NOT NULL,
    daily_pnl_pct           DOUBLE NOT NULL,
    cumulative_return_pct   DOUBLE NOT NULL,
    sharpe_ratio            DOUBLE,
    max_drawdown_pct        DOUBLE,
    win_rate                DOUBLE
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker              VARCHAR NOT NULL,
    as_of_date          DATE    NOT NULL,
    market_cap          DOUBLE,
    trailing_pe         DOUBLE,
    forward_pe          DOUBLE,
    price_to_book       DOUBLE,
    enterprise_value    DOUBLE,
    ev_to_revenue       DOUBLE,
    ev_to_ebitda        DOUBLE,
    total_revenue       DOUBLE,
    revenue_growth      DOUBLE,
    gross_margins       DOUBLE,
    operating_margins   DOUBLE,
    profit_margins      DOUBLE,
    return_on_equity    DOUBLE,
    return_on_assets    DOUBLE,
    debt_to_equity      DOUBLE,
    current_ratio       DOUBLE,
    book_value          DOUBLE,
    dividend_yield      DOUBLE,
    payout_ratio        DOUBLE,
    avg_volume          DOUBLE,
    shares_outstanding  DOUBLE,
    insider_hold_pct    DOUBLE,
    inst_hold_pct       DOUBLE,
    analyst_target_mean DOUBLE,
    analyst_target_high DOUBLE,
    analyst_target_low  DOUBLE,
    analyst_recommendation VARCHAR,
    analyst_count       INTEGER,
    sector              VARCHAR,
    industry            VARCHAR,
    country             VARCHAR,
    PRIMARY KEY (ticker, as_of_date)
);

CREATE TABLE IF NOT EXISTS dividends (
    ticker  VARCHAR NOT NULL,
    date    DATE    NOT NULL,
    amount  DOUBLE  NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS splits (
    ticker  VARCHAR NOT NULL,
    date    DATE    NOT NULL,
    ratio   DOUBLE  NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS corporate_events (
    ticker          VARCHAR NOT NULL,
    event_type      VARCHAR NOT NULL,
    event_date      DATE,
    earnings_high   DOUBLE,
    earnings_low    DOUBLE,
    earnings_avg    DOUBLE,
    revenue_high    DOUBLE,
    revenue_low     DOUBLE,
    revenue_avg     DOUBLE,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, event_type)
);
"""


class DuckDBStore:
    """Thread-safe DuckDB wrapper with connection pooling via a per-thread connection."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            for statement in DDL.split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(stmt)
        logger.info("DuckDB schema initialised", db_path=self._db_path)

    @contextmanager
    def _connect(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        conn = duckdb.connect(self._db_path)
        try:
            yield conn
        finally:
            conn.close()

    # ── OHLCV ──────────────────────────────────────────────────────────────────

    def upsert_ohlcv(self, df: pd.DataFrame, source: str) -> int:
        """Insert or replace OHLCV rows. Returns rows written."""
        required = {"ticker", "date", "open", "high", "low", "close", "volume", "adjusted_close"}
        if not required.issubset(df.columns):
            raise ValueError(f"Missing columns: {required - set(df.columns)}")
        df = df.copy()
        df["source"] = source
        # Ensure date column is datetime64 so DuckDB maps it correctly to DATE
        df["date"] = pd.to_datetime(df["date"])
        # pandas 2.x on Python 3.13 uses StringDtype ('str') by default;
        # DuckDB 1.1.x only recognises object-backed strings — cast all string cols.
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO ohlcv
                    (ticker, date, open, high, low, close, volume, adjusted_close, source)
                SELECT
                    ticker,
                    date::DATE,
                    open::DOUBLE,
                    high::DOUBLE,
                    low::DOUBLE,
                    close::DOUBLE,
                    volume::BIGINT,
                    adjusted_close::DOUBLE,
                    source
                FROM df
            """)
            return len(df)

    def get_ohlcv(
        self,
        ticker: str,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        conditions = ["ticker = ?"]
        params: list = [ticker]
        if start:
            conditions.append("date >= ?")
            params.append(start)
        if end:
            conditions.append("date <= ?")
            params.append(end)
        where = " AND ".join(conditions)
        with self._connect() as conn:
            return conn.execute(
                f"SELECT * FROM ohlcv WHERE {where} ORDER BY date",
                params,
            ).df()

    def get_latest_ohlcv_date(self, ticker: str) -> date | None:
        with self._connect() as conn:
            result = conn.execute(
                "SELECT MAX(date) FROM ohlcv WHERE ticker = ?", [ticker]
            ).fetchone()
        return result[0] if result and result[0] else None

    # ── Fundamentals ───────────────────────────────────────────────────────────

    def upsert_fundamentals(self, df: pd.DataFrame) -> int:
        df = df.copy()
        df["as_of_date"] = pd.to_datetime(df["as_of_date"])
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO fundamentals SELECT * FROM df")
            return len(df)

    def get_fundamentals(self, tickers: list[str] | None = None) -> pd.DataFrame:
        with self._connect() as conn:
            if tickers:
                placeholders = ",".join(["?" * len(tickers)])
                return conn.execute(
                    f"SELECT * FROM fundamentals WHERE ticker IN ({placeholders}) "
                    "QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY as_of_date DESC) = 1",
                    tickers,
                ).df()
            return conn.execute(
                "SELECT * FROM fundamentals "
                "QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY as_of_date DESC) = 1"
            ).df()

    # ── Dividends ──────────────────────────────────────────────────────────────

    def upsert_dividends(self, df: pd.DataFrame) -> int:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO dividends SELECT * FROM df")
            return len(df)

    # ── Splits ─────────────────────────────────────────────────────────────────

    def upsert_splits(self, df: pd.DataFrame) -> int:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO splits SELECT * FROM df")
            return len(df)

    # ── Corporate events ───────────────────────────────────────────────────────

    def upsert_corporate_events(self, df: pd.DataFrame) -> int:
        df = df.copy()
        df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO corporate_events SELECT * FROM df")
            return len(df)

    def get_db_stats(self) -> dict:
        with self._connect() as conn:
            tables = ["ohlcv", "fundamentals", "dividends", "splits", "corporate_events"]
            stats = {}
            for t in tables:
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
                    stats[t] = row[0] if row else 0
                except Exception:
                    stats[t] = 0
            try:
                stats["ohlcv_tickers"] = conn.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM ohlcv"
                ).fetchone()[0]
                stats["ohlcv_date_range"] = conn.execute(
                    "SELECT MIN(date), MAX(date) FROM ohlcv"
                ).fetchone()
            except Exception:
                pass
            return stats

    # ── Signals ────────────────────────────────────────────────────────────────

    def insert_signals(self, df: pd.DataFrame) -> int:
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO signals SELECT * FROM df")
            return len(df)

    def get_signals_for_date(self, signal_date: date) -> pd.DataFrame:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM signals WHERE signal_date = ? ORDER BY confidence DESC",
                [signal_date],
            ).df()
