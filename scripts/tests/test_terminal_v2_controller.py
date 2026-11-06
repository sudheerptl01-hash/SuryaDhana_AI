"""Terminal v2 — the controller's part (reports/terminal_v2/PLAN.md Wave 0 0.5 / 0.9, Wave 1.1 / 1.2 / 1.4 jobs; builder
B2; gate G11): the 18:30 pipeline equity-only, the 20:30 pass carrying the evening files + the drivers retry + iv_eod
last, the new 22:45 pass and 08:35 sweep, iv_intraday's gates, iv_weekly, the hourly data-health transitions,
DATASET_MAX_AGE_DAYS retired, the extended start-up catch-up with gap rows, the terminal jobs in missed_jobs(), the
freeze-window rule, the watchdog's second heartbeat. Every rule has its negative control. Nothing here touches the live
stack: data-service and ui-api are httpx.MockTransport fakes, the state files live in tmp_path."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from apscheduler.triggers.cron import CronTrigger

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc  # noqa: E402

IST = mc.IST
TERMINAL_JOB_IDS = ["index_drivers_daily", "nse_evening_pass", "morning_sweep", "iv_intraday", "iv_weekly", "data_health_check"]
DIRECTION_WORDS = re.compile(r"\b(bullish|bearish|buy|sell|go long|go short|target|(?<!not )forecast[s]?)\b", re.IGNORECASE)


def at(y: int, mo: int, d: int, h: int, mi: int, s: int = 0) -> datetime:
    return IST.localize(datetime(y, mo, d, h, mi, s))  # noqa: DTZ001 — pytz: localize, never tzinfo=


def fake_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(mc, "datetime", FakeDT)


class _Alerts:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def info(self, title: str, body: str) -> None:
        self.sent.append(("info", title, body))

    async def warning(self, title: str, body: str) -> None:
        self.sent.append(("warning", title, body))

    async def critical(self, title: str, body: str) -> None:
        self.sent.append(("critical", title, body))


class _FakeScheduler:
    def __init__(self) -> None:
        self.added: list[tuple[str, dict[str, Any]]] = []

    def add_job(self, func: Any, **kw: Any) -> None:
        self.added.append((func.__name__, kw))

    def get_jobs(self) -> list:
        return []


class Services:
    """A fake data-service (:8001) and ui-api (:8010): every POST /jobs/* starts a job whose GET /jobs/<id> answers 'done'
    with `results[path]` (or an error when `errors[path]` is set); other routes come from `routes`. Records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, Any]] = []
        self.routes: dict[tuple[str, str], Any] = {}
        self.results: dict[str, Any] = {}
        self.errors: dict[str, str] = {}
        self.statuses: dict[str, int] = {}  # a POST path → non-200 status (404: package not deployed)
        self._jobs: dict[str, str] = {}
        self._n = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = request.content
        self.calls.append((method, path, request.url.query.decode(), body))
        if method == "POST" and path.startswith("/jobs/"):
            if path in self.statuses:
                return httpx.Response(self.statuses[path], text="no such endpoint")
            self._n += 1
            jid = f"j{self._n}"
            self._jobs[jid] = path
            return httpx.Response(200, json={"job_id": jid})
        if method == "GET" and path.startswith("/jobs/j"):
            src = self._jobs[path.rsplit("/", 1)[1]]
            if src in self.errors:
                return httpx.Response(200, json={"status": "error", "error": self.errors[src]})
            return httpx.Response(200, json={"status": "done", "result": self.results.get(src, {"status": "ok"})})
        route = self.routes.get((method, path))
        if route is None:
            return httpx.Response(404)
        if callable(route):
            return route(request)
        if isinstance(route, int):
            return httpx.Response(route)
        return httpx.Response(200, json=route)

    def posts(self, path: str) -> list[tuple[str, Any]]:
        return [(q, b) for m, p, q, b in self.calls if m == "POST" and p == path]

    def post_paths(self) -> list[str]:
        return [p for m, p, _, _ in self.calls if m == "POST"]


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> Services:
    s = Services()
    real = httpx.AsyncClient
    monkeypatch.setattr(
        mc.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(s.handle), timeout=k.get("timeout"))
    )
    monkeypatch.setattr(mc, "DATA_SVC", "http://127.0.0.1:8001")
    monkeypatch.setattr(mc, "UI_API", "http://127.0.0.1:8010")
    monkeypatch.setattr(mc, "DATA_JOB_POLL_SECS", 0)
    return s


@pytest.fixture
def ctl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    alerts = _Alerts()
    sched = _FakeScheduler()
    monkeypatch.setattr(mc, "_alerts", alerts)
    monkeypatch.setattr(mc, "_latency", mc.LatencyTracker())
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "never-armed.json"))
    monkeypatch.setattr(mc, "_log", mc.LogRingBuffer())
    monkeypatch.setattr(mc, "scheduler", sched)
    monkeypatch.setattr(mc, "_TERMINAL_PAUSED_UNTIL", 0.0)
    monkeypatch.setattr(mc, "_GOLD_PAUSED_UNTIL", 0.0)
    monkeypatch.setattr(mc, "_GOLD_LAST_WARNED", {})
    monkeypatch.setattr(mc, "_IV_EOD_STATE", {})
    monkeypatch.setattr(mc, "_DRIVERS_STATE", {})
    monkeypatch.setattr(mc, "_IV_INTRADAY_DAY", {})
    monkeypatch.setattr(mc, "_HOLIDAY_LOGGED", set())
    monkeypatch.setattr(mc, "_HOLIDAYS", {"at": 10**12, "days": {}})  # no holiday lookup, none today
    monkeypatch.setattr(mc, "_job_locks", {})
    monkeypatch.setattr(mc, "DATA_HEALTH_STATE_FILE", tmp_path / "health_state.json")
    for flag in ("GOLD_JOBS_ENABLED", "DATA_JOBS_ENABLED", "TERMINAL_JOBS_ENABLED"):
        monkeypatch.setattr(mc, flag, True)
    return {"alerts": alerts, "sched": sched}


def log_lines() -> list[str]:
    return [json.loads(ln)["msg"] for ln in mc._log.tail(500)]


def _health(rows: list[dict], last_session: str = "2026-11-04") -> dict:
    states = [r["state"] for r in rows]
    return {
        "as_of": "2026-11-05T08:35:00+05:30",
        "rows": rows,
        "last_session": last_session,
        "summary": {
            "green": sum(s in ("fresh", "live") for s in states),
            "amber": states.count("amber"),
            "red": states.count("red"),
            "gaps": states.count("gap"),
            "rows": len(rows),
        },
    }


# ── the schedule (PLAN Wave 0 0.5 / Wave 1 jobs) and the freeze-window rule (§0.10) ──────────────────────────


def _registered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """The real lifespan() with a paused scheduler: {job id: apscheduler Job}."""

    class Paused(mc.AsyncIOScheduler):
        def start(self, paused: bool = False) -> None:
            super().start(paused=True)

    fake_clock(monkeypatch, at(2030, 3, 4, 21, 20))
    monkeypatch.setattr(mc, "_alerts", _Alerts())
    monkeypatch.setattr(mc, "HEARTBEAT_FILE", tmp_path / "hb.json")
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "history.json"))
    monkeypatch.setattr(mc, "_log", mc.LogRingBuffer())
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: [])
    monkeypatch.setattr(mc, "scheduler", None)
    monkeypatch.setattr(mc, "AsyncIOScheduler", Paused)

    async def no_bot() -> None:
        return None

    monkeypatch.setattr(mc, "telegram_poller", no_bot)

    async def scenario():
        async with mc.lifespan(mc.app):
            return {j.id: j for j in mc.scheduler.get_jobs()}

    return asyncio.run(scenario())


def _fires(trigger: Any, start: datetime, n: int) -> list[str]:
    out, prev = [], None
    for _ in range(n):
        t = trigger.get_next_fire_time(prev, (prev or start) + timedelta(microseconds=1))
        out.append(t.astimezone(IST).strftime("%a %H:%M"))
        prev = t
    return out


def test_lifespan_registers_the_terminal_jobs_at_their_ist_times(monkeypatch, tmp_path):
    jobs = _registered(monkeypatch, tmp_path)
    assert set(TERMINAL_JOB_IDS) <= set(jobs)
    mon = at(2026, 11, 2, 0, 0)  # Monday 2 Nov 2026
    assert _fires(jobs["index_drivers_daily"].trigger, mon, 2) == ["Mon 19:25", "Tue 19:25"]
    assert _fires(jobs["nse_evening_pass"].trigger, mon, 2) == ["Mon 22:45", "Tue 22:45"]
    assert _fires(jobs["morning_sweep"].trigger, mon, 2) == ["Mon 08:35", "Tue 08:35"]
    assert _fires(jobs["iv_weekly"].trigger, mon, 2) == ["Sat 03:00", "Sat 03:00"]
    assert _fires(jobs["data_health_check"].trigger, mon, 3) == ["Mon 00:10", "Mon 01:10", "Mon 02:10"]
    ticks = _fires(jobs["iv_intraday"].trigger, mon, 211)            # PLAN 2.1: every 2 minutes, 09:00–15:58 (the gate keeps 09:15–15:30)
    assert (
        ticks[:3] == ["Mon 09:00", "Mon 09:02", "Mon 09:04"]
        and "Mon 09:16" in ticks and "Mon 15:30" in ticks
        and ticks[209:211] == ["Mon 15:58", "Tue 09:00"]
    )
    assert _fires(jobs["iv_intraday"].trigger, at(2026, 11, 6, 16, 0), 1) == ["Mon 09:00"], "no weekend ticks"
    assert _fires(jobs["nse_positions_catchup"].trigger, mon, 1) == ["Mon 20:30"], "20:30 unchanged (carries iv_eod last)"
    assert "iv_eod" not in jobs, "iv_eod is a step of the 20:30 pass and the 22:45 retry, not a job of its own"
    assert jobs["nse_evening_pass"].misfire_grace_time == 3 * 3600 and jobs["iv_intraday"].misfire_grace_time == 120


def test_no_terminal_job_fires_inside_a_freeze_window_except_the_light_stored_data_ones(monkeypatch, tmp_path):
    """PLAN §0.10: nothing inside 07:45–09:20 / 18:30–21:15 except the light class. The 19:25 drivers (stored data + 3
    small GETs) and the 08:35 sweep (≤ 6 small GET-only jobs) are that class by the plan's own words; the hourly check is
    one local GET; the 09:05 intraday cron tick is skipped by the gate before any request."""
    jobs = _registered(monkeypatch, tmp_path)
    light = {"index_drivers_daily", "morning_sweep", "data_health_check", "iv_intraday"}
    for jid in TERMINAL_JOB_IDS:
        if jid in light:
            continue
        for stamp in _fires(jobs[jid].trigger, at(2026, 11, 2, 0, 0), 14):
            hh, mm = stamp.split()[1].split(":")
            hm = time(int(hh), int(mm))
            assert not any(a <= hm <= b for a, b in mc.FREEZE_WINDOWS), f"{jid} fires at {stamp}"
    assert not mc.iv_intraday_due(at(2026, 11, 2, 9, 5)), "the 09:05 tick (inside the morning window) never requests"
    assert mc.iv_intraday_due(at(2026, 11, 2, 9, 20)) and mc.iv_intraday_due(at(2026, 11, 2, 15, 30))
    assert mc.iv_intraday_due(at(2026, 11, 2, 9, 16)) and not mc.iv_intraday_due(at(2026, 11, 2, 9, 14)), "M45: the whole session from 09:15"
    assert not mc.iv_intraday_due(at(2026, 11, 2, 15, 35)) and not mc.iv_intraday_due(at(2026, 11, 7, 10, 0))


def test_the_1830_pipeline_is_equity_only(monkeypatch, ctl):
    seen: list[tuple[str, dict]] = []

    async def fake_job(job, path, body, quiet=False):
        seen.append((path, body))
        return {"refresh": {}, "bhavcopy": {"rows_written": 1}, "build": {}}

    async def no_check(job):
        return []

    monkeypatch.setattr(mc, "_run_data_job", fake_job)
    monkeypatch.setattr(mc, "_check_dataset_freshness", no_check)
    asyncio.run(mc.eod_data_pipeline())
    assert seen == [("/jobs/daily-pipeline", {"mode": "incremental", "skip_steps": ["nse_positions"]})]
    assert mc.EOD_PIPELINE_BODY["skip_steps"] == ["nse_positions"], "the F&O files land 20:10: the 20:30 pass fetches them"


# ── the 20:30 pass: evening files, the drivers retry, iv_eod last (PLAN 1.1 / 1.2 / 1.4) ─────────────────────


def test_the_2030_pass_runs_the_evening_files_then_iv_eod_last_and_retries_the_drivers_only_when_the_top10_was_missing(
    ctl, svc, monkeypatch
):
    fake_clock(monkeypatch, at(2026, 11, 4, 20, 30))
    svc.routes[("POST", "/db/fii-dii-cash/refresh")] = {"ok": True}
    svc.results["/jobs/ingest-nse-positions"] = {"tables": {"nse_fo_daily": {"last": "2026-11-04"}}}
    svc.results[mc.NSE_FILES_PATH] = {"files": {"nse_fii_stats": [{"status": "downloaded"}]}, "status": "ok"}
    svc.results[mc.IV_EOD_PATH] = {
        "status": "ok",
        "date": "2026-11-04",
        "iv": {"expiry_rows": 400, "surface_rows": 9000, "summary_rows": 224},
    }
    svc.results[mc.INDEX_DRIVERS_PATH] = {"status": "ok", "top10": {"status": "downloaded", "rows": 10}, "indices": {}}
    mc._DRIVERS_STATE.update(date="2026-11-04", top10_missing=True)  # the 19:25 run found no top-10 file
    asyncio.run(mc.nse_positions_catchup())
    paths = svc.post_paths()
    assert paths == [
        "/jobs/ingest-nse-positions",
        "/db/fii-dii-cash/refresh",
        mc.NSE_FILES_PATH,
        mc.INDEX_DRIVERS_PATH,
        mc.IV_EOD_PATH,
    ]
    assert svc.posts(mc.NSE_FILES_PATH)[0][1] == {"datasets": list(mc.NSE_EVENING_FILES)}
    assert svc.posts(mc.INDEX_DRIVERS_PATH) == [("job=index_drivers_daily", {"job": "index_drivers_daily", "date": "2026-11-04"})]
    assert svc.posts(mc.IV_EOD_PATH) == [("job=iv_eod", {"job": "iv_eod", "date": "2026-11-04"})]
    assert mc._IV_EOD_STATE["status"] == "ok" and mc._DRIVERS_STATE["top10_missing"] is False
    assert any("iv_eod 2026-11-04: expiry rows 400" in ln for ln in log_lines())
    # negative control: the 19:25 run had the top-10 file → no drivers retry; iv_eod still last
    svc.calls.clear()
    asyncio.run(mc.nse_positions_catchup())
    assert mc.INDEX_DRIVERS_PATH not in svc.post_paths() and svc.post_paths()[-1] == mc.IV_EOD_PATH
    # negative control: TERMINAL_JOBS_ENABLED=0 keeps the pre-existing two steps only
    monkeypatch.setattr(mc, "TERMINAL_JOBS_ENABLED", False)
    svc.calls.clear()
    asyncio.run(mc.nse_positions_catchup())
    assert svc.post_paths() == ["/jobs/ingest-nse-positions", "/db/fii-dii-cash/refresh"]
    assert ctl["alerts"].sent == [], "a clean pass sends nothing"


def test_iv_eod_not_yet_is_retried_at_2245_and_a_miss_of_the_slo_is_one_info_line(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 11, 4, 20, 31))
    svc.routes[("POST", "/db/fii-dii-cash/refresh")] = {"ok": True}
    svc.results[mc.IV_EOD_PATH] = {
        "status": "not_yet",
        "date": "2026-11-04",
        "reason": "no F&O file for 2026-11-04 (NSE publishes ≈ 20:10; retry in the 22:45 pass)",
    }
    assert asyncio.run(mc.iv_eod_step("nse_positions_catchup", "2026-11-04")) == "not_yet"
    assert mc.iv_eod_missed(mc._IV_EOD_STATE, "2026-11-04")
    # 22:45: the retry still finds no file → one Telegram info line, no critical
    fake_clock(monkeypatch, at(2026, 11, 4, 22, 45))
    asyncio.run(mc.nse_evening_pass())
    assert svc.posts(mc.IV_EOD_PATH)[-1] == ("job=iv_eod", {"job": "iv_eod", "date": "2026-11-04"})
    [(level, title, body)] = ctl["alerts"].sent
    assert (
        (level, title) == ("info", "IV EOD missed its 21:30 SLO") and "retry in the 22:45 pass" in body and "08:35 sweep" in body
    )
    assert not DIRECTION_WORDS.search(body)
    # the retry that succeeds: no line
    ctl["alerts"].sent.clear()
    mc._IV_EOD_STATE.clear()
    svc.results[mc.IV_EOD_PATH] = {"status": "ok", "date": "2026-11-04", "iv": {}}
    asyncio.run(mc.nse_evening_pass())
    assert ctl["alerts"].sent == [] and mc._IV_EOD_STATE["retry"] is True
    # negative control: the 20:30 run was ok → the 22:45 pass does not re-run iv_eod at all
    svc.calls.clear()
    asyncio.run(mc.nse_evening_pass())
    assert mc.IV_EOD_PATH not in svc.post_paths() and ctl["alerts"].sent == []
    assert any("iv_eod already ok" in ln for ln in log_lines())
    # a failed job (data-service error) is 'failed' in the state, never raised into the pass
    svc.errors[mc.IV_EOD_PATH] = "boom"
    mc._IV_EOD_STATE.clear()
    assert asyncio.run(mc.iv_eod_step("x", "2026-11-04")) == "failed" and "boom" in mc._IV_EOD_STATE["reason"]


def test_the_2245_pass_fetches_the_late_files_with_revalidation(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 11, 4, 22, 45))
    svc.routes[("POST", "/db/fii-dii-cash/refresh")] = {"ok": True}
    svc.results["/jobs/ingest-nse-positions"] = {
        "tables": {"nse_mtf": {"last": "2026-11-03"}, "nse_fo_daily": {"last": "2026-11-04"}}
    }
    svc.results[mc.NSE_FILES_PATH] = {
        "status": "ok",
        "nse_bhavcopy": [{"status": "revised"}],
        "files": {"nse_fo_volt": [{"status": "not_modified"}], "nse_mwpl_clients": [{"status": "downloaded"}]},
    }
    svc.results["/jobs/ingest-results"] = {"symbols": 12, "rows": 9}
    mc._IV_EOD_STATE.update(date="2026-11-04", status="ok")
    asyncio.run(mc.nse_evening_pass())
    assert svc.post_paths() == [
        "/jobs/ingest-nse-positions",
        mc.NSE_FILES_PATH,
        "/db/fii-dii-cash/refresh",
        "/jobs/ingest-results",
    ]
    [(q, body)] = svc.posts(mc.NSE_FILES_PATH)
    assert body["revalidate"] is True and body["datasets"][0] == "nse_bhavcopy"
    assert set(body["datasets"]) == {"nse_bhavcopy", *mc.NSE_IV_FILES, *mc.NSE_EVENING_FILES}
    assert svc.posts("/jobs/ingest-results") == [("", {"recent_events_days": 3, "max_age_days": 0})]
    line = next(ln for ln in log_lines() if ln.startswith("positions mtf=2026-11-03"))
    assert "revisions downloaded=1 not_modified=1 revised=1" in line and "results symbols=12 rows=9" in line
    assert mc._latency.stats()["nse_evening_pass"]["last_status"] == "done"
    # negative control: a 404 on the revision endpoint (B1 not deployed) is a line, not a failed pass, and pauses an hour
    svc.calls.clear()
    svc.statuses[mc.NSE_FILES_PATH] = 404
    asyncio.run(mc.nse_evening_pass())
    assert mc._latency.stats()["nse_evening_pass"]["last_status"] == "done" and mc._TERMINAL_PAUSED_UNTIL > 0
    assert any("revisions: data-service has no /jobs/ingest-nse-files" in ln for ln in log_lines())


def test_revision_digest_and_top10_missing_tolerate_any_shape():
    assert mc.revision_digest(None) == "no result" and mc.revision_digest({}) == "nothing to revalidate"
    assert mc.revision_digest({"files": [{"status": "cached"}, {"status": "cached"}, "junk"]}) == "cached=2"
    assert mc.top10_missing({"top10": {"status": "missing"}}) and mc.top10_missing({"top10": {"status": "http_503"}})
    assert not mc.top10_missing({"top10": {"status": "cached"}}) and not mc.top10_missing({}) and not mc.top10_missing(None)


# ── the 08:35 sweep and the digest (Wave 0 0.5, PLAN 1.4) ───────────────────────────────────────────────────

SWEEP_ROWS = [
    {
        "id": "nse_mtf",
        "state": "amber",
        "job_id": "nse_positions_catchup",
        "lag_sessions": 1,
        "as_of": "2026-11-02",
        "note": "stored 02 Nov · expected by 23:00 · 1 session behind",
    },
    {"id": "nse_fo_daily", "state": "red", "job_id": "nse_positions_catchup", "lag_sessions": 3, "as_of": "2026-10-30"},
    {
        "id": "iv_summary_daily",
        "state": "red",
        "job_id": "iv_eod",
        "lag_sessions": 3,
        "as_of": "2026-10-30",
        "note": "stored 30 Oct",
    },
    {
        "id": "index_contribution_daily",
        "state": "amber",
        "job_id": "index_drivers_daily",
        "lag_sessions": 1,
        "as_of": "2026-11-03",
    },
    {"id": "nse_results", "state": "amber", "job_id": "results_capture_daily", "lag_sessions": 1, "as_of": "2026-11-03"},
    {"id": "nse_bhavcopy", "state": "amber", "job_id": "eod_data_pipeline", "lag_sessions": 1, "as_of": "2026-11-03"},
    {"id": "ohlcv", "state": "red", "job_id": "eod_data_pipeline", "lag_sessions": 3, "as_of": "2026-10-30"},  # Yahoo: never here
    {
        "id": "ml_features",
        "state": "red",
        "job_id": "eod_data_pipeline",
        "lag_sessions": 3,
        "as_of": "2026-10-30",
    },  # ML build: never
    {"id": "gold_cot", "state": "red", "job_id": "gold_cot_weekly", "lag_sessions": 5, "as_of": "2026-10-20"},  # gold: its own
    {
        "id": "archive:preopen",
        "state": "gap",
        "job_id": "preopen_capture",
        "lag_sessions": None,
        "unrecoverable": True,
    },  # gap: nothing
    {"id": "nse_fii_dii_cash", "state": "amber", "job_id": "nse_positions_catchup", "lag_sessions": 1, "unrecoverable": True},
    {
        "id": "nse_deals",
        "state": "fresh",
        "job_id": "nse_positions_catchup",
        "lag_sessions": 0,
        "as_of": "2026-11-04",
    },  # fresh: nothing
]


def test_plan_sweep_reruns_only_the_light_nse_fetches_once_each():
    plan = mc.plan_sweep(SWEEP_ROWS, "2026-11-04")
    assert [p["label"] for p in plan] == ["positions", "bhavcopy", "results", "drivers", "iv_eod"], "fetches first, computations last"
    by = {p["label"]: p for p in plan}
    assert by["positions"] == {"label": "positions", "path": "/jobs/ingest-nse-positions", "body": {}, "kind": "job"}
    assert by["iv_eod"]["body"] == {"job": "iv_eod", "backfill_from": "2026-10-31", "backfill_to": "2026-11-04"}, (
        "3 sessions behind: resumable backfill"
    )
    assert by["drivers"]["body"] == {"job": "index_drivers_daily", "date": "2026-11-04"}, "1 session behind: the last session"
    assert by["results"]["body"] == {"recent_events_days": 3, "max_age_days": 0}
    assert by["bhavcopy"]["path"] == "/jobs/ingest-bhavcopy"
    paths = " ".join(p["path"] for p in plan)
    assert "daily-pipeline" not in paths and "refresh-universe" not in paths and "build-ml" not in paths and "gold" not in paths
    assert mc.plan_sweep([], "2026-11-04") == [] and mc.plan_sweep([SWEEP_ROWS[-1]], "2026-11-04") == []
    many = [{"id": f"x{i}", "state": "red", "job_id": "iv_eod", "lag_sessions": 1} for i in range(3)] + [
        {"id": "a", "state": "red", "job_id": "results_capture_daily"},
        {"id": "b", "state": "red", "job_id": "nse_evening_pass"},  # no catalog row names this job: nothing (dead branch gone)
        {"id": "c", "state": "red", "job_id": "nse_positions_catchup"},
        {"id": "d", "state": "red", "job_id": "index_drivers_daily"},
        {"id": "nse_bhavcopy", "state": "red", "job_id": "eod_data_pipeline"},
        {"id": "nse_events", "state": "red", "job_id": "eod_data_pipeline"},
    ]
    plan = mc.plan_sweep(many, "2026-11-04")
    assert len(plan) == mc.SWEEP_MAX_JOBS and len({p["path"] for p in plan}) == len(plan), "deduplicated and capped"


def test_the_0835_sweep_runs_the_plan_sends_one_digest_and_is_quiet_when_nothing_is_missing(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 11, 5, 8, 35))
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health(SWEEP_ROWS)
    svc.routes[("POST", "/db/fii-dii-cash/refresh")] = {"ok": True}
    svc.results[mc.IV_EOD_PATH] = {"status": "ok", "days": 3}
    svc.results[mc.INDEX_DRIVERS_PATH] = {"status": "degraded"}
    asyncio.run(mc.morning_sweep())
    assert svc.post_paths() == [          # m112 (6 Nov): no /jobs/ingest-results inside the 07:45–09:20 window
        "/jobs/ingest-nse-positions",
        "/jobs/ingest-bhavcopy",
        mc.INDEX_DRIVERS_PATH,
        mc.IV_EOD_PATH,
        "/db/fii-dii-cash/refresh",
    ]
    assert svc.posts(mc.IV_EOD_PATH) == [
        ("job=iv_eod", {"job": "iv_eod", "backfill_from": "2026-10-31", "backfill_to": "2026-11-04"})
    ]
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("info", "DATA 08:35 digest")
    assert body.startswith("1 green · 5 amber · 5 red · 1 gap of 12 datasets (last session 2026-11-04)")
    assert "and 1 more on SYS › DATA" in body, "11 rows that are not green: ten listed, the rest counted"
    assert (
        "GAP archive:preopen" in body and "RED iv_summary_daily: stored 30 Oct" in body and "AMBER nse_mtf: stored 02 Nov" in body
    )
    assert ("Sweep: results left to the 20:45 capture (≈ 14 min: not a light fetch in the window); positions ok; "
            "bhavcopy ok; drivers degraded; iv_eod ok; FII/DII HTTP 200") in body
    assert not DIRECTION_WORDS.search(body) and "score" not in body.lower()
    # nothing missing: no job, the digest alone
    svc.calls.clear()
    ctl["alerts"].sent.clear()
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health([SWEEP_ROWS[-1]])
    asyncio.run(mc.morning_sweep())
    assert svc.post_paths() == [] and [a[1] for a in ctl["alerts"].sent] == ["DATA 08:35 digest"]
    assert any("nothing missing from last night" in ln for ln in log_lines())
    # negative control: ui-api without the view → no job, no digest, one WARNING, the run is still 'done'
    svc.calls.clear()
    ctl["alerts"].sent.clear()
    del svc.routes[("GET", mc.DATA_HEALTH_API)]
    asyncio.run(mc.morning_sweep())
    assert svc.post_paths() == [] and ctl["alerts"].sent == []
    assert any("no data-health view: nothing swept, no digest" in ln for ln in log_lines())


# ── check:B2-CTRL major: the sweep and the catch-up re-fetch the evening + IV input files for missed sessions ──
# rows in the shape B3 serves from B1's catalog: the evening files carry job nse_positions_catchup, the IV inputs iv_eod —
# neither job's own path fetches them (the positions ingest is legacy-only; iv_eod reads the stored files)
EVENING_ROWS = [
    {"id": "nse_participant_vol", "state": "amber", "job_id": "nse_positions_catchup", "lag_sessions": 1, "as_of": "2026-11-03"},
    {"id": "nse_fii_stats", "state": "red", "job_id": "nse_positions_catchup", "lag_sessions": 3, "as_of": "2026-10-30"},
    {"id": "nse_fo_volt", "state": "red", "job_id": "iv_eod", "lag_sessions": 3, "as_of": "2026-10-30"},
    {"id": "nse_contract_delta", "state": "amber", "job_id": "iv_eod", "lag_sessions": 1, "as_of": "2026-11-03"},
    {"id": "index_ohlc_daily", "state": "amber", "job_id": "iv_eod", "lag_sessions": 1, "as_of": "2026-11-03"},
    {"id": "iv_summary_daily", "state": "red", "job_id": "iv_eod", "lag_sessions": 3, "as_of": "2026-10-30"},
]


def test_plan_sweep_refetches_the_evening_and_iv_input_files_for_the_missed_sessions():
    plan = mc.plan_sweep(EVENING_ROWS, "2026-11-04")
    assert [p["label"] for p in plan] == ["evening files", "iv_eod"], "one files step, then the computation that reads them"
    files = plan[0]
    assert files["path"] == mc.NSE_FILES_PATH
    assert files["body"] == {"job": "nse_files", "datasets": ["nse_participant_vol", "nse_fii_stats", "nse_fo_volt", "nse_contract_delta",
                                                              "index_ohlc_daily"],
                             "from": "2026-10-31", "to": "2026-11-04", "revalidate": False}, "from = day after the oldest as-of"
    assert plan[1]["body"] == {"job": "iv_eod", "backfill_from": "2026-10-31", "backfill_to": "2026-11-04"}
    # negative control (the bug): the evening rows no longer fall to the legacy positions ingest, which never fetches them
    assert "/jobs/ingest-nse-positions" not in [p["path"] for p in plan]
    # one session missing → just the last session
    one = mc.plan_sweep([EVENING_ROWS[0]], "2026-11-04")
    assert one[0]["body"]["from"] == "2026-11-04" and one[0]["body"]["to"] == "2026-11-04" and one[0]["body"]["datasets"] == ["nse_participant_vol"]
    # negative controls: fresh (or not-due) rows, gap rows and unrecoverable rows add nothing
    assert mc.plan_sweep([{**EVENING_ROWS[0], "state": "fresh"}], "2026-11-04") == []
    assert mc.plan_sweep([{**EVENING_ROWS[1], "state": "gap"}], "2026-11-04") == []
    assert mc.plan_sweep([{**EVENING_ROWS[1], "unrecoverable": True}], "2026-11-04") == []
    # a long hole is capped at a week of files inside the morning window (the next sweep resumes from the new as-of; the
    # start-up catch-up, outside the windows, takes up to a month)
    long = mc.plan_sweep([{**EVENING_ROWS[1], "lag_sessions": 60, "as_of": "2026-08-01"}], "2026-11-04")
    assert long[0]["body"]["from"] == "2026-10-28" and mc.SWEEP_FILES_MAX_SPAN_DAYS < mc.NSE_FILES_MAX_SPAN_DAYS
    # dedupe + cap: the files step counts once however many file rows there are
    many = EVENING_ROWS + SWEEP_ROWS
    plan = mc.plan_sweep(many, "2026-11-04")
    assert len(plan) <= mc.SWEEP_MAX_JOBS and [p["path"] for p in plan].count(mc.NSE_FILES_PATH) == 1


def test_the_0835_sweep_posts_the_files_span_before_iv_eod(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 11, 5, 8, 35))
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health(EVENING_ROWS)
    svc.results[mc.NSE_FILES_PATH] = {"status": "ok", "files": {"nse_fii_stats": [{"status": "downloaded"}] * 3}}
    svc.results[mc.IV_EOD_PATH] = {"status": "ok", "days": 3}
    asyncio.run(mc.morning_sweep())
    assert svc.post_paths() == [mc.NSE_FILES_PATH, mc.IV_EOD_PATH]
    [(q, body)] = svc.posts(mc.NSE_FILES_PATH)
    assert q == "" and body["from"] == "2026-10-31" and body["to"] == "2026-11-04" and "nse_fo_volt" in body["datasets"]
    assert "Sweep: evening files ok; iv_eod ok" in ctl["alerts"].sent[-1][2]


def test_nse_files_span_for_the_startup_catchup():
    assert mc.nse_files_span("2026-11-02T23:00:00+05:30", at(2026, 11, 5, 10, 0)) == ("2026-11-02", "2026-11-04"), "before 20:30: yesterday"
    assert mc.nse_files_span("2026-11-02", at(2026, 11, 5, 21, 0)) == ("2026-11-02", "2026-11-05"), "after 20:30: today's files are out"
    assert mc.nse_files_span("2026-11-02", at(2026, 11, 7, 10, 0)) == ("2026-11-02", "2026-11-06"), "Saturday: Friday"
    assert mc.nse_files_span("2026-11-02", at(2026, 11, 9, 10, 0)) == ("2026-11-02", "2026-11-06"), "Monday morning: Friday"
    assert mc.nse_files_span("2026-08-01", at(2026, 11, 5, 10, 0)) == ("2026-10-04", "2026-11-04"), "capped at a month"
    # negative controls: an empty span (down and up again before the evening's files) and an unparsable heartbeat
    assert mc.nse_files_span("2026-11-05T12:00:00+05:30", at(2026, 11, 5, 15, 0)) is None
    assert mc.nse_files_span("garbage", at(2026, 11, 5, 15, 0)) is None


def test_the_2245_pass_skips_the_session_files_on_a_holiday_but_keeps_positions_fii_dii_and_results(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 11, 20, 22, 45))                    # Fri 20 Nov 2026: Guru Nanak Jayanti
    monkeypatch.setattr(mc, "_HOLIDAYS", {"at": 10**12, "days": {"2026-11-20": "Guru Nanak Jayanti"}})
    svc.routes[("POST", "/db/fii-dii-cash/refresh")] = {"ok": True}
    svc.results["/jobs/ingest-results"] = {"symbols": 0, "rows": 0}
    closed_calls: list[str] = []

    async def closed(job: str) -> bool:
        closed_calls.append(job)
        return True

    monkeypatch.setattr(mc, "_closed_today", closed)
    asyncio.run(mc.nse_evening_pass())
    assert mc.NSE_FILES_PATH not in svc.post_paths() and mc.IV_EOD_PATH not in svc.post_paths()
    assert svc.post_paths() == ["/jobs/ingest-nse-positions", "/db/fii-dii-cash/refresh", "/jobs/ingest-results"]
    assert any("revisions: market closed today" in ln for ln in log_lines()) and closed_calls == ["nse_evening_pass"]
    # negative control: a session day posts the files with from = to = the session (never B1's date.today() default)
    svc.calls.clear()

    async def open_(job: str) -> bool:
        return False

    monkeypatch.setattr(mc, "_closed_today", open_)
    mc._IV_EOD_STATE.update(date="2026-11-20", status="ok")
    asyncio.run(mc.nse_evening_pass())
    [(_, body)] = svc.posts(mc.NSE_FILES_PATH)
    assert body["from"] == body["to"] == "2026-11-20" and body["revalidate"] is True


def test_a_missed_sweep_is_not_replayed_into_the_evening_and_its_one_off_leaves_the_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "GOLD_TODAY_SLOTS", {})
    _history_file(tmp_path, {"morning_sweep": "2026-11-03T08:36:00+05:30"})
    assert "morning_sweep" in mc.terminal_missed_jobs(at(2026, 11, 4, 10, 0), mc.read_job_history(tmp_path))
    assert "morning_sweep" in mc.terminal_missed_jobs(at(2026, 11, 4, 18, 29), mc.read_job_history(tmp_path))
    # from 18:30 the 20:30 / 22:45 passes own last night's files: no sweep (nor DATA digest) on a deploy evening
    assert "morning_sweep" not in mc.terminal_missed_jobs(at(2026, 11, 4, 18, 30), mc.read_job_history(tmp_path))
    assert "morning_sweep" not in mc.terminal_missed_jobs(at(2026, 11, 4, 21, 31), mc.read_job_history(tmp_path))
    assert set(mc.TERMINAL_ONEOFF_DEFER) == {"morning_sweep", "nse_positions_catchup"}
    assert mc.freeze_slot(at(2026, 11, 4, 8, 40)) == at(2026, 11, 4, 9, 21)
    assert mc.freeze_slot(at(2026, 11, 4, 20, 31)) == at(2026, 11, 4, 21, 16)
    assert mc.freeze_slot(at(2026, 11, 4, 10, 0)) == at(2026, 11, 4, 10, 0), "outside the windows: unchanged"


def test_lifespan_defers_the_sweep_and_positions_one_offs_out_of_the_windows(monkeypatch, tmp_path):
    class Paused(mc.AsyncIOScheduler):
        def start(self, paused: bool = False) -> None:
            super().start(paused=True)

    monkeypatch.setattr(mc, "_alerts", _Alerts())
    monkeypatch.setattr(mc, "HEARTBEAT_FILE", tmp_path / "hb.json")
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "history.json"))
    monkeypatch.setattr(mc, "_log", mc.LogRingBuffer())
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: ["morning_sweep", "nse_positions_catchup", "results_capture_daily"])
    monkeypatch.setattr(mc, "scheduler", None)
    monkeypatch.setattr(mc, "AsyncIOScheduler", Paused)

    async def no_bot() -> None:
        return None

    monkeypatch.setattr(mc, "telegram_poller", no_bot)

    async def scenario():
        async with mc.lifespan(mc.app):
            return {j.id: j for j in mc.scheduler.get_jobs()}

    fake_clock(monkeypatch, at(2030, 3, 4, 20, 40))                    # a crash restart inside the EOD window, no heartbeat gap
    jobs = asyncio.run(scenario())
    when = {k: v.trigger.run_date.astimezone(IST) for k, v in jobs.items() if k.endswith("_catchup") and hasattr(v.trigger, "run_date")}
    assert when["morning_sweep_catchup"].strftime("%H:%M") == "21:16" and when["nse_positions_catchup_catchup"].strftime("%H:%M") == "21:16"
    # negative control: a job not in TERMINAL_ONEOFF_DEFER keeps its one-off a minute or two after start
    assert when["results_capture_daily_catchup"].strftime("%H:%M") in ("20:41", "20:42")


def test_the_freshness_check_says_once_a_day_that_it_is_blind(ctl, svc, monkeypatch):
    monkeypatch.setattr(mc, "_FRESHNESS_BLIND_WARNED", {})
    fake_clock(monkeypatch, at(2026, 11, 5, 8, 31))
    svc.routes[("GET", mc.DATA_HEALTH_API)] = {"status": "ok", "service": "data-service", "db_read_only": False}   # the pre-v2 relay
    assert asyncio.run(mc._check_dataset_freshness("pre_market_sync")) == []
    assert asyncio.run(mc._check_dataset_freshness("eod_data_pipeline")) == []
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("warning", "Freshness check has no data-health view") and "no stale-feed alert" in body
    assert not DIRECTION_WORDS.search(body)
    fake_clock(monkeypatch, at(2026, 11, 6, 8, 31))
    asyncio.run(mc._check_dataset_freshness("pre_market_sync"))
    assert len(ctl["alerts"].sent) == 2, "the next day says it again"
    # negative control: with the view (nothing red) nothing is sent
    ctl["alerts"].sent.clear()
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health([{"id": "nse_fo_daily", "state": "fresh"}])
    assert asyncio.run(mc._check_dataset_freshness("pre_market_sync")) == [] and ctl["alerts"].sent == []


def test_the_digest_counts_unknown_rows_when_the_view_has_them():
    h = _health([{"id": "a", "state": "fresh"}, {"id": "market_monitor", "state": "unknown", "note": "job x not in the controller's schedule"}])
    h["summary"]["unknown"] = 1
    assert mc.health_digest(h).startswith("1 green · 0 amber · 0 red · 0 gap · 1 unknown of 2 datasets")
    assert " unknown" not in mc.health_digest(_health([{"id": "a", "state": "fresh"}])).splitlines()[0]


# ── the hourly data-health check: one line per transition (PLAN 1.4) ────────────────────────────────────────


def test_health_transitions_report_class_changes_only():
    rows = [
        {"id": "a", "state": "amber", "note": "n"},
        {"id": "b", "state": "fresh"},
        {"id": "c", "state": "red"},
        {"id": "d", "state": "gap"},
        {"id": "e", "state": "live"},
        {"id": "f", "state": "weird"},
    ]
    first = mc.health_transitions({}, rows)
    assert [(t["id"], t["from"], t["to"]) for t in first] == [("c", "new", "red"), ("d", "new", "gap")], (
        "first sight: red / gap only"
    )
    prev = {"a": "fresh", "b": "amber", "c": "red", "d": "gap", "e": "fresh"}
    moved = mc.health_transitions(prev, rows)
    assert [(t["id"], t["from"], t["to"], t["worse"]) for t in moved] == [
        ("a", "fresh", "amber", "1"),
        ("b", "amber", "fresh", ""),
    ]
    assert mc.health_transitions({"e": "live"}, rows[4:5]) == [], "live ⇄ fresh is the same class"


def test_hourly_check_sends_one_line_per_transition_and_nothing_when_nothing_moved(ctl, svc, monkeypatch, tmp_path):
    fake_clock(monkeypatch, at(2026, 11, 5, 10, 10))
    rows = [{"id": "nse_mtf", "state": "fresh", "note": "stored 04 Nov"}, {"id": "iv_summary_daily", "state": "fresh"}]
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health(rows)
    asyncio.run(mc.data_health_check())
    assert ctl["alerts"].sent == [] and mc.read_health_state(mc.DATA_HEALTH_STATE_FILE) == {
        "nse_mtf": "fresh",
        "iv_summary_daily": "fresh",
    }
    rows[0]["state"], rows[0]["note"] = "amber", "stored 03 Nov · expected by 23:00 · 1 session behind"
    rows[1]["state"] = "red"
    asyncio.run(mc.data_health_check())
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("warning", "DATA: 2 datasets changed state")
    assert body.splitlines()[:2] == [
        "nse_mtf: fresh → amber (stored 03 Nov · expected by 23:00 · 1 session behind)",
        "iv_summary_daily: fresh → red",
    ]
    ctl["alerts"].sent.clear()
    asyncio.run(mc.data_health_check())
    assert ctl["alerts"].sent == [], "same state an hour later: no line (the state file persists across restarts)"
    rows[0]["state"], rows[1]["state"] = "fresh", "fresh"
    asyncio.run(mc.data_health_check())
    assert ctl["alerts"].sent[-1][0] == "info" and "nse_mtf: amber → fresh" in ctl["alerts"].sent[-1][2]
    assert mc._latency.stats()["data_health_check"]["last_status"] == "done"
    assert not any("Finished" in ln for ln in log_lines()), "quiet: 24 runs a day write no Finished line"
    # negative control: the view down → nothing sent, the state untouched
    ctl["alerts"].sent.clear()
    del svc.routes[("GET", mc.DATA_HEALTH_API)]
    asyncio.run(mc.data_health_check())
    assert ctl["alerts"].sent == [] and mc.read_health_state(mc.DATA_HEALTH_STATE_FILE)["nse_mtf"] == "fresh"
    assert mc.read_health_state(tmp_path / "nowhere.json") == {}
    (tmp_path / "bad.json").write_text("{garbage")
    assert mc.read_health_state(tmp_path / "bad.json") == {}


def test_dataset_max_age_days_is_retired_and_the_freshness_check_reads_the_view(ctl, svc, monkeypatch):
    assert not hasattr(mc, "DATASET_MAX_AGE_DAYS")
    assert "DATASET_MAX_AGE_DAYS = {" not in (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
    fake_clock(monkeypatch, at(2026, 11, 5, 8, 31))
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health(
        [
            {
                "id": "nse_fo_daily",
                "state": "red",
                "note": "stored 30 Oct · expected by 21:00 · 3 sessions behind",
                "dictionary_anchor": "NSE_DATA_DICTIONARY.md#fo",
            },
            {"id": "nse_mtf", "state": "amber", "note": "stored 03 Nov · 1 session behind"},
            {"id": "archive:internals", "state": "gap", "note": "explicit gap row"},
        ]
    )
    assert asyncio.run(mc._check_dataset_freshness("pre_market_sync")) == [
        "nse_fo_daily: stored 30 Oct · expected by 21:00 · 3 sessions behind"
    ]
    [(level, title, body)] = ctl["alerts"].sent
    assert (
        (level, title) == ("critical", "NSE data feed stale") and "docs/NSE_DATA_DICTIONARY.md" in body and "expected-by" in body
    )
    assert "nse_mtf" not in body and "internals" not in body, "amber and gap rows are not 'stale'"


# ── iv_intraday (pilot) and iv_weekly ───────────────────────────────────────────────────────────────────────


def test_iv_intraday_skips_without_a_request_outside_the_window_on_a_holiday_and_without_a_session(ctl, svc, monkeypatch):
    svc.routes[("GET", "/provider/status")] = {"connected": False}
    svc.results[mc.IV_INTRADAY_PATH] = {"status": "ok", "calls": 8, "rows": 480}
    fake_clock(monkeypatch, at(2026, 11, 4, 9, 5))  # the cron's first tick, inside the morning window
    asyncio.run(mc.iv_intraday_tick())
    assert svc.calls == [], "outside 09:20–15:30: no request of any kind"
    fake_clock(monkeypatch, at(2026, 11, 4, 9, 20))
    monkeypatch.setattr(mc, "_HOLIDAYS", {"at": 10**12, "days": {"2026-11-04": "Test holiday"}})
    asyncio.run(mc.iv_intraday_tick())
    assert svc.calls == [], "NSE holiday: no request"
    monkeypatch.setattr(mc, "_HOLIDAYS", {"at": 10**12, "days": {}})
    asyncio.run(mc.iv_intraday_tick())
    assert svc.post_paths() == [], "no live Breeze session: the provider status is read, nothing is posted"
    assert sum("holds no live Breeze session" in ln for ln in log_lines()) == 1
    asyncio.run(mc.iv_intraday_tick())
    assert sum("holds no live Breeze session" in ln for ln in log_lines()) == 1, "said once an hour, not every 15 min"
    # a live session: one POST, quiet
    svc.routes[("GET", "/provider/status")] = {"connected": True}
    asyncio.run(mc.iv_intraday_tick())
    assert svc.posts(mc.IV_INTRADAY_PATH) == [("job=iv_intraday", {"job": "iv_intraday"})]
    assert any("first tick stored at 09:20: calls=8 rows=480" in ln for ln in log_lines())
    assert not any("Finished" in ln for ln in log_lines()) and ctl["alerts"].sent == []
    # data-service's own skip (the budget ledger refused): one WARNING an hour, never Telegram, still 'done'
    svc.results[mc.IV_INTRADAY_PATH] = {"status": "skipped", "reason": "budget ledger refused: day cap 700 reached", "calls": 0}
    asyncio.run(mc.iv_intraday_tick())
    asyncio.run(mc.iv_intraday_tick())
    assert sum("skipped by data-service: budget ledger refused" in ln for ln in log_lines()) == 1
    assert ctl["alerts"].sent == [] and mc._latency.stats()["iv_intraday"]["last_status"] == "done"
    # negative control: TERMINAL_JOBS_ENABLED=0 → nothing at all
    monkeypatch.setattr(mc, "TERMINAL_JOBS_ENABLED", False)
    svc.calls.clear()
    asyncio.run(mc.iv_intraday_tick())
    assert svc.calls == []


def test_iv_weekly_posts_the_recompute_and_a_404_pauses_the_terminal_jobs_for_an_hour(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 11, 7, 3, 0))
    svc.results[mc.IV_EOD_PATH] = {"status": "ok", "ranks_recomputed": 224, "catalog_rows": 61}
    asyncio.run(mc.iv_weekly())
    assert svc.posts(mc.IV_EOD_PATH) == [("job=iv_weekly", {"job": "iv_weekly"})]
    assert any("ranks recomputed for 224 symbol-days; catalog rows 61" in ln for ln in log_lines())
    svc.calls.clear()
    svc.statuses[mc.IV_EOD_PATH] = 404
    asyncio.run(mc.iv_weekly())
    assert mc._latency.stats()["iv_weekly"]["last_status"] == "error" and mc._TERMINAL_PAUSED_UNTIL > 0
    svc.calls.clear()
    asyncio.run(mc.iv_eod_step("x", "2026-11-06"))
    assert svc.calls == [] and mc._IV_EOD_STATE["status"] == "unavailable", "paused: no request until the hour is up"
    assert sum("Terminal v2 package not deployed" in ln for ln in log_lines()) == 1 and ctl["alerts"].sent == []


# ── missed_jobs() and the extended start-up catch-up (Wave 0 0.9) ───────────────────────────────────────────


def _history_file(root: Path, jobs: dict[str, str]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / ".scheduler_history.json").write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": {k: {"last_run_ts": v, "last_status": "done", "last_ms": 1.0, "runs": 1} for k, v in jobs.items()},
            }
        )
    )


def test_missed_jobs_lists_the_terminal_jobs_whose_slot_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "GOLD_TODAY_SLOTS", {})
    (tmp_path / "data" / "nse_archive" / "preopen").mkdir(parents=True)
    (tmp_path / "data" / "nse_archive" / "preopen" / "2026-11-04_FO.json").write_text("{}")
    (tmp_path / "reports" / "daily_wrap").mkdir(parents=True)
    (tmp_path / "reports" / "daily_wrap" / "2026-11-04.md").write_text("#")
    wed = at(2026, 11, 4, 23, 0)
    assert mc.missed_jobs(wed, tmp_path) == [], "no history: no evidence"
    _history_file(
        tmp_path,
        {
            "morning_sweep": "2026-11-04T08:36:00+05:30",
            "index_drivers_daily": "2026-11-03T19:26:00+05:30",
            "nse_positions_catchup": "2026-11-04T20:31:00+05:30",
            "results_capture_daily": "2026-11-03T20:46:00+05:30",
            "nse_evening_pass": "2026-11-03T22:46:00+05:30",
        },
    )
    assert mc.missed_jobs(wed, tmp_path) == ["index_drivers_daily", "results_capture_daily", "nse_evening_pass"]
    assert mc.missed_jobs(at(2026, 11, 4, 20, 0), tmp_path) == ["index_drivers_daily"], "20:30 / 20:45 / 22:45 not yet"
    assert mc.missed_jobs(at(2026, 11, 4, 8, 0), tmp_path) == [], "08:35 not yet"
    no_gold = lambda when: [j for j in mc.missed_jobs(when, tmp_path) if not j.startswith("gold_")]  # noqa: E731
    assert no_gold(at(2026, 11, 7, 12, 0)) == ["iv_weekly"], "Saturday noon: 03:00 passed, never ran"
    assert no_gold(at(2026, 11, 8, 12, 0)) == ["iv_weekly"], "Sunday: still this weekend's"
    _history_file(tmp_path, {"iv_weekly": "2026-11-07T03:01:00+05:30"})
    assert "iv_weekly" not in mc.missed_jobs(at(2026, 11, 8, 12, 0), tmp_path)
    assert mc.terminal_missed_jobs(wed, None) == []
    assert no_gold(at(2026, 11, 7, 2, 0)) == [], "Saturday 02:00: nothing due on a weekend before 03:00"


def test_startup_catchup_extends_to_results_valuation_drivers_iv_gap_rows_desk_and_shadow(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 11, 4, 22, 0))  # Wednesday night after the windows → "full"
    svc.results["/jobs/daily-pipeline"] = {"bhavcopy": {"days_loaded": 3}, "build": {"feature_date_range": ["x", "2026-11-04"]}}
    svc.results["/jobs/ingest-nse-positions"] = {"tables": {"nse_fo_daily": {"last": "2026-11-04"}}}
    svc.results["/jobs/ingest-results"] = {"symbols": 40, "rows": 31}
    svc.results[mc.INDEX_DRIVERS_PATH] = {"status": "ok", "days": 3}
    svc.results[mc.IV_EOD_PATH] = {"status": "ok", "days": 3}
    svc.results[mc.DATA_HEALTH_JOB_PATH] = {
        "gap_scan": {
            "gaps": {"archive:preopen": ["2026-11-02", "2026-11-03"], "archive:internals": ["2026-11-02"], "nse_fii_dii_cash": []}
        }
    }
    ran: list[Any] = []

    async def desk() -> None:
        async with mc._track("desk_daily"):          # a real tracked run: the report quotes the status it recorded
            ran.append("desk_daily")

    async def shadow() -> None:
        async with mc._track("alpha_shadow_daily"):
            ran.append("alpha_shadow_daily")

    async def valuation(recent: int = 10) -> None:
        ran.append(("index_valuation_daily", recent))

    monkeypatch.setattr(mc, "desk_daily", desk)
    monkeypatch.setattr(mc, "alpha_shadow_daily", shadow)
    monkeypatch.setattr(mc, "index_valuation_daily", valuation)
    missed = {
        "eod_data_pipeline": 3,
        "results_capture_daily": 3,
        "index_valuation_daily": 3,
        "desk_daily": 3,
        "alpha_shadow_daily": 3,
        "nse_positions_catchup": 3,
        "move_alerts": 200,
    }
    asyncio.run(mc._startup_catchup_run("2026-10-31T11:29:00+05:30", "2026-11-04T21:29:00+05:30", missed, "full", None))
    assert svc.post_paths() == [
        "/jobs/daily-pipeline",
        "/jobs/ingest-nse-positions",
        "/jobs/ingest-results",
        mc.NSE_FILES_PATH,
        mc.INDEX_DRIVERS_PATH,
        mc.IV_EOD_PATH,
        mc.DATA_HEALTH_JOB_PATH,
    ]
    # check:B2-CTRL major: the outage's evening + IV input files are fetched BEFORE the IV / drivers backfills read them
    assert svc.posts(mc.NSE_FILES_PATH) == [("", {"job": "nse_files", "datasets": ["nse_bhavcopy", *mc.NSE_IV_FILES, *mc.NSE_EVENING_FILES],
                                                  "from": "2026-10-31", "to": "2026-11-04", "revalidate": True})]
    assert svc.posts("/jobs/daily-pipeline") == [("", {"mode": "incremental", "skip_steps": ["nse_positions"]})]
    assert svc.posts("/jobs/ingest-results") == [("", {"recent_events_days": 7, "max_age_days": 0})], "window = days down (4) + 3"
    assert svc.posts(mc.INDEX_DRIVERS_PATH) == [
        ("job=index_drivers_daily", {"job": "index_drivers_daily", "backfill_from": "2026-10-31"})
    ]
    assert svc.posts(mc.IV_EOD_PATH) == [("job=iv_eod", {"job": "iv_eod", "backfill_from": "2026-10-31"})]
    [(_, gap_body)] = svc.posts(mc.DATA_HEALTH_JOB_PATH)
    assert gap_body == {"job": "data_health_refresh", "since": "2026-10-31", "reason": "stack down from 2026-10-31 (no capture)"}
    assert ran == [("index_valuation_daily", 10), "desk_daily", "alpha_shadow_daily"]
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("warning", "Stack was down — catching up")
    assert "results release times (7-day window): symbols=40 rows=31" in body
    assert "gap rows: archive:preopen 2026-11-02, 2026-11-03; archive:internals 2026-11-02" in body
    assert (
        "IV store: ok from 2026-10-31 (3 day(s))" in body
        and "Desk mark: re-run (done; its 19:30 run was missed)" in body
        and "S1 shadow: re-run (done; its 19:50 run was missed)" in body
    )
    # "nse" mode (market hours): the same extension after the NSE-file steps, no positions re-run of its own (the
    # 'nse' step list already carries it); nothing missed → no results / desk / shadow / valuation re-run
    svc.calls.clear()
    ran.clear()
    ctl["alerts"].sent.clear()
    svc.routes[("GET", "/db/market-monitor")] = {"as_of": "2026-11-04"}
    fake_clock(monkeypatch, at(2026, 11, 5, 10, 0))
    asyncio.run(
        mc._startup_catchup_run("2026-11-04T23:00:00+05:30", "2026-11-05T09:53:00+05:30", {"move_alerts": 3}, "nse", None)
    )
    assert svc.post_paths() == [
        "/jobs/ingest-bhavcopy",
        "/jobs/ingest-nse-positions",
        "/jobs/ingest-nse-events",
        mc.NSE_FILES_PATH,
        mc.INDEX_DRIVERS_PATH,
        mc.IV_EOD_PATH,
        mc.DATA_HEALTH_JOB_PATH,
    ]
    # 10:00: tonight's files are not out → the span ends at the last weekday before today
    assert [b["from"] + "→" + b["to"] for _, b in svc.posts(mc.NSE_FILES_PATH)] == ["2026-11-04→2026-11-04"]
    assert ran == [], "nothing missed: no desk / shadow / valuation re-run"
    body = ctl["alerts"].sent[0][2]
    assert "gap rows: archive:preopen 2026-11-02, 2026-11-03" in body and "NSE files 2026-11-04 → 2026-11-04" in body
    # negative control: "skip" mode (inside the EOD window) runs none of it — tonight's scheduled jobs do the work
    svc.calls.clear()
    asyncio.run(mc._startup_catchup_run("2026-11-04T23:00:00+05:30", "2026-11-05T19:00:00+05:30", missed, "skip", None))
    assert svc.calls == [] and ran == []
    # negative control: TERMINAL_JOBS_ENABLED=0 keeps the results / valuation / desk / shadow part, drops the B1 jobs
    monkeypatch.setattr(mc, "TERMINAL_JOBS_ENABLED", False)
    svc.calls.clear()
    asyncio.run(mc._startup_catchup_run("2026-10-31T11:29:00+05:30", "2026-11-04T21:29:00+05:30", missed, "full", None))
    assert mc.IV_EOD_PATH not in svc.post_paths() and mc.DATA_HEALTH_JOB_PATH not in svc.post_paths() and "desk_daily" in ran
    assert mc.NSE_FILES_PATH not in svc.post_paths()


def test_gold_key_jobs_now_include_the_asia_morning_india_and_health_ones():
    """0.9: the downtime catch-up re-runs them with backfill_from (B1 writes the back-dated rows backfilled=true)."""
    assert {"gold_asia_close", "gold_morning", "gold_india_midday", "gold_india_pm", "gold_health_snapshot"} <= set(
        mc.GOLD_KEY_JOBS
    )
    assert {"results_capture_daily", "index_valuation_daily", "index_drivers_daily", "nse_evening_pass"} <= mc._KEY_JOBS


def test_lifespan_leaves_the_terminal_ids_the_data_catchup_owns_to_it_but_not_in_skip_mode(monkeypatch, tmp_path):
    class Paused(mc.AsyncIOScheduler):
        def start(self, paused: bool = False) -> None:
            super().start(paused=True)

    monkeypatch.setattr(mc, "_alerts", _Alerts())
    monkeypatch.setattr(mc, "HEARTBEAT_FILE", tmp_path / "hb.json")
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "history.json"))
    monkeypatch.setattr(mc, "_log", mc.LogRingBuffer())
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: ["nse_positions_catchup", "index_drivers_daily", "nse_evening_pass"])
    monkeypatch.setattr(mc, "scheduler", None)
    monkeypatch.setattr(mc, "AsyncIOScheduler", Paused)

    async def no_bot() -> None:
        return None

    monkeypatch.setattr(mc, "telegram_poller", no_bot)

    async def scenario():
        async with mc.lifespan(mc.app):
            return {j.id: j for j in mc.scheduler.get_jobs()}

    # a 22:00 start after a day down: "full" catch-up owns the 20:30 pass and the drivers; the 22:45 pass (not in its
    # list) keeps its one-off
    fake_clock(monkeypatch, at(2030, 3, 4, 23, 50))
    mc.write_heartbeat(tmp_path / "hb.json", at(2030, 3, 3, 23, 0))
    jobs = asyncio.run(scenario())
    assert jobs["startup_catchup"].args[3] == "full"
    assert "nse_positions_catchup_catchup" not in jobs and "index_drivers_daily_catchup" not in jobs
    assert "nse_evening_pass_catchup" in jobs
    # a 19:00 start (EOD window → "skip"): the one-offs are the run
    fake_clock(monkeypatch, at(2030, 3, 4, 19, 0))
    mc.write_heartbeat(tmp_path / "hb.json", at(2030, 3, 3, 23, 0))
    jobs = asyncio.run(scenario())
    assert jobs["startup_catchup"].args[3] == "skip"
    assert {"nse_positions_catchup_catchup", "index_drivers_daily_catchup", "nse_evening_pass_catchup"} <= set(jobs)


# ── the file lists are B1's (fo_iv.jobs.EOD_FILES / nse_positions.TERMINAL_DATASETS) ────────────────────────


def test_the_controllers_file_lists_match_b1s_data_service():
    jobs_src = (ROOT / "services" / "data-service" / "fo_iv" / "jobs.py").read_text(encoding="utf-8")
    m = re.search(r"EOD_FILES: tuple\[str, \.\.\.\] = \((.*?)\)", jobs_src, re.S)
    assert m and tuple(re.findall(r'"([a-z_]+)"', m.group(1))) == mc.NSE_IV_FILES
    pos_src = (ROOT / "services" / "data-service" / "nse_positions.py").read_text(encoding="utf-8")
    block = pos_src[pos_src.index("TERMINAL_DATASETS: dict") : pos_src.index("TERMINAL_DATASET_NAMES")]
    names = set(re.findall(r'^\s+"([a-z_]+)": \{', block, re.M))
    assert set(mc.NSE_EVENING_FILES) <= names and set(mc.NSE_IV_FILES) <= names
    api_src = (ROOT / "services" / "data-service" / "fo_iv" / "api.py").read_text(encoding="utf-8")
    assert '@router.post("/jobs/iv-eod")' in api_src and '@router.post("/jobs/iv-intraday")' in api_src
    assert '@router.post("/jobs/ingest-nse-files")' in api_src
    assert '@router.post("/jobs/index-drivers")' in (ROOT / "services" / "data-service" / "index_drivers" / "api.py").read_text(
        encoding="utf-8"
    )
    assert '@router.post("/jobs/data-health")' in (ROOT / "services" / "data-service" / "data_health" / "api.py").read_text(
        encoding="utf-8"
    )
    assert '@router.get("/health")' in (ROOT / "services" / "ui-api" / "routers" / "data_health.py").read_text(encoding="utf-8")


def test_no_terminal_telegram_wording_carries_a_direction_word():
    src = (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
    block = src[src.index("# Terminal v2 (reports/terminal_v2/PLAN.md Wave 0 0.5") : src.index("async def results_capture_daily")]
    for s in re.findall(r'"([^"\n]*)"', block):
        assert not DIRECTION_WORDS.search(s), s
    digest = mc.health_digest(_health(SWEEP_ROWS))
    assert not DIRECTION_WORDS.search(digest) and "N of" not in digest


# ── the watchdog's second heartbeat (PLAN 0.2) ───────────────────────────────────────────────────────────────

BASH = "/bin/bash"


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".logs").mkdir()
    (repo / ".pids").mkdir()
    for rel in ("start-local.sh", "scripts/stack_watchdog.sh"):
        shutil.copy2(ROOT / rel, repo / rel)
    return repo


def sh(repo: Path, script: str) -> subprocess.CompletedProcess:
    env = {
        "HOME": str(repo / "home"),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "en_US.UTF-8",
    }
    return subprocess.run([BASH, "-c", script], cwd=repo, env=env, capture_output=True, check=False, text=True, timeout=60)


def test_watchdog_second_heartbeat_pings_on_every_run_and_is_off_without_the_url(tree):
    wd = "source scripts/stack_watchdog.sh; "
    r = sh(tree, wd + "ping_watchdog_alive")
    assert r.returncode == 0, r.stderr
    assert not (tree / ".pids" / "watchdog" / "deadman_watchdog").exists(), "no URL: no request, no state"
    (tree / ".env").write_text("HEALTHCHECK_WATCHDOG_URL=http://127.0.0.1:9/hc/abc\n")
    r = sh(tree, wd + "ping_watchdog_alive")
    assert r.returncode == 0, r.stderr
    at_, res = (tree / ".pids" / "watchdog" / "deadman_watchdog").read_text().split()
    assert res == "error" and at_.isdigit(), "an unreachable URL is recorded as error (never the URL itself)"
    assert (
        "127.0.0.1" not in (tree / ".logs" / "watchdog.log").read_text() if (tree / ".logs" / "watchdog.log").exists() else True
    )
    # main() beats before the stack is looked at — even when the stack is down and nothing else runs
    r = sh(tree, wd + "is_up() { return 0; }; start_local_running() { return 1; }; rm -f .pids/watchdog/deadman_watchdog; main")
    assert r.returncode == 0, r.stderr
    assert (tree / ".pids" / "watchdog" / "deadman_watchdog").exists()
    src = (ROOT / "scripts" / "stack_watchdog.sh").read_text(encoding="utf-8")
    assert src.index("take_lock || exit 0") < src.index("ping_watchdog_alive                 ") < src.index("down=$(candidates)")
    (tree / ".env").write_text("")
    sh(tree, wd + "ping_watchdog_alive")
    assert not (tree / ".pids" / "watchdog" / "deadman_watchdog").exists(), "unset again: the stale state is removed"


def test_status_line_mentions_the_second_heartbeat_only_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mc,
        "_env_file_value",
        lambda k: {"HEALTHCHECK_PING_URL": "https://hc-ping.com/x", "HEALTHCHECK_WATCHDOG_URL": ""}.get(k, ""),
    )
    monkeypatch.setattr(mc, "_DEADMAN_STATE", tmp_path / "deadman")
    monkeypatch.setattr(mc, "_WATCHDOG_BEAT_STATE", tmp_path / "deadman_watchdog")
    (tmp_path / "deadman").write_text(f"{int(datetime.now(IST).timestamp())} ok")
    assert mc._deadman_line() == "🟢 dead-man ping ok"
    monkeypatch.setattr(mc, "_env_file_value", lambda k: "https://hc-ping.com/x")
    assert mc._deadman_line().endswith("watchdog heartbeat: configured, none recorded yet")
    (tmp_path / "deadman_watchdog").write_text(f"{int(datetime.now(IST).timestamp())} ok")
    assert mc._deadman_line() == "🟢 dead-man ping ok · watchdog heartbeat ok"
    (tmp_path / "deadman_watchdog").write_text(f"{int(datetime.now(IST).timestamp()) - 1200} ok")
    assert mc._deadman_line().endswith("watchdog heartbeat: last 20 min ago")
    assert "hc-ping" not in mc._deadman_line(), "never the URL"


@pytest.mark.parametrize(
    "trigger_kw,expected",
    [
        ({"day_of_week": "mon-fri", "hour": 22, "minute": 45}, "22:45"),
        ({"day_of_week": "sat", "hour": 3, "minute": 0}, "03:00"),
    ],
)
def test_the_new_slots_are_outside_both_freeze_windows(trigger_kw, expected):
    t = CronTrigger(timezone=IST, **trigger_kw).get_next_fire_time(None, at(2026, 11, 2, 0, 0))
    assert t.strftime("%H:%M") == expected and not mc.in_freeze_window(t)
