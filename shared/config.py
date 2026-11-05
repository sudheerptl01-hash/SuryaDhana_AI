from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, SecretStr, field_validator

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover
    from pydantic import BaseSettings, SettingsConfigDict

# Resolve absolute project root once so services work regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Search for .env in this file's parent directory (project root) so that
# services launched from their own subdirectory still pick up the root .env
_ENV_FILE = _PROJECT_ROOT / ".env"


def load_env_into_process() -> bool:
    """Export the project ``.env`` into ``os.environ`` (without overriding).

    ``Settings`` reads .env into its own fields only, but several modules read
    ``os.environ`` directly (ICICI credentials in shared/icici.py, service URLs).
    Docker injects .env via ``env_file``; a locally launched uvicorn does not, so
    call this once at service start-up. Existing variables (e.g. compose
    ``environment:`` overrides) always win.
    """
    if not _ENV_FILE.exists():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    return bool(load_dotenv(_ENV_FILE, override=False))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
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
    duckdb_path: str = str(_PROJECT_ROOT / "data" / "market.duckdb")

    # ── Redis ─────────────────────────────────────────────────────────────────
    # redis_url may embed the password (redis://:<pw>@127.0.0.1:6379/0); start-local.sh exports it that way when
    # REDIS_PASSWORD (.env) or the Keychain item 'suryadhana-redis' is set (Wave 0.7, O-T10). Kept a plain str
    # because every client parses it as a URL; redis_password itself is a SecretStr.
    redis_url: str = "redis://redis:6379/0"
    redis_password: SecretStr = Field(default=SecretStr(""), description="requirepass for the local redis-server (optional)")
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # ── ICICI Direct Breeze API ────────────────────────────────────────────────
    # Secrets are SecretStr (Terminal v2 Wave 0.7, O-T10): repr/str/model_dump_json show '**********'; a caller
    # that needs the value says so with .get_secret_value(). A stray print(settings) can no longer leak them.
    icici_api_key: SecretStr = Field(default=SecretStr(""), description="ICICI Breeze API key")
    icici_api_secret: SecretStr = Field(default=SecretStr(""), description="ICICI Breeze API secret")
    icici_session_token: SecretStr = Field(default=SecretStr(""), description="ICICI session token (refreshed daily)")
    # GOLD program (PLAN §d): the dated customs duty the India price stack uses, and the optional CFTC Socrata token.
    gold_import_duty_pct: float = Field(
        default=15.0, description="Customs duty on gold, % (BCD 10 + AIDC 5 since 2026-05-13; confirm at CBIC, O-3)"
    )
    gold_import_duty_effective: str = Field(
        default="2026-05-13", description="Effective date of gold_import_duty_pct (Notification 16/2026-Customs)"
    )
    cftc_app_token: SecretStr = Field(default=SecretStr(""),
                                      description="Optional CFTC Socrata app token (O-7); raises the COT API rate limit")

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
    telegram_bot_token: SecretStr = Field(default=SecretStr(""), description="Telegram bot token for alerts")
    telegram_chat_id: str = Field(default="", description="Telegram chat ID for alerts")

    # ── Data history ───────────────────────────────────────────────────────────
    historical_years: int = Field(default=5, description="Years of OHLCV history to fetch")

    # ── Backups (Wave 0.1; O-T1 decides the target) ────────────────────────────
    offsite_backup_dir: str = Field(default="", description="scripts/db_backup.py --offsite target (a mounted volume, "
                                    "an rclone mount or an external SSD); empty = no off-machine copy")

    # Public, non-secret settings are listed by the SYS page; this is the contract the leak test checks against.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("icici_api_key", "icici_api_secret", "icici_session_token",
                                               "telegram_bot_token", "cftc_app_token", "redis_password")

    @field_validator("stop_loss_pct", "max_position_pct", "max_sector_pct", "daily_loss_limit_pct", "max_drawdown_pct")
    @classmethod
    def pct_must_be_between_0_and_1(cls, v: float) -> float:
        if not 0 < v < 1:
            raise ValueError("Percentage values must be between 0 and 1 (exclusive)")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
