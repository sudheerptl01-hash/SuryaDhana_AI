from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"


class Signal(BaseModel):
    ticker: str
    generated_at: datetime
    signal_date: date = Field(..., description="Date the signal is actionable (next trading day)")
    direction: SignalDirection
    prob_up: float = Field(..., ge=0.0, le=1.0, description="XGBoost classifier probability of UP")
    confidence: float = Field(..., ge=0.0, le=0.5, description="|prob_up - 0.5|, higher = more certain")
    expected_return_pct: float = Field(..., description="XGBoost regressor predicted 5-day return %")
    model_version: str
    features_snapshot: dict[str, float] = Field(default_factory=dict, description="Top-10 feature values at generation time")

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.12

    model_config = {"frozen": True, "protected_namespaces": ()}


class SignalBatch(BaseModel):
    signals: list[Signal]
    batch_date: date
    total_stocks_scanned: int

    @property
    def high_confidence_signals(self) -> list[Signal]:
        return [s for s in self.signals if s.is_high_confidence]

    def top_n(self, n: int = 20) -> list[Signal]:
        return sorted(self.signals, key=lambda s: s.confidence, reverse=True)[:n]
