"""F1.1 — .env.example truth: every live .env key is documented, and no real secret leaked.

The live .env is read ONLY inside this test for name/value comparison; nothing from it is
ever printed or asserted into failure messages.
"""
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
# Keys whose example value legitimately matches a common live value (non-secret constants).
NON_SECRET_OVERLAP_OK = {
    "ENVIRONMENT", "LOG_LEVEL", "DUCKDB_PATH", "DB_PATH", "DATA_DIR", "UI_MODE", "COST_PROFILE",
    "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "STOCK_UNIVERSE_PATH",
    "MAX_PORTFOLIO_POSITIONS", "HOLDING_PERIOD_DAYS", "STOP_LOSS_PCT", "TAKE_PROFIT_MULTIPLIER",
    "MAX_POSITION_PCT", "MAX_SECTOR_PCT", "DAILY_LOSS_LIMIT_PCT", "MAX_DRAWDOWN_PCT",
    "MIN_SIGNAL_CONFIDENCE", "PREDICTION_HORIZON_DAYS", "FEATURE_LOOKBACK_DAYS", "HISTORICAL_YEARS",
    "DATA_SERVICE_URL", "DATA_SVC_URL", "FEATURE_SERVICE_URL", "FEAT_SVC_URL", "ML_SERVICE_URL",
    "RL_SERVICE_URL", "RISK_SERVICE_URL", "EXECUTION_SERVICE_URL", "MONITORING_SERVICE_URL",
    "MASTER_CONTROLLER_URL", "UI_API_URL", "RL_TRAINER_PATH", "ICICI_AUTO_LOGIN", "DESK_ENABLED",
    "DESK_CAPITAL", "DESK_EQUITY_SHARE", "DESK_AVOID_BULK_BUY_DAYS", "DESK_LEDGER", "LIVE_TICKS",
    "AUTOPILOT_ENABLED", "AUTOPILOT_DEFAULT", "EXECUTION_MODE", "INITIAL_EQUITY",
    "NEWS_SCANNER_DEFAULT_EXCHANGE", "GOLD_LOG_ENABLED", "NIFTY_POLL_INTERVAL",
    "WATCHLIST_POLL_INTERVAL", "WATCHLIST_POLL_CONCURRENCY", "WATCHLIST_POLL_MAX_SYMBOLS",
    "DATA_JOBS_ENABLED", "DATA_JOB_TIMEOUT_SECS", "MAX_FEATURE_AGE_BUSINESS_DAYS", "BATCH_SIZE",
    "PAPER_PRICE_GUARD_PCT", "PAPER_TRADES_DB",
}
SECRET_KEYS = {"ICICI_API_KEY", "ICICI_API_SECRET", "ICICI_SESSION_TOKEN", "ICICI_CLIENT_ID",
               "ICICI_PASSWORD", "ICICI_MOBILE", "ICICI_TOTP_SECRET", "TELEGRAM_BOT_TOKEN",
               "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL", "FRED_API_KEY", "EIA_API_KEY",
               "HEALTHCHECK_PING_URL"}


def test_the_dead_man_ping_key_is_documented_empty():
    """SECREL-02: the off-machine dead-man key is in the example, with no value and a pointer to the RUNBOOK."""
    text = (ROOT / ".env.example").read_text()
    assert "\nHEALTHCHECK_PING_URL=\n" in text
    assert "'Off-machine dead-man ping'" in text


def test_every_live_key_is_documented_in_the_example():
    live = set(dotenv_values(ROOT / ".env"))
    example = set(dotenv_values(ROOT / ".env.example"))
    missing = sorted(live - example)
    assert missing == [], f".env keys missing from .env.example: {missing}"


def test_login_critical_keys_present_and_marked():
    text = (ROOT / ".env.example").read_text()
    for key in ("ICICI_CLIENT_ID", "ICICI_PASSWORD", "ICICI_MOBILE", "TELEGRAM_BOT_TOKEN"):
        assert f"\n{key}=" in text, f"{key} missing from .env.example"
    assert "LOGIN-CRITICAL" in text


def test_no_live_secret_value_leaked_into_the_example():
    live = dotenv_values(ROOT / ".env")
    example = dotenv_values(ROOT / ".env.example")
    leaked = [k for k, v in example.items()
              if v and k in live and live[k] and v == live[k] and k not in NON_SECRET_OVERLAP_OK]
    assert leaked == [], f"example value identical to live value for: {leaked}"
    # and secret keys must never carry a live value, whatever the overlap list says
    hard = [k for k in SECRET_KEYS if example.get(k) and live.get(k) and example[k] == live[k]]
    assert hard == []
