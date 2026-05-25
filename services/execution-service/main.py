from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.models import OrderStatus

from icici_client import ICICIOrderClient
from order_manager import OrderManager

logger = get_logger(__name__)

_client: ICICIOrderClient | None = None
_manager: OrderManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _client, _manager
    settings = get_settings()
    configure_logging("execution-service", settings.log_level)
    _client = ICICIOrderClient(settings.icici_api_key, settings.icici_api_secret, settings.icici_session_token)
    _manager = OrderManager(_client)
    logger.info("Execution service started", stub_mode=_client.is_stub)
    yield
    logger.info("Execution service stopped")


app = FastAPI(title="SuryaDhana — Execution Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "execution-service", "stub_mode": _client.is_stub if _client else True}


class PlaceOrderRequest(BaseModel):
    ticker: str
    shares: int
    limit_price: float
    stop_loss_price: float
    take_profit_price: float
    signal_id: str | None = None


@app.post("/order/buy")
async def place_buy_order(req: PlaceOrderRequest) -> dict:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Execution service not ready")
    order = _manager.create_buy_order(
        ticker=req.ticker,
        shares=req.shares,
        limit_price=req.limit_price,
        stop_loss_price=req.stop_loss_price,
        take_profit_price=req.take_profit_price,
        signal_id=req.signal_id,
    )
    submitted = _manager.submit_order(order)
    return {"order_id": submitted.order_id, "broker_order_id": submitted.broker_order_id, "status": submitted.status}


class SellOrderRequest(BaseModel):
    ticker: str
    shares: int
    reason: str = "signal"


@app.post("/order/sell")
async def place_sell_order(req: SellOrderRequest) -> dict:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Execution service not ready")
    order = _manager.create_sell_order(req.ticker, req.shares, req.reason)
    submitted = _manager.submit_order(order)
    return {"order_id": submitted.order_id, "status": submitted.status}


@app.get("/orders/pending")
async def get_pending_orders() -> dict:
    if _manager is None:
        raise HTTPException(status_code=503, detail="Execution service not ready")
    orders = _manager.get_pending_orders()
    return {"count": len(orders), "orders": [o.model_dump() for o in orders]}
