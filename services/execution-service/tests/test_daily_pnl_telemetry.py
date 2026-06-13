"""C8 — daily-PnL telemetry must report the TRUE intraday hole, not just paid costs.

Regression guard for the observability defect in `_update_daily_pnl`: the persisted
`daily_pnl.total_pnl` figure used to be `-tx_costs_today`, which excluded unrealized
mark-to-market losses, while the *active* kill-switch (`check_daily_loss_limit`) already
evaluated `unrealized - tx_costs_today`. A risk officer watching the dashboard was blind
to a -1.9% MTM hole until the switch fired at -2%. These tests pin the two figures
together so they can never diverge again.
"""

import sqlite3
from pathlib import Path

import pytest

# The module under test lives at services/execution-service/live_execution.py.
import sys

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # services/execution-service

from live_execution import (  # noqa: E402
    ExecutionEngine,
    ExecutionMode,
    Position,
)


def _engine(tmp_path, initial_equity: float = 1_000_000.0) -> ExecutionEngine:
    db = tmp_path / "paper_trades.db"
    return ExecutionEngine(
        mode=ExecutionMode.PAPER,
        db_path=str(db),
        initial_equity=initial_equity,
    )


def _read_daily_row(engine: ExecutionEngine) -> sqlite3.Row:
    conn = sqlite3.connect(engine._db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM daily_pnl ORDER BY date DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "no daily_pnl row persisted"
    return row


def test_persisted_daily_loss_includes_unrealized_mtm(tmp_path):
    """The persisted total_pnl must be (unrealized - tx_costs), not just -tx_costs."""
    eng = _engine(tmp_path, initial_equity=1_000_000.0)
    # A -1.9% unrealized hole that has NOT yet been realised (no sell), plus small costs.
    eng._positions["RELIANCE"] = Position(
        symbol="RELIANCE", quantity=100, avg_entry_price=2_500.0,
        signal_source="XGBoost", entry_time="2026-06-13T09:30:00Z",
        unrealized_pnl=-18_000.0,
    )
    eng._positions["TCS"] = Position(
        symbol="TCS", quantity=50, avg_entry_price=3_800.0,
        signal_source="XGBoost", entry_time="2026-06-13T09:35:00Z",
        unrealized_pnl=-1_000.0,
    )
    eng._tx_costs_today = 500.0

    conn = sqlite3.connect(eng._db_path)
    try:
        eng._update_daily_pnl(conn)
        conn.commit()
    finally:
        conn.close()

    row = _read_daily_row(eng)
    expected = (-18_000.0 - 1_000.0) - 500.0  # unrealized - tx_costs = -19_500
    assert row["total_pnl"] == pytest.approx(expected)
    # The OLD (defective) behaviour would have persisted only -500.
    assert row["total_pnl"] != pytest.approx(-500.0)
    # loss_pct must reflect the true hole vs day-open equity.
    assert row["loss_pct"] == pytest.approx(expected / 1_000_000.0)
    assert row["loss_pct"] == pytest.approx(-0.0195)


def test_telemetry_matches_active_killswitch_figure(tmp_path):
    """Persisted telemetry figure must equal the figure the kill-switch evaluates."""
    eng = _engine(tmp_path, initial_equity=2_000_000.0)
    eng._positions["INFY"] = Position(
        symbol="INFY", quantity=200, avg_entry_price=1_500.0,
        signal_source="RL Agent", entry_time="2026-06-13T10:00:00Z",
        unrealized_pnl=-25_000.0,
    )
    eng._tx_costs_today = 1_250.0

    # Reproduce exactly what check_daily_loss_limit computes (live_execution.py:753-755).
    unrealized = sum(p.unrealized_pnl for p in eng._positions.values())
    killswitch_daily_pnl = unrealized - eng._tx_costs_today

    conn = sqlite3.connect(eng._db_path)
    try:
        eng._update_daily_pnl(conn)
        conn.commit()
    finally:
        conn.close()

    row = _read_daily_row(eng)
    assert row["total_pnl"] == pytest.approx(killswitch_daily_pnl)
    assert row["unrealized_pnl"] == pytest.approx(unrealized)


def test_unrealized_gain_offsets_tx_costs(tmp_path):
    """A winning intraday book should show a smaller net loss (or a profit), not -tx only."""
    eng = _engine(tmp_path, initial_equity=500_000.0)
    eng._positions["HDFCBANK"] = Position(
        symbol="HDFCBANK", quantity=100, avg_entry_price=1_600.0,
        signal_source="Manual", entry_time="2026-06-13T11:00:00Z",
        unrealized_pnl=+8_000.0,  # winning position
    )
    eng._tx_costs_today = 300.0

    conn = sqlite3.connect(eng._db_path)
    try:
        eng._update_daily_pnl(conn)
        conn.commit()
    finally:
        conn.close()

    row = _read_daily_row(eng)
    # +8000 unrealized gain - 300 costs = +7700 net (a profit, correctly surfaced).
    assert row["total_pnl"] == pytest.approx(7_700.0)
    assert row["total_pnl"] > 0.0
