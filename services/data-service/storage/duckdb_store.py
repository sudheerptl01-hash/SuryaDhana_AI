from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from shared.logging import get_logger


def missed_weekday_sessions(latest: date, today: date) -> int:
    """Weekday sessions strictly between ``latest`` and ``today`` whose bar should already exist.

    Today's own bar is not expected until the EOD run, so it never counts. There is no NSE
    holiday calendar here, so an exchange holiday reads as one missed session (conservative).
    """
    if latest >= today:
        return 0
    return int(np.busday_count(latest + timedelta(days=1), today))

logger = get_logger(__name__)

_OHLCV_META_CACHE: list[dict] | None = None
_OHLCV_META_TS: float = 0.0
_OHLCV_META_TTL: float = 300.0  # 5 minutes


def _duck_compatible(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of ``df`` with pandas string-extension columns cast to ``object``.

    pandas >= 3 infers the ``str`` dtype, which DuckDB's replacement scan rejects
    ("Data type 'str' not recognized"); object columns are ingested as VARCHAR.
    """
    df = df.copy()
    for col in df.columns:
        if isinstance(df[col].dtype, pd.StringDtype) or str(df[col].dtype) in ("str", "string"):
            df[col] = df[col].astype(object)
    return df

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

CREATE TABLE IF NOT EXISTS stock_metrics (
    ticker          VARCHAR NOT NULL,
    as_of_date      DATE    NOT NULL,
    cmp             DOUBLE,
    pe_ratio        DOUBLE,
    mktcap_cr       DOUBLE,
    div_yld_pct     DOUBLE,
    np_qtr_cr       DOUBLE,
    qtr_pft_var     DOUBLE,
    sales_qtr_cr    DOUBLE,
    qtr_sal_var     DOUBLE,
    roce_pct        DOUBLE,
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

CREATE TABLE IF NOT EXISTS live_quotes (
    symbol      VARCHAR NOT NULL,
    ts          TIMESTAMP NOT NULL,
    payload     VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ML feature store: columnar, one row per (ticker, date)
CREATE TABLE IF NOT EXISTS ml_features (
    ticker          VARCHAR NOT NULL,
    date            DATE    NOT NULL,
    -- ── Price / Technical ──────────────────────────────────────────────────────
    ret_1d          DOUBLE, ret_5d  DOUBLE, ret_20d DOUBLE,
    log_ret         DOUBLE,
    sma_20          DOUBLE, sma_50  DOUBLE, sma_200 DOUBLE,
    ema_12          DOUBLE, ema_26  DOUBLE,
    price_vs_sma20  DOUBLE, price_vs_sma50 DOUBLE, price_vs_sma200 DOUBLE,
    rsi_14          DOUBLE, rsi_7   DOUBLE, rsi_28  DOUBLE,
    macd            DOUBLE, macd_signal DOUBLE, macd_hist DOUBLE,
    bollinger_pctb  DOUBLE, bb_width DOUBLE,
    atr_14          DOUBLE, atr_14_pct DOUBLE,
    realized_vol_20d DOUBLE,
    volume_zscore   DOUBLE, volume_ratio DOUBLE,
    obv             DOUBLE,
    gap_pct         DOUBLE,
    high_low_ratio  DOUBLE, close_position DOUBLE,
    stoch_k         DOUBLE, stoch_d DOUBLE,
    williams_r      DOUBLE,
    roc_5           DOUBLE, roc_10 DOUBLE, roc_20 DOUBLE,
    mfi_14          DOUBLE, cmf_20 DOUBLE,
    return_lag_1d   DOUBLE, return_lag_2d DOUBLE, return_lag_3d DOUBLE,
    return_lag_5d   DOUBLE, return_lag_10d DOUBLE,
    is_green_candle INTEGER,
    -- ── Calendar ──────────────────────────────────────────────────────────────
    day_of_week     INTEGER, month INTEGER,
    -- ── Fundamentals (from yfinance quarterly, forward-filled) ────────────────
    trailing_pe     DOUBLE, price_to_book  DOUBLE, ev_to_ebitda DOUBLE,
    peg_ratio       DOUBLE,
    revenue_growth  DOUBLE,
    gross_margins   DOUBLE, operating_margins DOUBLE, profit_margins DOUBLE,
    return_on_equity DOUBLE, return_on_assets DOUBLE,
    debt_to_equity  DOUBLE, current_ratio   DOUBLE,
    altman_z        DOUBLE,
    -- ── Promoter / Institutional (from yfinance .info) ────────────────────────
    insider_hold_pct DOUBLE, inst_hold_pct DOUBLE,
    -- ── Macro / Regime (market-wide, same for all tickers on a date) ──────────
    india_vix       DOUBLE, vix_zscore      DOUBLE,
    nifty_ret_5d    DOUBLE, nifty_regime    VARCHAR,
    market_breadth  DOUBLE,
    usd_inr         DOUBLE,
    -- ── Metadata ──────────────────────────────────────────────────────────────
    feature_version VARCHAR DEFAULT 'v1',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

-- ML label store: forward-looking labels (NEVER use as features)
CREATE TABLE IF NOT EXISTS ml_labels (
    ticker              VARCHAR NOT NULL,
    date                DATE    NOT NULL,
    horizon_days        INTEGER NOT NULL DEFAULT 5,
    -- Simple binary direction
    label_direction     INTEGER,   -- 1=UP, 0=DOWN
    label_return_pct    DOUBLE,    -- actual % return
    -- Triple-barrier (Lopez de Prado)
    label_barrier       INTEGER,   -- +1=profit target hit, -1=stop loss hit, 0=timeout
    profit_target_pct   DOUBLE DEFAULT 2.0,
    stop_loss_pct       DOUBLE DEFAULT 2.0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date, horizon_days)
);

-- Instrument master: which universe tickers are operating companies vs ETFs/funds.
-- Classified from NSE's official EQUITY_L / eq_etfseclist files (data/reference/).
CREATE TABLE IF NOT EXISTS instruments (
    ticker           VARCHAR NOT NULL PRIMARY KEY,
    instrument_type  VARCHAR NOT NULL,   -- EQUITY | ETF | INVALID | UNKNOWN
    ml_eligible      BOOLEAN NOT NULL,   -- only EQUITY rows feed ML / screener / backtest
    classified_by    VARCHAR NOT NULL,   -- nse_equity_list | nse_etf_list | rule:<name>
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Market index daily closes (NIFTY 50, INDIA VIX) for macro features.
CREATE TABLE IF NOT EXISTS market_index_daily (
    symbol      VARCHAR NOT NULL,
    date        DATE    NOT NULL,
    close       DOUBLE  NOT NULL,
    source      VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, date)
);

-- Bars rejected by the ingestion quality gate (kept for audit, never used).
CREATE TABLE IF NOT EXISTS ohlcv_quarantine (
    ticker      VARCHAR NOT NULL,
    date        DATE    NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    reason      VARCHAR NOT NULL,
    source      VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

-- NSE full bhavcopy: every security every day as published (raw prices, incl. later
-- delisted names) + delivery. Survivorship-free research universe (bhavcopy.py).
CREATE TABLE IF NOT EXISTS nse_bhavcopy (
    symbol        VARCHAR NOT NULL,
    series        VARCHAR NOT NULL,
    date          DATE    NOT NULL,
    prev_close    DOUBLE,
    open          DOUBLE,
    high          DOUBLE,
    low           DOUBLE,
    last          DOUBLE,
    close         DOUBLE  NOT NULL,
    avg_price     DOUBLE,
    volume        BIGINT,
    turnover_lacs DOUBLE,
    trades        BIGINT,
    deliv_qty     BIGINT,
    deliv_pct     DOUBLE,
    PRIMARY KEY (symbol, series, date)
);

-- "Who is holding overnight" datasets (nse_positions.py, nse_filings.py).
-- One row per underlying per day from the F&O bhavcopy. OI in shares, volume in contracts.
CREATE TABLE IF NOT EXISTS nse_fo_daily (
    date            DATE    NOT NULL,
    symbol          VARCHAR NOT NULL,
    kind            VARCHAR NOT NULL,        -- stock | index
    near_expiry     DATE,
    fut_close       DOUBLE,
    fut_settle      DOUBLE,
    fut_oi          DOUBLE,
    fut_oi_chg      DOUBLE,
    fut_contracts   DOUBLE,
    fut_value_lakh  DOUBLE,
    call_oi         DOUBLE,
    put_oi          DOUBLE,
    call_oi_chg     DOUBLE,
    put_oi_chg      DOUBLE,
    opt_contracts   DOUBLE,
    opt_value_lakh  DOUBLE,
    PRIMARY KEY (date, symbol)
);

-- FII/FPI and DII cash-market buying and selling (NSE + BSE + MSEI, provisional, rupees crore). NSE's API only
-- serves the latest day, so history starts when collection started (12 Oct 2026).
CREATE TABLE IF NOT EXISTS nse_fii_dii_cash (
    date      DATE    NOT NULL,
    category  VARCHAR NOT NULL,
    buy_cr    DOUBLE,
    sell_cr   DOUBLE,
    net_cr    DOUBLE,
    PRIMARY KEY (date, category)
);

CREATE TABLE IF NOT EXISTS nse_participant_oi (
    date               DATE    NOT NULL,
    client_type        VARCHAR NOT NULL,     -- CLIENT | DII | FII | PRO | TOTAL
    fut_idx_long       BIGINT, fut_idx_short  BIGINT,
    fut_stk_long       BIGINT, fut_stk_short  BIGINT,
    opt_idx_call_long  BIGINT, opt_idx_put_long  BIGINT,
    opt_idx_call_short BIGINT, opt_idx_put_short BIGINT,
    opt_stk_call_long  BIGINT, opt_stk_put_long  BIGINT,
    opt_stk_call_short BIGINT, opt_stk_put_short BIGINT,
    total_long         BIGINT, total_short    BIGINT,
    PRIMARY KEY (date, client_type)
);

-- Bulk and block deals by named client, and institutional short sales (kind = short).
CREATE TABLE IF NOT EXISTS nse_deals (
    date           DATE    NOT NULL,
    kind           VARCHAR NOT NULL,         -- bulk | block | short
    symbol         VARCHAR NOT NULL,
    security_name  VARCHAR,
    client_name    VARCHAR,
    side           VARCHAR,                  -- BUY | SELL
    qty            DOUBLE,
    price          DOUBLE,
    remarks        VARCHAR
);

-- Margin trading (MTF) funded positions. The report for day T is published on T+1.
CREATE TABLE IF NOT EXISTS nse_mtf (
    date          DATE    NOT NULL,
    symbol        VARCHAR NOT NULL,
    name          VARCHAR,
    qty_financed  DOUBLE,
    amount_lakh   DOUBLE,
    PRIMARY KEY (date, symbol)
);
CREATE TABLE IF NOT EXISTS nse_mtf_market (
    date             DATE PRIMARY KEY,
    begin_lakh       DOUBLE,
    fresh_lakh       DOUBLE,
    liquidated_lakh  DOUBLE,
    end_lakh         DOUBLE
);

-- SEBI PIT insider disclosures. intimation_date is when the market learned of the trade.
CREATE TABLE IF NOT EXISTS nse_insider_trades (
    record_id        VARCHAR PRIMARY KEY,
    symbol           VARCHAR NOT NULL,
    person           VARCHAR,
    category         VARCHAR,
    mode             VARCHAR,
    txn_type         VARCHAR,
    qty              DOUBLE,
    value            DOUBLE,
    before_pct       DOUBLE,
    after_pct        DOUBLE,
    from_date        DATE,
    to_date          DATE,
    intimation_date  DATE,
    broadcast_ts     VARCHAR
);

-- Quarterly shareholding pattern with shareholder counts parsed from the XBRL filing.
CREATE TABLE IF NOT EXISTS nse_shareholding (
    symbol          VARCHAR NOT NULL,
    period_end      DATE    NOT NULL,
    broadcast_ts    VARCHAR,
    promoter_pct    DOUBLE,
    public_pct      DOUBLE,
    total_holders   DOUBLE,
    retail_holders  DOUBLE,
    retail_pct      DOUBLE,
    hni_holders     DOUBLE,
    fpi_holders     DOUBLE,
    fpi_pct         DOUBLE,
    mf_holders      DOUBLE,
    mf_pct          DOUBLE,
    xbrl_url        VARCHAR,
    PRIMARY KEY (symbol, period_end, broadcast_ts)
);

-- Corporate events from NSE (event calendar, board-meeting intimations, corporate actions). Upcoming
-- rows are re-pulled daily and past rows stay, so the table becomes a point-in-time event history.
CREATE TABLE IF NOT EXISTS nse_events (
    symbol        VARCHAR NOT NULL,
    event_date    DATE    NOT NULL,
    kind          VARCHAR NOT NULL,      -- RESULTS | DIVIDEND | BONUS | SPLIT | RIGHTS | BUYBACK | FUND RAISE | M&A | AGM | OTHER
    source        VARCHAR NOT NULL,      -- calendar | board | action
    tags          VARCHAR,               -- every kind the purpose mentions, comma separated
    company       VARCHAR,
    purpose       VARCHAR,
    detail        VARCHAR,
    record_date   DATE,
    announced_at  VARCHAR,
    url           VARCHAR,
    first_seen    TIMESTAMP,
    PRIMARY KEY (symbol, event_date, kind, source)
);

-- Quarterly results release times (NSE financial-results + integrated-filing feeds), one row per quarter-end
CREATE TABLE IF NOT EXISTS nse_results (
    symbol        VARCHAR   NOT NULL,
    period_end    DATE      NOT NULL,
    released_at   TIMESTAMP NOT NULL,
    fetched_at    TIMESTAMP,
    PRIMARY KEY (symbol, period_end)
);

-- Terminal v2 (PLAN 1.4 ingests, builder B1-DATA): participant-wise volumes, FII derivative stats, clients >= 3 % of MWPL (T-1).
-- Parsers + ingest in nse_positions.py (TERMINAL_DATASETS). The IV / drivers / data-health tables live in their packages.
-- (No semicolon may appear in a comment of this string: _init_schema splits it on the semicolon.)
CREATE TABLE IF NOT EXISTS nse_participant_vol (
    date DATE NOT NULL, client_type VARCHAR NOT NULL,
    fut_idx_long BIGINT, fut_idx_short BIGINT, fut_stk_long BIGINT, fut_stk_short BIGINT,
    opt_idx_call_long BIGINT, opt_idx_put_long BIGINT, opt_idx_call_short BIGINT, opt_idx_put_short BIGINT,
    opt_stk_call_long BIGINT, opt_stk_put_long BIGINT, opt_stk_call_short BIGINT, opt_stk_put_short BIGINT,
    total_long BIGINT, total_short BIGINT, first_seen_at TIMESTAMP,
    PRIMARY KEY (date, client_type)
);
CREATE TABLE IF NOT EXISTS nse_fii_stats (
    date DATE NOT NULL, instrument VARCHAR NOT NULL, buy_contracts BIGINT, buy_cr DOUBLE, sell_contracts BIGINT, sell_cr DOUBLE,
    oi_contracts BIGINT, oi_cr DOUBLE, first_seen_at TIMESTAMP,
    PRIMARY KEY (date, instrument)
);
CREATE TABLE IF NOT EXISTS nse_mwpl_clients (
    date DATE NOT NULL, symbol VARCHAR NOT NULL, client_rank INTEGER NOT NULL, pct_mwpl DOUBLE, first_seen_at TIMESTAMP,
    PRIMARY KEY (date, symbol, client_rank)
);
-- Point-in-time columns (PLAN 1.4 / §0.3) on the NSE tables NSE re-publishes or adds to late: nullable, filled by the
-- 22:45 revision pass (nse_positions.revise_bhavcopy) and by later ingests. Existing upserts list their columns explicitly.
ALTER TABLE nse_bhavcopy ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP;
ALTER TABLE nse_bhavcopy ADD COLUMN IF NOT EXISTS release_at TIMESTAMP;
ALTER TABLE nse_deals ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP;
ALTER TABLE nse_results ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP;

ALTER TABLE ml_labels ADD COLUMN IF NOT EXISTS cost_hurdle_pct DOUBLE;
ALTER TABLE ml_features ADD COLUMN IF NOT EXISTS sma_ratio_20_50 DOUBLE;
ALTER TABLE ml_features ADD COLUMN IF NOT EXISTS uptrend_20_50 INTEGER;
ALTER TABLE ml_features ADD COLUMN IF NOT EXISTS uptrend_50_200 INTEGER;
ALTER TABLE ml_features ADD COLUMN IF NOT EXISTS macd_pct DOUBLE;
ALTER TABLE ml_features ADD COLUMN IF NOT EXISTS macd_hist_pct DOUBLE;
"""


class _RWLock:
    """Readers-writer lock for one DuckDB database handle (Terminal v2 PLAN 1.5, R-ARCH fix 2).

    Readers share; a writer is exclusive and preferred (a waiting writer stops new readers so an ingest can
    never starve behind a stream of page reads). Re-entrancy rules, so a caller can never deadlock itself:
    the thread holding the exclusive lock may take shared locks (no-ops) and may re-enter exclusive; a thread
    holding a shared lock that asks for exclusive gets ``RuntimeError`` (upgrade would deadlock against the
    other readers) instead of hanging. Wait time is reported to ``on_wait(mode, seconds)`` for the metrics.
    """

    def __init__(self, on_wait: Any = None) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer: int | None = None          # ident of the thread holding exclusive
        self._writer_depth = 0
        self._writers_waiting = 0
        self._local = threading.local()           # per-thread shared-lock depth
        self.on_wait = on_wait

    def _read_depth(self) -> int:
        return getattr(self._local, "depth", 0)

    def _set_read_depth(self, n: int) -> None:
        self._local.depth = n

    # ── shared ────────────────────────────────────────────────────────────────
    def acquire_read(self) -> None:
        me = threading.get_ident()
        if self._writer == me or self._read_depth() > 0:   # inside own write, or nested read: no-op
            self._set_read_depth(self._read_depth() + 1)
            return
        t0 = time.monotonic()
        with self._cond:
            while self._writer is not None or self._writers_waiting > 0:
                self._cond.wait()
            self._readers += 1
        self._set_read_depth(1)
        if self.on_wait is not None:
            self.on_wait("read", time.monotonic() - t0)

    def release_read(self) -> None:
        depth = self._read_depth()
        if depth <= 0:
            raise RuntimeError("release_read without acquire_read")
        self._set_read_depth(depth - 1)
        if depth > 1 or self._writer == threading.get_ident():
            return
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    # ── exclusive ─────────────────────────────────────────────────────────────
    def acquire_write(self) -> None:
        me = threading.get_ident()
        if self._writer == me:
            self._writer_depth += 1
            return
        if self._read_depth() > 0:
            raise RuntimeError("cannot take the DuckDB write lock while holding a read lock (upgrade deadlock)")
        t0 = time.monotonic()
        with self._cond:
            self._writers_waiting += 1
            try:
                while self._writer is not None or self._readers > 0:
                    self._cond.wait()
            finally:
                self._writers_waiting -= 1
            self._writer = me
            self._writer_depth = 1
        if self.on_wait is not None:
            self.on_wait("write", time.monotonic() - t0)

    def release_write(self) -> None:
        if self._writer != threading.get_ident():
            raise RuntimeError("release_write by a thread that does not hold the write lock")
        self._writer_depth -= 1
        if self._writer_depth > 0:
            return
        with self._cond:
            self._writer = None
            self._cond.notify_all()

    def locked(self) -> bool:
        """True while any holder exists (the old ``threading.Lock.locked()`` contract of ``store._lock``)."""
        return self._writer is not None or self._readers > 0


class _ExclusiveHandle:
    """``store._lock`` as it always behaved: ``with store._lock:`` is the exclusive (write) side of the RW lock.

    Kept so the remaining ``with store._lock: store._conn.execute(...)`` call sites outside the store stay correct
    (serialised, as before) until they move to ``store.read()`` / ``store.reader()`` / ``store.writer()``.
    """

    def __init__(self, rw: _RWLock) -> None:
        self._rw = rw

    def __enter__(self) -> _ExclusiveHandle:
        self._rw.acquire_write()
        return self

    def __exit__(self, *exc: object) -> None:
        self._rw.release_write()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        self._rw.acquire_write()
        return True

    def release(self) -> None:
        self._rw.release_write()

    def locked(self) -> bool:
        return self._rw.locked()


TERMINAL_V2_SCHEMA_MODULES: tuple[str, ...] = ("data_health.schema", "fo_iv.schema", "index_drivers.schema")


def _terminal_v2_ddl() -> list[str]:
    """The CREATE statements of the terminal v2 packages that are importable (each guarded; order: data_health first)."""
    import importlib

    out: list[str] = []
    for name in TERMINAL_V2_SCHEMA_MODULES:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        out.extend(mod.ddl_statements())
    return out


def _terminal_v2_positions_meta(store: Any) -> dict[str, dict[str, Any]]:
    """{table: {first, last, rows}} from every importable terminal v2 package (never raises: freshness rows are additive)."""
    import importlib

    out: dict[str, dict[str, Any]] = {}
    for name in TERMINAL_V2_SCHEMA_MODULES:
        try:
            mod = importlib.import_module(name)
            out.update(mod.positions_meta(store))
        except Exception:  # noqa: BLE001 — a missing package or a store opened before its DDL ran
            continue
    return out


def _lock_wait_observer() -> Any:
    """The DuckDB lock-wait histogram from shared.metrics when it is importable (data-service, tests); else None."""
    try:
        from shared.metrics import observe_duckdb_lock_wait
    except Exception:  # noqa: BLE001 — metrics are optional for scripts that import the store alone
        return None
    return observe_duckdb_lock_wait


class DuckDBStore:
    """
    Persistent-connection DuckDB owner (data-service is the single writer).

    Opens one read-write connection at startup and holds it for the process lifetime. Writes run on that
    connection under the exclusive side of a readers-writer lock (``write()`` / ``writer()`` / the legacy
    ``_lock``). Reads run on a per-call ``self._conn.cursor()`` — DuckDB's documented way to use one database
    from many threads: a cursor shares the database and has its own transaction context — under the shared
    side (``read()`` / ``read_rows()`` / ``read_one()`` / ``reader()``), so ten concurrent page reads take
    about as long as one (R-ARCH §2.3 measured ten taking the sum of ten under the old single ``threading.Lock``).

    DataFrame replacement scans (``FROM df`` with a local pandas frame) work on cursors exactly as on the
    connection; a frame that must be visible under a fixed name is passed as ``frames={"name": df}``.

    WHY one connection: on Docker Desktop (Mac) with virtioFS, duckdb.connect() re-acquires POSIX advisory
    locks on every open/close cycle and a second open can fail with "Conflicting lock held in PID 0"; one
    open handle plus cursors sidesteps that race.
    """

    def __init__(self, db_path: str, read_only: bool = False) -> None:
        self._db_path = db_path
        self._rw = _RWLock(on_wait=_lock_wait_observer())
        self._lock: Any = _ExclusiveHandle(self._rw)
        self._closed = False
        self._read_only = read_only
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        if read_only:
            self._conn = duckdb.connect(self._db_path, read_only=True)
        else:
            try:
                self._conn = duckdb.connect(self._db_path)
            except Exception as e:
                if "lock" in str(e).lower():
                    import logging
                    logging.getLogger(__name__).warning(
                        "DuckDB write-lock unavailable; falling back to read-only mode"
                    )
                    self._read_only = True
                    self._conn = duckdb.connect(self._db_path, read_only=True)
                else:
                    raise
        self._apply_pragmas(self._conn)
        if not self._read_only:
            self._init_schema()

    def _apply_pragmas(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Cap DuckDB's memory (design review minor 11): unbounded, a full-table
        window scan can balloon past the container limit and OOM the service.
        Spill goes to an on-disk temp dir instead. Best-effort — an old DuckDB
        without a PRAGMA must not stop the service from starting."""
        mem = os.getenv("DUCKDB_MEMORY_LIMIT", "1.5GB")
        tmp = Path(self._db_path).parent / ".duckdb_tmp"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
            conn.execute(f"SET memory_limit='{mem}'")
            conn.execute(f"SET temp_directory='{tmp}'")
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Could not apply DuckDB memory pragmas (memory_limit=%s)", mem
            )

    # ── Read / write API (PLAN 1.5) ──────────────────────────────────────────

    @contextmanager
    def reader(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """A per-call cursor under the SHARED lock: ``with store.reader() as con: con.execute(...)``.

        For SELECTs only (including helpers that take a connection, e.g. ``security.profile(con, ...)``). The
        cursor is closed on exit, so a frame registered on it never leaks into the next call.
        """
        if self._closed:
            raise RuntimeError("DuckDBStore is closed")
        self._rw.acquire_read()
        cur = None
        try:
            cur = self._conn.cursor()
            yield cur
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:  # noqa: BLE001 — a cursor that failed to open has nothing to close
                    pass
            self._rw.release_read()

    @contextmanager
    def writer(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """The primary connection under the EXCLUSIVE lock, for multi-statement writes / transactions."""
        if self._closed:
            raise RuntimeError("DuckDBStore is closed")
        self._rw.acquire_write()
        try:
            yield self._conn
        finally:
            self._rw.release_write()

    @staticmethod
    def _register(con: duckdb.DuckDBPyConnection, frames: Mapping[str, pd.DataFrame] | None) -> list[str]:
        names: list[str] = []
        for name, frame in (frames or {}).items():
            con.register(name, _duck_compatible(frame))
            names.append(name)
        return names

    def read(self, sql: str, params: Sequence[Any] | None = None, *,
             frames: Mapping[str, pd.DataFrame] | None = None) -> pd.DataFrame:
        """SELECT → DataFrame on a per-call cursor under the shared lock."""
        with self.reader() as con:
            self._register(con, frames)
            return con.execute(sql, list(params) if params is not None else []).df()

    def read_rows(self, sql: str, params: Sequence[Any] | None = None, *,
                  frames: Mapping[str, pd.DataFrame] | None = None) -> list[tuple]:
        """SELECT → ``fetchall()`` rows under the shared lock."""
        with self.reader() as con:
            self._register(con, frames)
            return con.execute(sql, list(params) if params is not None else []).fetchall()

    def read_one(self, sql: str, params: Sequence[Any] | None = None, *,
                 frames: Mapping[str, pd.DataFrame] | None = None) -> tuple | None:
        """SELECT → ``fetchone()`` (``None`` when empty) under the shared lock."""
        with self.reader() as con:
            self._register(con, frames)
            return con.execute(sql, list(params) if params is not None else []).fetchone()

    def write(self, sql: str, params: Sequence[Any] | None = None, *,
              frames: Mapping[str, pd.DataFrame] | None = None) -> int:
        """One mutating statement on the primary connection under the exclusive lock.

        Returns the statement's row count when DuckDB reports one (INSERT / UPDATE / DELETE), else -1. Frames
        registered for the statement are unregistered afterwards so the primary connection's catalog stays clean.
        """
        with self.writer() as con:
            names = self._register(con, frames)
            try:
                res = con.execute(sql, list(params) if params is not None else [])
                try:
                    row = res.fetchone()
                except Exception:  # noqa: BLE001 — DDL and statements without a result set
                    return -1
                return int(row[0]) if row and isinstance(row[0], (int, np.integer)) else -1
            finally:
                for name in names:
                    try:
                        con.unregister(name)
                    except Exception:  # noqa: BLE001
                        pass

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Checkpoint and close.  Call on service shutdown.  Waits for in-flight readers (exclusive lock)."""
        with self._lock:
            self._closed = True
            try:
                self._conn.execute("CHECKPOINT")
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass

    def _init_schema(self) -> None:
        with self.writer() as con:          # DDL is a write: the exclusive side of the RW lock (check:B1-DATA)
            for statement in DDL.split(";"):
                stmt = statement.strip()
                if stmt:
                    con.execute(stmt)
            # GOLD program (PLAN §c.1): the gold tables live in gold/schema.py; every statement is IF NOT EXISTS /
            # OR REPLACE so a restart creates them. Guarded: a tree without the package still starts.
            try:
                from gold.schema import ddl_statements as _gold_ddl
            except ImportError:
                _gold_ddl = None
            if _gold_ddl is not None:
                for stmt in _gold_ddl():
                    con.execute(stmt)
            # Terminal v2 (PLAN 1.1 / 1.2 / 1.4; builder B1-DATA): the IV store, the index drivers and the data-health tables
            # live in their packages (fo_iv/schema.py, index_drivers/schema.py, data_health/schema.py); every statement is
            # IF NOT EXISTS so a restart creates them. Guarded: a tree without a package still starts.
            for stmt in _terminal_v2_ddl():
                con.execute(stmt)
        logger.info("DuckDB schema initialised", db_path=self._db_path)

    # ── OHLCV ──────────────────────────────────────────────────────────────────

    def upsert_ohlcv(self, df: pd.DataFrame, source: str) -> int:
        """Insert or replace OHLCV rows.  Returns rows written."""
        required = {"ticker", "date", "open", "high", "low", "close", "volume", "adjusted_close"}
        if not required.issubset(df.columns):
            raise ValueError(f"Missing columns: {required - set(df.columns)}")
        df = df.copy()
        df["source"] = source
        df["date"] = pd.to_datetime(df["date"])
        df = _duck_compatible(df)
        with self._lock:
            self._conn.execute("""
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
        self.invalidate_ohlcv_meta_cache()
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
        with self.reader() as con:
            return con.execute(
                f"SELECT * FROM ohlcv WHERE {where} ORDER BY date",
                params,
            ).df()

    def replace_ticker_history(self, ticker: str, df: pd.DataFrame, source: str) -> int:
        """Atomically replace a ticker's full OHLCV history.

        Used when the provider's adjustment basis changed (split/bonus re-adjusts all
        past prices) so old and new rows can never be mixed in one series.
        """
        df = df.copy()
        df["ticker"] = ticker
        df["source"] = source
        df["date"] = pd.to_datetime(df["date"])
        df = _duck_compatible(df)
        with self._lock:
            # DuckDB 1.1 rejects DELETE + re-INSERT of the same primary key inside one
            # transaction, so: drop only dates absent from the new history, then upsert.
            self._conn.execute("BEGIN TRANSACTION")
            try:
                self._conn.execute(
                    "DELETE FROM ohlcv WHERE ticker = ? AND date NOT IN (SELECT date::DATE FROM df)",
                    [ticker],
                )
                self._conn.execute("""
                    INSERT OR REPLACE INTO ohlcv
                        (ticker, date, open, high, low, close, volume, adjusted_close, source)
                    SELECT ticker, date::DATE, open::DOUBLE, high::DOUBLE, low::DOUBLE,
                           close::DOUBLE, volume::BIGINT, adjusted_close::DOUBLE, source
                    FROM df
                """)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        self.invalidate_ohlcv_meta_cache()
        return len(df)

    def get_earliest_ohlcv_date(self, ticker: str) -> date | None:
        with self.reader() as con:
            row = con.execute("SELECT MIN(date) FROM ohlcv WHERE ticker = ?", [ticker]).fetchone()
        return row[0] if row and row[0] else None

    def get_quarantine_summary(self, limit: int = 50) -> dict:
        with self.reader() as con:
            by_reason = con.execute(
                "SELECT reason, COUNT(*) n, COUNT(DISTINCT ticker) t FROM ohlcv_quarantine "
                "GROUP BY 1 ORDER BY 2 DESC").fetchall()
            recent = con.execute(
                "SELECT ticker, date::VARCHAR, close, volume, reason FROM ohlcv_quarantine "
                "ORDER BY created_at DESC, ticker LIMIT ?", [limit]).fetchall()
        return {
            "by_reason": [{"reason": r, "bars": n, "tickers": t} for r, n, t in by_reason],
            "recent": [{"ticker": a, "date": b, "close": c, "volume": v, "reason": r}
                       for a, b, c, v, r in recent],
        }

    def count_non_source_rows(self, ticker: str, source: str) -> int:
        """Rows for ``ticker`` from any provider other than ``source`` (mixed series)."""
        with self.reader() as con:
            return int(con.execute(
                "SELECT COUNT(*) FROM ohlcv WHERE ticker = ? AND source <> ?", [ticker, source]
            ).fetchone()[0])

    def delete_ohlcv_dates(self, ticker: str, dates: list) -> None:
        """Remove specific bars (e.g. ones the quality gate now rejects)."""
        if not dates:
            return
        with self._lock:
            self._conn.executemany(
                "DELETE FROM ohlcv WHERE ticker = ? AND date = ?",
                [[ticker, d] for d in dates],
            )

    def insert_quarantine(self, df: pd.DataFrame, source: str) -> int:
        if df.empty:
            return 0
        df = df.copy()
        df["source"] = source
        df["date"] = pd.to_datetime(df["date"])
        df = _duck_compatible(df)
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO ohlcv_quarantine
                    (ticker, date, open, high, low, close, volume, reason, source)
                SELECT ticker, date::DATE, open, high, low, close, volume::BIGINT, reason, source
                FROM df
            """)
        return len(df)

    def checkpoint(self) -> None:
        """Flush the WAL into the main file so file-copy readers see current data."""
        if self._read_only:
            return
        with self._lock:
            self._conn.execute("CHECKPOINT")

    # ── Instruments / market indices ───────────────────────────────────────────

    def replace_instruments(self, df: pd.DataFrame) -> int:
        df = _duck_compatible(df)
        with self._lock:
            self._conn.execute("BEGIN TRANSACTION")
            try:
                self._conn.execute("DELETE FROM instruments WHERE ticker NOT IN (SELECT ticker FROM df)")
                self._conn.execute("""
                    INSERT OR REPLACE INTO instruments (ticker, instrument_type, ml_eligible, classified_by)
                    SELECT ticker, instrument_type, ml_eligible, classified_by FROM df
                """)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return len(df)

    def get_instruments(self) -> pd.DataFrame:
        with self.reader() as con:
            return con.execute("SELECT * FROM instruments ORDER BY ticker").df()

    def get_ml_eligible_tickers(self) -> list[str]:
        with self.reader() as con:
            rows = con.execute(
                "SELECT ticker FROM instruments WHERE ml_eligible ORDER BY ticker"
            ).fetchall()
        return [r[0] for r in rows]

    def upsert_index_daily(self, symbol: str, df: pd.DataFrame, source: str) -> int:
        if df.empty:
            return 0
        df = df[["date", "close"]].copy()
        df["symbol"] = symbol
        df["source"] = source
        df["date"] = pd.to_datetime(df["date"])
        df = _duck_compatible(df)
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO market_index_daily (symbol, date, close, source)
                SELECT symbol, date::DATE, close::DOUBLE, source FROM df
            """)
        return len(df)

    # ── NSE bhavcopy ───────────────────────────────────────────────────────────

    def upsert_bhavcopy(self, df: pd.DataFrame) -> int:
        """Insert or replace one or more days of parsed bhavcopy rows."""
        if df.empty:
            return 0
        cols = ["symbol", "series", "date", "prev_close", "open", "high", "low", "last", "close",
                "avg_price", "volume", "turnover_lacs", "trades", "deliv_qty", "deliv_pct"]
        bhav = _duck_compatible(df[cols].copy())
        with self._lock:
            self._conn.execute(f"""
                INSERT OR REPLACE INTO nse_bhavcopy ({", ".join(cols)})
                SELECT symbol, series, date::DATE, prev_close, open, high, low, last, close, avg_price,
                       volume::BIGINT, turnover_lacs, trades::BIGINT, deliv_qty::BIGINT, deliv_pct
                FROM bhav
            """)
        return len(bhav)

    def get_bhavcopy_meta(self) -> dict:
        with self.reader() as con:
            row = con.execute("""
                SELECT MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT date), COUNT(DISTINCT symbol),
                       COUNT(DISTINCT symbol) FILTER (WHERE series = 'EQ')
                FROM nse_bhavcopy
            """).fetchone()
        keys = ("first_date", "last_date", "rows", "days", "symbols", "eq_symbols")
        return {k: (str(v) if k.endswith("date") and v is not None else v) for k, v in zip(keys, row, strict=True)}

    # ── NSE positions / filings ("who is holding overnight") ─────────────────────

    def _upsert(self, table: str, df: pd.DataFrame, cols: list[str], casts: dict[str, str] | None = None) -> int:
        if df is None or df.empty:
            return 0
        frame = _duck_compatible(df[cols].copy())
        casts = casts or {}
        select = ", ".join(f"{c}::{casts[c]}" if c in casts else c for c in cols)
        with self._lock:
            self._conn.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) SELECT {select} FROM frame")
        return len(frame)

    def upsert_fo_daily(self, df: pd.DataFrame) -> int:
        cols = ["date", "symbol", "kind", "near_expiry", "fut_close", "fut_settle", "fut_oi", "fut_oi_chg",
                "fut_contracts", "fut_value_lakh", "call_oi", "put_oi", "call_oi_chg", "put_oi_chg",
                "opt_contracts", "opt_value_lakh"]
        return self._upsert("nse_fo_daily", df, cols, {"date": "DATE", "near_expiry": "DATE"})

    def upsert_participant_oi(self, df: pd.DataFrame) -> int:
        from nse_positions import PARTICIPANT_COLS
        return self._upsert("nse_participant_oi", df, ["date", "client_type", *PARTICIPANT_COLS],
                            {"date": "DATE", **{c: "BIGINT" for c in PARTICIPANT_COLS}})

    def upsert_fii_dii_cash(self, df: pd.DataFrame) -> int:
        return self._upsert("nse_fii_dii_cash", df, ["date", "category", "buy_cr", "sell_cr", "net_cr"], {"date": "DATE"})

    def fii_dii_cash(self, days: int = 90) -> list[dict]:
        with self.reader() as con:
            df = con.execute("""SELECT date, category, buy_cr, sell_cr, net_cr FROM nse_fii_dii_cash
                                       WHERE date >= current_date - CAST(? AS INTEGER) ORDER BY date, category""", [days]).df()
        if df.empty:
            return []
        df["date"] = df["date"].astype(str)
        return df.to_dict(orient="records")

    def replace_deals(self, kind: str, start, end, df: pd.DataFrame) -> int:
        """Idempotent per (kind, date range): the deals feed has no natural key."""
        cols = ["date", "kind", "symbol", "security_name", "client_name", "side", "qty", "price", "remarks"]
        with self._lock:
            self._conn.execute("DELETE FROM nse_deals WHERE kind = ? AND date BETWEEN ?::DATE AND ?::DATE",
                               [kind, str(start), str(end)])
            if df is None or df.empty:
                return 0
            frame = _duck_compatible(df[cols].copy())
            self._conn.execute(f"INSERT INTO nse_deals ({', '.join(cols)}) SELECT date::DATE, kind, symbol, security_name, "
                               "client_name, side, qty, price, remarks FROM frame")
        return len(frame)

    def upsert_mtf(self, table: pd.DataFrame, totals: dict) -> int:
        n = self._upsert("nse_mtf", table, ["date", "symbol", "name", "qty_financed", "amount_lakh"], {"date": "DATE"})
        tot = pd.DataFrame([{k: totals.get(k) for k in ("date", "begin_lakh", "fresh_lakh", "liquidated_lakh", "end_lakh")}])
        self._upsert("nse_mtf_market", tot, list(tot.columns), {"date": "DATE"})
        return n

    def upsert_insider_trades(self, df: pd.DataFrame) -> int:
        cols = ["record_id", "symbol", "person", "category", "mode", "txn_type", "qty", "value", "before_pct",
                "after_pct", "from_date", "to_date", "intimation_date", "broadcast_ts"]
        return self._upsert("nse_insider_trades", df, cols,
                            {"from_date": "DATE", "to_date": "DATE", "intimation_date": "DATE"})

    def insider_buys(self, days: int = 60, min_value: float = 1e6) -> list[dict]:
        """Open-market purchases by promoters, directors and KMP (the H4 definition in reports/held_overnight), per
        stock over the last `days`: total value, filings, buyers, and the move since the latest filing's close."""
        with self.reader() as con:
            df = con.execute("""
                WITH buys AS (
                    SELECT symbol, intimation_date AS d, person, category, value FROM nse_insider_trades
                    WHERE mode ILIKE 'market purchase%' AND txn_type ILIKE 'buy%' AND value >= ?
                      AND regexp_matches(lower(coalesce(category, '')), 'promoter|director|kmp|key managerial')
                      AND intimation_date BETWEEN current_date - CAST(? AS INTEGER) AND current_date),
                agg AS (
                    SELECT symbol, MAX(d) AS last_date, MIN(d) AS first_date, SUM(value) AS total_value,
                           COUNT(*) AS trades, COUNT(DISTINCT person) AS buyers,
                           string_agg(DISTINCT category, ', ') AS categories,
                           arg_max(person, value) AS top_buyer
                    FROM buys GROUP BY symbol),
                px AS (SELECT symbol, date, close FROM nse_bhavcopy WHERE series = 'EQ'
                       AND date >= current_date - CAST(? AS INTEGER) - 10),
                last_px AS (SELECT symbol, arg_max(close, date) AS last_close, MAX(date) AS last_px_date FROM px GROUP BY symbol)
                SELECT a.*, l.last_close, l.last_px_date,
                       (SELECT p.close FROM px p WHERE p.symbol = a.symbol AND p.date <= a.last_date ORDER BY p.date DESC LIMIT 1) AS filing_close
                FROM agg a LEFT JOIN last_px l USING (symbol)
                ORDER BY a.last_date DESC, a.total_value DESC""", [min_value, days, days]).df()
        if df.empty:
            return []
        # split-safe: the raw closes above are for display; the move uses adjusted closes
        adj = self.adjusted_closes(df["symbol"].tolist(), str(pd.Timestamp(df["last_date"].min()) - pd.Timedelta(days=10))[:10])
        df["since_filing_pct"] = [self.move_since(adj, sym, d) for sym, d in zip(df["symbol"], df["last_date"], strict=True)]
        for c in ("last_date", "first_date", "last_px_date"):
            df[c] = df[c].astype(str)
        df = df.astype(object).where(df.notna(), None)
        return df.to_dict(orient="records")

    def recent_deals(self, days: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Bulk and block deals of the last `days` (raw rows), plus each dealt stock's EQ bhavcopy over the same span
        (date, close, volume) for the share-of-volume and move-since figures."""
        with self.reader() as con:
            deals = con.execute("""
                SELECT date, kind, symbol, security_name, client_name, upper(side) AS side, qty, price FROM nse_deals
                WHERE kind IN ('bulk', 'block') AND date >= current_date - CAST(? AS INTEGER)""", [days]).df()
            px = con.execute("""
                SELECT symbol, date, close, volume FROM nse_bhavcopy WHERE series = 'EQ'
                  AND date >= current_date - CAST(? AS INTEGER) - 5
                  AND symbol IN (SELECT DISTINCT symbol FROM nse_deals
                                 WHERE kind IN ('bulk', 'block') AND date >= current_date - CAST(? AS INTEGER))""",
                [days, days]).df()
        return deals, px

    def holding_changes(self) -> list[dict]:
        """Each stock's latest shareholding filing vs its previous one: change in promoter, FPI, mutual-fund and retail
        share (percentage points) and in the number of shareholders (the ~320 liquid names covered)."""
        with self.reader() as con:
            df = con.execute("""
                WITH r AS (SELECT *, row_number() OVER (PARTITION BY symbol ORDER BY period_end DESC) AS rn FROM nse_shareholding),
                     a AS (SELECT * FROM r WHERE rn = 1), b AS (SELECT * FROM r WHERE rn = 2)
                SELECT a.symbol, a.period_end, b.period_end AS prev_period, a.broadcast_ts,
                       a.promoter_pct, a.promoter_pct - b.promoter_pct AS d_promoter,
                       a.fpi_pct, a.fpi_pct - b.fpi_pct AS d_fpi, a.mf_pct, a.mf_pct - b.mf_pct AS d_mf,
                       a.retail_pct, a.retail_pct - b.retail_pct AS d_retail,
                       a.total_holders, (a.total_holders / NULLIF(b.total_holders, 0) - 1) * 100 AS d_holders_pct
                FROM a LEFT JOIN b USING (symbol)""").df()
        if df.empty:
            return []
        for c in ("period_end", "prev_period"):
            df[c] = df[c].astype(str).replace({"NaT": None, "None": None})
        return df.astype(object).where(df.notna(), None).to_dict(orient="records")

    def mtf_monitor(self, lookback: int = 20, market_days: int = 250) -> dict[str, Any]:
        """Margin trading (MTF) crowding: the market MTF book over time, and per stock the funded amount, its change
        over `lookback` sessions, and days-to-unwind (funded amount ÷ 20-day average traded value)."""
        with self.reader() as con:
            mkt = con.execute("""SELECT date, begin_lakh, fresh_lakh, liquidated_lakh, end_lakh FROM nse_mtf_market
                                        ORDER BY date DESC LIMIT ?""", [market_days]).df()
            dates = [r[0] for r in con.execute(
                "SELECT DISTINCT date FROM nse_mtf ORDER BY date DESC LIMIT ?", [lookback + 1]).fetchall()]
            if len(dates) < 2:
                return {"market": [], "stocks": [], "as_of": None, "base_date": None}
            d1, d0 = dates[0], dates[-1]
            df = con.execute("""
                WITH now AS (SELECT symbol, name, qty_financed AS qty, amount_lakh FROM nse_mtf WHERE date = ?),
                     base AS (SELECT symbol, qty_financed AS qty0, amount_lakh AS amt0 FROM nse_mtf WHERE date = ?),
                     tv AS (SELECT symbol, AVG(turnover_lacs) AS avg_tv_lakh, arg_max(close, date) AS close
                            FROM nse_bhavcopy WHERE series = 'EQ' AND date > ?::DATE - INTERVAL 35 DAY AND date <= ?
                            GROUP BY symbol)
                SELECT n.symbol, n.name, n.qty, n.amount_lakh, b.qty0, b.amt0, t.avg_tv_lakh, t.close
                FROM now n LEFT JOIN base b USING (symbol) LEFT JOIN tv t USING (symbol)""", [d1, d0, d1, d1]).df()
        df["amount_cr"] = df["amount_lakh"] / 100
        df["qty_chg_pct"] = np.where(df["qty0"] > 0, (df["qty"] / df["qty0"] - 1) * 100, np.nan)
        df["days_to_unwind"] = np.where(df["avg_tv_lakh"] > 0, df["amount_lakh"] / df["avg_tv_lakh"], np.nan)
        df = df.replace([np.inf, -np.inf], np.nan)
        stocks = df[["symbol", "name", "amount_cr", "qty_chg_pct", "days_to_unwind", "close"]].sort_values("amount_cr", ascending=False)
        mkt = mkt.sort_values("date")
        mkt["date"] = mkt["date"].astype(str)
        clean = lambda f: f.astype(object).where(f.notna(), None).to_dict(orient="records")  # noqa: E731
        return {"as_of": str(d1), "base_date": str(d0), "lookback": len(dates) - 1, "market": clean(mkt), "stocks": clean(stocks)}

    def adjusted_closes(self, symbols: list[str], since: str) -> pd.DataFrame:
        """Wide dates × symbols closes adjusted for splits and bonuses (shared.nse_panel.adjust, EQ/BE/BZ rows) from
        `since`. Use for any "move since" figure: our bhavcopy's prices and prev_close are not adjusted."""
        from shared.nse_panel import adjust, pick_equity_rows
        if not symbols:
            return pd.DataFrame()
        frame = _duck_compatible(pd.DataFrame({"symbol": list(dict.fromkeys(symbols))}))  # noqa: F841 — DuckDB replacement scan reads it
        with self.reader() as con:
            raw = con.execute("SELECT * FROM nse_bhavcopy WHERE date >= ?::DATE AND symbol IN (SELECT symbol FROM frame)",
                                     [since]).df()
            splits = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0").df()
        if raw.empty:
            return pd.DataFrame()
        raw["date"] = pd.to_datetime(raw["date"])
        splits["date"] = pd.to_datetime(splits["date"]).dt.tz_localize(None).dt.normalize()
        long = adjust(pick_equity_rows(raw), splits)
        return long.pivot(index="date", columns="symbol", values="adj_close").sort_index()

    @staticmethod
    def move_since(closes: pd.DataFrame, symbol: str, day: Any) -> float | None:
        """% move from the close on (or before) `day` to the latest close, on adjusted closes."""
        if closes is None or closes.empty or symbol not in closes.columns:
            return None
        c = closes[symbol].dropna()
        base = c[c.index <= pd.Timestamp(day)]
        if base.empty or c.empty:
            return None
        return float((c.iloc[-1] / base.iloc[-1] - 1) * 100)

    def basket_returns(self, symbols: list[str], days: int = 365) -> tuple[pd.DataFrame, pd.Series]:
        """Daily returns of `symbols` (dates × symbols) from corporate-action-adjusted closes, and NIFTY 50 daily
        returns, over the last `days` calendar days. NSE's prev_close is NOT adjusted in our bhavcopy (a 1:5 split
        shows as −80%), so the adjustment is shared.nse_panel.adjust: the same code the Decision Desk ranks on."""
        from shared.nse_panel import adjust, pick_equity_rows
        frame = _duck_compatible(pd.DataFrame({"symbol": symbols}))  # noqa: F841 — DuckDB replacement scan reads it
        with self.reader() as con:
            raw = con.execute("""
                SELECT * FROM nse_bhavcopy WHERE date >= current_date - CAST(? AS INTEGER) - 7
                  AND symbol IN (SELECT symbol FROM frame)""", [days]).df()
            splits = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0").df()
            nifty = con.execute("""
                SELECT date, close FROM market_index_daily WHERE symbol = 'NIFTY50'
                  AND date >= current_date - CAST(? AS INTEGER) - 10 ORDER BY date""", [days]).df()
        n = nifty.assign(date=pd.to_datetime(nifty["date"])).set_index("date")["close"].pct_change().dropna()
        if raw.empty:
            return pd.DataFrame(), n
        raw["date"] = pd.to_datetime(raw["date"])
        splits["date"] = pd.to_datetime(splits["date"]).dt.tz_localize(None).dt.normalize()
        long = adjust(pick_equity_rows(raw), splits)
        close = long.pivot(index="date", columns="symbol", values="adj_close").sort_index()
        rets = close.pct_change(fill_method=None)
        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        return rets[rets.index >= cutoff], n

    def listing_paths(self, symbols: list[str], since: str) -> pd.DataFrame:
        """Daily raw open / close of newly listed stocks from `since` (any trading series: new listings often start in
        BE, SME stocks trade as SM / ST; EQ preferred), plus `adj_close` adjusted for later splits and bonuses
        (shared.nse_panel.adjust), so returns after listing are not broken by a corporate action."""
        from shared.nse_panel import adjust
        if not symbols:
            return pd.DataFrame(columns=["symbol", "date", "open", "close", "adj_close"])
        frame = _duck_compatible(pd.DataFrame({"symbol": symbols}))  # noqa: F841 — DuckDB replacement scan reads it
        with self.reader() as con:
            raw = con.execute("""
                SELECT * FROM nse_bhavcopy WHERE series IN ('EQ', 'BE', 'BZ', 'SM', 'ST') AND date >= ?::DATE
                  AND symbol IN (SELECT symbol FROM frame)""", [since]).df()
            splits = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0").df()
        if raw.empty:
            return pd.DataFrame(columns=["symbol", "date", "open", "close", "adj_close"])
        raw["date"] = pd.to_datetime(raw["date"])
        raw["_rank"] = raw["series"].map({"EQ": 0, "BE": 1, "BZ": 2, "SM": 3, "ST": 4})
        one = raw.sort_values(["symbol", "date", "_rank"]).drop_duplicates(["symbol", "date"]).drop(columns="_rank")
        splits["date"] = pd.to_datetime(splits["date"]).dt.tz_localize(None).dt.normalize()
        adj = adjust(one, splits)
        return adj[["symbol", "date", "open", "close", "adj_close"]].reset_index(drop=True)

    def known_pit_gg_apps(self) -> set[str]:
        """appIds of single-filing PIT filings already parsed (record_id = 'gg|<appId>|<context>')."""
        with self.reader() as con:
            rows = con.execute(
                "SELECT DISTINCT split_part(record_id, '|', 2) FROM nse_insider_trades WHERE record_id LIKE 'gg|%'").fetchall()
        return {r[0] for r in rows}

    def fix_future_insider_dates(self) -> int:
        """NSE typos put some intimation dates in the future (e.g. 2028) or the distant past (e.g. 1925, before SEBI's
        PIT rules existed): use the broadcast date instead."""
        bad = ("(intimation_date > current_date OR intimation_date < DATE '2000-01-01') "
               "AND try_strptime(broadcast_ts, '%d-%b-%Y %H:%M') IS NOT NULL")
        with self._lock:
            n = self._conn.execute(f"SELECT COUNT(*) FROM nse_insider_trades WHERE {bad}").fetchone()[0]
            if n:
                self._conn.execute(f"""UPDATE nse_insider_trades
                    SET intimation_date = CAST(try_strptime(broadcast_ts, '%d-%b-%Y %H:%M') AS DATE) WHERE {bad}""")
            # rows parsed before the XBRL entity fix: "&amp;" → "&"
            self._conn.execute("""UPDATE nse_insider_trades
                SET person = replace(replace(person, '&amp;', '&'), '&apos;', chr(39)),
                    category = replace(category, '&amp;', '&')
                WHERE record_id LIKE 'gg|%' AND (person LIKE '%&amp;%' OR person LIKE '%&apos;%' OR category LIKE '%&amp;%')""")
        return int(n)

    def upsert_shareholding(self, df: pd.DataFrame) -> int:
        cols = ["symbol", "period_end", "broadcast_ts", "promoter_pct", "public_pct", "total_holders", "retail_holders",
                "retail_pct", "hni_holders", "fpi_holders", "fpi_pct", "mf_holders", "mf_pct", "xbrl_url"]
        return self._upsert("nse_shareholding", df, cols, {"period_end": "DATE"})

    def shareholding_missing_categories(self) -> list[dict]:
        """Filings with an XBRL link but no FPI/MF split (parsed before the old-layout fix). NSE lists
        `…/xbrl/-` when a filing has no XBRL."""
        with self.reader() as con:
            df = con.execute("""
                SELECT symbol, CAST(period_end AS VARCHAR) AS period_end, broadcast_ts, promoter_pct, public_pct, xbrl_url
                FROM nse_shareholding
                WHERE xbrl_url IS NOT NULL AND xbrl_url NOT LIKE '%/-' AND (fpi_pct IS NULL OR mf_pct IS NULL)
            """).df()
        return df.to_dict("records")

    def known_shareholding_filings(self) -> set[tuple[str, str, str]]:
        with self.reader() as con:
            rows = con.execute("SELECT symbol, CAST(period_end AS VARCHAR), broadcast_ts FROM nse_shareholding").fetchall()
        return {(a, b, c) for a, b, c in rows}

    def last_date(self, table: str) -> str | None:
        allowed = {"nse_fo_daily", "nse_participant_oi", "nse_deals", "nse_mtf", "nse_bhavcopy"}
        if table not in allowed:
            raise ValueError(table)
        with self.reader() as con:
            v = con.execute(f"SELECT MAX(date) FROM {table}").fetchone()[0]
        return str(v) if v is not None else None

    def upsert_nse_events(self, df: pd.DataFrame) -> int:
        """Insert or refresh events; `first_seen` keeps the first time an event was observed (point-in-time)."""
        if df is None or df.empty:
            return 0
        cols = ["symbol", "event_date", "kind", "source", "tags", "company", "purpose", "detail", "record_date",
                "announced_at", "url"]
        frame = _duck_compatible(df[cols].copy())
        with self._lock:
            self._conn.execute(f"""
                INSERT INTO nse_events ({', '.join(cols)}, first_seen)
                SELECT symbol, event_date::DATE, kind, source, tags, company, purpose, detail, record_date::DATE,
                       announced_at, url, now()::TIMESTAMP FROM frame
                ON CONFLICT (symbol, event_date, kind, source) DO UPDATE SET
                    tags = excluded.tags, company = excluded.company, purpose = excluded.purpose,
                    detail = excluded.detail, record_date = excluded.record_date,
                    announced_at = excluded.announced_at, url = excluded.url
            """)
        return len(frame)

    def get_nse_events(self, start: str, end: str) -> list[dict]:
        """Events in [start, end] with the latest close and 20-session median turnover (₹ cr) for sizing."""
        with self.reader() as con:
            df = con.execute("""
                WITH last AS (SELECT MAX(date) AS d FROM nse_bhavcopy),
                recent AS (SELECT DISTINCT date FROM nse_bhavcopy ORDER BY date DESC LIMIT 20),
                liq AS (
                    SELECT symbol, MEDIAN(turnover_lacs) / 100 AS turnover_cr FROM nse_bhavcopy
                    WHERE series = 'EQ' AND date IN (SELECT date FROM recent) GROUP BY symbol),
                px AS (
                    SELECT symbol, close FROM nse_bhavcopy
                    WHERE series = 'EQ' AND date = (SELECT d FROM last))
                SELECT e.symbol, CAST(e.event_date AS VARCHAR) AS event_date, e.kind, e.source, e.tags, e.company,
                       e.purpose, e.detail, CAST(e.record_date AS VARCHAR) AS record_date, e.announced_at, e.url,
                       CAST(e.first_seen AS VARCHAR) AS first_seen, liq.turnover_cr, px.close
                FROM nse_events e LEFT JOIN liq USING (symbol) LEFT JOIN px USING (symbol)
                WHERE e.event_date BETWEEN ?::DATE AND ?::DATE
                ORDER BY e.event_date, liq.turnover_cr DESC NULLS LAST, e.symbol
            """, [start, end]).fetchdf()
        df = df.astype(object).where(df.notna(), None)
        return df.to_dict(orient="records")

    def results_fetched_at(self, symbol: str):
        with self.reader() as con:
            row = con.execute("SELECT MAX(fetched_at) FROM nse_results WHERE symbol = ?", [symbol]).fetchone()
        return row[0] if row else None

    def upsert_results(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        frame = _duck_compatible(df[["symbol", "period_end", "released_at"]].copy())
        with self._lock:
            self._conn.execute("""
                INSERT INTO nse_results (symbol, period_end, released_at, fetched_at)
                SELECT symbol, period_end::DATE, released_at::TIMESTAMP, now()::TIMESTAMP FROM frame
                ON CONFLICT (symbol, period_end) DO UPDATE SET
                    released_at = LEAST(nse_results.released_at, excluded.released_at), fetched_at = excluded.fetched_at
            """)
        return len(frame)

    def get_results(self, symbol: str) -> pd.DataFrame:
        with self.reader() as con:
            return con.execute(
                "SELECT symbol, period_end, released_at FROM nse_results WHERE symbol = ? ORDER BY released_at",
                [symbol]).df()

    def get_positions_meta(self) -> dict:
        out = {}
        specs = {"nse_fo_daily": "date", "nse_participant_oi": "date", "nse_deals": "date", "nse_mtf": "date",
                 "nse_insider_trades": "intimation_date", "nse_shareholding": "period_end",
                 "nse_bhavcopy": "date", "nse_events": "event_date", "nse_results": "released_at",
                 "nse_fii_dii_cash": "date"}
        with self.reader() as con:
            for table, col in specs.items():
                lo, hi, n = con.execute(f"SELECT MIN({col}), MAX({col}), COUNT(*) FROM {table}").fetchone()
                out[table] = {"first": str(lo) if lo else None, "last": str(hi) if hi else None, "rows": n}
        # GOLD program (PLAN §c.3 freshness): gold_series, gold_cot, gold_curve, … rows for the WHSE panel and the
        # 08:30 pre_market_sync alert; additive and guarded (missing package or tables → no rows, never an error).
        try:
            from gold.schema import positions_meta as _gold_meta
            out.update(_gold_meta(self))
        except Exception:  # noqa: BLE001 — never let the gold layer break the NSE freshness rows
            pass
        out.update(_terminal_v2_positions_meta(self))   # Terminal v2 tables (fo_iv, index_drivers, data_health), additive and guarded
        return out

    def get_historical_liquid_symbols(self, n: int = 300, first_year: int = 2014, last_year: int = 2025) -> list[str]:
        """Union over years of the n most traded EQ symbols (median turnover in that calendar year), so a study
        built on them is not limited to today's survivors."""
        with self.reader() as con:
            rows = con.execute("""
                WITH y AS (
                    SELECT symbol, YEAR(date) AS yr, MEDIAN(turnover_lacs) AS med FROM nse_bhavcopy
                    WHERE series = 'EQ' AND YEAR(date) BETWEEN ? AND ? GROUP BY symbol, YEAR(date)),
                r AS (SELECT symbol, yr, ROW_NUMBER() OVER (PARTITION BY yr ORDER BY med DESC) AS rk FROM y)
                SELECT DISTINCT symbol FROM r WHERE rk <= ? ORDER BY symbol
            """, [first_year, last_year, n]).fetchall()
        return [r[0] for r in rows]

    def get_liquid_symbols(self, n: int = 300, days: int = 60) -> list[str]:
        """Most-traded EQ symbols by median turnover over the last `days` sessions (bhavcopy)."""
        with self.reader() as con:
            rows = con.execute("""
                WITH recent AS (SELECT DISTINCT date FROM nse_bhavcopy ORDER BY date DESC LIMIT ?)
                SELECT symbol FROM nse_bhavcopy
                WHERE series = 'EQ' AND date IN (SELECT date FROM recent)
                GROUP BY symbol ORDER BY MEDIAN(turnover_lacs) DESC LIMIT ?
            """, [days, n]).fetchall()
        return [r[0] for r in rows]

    def get_index_daily(self, symbol: str) -> pd.DataFrame:
        with self.reader() as con:
            return con.execute(
                "SELECT date, close FROM market_index_daily WHERE symbol = ? ORDER BY date",
                [symbol],
            ).df()

    def get_ohlcv_for_tickers(self, tickers: list[str]) -> pd.DataFrame:
        """Full OHLCV history for a ticker list in one scan (ML dataset build)."""
        if not tickers:
            return pd.DataFrame()
        tdf = _duck_compatible(pd.DataFrame({"ticker": tickers}))  # noqa: F841 — DuckDB replacement scan reads it
        with self.reader() as con:
            return con.execute("""
                SELECT o.ticker, o.date, o.open, o.high, o.low, o.close, o.volume, o.adjusted_close
                FROM ohlcv o JOIN tdf USING (ticker)
                ORDER BY o.ticker, o.date
            """).df()

    def replace_ml_dataset(self, features: pd.DataFrame, labels: pd.DataFrame) -> tuple[int, int]:
        """Swap ml_features + ml_labels in ONE transaction.

        Readers never observe an empty or half-written feature store: either the old
        dataset or the new one is visible, and a failed insert rolls everything back.
        """
        features = _duck_compatible(features)
        labels = _duck_compatible(labels)
        with self._lock:
            feat_table_cols = [r[0] for r in self._conn.execute("DESCRIBE ml_features").fetchall()]
            lbl_table_cols = [r[0] for r in self._conn.execute("DESCRIBE ml_labels").fetchall()]
            # Every table column is written (NULL when the build doesn't produce it) so an
            # upserted row can never keep a stale value from a previous build.
            def _cols(table_cols: list[str], df: pd.DataFrame) -> tuple[str, str]:
                cols = [c for c in table_cols if c != "created_at"]
                sel = ", ".join(f'"{c}"' if c in df.columns else f'NULL AS "{c}"' for c in cols)
                return ", ".join(f'"{c}"' for c in cols), sel

            fcols, fsel = _cols(feat_table_cols, features)
            lcols, lsel = _cols(lbl_table_cols, labels)
            # DuckDB 1.1 cannot DELETE + re-INSERT the same key in one transaction:
            # delete rows absent from the new build, then upsert everything.
            # Explicitly registered views: the schema has legacy tables literally named
            # "features" / "labels", which DuckDB would bind in preference to same-named
            # Python variables — silently copying from the (empty) legacy tables.
            self._conn.register("_new_ml_features", features)
            self._conn.register("_new_ml_labels", labels)
            self._conn.execute("BEGIN TRANSACTION")
            try:
                self._conn.execute("""
                    DELETE FROM ml_features f WHERE NOT EXISTS (
                        SELECT 1 FROM _new_ml_features n
                        WHERE n.ticker = f.ticker AND n.date::DATE = f.date)
                """)
                self._conn.execute(
                    f"INSERT OR REPLACE INTO ml_features ({fcols}) SELECT {fsel} FROM _new_ml_features")
                self._conn.execute("""
                    DELETE FROM ml_labels l WHERE NOT EXISTS (
                        SELECT 1 FROM _new_ml_labels n
                        WHERE n.ticker = l.ticker AND n.date::DATE = l.date
                          AND n.horizon_days = l.horizon_days)
                """)
                self._conn.execute(
                    f"INSERT OR REPLACE INTO ml_labels ({lcols}) SELECT {lsel} FROM _new_ml_labels")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            finally:
                self._conn.unregister("_new_ml_features")
                self._conn.unregister("_new_ml_labels")
        return len(features), len(labels)

    def get_latest_ohlcv_date(self, ticker: str) -> date | None:
        with self.reader() as con:
            result = con.execute(
                "SELECT MAX(date) FROM ohlcv WHERE ticker = ?", [ticker]
            ).fetchone()
        return result[0] if result and result[0] else None

    # ── Fundamentals ───────────────────────────────────────────────────────────

    def upsert_fundamentals(self, df: pd.DataFrame) -> int:
        df = df.copy()
        df["as_of_date"] = pd.to_datetime(df["as_of_date"])
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO fundamentals SELECT * FROM df")
        return len(df)

    def get_fundamentals(self, tickers: list[str] | None = None) -> pd.DataFrame:
        with self.reader() as con:
            if tickers:
                placeholders = ",".join(["?" * len(tickers)])
                return con.execute(
                    f"SELECT * FROM fundamentals WHERE ticker IN ({placeholders}) "
                    "QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY as_of_date DESC) = 1",
                    tickers,
                ).df()
            return con.execute(
                "SELECT * FROM fundamentals "
                "QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY as_of_date DESC) = 1"
            ).df()

    # ── Stock Metrics ──────────────────────────────────────────────────────────

    def upsert_stock_metrics(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        df = pd.DataFrame(rows)
        df["as_of_date"] = pd.to_datetime(df["as_of_date"])
        cols = ["ticker", "as_of_date", "cmp", "pe_ratio", "mktcap_cr", "div_yld_pct",
                "np_qtr_cr", "qtr_pft_var", "sales_qtr_cr", "qtr_sal_var", "roce_pct"]
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols]
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO stock_metrics SELECT * FROM df")
        return len(df)

    # ── Dividends ──────────────────────────────────────────────────────────────

    def upsert_dividends(self, df: pd.DataFrame) -> int:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO dividends SELECT * FROM df")
        return len(df)

    # ── Splits ─────────────────────────────────────────────────────────────────

    def upsert_splits(self, df: pd.DataFrame) -> int:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO splits SELECT * FROM df")
        return len(df)

    # ── Corporate events ───────────────────────────────────────────────────────

    def upsert_corporate_events(self, df: pd.DataFrame) -> int:
        df = df.copy()
        df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO corporate_events SELECT * FROM df")
        return len(df)

    def get_db_stats(self) -> dict:
        tables = ["ohlcv", "fundamentals", "dividends", "splits", "corporate_events"]
        stats = {}
        with self.reader() as con:
            for t in tables:
                try:
                    row = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
                    stats[t] = row[0] if row else 0
                except Exception:
                    stats[t] = 0
            try:
                stats["ohlcv_tickers"] = con.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM ohlcv"
                ).fetchone()[0]
                stats["ohlcv_date_range"] = con.execute(
                    "SELECT MIN(date), MAX(date) FROM ohlcv"
                ).fetchone()
            except Exception:
                pass
        return stats

    # ── Live quotes ────────────────────────────────────────────────────────────

    def upsert_live_quote(self, symbol: str, ts, payload: str) -> int:
        """Append a live-quote tick to live_quotes (unbounded, ring-buffer via pruning)."""
        df = pd.DataFrame([{
            "symbol": symbol,
            "ts": pd.to_datetime(ts, unit="s" if isinstance(ts, (int, float)) else None),
            "payload": str(payload),
        }])
        for col in df.select_dtypes(include=["string"]).columns:
            df[col] = df[col].astype(object)
        with self._lock:
            self._conn.execute(
                "INSERT INTO live_quotes (symbol, ts, payload) SELECT symbol, ts, payload FROM df"
            )
            # Keep only the last 10 000 rows to prevent unbounded growth
            self._conn.execute("""
                DELETE FROM live_quotes
                WHERE rowid NOT IN (
                    SELECT rowid FROM live_quotes ORDER BY ts DESC LIMIT 10000
                )
            """)
        return 1

    def get_latest_live_quotes(self, limit: int = 100) -> list[dict]:
        with self.reader() as con:
            try:
                rows = con.execute(
                    "SELECT symbol, ts, payload, created_at "
                    "FROM live_quotes ORDER BY ts DESC LIMIT ?",
                    [limit],
                ).fetchall()
            except Exception:
                return []
        return [
            {"symbol": r[0], "ts": str(r[1]), "payload": r[2], "created_at": str(r[3])}
            for r in rows
        ]

    # ── Dashboard stats (for ui-api HTTP proxy) ────────────────────────────────

    def get_dashboard_stats(self) -> dict:
        """
        Aggregate stats consumed by ui-api's /dashboard/summary.
        ui-api cannot open a concurrent DuckDB RO connection on virtioFS
        (Docker Desktop Mac), so this endpoint bridges the gap.
        """
        from datetime import date as _date

        with self.reader() as con:
            try:
                total_stocks = con.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM ohlcv"
                ).fetchone()[0]
            except Exception:
                total_stocks = 0

            if total_stocks == 0:
                return {"total_stocks": 0, "freshness": {}, "enrichment": {}, "data_range": {}}

            try:
                latest_date, min_date = con.execute(
                    "SELECT MAX(date), MIN(date) FROM ohlcv"
                ).fetchone()
            except Exception:
                latest_date, min_date = None, None

            try:
                # Staleness in TRADING SESSIONS behind the latest session in the DB, not
                # calendar days: on weekends/holidays a stock updated at the last close is fresh.
                freshness_rows = con.execute("""
                    WITH sessions AS (
                        SELECT date, ROW_NUMBER() OVER (ORDER BY date DESC) - 1 AS behind
                        FROM (SELECT DISTINCT date FROM ohlcv)
                    ), last AS (SELECT ticker, MAX(date) AS d FROM ohlcv GROUP BY ticker)
                    SELECT s.behind FROM last JOIN sessions s ON s.date = last.d
                """).fetchall()
                fresh      = sum(1 for r in freshness_rows if r[0] is not None and r[0] == 0)
                stale      = sum(1 for r in freshness_rows if r[0] is not None and 1 <= r[0] <= 5)
                very_stale = sum(1 for r in freshness_rows if r[0] is not None and r[0] > 5)
            except Exception:
                fresh = stale = very_stale = 0

            try:
                enriched_count = con.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM stock_metrics"
                ).fetchone()[0]
            except Exception:
                enriched_count = 0

            try:
                with_fund = con.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM fundamentals"
                ).fetchone()[0]
                with_div  = con.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM dividends"
                ).fetchone()[0]
                with_split = con.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM splits"
                ).fetchone()[0]
            except Exception:
                with_fund = with_div = with_split = 0

        today = _date.today()  # noqa: DTZ011 — a local calendar date, like the bars
        days_stale_max = (today - latest_date).days if latest_date else None
        sessions_missed = missed_weekday_sessions(latest_date, today) if latest_date else None
        fresh_pct = round(fresh / total_stocks * 100, 1) if total_stocks else 0
        enrichment_pct = round(enriched_count / total_stocks * 100, 1) if total_stocks else 0

        return {
            "total_stocks": total_stocks,
            "latest_date":  str(latest_date) if latest_date else None,
            "days_stale":   days_stale_max,
            "sessions_missed": sessions_missed,
            "data_range": {
                "from": str(min_date) if min_date else None,
                "to":   str(latest_date) if latest_date else None,
            },
            "freshness": {
                "fresh":      fresh,
                "stale":      stale,
                "very_stale": very_stale,
                "fresh_pct":  fresh_pct,
            },
            "enrichment": {
                "enriched":        enriched_count,
                "total":           total_stocks,
                "enrichment_pct":  enrichment_pct,
                "with_fundamentals": with_fund,
                "with_dividends":    with_div,
                "with_splits":       with_split,
            },
            "health": {
                "status": (
                    "empty"   if total_stocks == 0 else
                    # Weekends/holidays are not staleness: count missed weekday sessions.
                    "healthy" if sessions_missed is not None and sessions_missed == 0 else
                    "warning" if sessions_missed is not None and sessions_missed <= 2 else
                    "stale"
                ),
                "freshness_pct": fresh_pct,
            },
        }

    def invalidate_ohlcv_meta_cache(self) -> None:
        global _OHLCV_META_CACHE, _OHLCV_META_TS
        _OHLCV_META_CACHE = None
        _OHLCV_META_TS = 0.0

    def get_ohlcv_meta_all(self) -> list[dict]:
        """
        Per-ticker OHLCV stats consumed by ui-api's /stocks/list.
        Results cached for 5 minutes — the full scan takes ~60s on 1M+ rows.
        """
        global _OHLCV_META_CACHE, _OHLCV_META_TS
        if _OHLCV_META_CACHE is not None and (time.time() - _OHLCV_META_TS) < _OHLCV_META_TTL:
            return _OHLCV_META_CACHE

        with self.reader() as con:
            try:
                rows = con.execute("""
                    WITH stock_stats AS (
                        SELECT
                            ticker,
                            COUNT(*)                                                   AS total_rows,
                            MIN(date)                                                  AS first_date,
                            MAX(date)                                                  AS latest_date,
                            CAST((MAX(date) - MIN(date)) / 365.25 AS INT)             AS years_of_data,
                            ROUND(100.0 * COUNT(*) / GREATEST(
                                CAST(((MAX(date) - MIN(date)) * 252) / 365 AS INT),
                                COUNT(*)
                            ), 1)                                                      AS data_density_pct
                        FROM ohlcv
                        WHERE ticker NOT LIKE '^%'
                        GROUP BY ticker
                    ),
                    latest_price AS (
                        SELECT ticker, close AS latest_price, date AS price_date
                        FROM ohlcv
                        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
                    ),
                    sessions AS (
                        SELECT date, ROW_NUMBER() OVER (ORDER BY date DESC) - 1 AS behind
                        FROM (SELECT DISTINCT date FROM ohlcv WHERE ticker NOT LIKE '^%')
                    ),
                    stock_metrics_latest AS (
                        SELECT ticker, cmp, pe_ratio, mktcap_cr, div_yld_pct,
                               np_qtr_cr, qtr_pft_var, sales_qtr_cr, qtr_sal_var, roce_pct
                        FROM stock_metrics
                        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY as_of_date DESC) = 1
                    )
                    SELECT
                        s.ticker,
                        p.latest_price,
                        p.price_date::VARCHAR,
                        s.total_rows,
                        s.first_date::VARCHAR,
                        s.latest_date::VARCHAR,
                        s.years_of_data,
                        s.data_density_pct,
                        CAST((CURRENT_DATE - s.latest_date) AS INT) AS days_since_update,
                        m.cmp,        m.pe_ratio,    m.mktcap_cr,  m.div_yld_pct,
                        m.np_qtr_cr,  m.qtr_pft_var, m.sales_qtr_cr, m.qtr_sal_var, m.roce_pct,
                        ss.behind AS sessions_behind
                    FROM stock_stats s
                    JOIN latest_price p ON s.ticker = p.ticker
                    LEFT JOIN stock_metrics_latest m ON s.ticker = m.ticker
                    LEFT JOIN sessions ss ON ss.date = s.latest_date
                    ORDER BY s.ticker
                """).fetchall()
            except Exception:
                return []

        def _f(v): return float(v) if v is not None else None
        def _s(v): return str(v) if v else None

        result = []
        for r in rows:
            result.append({
                "ticker":            r[0],
                "latest_price":      _f(r[1]),
                "price_date":        _s(r[2]),
                "total_rows":        int(r[3]),
                "first_date":        _s(r[4]),
                "latest_date":       _s(r[5]),
                "years_of_data":     int(r[6]) if r[6] is not None else 0,
                "data_density_pct":  _f(r[7]) or 0.0,
                "days_since_update": int(r[8]) if r[8] is not None else None,
                # trading sessions behind the newest session in the DB (0 = current)
                "sessions_behind":   int(r[18]) if r[18] is not None else None,
                # metrics (may be null for unenriched tickers)
                "cmp":               _f(r[9]),
                "pe_ratio":          _f(r[10]),
                "mktcap_cr":         _f(r[11]),
                "div_yld_pct":       _f(r[12]),
                "np_qtr_cr":         _f(r[13]),
                "qtr_pft_var":       _f(r[14]),
                "sales_qtr_cr":      _f(r[15]),
                "qtr_sal_var":       _f(r[16]),
                "roce_pct":          _f(r[17]),
            })
        _OHLCV_META_CACHE = result
        _OHLCV_META_TS = time.time()
        return result

    def run_screener(
        self,
        filters: dict[str, bool],
        skip: int = 0,
        limit: int = 50,
    ) -> dict:
        """
        Minervini TREND TEMPLATE screener (T1-T8) + SEPA stage.
        filters: dict with boolean keys t1..t8.
        """
        _SCREENER_SQL = """
        WITH recent_ohlcv AS (
            SELECT ticker, date, close
            FROM ohlcv
            WHERE ticker != 'NIFTY500'
              -- ETFs / liquid funds / placeholders are not stocks: keep them out of
              -- the trend template. Falls back to all tickers if instruments is empty.
              AND (NOT EXISTS (SELECT 1 FROM instruments)
                   OR ticker IN (SELECT ticker FROM instruments WHERE ml_eligible))
            QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) <= 260
        ),
        stock_ma AS (
            SELECT
                ticker, date, close,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)  as ma50,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW) as ma150,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) as ma200,
                MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) as high52w,
                MIN(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) as low52w,
                LAG(close, 63)  OVER (PARTITION BY ticker ORDER BY date) as close_3m_ago,
                LAG(close, 126) OVER (PARTITION BY ticker ORDER BY date) as close_6m_ago,
                LAG(close, 189) OVER (PARTITION BY ticker ORDER BY date) as close_9m_ago,
                LAG(close, 252) OVER (PARTITION BY ticker ORDER BY date) as close_12m_ago,
                ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
            FROM recent_ohlcv
        ),
        stock_with_history AS (
            SELECT *, LAG(ma200, 30) OVER (PARTITION BY ticker ORDER BY date) as ma200_1m_ago
            FROM stock_ma
        ),
        latest_stats AS (
            SELECT
                ticker, date, close, ma50, ma150, ma200, high52w, low52w,
                close_3m_ago, close_6m_ago, close_9m_ago, close_12m_ago,
                ma200_1m_ago,
                (close > ma150 AND close > ma200)                         as t1_pass,
                (ma150 > ma200)                                           as t2_pass,
                (ma200 > COALESCE(ma200_1m_ago, ma200))                  as t3_pass,
                (ma50 > ma150 AND ma50 > ma200)                          as t4_pass,
                (close > ma50)                                            as t5_pass,
                (close >= low52w * 1.30)                                  as t6_pass,
                (close >= high52w * 0.75)                                 as t7_pass,
                (CASE
                    WHEN (close > ma50) AND (ma50 > ma150) AND (ma150 > ma200) THEN 'Stage 3: Uptrend'
                    WHEN (close > ma200) AND (ma150 > ma200) AND (ma50 < ma150) THEN 'Stage 2: Breakout'
                    WHEN (close < ma200) OR (ma150 < ma200)                    THEN 'Stage 4: Decline'
                    ELSE 'Stage 1: Base'
                END) as sepa_stage
            FROM stock_with_history WHERE rn = 1
        ),
        rs_scores AS (
            SELECT ticker,
                (0.4 * COALESCE((close - close_3m_ago)  / NULLIF(close_3m_ago,  0), 0)
               + 0.2 * COALESCE((close - close_6m_ago)  / NULLIF(close_6m_ago,  0), 0)
               + 0.2 * COALESCE((close - close_9m_ago)  / NULLIF(close_9m_ago,  0), 0)
               + 0.2 * COALESCE((close - close_12m_ago) / NULLIF(close_12m_ago, 0), 0)) as composite_rs
            FROM latest_stats
        ),
        rs_ranked AS (
            SELECT ticker,
                GREATEST(1, LEAST(99, CAST(PERCENT_RANK() OVER (ORDER BY composite_rs) * 98 + 1 AS INTEGER))) as rs_rating
            FROM rs_scores
        )
        SELECT
            s.ticker, s.close, s.date,
            s.ma50, s.ma150, s.ma200, s.high52w, s.low52w,
            COALESCE(r.rs_rating, 50) as rs_rating,
            COALESCE(s.t1_pass, FALSE) as t1,
            COALESCE(s.t2_pass, FALSE) as t2,
            COALESCE(s.t3_pass, FALSE) as t3,
            COALESCE(s.t4_pass, FALSE) as t4,
            COALESCE(s.t5_pass, FALSE) as t5,
            COALESCE(s.t6_pass, FALSE) as t6,
            COALESCE(s.t7_pass, FALSE) as t7,
            (COALESCE(r.rs_rating, 0) >= 70) as t8,
            s.sepa_stage
        FROM latest_stats s
        LEFT JOIN rs_ranked r ON s.ticker = r.ticker
        """
        active = [k for k, v in filters.items() if v and k in ("t1","t2","t3","t4","t5","t6","t7","t8")]
        where = f" WHERE {' AND '.join(f'{f} = true' for f in active)}" if active else ""

        with self.reader() as con:
            try:
                total = con.execute(
                    f"SELECT COUNT(*) FROM ({_SCREENER_SQL}) screened{where}"
                ).fetchone()[0]
                rows = con.execute(
                    f"SELECT * FROM ({_SCREENER_SQL}) screened{where} ORDER BY ticker LIMIT {limit} OFFSET {skip}"
                ).fetchall()
            except Exception:
                return {"total": 0, "skip": skip, "limit": limit, "results": []}

        def _f(v): return float(v) if v is not None else None

        results = [
            {
                "ticker":       r[0],
                "latest_price": _f(r[1]),
                "price_date":   str(r[2]) if r[2] else None,
                "ma50":         _f(r[3]),
                "ma150":        _f(r[4]),
                "ma200":        _f(r[5]),
                "high52w":      _f(r[6]),
                "low52w":       _f(r[7]),
                "rs_rating":    int(r[8]),
                "filters": {
                    "t1": bool(r[9]),  "t2": bool(r[10]),
                    "t3": bool(r[11]), "t4": bool(r[12]),
                    "t5": bool(r[13]), "t6": bool(r[14]),
                    "t7": bool(r[15]), "t8": bool(r[16]),
                },
                "sepa_stage": r[17],
            }
            for r in rows
        ]
        return {"total": total, "skip": skip, "limit": limit, "results": results}

    # ── Signals ────────────────────────────────────────────────────────────────

    def insert_signals(self, df: pd.DataFrame) -> int:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO signals SELECT * FROM df")
        return len(df)

    def get_signals_for_date(self, signal_date: date) -> pd.DataFrame:
        with self.reader() as con:
            return con.execute(
                "SELECT * FROM signals WHERE signal_date = ? ORDER BY confidence DESC",
                [signal_date],
            ).df()

    # ── ML Feature Store ───────────────────────────────────────────────────────

    def upsert_ml_features(self, df: pd.DataFrame) -> int:
        """Write ML features to ml_features table. df must have (ticker, date) columns."""
        if df.empty:
            return 0
        if "date" in df.columns:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO ml_features SELECT * FROM df")
        return len(df)

    def get_ml_features(
        self,
        ticker: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        conditions = []
        params: list = []
        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker)
        if start:
            conditions.append("date >= ?")
            params.append(start)
        if end:
            conditions.append("date <= ?")
            params.append(end)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self.reader() as con:
            return con.execute(
                f"SELECT * FROM ml_features {where} ORDER BY ticker, date",
                params,
            ).df()

    # ── ML Labels ──────────────────────────────────────────────────────────────

    def upsert_ml_labels(self, df: pd.DataFrame) -> int:
        """Write ML labels to ml_labels table."""
        if df.empty:
            return 0
        if "date" in df.columns:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.date
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO ml_labels SELECT * FROM df")
        return len(df)

    def get_ml_labels(
        self,
        ticker: str | None = None,
        horizon: int = 5,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        conditions = ["horizon_days = ?"]
        params: list = [horizon]
        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker)
        if start:
            conditions.append("date >= ?")
            params.append(start)
        if end:
            conditions.append("date <= ?")
            params.append(end)
        where = "WHERE " + " AND ".join(conditions)
        with self.reader() as con:
            return con.execute(
                f"SELECT * FROM ml_labels {where} ORDER BY ticker, date",
                params,
            ).df()
