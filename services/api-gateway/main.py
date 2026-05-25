from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger, set_correlation_id
from routers import data_router, signals_router

logger = get_logger(__name__)

SERVICE_URLS = {
    "data": lambda s: s.data_service_url,
    "feature": lambda s: s.feature_service_url,
    "ml": lambda s: s.ml_service_url,
    "rl": lambda s: s.rl_service_url,
    "risk": lambda s: s.risk_service_url,
    "execution": lambda s: s.execution_service_url,
    "monitoring": lambda s: s.monitoring_service_url,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging("api-gateway", settings.log_level)
    logger.info("API Gateway started", environment=settings.environment)
    yield
    logger.info("API Gateway stopped")


app = FastAPI(
    title="SuryaDhana AI — Trading System API",
    description="Quantitative trading system for NSE/BSE stocks (ML + RL + Execution)",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_router)
app.include_router(signals_router)


# ── Health & status ────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway", "version": "1.0.0"}


@app.get("/status")
async def system_status() -> dict:
    settings = get_settings()
    statuses = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url_fn in SERVICE_URLS.items():
            try:
                resp = await client.get(f"{url_fn(settings)}/health")
                statuses[name] = "up" if resp.status_code == 200 else "degraded"
            except Exception:
                statuses[name] = "down"
    overall = "healthy" if all(v == "up" for v in statuses.values()) else "degraded"
    return {"overall": overall, "services": statuses}


@app.get("/version")
async def version() -> dict:
    return {"version": "1.0.0", "system": "SuryaDhana AI"}
