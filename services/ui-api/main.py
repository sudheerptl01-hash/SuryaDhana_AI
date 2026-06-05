"""
SuryaDhana — UI API Service
Aggregates DuckDB data into UI-friendly payloads for the Next.js dashboard.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env from project root (two levels up from services/ui-api/)
try:
    from dotenv import load_dotenv
    candidates = [
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
        Path("/app/.env"),
    ]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate, override=False)
            break
except ImportError:
    pass

from routers import dashboard, stocks, analytics, performance, positions, config, pipeline, execution, telemetry, lw_scanner
from routers import monitor
from routers import data_proxy
from routers import alpha
from routers import ml_workspace


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[ui-api] started")
    yield
    print("[ui-api] stopped")


app = FastAPI(
    title="SuryaDhana — UI API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(stocks.router,    prefix="/api/stocks",    tags=["stocks"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(config.router,   prefix="/api/config",    tags=["config"])
app.include_router(pipeline.router,   prefix="/api/pipeline",   tags=["pipeline"])
app.include_router(execution.router,  prefix="/api/execution",  tags=["execution"])
app.include_router(telemetry.router,  prefix="/api/telemetry",  tags=["telemetry"])
app.include_router(lw_scanner.router, prefix="/api/lw",         tags=["lw-scanner"])
app.include_router(monitor.router,     prefix="/api/monitor",  tags=["monitor"])
app.include_router(data_proxy.router,  prefix="/api/data",     tags=["data-proxy"])
app.include_router(alpha.router,       prefix="/api/alpha",    tags=["alpha-discovery"])
app.include_router(ml_workspace.router, prefix="/api/ml",       tags=["ml-workspace"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ui-api"}
