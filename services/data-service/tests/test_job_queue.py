"""DurableJobManager (job_queue.py, R2-QUEUE): persisted rows, one-per-kind dedupe, the lease + heartbeat,
kill-resume (expired lease → re-queued → adopted by the next submit), sync-row recording, and the compact
recent() view. The surface must stay a drop-in for jobs.JobManager ({job, created} and the legacy job keys),
because master_controller polls GET /jobs/{id} for status running|done|error."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from job_queue import DurableJobManager, default_db_path

LEGACY_KEYS = {"job_id", "kind", "status", "progress", "total", "started_at", "finished_at", "result", "error"}


def _wait(mgr: DurableJobManager, job_id: str, timeout: float = 10.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = mgr.get(job_id)
        if j and j["status"] not in ("running", "queued"):
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "job_queue.sqlite"


def test_submit_runs_persists_and_survives_restart(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    job, created = mgr.submit("refresh", lambda p: (p(3, 3), {"written": 7})[1])
    assert created and job["status"] in ("running", "done") and LEGACY_KEYS <= set(job)
    done = _wait(mgr, job["job_id"])
    assert done["status"] == "done" and done["result"] == {"written": 7} and done["finished_at"]
    mgr.close()

    # a fresh manager on the same file (a restart) still serves the row — the queue is the store
    mgr2 = DurableJobManager(db)
    j = mgr2.get(job["job_id"])
    assert j and j["status"] == "done" and j["result"] == {"written": 7} and LEGACY_KEYS <= set(j)
    assert any(x["job_id"] == job["job_id"] for x in mgr2.list())
    mgr2.close()


def test_one_job_per_kind_and_is_running(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    gate = threading.Event()
    j1, created1 = mgr.submit("bhavcopy", lambda p: (gate.wait(10), {"ok": True})[1])
    j2, created2 = mgr.submit("bhavcopy", lambda p: {"ok": False})
    assert created1 and not created2 and j2["job_id"] == j1["job_id"]
    assert mgr.is_running("bhavcopy") and not mgr.is_running("refresh")
    # drop-in for main._submit's response shape
    assert {**j2, "already_running": not created2}["already_running"] is True
    gate.set()
    assert _wait(mgr, j1["job_id"])["result"] == {"ok": True}
    assert not mgr.is_running("bhavcopy")
    mgr.close()


def test_error_is_persisted(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    def boom(p):
        raise ValueError("nope")
    job, _ = mgr.submit("build", boom)
    done = _wait(mgr, job["job_id"])
    assert done["status"] == "error" and "ValueError: nope" in done["error"] and done["result"] is None
    mgr.close()
    mgr2 = DurableJobManager(db)
    assert mgr2.get(job["job_id"])["status"] == "error"
    mgr2.close()


def test_kill_resume_expired_lease_is_requeued_and_adopted(db: Path):
    """The acceptance test: a crash mid-job leaves a leased running row; the next start re-queues it and the
    next submit of that kind adopts the same job_id (attempt 2) and re-runs."""
    mgr_a = DurableJobManager(db, lease_s=0.2, heartbeat_s=3600)   # no renewal: the 'crash'
    job, _ = mgr_a.submit("nse_positions", lambda p: (threading.Event().wait(), {})[1])   # blocks forever
    mgr_a.close()                                                   # heartbeat gone == process dead
    from datetime import datetime, timezone
    deadline = time.time() + 5
    while time.time() < deadline:                                   # wait out the 0.2 s lease
        with sqlite3.connect(db) as con:
            lease = con.execute("SELECT lease_expires_at FROM jobs WHERE job_id = ?", (job["job_id"],)).fetchone()[0]
        if lease and datetime.fromisoformat(lease) < datetime.now(timezone.utc):
            break
        time.sleep(0.05)

    mgr_b = DurableJobManager(db, heartbeat_s=60)                   # the restart
    row = mgr_b.get(job["job_id"])
    assert row["status"] == "queued" and row["requeued"] is True

    resumed, created = mgr_b.submit("nse_positions", lambda p: {"resumed": True})
    assert created and resumed["job_id"] == job["job_id"] and resumed["attempt"] == 2
    done = _wait(mgr_b, job["job_id"])
    assert done["status"] == "done" and done["result"] == {"resumed": True} and done["attempt"] == 2
    mgr_b.close()


def test_fresh_lease_of_live_pid_is_left_alone(db: Path):
    """A running row whose lease is current and whose pid is alive (this process) is NOT requeued."""
    mgr_a = DurableJobManager(db, lease_s=120, heartbeat_s=60)
    gate = threading.Event()
    job, _ = mgr_a.submit("gold:gold_overnight", lambda p: (gate.wait(10), {"ok": 1})[1])
    mgr_b = DurableJobManager(db, heartbeat_s=60)
    assert mgr_b.get(job["job_id"])["status"] == "running"
    gate.set()
    _wait(mgr_a, job["job_id"])
    mgr_a.close(); mgr_b.close()


def test_heartbeat_flushes_progress_and_extends_lease(db: Path):
    mgr = DurableJobManager(db, lease_s=120, heartbeat_s=3600)
    gate = threading.Event()

    def fn(progress):
        progress(42, 100)
        gate.wait(10)
        return {"ok": True}

    job, _ = mgr.submit("iv:iv_eod", fn)
    time.sleep(0.1)
    assert mgr.flush_heartbeat() == 1
    with sqlite3.connect(db) as con:
        progress, total, hb, lease = con.execute(
            "SELECT progress, total, heartbeat_at, lease_expires_at FROM jobs WHERE job_id = ?",
            (job["job_id"],)).fetchone()
    assert (progress, total) == (42, 100) and hb and lease and lease > hb
    gate.set()
    _wait(mgr, job["job_id"])
    mgr.close()


def test_record_sync_persists_row_and_returns_result_unchanged(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    out = mgr.record_sync("nse_index_closes", lambda: {"written": {"^NSEI": 26000.0}})
    assert out == {"written": {"^NSEI": 26000.0}}                   # the endpoint's contract is untouched
    rows = [r for r in mgr.recent() if r["kind"] == "nse_index_closes"]
    assert rows and rows[0]["status"] == "done"

    with pytest.raises(RuntimeError):
        mgr.record_sync("fii_dii_backfill", lambda: (_ for _ in ()).throw(RuntimeError("nse down")))
    err = [r for r in mgr.recent() if r["kind"] == "fii_dii_backfill"]
    assert err and err[0]["status"] == "error" and "nse down" in err[0]["error"]
    mgr.close()


def test_recent_is_compact_and_capped(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    for i in range(5):
        mgr.record_sync(f"k{i}", lambda i=i: {"i": i})
    rows = mgr.recent(3)
    assert len(rows) == 3 and all("result" not in r for r in rows)
    assert {"job_id", "kind", "status", "attempt", "requeued", "submitted_at", "finished_at",
            "duration_s"} <= set(rows[0])
    mgr.close()


def test_history_trim_keeps_cap(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60, keep=10)
    for _ in range(25):
        mgr.record_sync("trim", lambda: {"ok": True})
    with sqlite3.connect(db) as con:
        n = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert n <= 11      # keep + at most the row being inserted
    mgr.close()


def test_default_db_path_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JOB_QUEUE_DB", raising=False)
    assert default_db_path(tmp_path) == tmp_path / "job_queue.sqlite"
    monkeypatch.setenv("JOB_QUEUE_DB", str(tmp_path / "elsewhere.sqlite"))
    assert default_db_path(tmp_path) == tmp_path / "elsewhere.sqlite"
