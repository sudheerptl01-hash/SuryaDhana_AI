from __future__ import annotations

from datetime import datetime
from typing import Any

from shared.logging import get_logger
from shared.models import Order, OrderStatus, OrderType, OrderSide

logger = get_logger(__name__)


class ICICIOrderClient:
    """
    Thin wrapper over ICICI Breeze for order placement and tracking.
    In development mode (no credentials), all order calls are stubbed.
    """

    def __init__(self, api_key: str, api_secret: str, session_token: str) -> None:
        self._api_key = api_key
        self._stub = not (api_key and api_secret and session_token)
        self._breeze: Any = None

        if not self._stub:
            self._connect(api_secret, session_token)

    def _connect(self, api_secret: str, session_token: str) -> None:
        try:
            from breeze_connect import BreezeConnect  # type: ignore[import]
            self._breeze = BreezeConnect(api_key=self._api_key)
            self._breeze.generate_session(api_secret=api_secret, session_token=session_token)
            logger.info("ICICI order client connected")
        except Exception as exc:
            logger.error("ICICI connection failed, falling back to stub", error=str(exc))
            self._stub = True

    def place_order(self, order: Order) -> str:
        """Places an order. Returns broker_order_id."""
        if self._stub:
            broker_id = f"STUB-{order.order_id[:8]}"
            logger.info("STUB order placed", ticker=order.ticker, side=order.side, qty=order.quantity, broker_id=broker_id)
            return broker_id

        stock_code = order.ticker.replace(".NS", "")
        order_type = "limit" if order.order_type == OrderType.LIMIT else "market"
        action = "buy" if order.side == OrderSide.BUY else "sell"

        response = self._breeze.place_order(
            stock_code=stock_code,
            exchange_code="NSE",
            product="cash",
            action=action,
            order_type=order_type,
            stoploss="0",
            quantity=str(order.quantity),
            price=str(order.limit_price) if order.limit_price else "0",
            validity="day",
        )
        if response.get("Status") != 200:
            raise RuntimeError(f"Order placement failed for {order.ticker}: {response}")

        broker_id = response["Success"]["order_id"]
        logger.info("Order placed", ticker=order.ticker, broker_id=broker_id)
        return broker_id

    def cancel_order(self, broker_order_id: str, ticker: str) -> bool:
        if self._stub:
            logger.info("STUB order cancelled", broker_order_id=broker_order_id)
            return True

        stock_code = ticker.replace(".NS", "")
        response = self._breeze.cancel_order(
            exchange_code="NSE",
            order_id=broker_order_id,
        )
        return response.get("Status") == 200

    def get_order_status(self, broker_order_id: str) -> dict:
        if self._stub:
            return {"status": "complete", "filled_qty": 0, "avg_price": 0.0}

        response = self._breeze.get_order_detail(
            exchange_code="NSE",
            order_id=broker_order_id,
        )
        if response.get("Status") != 200:
            return {"status": "error"}
        return response.get("Success", {})

    def get_portfolio(self) -> list[dict]:
        if self._stub:
            return []
        response = self._breeze.get_portfolio_holdings(
            exchange_code="NSE",
            from_date="",
            to_date="",
            stock_code="",
            portfolio_type="",
        )
        if response.get("Status") != 200:
            return []
        return response.get("Success", [])

    @property
    def is_stub(self) -> bool:
        return self._stub
