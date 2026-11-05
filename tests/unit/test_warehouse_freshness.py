"""Warehouse freshness is measured in trading sessions, not calendar days (offline)."""
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/data-service"))

from storage.duckdb_store import DuckDBStore, missed_weekday_sessions  # noqa: E402

FRI, SAT, SUN, MON, TUE, WED = (date(2026, 9, d) for d in (25, 26, 27, 28, 29, 30))


def test_weekend_and_same_day_are_not_missed_sessions():
    assert missed_weekday_sessions(FRI, SAT) == 0
    assert missed_weekday_sessions(FRI, SUN) == 0
    assert missed_weekday_sessions(FRI, MON) == 0   # Monday's bar only lands at the EOD run
    assert missed_weekday_sessions(FRI, FRI) == 0
    assert missed_weekday_sessions(SUN, FRI) == 0   # clock skew never goes negative


def test_missing_weekdays_are_counted():
    assert missed_weekday_sessions(FRI, TUE) == 1   # Monday missing
    assert missed_weekday_sessions(FRI, WED) == 2


def _bars(ticker: str, dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "ticker": ticker, "date": dates, "open": 10.0, "high": 11.0, "low": 9.0,
        "close": 10.5, "volume": 1000, "adjusted_close": 10.5,
    })


def test_ohlcv_meta_reports_sessions_behind_latest_session(tmp_path):
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    sessions = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]
    store.upsert_ohlcv(_bars("CURRENT", sessions), source="test")
    store.upsert_ohlcv(_bars("LAGGING", sessions[:3]), source="test")
    meta = {r["ticker"]: r for r in store.get_ohlcv_meta_all()}
    assert meta["CURRENT"]["sessions_behind"] == 0
    assert meta["LAGGING"]["sessions_behind"] == 2
