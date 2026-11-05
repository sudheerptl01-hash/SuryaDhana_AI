"""P14 — SYS lost every job's last run on each controller restart (all '—').

JobHistory persists last run, status and duration per job to a small JSON file (atomic temp + rename), armed only by
load() at controller start; /api/scheduler/status fills its existing last_* fields from it until a job runs again
in the new process, plus an additive `last_run_source`. Temp paths only: the real data/.scheduler_history.json is
never read or written here (and importing the controller never arms the real store).
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc


def test_importing_the_controller_never_arms_the_real_store():
    assert mc._history.path == ROOT / "data" / ".scheduler_history.json"
    assert mc._history._armed is False, "only lifespan() may arm the real history file"


def test_roundtrip_atomic_and_survives_a_restart(tmp_path):
    path = tmp_path / "data" / ".scheduler_history.json"
    h = mc.JobHistory(path)
    h.record("db_backup_daily", "done", 1234.567)
    assert not path.exists(), "not armed yet: nothing written"
    assert h.load() == 1                                        # absent file → empty; the earlier run is kept
    h.record("db_backup_daily", "error", 50.0, ts="2026-10-26T02:15:40+05:30")
    h.record("news_track_record_daily", "done", 22000.0, ts="2026-10-26T19:45:30+05:30")
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name], "no temp file left behind"
    saved = json.loads(path.read_text())
    assert saved["version"] == 1 and saved["jobs"]["db_backup_daily"]["runs"] == 2
    # a restart: a new process loads what the previous one saved
    h2 = mc.JobHistory(path)
    assert h2.load() == 2
    assert h2.get("db_backup_daily") == {"last_run_ts": "2026-10-26T02:15:40+05:30", "last_status": "error",
                                         "last_ms": 50.0, "runs": 2}
    assert h2.get("never_ran") is None


def test_garbage_or_wrong_shape_loads_empty_and_is_rewritten(tmp_path):
    path = tmp_path / "h.json"
    for bad in ("{garbage", "[1, 2]", json.dumps({"jobs": "nope"}), json.dumps({"jobs": {"x": 5}})):
        path.write_text(bad)
        assert mc.JobHistory(path).load() == 0
    h = mc.JobHistory(path)
    h.load()
    h.record("x", "done", 1.0)
    assert json.loads(path.read_text())["jobs"]["x"]["last_status"] == "done"


def test_a_failed_write_never_breaks_a_job(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    h = mc.JobHistory(blocker / "h.json")                       # parent is a file: every write fails
    h.load()
    h.record("a", "done", 1.0)
    h.record("b", "done", 1.0)
    assert h.get("b")["last_status"] == "done"                  # kept in memory
    assert capsys.readouterr().out.count("job history not saved") == 1      # warned once, not per job


@pytest.fixture()
def armed(monkeypatch, tmp_path):
    h = mc.JobHistory(tmp_path / "hist.json")
    h.load()
    monkeypatch.setattr(mc, "_history", h)
    monkeypatch.setattr(mc, "_latency", mc.LatencyTracker())
    return h


def test_track_records_done_error_and_soft_failures(armed):
    async def run(job, mode):
        try:
            async with mc._track(job):
                if mode == "raise":
                    raise RuntimeError("boom")
                if mode == "soft":
                    mc._mark_failed(job)
        except RuntimeError:
            pass
    asyncio.run(run("ok_job", "ok"))
    asyncio.run(run("raising_job", "raise"))
    asyncio.run(run("soft_job", "soft"))
    asyncio.run(run("soft_job", "ok"))            # the mark is per run: the next clean run is `done` again
    saved = json.loads(armed.path.read_text())["jobs"]
    assert saved["ok_job"]["last_status"] == "done" and saved["raising_job"]["last_status"] == "error"
    assert saved["soft_job"]["last_status"] == "done" and saved["soft_job"]["runs"] == 2
    asyncio.run(run("soft_job", "soft"))
    assert mc.JobHistory(armed.path).load() == 3
    assert json.loads(armed.path.read_text())["jobs"]["soft_job"]["last_status"] == "error"


def test_a_bad_row_never_breaks_the_job_that_owns_it(armed):
    """F4-OPS review: {'runs': 'n/a'} loaded fine, then every run of that job raised ValueError out of _track."""
    armed.path.write_text(json.dumps({"version": 1, "jobs": {"desk_daily": {"runs": "n/a", "last_status": "done"}}}))
    assert armed.load() == 1

    async def run():
        async with mc._track("desk_daily"):
            pass
    asyncio.run(run())
    row = json.loads(armed.path.read_text())["jobs"]["desk_daily"]
    assert row["runs"] == 1 and row["last_status"] == "done"


def _fake_scheduler(*ids):
    jobs = [SimpleNamespace(id=i, name=i.replace("_", " "), next_run_time=None) for i in ids]
    return SimpleNamespace(running=True, get_jobs=lambda: jobs)


@pytest.fixture()
def status_env(monkeypatch):
    async def no_probe():
        return None
    monkeypatch.setattr(mc, "_probe_broker_latency", no_probe)
    monkeypatch.setattr(mc, "scheduler", _fake_scheduler("db_backup_daily", "desk_daily", "never_ran"))


def test_status_after_a_restart_shows_the_persisted_last_run(status_env, armed, tmp_path):
    armed.record("db_backup_daily", "done", 4100.0, ts="2026-10-26T02:15:41+05:30")
    armed.record("desk_daily", "error", 900.0, ts="2026-10-23T19:30:02+05:30")
    restarted = mc.JobHistory(armed.path)                       # new process: empty tracker, history from disk
    restarted.load()
    mc._history = restarted
    jobs = {j["id"]: j for j in asyncio.run(mc.get_scheduler_status())["jobs"]}
    assert jobs["db_backup_daily"]["last_status"] == "done" and jobs["db_backup_daily"]["last_latency_ms"] == 4100.0
    assert jobs["db_backup_daily"]["last_run_ts"] == "2026-10-26T02:15:41+05:30"
    assert jobs["db_backup_daily"]["last_run_source"] == "history"
    assert jobs["desk_daily"]["last_status"] == "error"
    assert jobs["never_ran"]["last_status"] is None and jobs["never_ran"]["last_run_source"] is None
    # the existing contract is unchanged: every old key still present
    assert {"id", "name", "next_run_ist", "next_run_unix", "last_latency_ms", "avg_latency_ms", "last_status",
            "last_run_ts", "samples"} <= set(jobs["never_ran"])


def test_negative_control_without_history_the_restart_shows_nothing(status_env, monkeypatch, tmp_path):
    """The pre-fix behaviour: a fresh process with an empty tracker and no history file reports every job blank."""
    empty = mc.JobHistory(tmp_path / "absent.json")
    empty.load()
    monkeypatch.setattr(mc, "_history", empty)
    monkeypatch.setattr(mc, "_latency", mc.LatencyTracker())
    jobs = asyncio.run(mc.get_scheduler_status())["jobs"]
    assert all(j["last_status"] is None and j["last_run_ts"] is None for j in jobs)


def test_a_run_in_this_process_wins_over_history(status_env, armed):
    armed.record("desk_daily", "error", 900.0, ts="2026-10-23T19:30:02+05:30")
    mc._latency.record("desk_daily", 1500.0, "done")
    row = mc.job_last_run("desk_daily", mc._latency.stats())
    assert row["last_status"] == "done" and row["last_run_source"] == "this_run" and row["samples"] == 1
    assert row["avg_latency_ms"] == 1500.0
