"""GET /api/health/upstream — is data-service answering, and is the store writable? (O-F5a, RISK §b, D-BOOT)

The terminal shell polls this ONE cheap endpoint to decide its WARMING UP / DB READ-ONLY strip instead of
letting 43 panels each discover an outage one raw transport error at a time. ui-api probes data-service's
`/health` with a 1 s timeout and caches the verdict for 5 s server-side behind a single-flight lock, so any
number of windows and panels cost data-service at most one probe per 5 s.

Shape (additive-safe): ``{"data_service": "up"|"down", "db_read_only": bool, "as_of": <epoch s>, "cached": bool}``
- ``data_service: "down"`` → the shell shows the WARMING UP strip (ui-api itself is clearly up: it answered).
- ``db_read_only: true`` → the DB READ-ONLY strip (reads work, ingest is paused; F-01's watchdog start order
  is the root-cause fix — this is the honest face while a lock is still held).

Mount (PM-only, services/ui-api/main.py):
    from routers import health_upstream
    app.include_router(health_upstream.router, prefix="/api/health", tags=["health"])
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter

router = APIRouter()
log = logging.getLogger("ui-api.health_upstream")

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
PROBE_TIMEOUT_S = 1.0
CACHE_S = 5.0

# Injectable for tests (httpx.MockTransport); None = real network.
_TRANSPORT: httpx.AsyncBaseTransport | None = None

_lock = asyncio.Lock()
_cached: dict[str, Any] | None = None
_cached_at = 0.0


def _reset_cache() -> None:
    """Tests only: forget the cached verdict."""
    global _cached, _cached_at
    _cached = None
    _cached_at = 0.0


async def _probe() -> dict[str, Any]:
    """One real probe. Any failure (timeout, refused, non-200, bad JSON) is simply 'down' — a health
    probe never raises and never puts transport internals on the wire (they go to the log)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(PROBE_TIMEOUT_S), transport=_TRANSPORT) as client:
            r = await client.get(f"{DATA_SVC}/health")
        if r.status_code != 200:
            log.debug("data-service /health answered %s", r.status_code)
            return {"data_service": "down", "db_read_only": False}
        body = r.json()
        read_only = bool(body.get("db_read_only")) if isinstance(body, dict) else False
        return {"data_service": "up", "db_read_only": read_only}
    except Exception as exc:  # noqa: BLE001 — down is the verdict, whatever the transport said
        log.debug("data-service /health probe failed: %s", type(exc).__name__)
        return {"data_service": "down", "db_read_only": False}


@router.get("/upstream")
async def upstream_health() -> dict[str, Any]:
    """The cached data-service verdict for the shell strip (5 s cache, single-flight)."""
    global _cached, _cached_at
    if _cached is not None and time.monotonic() - _cached_at < CACHE_S:
        return {**_cached, "cached": True}
    async with _lock:
        if _cached is not None and time.monotonic() - _cached_at < CACHE_S:
            return {**_cached, "cached": True}
        verdict = await _probe()
        verdict["as_of"] = round(time.time(), 3)
        _cached, _cached_at = verdict, time.monotonic()
        return {**verdict, "cached": False}
