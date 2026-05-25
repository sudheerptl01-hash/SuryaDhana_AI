from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Fill(BaseModel):
    fill_id: str
    order_id: str
    filled_at: datetime
    quantity: int
    fill_price: float
    brokerage_inr: float = 0.0

    @property
    def fill_value_inr(self) -> float:
        return self.quantity * self.fill_price


class Order(BaseModel):
    order_id: str
    ticker: str
    side: OrderSide
    order_type: OrderType
    quantity: int = Field(..., gt=0)
    limit_price: float | None = Field(None, gt=0)
    stop_loss_price: float | None = Field(None, gt=0)
    take_profit_price: float | None = Field(None, gt=0)
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime
    filled_at: datetime | None = None
    fills: list[Fill] = Field(default_factory=list)
    signal_id: str | None = None
    broker_order_id: str | None = None

    @property
    def avg_fill_price(self) -> float | None:
        if not self.fills:
            return None
        total_qty = sum(f.quantity for f in self.fills)
        total_val = sum(f.fill_price * f.quantity for f in self.fills)
        return total_val / total_qty if total_qty else None

    @property
    def filled_quantity(self) -> int:
        return sum(f.quantity for f in self.fills)
