"""C4 — persistent cross-campaign research-trial ledger.

Validates the round-trip persistence, config_hash dedupe (identical re-runs do not
inflate N), source/since filtering, the distinct-vs-raw count semantics, and the
defensive-write contract (a bad path never raises — flush reports the failure, the
reader returns a neutral 0 so DSR falls back to the per-run count).

Every test isolates a throwaway DuckDB file via tmp_path; the live store is untouched.
"""
import os
import sys

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trial_ledger as tl  # noqa: E402


def _db(tmp_path):
    return str(tmp_path / "campaign.duckdb")


# ── Schema + round-trip ─────────────────────────────────────────────────────────────

def test_ensure_table_creates_research_trials_schema(tmp_path):
    db = _db(tmp_path)
    assert tl.ensure_research_trials_table(db) is True
    con = duckdb.connect(db, read_only=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info('research_trials')").fetchall()]
    con.close()
    for expected in ("trial_id", "run_id", "ts", "source", "config_hash",
                     "sharpe", "n_obs", "skew", "kurtosis", "daily_returns_ref"):
        assert expected in cols


def test_ledger_round_trip(tmp_path):
    db = _db(tmp_path)
    led = tl.TrialLedger(run_id="grid-1", source="grid_combo", db_path=db)
    led.record(sharpe=1.4, config=["VMI", "VIPT"], n_obs=900, skew=-0.3, kurtosis=4.1)
    led.record(sharpe=0.8, config=["VMI"], n_obs=900, skew=0.1, kurtosis=3.2)
    res = led.flush()
    assert res["ok"] is True
    assert res["written"] == 2
    con = duckdb.connect(db, read_only=True)
    rows = con.execute("SELECT source, sharpe, n_obs FROM research_trials ORDER BY sharpe").fetchall()
    con.close()
    assert len(rows) == 2
    assert rows[1][0] == "grid_combo"
    assert rows[1][1] == pytest.approx(1.4)
    assert rows[1][2] == 900


# ── config_hash dedupe ──────────────────────────────────────────────────────────────

def test_config_hash_is_order_independent_and_deterministic():
    h1 = tl.config_hash({"a": 1, "b": 2})
    h2 = tl.config_hash({"b": 2, "a": 1})
    assert h1 == h2
    assert tl.config_hash(["VMI", "VIPT"]) == tl.config_hash(["VMI", "VIPT"])
    assert tl.config_hash(["VMI"]) != tl.config_hash(["VIPT"])


def test_dedupe_collapses_identical_reruns(tmp_path):
    db = _db(tmp_path)
    # First campaign: two distinct configs.
    a = tl.TrialLedger(run_id="run-A", source="grid_combo", db_path=db)
    a.record(sharpe=1.0, config=["VMI", "VIPT"], n_obs=800)
    a.record(sharpe=0.5, config=["VMI"], n_obs=800)
    assert a.flush()["written"] == 2
    # Re-run the IDENTICAL campaign: same config hashes -> all deduped, N not inflated.
    b = tl.TrialLedger(run_id="run-B", source="grid_combo", db_path=db)
    b.record(sharpe=1.05, config=["VMI", "VIPT"], n_obs=800)   # same combo, new run
    b.record(sharpe=0.55, config=["VMI"], n_obs=800)
    res = b.flush()
    assert res["written"] == 0
    assert res["skipped"] == 2
    assert tl.count_trials(db_path=db) == 2          # distinct config count unchanged
    # A genuinely NEW combo is added.
    c = tl.TrialLedger(run_id="run-C", source="grid_combo", db_path=db)
    c.record(sharpe=1.3, config=["VMI", "VIPT", "Intention"], n_obs=800)
    assert c.flush()["written"] == 1
    assert tl.count_trials(db_path=db) == 3


def test_intra_batch_duplicates_collapse(tmp_path):
    db = _db(tmp_path)
    led = tl.TrialLedger(run_id="dup", source="grid_combo", db_path=db)
    led.record(sharpe=1.0, config=["VMI"], n_obs=500)
    led.record(sharpe=2.0, config=["VMI"], n_obs=500)   # same hash within one flush
    res = led.flush()
    assert res["written"] == 1
    assert res["skipped"] == 1


def test_dedupe_off_keeps_all_rows(tmp_path):
    db = _db(tmp_path)
    led = tl.TrialLedger(run_id="raw", source="grid_combo", db_path=db)
    led.record(sharpe=1.0, config=["VMI"], n_obs=500)
    led.record(sharpe=2.0, config=["VMI"], n_obs=500)
    assert led.flush(dedupe=False)["written"] == 2
    assert tl.count_trials(db_path=db, distinct=True) == 1     # 1 distinct config
    assert tl.count_trials(db_path=db, distinct=False) == 2    # 2 raw rows


# ── source + since filtering, reader ────────────────────────────────────────────────

def test_count_trials_filters_by_source(tmp_path):
    db = _db(tmp_path)
    g = tl.TrialLedger(run_id="g", source="grid_combo", db_path=db)
    g.record(sharpe=1.0, config=["VMI"], n_obs=500)
    g.record(sharpe=0.9, config=["VIPT"], n_obs=500)
    g.flush()
    w = tl.TrialLedger(run_id="w", source="wfo_window_select", db_path=db)
    w.record(sharpe=1.1, config=["VMI", "Squeeze"], n_obs=90)
    w.flush()
    assert tl.count_trials(db_path=db) == 3
    assert tl.count_trials(db_path=db, source="grid_combo") == 2
    assert tl.count_trials(db_path=db, source="wfo_window_select") == 1


def test_read_trial_sharpes_distinct(tmp_path):
    db = _db(tmp_path)
    led = tl.TrialLedger(run_id="s", source="grid_combo", db_path=db)
    led.record(sharpe=1.0, config=["VMI"], n_obs=500)
    led.record(sharpe=0.5, config=["VIPT"], n_obs=500)
    led.flush()
    sharpes = tl.read_trial_sharpes(db_path=db)
    assert sorted(sharpes) == pytest.approx([0.5, 1.0])


def test_invalid_source_normalised_to_manual(tmp_path):
    db = _db(tmp_path)
    led = tl.TrialLedger(run_id="x", source="not_a_real_source", db_path=db)
    assert led.source == "manual_backtest"
    led.record(sharpe=1.0, config=["VMI"], n_obs=500)
    led.flush()
    assert tl.count_trials(db_path=db, source="manual_backtest") == 1


# ── Defensive contract ──────────────────────────────────────────────────────────────

def test_flush_empty_is_noop(tmp_path):
    led = tl.TrialLedger(run_id="empty", db_path=_db(tmp_path))
    res = led.flush()
    assert res["ok"] is True
    assert res["written"] == 0


def test_write_failure_never_raises(tmp_path):
    bad = str(tmp_path / "no_such_dir" / "x.duckdb")
    led = tl.TrialLedger(run_id="boom", db_path=bad)
    led.record(sharpe=1.0, config=["VMI"], n_obs=500)
    res = led.flush()                # must not raise
    assert res["ok"] is False
    assert res["written"] == 0


def test_count_trials_missing_table_returns_zero(tmp_path):
    # Fresh DB with no research_trials table -> reader returns 0, not an error.
    db = _db(tmp_path)
    duckdb.connect(db).close()       # create the file, no table
    assert tl.count_trials(db_path=db) == 0
    assert tl.read_trial_sharpes(db_path=db) == []


def test_record_tolerates_nan_and_missing_fields(tmp_path):
    db = _db(tmp_path)
    led = tl.TrialLedger(run_id="nan", source="grid_combo", db_path=db)
    led.record(sharpe=float("nan"), config=["VMI"], n_obs=500)   # NaN sharpe -> 0.0
    res = led.flush()
    assert res["written"] == 1
    con = duckdb.connect(db, read_only=True)
    val = con.execute("SELECT sharpe FROM research_trials").fetchone()[0]
    con.close()
    assert val == pytest.approx(0.0)
