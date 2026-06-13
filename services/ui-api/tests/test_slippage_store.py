"""
C6 (§4.8) — slippage table round-trip + defensive-write tests.

Hermetic: every test writes to a tmp DuckDB file, never the live market.duckdb.
"""
import os
import sys

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import slippage_store as ss  # noqa: E402


def _sample_row(ticker="THIN"):
    return {
        "ticker": ticker,
        "entry_date": "2024-01-01",
        "arrival_price": 1000.0,
        "realised_vwap": 1010.25,
        "alloc": 2e7,
        "adv": 1e7,
        "participation": 2.0,
        "n_slices": 65,
        "n_sessions": 5,
        "fill_ratio": 0.459,
        "is_bps": 102.4,
        "y_i": 1.5,
        "unfilled_notional": 1.08e8,
        "atr_pct": 3.24,
    }


def test_ensure_table_creates_slippage_schema(tmp_path):
    db = str(tmp_path / "m.duckdb")
    assert ss.ensure_slippage_table(db) is True
    con = duckdb.connect(db, read_only=True)
    # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk) — name is [1].
    cols = {r[1] for r in con.execute("PRAGMA table_info('slippage')").fetchall()}
    con.close()
    for expected in ("run_id", "ticker", "arrival_price", "realised_vwap",
                     "participation", "n_slices", "is_bps", "y_i"):
        assert expected in cols


def test_collector_round_trip(tmp_path):
    db = str(tmp_path / "m.duckdb")
    col = ss.SlippageCollector(run_id="run-123", side="BUY", db_path=db)
    col.add(_sample_row("AAA"))
    col.add(_sample_row("BBB"))
    assert col.n_buffered == 2
    status = col.flush()
    assert status["ok"] is True
    assert status["written"] == 2

    con = duckdb.connect(db, read_only=True)
    rows = con.execute(
        "SELECT ticker, arrival_price, realised_vwap, participation, n_slices, "
        "is_bps, y_i, run_id FROM slippage ORDER BY ticker"
    ).fetchall()
    con.close()
    assert len(rows) == 2
    assert rows[0][0] == "AAA"
    assert rows[0][1] == pytest.approx(1000.0)
    assert rows[0][2] == pytest.approx(1010.25)
    assert rows[0][4] == 65          # n_slices persisted as INTEGER
    assert rows[0][6] == pytest.approx(1.5)   # y_i
    assert rows[0][7] == "run-123"


def test_flush_empty_is_noop(tmp_path):
    db = str(tmp_path / "m.duckdb")
    col = ss.SlippageCollector(run_id="empty", db_path=db)
    status = col.flush()
    assert status["ok"] is True
    assert status["written"] == 0


def test_write_failure_never_raises(tmp_path):
    # Point at an un-writable path; flush must return ok=False, NOT raise.
    bad_db = "/nonexistent_dir_xyz/cannot/write/here.duckdb"
    col = ss.SlippageCollector(run_id="boom", db_path=bad_db)
    col.add(_sample_row())
    status = col.flush()   # must not raise
    assert status["ok"] is False
    assert status["written"] == 0
    assert status["reason"]


def test_add_tolerates_malformed_row(tmp_path):
    db = str(tmp_path / "m.duckdb")
    col = ss.SlippageCollector(run_id="malformed", db_path=db)
    # Missing keys + wrong types must be coerced to defaults, not crash.
    col.add({"ticker": "X", "arrival_price": "not-a-number", "n_slices": None})
    status = col.flush()
    assert status["ok"] is True
    assert status["written"] == 1
    con = duckdb.connect(db, read_only=True)
    r = con.execute("SELECT ticker, arrival_price, n_slices FROM slippage").fetchone()
    con.close()
    assert r[0] == "X"
    assert r[1] == pytest.approx(0.0)   # coerced default
    assert r[2] == 0
