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
    _root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(_root / ".env", override=False)
except ImportError:
    pass

from routers import dashboard, stocks, analytics, performance, positions


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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ui-api"}
