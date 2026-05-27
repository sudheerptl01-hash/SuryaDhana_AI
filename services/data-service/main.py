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
        redis_client = None
        try:
            if redis_url:
                import redis
                redis_client = redis.from_url(redis_url)
        except Exception:
            redis_client = None

        while True:
            try:
                if not _live or not _live.is_connected():
                    await asyncio.sleep(5)
                    continue
                quote = None
                symbol = None
                for cand in candidates:
                    try:
                        q = _live.get_live_quote(cand)
                        if q:
                            quote = q
                            symbol = cand
                            break
                    except Exception:
                        continue
                if quote is not None and symbol is not None:
                    ts = quote.get("timestamp") or time.time()
                    payload = json.dumps(quote, default=str)
                    try:
                        _store.upsert_live_quote(symbol, ts, payload)
                    except Exception as exc:
                        logger.warning("Failed to write live quote", error=str(exc))
                    # publish to redis channel
                    if redis_client:
                        try:
                            redis_client.publish("live.quotes", json.dumps({"symbol": symbol, "ts": ts, "payload": quote}, default=str))
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning("NIFTY poller error", error=str(exc))
            await asyncio.sleep(5)

    try:
        _nifty_task = asyncio.create_task(_nifty_poller())
    except Exception:
        _nifty_task = None

    logger.info("Data service started")
    yield
    try:
        _live.disconnect()
    except Exception:
        pass
    # Stop poller
    try:
        if _nifty_task is not None:
            _nifty_task.cancel()
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

@app.get("/live/intraday/{ticker}")
async def get_intraday(
    ticker: str,
    interval: str = "5minute",
    live: LiveDataProvider = Depends(get_live_provider),
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """Fetch today's intraday bars via ICICI Breeze v2, store them, and return the data."""
    batch = live.get_intraday_ohlcv(ticker=ticker, interval=interval)
    records_out: list[dict] = []
    if batch.records:
        import pandas as pd
        df = pd.DataFrame([r.model_dump() for r in batch.records])
        df["source"] = "icici_breeze_v2"
        store.upsert_ohlcv(df, source="icici_breeze_v2")
        records_out = df.to_dict(orient="records")
    return {
        "ticker": ticker,
        "interval": interval,
        "rows": len(records_out),
        "data": records_out,
    }
