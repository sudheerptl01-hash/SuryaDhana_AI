from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ────────────────────────────────────────────────────────────
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Service ports ──────────────────────────────────────────────────────────
    gateway_port: int = 8000
    data_service_port: int = 8001
    feature_service_port: int = 8002
    ml_service_port: int = 8003
    rl_service_port: int = 8004
    risk_service_port: int = 8005
    execution_service_port: int = 8006
    monitoring_service_port: int = 8007

    # ── Internal service URLs (used by gateway / inter-service calls) ──────────
    data_service_url: str = "http://data-service:8001"
    feature_service_url: str = "http://feature-service:8002"
    ml_service_url: str = "http://ml-service:8003"
    rl_service_url: str = "http://rl-service:8004"
    risk_service_url: str = "http://risk-service:8005"
    execution_service_url: str = "http://execution-service:8006"
    monitoring_service_url: str = "http://monitoring-service:8007"

    # ── Database ───────────────────────────────────────────────────────────────
    duckdb_path: str = "data/market.duckdb"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # ── ICICI Direct Breeze API ────────────────────────────────────────────────
    icici_api_key: str = Field(default="", description="ICICI Breeze API key")
    icici_api_secret: str = Field(default="", description="ICICI Breeze API secret")
    icici_session_token: str = Field(default="", description="ICICI session token (refreshed daily)")

    # ── Trading parameters ─────────────────────────────────────────────────────
    stock_universe_path: str = "data/NSE_1000_MIDCAP_500.csv"
    max_portfolio_positions: int = 5
    holding_period_days: int = 5
    stop_loss_pct: float = Field(default=0.02, description="2% below entry")
    take_profit_multiplier: float = Field(default=1.0, description="Exits at predicted return %")
    max_position_pct: float = Field(default=0.15, description="Max 15% per stock")
    max_sector_pct: float = Field(default=0.40, description="Max 40% per sector")
    daily_loss_limit_pct: float = Field(default=0.02, description="Stop trading if down 2% for the day")
    max_drawdown_pct: float = Field(default=0.20, description="Emergency stop at 20% drawdown")

    # ── ML parameters ─────────────────────────────────────────────────────────
    min_signal_confidence: float = Field(default=0.12, description="Min |prob_up - 0.5| to consider a signal")
    prediction_horizon_days: int = 5
    feature_lookback_days: int = 60

    # ── Monitoring / alerting ──────────────────────────────────────────────────
    telegram_bot_token: str = Field(default="", description="Telegram bot token for alerts")
    telegram_chat_id: str = Field(default="", description="Telegram chat ID for alerts")

    # ── Data history ───────────────────────────────────────────────────────────
    historical_years: int = Field(default=5, description="Years of OHLCV history to fetch")

    @field_validator("stop_loss_pct", "max_position_pct", "max_sector_pct", "daily_loss_limit_pct", "max_drawdown_pct")
    @classmethod
    def pct_must_be_between_0_and_1(cls, v: float) -> float:
        if not 0 < v < 1:
            raise ValueError("Percentage values must be between 0 and 1 (exclusive)")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
