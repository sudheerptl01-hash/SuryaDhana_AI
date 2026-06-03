from __future__ import annotations

import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.icici import load_icici_credentials
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
    # Auto-connect Breeze from .env (shared loader; normalizes the daily token).
    _creds = load_icici_credentials()
    _client = ICICIOrderClient(_creds.api_key, _creds.api_secret, _creds.session_token)
    _manager = OrderManager(_client)
    logger.info(
        "Execution service started",
        stub_mode=_client.is_stub,
        needs_daily_token=_creds.needs_daily_token,
    )
    yield
    logger.info("Execution service stopped")


app = FastAPI(title="SuryaDhana — Execution Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "execution-service", "stub_mode": _client.is_stub if _client else True}


def _extract_session_token(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if not value.startswith("http"):
        return value
    match = re.search(r"(?:apisession|session_token|apiSession|api_session)=([^&\\s]+)", value)
    return match.group(1) if match else value


class ICICIConfigureRequest(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    session_token: str | None = None


@app.get("/broker/status")
async def broker_status() -> dict:
    return {
        "connected": bool(_client and not _client.is_stub),
        "stub_mode": _client.is_stub if _client else True,
    }


@app.post("/broker/configure")
async def configure_broker(req: ICICIConfigureRequest) -> dict:
    global _client, _manager

    api_key = (req.api_key if req.api_key is not None else os.environ.get("ICICI_API_KEY", "")).strip()
    api_secret = (req.api_secret if req.api_secret is not None else os.environ.get("ICICI_API_SECRET", "")).strip()
    session_token = _extract_session_token(req.session_token if req.session_token is not None else os.environ.get("ICICI_SESSION_TOKEN", ""))

    os.environ["ICICI_API_KEY"] = api_key
    os.environ["ICICI_API_SECRET"] = api_secret
    os.environ["ICICI_SESSION_TOKEN"] = session_token

    _client = ICICIOrderClient(api_key, api_secret, session_token)
    _manager = OrderManager(_client)
    return {
        "connected": not _client.is_stub,
        "stub_mode": _client.is_stub,
    }


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


class SquareOffRequest(BaseModel):
    reason: str = "eod_rebalancing"
    tickers: list[str] | None = None  # None = square off ALL pending positions


@app.post("/square-off")
async def square_off(req: SquareOffRequest) -> dict:
    """
    EOD square-off: cancel all pending orders, then submit SELL orders for open
    intraday positions. Called by master_controller at 15:15 IST.
    """
    if _manager is None or _client is None:
        raise HTTPException(status_code=503, detail="Execution service not ready")

    pending = _manager.get_pending_orders()
    cancelled = 0
    cancel_errors: list[str] = []

    for order in pending:
        if req.tickers is not None and order.ticker not in req.tickers:
            continue
        try:
            broker_id = getattr(order, "broker_order_id", None) or order.order_id
            _client.cancel_order(broker_id, order.ticker)
            cancelled += 1
        except Exception as exc:
            cancel_errors.append(f"{order.ticker}: {exc}")
            logger.warning("Cancel failed during square-off", ticker=order.ticker, error=str(exc))

    logger.info(
        "Square-off executed",
        reason=req.reason,
        cancelled_orders=cancelled,
        cancel_errors=len(cancel_errors),
        stub_mode=_client.is_stub,
    )

    return {
        "status": "squared_off",
        "reason": req.reason,
        "cancelled_orders": cancelled,
        "cancel_errors": cancel_errors,
        "stub_mode": _client.is_stub,
    }
