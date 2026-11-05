"""
Telemetry router — proxies master-controller scheduler data + local psutil metrics.
Exposes: /api/telemetry/status | /api/telemetry/logs | /api/telemetry/logs/stream
         /api/telemetry/autopilot | /api/telemetry/metrics
"""
from __future__ import annotations

import asyncio
import os
import time as _time
from datetime import datetime
from typing import Any, AsyncIterator

import httpx
import psutil
import pytz
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

IST = pytz.timezone("Asia/Kolkata")
MASTER_CTL_URL = os.getenv("MASTER_CONTROLLER_URL", "http://master-controller:8008")
EXECUTION_SVC  = os.getenv("EXECUTION_SERVICE_URL", "http://execution-service:8006")


async def _probe_broker_latency() -> float | None:
    try:
        t0 = _time.perf_counter()
        async with httpx.AsyncClient(timeout=3) as client:
            await client.get(f"{EXECUTION_SVC}/health")
        return round((_time.perf_counter() - t0) * 1000, 1)
    except Exception:
        return None


async def _fetch_scheduler_status() -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MASTER_CTL_URL}/api/scheduler/status")
            return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


# ── Status (aggregate) ────────────────────────────────────────────────────────
@router.get("/caches")
def get_cache_stats():
    """Every bounded TTLCache in this process: size vs bound, hits/misses/evictions (S1 observability)."""
    from cache import cache_stats
    return {"caches": cache_stats()}


@router.get("/status")
async def get_telemetry_status() -> dict[str, Any]:
    scheduler_data, broker_ms = await asyncio.gather(
        _fetch_scheduler_status(),
        _probe_broker_latency(),
    )

    cpu_pct = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()

    # Merge broker latency: prefer master-controller's probe (it measures
    # execution-service directly from its own network); fall back to local probe.
    if scheduler_data and scheduler_data.get("broker_latency_ms") is not None:
        broker_ms = scheduler_data["broker_latency_ms"]

    return {
        "scheduler": scheduler_data,
        "system": {
            "cpu_pct": round(cpu_pct, 1),
            "mem_pct": round(mem.percent, 1),
            "mem_used_gb": round(mem.used / 1e9, 2),
            "mem_total_gb": round(mem.total / 1e9, 2),
        },
        "broker_latency_ms": broker_ms,
        "ist_now": datetime.now(IST).isoformat(),
        "master_controller_online": scheduler_data is not None,
    }


# ── Log tail (REST) ───────────────────────────────────────────────────────────
@router.get("/logs")
async def get_telemetry_logs(limit: int = 100) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{MASTER_CTL_URL}/api/scheduler/logs",
                params={"limit": limit},
            )
            return resp.json() if resp.status_code == 200 else []
    except Exception:
        return []


# ── SSE log stream (proxied from master-controller) ───────────────────────────
@router.get("/logs/stream")
async def stream_logs(request: Request) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET", f"{MASTER_CTL_URL}/api/scheduler/logs/stream"
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        if await request.is_disconnected():
                            return
                        yield chunk
        except Exception as exc:
            err = f'{{"level":"ERROR","job":"proxy","msg":"Master controller stream lost: {exc}"}}'
            yield f"data: {err}\n\n".encode()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Autopilot ─────────────────────────────────────────────────────────────────
class AutopilotRequest(BaseModel):
    enabled: bool


@router.get("/autopilot")
async def get_autopilot() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MASTER_CTL_URL}/api/scheduler/autopilot")
            return resp.json() if resp.status_code == 200 else {"enabled": False, "error": "disconnected"}
    except Exception:
        return {"enabled": False, "error": "master-controller offline"}


@router.post("/autopilot")
async def set_autopilot(req: AutopilotRequest) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{MASTER_CTL_URL}/api/scheduler/autopilot",
                json={"enabled": req.enabled},
            )
            return resp.json() if resp.status_code == 200 else {"error": "master-controller unreachable"}
    except Exception as exc:
        return {"error": str(exc)}


class IciciRefreshRequest(BaseModel):
    force: bool = False


@router.post("/icici-refresh")
async def icici_refresh(req: IciciRefreshRequest | None = None, force: int = 0) -> dict[str, Any]:
    """BRKR 'CHECK SESSION / LOG IN IF EXPIRED' (PLAN §g step 4): server-side proxy to the controller's
    POST /api/scheduler/icici-refresh[?force=1] (the webview is pinned to :8010; the controller has no CORS by design).
    Never answers 404 on a controller failure: the panel reads 404/405 as 'proxy not in this release'."""
    use_force = bool(force) or bool(req and req.force)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{MASTER_CTL_URL}/api/scheduler/icici-refresh", params={"force": 1} if use_force else None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"master-controller unreachable: {type(exc).__name__}") from exc
    try:
        body = resp.json()
    except ValueError:
        body = {"detail": resp.text[:200]}
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"controller_status": resp.status_code, **(body if isinstance(body, dict) else {})})
    return {"started": True, "force": use_force, **(body if isinstance(body, dict) else {})}


# ── Latency metrics ───────────────────────────────────────────────────────────
@router.get("/metrics")
async def get_telemetry_metrics() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{MASTER_CTL_URL}/api/scheduler/metrics")
            return resp.json() if resp.status_code == 200 else {}
    except Exception:
        return {"error": "master-controller offline"}
