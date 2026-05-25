from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Stock(BaseModel):
    ticker: str = Field(..., description="NSE ticker symbol, e.g. RELIANCE.NS")
    name: str
    sector: str
    industry: str
    market_cap_cr: float = Field(..., gt=0, description="Market cap in INR Crore")
    avg_daily_volume_cr: float = Field(..., gt=0, description="Avg daily traded volume in INR Crore")
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    roe_pct: float | None = None
    debt_to_equity: float | None = None
    is_active: bool = True

    @field_validator("ticker")
    @classmethod
    def ticker_uppercase(cls, v: str) -> str:
        return v.upper()

    model_config = {"frozen": True}


class StockUniverse(BaseModel):
    stocks: list[Stock]
    version: str = Field(..., description="Lock version, e.g. 'v1-2024-05-22'")

    @property
    def tickers(self) -> list[str]:
        return [s.ticker for s in self.stocks]

    def by_sector(self) -> dict[str, list[Stock]]:
        result: dict[str, list[Stock]] = {}
        for s in self.stocks:
            result.setdefault(s.sector, []).append(s)
        return result
