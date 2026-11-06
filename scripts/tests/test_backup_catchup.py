"""P7 — a 02:15 backup missed during an outage (the Mac off on 24–25 Oct 2026) was never re-run.

Start-up now schedules ONE backup when today's is missing and its 02:15 slot has passed, never inside (or less than
the backup's own 20-min timeout before) the 07:45–09:20 / 18:30–21:15 freeze windows, after the start-up data
catch-up; and two backups never run at once (the controller's job lock in-process, db_backup.py's flock across
processes). Everything runs on temp backup dirs and a fake clock; the backup subprocess is a fake, alerts are
recorded and never sent, and no lifespan test touches data/ (heartbeat, history and backup dir are temp paths).
"""
# ruff: noqa: DTZ001 - fake-clock datetimes are localized with pytz (IST.localize), as in the controller
import asyncio
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import db_backup
import master_controller as mc

IST = mc.IST


def at(y, mo, d, h, mi, s=0):
    return IST.localize(datetime(y, mo, d, h, mi, s))


def hm(t):
    return t.strftime("%H:%M") if t else None


def fake_clock(monkeypatch, now):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)
    monkeypatch.setattr(mc, "datetime", FakeDT)


class _Alerts:
    def __init__(self):
        self.sent = []

    async def info(self, title, body):
        self.sent.append(("info", title))

    async def warning(self, title, body):
        self.sent.append(("warning", title))

    async def critical(self, title, body):
        self.sent.append(("critical", title))


class _FakeScheduler:
    def __init__(self):
        self.added = []

    def add_job(self, func, **kw):
        self.added.append((func.__name__, kw))


@pytest.fixture()
def ctl(monkeypatch, tmp_path):
    """Controller wired to temp paths and fakes: a recorded backup subprocess, recorded alerts, unarmed history."""
    alerts = _Alerts()
    monkeypatch.setattr(mc, "_alerts", alerts)
    monkeypatch.setattr(mc, "_latency", mc.LatencyTracker())
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "never-armed.json"))
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(mc, "BACKUP_CATCHUP_POLL_S", 0.01)
    sched = _FakeScheduler()
    monkeypatch.setattr(mc, "scheduler", sched)
    state = {"calls": [], "rc": 0, "gate": None}

    def fake_run(cmd, **kw):
        state["calls"].append(cmd)
        if state["gate"] is not None:
            state["gate"].wait(5)
        return subprocess.CompletedProcess(cmd, state["rc"], stdout="RESULT {}\n", stderr="boom: disk full\n")
    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    return {"alerts": alerts, "sched": sched, "state": state, "dest": tmp_path / "backups"}


def done_backup(dest: Path, day: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"market-{day}.meta.json").write_text("{}")


# ── planning (pure, fake clock, temp backup dir) ──────────────────────────────────────────────────────────

def test_plan_only_when_todays_backup_is_missing_after_0215(tmp_path):
    dest = tmp_path / "b"
    assert mc.plan_backup_catchup(at(2026, 10, 25, 1, 0), dest) is None             # 02:15 not reached yet
    assert hm(mc.plan_backup_catchup(at(2026, 10, 25, 2, 16), dest)) == "02:19"      # restart across 02:15
    assert hm(mc.plan_backup_catchup(at(2026, 10, 25, 17, 0), dest)) == "17:03"      # the 25 Oct case (Sunday)
    done_backup(dest, "20261024")                                                    # yesterday's does not count
    assert mc.plan_backup_catchup(at(2026, 10, 25, 17, 0), dest) is not None
    (dest / "market-20261025.duckdb").write_bytes(b"partial")                        # killed run: no meta yet
    assert mc.plan_backup_catchup(at(2026, 10, 25, 17, 0), dest) is not None
    done_backup(dest, "20261025")
    assert mc.plan_backup_catchup(at(2026, 10, 25, 17, 0), dest) is None             # today's exists: nothing to do


@pytest.mark.parametrize(("now", "expected"), [
    ((7, 20), "07:23"),   # done (≤ 20 min) before 07:45
    ((7, 30), "09:21"),   # would still run at 07:45 → after the morning window
    ((8, 0), "09:21"),    # inside the ICICI-login / pre-open window
    ((9, 19), "09:22"),   # +3 min is already past the window
    ((18, 5), "18:08"),   # done before 18:30
    ((18, 15), "21:16"),  # would run into the EOD window
    ((20, 0), "21:16"),   # inside the EOD window
    ((21, 14), "21:17"),
    ((23, 0), "23:03"),
])
def test_plan_never_starts_in_or_just_before_a_freeze_window(tmp_path, now, expected):
    assert hm(mc.plan_backup_catchup(at(2026, 10, 26, *now), tmp_path / "b")) == expected


def test_plan_does_not_cross_midnight_and_follows_the_data_catchup(tmp_path):
    assert mc.plan_backup_catchup(at(2026, 10, 25, 23, 58), tmp_path / "b") is None    # 02:15 is close then
    # data catch-up moved to 09:21 → the backup goes 3 min after it, not alongside it
    assert hm(mc.plan_backup_catchup(at(2026, 10, 26, 8, 0), tmp_path / "b", not_before=at(2026, 10, 26, 9, 21))) == "09:24"
    assert hm(mc.plan_backup_catchup(at(2026, 10, 26, 22, 0), tmp_path / "b",
                                     not_before=at(2026, 10, 26, 22, 1, 30))) == "22:04"


def test_backup_slot_boundaries():
    assert mc.backup_slot(at(2026, 10, 26, 7, 24, 59)) == at(2026, 10, 26, 7, 24, 59)
    assert mc.backup_slot(at(2026, 10, 26, 7, 25)) == at(2026, 10, 26, 9, 21)
    assert mc.backup_slot(at(2026, 10, 26, 9, 20, 59)) == at(2026, 10, 26, 9, 21)
    assert mc.backup_slot(at(2026, 10, 26, 9, 21)) == at(2026, 10, 26, 9, 21)
    assert mc.backup_slot(at(2026, 10, 26, 21, 15, 30)) == at(2026, 10, 26, 21, 16)


# ── the one-off job (fake clock, fake subprocess) ────────────────────────────────────────────────────────

def test_catchup_runs_the_backup_once_when_due(ctl, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 25, 21, 20))
    asyncio.run(mc.db_backup_catchup())
    [cmd] = ctl["state"]["calls"]
    assert cmd[-1].endswith("db_backup.py")
    assert ctl["alerts"].sent == [] and ctl["sched"].added == []
    assert mc._latency.stats()["db_backup_daily"]["last_status"] == "done"     # SYS shows the backup's run


def test_catchup_does_nothing_when_the_backup_appeared_or_midnight_passed(ctl, monkeypatch):
    done_backup(ctl["dest"], "20261025")
    fake_clock(monkeypatch, at(2026, 10, 25, 21, 20))
    asyncio.run(mc.db_backup_catchup())
    fake_clock(monkeypatch, at(2026, 10, 26, 0, 30))           # waited past midnight: tonight's 02:15 is next
    asyncio.run(mc.db_backup_catchup())
    assert ctl["state"]["calls"] == []


def test_catchup_landing_in_a_freeze_window_moves_itself(ctl, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 26, 19, 5))
    asyncio.run(mc.db_backup_catchup())
    assert ctl["state"]["calls"] == []
    [(name, kw)] = ctl["sched"].added
    assert name == "db_backup_catchup" and kw["run_date"] == at(2026, 10, 26, 21, 16)
    assert kw["id"] == "db_backup_catchup" and kw["replace_existing"] is True
    assert kw["misfire_grace_time"] >= 3600 and kw["coalesce"] is True, "a late loop must not drop the catch-up"


def test_catchup_waits_for_the_data_catchup_to_stop_writing(ctl, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 25, 21, 20))

    async def scenario():
        lock = mc._get_lock("startup_catchup")
        await lock.acquire()
        task = asyncio.create_task(mc.db_backup_catchup())
        await asyncio.sleep(0.1)
        assert ctl["state"]["calls"] == [], "no backup while the data catch-up holds the DuckDB"
        lock.release()
        await asyncio.wait_for(task, 5)
    asyncio.run(scenario())
    assert len(ctl["state"]["calls"]) == 1


def test_the_data_catchup_itself_holds_the_lock_the_backup_waits_on(ctl, monkeypatch):
    """F4-OPS review: the wait above takes the lock by hand, so nothing proved that startup_catchup really holds it
    (removing its `async with _get_lock("startup_catchup")` left every test green). Here the real startup_catchup
    runs with its body (_startup_catchup_run: data-service calls, the report) replaced by a step that blocks."""
    fake_clock(monkeypatch, at(2026, 10, 25, 21, 20))
    seen: dict[str, object] = {}

    async def scenario():
        running, release = asyncio.Event(), asyncio.Event()

        async def blocked_body(*_a, **_k):
            seen["locked"] = mc._get_lock("startup_catchup").locked()
            running.set()
            await release.wait()
        monkeypatch.setattr(mc, "_startup_catchup_run", blocked_body)
        data = asyncio.create_task(mc.startup_catchup("2026-10-23T18:00:00", "2026-10-25T21:20:00", {}, "full", "21:23"))
        await asyncio.wait_for(running.wait(), 5)
        backup = asyncio.create_task(mc.db_backup_catchup())
        await asyncio.sleep(0.1)
        seen["calls_while_writing"] = list(ctl["state"]["calls"])
        release.set()
        await asyncio.wait_for(asyncio.gather(data, backup), 5)
    asyncio.run(scenario())
    assert seen["locked"] is True, "startup_catchup must hold its lock while it writes the DuckDB"
    assert seen["calls_while_writing"] == [], "no backup while the data catch-up runs"
    assert len(ctl["state"]["calls"]) == 1, "the backup runs once the data catch-up is done"


def test_catchup_gives_up_if_the_data_catchup_never_ends(ctl, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 25, 21, 20))
    monkeypatch.setattr(mc, "BACKUP_CATCHUP_MAX_WAIT_S", 0.05)

    async def scenario():
        lock = mc._get_lock("startup_catchup")
        await lock.acquire()
        try:
            await mc.db_backup_catchup()
        finally:
            lock.release()
    asyncio.run(scenario())
    assert ctl["state"]["calls"] == []


def test_never_two_backups_at_once_in_the_controller(ctl, monkeypatch):
    """The 02:15 job and the start-up catch-up at the same moment: one backup subprocess, the other skips."""
    fake_clock(monkeypatch, at(2026, 10, 25, 21, 20))
    gate = threading.Event()
    ctl["state"]["gate"] = gate

    async def scenario():
        first = asyncio.create_task(mc.db_backup_daily())
        await asyncio.sleep(0.05)                              # the scheduled run is inside its subprocess
        await mc.db_backup_catchup()                           # → db_backup_daily sees the lock and skips
        gate.set()
        await first
    asyncio.run(scenario())
    assert len(ctl["state"]["calls"]) == 1


def test_busy_exit_is_a_skip_and_failure_is_critical_and_error(ctl, monkeypatch):
    ctl["state"]["rc"] = mc.DB_BACKUP_BUSY_EXIT
    asyncio.run(mc.db_backup_daily())
    assert ctl["alerts"].sent == [] and mc._latency.stats()["db_backup_daily"]["last_status"] == "done"
    ctl["state"]["rc"] = 1
    asyncio.run(mc.db_backup_daily())
    assert ctl["alerts"].sent == [("critical", "DuckDB backup FAILED")]
    assert mc._latency.stats()["db_backup_daily"]["last_status"] == "error"
    assert mc.DB_BACKUP_BUSY_EXIT == db_backup.EXIT_BUSY


# ── db_backup.py: one run at a time across processes ─────────────────────────────────────────────────────

def test_db_backup_refuses_while_another_process_holds_the_lock(tmp_path, monkeypatch, capsys):
    dest = tmp_path / "b"
    dest.mkdir()
    holder = subprocess.Popen(
        [sys.executable, "-c", ("import fcntl, sys, time\nf = open(sys.argv[1], 'a+')\n"
                                "fcntl.flock(f, fcntl.LOCK_EX)\nprint('locked', flush=True)\ntime.sleep(30)"),
         str(dest / db_backup.LOCK_NAME)],
        stdout=subprocess.PIPE, text=True)
    ran = []
    monkeypatch.setattr(db_backup, "run", lambda **kw: ran.append(kw) or {"file": "market-x.duckdb", "prefs": {}})
    try:
        assert holder.stdout.readline().strip() == "locked"
        assert db_backup.main(["--dest", str(dest)]) == db_backup.EXIT_BUSY
        assert ran == [] and "another backup is running" in capsys.readouterr().err
        assert sorted(p.name for p in dest.iterdir()) == [db_backup.LOCK_NAME], "nothing written while busy"
    finally:
        holder.kill()
        holder.wait(5)
    # negative control: the holder is gone (the kernel released its lock) → the backup runs
    assert db_backup.main(["--dest", str(dest)]) == 0 and len(ran) == 1


def test_single_run_is_exclusive_and_released(tmp_path):
    with db_backup.single_run(tmp_path), pytest.raises(db_backup.BackupBusy), db_backup.single_run(tmp_path):
        pass                                                    # the inner run is refused while the outer holds it
    with db_backup.single_run(tmp_path):                        # released after the first run
        pass


# ── start-up wiring (lifespan with temp paths, fake clock, nothing sent, nothing in data/) ─────────────────

class _PausedScheduler(mc.AsyncIOScheduler):
    """lifespan()'s scheduler, started PAUSED: its jobs are registered (next_run_time computed) but none can fire on
    the real wall clock between start and shutdown (the cron triggers use real time; only mc.datetime is faked)."""

    def start(self, paused: bool = False) -> None:
        super().start(paused=True)


def _quiet_lifespan(monkeypatch) -> list[_PausedScheduler]:
    """F4-OPS review: lifespan() reassigned the module-global mc.scheduler (a stopped scheduler with ~31 real jobs
    leaked into every later test) and started a live AsyncIOScheduler. monkeypatch restores mc.scheduler; the paused
    subclass keeps every job from running. Returns the schedulers lifespan created."""
    made: list[_PausedScheduler] = []

    class Recorded(_PausedScheduler):
        def __init__(self, *a, **k) -> None:
            super().__init__(*a, **k)
            made.append(self)
    monkeypatch.setattr(mc, "scheduler", None)
    monkeypatch.setattr(mc, "AsyncIOScheduler", Recorded)
    return made


def test_lifespan_wiring_leaves_no_scheduler_and_runs_no_job(monkeypatch, tmp_path):
    """The hygiene the two lifespan tests rely on: the scheduler lifespan built was paused and is shut down, and
    mc.scheduler is restored to what it was before (None) once the test ends."""
    started = at(2030, 3, 4, 21, 20)
    fake_clock(monkeypatch, started)
    monkeypatch.setattr(mc, "_alerts", _Alerts())
    monkeypatch.setattr(mc, "HEARTBEAT_FILE", tmp_path / "hb.json")
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "history.json"))
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: [])

    async def no_bot():
        return None
    monkeypatch.setattr(mc, "telegram_poller", no_bot)
    made = _quiet_lifespan(monkeypatch)

    async def scenario():
        async with mc.lifespan(mc.app):
            from apscheduler.schedulers.base import STATE_PAUSED
            return mc.scheduler.state == STATE_PAUSED, len(mc.scheduler.get_jobs())
    paused, jobs = asyncio.run(scenario())
    assert paused and jobs > 20 and len(made) == 1 and not made[0].running


def test_lifespan_schedules_the_backup_after_the_data_catchup(monkeypatch, tmp_path):
    started = at(2030, 3, 4, 21, 20)                          # a Monday, after the EOD window, far from real time
    fake_clock(monkeypatch, started)
    _quiet_lifespan(monkeypatch)
    alerts = _Alerts()
    monkeypatch.setattr(mc, "_alerts", alerts)
    monkeypatch.setattr(mc, "HEARTBEAT_FILE", tmp_path / "hb.json")
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "history.json"))
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: [])

    async def no_bot():
        return None
    monkeypatch.setattr(mc, "telegram_poller", no_bot)
    mc.write_heartbeat(tmp_path / "hb.json", started - timedelta(days=2))    # down since Saturday evening

    async def scenario():
        async with mc.lifespan(mc.app):
            s = mc.scheduler
            backup, catchup = s.get_job("db_backup_catchup"), s.get_job("startup_catchup")
            assert backup.misfire_grace_time >= 3600, "a late loop must not drop the catch-up"
            return (backup.next_run_time.astimezone(IST), catchup.next_run_time.astimezone(IST), catchup.kwargs,
                    catchup.args[3])
    backup_at, catchup_at, kwargs, mode = asyncio.run(scenario())
    assert mode == "full" and hm(catchup_at) == "21:21"
    assert backup_at == catchup_at + mc.BACKUP_CATCHUP_DELAY
    assert kwargs == {"backup_at": hm(backup_at), "replay": [], "later": []}      # full mode: no evening replay (M30)
    assert (tmp_path / "hb.json").exists() and not list((tmp_path / "backups").glob("*"))
    assert ("info", "SuryaDhana Online") in alerts.sent


def test_lifespan_adds_no_backup_when_todays_exists(monkeypatch, tmp_path):
    started = at(2030, 3, 4, 21, 20)
    fake_clock(monkeypatch, started)
    _quiet_lifespan(monkeypatch)
    monkeypatch.setattr(mc, "_alerts", _Alerts())
    monkeypatch.setattr(mc, "HEARTBEAT_FILE", tmp_path / "hb.json")
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "history.json"))
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: [])

    async def no_bot():
        return None
    monkeypatch.setattr(mc, "telegram_poller", no_bot)
    done_backup(tmp_path / "backups", "20300304")

    async def scenario():
        async with mc.lifespan(mc.app):
            return mc.scheduler.get_job("db_backup_catchup")
    assert asyncio.run(scenario()) is None


def test_lifespan_inside_the_eod_window_replays_the_missed_evening_jobs(monkeypatch, tmp_path):
    """M30 (5 Nov, controller down 19:34:54–19:55:26): the start-up planned "skip" and re-ran nothing; now the catch-up
    carries the replay of the 19:45 track record and the 19:50 S1 shadow, and SYS's catchup_at names it for both."""
    started = at(2030, 3, 6, 19, 55, 26)                      # a Wednesday, inside the 18:30–21:15 window
    fake_clock(monkeypatch, started)
    _quiet_lifespan(monkeypatch)
    monkeypatch.setattr(mc, "_alerts", _Alerts())
    monkeypatch.setattr(mc, "HEARTBEAT_FILE", tmp_path / "hb.json")
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    done_backup(tmp_path / "backups", "20300306")
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "history.json"))
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: [])

    async def no_bot():
        return None
    monkeypatch.setattr(mc, "telegram_poller", no_bot)
    mc.write_heartbeat(tmp_path / "hb.json", at(2030, 3, 6, 19, 34, 54))

    async def scenario():
        async with mc.lifespan(mc.app):
            job = mc.scheduler.get_job("startup_catchup")
            return job.args[3], job.kwargs, dict(mc._CATCHUP_PLAN)
    mode, kwargs, plan = asyncio.run(scenario())
    assert mode == "skip" and kwargs["replay"] == ["alpha_shadow_daily", "news_track_record_daily"]   # the shadow first
    assert set(plan) >= {"news_track_record_daily", "alpha_shadow_daily"} and "desk_daily" not in plan   # 19:30 ran
    assert mc._DATASET_CHECK["armed"] is False, "the lifespan disarms the dataset read when it ends"
