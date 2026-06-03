from __future__ import annotations

import os
import re
import sys
import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, status, BackgroundTasks
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import Settings, get_settings
from shared.logging import configure_logging, get_logger
from shared.models import OHLCVBatch

from providers import DirectYahooProvider, build_live_provider, LiveDataProvider
from storage import DuckDBStore

logger = get_logger(__name__)

_store: DuckDBStore | None = None
_yfinance: DirectYahooProvider | None = None
_live: LiveDataProvider | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _store, _yfinance, _live
    settings = get_settings()
    configure_logging("data-service", settings.log_level)
    _store = DuckDBStore(settings.duckdb_path)
    _yfinance = DirectYahooProvider()
    _live = build_live_provider(
        settings.icici_api_key,
        settings.icici_api_secret,
        settings.icici_session_token,
    )
    try:
        _live.connect()
        logger.info("ICICI Breeze connected")
    except Exception as e:
        logger.warning(f"ICICI Breeze connection failed: {e}. Continuing with yfinance only.")

    # Start background NIFTY poller task
    _nifty_task: asyncio.Task | None = None

    async def _nifty_poller():
        candidates = ["NIFTY", "NIFTY50", "NSEI", "^NSEI", "NIFTY.NS"]
        redis_url = os.environ.get("REDIS_URL")

        # ── Redis client setup ────────────────────────────────────────────────
        redis_client = None
        if redis_url:
            try:
                import redis as _redis
                redis_client = _redis.from_url(redis_url, socket_connect_timeout=3)
                # Eagerly ping so we know it's reachable before the first tick
                redis_client.ping()
                logger.info("NIFTY poller: Redis connected", url=redis_url)
            except Exception as exc:
                logger.warning("NIFTY poller: Redis unavailable — live quotes won't stream", error=str(exc))
                redis_client = None
        else:
            logger.warning("NIFTY poller: REDIS_URL not set — live quotes won't stream")

        tick_count = 0
        while True:
            try:
                if not _live or not _live.is_connected():
                    await asyncio.sleep(5)
                    continue

                # ── Fetch quote (synchronous I/O → thread pool) ───────────────
                quote = None
                symbol = None
                for cand in candidates:
                    try:
                        q = await asyncio.to_thread(_live.get_live_quote, cand)
                        if q:
                            quote = q
                            symbol = cand
                            break
                    except Exception:
                        continue

                if quote is not None and symbol is not None:
                    ts = quote.get("timestamp") or time.time()
                    payload = json.dumps(quote, default=str)

                    # ── Persist to DuckDB (non-blocking) ─────────────────────
                    try:
                        await asyncio.to_thread(_store.upsert_live_quote, symbol, ts, payload)
                    except Exception as exc:
                        logger.warning("NIFTY poller: DuckDB write failed", error=str(exc))

                    # ── Publish to Redis regardless of DuckDB result ──────────
                    if redis_client is not None:
                        msg = json.dumps(
                            {"symbol": symbol, "ts": ts, "payload": quote},
                            default=str,
                        )
                        try:
                            await asyncio.to_thread(redis_client.publish, "live.quotes", msg)
                            tick_count += 1
                            if tick_count % 12 == 1:  # log every ~1 min
                                logger.info(
                                    "NIFTY tick published",
                                    symbol=symbol,
                                    tick=tick_count,
                                    price=quote.get("last_price") or quote.get("ltp"),
                                )
                        except Exception as exc:
                            logger.warning("NIFTY poller: Redis publish failed", error=str(exc))
                            # Try to reconnect on next iteration
                            try:
                                redis_client.ping()
                            except Exception:
                                logger.warning("NIFTY poller: Redis connection lost — reconnecting")
                                try:
                                    redis_client = _redis.from_url(redis_url, socket_connect_timeout=3)
                                    redis_client.ping()
                                except Exception:
                                    redis_client = None

            except Exception as exc:
                logger.warning("NIFTY poller error", error=str(exc))
            await asyncio.sleep(5)

    try:
        _nifty_task = asyncio.create_task(_nifty_poller())
    except Exception:
        _nifty_task = None

    logger.info("Data service started")
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    try:
        if _nifty_task is not None:
            _nifty_task.cancel()
            await asyncio.gather(_nifty_task, return_exceptions=True)
    except Exception:
        pass
    try:
        _live.disconnect()
    except Exception:
        pass
    try:
        _store.close()
    except Exception:
        pass
    logger.info("Data service stopped")


app = FastAPI(
    title="SuryaDhana — Data Service",
    version="1.0.0",
    lifespan=lifespan,
)


def get_store() -> DuckDBStore:
    assert _store is not None
    return _store


def get_yfinance() -> DirectYahooProvider:
    assert _yfinance is not None
    return _yfinance


def get_live_provider() -> LiveDataProvider:
    assert _live is not None
    return _live


def _extract_session_token(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if not value.startswith("http"):
        return value
    match = re.search(r"(?:apisession|session_token|apiSession|api_session)=([^&\\s]+)", value)
    return match.group(1) if match else value


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "data-service"}


@app.get("/ready")
async def ready(store: DuckDBStore = Depends(get_store)) -> dict:
    return {"status": "ready", "db": store._db_path}


@app.post("/admin/migrate")
async def run_migrations(store: DuckDBStore = Depends(get_store)) -> dict:
    """
    Cycle the DuckDB connection to write mode, run schema DDL to create any missing tables,
    then return to read-only. Call once after adding new tables to duckdb_store.py DDL.
    """
    import duckdb as _duckdb

    db_path = store._db_path
    # Close existing read-only connection to release shared lock
    try:
        store.close()
    except Exception:
        pass

    created: list[str] = []
    try:
        con = _duckdb.connect(db_path)
        tables_before = {r[0] for r in con.execute("SHOW TABLES").fetchall()}

        # ml_features table
        con.execute("""
            CREATE TABLE IF NOT EXISTS ml_features (
                ticker VARCHAR NOT NULL, date DATE NOT NULL,
                ret_1d DOUBLE, ret_5d DOUBLE, ret_20d DOUBLE, log_ret DOUBLE,
                sma_20 DOUBLE, sma_50 DOUBLE, sma_200 DOUBLE,
                ema_12 DOUBLE, ema_26 DOUBLE,
                price_vs_sma20 DOUBLE, price_vs_sma50 DOUBLE, price_vs_sma200 DOUBLE,
                sma_ratio_20_50 DOUBLE, uptrend_20_50 INTEGER, uptrend_50_200 INTEGER,
                rsi_14 DOUBLE, rsi_7 DOUBLE, rsi_28 DOUBLE,
                macd DOUBLE, macd_signal DOUBLE, macd_hist DOUBLE,
                bollinger_pctb DOUBLE, bb_width DOUBLE,
                atr_14 DOUBLE, atr_14_pct DOUBLE, realized_vol_20d DOUBLE,
                volume_zscore DOUBLE, volume_ratio DOUBLE, obv DOUBLE,
                mfi_14 DOUBLE, cmf_20 DOUBLE,
                stoch_k DOUBLE, stoch_d DOUBLE, williams_r DOUBLE,
                roc_5 DOUBLE, roc_10 DOUBLE, roc_20 DOUBLE,
                gap_pct DOUBLE, high_low_ratio DOUBLE, close_position DOUBLE,
                is_green_candle INTEGER,
                return_lag_1d DOUBLE, return_lag_2d DOUBLE, return_lag_3d DOUBLE,
                return_lag_5d DOUBLE, return_lag_10d DOUBLE,
                day_of_week INTEGER, month INTEGER,
                trailing_pe DOUBLE, price_to_book DOUBLE, ev_to_ebitda DOUBLE,
                peg_ratio DOUBLE, revenue_growth DOUBLE,
                gross_margins DOUBLE, operating_margins DOUBLE, profit_margins DOUBLE,
                return_on_equity DOUBLE, return_on_assets DOUBLE,
                debt_to_equity DOUBLE, current_ratio DOUBLE, altman_z DOUBLE,
                insider_hold_pct DOUBLE, inst_hold_pct DOUBLE,
                india_vix DOUBLE, vix_zscore DOUBLE,
                nifty_ret_5d DOUBLE, nifty_regime VARCHAR, market_breadth DOUBLE,
                feature_version VARCHAR DEFAULT 'v1',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, date)
            )
        """)

        # ml_labels table
        con.execute("""
            CREATE TABLE IF NOT EXISTS ml_labels (
                ticker VARCHAR NOT NULL, date DATE NOT NULL,
                horizon_days INTEGER NOT NULL DEFAULT 5,
                label_direction INTEGER, label_return_pct DOUBLE,
                label_barrier INTEGER, profit_target_pct DOUBLE DEFAULT 2.0,
                stop_loss_pct DOUBLE DEFAULT 2.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, date, horizon_days)
            )
        """)

        tables_after = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        created = sorted(tables_after - tables_before)
        con.close()
    except Exception as exc:
        # Re-open read-only before returning error
        store._read_only = True
        store._conn = _duckdb.connect(db_path, read_only=True)
        raise HTTPException(status_code=500, detail=f"Migration failed: {exc}")

    # Re-open read-only connection
    store._read_only = True
    store._conn = _duckdb.connect(db_path, read_only=True)

    return {"status": "ok", "tables_created": created, "message": "Schema migration complete"}


@app.post("/admin/import-ml-data")
async def import_ml_data_from_parquet(store: DuckDBStore = Depends(get_store)) -> dict:
    """
    Read computed_features.parquet and computed_labels.parquet (written by the pipeline)
    and persist them into DuckDB ml_features + ml_labels tables.

    Called automatically by pipeline.py after feature generation completes.
    Cycles the DuckDB connection through write mode to perform the import.
    """
    import duckdb as _duckdb
    import pandas as pd
    from pathlib import Path as _Path

    db_path = store._db_path
    data_dir = _Path(db_path).parent
    feat_parquet = data_dir / "computed_features.parquet"
    lbl_parquet  = data_dir / "computed_labels.parquet"

    if not feat_parquet.exists() and not lbl_parquet.exists():
        raise HTTPException(status_code=404, detail="No Parquet files found — run feature generation first")

    result = {"features": 0, "labels": 0, "status": "ok"}

    if store._read_only:
        raise HTTPException(
            status_code=503,
            detail="DuckDB is in read-only mode — restart data-service when no other process holds the DB write lock"
        )

    try:
        con = store._conn  # reuse existing write-mode connection

        if feat_parquet.exists():
            # Discover Parquet columns
            parquet_cols = {r[0] for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{feat_parquet}') LIMIT 1"
            ).fetchall()}

            # All numeric feature columns from feature_engine (no macro/varchar edge cases)
            numeric_features = [
                "ret_1d", "ret_5d", "ret_20d", "log_ret",
                "sma_20", "sma_50", "sma_200", "ema_12", "ema_26",
                "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
                "sma_ratio_20_50", "uptrend_20_50", "uptrend_50_200",
                "rsi_14", "rsi_7", "rsi_28",
                "macd", "macd_signal", "macd_hist",
                "bollinger_pctb", "bb_width",
                "atr_14", "atr_14_pct", "realized_vol_20d",
                "volume_zscore", "volume_ratio", "obv",
                "mfi_14", "cmf_20",
                "stoch_k", "stoch_d", "williams_r",
                "roc_5", "roc_10", "roc_20",
                "gap_pct", "high_low_ratio", "close_position",
                "is_green_candle",
                "return_lag_1d", "return_lag_2d", "return_lag_3d", "return_lag_5d", "return_lag_10d",
                "day_of_week", "month",
                "trailing_pe", "price_to_book", "ev_to_ebitda",
                "peg_ratio", "revenue_growth",
                "gross_margins", "operating_margins", "profit_margins",
                "return_on_equity", "return_on_assets",
                "debt_to_equity", "current_ratio", "altman_z",
                "insider_hold_pct", "inst_hold_pct",
                "india_vix", "vix_zscore", "nifty_ret_5d", "market_breadth",
            ]

            # Only include columns that exist in BOTH Parquet AND ml_features table
            table_cols = {r[0] for r in con.execute("DESCRIBE ml_features").fetchall()}
            insert_cols = ["ticker", "date"]
            select_exprs = ["ticker::VARCHAR", "date::DATE"]
            for col in numeric_features:
                if col in table_cols:
                    insert_cols.append(col)
                    select_exprs.append(f"{col}::DOUBLE" if col in parquet_cols else "NULL")
            # nifty_regime (VARCHAR)
            if "nifty_regime" in table_cols:
                insert_cols.append("nifty_regime")
                select_exprs.append("TRY_CAST(nifty_regime AS VARCHAR)" if "nifty_regime" in parquet_cols else "NULL")
            insert_cols.append("feature_version")
            select_exprs.append("COALESCE(TRY_CAST(feature_version AS VARCHAR), 'v1')" if "feature_version" in parquet_cols else "'v1'")

            col_list = ", ".join(insert_cols)
            val_list = ", ".join(select_exprs)

            with store._lock:
                con.execute("DELETE FROM ml_features")
                con.execute(f"INSERT INTO ml_features ({col_list}) SELECT {val_list} FROM read_parquet('{feat_parquet}')")
            result["features"] = con.execute("SELECT COUNT(*) FROM ml_features").fetchone()[0]

        if lbl_parquet.exists():
            lbl_parquet_cols = {r[0] for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{lbl_parquet}') LIMIT 1"
            ).fetchall()}

            def _lc(col: str, fallback: str) -> str:
                return col if col in lbl_parquet_cols else fallback

            with store._lock:
                con.execute("DELETE FROM ml_labels")
                con.execute(f"""
                    INSERT INTO ml_labels (ticker, date, horizon_days, label_direction,
                                           label_return_pct, label_barrier,
                                           profit_target_pct, stop_loss_pct)
                    SELECT
                        ticker::VARCHAR,
                        date::DATE,
                        {_lc("TRY_CAST(horizon_days AS INTEGER)", "5")},
                        TRY_CAST(label_direction AS INTEGER),
                        label_return_pct::DOUBLE,
                        {_lc("TRY_CAST(label_barrier AS INTEGER)", "NULL")},
                        {_lc("TRY_CAST(profit_target_pct AS DOUBLE)", "2.0")},
                        {_lc("TRY_CAST(stop_loss_pct AS DOUBLE)", "2.0")}
                    FROM read_parquet('{lbl_parquet}')
                """)
            result["labels"] = con.execute("SELECT COUNT(*) FROM ml_labels").fetchone()[0]

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    return result


class ICICIConfigureRequest(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    session_token: str | None = None


@app.get("/provider/status")
async def provider_status(live: LiveDataProvider = Depends(get_live_provider)) -> dict:
    return {
        "provider": type(live).__name__,
        "connected": live.is_connected(),
    }


@app.post("/provider/configure")
async def configure_provider(req: ICICIConfigureRequest) -> dict:
    global _live

    api_key = (req.api_key if req.api_key is not None else os.environ.get("ICICI_API_KEY", "")).strip()
    api_secret = (req.api_secret if req.api_secret is not None else os.environ.get("ICICI_API_SECRET", "")).strip()
    session_token = _extract_session_token(req.session_token if req.session_token is not None else os.environ.get("ICICI_SESSION_TOKEN", ""))

    os.environ["ICICI_API_KEY"] = api_key
    os.environ["ICICI_API_SECRET"] = api_secret
    os.environ["ICICI_SESSION_TOKEN"] = session_token

    if _live is not None:
        _live.disconnect()

    _live = build_live_provider(api_key, api_secret, session_token)
    try:
        _live.connect()
        return {
            "provider": type(_live).__name__,
            "connected": _live.is_connected(),
        }
    except Exception as exc:
        logger.error("Failed to reconfigure data-service ICICI provider", error=str(exc))
        return {
            "provider": type(_live).__name__,
            "connected": False,
            "error": str(exc),
        }


# ── Historical data ────────────────────────────────────────────────────────────

class FetchHistoricalRequest(BaseModel):
    tickers: list[str]
    years: int = 5


class FetchHistoricalResponse(BaseModel):
    fetched: dict[str, int]  # ticker → rows written
    errors: list[str]


@app.post("/fetch/historical", response_model=FetchHistoricalResponse)
async def fetch_historical(
    req: FetchHistoricalRequest,
    background_tasks: BackgroundTasks,
    yf: DirectYahooProvider = Depends(get_yfinance),
    live: LiveDataProvider = Depends(get_live_provider),
    store: DuckDBStore = Depends(get_store),
) -> FetchHistoricalResponse:
    """
    Fetch historical OHLCV and store in DuckDB.
    Strategy: ICICI Breeze v2 (primary) → yfinance (fallback if ICICI not configured).
    """
    from providers.icici_breeze_provider import ICICIBreezeProvider
    from datetime import timedelta

    results: dict[str, int] = {}
    errors: list[str] = []

    use_icici = isinstance(live, ICICIBreezeProvider)
    end_date = date.today()
    start_date = end_date - timedelta(days=req.years * 365 + 10)

    logger.info(
        "fetch/historical called",
        tickers=len(req.tickers),
        years=req.years,
        source="icici_breeze_v2" if use_icici else "yahoo_v8",
    )

    if use_icici:
        # ── ICICI Breeze v2 path ───────────────────────────────────────────────
        for ticker in req.tickers:
            try:
                batch = live.get_daily_ohlcv_v2(
                    ticker=ticker,
                    start=start_date,
                    end=end_date,
                )
                if not batch.records:
                    errors.append(f"{ticker}: no data returned")
                    continue
                df = pd.DataFrame([r.model_dump() for r in batch.records])
                df["source"] = "icici_breeze_v2"
                rows = store.upsert_ohlcv(df, source="icici_breeze_v2")
                results[ticker] = rows
            except Exception as exc:
                logger.error("ICICI fetch failed, trying yfinance fallback", ticker=ticker, error=str(exc))
                # Per-ticker direct yahoo fallback
                try:
                    fb_batch = yf.fetch_single(ticker, start=start_date, end=end_date)
                    if fb_batch.records:
                        fb_df = yf.to_dataframe(fb_batch)
                        fb_df["source"] = "yahoo_v8"
                        rows = store.upsert_ohlcv(fb_df, source="yahoo_v8")
                        results[ticker] = rows
                    else:
                        errors.append(f"{ticker}: icici failed ({exc}), yahoo_v8 also empty")
                except Exception as fb_exc:
                    errors.append(f"{ticker}: icici ({exc}), yahoo_v8 ({fb_exc})")
    else:
        # ── Direct Yahoo v8 path (ICICI not configured) ───────────────────────
        logger.warning("ICICI not configured — using Yahoo Finance v8 API")
        batches = yf.fetch_historical(req.tickers, years=req.years)
        for ticker, batch in batches.items():
            if not batch.records:
                errors.append(f"{ticker}: no data returned")
                continue
            try:
                df = yf.to_dataframe(batch)
                df["source"] = "yahoo_v8"
                rows = store.upsert_ohlcv(df, source="yahoo_v8")
                results[ticker] = rows
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")

    return FetchHistoricalResponse(fetched=results, errors=errors)


# ── Single ticker refresh ──────────────────────────────────────────────────────

class RefreshTickerRequest(BaseModel):
    ticker: str
    start_date: date | None = None


class RefreshBatchRequest(BaseModel):
    tickers: list[str]
    years: int = 5


class RefreshBatchResponse(BaseModel):
    refreshed: dict[str, int]
    errors: list[str]


def _incremental_start_date(store: DuckDBStore, ticker: str, years: int) -> date:
    from datetime import timedelta

    latest = store.get_latest_ohlcv_date(ticker)
    if latest:
        return latest + timedelta(days=1)
    return date.today() - timedelta(days=years * 365 + 10)


def _fetch_incremental_batch_for_ticker(
    *,
    ticker: str,
    years: int,
    yf: DirectYahooProvider,
    live: LiveDataProvider,
    store: DuckDBStore,
) -> int:
    from datetime import timedelta
    from providers.icici_breeze_provider import ICICIBreezeProvider

    start = _incremental_start_date(store, ticker, years)
    end = date.today()
    if start > end:
        return 0

    use_icici = isinstance(live, ICICIBreezeProvider)
    if use_icici:
        try:
            batch = live.get_daily_ohlcv_v2(ticker=ticker, start=start, end=end)
            if batch.records:
                df = pd.DataFrame([r.model_dump() for r in batch.records])
                df["source"] = "icici_breeze_v2"
                return store.upsert_ohlcv(df, source="icici_breeze_v2")
            return 0
        except Exception as exc:
            logger.error("ICICI incremental fetch failed, trying yfinance fallback", ticker=ticker, error=str(exc))

    batch = yf.fetch_single(ticker, start=start, end=end + timedelta(days=1))
    if not batch.records:
        return 0
    df = yf.to_dataframe(batch)
    df["source"] = "yahoo_v8"
    return store.upsert_ohlcv(df, source="yahoo_v8")


@app.post("/fetch/refresh")
async def refresh_ticker(
    req: RefreshTickerRequest,
    yf: DirectYahooProvider = Depends(get_yfinance),
    store: DuckDBStore = Depends(get_store),
) -> dict:
    from datetime import timedelta

    start = req.start_date or store.get_latest_ohlcv_date(req.ticker)
    if start:
        start = start + timedelta(days=1)
    else:
        from datetime import date as d
        from shared.config import get_settings as gs
        settings = gs()
        from datetime import timedelta as td
        start = d.today() - td(days=settings.historical_years * 365)

    batch = yf.fetch_single(req.ticker, start=start)
    if not batch.records:
        return {"ticker": req.ticker, "rows_written": 0, "message": "No new data"}

    df = yf.to_dataframe(batch)
    rows = store.upsert_ohlcv(df, source="yahoo_v8")
    return {"ticker": req.ticker, "rows_written": rows}


@app.post("/fetch/refresh-batch", response_model=RefreshBatchResponse)
async def refresh_batch(
    req: RefreshBatchRequest,
    yf: DirectYahooProvider = Depends(get_yfinance),
    live: LiveDataProvider = Depends(get_live_provider),
    store: DuckDBStore = Depends(get_store),
) -> RefreshBatchResponse:
    """
    Incrementally update daily rows for every ticker.
    If a ticker already has history, fetch only missing dates after the latest row.
    If a ticker has no history yet, backfill the configured history window.
    """
    results: dict[str, int] = {}
    errors: list[str] = []

    for ticker in req.tickers:
        try:
            rows = _fetch_incremental_batch_for_ticker(
                ticker=ticker,
                years=req.years,
                yf=yf,
                live=live,
                store=store,
            )
            results[ticker] = rows
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")

    return RefreshBatchResponse(refreshed=results, errors=errors)


# ── OHLCV read ─────────────────────────────────────────────────────────────────

@app.get("/ohlcv/{ticker}")
async def get_ohlcv(
    ticker: str,
    start: date | None = None,
    end: date | None = None,
    store: DuckDBStore = Depends(get_store),
) -> dict:
    df = store.get_ohlcv(ticker, start=start, end=end)
    if df.empty:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No OHLCV data for {ticker}")
    # Normalise date column to plain yyyy-mm-dd strings (lightweight-charts requirement)
    if "date" in df.columns:
        df = df.copy()
        df["date"] = df["date"].astype(str).str[:10]
    return {"ticker": ticker, "rows": len(df), "data": df.to_dict(orient="records")}


# ── Live quote ─────────────────────────────────────────────────────────────────

@app.get("/live/quote/{ticker}")
async def get_live_quote(
    ticker: str,
    live: LiveDataProvider = Depends(get_live_provider),
) -> dict:
    quote = live.get_live_quote(ticker)
    return {"ticker": ticker, "quote": quote}


@app.get("/live/index/nifty")
async def get_live_nifty(store: DuckDBStore = Depends(get_store)) -> dict:
    """Return the latest stored NIFTY quote (if available)."""
    rows = store.get_latest_live_quotes(limit=10)
    # prefer symbols commonly used for NIFTY
    for r in rows:
        sym = r.get("symbol", "").upper()
        if sym in ("NIFTY", "NSEI", "NIFTY50", "NIFTY.NS", "^NSEI"):
            return {"symbol": sym, "record": r}
    return {"symbol": None, "recent": rows}


# ── ICICI Breeze v2 daily historical ingestion ─────────────────────────────────

class FetchICICIDailyRequest(BaseModel):
    tickers: list[str]
    start_date: date
    end_date: date | None = None
    exchange_code: str = "NSE"


class FetchICICIDailyResponse(BaseModel):
    fetched: dict[str, int]
    errors: list[str]


@app.post("/fetch/icici/daily", response_model=FetchICICIDailyResponse)
async def fetch_icici_daily(
    req: FetchICICIDailyRequest,
    live: LiveDataProvider = Depends(get_live_provider),
    store: DuckDBStore = Depends(get_store),
) -> FetchICICIDailyResponse:
    """
    Ingest daily OHLCV from ICICI Breeze v2 into DuckDB.

    Uses get_historical_data_v2 with automatic 365-day chunking.
    Requires ICICI credentials in .env (ICICI_API_KEY / SECRET / SESSION_TOKEN).
    """
    from providers.icici_breeze_provider import ICICIBreezeProvider

    if not isinstance(live, ICICIBreezeProvider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ICICI Breeze credentials not configured. Set ICICI_API_KEY, ICICI_API_SECRET, ICICI_SESSION_TOKEN in .env",
        )

    end = req.end_date or date.today()
    results: dict[str, int] = {}
    errors: list[str] = []

    for ticker in req.tickers:
        try:
            batch = live.get_daily_ohlcv_v2(
                ticker=ticker,
                start=req.start_date,
                end=end,
                exchange_code=req.exchange_code,
            )
            if not batch.records:
                errors.append(f"{ticker}: no data returned")
                continue
            import pandas as pd
            df = pd.DataFrame([r.model_dump() for r in batch.records])
            df["source"] = "icici_breeze_v2"
            rows = store.upsert_ohlcv(df, source="icici_breeze_v2")
            results[ticker] = rows
        except Exception as exc:
            logger.error("ICICI daily fetch failed", ticker=ticker, error=str(exc))
            errors.append(f"{ticker}: {exc}")

    return FetchICICIDailyResponse(fetched=results, errors=errors)


# ── Fundamentals / Stock Metrics ──────────────────────────────────────────────

class FetchFundamentalsRequest(BaseModel):
    tickers: list[str]


class FetchFundamentalsResponse(BaseModel):
    fetched: int
    skipped: int
    errors: list[str]


@app.post("/fetch/fundamentals", response_model=FetchFundamentalsResponse)
async def fetch_fundamentals(
    req: FetchFundamentalsRequest,
    store: DuckDBStore = Depends(get_store),
) -> FetchFundamentalsResponse:
    """
    Fetch PE, market cap, revenue, margins, ROCE etc. from Yahoo Finance
    and write to stock_metrics + fundamentals tables.
    ~0.6s per ticker; call with batches of 50-100 at a time.
    """
    import time as _time
    import random as _random
    from providers.fundamentals_provider import fetch_fundamentals as _fetch_fund, _get_session

    session = _get_session()
    metrics_rows: list[dict] = []
    fund_rows:    list[dict] = []
    errors:       list[str]  = []
    skipped = 0

    fund_cols = [
        "ticker","as_of_date","market_cap","trailing_pe","forward_pe","price_to_book",
        "enterprise_value","ev_to_revenue","ev_to_ebitda","total_revenue","revenue_growth",
        "gross_margins","operating_margins","profit_margins","return_on_equity",
        "return_on_assets","debt_to_equity","current_ratio","book_value","dividend_yield",
        "payout_ratio","avg_volume","shares_outstanding","insider_hold_pct","inst_hold_pct",
        "analyst_target_mean","analyst_target_high","analyst_target_low",
        "analyst_recommendation","analyst_count",
    ]

    for i, ticker in enumerate(req.tickers):
        try:
            data = _fetch_fund(ticker, session)
            if data is None:
                skipped += 1
                continue

            metrics_rows.append({
                "ticker":        ticker,
                "as_of_date":    data["as_of_date"],
                "cmp":           data.get("cmp"),
                "pe_ratio":      data.get("pe_ratio"),
                "mktcap_cr":     data.get("mktcap_cr"),
                "div_yld_pct":   data.get("div_yld_pct"),
                "np_qtr_cr":     data.get("np_qtr_cr"),
                "qtr_pft_var":   data.get("qtr_pft_var"),
                "sales_qtr_cr":  data.get("sales_qtr_cr"),
                "qtr_sal_var":   data.get("qtr_sal_var"),
                "roce_pct":      data.get("roce_pct"),
            })

            fund_row = {c: data.get(c) for c in fund_cols}
            fund_row["sector"]   = None
            fund_row["industry"] = None
            fund_row["country"]  = "India"
            fund_rows.append(fund_row)

        except Exception as exc:
            errors.append(f"{ticker}: {exc}")

        if i < len(req.tickers) - 1:
            _time.sleep(0.5 + _random.uniform(0, 0.3))

    if metrics_rows:
        store.upsert_stock_metrics(metrics_rows)
    if fund_rows:
        import pandas as pd
        df_fund = pd.DataFrame(fund_rows)
        store.upsert_fundamentals(df_fund)

    logger.info(
        "Fundamentals fetch complete",
        fetched=len(metrics_rows), skipped=skipped, errors=len(errors)
    )
    return FetchFundamentalsResponse(
        fetched=len(metrics_rows), skipped=skipped, errors=errors
    )


# ── ICICI intraday (today's bars) ──────────────────────────────────────────────

# ── Dashboard stats proxy (for ui-api — avoids concurrent DuckDB lock) ────────

@app.get("/db/stats")
async def get_db_stats(store: DuckDBStore = Depends(get_store)) -> dict:
    """
    Aggregate dashboard stats (total_stocks, freshness, enrichment, data_range).
    ui-api calls this instead of opening a second DuckDB connection, which
    fails on Docker Desktop Mac (virtioFS concurrent-lock bug).
    """
    return store.get_dashboard_stats()


@app.get("/db/ohlcv-meta")
async def get_ohlcv_meta(store: DuckDBStore = Depends(get_store)) -> dict:
    """
    Per-ticker OHLCV + metrics stats for the stocks list page.
    Returns a list keyed by ticker with total_rows, dates, price, metrics.
    """
    rows = store.get_ohlcv_meta_all()
    return {"count": len(rows), "data": rows}


@app.get("/db/screener")
async def run_screener(
    t1: bool = False, t2: bool = False, t3: bool = False, t4: bool = False,
    t5: bool = False, t6: bool = False, t7: bool = False, t8: bool = False,
    skip: int = 0, limit: int = 50,
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """Minervini T1-T8 screener via data-service DuckDB (avoids ui-api concurrent lock)."""
    filters = {"t1": t1, "t2": t2, "t3": t3, "t4": t4,
               "t5": t5, "t6": t6, "t7": t7, "t8": t8}
    return store.run_screener(filters, skip=skip, limit=limit)


# ── ICICI intraday (today's bars) ──────────────────────────────────────────────

@app.get("/db/ohlcv-bulk")
async def get_ohlcv_bulk(
    days: int = 700,
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """Return all OHLCV rows for the last N days (excludes macro tickers like ^NSEI).
    Used by pipeline.py feature generation to avoid direct DuckDB access from ui-api.
    """
    with store._lock:
        df = store._conn.execute(f"""
            SELECT ticker, date::VARCHAR AS date, open, high, low, close, volume, adjusted_close
            FROM ohlcv
            WHERE date >= (CURRENT_DATE - INTERVAL '{days}' DAY)
              AND ticker NOT LIKE '^%'
            ORDER BY ticker, date
        """).df()
    df["date"] = df["date"].str[:10]
    return {"rows": len(df), "data": df.to_dict(orient="records")}


@app.get("/db/latest-features")
async def get_latest_features(store: DuckDBStore = Depends(get_store)) -> dict:
    """Latest ml_features row per ticker — consumed by ml-service /batch-predict.

    ml-service must NOT open its own DuckDB connection: on Docker Desktop (Mac,
    virtioFS) a second connection fails with "Conflicting lock is held in PID 0"
    even read-only. data-service owns the lock, so it serves the feature matrix
    over HTTP instead.
    """
    with store._lock:
        df = store._conn.execute("""
            SELECT f.*
            FROM ml_features f
            INNER JOIN (
                SELECT ticker, MAX(date) AS max_date
                FROM ml_features
                GROUP BY ticker
            ) latest ON f.ticker = latest.ticker AND f.date = latest.max_date
        """).df()
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str[:10]
    return {"rows": len(df), "data": df.to_dict(orient="records")}


@app.get("/db/fundamentals-bulk")
async def get_fundamentals_bulk(store: DuckDBStore = Depends(get_store)) -> dict:
    """Return latest fundamentals snapshot per ticker (for feature generation).
    Used by pipeline.py to avoid direct DuckDB access from ui-api.
    """
    df = store.get_fundamentals()
    if not df.empty and "as_of_date" in df.columns:
        df["as_of_date"] = df["as_of_date"].astype(str).str[:10]
    return {"rows": len(df), "data": df.to_dict(orient="records")}


@app.get("/db/ml-stats")
async def get_ml_stats(store: DuckDBStore = Depends(get_store)) -> dict:
    """Return ml_features + ml_labels row counts, freshness and class-balance stats."""
    with store._lock:
        feat = store._conn.execute(
            "SELECT COUNT(*) AS cnt, COUNT(DISTINCT ticker) AS tickers, "
            "MAX(date)::VARCHAR AS latest FROM ml_features"
        ).fetchone()
        lbl = store._conn.execute(
            "SELECT COUNT(*) AS cnt, COUNT(DISTINCT ticker) AS tickers, "
            "MAX(date)::VARCHAR AS latest, "
            "SUM(CASE WHEN label_direction=1 THEN 1 ELSE 0 END) AS up_cnt, "
            "SUM(CASE WHEN label_direction=0 THEN 1 ELSE 0 END) AS dn_cnt, "
            "AVG(label_return_pct) AS avg_ret, STDDEV(label_return_pct) AS std_ret "
            "FROM ml_labels"
        ).fetchone()
    total_lbl = lbl[0] or 0
    up_lbl    = int(lbl[3] or 0)
    dn_lbl    = int(lbl[4] or 0)
    return {
        "features": {"rows": feat[0], "tickers": feat[1], "latest_date": feat[2]},
        "labels": {
            "rows": total_lbl, "tickers": lbl[1], "latest_date": lbl[2],
            "up_labels": up_lbl, "down_labels": dn_lbl,
            "class_balance_pct": round(up_lbl / total_lbl * 100, 1) if total_lbl else 0,
            "avg_return_pct": round(float(lbl[5] or 0), 4),
            "std_return_pct": round(float(lbl[6] or 0), 4),
        },
    }


@app.get("/live/intraday/{ticker}")
async def get_intraday(
    ticker: str,
    interval: str = "5minute",
    live: LiveDataProvider = Depends(get_live_provider),
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """Fetch today's intraday bars via ICICI Breeze v2.

    Falls back to the last 30 daily OHLCV bars from DuckDB when the live
    provider is not connected (expired session, stub mode, etc.).
    """
    records_out: list[dict] = []
    source = "icici"

    if live.is_connected():
        try:
            batch = await asyncio.to_thread(live.get_intraday_ohlcv, ticker, interval)
            if batch.records:
                records_out = [r.model_dump() for r in batch.records]
        except Exception as e:
            logger.warning("Intraday fetch failed, falling back to DuckDB", ticker=ticker, error=str(e))

    if not records_out:
        source = "duckdb_daily"
        try:
            from datetime import timedelta
            end_dt = date.today()
            start_dt = end_dt - timedelta(days=60)
            df = await asyncio.to_thread(store.get_ohlcv, ticker.upper(), start_dt, end_dt)
            if not df.empty:
                df = df.tail(30).copy()
                df["date"] = df["date"].astype(str).str[:10]
                df["time"] = df["date"]
                records_out = df.to_dict(orient="records")
        except Exception as e:
            logger.warning("DuckDB OHLCV fallback failed", ticker=ticker, error=str(e))

    return {
        "ticker": ticker,
        "interval": interval,
        "source": source,
        "rows": len(records_out),
        "data": records_out,
    }
