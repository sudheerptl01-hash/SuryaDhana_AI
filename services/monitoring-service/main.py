from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

from telegram_bot import TelegramAlertBot, AlertLevel
from metrics import (
    registry,
    portfolio_value, daily_pnl, daily_pnl_pct, open_positions,
    win_rate, sharpe_ratio, max_drawdown,
    signals_generated, high_confidence_signals, model_accuracy,
    orders_placed, orders_filled, orders_rejected,
    stop_losses_hit, take_profits_hit, time_stops_hit,
)

logger = get_logger(__name__)

_telegram: TelegramAlertBot | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _telegram
    settings = get_settings()
    configure_logging("monitoring-service", settings.log_level)
    _telegram = TelegramAlertBot(settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id)
    logger.info("Monitoring service started", telegram_stub=_telegram._stub)
    yield
    logger.info("Monitoring service stopped")


app = FastAPI(title="SuryaDhana — Monitoring Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "monitoring-service"}


# ── Prometheus metrics endpoint ────────────────────────────────────────────────

@app.get("/metrics")
async def metrics_endpoint() -> Response:
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


# ── Metric ingestion ───────────────────────────────────────────────────────────

class PortfolioMetricsRequest(BaseModel):
    total_value_inr: float
    daily_pnl_inr: float
    daily_pnl_pct_val: float
    num_positions: int
    win_rate_val: float = 0.0
    sharpe_ratio_val: float = 0.0
    max_drawdown_pct_val: float = 0.0


@app.post("/ingest/portfolio")
async def ingest_portfolio_metrics(req: PortfolioMetricsRequest) -> dict:
    portfolio_value.set(req.total_value_inr)
    daily_pnl.set(req.daily_pnl_inr)
    daily_pnl_pct.set(req.daily_pnl_pct_val)
    open_positions.set(req.num_positions)
    win_rate.set(req.win_rate_val)
    sharpe_ratio.set(req.sharpe_ratio_val)
    max_drawdown.set(req.max_drawdown_pct_val)
    return {"status": "ok"}


class SignalMetricsRequest(BaseModel):
    total_signals: int
    high_confidence_count: int
    ml_accuracy: float = 0.0


@app.post("/ingest/signals")
async def ingest_signal_metrics(req: SignalMetricsRequest) -> dict:
    signals_generated.inc(req.total_signals)
    high_confidence_signals.set(req.high_confidence_count)
    model_accuracy.set(req.ml_accuracy)
    return {"status": "ok"}


# ── Alerts ─────────────────────────────────────────────────────────────────────

class AlertRequest(BaseModel):
    level: str
    title: str
    body: str


@app.post("/alert/send")
async def send_alert(req: AlertRequest) -> dict:
    if _telegram is None:
        return {"status": "skipped", "reason": "telegram not initialised"}
    level = AlertLevel(req.level.upper())
    ok = await _telegram.send(level, req.title, req.body)
    return {"status": "sent" if ok else "failed"}


@app.post("/alert/daily-summary")
async def send_daily_summary(metrics: dict[str, Any]) -> dict:
    if _telegram is None:
        return {"status": "skipped"}
    ok = await _telegram.send_daily_summary(metrics)
    return {"status": "sent" if ok else "failed"}
