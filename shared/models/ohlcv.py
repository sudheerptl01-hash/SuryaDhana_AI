from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator


class OHLCV(BaseModel):
    ticker: str
    date: date
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: int = Field(..., ge=0)
    adjusted_close: float = Field(..., gt=0)

    @model_validator(mode="after")
    def validate_ohlc_consistency(self) -> "OHLCV":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) < low ({self.low}) for {self.ticker} on {self.date}")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"open ({self.open}) outside [low, high] range for {self.ticker} on {self.date}")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"close ({self.close}) outside [low, high] range for {self.ticker} on {self.date}")
        return self

    model_config = {"frozen": True}


class OHLCVBatch(BaseModel):
    ticker: str
    records: list[OHLCV]
    source: str = Field(..., description="'yfinance' or 'icici_breeze'")

    @property
    def date_range(self) -> tuple[date, date] | None:
        if not self.records:
            return None
        dates = [r.date for r in self.records]
        return min(dates), max(dates)
