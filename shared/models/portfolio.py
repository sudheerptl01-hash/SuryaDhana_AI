from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class Position(BaseModel):
    ticker: str
    quantity: int = Field(..., gt=0)
    avg_entry_price: float = Field(..., gt=0)
    entry_date: date
    stop_loss_price: float
    take_profit_price: float
    holding_days: int = 0
    current_price: float | None = None
    signal_id: str | None = None

    @property
    def cost_basis_inr(self) -> float:
        return self.quantity * self.avg_entry_price

    @property
    def current_value_inr(self) -> float | None:
        if self.current_price is None:
            return None
        return self.quantity * self.current_price

    @property
    def unrealised_pnl_inr(self) -> float | None:
        val = self.current_value_inr
        if val is None:
            return None
        return val - self.cost_basis_inr

    @property
    def unrealised_pnl_pct(self) -> float | None:
        pnl = self.unrealised_pnl_inr
        if pnl is None:
            return None
        return (pnl / self.cost_basis_inr) * 100

    @property
    def should_stop_loss(self) -> bool:
        if self.current_price is None:
            return False
        return self.current_price <= self.stop_loss_price

    @property
    def should_take_profit(self) -> bool:
        if self.current_price is None:
            return False
        return self.current_price >= self.take_profit_price

    @property
    def should_time_exit(self) -> bool:
        return self.holding_days >= 5


class Portfolio(BaseModel):
    positions: list[Position] = Field(default_factory=list)
    cash_inr: float = Field(..., ge=0)
    max_positions: int = 5
    max_position_pct: float = 0.15
    max_sector_pct: float = 0.40

    @property
    def total_value_inr(self) -> float:
        invested = sum(p.cost_basis_inr for p in self.positions)
        return self.cash_inr + invested

    @property
    def invested_pct(self) -> float:
        if self.total_value_inr == 0:
            return 0.0
        invested = sum(p.cost_basis_inr for p in self.positions)
        return invested / self.total_value_inr

    @property
    def has_open_slot(self) -> bool:
        return len(self.positions) < self.max_positions

    def position_for(self, ticker: str) -> Position | None:
        for p in self.positions:
            if p.ticker == ticker:
                return p
        return None


class PortfolioSnapshot(BaseModel):
    snapshot_at: datetime
    portfolio: Portfolio
    total_value_inr: float
    daily_pnl_inr: float
    daily_pnl_pct: float
    cumulative_return_pct: float
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
