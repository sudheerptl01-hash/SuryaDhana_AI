"""G3 addition: the drivers' fit gate at its boundary. B1's ``tests/test_index_drivers.py`` proves a clean fixture is not
degraded and a 100-point residual frame is; PLAN 1.7 states the rule as "60-session MAE ≤ 25 pts else ``fit.degraded``", so
this pins the threshold itself (24.99 passes, 25.01 degrades), the 60-session window (an old blow-up outside it does not
count) and point-in-time reading (a bad session AFTER ``as_of`` is never seen)."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from data_health import db  # noqa: E402
from index_drivers import reads  # noqa: E402

NOW = datetime(2026, 11, 5, 0, 0)  # noqa: DTZ001 — computed_at is stored naive IST
COLS = ["index_name", "date", "actual_points", "explained_points", "residual_points", "index_level", "prev_index_level",
        "index_close_source", "weight_method", "members_priced", "members_total", "computed_at"]


@pytest.fixture
def store(tmp_path: Path):
    from storage.duckdb_store import DuckDBStore

    s = DuckDBStore(str(tmp_path / "fit.duckdb"))
    yield s
    s.close()


def _sessions(n: int, end: date = date(2026, 10, 30)) -> list[date]:
    out: list[date] = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _write(store, name: str, residuals: dict[date, float]) -> None:
    rows = [{"index_name": name, "date": d, "actual_points": 100.0 + r, "explained_points": 100.0, "residual_points": r,
             "index_level": 24000.0, "prev_index_level": 23900.0, "index_close_source": "nse_daily_file",
             "weight_method": "rebuilt",
             "members_priced": 50, "members_total": 50, "computed_at": NOW} for d, r in residuals.items()]
    db.upsert(store, "index_contribution_fit", pd.DataFrame(rows, columns=COLS), COLS,
              {"date": "DATE", "computed_at": "TIMESTAMP"})


def test_threshold_is_25_points_and_inclusive(store):
    days = _sessions(60)
    assert reads.MAE_DEGRADED == 25.0
    _write(store, "AT", {d: (24.99 if i % 2 else -24.99) for i, d in enumerate(days)})
    _write(store, "OVER", {d: (25.01 if i % 2 else -25.01) for i, d in enumerate(days)})
    at, over = reads.fit_stats(store, "AT", days[-1]), reads.fit_stats(store, "OVER", days[-1])
    assert at["mae_60s"] == 24.99 and at["degraded"] is False and at["sessions"] == 60
    assert over["mae_60s"] == 25.01 and over["degraded"] is True                 # negative control


def test_only_the_last_60_sessions_count_and_nothing_after_as_of(store):
    days = _sessions(90)
    old_blowup = {d: 500.0 for d in days[:30]}                                  # sessions 61–90 back: outside the window
    recent = {d: 5.0 for d in days[30:]}
    _write(store, "WIN", {**old_blowup, **recent})
    st = reads.fit_stats(store, "WIN", days[-1])
    assert st["sessions"] == 60 and st["mae_60s"] == 5.0 and st["degraded"] is False
    # negative control: move the window back so the blow-up is inside it → degraded
    assert reads.fit_stats(store, "WIN", days[45])["degraded"] is True
    # point in time: a terrible session after as_of is never read
    later = days[-1] + timedelta(days=3)
    _write(store, "WIN", {later: 10_000.0})
    assert reads.fit_stats(store, "WIN", days[-1])["mae_60s"] == 5.0
    assert reads.fit_stats(store, "WIN", later)["degraded"] is True


def test_no_fit_rows_is_degraded_never_a_pass(store):
    st = reads.fit_stats(store, "NOTHING", date(2026, 10, 30))
    assert st["degraded"] is True and st["mae_60s"] is None and st["sessions"] == 0
