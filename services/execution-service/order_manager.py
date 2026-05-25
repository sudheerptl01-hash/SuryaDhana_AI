from __future__ import annotations

import uuid
from datetime import datetime

from shared.logging import get_logger
from shared.models import Order, OrderSide, OrderStatus, OrderType

from icici_client import ICICIOrderClient

logger = get_logger(__name__)


class OrderManager:
    """Manages order lifecycle: create → place → track → exit."""

    def __init__(self, client: ICICIOrderClient) -> None:
        self._client = client
        self._orders: dict[str, Order] = {}

    def create_buy_order(
        self,
        ticker: str,
        shares: int,
        limit_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        signal_id: str | None = None,
    ) -> Order:
        order = Order(
            order_id=str(uuid.uuid4()),
            ticker=ticker,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=shares,
            limit_price=round(limit_price * 0.98, 2),  # 2% below market (limit order)
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            status=OrderStatus.PENDING,
            created_at=datetime.utcnow(),
            signal_id=signal_id,
        )
        self._orders[order.order_id] = order
        return order

    def submit_order(self, order: Order) -> Order:
        try:
            broker_id = self._client.place_order(order)
            updated = order.model_copy(update={"status": OrderStatus.SUBMITTED, "broker_order_id": broker_id})
            self._orders[order.order_id] = updated
            logger.info("Order submitted", order_id=order.order_id, broker_id=broker_id)
            return updated
        except Exception as exc:
            rejected = order.model_copy(update={"status": OrderStatus.REJECTED})
            self._orders[order.order_id] = rejected
            logger.error("Order submission failed", order_id=order.order_id, error=str(exc))
            return rejected

    def create_sell_order(
        self,
        ticker: str,
        shares: int,
        reason: str = "signal",
    ) -> Order:
        order = Order(
            order_id=str(uuid.uuid4()),
            ticker=ticker,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=shares,
            status=OrderStatus.PENDING,
            created_at=datetime.utcnow(),
        )
        self._orders[order.order_id] = order
        logger.info("Sell order created", ticker=ticker, shares=shares, reason=reason)
        return order

    def get_pending_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)]

    def get_all_orders(self) -> list[Order]:
        return list(self._orders.values())
