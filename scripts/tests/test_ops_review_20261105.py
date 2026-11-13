"""O-OPS (6 Nov 2026): the controller fixes from the 43-page review of 5 Nov — every rule with a negative control.

* M30  the in-window catch-up replays the evening jobs it used to skip (the S1 shadow first) and the report says exactly
       what was re-run and what was NOT (no blanket "mark every missed session on their next run").
* M33  a job whose catalogued datasets did not move reports "no new data", not "done"; the dormant legacy engine with
       AUTOPILOT off reports "skipped" (m111).
* m111 the first data-service polls come sooner (a 2 s job no longer reads 15,0xx ms) and every job's schedule is in words.
* m112 the morning sweep stops waiting after its budget and leaves the heavy results ingest out of the freeze window.
* m113 a job in flight says so (running_since) on /api/scheduler/status.
* gold_mcx_close: re-run after downtime only while an ICICI session is live.
* M32  the 02:15 job passes --offsite only when OFFSITE_BACKUP_DIR is set; an off-site failure is not a backup failure.
* PLAN 2.3 (W2-ALERTS): the alert dispatch round, the post-EOD hook and the Telegram parity commands.
* M31  the PM-run backfill-outage command: dry run by default, refused inside a freeze window, honest inbox lines.

Fakes only: no request leaves the process (httpx.MockTransport), temp paths for every file, a fake clock.
"""
# ruff: noqa: DTZ001 - fake-clock datetimes are localized with pytz (IST.localize), as in the controller
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc  # noqa: E402

IST = mc.IST


def at(y: int, mo: int, d: int, h: int, mi: int, s: int = 0) -> datetime:
    return IST.localize(datetime(y, mo, d, h, mi, s))


def fake_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return now if tz is None else now.astimezone(tz)
    monkeypatch.setattr(mc, "datetime", FakeDT)


class Alerts:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def info(self, title: str, body: str) -> None:
        self.sent.append(("info", title, body))

    async def warning(self, title: str, body: str) -> None:
        self.sent.append(("warning", title, body))

    async def critical(self, title: str, body: str) -> None:
        self.sent.append(("critical", title, body))


@pytest.fixture()
def ctl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    alerts = Alerts()
    macs: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mc, "_alerts", alerts)
    monkeypatch.setattr(mc, "_latency", mc.LatencyTracker())
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "never-armed.json"))
    monkeypatch.setattr(mc, "_notify_mac", lambda title, body, kind="alert": macs.append((title, body, kind)))
    monkeypatch.setattr(mc, "scheduler", None)
    monkeypatch.setattr(mc, "_CATCHUP_PLAN", {})          # SYS's per-job catchup_at: never leaks between tests
    monkeypatch.setattr(mc, "_CATCHUP_SCHEDULED", set())
    monkeypatch.setattr(mc, "_job_locks", {})
    monkeypatch.setattr(mc, "_evening_snapshot_env", lambda: {})     # no snapshot pointer read
    return {"alerts": alerts, "macs": macs, "tmp": tmp_path}


@pytest.fixture(autouse=True)
def _cli_globals_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    """backfill_outage_main rebinds UI_API / DATA_SVC / PYTHON_BIN for its shell run: restored after every test here."""
    for name in ("UI_API", "DATA_SVC", "PYTHON_BIN"):
        monkeypatch.setattr(mc, name, getattr(mc, name))


def mock_http(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    """Every httpx.AsyncClient the controller builds talks to `handler` (an httpx.MockTransport); returns the requests."""
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(*a: Any, **k: Any) -> httpx.AsyncClient:
        k.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(record), **k)
    monkeypatch.setattr(mc.httpx, "AsyncClient", factory)
    return seen


# ══ M30: the evening replay ═══════════════════════════════════════════════════════════════════════════════════
FIVE_NOV_MISSED = {"news_track_record_daily": 1, "alpha_shadow_daily": 1, "filing_alerts": 5, "gold_intraday_bars": 5}


def test_the_5_nov_restart_replays_the_track_record_and_the_s1_shadow() -> None:
    started = at(2026, 11, 5, 19, 55, 26)
    assert mc.plan_catchup(started, FIVE_NOV_MISSED)[0] == "skip"           # inside the EOD window, as on 5 Nov
    replay, later = mc.evening_replay_plan(started, FIVE_NOV_MISSED)
    assert replay == ["alpha_shadow_daily", "news_track_record_daily"] and later == []     # the S1 shadow first


def test_replay_runs_dependencies_first_and_leaves_a_slot_still_ahead_to_its_own_run() -> None:
    every = {j: 1 for j, _, _ in mc.EVENING_REPLAY}
    replay, later = mc.evening_replay_plan(at(2026, 11, 6, 20, 40), every)     # a Friday after 20:10
    assert replay == [j for j, _, _ in mc.EVENING_REPLAY] and later == []
    assert (replay.index("eod_data_pipeline") < replay.index("shared_snapshot_build") < replay.index("desk_daily")
            < replay.index("alpha_shadow_daily") < replay.index("news_track_record_daily"))
    # a start at 18:25 after a day down: today's 18:30 pipeline is still ahead → its own run, never a race with it
    replay, later = mc.evening_replay_plan(at(2026, 11, 5, 18, 25), {"eod_data_pipeline": 1, "desk_daily": 1})
    assert replay == [] and later == ["eod_data_pipeline", "desk_daily"]
    # negative control: nothing missed → nothing replayed (a routine restart replays nothing)
    assert mc.evening_replay_plan(at(2026, 11, 5, 20, 0), {"filing_alerts": 3}) == ([], [])


def test_the_skip_mode_catchup_runs_the_replay_and_reports_only_what_ran(ctl: dict[str, Any],
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock(monkeypatch, at(2026, 11, 5, 19, 57))
    ran: list[str] = []

    def job(name: str) -> Any:
        async def run() -> None:
            async with mc._track(name):
                ran.append(name)
        return run
    for name in ("news_track_record_daily", "alpha_shadow_daily", "desk_daily"):
        monkeypatch.setattr(mc, name, job(name))
    missed = {**FIVE_NOV_MISSED, "results_capture_daily": 1}
    asyncio.run(mc._startup_catchup_run("2026-11-05T19:34:54+05:30", "2026-11-05T19:55:26+05:30", missed, "skip", None,
                                        ["alpha_shadow_daily", "news_track_record_daily"], []))
    assert ran == ["alpha_shadow_daily", "news_track_record_daily"]
    [(level, title, body)] = ctl["alerts"].sent
    assert level == "warning" and "news_track_record_daily: re-run (done)" in body and "alpha_shadow_daily: re-run (done)" in body
    assert "mark every missed session on their next run" not in body                 # the 5 Nov false claim is gone
    assert "the S1 shadow replayed every missed session" in body
    assert "NOT re-run (next scheduled run): results_capture_daily" in body          # honest about what does not run


def test_negative_control_without_the_replay_the_report_says_the_shadow_is_not_re_run(ctl: dict[str, Any],
                                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock(monkeypatch, at(2026, 11, 5, 19, 57))
    asyncio.run(mc._startup_catchup_run("2026-11-05T19:34:54+05:30", "2026-11-05T19:55:26+05:30", FIVE_NOV_MISSED, "skip",
                                        None, [], []))
    body = ctl["alerts"].sent[0][2]
    assert "NOT re-run (next scheduled run): alpha_shadow_daily" in body and "news_track_record_daily" in body
    assert "replayed every missed session" not in body


def test_catchup_gaps_names_the_next_run_and_the_ones_left_to_today() -> None:
    nxt = {"alpha_shadow_daily": at(2026, 11, 6, 19, 50), "eod_data_pipeline": at(2026, 11, 5, 18, 30)}
    out = mc.catchup_gaps({"alpha_shadow_daily": 1, "eod_data_pipeline": 1, "filing_alerts": 9}, set(),
                          ["eod_data_pipeline"], nxt)
    assert out == ["left to today's scheduled run: eod_data_pipeline 18:30",
                   "NOT re-run (next scheduled run): alpha_shadow_daily Fri 06 Nov 19:50"]
    assert mc.catchup_gaps({"filing_alerts": 9}, set(), [], {}) == []                 # minute jobs are not listed


def test_full_mode_coverage_includes_the_desk_and_the_shadow_it_replays() -> None:
    cov = mc.catchup_coverage("full", {"desk_daily": 1, "alpha_shadow_daily": 1, "news_track_record_daily": 1}, ())
    assert {"eod_data_pipeline", "desk_daily", "alpha_shadow_daily"} <= cov and "news_track_record_daily" not in cov
    assert "eod_data_pipeline" not in mc.catchup_coverage("nse", {"eod_data_pipeline": 1}, ())   # market hours: 18:30


# ══ M33 / m111: the job status ════════════════════════════════════════════════════════════════════════════════
def _health(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"rows": list(rows)}


ROW_PREOPEN = {"id": "gold_preopen_log", "job_id": "gold_preopen_snapshot", "as_of": "2026-10-30", "last_fetch": None}
ROW_IBJA = {"id": "gold_india_ibja", "job_id": "gold_india_pm", "as_of": "2026-11-04",
            "last_fetch": {"date": "2026-11-04", "fetched_at": "2026-11-05T12:40:00+00:00", "revision": 0}}


def test_dataset_outcome_no_new_data_only_when_nothing_moved() -> None:
    before = mc.dataset_fingerprints(_health(ROW_PREOPEN, ROW_IBJA), "gold_india_pm")
    refetched = {**ROW_IBJA, "last_fetch": {**ROW_IBJA["last_fetch"], "fetched_at": "2026-11-06T12:40:00+00:00"}}
    assert mc.dataset_outcome(before, mc.dataset_fingerprints(_health(refetched), "gold_india_pm")) == mc.STATUS_NO_NEW_DATA
    moved = {**ROW_IBJA, "as_of": "2026-11-05"}
    assert mc.dataset_outcome(before, mc.dataset_fingerprints(_health(moved), "gold_india_pm")) is None      # control
    revised = {**ROW_IBJA, "last_fetch": {**ROW_IBJA["last_fetch"], "revision": 1}}
    assert mc.dataset_outcome(before, mc.dataset_fingerprints(_health(revised), "gold_india_pm")) is None
    # no evidence → keep the status: an endpoint-kind row, a job with no row, data-service silent
    endpoint = {"id": "desk_mark", "job_id": "desk_daily", "as_of": None, "last_fetch": None}
    assert mc.dataset_outcome(mc.dataset_fingerprints(_health(endpoint), "desk_daily"), {}) is None
    assert mc.dataset_fingerprints({"error": "down"}, "x") is None and mc.dataset_outcome(before, None) is None


def _track_once(job: str, *, fail: bool = False, mark: str | None = None, soft_fail: bool = False) -> str:
    async def run() -> None:
        async with mc._track(job):
            if mark:
                mc._mark_status(job, mark)
            if soft_fail:
                mc._mark_failed(job)
            if fail:
                raise RuntimeError("boom")
    try:
        asyncio.run(run())
    except RuntimeError:
        pass
    return mc._latency.stats()[job]["last_status"]


def test_track_reports_no_new_data_from_the_before_and_after_reads(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """M33 + P0-2 (13 Nov 2026): an unmoved catalogued dataset is "no new data" ONLY while the server's
    holiday-aware watermark check owes nothing; the moment the check says a session was expected, the run is
    FAILED (table_unmoved:…) — a job may never report success while its table silently stands still."""
    reads = {"n": 0}
    stuck = mc.dataset_fingerprints(_health(ROW_PREOPEN), "gold_preopen_snapshot")
    moved = mc.dataset_fingerprints(_health({**ROW_PREOPEN, "as_of": "2026-11-06"}), "gold_preopen_snapshot")
    after = {"value": stuck}

    async def snap(job: str) -> Any:
        reads["n"] += 1
        return stuck if reads["n"] % 2 else after["value"]
    monkeypatch.setattr(mc, "_dataset_snapshot", snap)
    verdict: dict[str, Any] = {"body": {"status": "ok", "reasons": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs/data-health":
            return httpx.Response(200, json=verdict["body"])
        return httpx.Response(200, json=_health(ROW_PREOPEN))
    mock_http(monkeypatch, handler)

    # P0-2: unmoved AND the server says a session was owed → FAILED, loudly
    verdict["body"] = {"status": "FAILED", "reasons": ["table_unmoved:gold_preopen_log"]}
    assert _track_once("gold_preopen_snapshot") == "FAILED (table_unmoved:gold_preopen_log)"
    # M33 survives: unmoved but nothing was owed (holiday / pre-deadline) → "no new data"
    verdict["body"] = {"status": "ok", "reasons": []}
    assert _track_once("gold_preopen_snapshot") == "no new data"
    # no watermark evidence at all → never a failure without evidence
    verdict["body"] = {}
    assert _track_once("gold_preopen_snapshot") == "no new data"
    after["value"] = moved
    assert _track_once("gold_preopen_snapshot") == "done"                               # control: the row moved
    after["value"] = stuck
    verdict["body"] = {"status": "FAILED", "reasons": ["table_unmoved:gold_preopen_log"]}
    assert _track_once("gold_preopen_snapshot", fail=True) == "error"                  # an error always wins
    assert _track_once("gold_preopen_snapshot", soft_fail=True) == "error"


def test_the_dataset_read_needs_the_lifespan_arm_and_the_switch(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seen = mock_http(monkeypatch, lambda r: httpx.Response(200, json=_health(ROW_PREOPEN)))
    assert asyncio.run(mc._dataset_snapshot("gold_preopen_snapshot")) is None and seen == []    # not armed: no request
    monkeypatch.setattr(mc, "JOB_DATASET_CHECK", True)
    mc._DATASET_CHECK["armed"] = True
    got = asyncio.run(mc._dataset_snapshot("gold_preopen_snapshot"))
    assert got == {"gold_preopen_log": ("2026-10-30", None, None, None, None)} and seen[0].url.path == "/db/data-health"
    assert asyncio.run(mc._dataset_snapshot("price_alerts_check")) is None and len(seen) == 1   # owns nothing: no GET
    monkeypatch.setattr(mc, "JOB_DATASET_CHECK", False)
    assert asyncio.run(mc._dataset_snapshot("gold_preopen_snapshot")) is None and len(seen) == 1


def test_autopilot_off_legacy_runs_say_skipped(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc._autopilot, "_enabled", False, raising=False)
    monkeypatch.setattr(type(mc._autopilot), "on", property(lambda self: False))
    asyncio.run(mc.overnight_rl_retrain())
    asyncio.run(mc.eod_rebalancing())
    st = mc._latency.stats()
    assert st["overnight_rl_retrain"]["last_status"] == "skipped" and st["eod_rebalancing"]["last_status"] == "skipped"
    assert _track_once("plain_job") == "done"                                           # control: no mark → done
    assert _track_once("marked_job", mark=mc.STATUS_SKIPPED) == "skipped"


def test_the_first_polls_come_sooner_but_never_above_the_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    delays = [mc.data_job_poll_delay(i) for i in range(9)]
    assert delays == [1, 1, 2, 3, 5, 8, 15, 15, 15]
    assert sum(delays[:2]) <= 2 < 15            # a 2 s job is seen by the 2nd poll, not after the old flat 15 s
    monkeypatch.setattr(mc, "DATA_JOB_POLL_SECS", 0)
    assert {mc.data_job_poll_delay(i) for i in range(9)} == {0}                         # tests that set 0 stay instant


@pytest.mark.parametrize(("trigger", "words"), [
    (CronTrigger(day_of_week="mon-fri", hour=19, minute=50, timezone=IST), "Mon–Fri 19:50"),
    (CronTrigger(hour=2, minute=15, timezone=IST), "02:15"),
    (CronTrigger(day_of_week="mon-fri", hour=9, minute=9, second=30, timezone=IST), "Mon–Fri 09:09:30"),
    (CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/2", timezone=IST), "Mon–Fri every 2 min 9–15h"),
    (CronTrigger(minute=10, timezone=IST), "hourly at :10"),
    (CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*", timezone=IST), "Mon–Fri every minute 9–15h"),
    (OrTrigger([CronTrigger(day_of_week="sat", hour="2-6", minute=30, timezone=IST),
                CronTrigger(day_of_week="mon-tue", hour=6, minute=30, timezone=IST)]),
     "Sat 2–6h hourly at :30 · Mon–Tue 06:30"),
    (IntervalTrigger(seconds=60, timezone=IST), "every 60 s"),
])
def test_describe_trigger_in_words(trigger: Any, words: str) -> None:
    assert mc.describe_trigger(trigger) == words


def test_describe_trigger_falls_back_to_the_text_and_handles_one_offs() -> None:
    assert mc.describe_trigger(DateTrigger(run_date=at(2026, 11, 6, 21, 16))) == "once Fri 06 Nov 21:16"
    weird = SimpleNamespace(name="x")
    assert mc.describe_trigger(weird) == str(weird) and mc.describe_trigger(None) is None


def test_status_carries_schedule_running_and_catchup(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    trig = CronTrigger(day_of_week="mon-fri", hour=19, minute=50, timezone=IST)
    jobs = [SimpleNamespace(id="alpha_shadow_daily", name="S1", next_run_time=None, trigger=trig),
            SimpleNamespace(id="results_capture_daily", name="R", next_run_time=None, trigger=trig)]
    monkeypatch.setattr(mc, "scheduler", SimpleNamespace(running=True, get_jobs=lambda: jobs))

    async def no_probe() -> None:
        return None
    monkeypatch.setattr(mc, "_probe_broker_latency", no_probe)
    mc._RUNNING["results_capture_daily"] = "2026-11-05T20:45:00+05:30"
    mc._note_catchup("alpha_shadow_daily", at(2026, 11, 5, 19, 57))
    got = {j["id"]: j for j in asyncio.run(mc.get_scheduler_status())["jobs"]}
    assert got["alpha_shadow_daily"]["schedule_ist"] == "Mon–Fri 19:50"
    assert got["alpha_shadow_daily"]["catchup_at"] == "2026-11-05T19:57:00+05:30" and got["alpha_shadow_daily"]["running_since"] is None
    assert got["results_capture_daily"]["running_since"] == "2026-11-05T20:45:00+05:30"
    assert got["results_capture_daily"]["catchup_at"] is None            # control: nothing scheduled → no claim
    assert _track_once("alpha_shadow_daily") == "done" and "alpha_shadow_daily" not in mc._CATCHUP_PLAN   # it ran


# ══ m112: the morning sweep ═══════════════════════════════════════════════════════════════════════════════════
SWEEP_ROWS = [
    {"id": "nse_results", "state": "red", "job_id": "results_capture_daily", "as_of": "2026-10-30", "lag_sessions": 3},
    {"id": "nse_fo_daily", "state": "amber", "job_id": "nse_positions_catchup", "as_of": "2026-11-03", "lag_sessions": 1},
    {"id": "nse_bhavcopy", "state": "amber", "job_id": "eod_data_pipeline", "as_of": "2026-11-03", "lag_sessions": 1},
]


def _sweep(monkeypatch: pytest.MonkeyPatch, now: datetime, slow: set[str], budget: float) -> tuple[list[str], str]:
    fake_clock(monkeypatch, now)
    monkeypatch.setattr(mc, "SWEEP_BUDGET_S", budget)
    monkeypatch.setattr(mc, "SWEEP_STEP_MIN_S", 0.05)
    calls: list[str] = []

    async def health(job: str) -> Any:
        return {"rows": SWEEP_ROWS, "last_session": "2026-11-04"}

    async def job(name: str, path: str, body: Any = None, quiet: bool = False) -> dict[str, Any]:
        calls.append(path)
        if path in slow:
            await asyncio.sleep(0.5)
        return {"status": "ok"}
    monkeypatch.setattr(mc, "_data_health", health)
    monkeypatch.setattr(mc, "_run_data_job", job)
    monkeypatch.setattr(mc, "health_digest", lambda h: "digest")
    asyncio.run(mc.morning_sweep())
    return calls, mc._alerts.sent[-1][2]


def test_the_sweep_leaves_the_results_ingest_out_of_the_morning_window(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    calls, body = _sweep(monkeypatch, at(2026, 11, 6, 8, 35), set(), 480)
    assert "/jobs/ingest-results" not in calls and "results left to the 20:45 capture" in body
    calls, body = _sweep(monkeypatch, at(2026, 11, 6, 13, 2), set(), 480)            # control: outside the window
    assert "/jobs/ingest-results" in calls and "results ok" in body


def test_the_sweep_stops_waiting_after_its_budget(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    calls, body = _sweep(monkeypatch, at(2026, 11, 6, 8, 35), {"/jobs/ingest-nse-positions"}, 0.1)
    assert calls == ["/jobs/ingest-nse-positions"]
    assert "positions still running in data-service after the sweep budget" in body and "bhavcopy not started" in body
    calls, body = _sweep(monkeypatch, at(2026, 11, 6, 8, 35), {"/jobs/ingest-nse-positions"}, 30)    # control
    assert calls == ["/jobs/ingest-nse-positions", "/jobs/ingest-bhavcopy"] and "positions ok" in body


# ══ gold_mcx_close after downtime ═════════════════════════════════════════════════════════════════════════════
def test_gold_mcx_close_is_re_run_only_while_a_session_is_live(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    ingested: list[str] = []
    live = {"v": False}

    async def session() -> bool:
        return live["v"]

    async def ingest(job: str, groups: Any, backfill_from: Any = None, quiet: bool = False) -> dict[str, Any]:
        ingested.append(job)
        return {"groups": {g: {"status": "ok"} for g in groups}}
    monkeypatch.setattr(mc, "_breeze_session_live", session)
    monkeypatch.setattr(mc, "_gold_ingest", ingest)
    line = asyncio.run(mc.gold_downtime_catchup(["gold_overnight", "gold_mcx_close"], "2026-11-03"))
    assert ingested == ["gold_overnight"] and "gold_mcx_close: not re-run (no live ICICI session now" in line
    live["v"] = True                                                                   # control: a live session
    asyncio.run(mc.gold_downtime_catchup(["gold_mcx_close"], "2026-11-03"))
    assert ingested == ["gold_overnight", "gold_mcx_close"]


# ══ M32: --offsite only when OFFSITE_BACKUP_DIR is set ═══════════════════════════════════════════════════════
def test_offsite_flag_only_with_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OFFSITE_BACKUP_DIR", raising=False)
    monkeypatch.setattr(mc, "_env_file_value", lambda key: "")
    assert mc.offsite_dir() is None and "--offsite" not in mc.db_backup_cmd(mc.offsite_dir())       # control: unset
    monkeypatch.setattr(mc, "_env_file_value", lambda key: "/Volumes/Backup/sd" if key == "OFFSITE_BACKUP_DIR" else "")
    assert mc.db_backup_cmd(mc.offsite_dir())[-2:] == ["--offsite", "/Volumes/Backup/sd"]           # set in .env later
    monkeypatch.setenv("OFFSITE_BACKUP_DIR", "  /mnt/x  ")
    assert mc.offsite_dir() == "/mnt/x"


def test_an_offsite_failure_is_a_warning_not_a_failed_backup(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    state = {"stderr": "off-site copy FAILED (RuntimeError: off-site target is not mounted); the local backup is fine"}

    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="RESULT {}\n", stderr=state["stderr"])
    monkeypatch.setattr(mc.subprocess, "run", run)
    asyncio.run(mc.db_backup_daily())
    assert [(lv, t) for lv, t, _ in ctl["alerts"].sent] == [("warning", "Off-site backup copy FAILED")]
    assert mc._latency.stats()["db_backup_daily"]["last_status"] == "error"
    ctl["alerts"].sent.clear()
    state["stderr"] = "Traceback ...\nOSError: disk full"                               # control: a real failure
    asyncio.run(mc.db_backup_daily())
    assert [(lv, t) for lv, t, _ in ctl["alerts"].sent] == [("critical", "DuckDB backup FAILED")]


# ══ PLAN 2.3: the alert dispatch round, the post-EOD hook, Telegram parity ═══════════════════════════════════
DISPATCH = [
    {"seq": 1, "origin": "price", "kind": "price", "title": "SuryaDhana price alert", "telegram_title": "Price alert",
     "text": "TCS rose above ₹3,200.00 (now ₹3,210.00)", "channel": "both", "symbol": "TCS"},
    {"seq": 2, "origin": "rule", "kind": "rule", "title": "SuryaDhana alert", "telegram_title": "Alert",
     "text": "NIFTY IV percentile 82 at or over 80 · context · as of 05 Nov", "channel": "telegram", "symbol": "NIFTY"},
    {"seq": 3, "origin": "rule", "kind": "rule", "title": "SuryaDhana alert", "telegram_title": "Alert",
     "text": "VIX 16.2 changed", "channel": "mac", "symbol": "INDIAVIX"},
]


def test_dispatch_delivers_each_fire_on_its_channels_and_never_the_hits_twice(ctl: dict[str, Any],
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    hits = [{"sym": "TCS", "side": "above", "level": 3200.0, "price": 3210.0}]
    seen = mock_http(monkeypatch, lambda r: httpx.Response(200, json={"hits": hits, "dispatch": DISPATCH}))
    asyncio.run(mc.alerts_dispatch("price_alerts_check", "all"))
    assert seen[0].method == "POST" and seen[0].url.path == "/api/alerts/run"
    assert dict(seen[0].url.params) == {"scope": "all", "dispatch": "1"}
    assert [m[0] for m in ctl["macs"]] == ["SuryaDhana price alert", "SuryaDhana alert"]           # both + mac
    assert [t for _, t, _ in ctl["alerts"].sent] == ["Price alert", "Alert"]                       # both + telegram
    assert sum("TCS rose above" in m[1] for m in ctl["macs"]) == 1                                 # not twice


def test_negative_control_an_older_ui_api_without_dispatch_announces_the_legacy_hits(ctl: dict[str, Any],
                                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    hits = [{"sym": "INFY", "side": "move", "level": 3.0, "price": 1501.25, "change_pct": -3.42}]
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"hits": hits}))
    asyncio.run(mc.alerts_dispatch("price_alerts_check", "all"))
    assert ctl["macs"] == [("SuryaDhana price alert", "INFY -3.4% today (alert at ±3%, now ₹1,501.25)", "price")]


def test_a_relayed_fire_with_a_direction_word_is_withheld() -> None:
    assert mc.alert_text_or_withheld(DISPATCH[1]) == DISPATCH[1]["text"]                           # control
    bad = {**DISPATCH[1], "text": "NIFTY looks bullish: buy the dip"}
    out = mc.alert_text_or_withheld(bad)
    assert "bullish" not in out and "buy" not in out and out.startswith("NIFTY: an alert rule's condition was met")
    assert [c for c, _, _ in mc.alert_deliveries({**DISPATCH[2], "channel": "pager"})] == ["mac", "telegram"]   # never dropped


def test_after_an_eod_step_the_stored_series_rules_are_evaluated(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seen = mock_http(monkeypatch, lambda r: httpx.Response(200, json={"hits": [], "dispatch": [DISPATCH[1]]}))
    monkeypatch.setattr(mc, "ALERTS_ENGINE_ENABLED", True)
    asyncio.run(mc.alerts_after("nse_positions_catchup"))
    assert dict(seen[0].url.params) == {"scope": "eod", "dispatch": "1"} and [t for _, t, _ in ctl["alerts"].sent] == ["Alert"]
    monkeypatch.setattr(mc, "ALERTS_ENGINE_ENABLED", False)                            # control: switched off
    asyncio.run(mc.alerts_after("nse_positions_catchup"))
    assert len(seen) == 1
    monkeypatch.setattr(mc, "ALERTS_ENGINE_ENABLED", True)
    mock_http(monkeypatch, lambda r: httpx.Response(404, json={"detail": "Not Found"}))
    asyncio.run(mc.alerts_after("nse_evening_pass"))                                   # a failed round never raises


@pytest.mark.parametrize(("text", "parsed"), [
    ("/alerts list", ("list", "")),
    ("/alerts@SuryaBot list", ("list", "")),
    ("/alert add iv_pctile:NIFTY above 80 repeat telegram", ("add", "iv_pctile:NIFTY above 80 repeat telegram")),
    ("/ALERT ADD price:TCS cross_up 4000", ("add", "price:TCS cross_up 4000")),
    ("/alert add", ("add", "")),
    ("/alerts", None),                          # the legacy price-level list stays with telegram_bot
    ("/alert TCS above 2400", None),            # the legacy price level stays with telegram_bot
    ("/alertsx list", None),
    ("alerts list", None),
])
def test_alert_command_parsing(text: str, parsed: Any) -> None:
    assert mc.alert_command(text) == parsed


def test_alert_bot_reply_lists_and_adds_through_ui_api() -> None:
    calls: list[tuple[str, Any]] = []
    rules = {"rules": [{"id": "px:TCS:above", "origin": "price", "summary": "TCS price at or over ₹2,400", "status": "active"},
                       {"id": "r-1", "origin": "rule", "summary": "NIFTY IV percentile at or over 80 · repeat", "status": "snoozed",
                        "snooze_until": "2026-11-06T11:00:00+05:30", "last_fired_at": "2026-11-05T14:20:00+05:30"}]}

    async def get(path: str, **params: Any) -> Any:
        calls.append(("GET", path))
        return rules

    async def put(path: str, body: dict[str, Any]) -> Any:
        calls.append(("PUT", path))
        if "nonsense" in body["text"]:
            return {"ok": False, "error": "unknown op 'nonsense'"}
        return {"ok": True, "rule": {"id": "r-2", "summary": "NIFTY IV percentile at or over 80"}}
    listed = asyncio.run(mc.alert_bot_reply("/alerts list", get, put))
    assert listed.splitlines()[1].startswith("• NIFTY IV percentile") and "snoozed to 11:00" in listed
    assert "last fired 11-05 14:20" in listed and "<code>px:TCS:above</code>" in listed
    added = asyncio.run(mc.alert_bot_reply("/alert add iv_pctile:NIFTY above 80", get, put))
    assert added.startswith("Rule stored: NIFTY IV percentile at or over 80") and "describes a level, not a call" in added
    refused = asyncio.run(mc.alert_bot_reply("/alert add iv_pctile:NIFTY nonsense 80", get, put))
    assert refused.startswith("Not stored: unknown op") and "Usage:" in refused
    assert calls == [("GET", mc.ALERTS_RULES_PATH), ("PUT", mc.ALERTS_FROM_TEXT_PATH), ("PUT", mc.ALERTS_FROM_TEXT_PATH)]
    assert asyncio.run(mc.alert_bot_reply("/alert TCS above 2400", get, put)) is None              # control: legacy


def test_alert_replies_survive_an_absent_engine() -> None:
    assert "did not answer" in mc.fmt_alert_rules(None) and "Nothing stored" in mc.fmt_alert_added(None)
    assert mc.fmt_alert_rules({"rules": []}).startswith("No alert rules yet")


# ══ M31: backfill-outage ══════════════════════════════════════════════════════════════════════════════════════
N50 = [{"date": "2026-10-30", "close": 23053.1}, {"date": "2026-11-02", "close": 23440.8},
       {"date": "2026-11-03", "close": 23810.85}, {"date": "2026-11-04", "close": 23960.6}]
BANK = [{"date": "2026-10-30", "close": 51000.0}, {"date": "2026-11-02", "close": 51510.0}]


def _line(at_: str, kind: str, title: str = "t") -> str:
    return json.dumps({"at": at_, "kind": kind, "title": title, "body": "b"})


def test_missed_note_slots_come_from_the_stored_sessions_and_the_inbox() -> None:
    sessions = mc.outage_sessions(N50, "2026-11-01", "2026-11-04")
    assert sessions == ["2026-11-02", "2026-11-03", "2026-11-04"]                       # the weekend is no session
    inbox = [_line("2026-11-04T08:50:03+05:30", "morning"), _line("2026-11-04T21:08:00+05:30", "wrap")]
    assert mc.missing_note_slots(inbox, sessions) == [("2026-11-02", "morning"), ("2026-11-02", "close"),
                                                      ("2026-11-03", "morning"), ("2026-11-03", "close"),
                                                      ("2026-11-04", "close")]


# the controller's own downtime reports, as its log writes them (.logs/master-controller.log, 'Stack was down' body)
LOG_LINES = ["[INFO]  [scheduler] APScheduler started (IST)",
             "[WARN]  [startup_catchup] Down from 2026-10-28 12:46 to 2026-10-30 08:11 IST.",
             "[WARN]  [startup_catchup] Down from 2026-10-31 11:29 to 2026-11-04 21:29 IST.",
             "[WARN]  [startup_catchup] Down from 2026-10-31 11:29 to 2026-11-04 21:29 IST.",       # a duplicate
             "[WARN]  [startup_catchup] Down from 2026-13-40 99:99 to 2026-11-04 21:29 IST."]       # garbage: ignored
DOWNS = mc.controller_downtimes(LOG_LINES)


def test_the_controller_downtimes_come_from_its_own_log_lines() -> None:
    assert DOWNS == [(at(2026, 10, 28, 12, 46), at(2026, 10, 30, 8, 11)), (at(2026, 10, 31, 11, 29), at(2026, 11, 4, 21, 29))]
    assert mc.downtime_over(DOWNS, at(2026, 10, 29, 8, 50)) == DOWNS[0]
    assert mc.downtime_over(DOWNS, at(2026, 11, 4, 15, 40)) == DOWNS[1]
    # negative controls: back at 08:11 on 30 Oct → the 08:50 slot was NOT inside a recorded downtime; 16 Oct: no record
    assert mc.downtime_over(DOWNS, at(2026, 10, 30, 8, 50)) is None and mc.downtime_over(DOWNS, at(2026, 10, 16, 8, 50)) is None
    assert mc.controller_downtimes(["Down from yesterday", ""]) == []


def test_backfilled_notes_are_arithmetic_dated_and_honest() -> None:
    now = at(2026, 11, 6, 21, 30)
    close = mc.backfilled_note("2026-11-02", "close", N50, BANK, now, DOWNS)
    assert close["at"] == "2026-11-02T15:40:00+05:30" and close["kind"] == "close" and close["backfilled"] is True
    assert "NIFTY 50 23,440.80 (+1.68 %)" in close["body"] and "NIFTY BANK 51,510.00 (+1.00 %)" in close["body"]
    assert "no closing note is recorded for this session; backfilled from stored data on 06 Nov 21:30" in close["body"]
    assert "(backfilled)" in close["title"]
    # a cause only where the controller's own log records one over that slot, quoted with its dates
    assert "The controller's log records it down from 31 Oct 11:29 to 04 Nov 21:29 IST" in close["body"]
    assert close["controller_down"] == {"from": "2026-10-31T11:29+05:30", "to": "2026-11-04T21:29+05:30",
                                        "source": "controller log"}
    morning = mc.backfilled_note("2026-11-02", "morning", N50, BANK, now, DOWNS)
    assert morning["kind"] == "gap" and morning["body"].startswith("No pre-market note is recorded for this session")
    assert "cannot be rebuilt" in morning["body"] and "GIFT" in morning["body"] and "records it down" in morning["body"]
    assert not mc.ALERT_DIRECTION_WORDS.search(close["body"] + morning["body"])
    assert "not stored" in mc.backfilled_note("2026-11-05", "close", N50, BANK, now)["body"]       # nothing invented
    # NEGATIVE CONTROL (6 Nov checker): a session without a recorded downtime names no cause at all — 30 Oct 08:50 (the
    # controller was back at 08:11), and any session when no log is available
    for day, slot, downs in (("2026-10-30", "morning", DOWNS), ("2026-11-02", "close", ()), ("2026-11-02", "morning", ())):
        rec = mc.backfilled_note(day, slot, N50, BANK, now, downs)
        assert "controller" not in rec["body"] and "down" not in rec["body"] and "controller_down" not in rec, (day, slot)
        assert "not sent" not in rec["body"]                        # the code never checked what was sent


def test_the_merge_puts_lines_in_time_order_and_is_idempotent() -> None:
    inbox = [_line("2026-11-01T10:00:00+05:30", "move"), "not json", _line("2026-11-05T08:50:00+05:30", "morning")]
    rec = mc.backfilled_note("2026-11-02", "close", N50, BANK, at(2026, 11, 6, 21, 30))
    merged = mc.merge_notifications(inbox, [rec])
    assert len(merged) == 4 and json.loads(merged[2])["for_session"] == "2026-11-02" and merged[1] == "not json"
    assert merged[-1] != json.dumps(rec, ensure_ascii=True)        # negative control: a plain append would put it last
    assert mc.merge_notifications(merged, [rec]) == merged         # a second run adds nothing


def test_the_plan_wires_d_data_s_generator_and_job() -> None:
    plan = {p["step"]: p for p in mc.plan_outage_backfill("2026-10-12", "2026-11-04", mc.OUTAGE_STEPS, "~/fii.csv")}
    assert plan["wraps"]["cmd"][1].endswith("scripts/daily_wrap.py") and plan["wraps"]["cmd"][2:4] == ["--backfill-missing", "--since"]
    # the command's --until reaches D-DATA's CLI (daily_wrap.py --until; 6 Nov checker: it was dropped)
    wraps = plan["wraps"]["cmd"]
    assert wraps[wraps.index("--since") + 1] == "2026-10-12" and wraps[wraps.index("--until") + 1] == "2026-11-04"
    assert plan["wraps"]["dry_run_cmd"] == [*wraps, "--dry-run"] and "--dry-run" not in wraps
    assert plan["fii_dii"]["path"] == "/jobs/fii-dii-backfill" and plan["fii_dii"]["body"] == {"since": "2026-10-12",
                                                                                              "csv_path": "~/fii.csv"}
    assert [p["step"] for p in mc.plan_outage_backfill("2026-10-12", "2026-11-04", ["notes"], None)] == ["notes"]


def test_the_command_is_a_dry_run_by_default_and_refuses_a_freeze_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                                        capsys: pytest.CaptureFixture[str]) -> None:
    inbox = tmp_path / "notifications.jsonl"
    inbox.write_text(_line("2026-11-01T10:00:00+05:30", "move") + "\n")
    monkeypatch.setattr(mc, "_NOTIFY_LOG", inbox)
    seen = mock_http(monkeypatch, lambda r: httpx.Response(500))
    ran: list[Any] = []
    monkeypatch.setattr(mc.subprocess, "run", lambda *a, **k: ran.append(a))
    assert mc.backfill_outage_main(["--since", "2026-11-01", "--until", "2026-11-04"]) == 0
    out = capsys.readouterr().out
    assert '"dry_run": true' in out and "Nothing written" in out and ran == [] and seen == []
    assert mc.backfill_outage_main(["--until", "2026-11-04"]) == 0       # the default range is the review's evidence window
    assert '"since": "2026-10-28"' in capsys.readouterr().out and mc.OUTAGE_SINCE_DEFAULT == "2026-10-28"
    assert inbox.read_text().count("\n") == 1                                          # untouched
    fake_clock(monkeypatch, at(2026, 11, 6, 19, 0))
    assert mc.backfill_outage_main(["--execute", "--steps", "notes"]) == 3 and inbox.read_text().count("\n") == 1
    with pytest.raises(SystemExit):
        mc.backfill_outage_main(["--steps", "wraps,typo"])
    monkeypatch.delenv("UI_API_URL", raising=False)
    monkeypatch.delenv("PYTHON_BIN", raising=False)
    mc.backfill_outage_main(["--steps", "wraps"])                     # from a shell: the local stack, this interpreter
    assert mc.UI_API == "http://127.0.0.1:8010" and mc.PYTHON_BIN == sys.executable


def test_the_notes_step_writes_the_inbox_when_executed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    inbox = tmp_path / "notifications.jsonl"
    inbox.write_text(_line("2026-11-01T10:00:00+05:30", "move") + "\n" + _line("2026-11-05T08:50:00+05:30", "morning") + "\n")
    monkeypatch.setattr(mc, "_NOTIFY_LOG", inbox)
    monkeypatch.setattr(mc, "CONTROLLER_LOG", tmp_path / "logs" / "master-controller.log")     # no log: no cause named
    fake_clock(monkeypatch, at(2026, 11, 6, 22, 0))
    monkeypatch.setattr(mc, "_index_rows", lambda symbol, since: N50 if symbol == "NIFTY 50" else BANK)
    assert mc.backfill_outage_main(["--execute", "--steps", "notes", "--since", "2026-11-02", "--until", "2026-11-03"]) == 0
    lines = inbox.read_text().splitlines()
    kinds = [(json.loads(x).get("for_session"), json.loads(x)["kind"]) for x in lines]
    assert kinds == [(None, "move"), ("2026-11-02", "gap"), ("2026-11-02", "close"), ("2026-11-03", "gap"),
                     ("2026-11-03", "close"), (None, "morning")]
    assert mc.backfill_outage_main(["--execute", "--steps", "notes", "--since", "2026-11-02", "--until", "2026-11-03"]) == 0
    assert inbox.read_text().splitlines() == lines                                     # idempotent
    assert not any("controller" in json.loads(x).get("body", "") for x in lines)       # no log → no cause


def test_the_notes_step_names_an_outage_only_where_the_controller_log_records_one(monkeypatch: pytest.MonkeyPatch,
                                                                                 tmp_path: Path,
                                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    inbox = tmp_path / "notifications.jsonl"
    inbox.write_text(_line("2026-10-30T15:40:00+05:30", "close") + "\n")
    monkeypatch.setattr(mc, "_NOTIFY_LOG", inbox)
    log = tmp_path / "logs" / "master-controller.log"
    log.parent.mkdir()
    log.write_text("\n".join(LOG_LINES[:2]) + "\n")                     # 28 Oct 12:46 → 30 Oct 08:11 only
    (tmp_path / "logs" / "master-controller.log.1").write_text(LOG_LINES[2] + "\n")     # a rotated copy is read too
    monkeypatch.setattr(mc, "CONTROLLER_LOG", log)
    fake_clock(monkeypatch, at(2026, 11, 7, 10, 0))                                     # a Saturday: no freeze window
    rows = [{"date": "2026-10-29", "close": 22900.0}, *N50]
    monkeypatch.setattr(mc, "_index_rows", lambda symbol, since: rows if symbol == "NIFTY 50" else BANK)
    assert mc.backfill_outage_main(["--execute", "--steps", "notes", "--since", "2026-10-29", "--until", "2026-11-02"]) == 0
    assert "5 missed note slot(s) (4 inside a downtime the controller's log records)" in capsys.readouterr().out
    recs = {(r["for_session"], r["for_slot"]): r for r in map(json.loads, inbox.read_text().splitlines()) if r.get("backfilled")}
    assert set(recs) == {("2026-10-29", "morning"), ("2026-10-29", "close"), ("2026-10-30", "morning"),
                         ("2026-11-02", "morning"), ("2026-11-02", "close")}
    assert "down from 28 Oct 12:46 to 30 Oct 08:11" in recs[("2026-10-29", "morning")]["body"]
    assert "down from 31 Oct 11:29 to 04 Nov 21:29" in recs[("2026-11-02", "close")]["body"]
    # negative control: 30 Oct 08:50 — the controller was back at 08:11, so the line names no cause
    assert "controller" not in recs[("2026-10-30", "morning")]["body"]


def test_the_entrypoint_routes_the_subcommand_before_the_no_argument_guard() -> None:
    src = (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    assert main.index('sys.argv[1] == "backfill-outage"') < main.index("uvicorn.run(")
    assert main.index('sys.argv[1] == "backfill-outage"') < main.index("Takes no arguments")


def test_the_lifespan_never_leaves_the_dataset_check_armed() -> None:
    src = (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
    life = src[src.index("async def lifespan("):src.index("app = FastAPI(")]
    assert '_DATASET_CHECK["armed"] = True' in life and '_DATASET_CHECK["armed"] = False' in life
    assert life.index('_DATASET_CHECK["armed"] = False') > life.index("yield")


def test_evening_replay_order_matches_the_schedule() -> None:
    """The replay order is the evening's own order (each job after the ones it reads) with one exception: the S1 shadow
    runs before the 19:45 news track record (6 Nov checker: the review asked "the S1 shadow first"; the shadow never reads
    the track record, whose subprocess may take 30 min). The slots are pinned on the registered crons."""
    order = [job for job, _, _ in mc.EVENING_REPLAY]
    by_slot = [job for job, _, _ in sorted(mc.EVENING_REPLAY, key=lambda e: e[2])]
    shadow_first = [j for j in by_slot if j != "alpha_shadow_daily"]
    shadow_first.insert(shadow_first.index("news_track_record_daily"), "alpha_shadow_daily")
    assert order == shadow_first
    assert order.index("desk_daily") < order.index("alpha_shadow_daily") < order.index("news_track_record_daily")
    assert by_slot != order                                    # negative control: plain slot order puts the track record first
    src = (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
    for job, _, slot in mc.EVENING_REPLAY:            # the replay's slot is the job's registered cron
        block = src[src.index(f'id="{job}"') - 400:src.index(f'id="{job}"')]
        assert f"hour={slot.hour}, minute={slot.minute}" in block, job
    assert timedelta(minutes=5) > timedelta(0)


def test_a_failed_replay_is_reported_as_failed_never_as_replayed(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock(monkeypatch, at(2026, 11, 5, 19, 57))

    async def broken_shadow() -> None:
        async with mc._track("alpha_shadow_daily"):
            mc._mark_failed("alpha_shadow_daily")
    monkeypatch.setattr(mc, "alpha_shadow_daily", broken_shadow)
    asyncio.run(mc._startup_catchup_run("2026-11-05T19:34:54+05:30", "2026-11-05T19:55:26+05:30",
                                        {"alpha_shadow_daily": 1, "db_backup_daily": 1}, "skip", "21:16",
                                        ["alpha_shadow_daily"], []))
    body = ctl["alerts"].sent[0][2]
    assert "alpha_shadow_daily: re-run (error)" in body and "replayed every missed session" not in body
    assert "today's 02:15 backup is missing: one run at 21:16" in body
    assert "NOT re-run" not in body                    # the backup has its one-off, the shadow was re-run (and failed)


# ── 6 Nov checker (major 1): the REAL alpha_shadow_daily / desk_daily inside the replay, never a stub ─────────────
def _report(ctl: dict[str, Any]) -> str:
    return next(b for _, t, b in ctl["alerts"].sent if t.startswith("Stack was down"))


def _replay_shadow(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch, run: Any) -> str:
    ctl["alerts"].sent.clear()
    monkeypatch.setattr(mc.subprocess, "run", run)
    asyncio.run(mc._startup_catchup_run("2026-11-05T19:34:54+05:30", "2026-11-05T19:55:26+05:30",
                                        {"alpha_shadow_daily": 1}, "skip", None, ["alpha_shadow_daily"], []))
    return _report(ctl)


def test_the_real_s1_shadow_failing_in_the_replay_is_reported_as_failed(ctl: dict[str, Any],
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock(monkeypatch, at(2026, 11, 5, 19, 57))
    calls: list[list[str]] = []

    def exits(code: int) -> Any:
        def run(cmd: list[str], **k: Any) -> SimpleNamespace:
            calls.append(cmd)
            return SimpleNamespace(returncode=code, stdout="", stderr="Traceback (most recent call last):\nValueError: boom")
        return run
    # a non-zero exit: SYS says error, the report says error, never "replayed"
    body = _replay_shadow(ctl, monkeypatch, exits(1))
    assert calls and calls[-1][-2].endswith("alpha_lab/paper/shadow.py") and calls[-1][-1] == "--daily"
    assert "alpha_shadow_daily: re-run (error)" in body and "replayed every missed session" not in body
    assert mc._latency.stats("alpha_shadow_daily")["alpha_shadow_daily"]["last_status"] == "error"
    assert ("warning", "S1 shadow job failed") in [(lv, t) for lv, t, _ in ctl["alerts"].sent]
    assert "exit 1: ValueError: boom" in next(b for _, t, b in ctl["alerts"].sent if t == "S1 shadow job failed")

    # an exception (a timeout, a spawn error): the same
    def boom(cmd: list[str], **k: Any) -> Any:
        raise mc.subprocess.TimeoutExpired(cmd, 600)
    body = _replay_shadow(ctl, monkeypatch, boom)
    assert "alpha_shadow_daily: re-run (error)" in body and "replayed every missed session" not in body
    assert ("warning", "S1 shadow job failed") in [(lv, t) for lv, t, _ in ctl["alerts"].sent]

    # NEGATIVE CONTROL: exit 0 → done, and only then the "replayed" line
    body = _replay_shadow(ctl, monkeypatch, exits(0))
    assert "alpha_shadow_daily: re-run (done)" in body
    assert "the S1 shadow replayed every missed session from stored closes (rules unchanged)" in body
    assert "S1 shadow job failed" not in [t for _, t, _ in ctl["alerts"].sent]


def test_a_disabled_desk_or_a_run_that_moved_nothing_is_never_a_replay(ctl: dict[str, Any],
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock(monkeypatch, at(2026, 11, 5, 20, 5))
    posts: list[str] = []

    def ui_api(req: httpx.Request) -> httpx.Response:
        posts.append(req.url.path)
        return httpx.Response(200, json={"sessions_marked": 1, "executions": [], "plan": None})
    mock_http(monkeypatch, ui_api)

    def catchup() -> str:
        ctl["alerts"].sent.clear()
        asyncio.run(mc._startup_catchup_run("2026-11-05T19:25:00+05:30", "2026-11-05T20:03:00+05:30",
                                            {"desk_daily": 1}, "skip", None, ["desk_daily"], []))
        return _report(ctl)
    # DESK_ENABLED=0: the REAL desk_daily records "skipped"; nothing was marked, so nothing "replayed"
    monkeypatch.setattr(mc, "DESK_ENABLED", False)
    body = catchup()
    assert posts == [] and "desk_daily: re-run (skipped)" in body and "the Desk replayed" not in body
    assert mc._latency.stats("desk_daily")["desk_daily"]["last_status"] == mc.STATUS_SKIPPED
    # a run that moved no dataset ("no new data") replayed nothing either
    monkeypatch.setattr(mc, "DESK_ENABLED", True)
    monkeypatch.setattr(mc, "dataset_outcome", lambda before, after: mc.STATUS_NO_NEW_DATA)
    monkeypatch.setattr(mc, "_dataset_snapshot", lambda job_id: asyncio.sleep(0, result={"desk_mark": ("2026-10-30",)}))
    body = catchup()
    assert posts[0] == "/api/desk/daily" and [p for p in posts[1:] if "data-health" not in p] == [], \
        f"only the desk replay + its watermark check may post here: {posts}"
    assert "desk_daily: re-run (no new data)" in body and "the Desk replayed" not in body
    # NEGATIVE CONTROL: the Desk enabled and its datasets moved → done → "the Desk replayed every missed session"
    monkeypatch.setattr(mc, "dataset_outcome", lambda before, after: None)
    body = catchup()
    assert "desk_daily: re-run (done)" in body and "the Desk replayed every missed session" in body


def test_an_earlier_done_never_reads_as_this_catch_up_s_replay(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The status quoted is the one THIS catch-up's run recorded: a shadow that returned before _track (its lock held by
    a run in flight) must not borrow the 19:00 'done' of an earlier run."""
    fake_clock(monkeypatch, at(2026, 11, 5, 19, 0))
    assert _track_once("alpha_shadow_daily") == "done"                       # an earlier run, before the catch-up
    fake_clock(monkeypatch, at(2026, 11, 5, 19, 57))

    async def returned_early() -> None:
        return None
    monkeypatch.setattr(mc, "alpha_shadow_daily", returned_early)
    asyncio.run(mc._startup_catchup_run("2026-11-05T19:34:54+05:30", "2026-11-05T19:55:26+05:30",
                                        {"alpha_shadow_daily": 1}, "skip", None, ["alpha_shadow_daily"], []))
    body = _report(ctl)
    assert "alpha_shadow_daily: re-run requested, no run recorded" in body and "replayed every missed session" not in body
    # negative control: the helper does see a run that ended at or after the catch-up's start
    assert mc._status_since("alpha_shadow_daily", at(2026, 11, 5, 18, 0)) == "done"
    assert mc._status_since("alpha_shadow_daily", at(2026, 11, 5, 19, 30)) is None


def test_a_failed_desk_in_the_full_catchup_never_stops_the_shadow_or_the_report(ctl: dict[str, Any],
                                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """desk_daily raises on failure; outside the window (_terminal_downtime_catchup) that used to abort the shadow and
    the whole 'Stack was down' report."""
    fake_clock(monkeypatch, at(2026, 11, 7, 10, 0))
    monkeypatch.setattr(mc, "TERMINAL_JOBS_ENABLED", False)
    monkeypatch.setattr(mc, "DATA_JOB_POLL_SECS", 0)

    def svc(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/desk/daily":
            return httpx.Response(500, text="desk store locked")
        if req.method == "POST":
            return httpx.Response(200, json={"job_id": "j1"})
        if req.url.path.startswith("/jobs/"):
            return httpx.Response(200, json={"status": "done", "result": {}})
        return httpx.Response(200, json={})
    mock_http(monkeypatch, svc)
    monkeypatch.setattr(mc.subprocess, "run", lambda cmd, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    asyncio.run(mc._startup_catchup_run("2026-11-06T21:30:00+05:30", "2026-11-07T09:58:00+05:30",
                                        {"desk_daily": 1, "alpha_shadow_daily": 1}, "nse", None))
    body = _report(ctl)
    assert "Desk mark: re-run FAILED RuntimeError" in body and "S1 shadow: re-run (done; its 19:50 run was missed)" in body
    assert "the S1 shadow replayed every missed session" in body and "the Desk and" not in body
    assert "the Desk replayed" not in body
    assert ("critical", "Decision Desk cycle FAILED") in [(lv, t) for lv, t, _ in ctl["alerts"].sent]


# ── 6 Nov checker (minor): catchup_at never outlives the catch-up that owned it ──────────────────────────────────
def test_catchup_notes_name_only_the_missed_jobs() -> None:
    assert mc.catchup_notes("nse", {"results_capture_daily": 1, "filing_alerts": 4}, ()) == ["results_capture_daily"]
    assert "nse_positions_catchup" not in mc.catchup_notes("full", {"eod_data_pipeline": 1}, ())
    # control: a missed one is named, and the replay keeps its order first
    assert mc.catchup_notes("nse", {"nse_positions_catchup": 1}, ()) == ["nse_positions_catchup"]
    assert mc.catchup_notes("skip", {"alpha_shadow_daily": 1, "news_track_record_daily": 1},
                            ["alpha_shadow_daily", "news_track_record_daily"]) == ["alpha_shadow_daily", "news_track_record_daily"]


def test_the_startup_catchup_spends_the_catchup_at_of_the_jobs_it_ran(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "TERMINAL_JOBS_ENABLED", False)
    monkeypatch.setattr(mc, "DATA_JOB_POLL_SECS", 0)
    now = at(2026, 11, 6, 10, 0)
    fake_clock(monkeypatch, now)

    def svc(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={"job_id": "j1"})
        if req.url.path.startswith("/jobs/"):
            return httpx.Response(200, json={"status": "done", "result": {"days_loaded": 1}})
        return httpx.Response(200, json={"as_of": "2026-11-05"})
    mock_http(monkeypatch, svc)
    missed = {"nse_positions_catchup": 1, "results_capture_daily": 1}

    def run() -> dict[str, str]:
        for name in mc.catchup_notes("nse", missed, ()):
            mc._note_catchup(name, now)
        mc._note_catchup("daily_wrap", now)                    # another job's catch-up: never touched here
        asyncio.run(mc._startup_catchup_run("2026-11-05T22:00:00+05:30", "2026-11-06T09:59:00+05:30", missed, "nse", None))
        return dict(mc._CATCHUP_PLAN)
    assert run() == {"daily_wrap": "2026-11-06T10:00:00+05:30"}      # ran under startup_catchup's id, yet cleared
    # negative control: a job whose own one-off is still pending in the scheduler keeps its catch-up time
    mc._CATCHUP_PLAN.clear()
    monkeypatch.setattr(mc, "scheduler", SimpleNamespace(get_job=lambda jid: object() if jid == "results_capture_daily_catchup"
                                                         else None))
    assert run() == {"daily_wrap": "2026-11-06T10:00:00+05:30", "results_capture_daily": "2026-11-06T10:00:00+05:30"}
    # negative control: a gold job the catch-up moves to the end of a freeze window keeps that (future) time
    added: list[str] = []
    monkeypatch.setattr(mc, "scheduler", SimpleNamespace(get_job=lambda jid: None,
                                                         add_job=lambda *a, **k: added.append(k["id"])))
    mc._CATCHUP_PLAN.clear()
    fake_clock(monkeypatch, at(2026, 11, 6, 19, 57))
    asyncio.run(mc._startup_catchup_run("2026-11-06T19:30:00+05:30", "2026-11-06T19:55:00+05:30",
                                        {"gold_overnight": 1}, "skip", None, [], []))
    assert added == ["gold_downtime_catchup"] and mc._CATCHUP_PLAN.get("gold_overnight", "") > "2026-11-06T21:"


def test_a_gold_job_the_catchup_skips_has_no_catchup_time_left(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_session() -> bool:
        return False
    monkeypatch.setattr(mc, "_breeze_session_live", no_session)
    mc._note_catchup("gold_mcx_close", at(2026, 11, 6, 9, 21))
    mc._note_catchup("gold_cot_weekly", at(2026, 11, 7, 2, 30))          # not part of this catch-up (control)
    line = asyncio.run(mc.gold_downtime_catchup(["gold_mcx_close"], "2026-11-03"))
    assert "gold_mcx_close: not re-run" in line
    assert mc._CATCHUP_PLAN == {"gold_cot_weekly": "2026-11-07T02:30:00+05:30"}


def test_every_tracked_run_feeds_sd_job_seconds(ctl: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """M38 (controller part): observe_job had 0 callers, so sd_job_seconds never appeared on /metrics."""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(mc, "observe_job", lambda job, seconds, status="ok": seen.append((job, status)))
    _track_once("desk_daily")
    _track_once("desk_daily", fail=True)
    assert seen == [("desk_daily", "done"), ("desk_daily", "error")]

    def broken(*a: Any, **k: Any) -> None:
        raise RuntimeError("registry gone")
    monkeypatch.setattr(mc, "observe_job", broken)
    assert _track_once("desk_daily") == "done"                  # control: a broken metric never fails the job
