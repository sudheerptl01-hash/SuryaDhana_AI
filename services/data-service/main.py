from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

import pandas as pd
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import Settings, get_settings
from shared.logging import configure_logging, get_logger
from shared.models import OHLCVBatch

from providers import YFinanceProvider, build_live_provider, LiveDataProvider
from storage import DuckDBStore

logger = get_logger(__name__)

_store: DuckDBStore | None = None
_yfinance: YFinanceProvider | None = None
_live: LiveDataProvider | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _store, _yfinance, _live
    settings = get_settings()
    configure_logging("data-service", settings.log_level)
    _store = DuckDBStore(settings.duckdb_path)
    _yfinance = YFinanceProvider()
    _live = build_live_provider(
        settings.icici_api_key,
        settings.icici_api_secret,
        settings.icici_session_token,
    )
    _live.connect()
    logger.info("Data service started")
    yield
    _live.disconnect()
    logger.info("Data service stopped")


app = FastAPI(
    title="SuryaDhana — Data Service",
    version="1.0.0",
    lifespan=lifespan,
)


def get_store() -> DuckDBStore:
    assert _store is not None
    return _store


def get_yfinance() -> YFinanceProvider:
    assert _yfinance is not None
    return _yfinance


def get_live_provider() -> LiveDataProvider:
    assert _live is not None
    return _live


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "data-service"}


@app.get("/ready")
async def ready(store: DuckDBStore = Depends(get_store)) -> dict:
    return {"status": "ready", "db": store._db_path}


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
    yf: YFinanceProvider = Depends(get_yfinance),
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
        source="icici_breeze_v2" if use_icici else "yfinance",
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
                # Per-ticker yfinance fallback
                try:
                    fb_batch = yf.fetch_single(ticker, start=start_date, end=end_date)
                    if fb_batch.records:
                        fb_df = yf.to_dataframe(fb_batch)
                        fb_df["source"] = "yfinance"
                        rows = store.upsert_ohlcv(fb_df, source="yfinance")
                        results[ticker] = rows
                    else:
                        errors.append(f"{ticker}: icici failed ({exc}), yfinance also empty")
                except Exception as fb_exc:
                    errors.append(f"{ticker}: icici ({exc}), yfinance ({fb_exc})")
    else:
        # ── yfinance path (ICICI not configured) ──────────────────────────────
        logger.warning("ICICI not configured — using yfinance for historical fetch")
        batches = yf.fetch_historical(req.tickers, years=req.years)
        for ticker, batch in batches.items():
            if not batch.records:
                errors.append(f"{ticker}: no data returned")
                continue
            try:
                df = yf.to_dataframe(batch)
                df["source"] = "yfinance"
                rows = store.upsert_ohlcv(df, source="yfinance")
                results[ticker] = rows
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")

    return FetchHistoricalResponse(fetched=results, errors=errors)


# ── Single ticker refresh ──────────────────────────────────────────────────────

class RefreshTickerRequest(BaseModel):
    ticker: str
    start_date: date | None = None


@app.post("/fetch/refresh")
async def refresh_ticker(
    req: RefreshTickerRequest,
    yf: YFinanceProvider = Depends(get_yfinance),
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
    rows = store.upsert_ohlcv(df, source="yfinance")
    return {"ticker": req.ticker, "rows_written": rows}


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


# ── ICICI intraday (today's bars) ──────────────────────────────────────────────

@app.get("/live/intraday/{ticker}")
async def get_intraday(
    ticker: str,
    interval: str = "5minute",
    live: LiveDataProvider = Depends(get_live_provider),
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """Fetch today's intraday bars via ICICI Breeze v2 and optionally store them."""
    batch = live.get_intraday_ohlcv(ticker=ticker, interval=interval)
    if batch.records:
        import pandas as pd
        df = pd.DataFrame([r.model_dump() for r in batch.records])
        df["source"] = "icici_breeze_v2"
        store.upsert_ohlcv(df, source="icici_breeze_v2")
    return {"ticker": ticker, "interval": interval, "rows": len(batch.records)}
