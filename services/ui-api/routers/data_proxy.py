"""
data_proxy.py — Transparent reverse proxy: ui-api → data-service.

All data-service endpoints are re-exposed under /api/data/* so the
Next.js frontend only talks to ui-api, which works in both:
  - Local dev:  ui-api:8010  →  data-service:8001
  - Docker:     ui-api:8010  →  data-service:8001  (Docker DNS)

Security: In production, add bearer-token validation here before forwarding.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter()

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
_SHORT_TIMEOUT = httpx.Timeout(15.0)   # health / quotes
_MEDIUM_TIMEOUT = httpx.Timeout(60.0)  # single-ticker refresh / intraday
_LONG_TIMEOUT   = httpx.Timeout(300.0) # bulk historical / fundamentals


def _raise_upstream(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)


# ── Health & Status ────────────────────────────────────────────────────────────

@router.get("/health")
async def data_health() -> Any:
    try:
        async with httpx.AsyncClient(timeout=_SHORT_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/health")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.get("/ready")
async def data_ready() -> Any:
    try:
        async with httpx.AsyncClient(timeout=_SHORT_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/ready")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.get("/provider/status")
async def provider_status() -> Any:
    try:
        async with httpx.AsyncClient(timeout=_SHORT_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/provider/status")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.post("/provider/configure")
async def configure_provider(request: Request) -> Any:
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.post(f"{DATA_SVC}/provider/configure", json=body)
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


# ── Historical fetch ───────────────────────────────────────────────────────────

@router.post("/fetch/historical")
async def fetch_historical(request: Request) -> Any:
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=_LONG_TIMEOUT) as client:
            r = await client.post(f"{DATA_SVC}/fetch/historical", json=body)
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.post("/fetch/refresh")
async def fetch_refresh(request: Request) -> Any:
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.post(f"{DATA_SVC}/fetch/refresh", json=body)
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.post("/fetch/refresh-batch")
async def fetch_refresh_batch(request: Request) -> Any:
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=_LONG_TIMEOUT) as client:
            r = await client.post(f"{DATA_SVC}/fetch/refresh-batch", json=body)
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.post("/fetch/icici/daily", deprecated=True)
async def fetch_icici_daily(request: Request) -> Any:
    """DEPRECATED (F1.6): ticks come from the Breeze WebSocket; yfinance is the daily
    source of record. Kept one release for manual backfills; remove after 2026-11."""
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=_LONG_TIMEOUT) as client:
            r = await client.post(f"{DATA_SVC}/fetch/icici/daily", json=body)
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.post("/fetch/fundamentals")
async def fetch_fundamentals(request: Request) -> Any:
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=_LONG_TIMEOUT) as client:
            r = await client.post(f"{DATA_SVC}/fetch/fundamentals", json=body)
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


# ── OHLCV read ─────────────────────────────────────────────────────────────────

@router.get("/ohlcv/{ticker}")
async def get_ohlcv(
    ticker: str,
    start: str | None = Query(default=None),
    end:   str | None = Query(default=None),
) -> Any:
    params: dict[str, str] = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    try:
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/ohlcv/{ticker}", params=params)
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


# ── Live quotes ────────────────────────────────────────────────────────────────

@router.get("/live/quote/{ticker}")
async def get_live_quote(ticker: str) -> Any:
    try:
        async with httpx.AsyncClient(timeout=_SHORT_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/live/quote/{ticker}")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.get("/live/index/nifty")
async def get_live_nifty_direct() -> Any:
    try:
        async with httpx.AsyncClient(timeout=_SHORT_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/live/index/nifty")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.get("/live/intraday/{ticker}")
async def get_intraday(
    ticker: str,
    interval: str = Query(default="5minute"),
    day: str | None = Query(default=None),
) -> Any:
    try:
        params: dict[str, str] = {"interval": interval}
        if day:
            params["day"] = day
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.get(
                f"{DATA_SVC}/live/intraday/{ticker}",
                params=params,
            )
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


# ── DB stats proxy (bridges virtioFS DuckDB concurrent-lock limitation) ────────

@router.get("/db/stats")
async def db_stats() -> Any:
    """
    Proxy data-service /db/stats.

    ui-api cannot open a concurrent read-only DuckDB connection while
    data-service holds the persistent RW lock on virtioFS (Docker Desktop
    Mac).  This endpoint bypasses that by fetching stats over HTTP from
    data-service, which already owns the lock.
    """
    try:
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/db/stats")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.get("/db/archive-meta")
async def archive_meta() -> Any:
    try:
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/db/archive-meta")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.get("/db/nse-positions-meta")
async def nse_datasets_meta() -> Any:
    """Rows and date range of every NSE research table (bhavcopy, F&O, deals, MTF, filings, events, results)."""
    try:
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/db/nse-positions-meta")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.get("/db/ohlcv-meta")
async def db_ohlcv_meta() -> Any:
    """
    Proxy data-service /db/ohlcv-meta.
    Returns per-ticker OHLCV + metrics stats for the stocks list page.
    """
    try:
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/db/ohlcv-meta")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")


@router.get("/db/ml-stats")
async def db_ml_stats() -> Any:
    """
    Proxy data-service /db/ml-stats.

    Returns ml_features + ml_labels row counts, ticker coverage, freshness and
    label class-balance stats.  Powers the Warehouse & ML Health console — the
    ui-api cannot open a concurrent DuckDB RO connection on virtioFS (Docker
    Desktop Mac), so this bridges to data-service which owns the RW lock.
    """
    try:
        async with httpx.AsyncClient(timeout=_MEDIUM_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/db/ml-stats")
        _raise_upstream(r)
        return r.json()
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="data-service unreachable")
