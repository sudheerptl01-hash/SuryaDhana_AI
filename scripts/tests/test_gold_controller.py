"""GOLD program, builder B2 (scripts/master_controller.py; reports/gold_program/PLAN.md §c.3, §b, §g; gate T5).

* the gold ingest jobs: every PLAN §c.3 id registered with its IST trigger(s), dormant (O-8) ones not; heavy jobs never
  fire inside a freeze window and a late run of one defers to the window's end; the light ones run inside it;
* MCX holiday gating of the pre-open desk jobs (shared/mcx_specs): no 08:45 snapshot on full and morning-closure days,
  the open captured at 17:10 on a morning-closure day;
* the 08:45 Telegram wording with the measured miss and the Saturday COT digest — both description, no direction;
* catch-up: _KEY_JOBS and missed_jobs() carry the gold ids; the downtime catch-up re-runs them with backfill_from;
* `?force=1` on POST /api/scheduler/icici-refresh passes --force (fake), the cross-site refusal still holds, a login
  that needs you (rc 2) is recorded as an error (_mark_failed), and the OTP hint no longer misfires on "TOTP";
* the Telegram /status gold freshness line and the freshness alert's rows (a malformed row never aborts the check);
* wave 1b: the downtime catch-up is tracked, asks for every day-conditional group and waits for a held lock; the
  missed-today one-offs leave the gold ids the downtime catch-up owns; relayed COT / desk strings pass the direction
  guard; every controller group name resolves in B1's gold.jobs and B1's result shape (groups{status, inserted},
  rows_total, tables) is read as the controller reads it.

PLAN §h T5 also lists "conditional-GET master loader (304 path)": that loader is B1's (data-service
gold/ingest_india.py, the `mcx_master` group — If-Modified-Since from the stored Last-Modified, a 304 →
{"status": "not_modified"}), covered by tests/gold/test_jobs_api.py. The controller's side of that path is here:
a `not_modified` group is an outcome, not a failure (no ERROR, no Telegram, SYS says done).

Nothing live: data-service, ui-api and the refresh script are fakes (httpx gets a MockTransport); the clock is faked
where the day matters; history/heartbeat/backup paths are temp paths or never armed; no file under data/ is touched.
"""
# ruff: noqa: DTZ001 - fake-clock datetimes are localized with pytz (IST.localize), as in the controller
from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import db_backup
import master_controller as mc

IST = mc.IST
PLAN_C3_JOBS = ["gold_overnight", "gold_intraday_bars", "gold_morning", "gold_mcx_master", "gold_health_snapshot",
                "gold_brief_ingest", "gold_calendar_refresh", "gold_india_midday", "gold_cme_daily", "gold_asia_close",
                "gold_india_pm", "gold_fred_daily", "gold_cot_weekly", "gold_weekly", "gold_cme_calendar", "gold_mcx_close"]
# PLAN §f / O-14: no gold alert implies a direction. "does not forecast" and "no forecasting power" are the
# disclaimers themselves (negated, or the -ing form), so they are not direction words.
DIRECTION_WORDS = re.compile(r"\b(bullish|bearish|buy|sell|go long|go short|long gold|short gold|target|(?<!not )forecast[s]?)\b",
                             re.IGNORECASE)
# The 20 Oct 2026 week in PLAN §d's /api/gold/cot shape (numbers from G-COT/data/cot_gold_latest.json)
COT_20_OCT: dict[str, Any] = {
    "as_of": "2026-10-24T02:31:00+05:30",
    "latest": {"report_date": "2026-10-20", "release_at": "2026-10-23T19:30:13Z", "next_release_ist": "Sat 31 Oct 01:00 IST",
               "stale": False},
    "open_interest": {"total": 402279, "chg": 5934, "pct_rank": 61.0},
    "groups": [
        {"key": "mm", "label": "Managed money", "long": 120970, "short": 16764, "spread": 38634, "net": 104206,
         "chg_long": -3777, "chg_short": -894, "chg_net": -2883, "who_did": ["closed 3,777 longs", "covered 894 shorts"]},
        {"key": "sd", "label": "Swap dealers", "long": 17737, "short": 238536, "spread": 22079, "net": -220799,
         "chg_long": 3761, "chg_short": 466, "chg_net": 3295, "who_did": ["added 3,761 longs", "added 466 shorts"]},
    ],
    "driver_label": "long liquidation",
    "crowd": {"cot_index_52": 26.3, "z156": -0.8, "label": "crowdedness, not a signal — no forecasting power 2006–2026 (G-STUDY)"},
    "badge": "context",
}


def at(y: int, mo: int, d: int, h: int, mi: int, s: int = 0) -> datetime:
    return IST.localize(datetime(y, mo, d, h, mi, s))


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
    """A fake data-service (:8001) and ui-api (:8010) behind httpx.MockTransport: records every request, answers from
    `routes` ({(method, path): body | status | callable(request)}); the ingest job polls to 'done' with `result`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, Any]] = []     # (method, path, query, json body)
        self.routes: dict[tuple[str, str], Any] = {}
        self.result: dict[str, Any] = {"groups": {"cot": {"status": "ok", "new_rows": 8}}, "tables": {"gold_cot": {"last": "2026-10-20"}}}
        self.ingest_status = 200
        self.job_status = "done"                              # what GET /jobs/j1 reports ('error' → `job_error` as the reason)
        self.job_error: str | None = None
        self.on_ingest: Callable[[httpx.Request], None] | None = None   # called on every accepted ingest POST

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = request.content
        self.calls.append((method, path, request.url.query.decode(), body))
        if path == mc.GOLD_INGEST_PATH and method == "POST":
            if self.ingest_status != 200:
                return httpx.Response(self.ingest_status, text="no such endpoint")
            if self.on_ingest is not None:
                self.on_ingest(request)
            return httpx.Response(200, json={"job_id": "j1"})
        if path == "/jobs/j1":
            if self.job_status == "error":
                return httpx.Response(200, json={"status": "error", "error": self.job_error})
            return httpx.Response(200, json={"status": "done", "result": self.result})
        if path == mc.GOLD_INVALIDATE_PATH:
            return httpx.Response(200, json={"ok": True})
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


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> Services:
    s = Services()
    real = httpx.AsyncClient
    monkeypatch.setattr(mc.httpx, "AsyncClient",
                        lambda *a, **k: real(transport=httpx.MockTransport(s.handle), timeout=k.get("timeout")))
    monkeypatch.setattr(mc, "DATA_SVC", "http://127.0.0.1:8001")
    monkeypatch.setattr(mc, "UI_API", "http://127.0.0.1:8010")
    monkeypatch.setattr(mc, "DATA_JOB_POLL_SECS", 0)
    return s


@pytest.fixture
def ctl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Controller state isolated: recorded alerts, fresh latency/history (never armed), a recording scheduler, gold
    pause/rate-limit state reset, every job enabled, no job locks held."""
    alerts = _Alerts()
    sched = _FakeScheduler()
    monkeypatch.setattr(mc, "_alerts", alerts)
    monkeypatch.setattr(mc, "_latency", mc.LatencyTracker())
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "never-armed.json"))
    monkeypatch.setattr(mc, "_log", mc.LogRingBuffer())
    monkeypatch.setattr(mc, "scheduler", sched)
    monkeypatch.setattr(mc, "_GOLD_PAUSED_UNTIL", 0.0)
    monkeypatch.setattr(mc, "_GOLD_LAST_WARNED", {})
    monkeypatch.setattr(mc, "_GOLD_ALERTED_DAY", {})
    monkeypatch.setattr(mc, "_HOLIDAY_LOGGED", set())
    monkeypatch.setattr(mc, "_job_locks", {})
    for flag in ("GOLD_JOBS_ENABLED", "DATA_JOBS_ENABLED", "GOLD_LOG_ENABLED"):
        monkeypatch.setattr(mc, flag, True)
    return {"alerts": alerts, "sched": sched}


def log_lines() -> list[str]:
    return [json.loads(ln)["msg"] for ln in mc._log.tail(500)]


# ── the schedule (PLAN §c.3) ───────────────────────────────────────────────────────────────────────────────────

def _fires(trigger: Any, start: datetime, n: int) -> list[str]:
    out, prev = [], None
    for _ in range(n):
        t = trigger.get_next_fire_time(prev, (prev or start) + timedelta(microseconds=1))
        out.append(t.astimezone(IST).strftime("%a %d %H:%M"))
        prev = t
    return out


def test_every_plan_c3_job_is_registered_with_its_ist_times_and_dormant_ones_are_not():
    sched = _FakeScheduler()
    assert mc.register_gold_jobs(sched) == PLAN_C3_JOBS == list(mc.GOLD_JOBS)
    assert set(mc.GOLD_DORMANT_JOBS) == {"gold_mcx_bhavcopy", "gold_mcx_category", "gold_breeze_daily"}
    assert not set(mc.GOLD_DORMANT_JOBS) & set(mc.GOLD_JOBS)
    by_id = {kw["id"]: (name, kw) for name, kw in sched.added}
    for job_id, spec in mc.GOLD_JOBS.items():
        name, kw = by_id[job_id]
        assert kw["max_instances"] == 1 and kw["coalesce"] is True and kw["misfire_grace_time"] == spec.misfire_grace_s
        assert (name, kw["args"]) == (("gold_cot_weekly", []) if job_id == "gold_cot_weekly" else ("gold_job", [job_id]))
    ref = at(2026, 10, 23, 22, 0)                                            # a Friday evening
    trig = {k: v[1]["trigger"] for k, v in by_id.items()}
    assert _fires(trig["gold_cot_weekly"], ref, 8) == ["Sat 24 02:30", "Sat 24 03:30", "Sat 24 04:30", "Sat 24 05:30",
                                                       "Sat 24 06:30", "Mon 26 06:30", "Tue 27 06:30", "Sat 31 02:30"]
    assert _fires(trig["gold_overnight"], ref, 3) == ["Sat 24 03:10", "Mon 26 03:10", "Tue 27 03:10"]   # no Sunday
    assert _fires(trig["gold_mcx_master"], ref, 3) == ["Mon 26 07:35", "Mon 26 08:35", "Tue 27 07:35"]
    assert _fires(trig["gold_cme_daily"], ref, 3) == ["Sat 24 15:45", "Sat 24 17:15", "Mon 26 15:45"]
    assert _fires(trig["gold_weekly"], ref, 3) == ["Sat 24 10:30", "Mon 26 12:00", "Fri 30 18:00"]
    assert _fires(trig["gold_cme_calendar"], ref, 1) == ["Sun 25 04:00"]
    assert _fires(trig["gold_fred_daily"], ref, 2) == ["Sat 24 21:30", "Sun 25 21:30"]
    assert _fires(trig["gold_morning"], ref, 2) == ["Sat 24 06:40", "Mon 26 06:40"]
    assert _fires(trig["gold_india_midday"], ref, 1) == ["Mon 26 13:45"]
    assert _fires(trig["gold_asia_close"], ref, 1) == ["Mon 26 16:10"]
    assert _fires(trig["gold_india_pm"], ref, 1) == ["Mon 26 18:10"]
    assert _fires(trig["gold_health_snapshot"], ref, 1) == ["Mon 26 08:40"]
    assert _fires(trig["gold_brief_ingest"], ref, 2) == ["Sat 24 09:05", "Sun 25 09:05"]
    assert _fires(trig["gold_calendar_refresh"], ref, 2) == ["Fri 23 23:00", "Sat 24 09:00"]
    assert _fires(trig["gold_intraday_bars"], ref, 2) == ["Fri 23 22:05", "Fri 23 22:10"]
    assert _fires(trig["gold_mcx_close"], ref, 3) == ["Fri 23 23:58", "Sat 24 00:15", "Mon 26 23:58"]


def test_no_heavy_gold_job_is_scheduled_inside_a_freeze_window():
    sched = _FakeScheduler()
    mc.register_gold_jobs(sched)
    start = at(2026, 10, 23, 0, 0)
    for name, kw in sched.added:
        spec = mc.GOLD_JOBS[kw["id"]]
        if spec.light:
            continue
        t, prev = None, None
        for _ in range(80):                                                  # ≥ 2 weeks for every cadence
            t = kw["trigger"].get_next_fire_time(prev, (prev or start) + timedelta(microseconds=1))
            assert not mc.in_freeze_window(t.astimezone(IST)), f"{kw['id']} fires at {t.astimezone(IST)}"
            prev = t
    # and the few PLAN §c.3 places inside a window are exactly the light ones
    assert {j for j, s in mc.GOLD_JOBS.items() if s.light} == {"gold_intraday_bars", "gold_mcx_master", "gold_health_snapshot",
                                                                "gold_brief_ingest", "gold_calendar_refresh"}


def test_key_jobs_max_age_rows_and_groups_per_day():
    assert {"gold_overnight", "gold_cot_weekly", "gold_mcx_master"} <= mc._KEY_JOBS
    # Terminal v2 0.9 extended the downtime re-run (backfill_from) to the Asia-close, morning, India and health jobs
    assert mc.GOLD_KEY_JOBS == ("gold_overnight", "gold_morning", "gold_mcx_master", "gold_health_snapshot",
                                "gold_india_midday", "gold_asia_close", "gold_india_pm", "gold_cot_weekly", "gold_mcx_close")
    assert mc.GOLD_MAX_AGE_DAYS == {"gold_cot": 9, "gold_curve": 4, "gold_daily_bars": 4, "gold_etf_holdings": 5,
                                    "gold_cme_daily_voi": 4}
    assert not hasattr(mc, "DATASET_MAX_AGE_DAYS"), "retired (Terminal v2 1.4): expected_by + max_age sessions via /api/data/health"
    assert "gpr_daily" in mc.gold_groups("gold_morning", at(2026, 10, 26, 6, 40))          # Monday
    assert "gpr_daily" not in mc.gold_groups("gold_morning", at(2026, 10, 27, 6, 40))      # Tuesday
    assert mc.gold_groups("gold_overnight", at(2026, 10, 27, 3, 10))[-1] == "fred_weekly"  # Tue 03:10: H.10
    assert mc.gold_groups("gold_overnight", at(2026, 10, 30, 3, 10))[-1] == "fred_weekly"  # Fri 03:10: H.4.1 / TGA
    assert "fred_weekly" not in mc.gold_groups("gold_overnight", at(2026, 10, 28, 3, 10))


@pytest.mark.parametrize(("ist", "open_"), [
    ((2026, 10, 24, 12, 0), False),    # Saturday
    ((2026, 10, 26, 3, 0), False),     # Mon 03:00 IST = Sun 17:30 ET: Globex not yet open
    ((2026, 10, 26, 3, 35), True),     # Sun 18:05 ET
    ((2026, 10, 27, 2, 40), False),    # Mon 17:10 ET: maintenance hour (US daylight time)
    ((2026, 10, 27, 3, 35), True),
    ((2026, 11, 3, 3, 40), False),     # after 1 Nov: 17:10 EST is 03:40 IST
    ((2026, 11, 3, 4, 35), True),
    ((2026, 10, 31, 2, 20), True),     # Fri 16:50 ET: still trading
    ((2026, 10, 31, 2, 40), False),    # Fri 17:10 ET: weekend close
])
def test_comex_globex_hours_are_dst_aware(ist, open_):
    assert mc.comex_globex_open(at(*ist)) is open_


def test_lifespan_registers_the_gold_jobs_and_downtime_counts_them(monkeypatch, tmp_path):
    """The real lifespan() with a paused scheduler (the test_backup_catchup pattern): every gold id is a job, the
    evening capture too, and a weekend outage would count gold_cot_weekly / gold_overnight as missed."""
    class Paused(mc.AsyncIOScheduler):
        def start(self, paused: bool = False) -> None:
            super().start(paused=True)
    started = at(2030, 3, 4, 21, 20)
    fake_clock(monkeypatch, started)
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
            jobs = mc.scheduler.get_jobs()
            ids = {j.id for j in jobs}
            missed = mc.downtime_missed(jobs, at(2026, 10, 23, 23, 0), at(2026, 10, 26, 9, 53))
            return ids, missed
    ids, missed = asyncio.run(scenario())
    assert set(PLAN_C3_JOBS) <= ids and {"gold_open_capture", "gold_open_capture_evening", "gold_preopen_snapshot"} <= ids
    assert not set(mc.GOLD_DORMANT_JOBS) & ids
    assert missed["gold_cot_weekly"] == 6 and missed["gold_overnight"] == 2 and missed["gold_mcx_master"] == 2
    assert "gold jobs: gold_overnight" in " ".join(log_lines())


# ── freeze-window behaviour of a run ─────────────────────────────────────────────────────────────────────────

def test_freeze_slot_boundaries():
    assert mc.freeze_slot(at(2026, 10, 26, 7, 44, 59)) == at(2026, 10, 26, 7, 44, 59)
    assert mc.freeze_slot(at(2026, 10, 26, 7, 45)) == at(2026, 10, 26, 9, 21)
    assert mc.freeze_slot(at(2026, 10, 26, 9, 20, 30)) == at(2026, 10, 26, 9, 21), "the whole 09:20 minute is inside"
    assert mc.freeze_slot(at(2026, 10, 26, 9, 21)) == at(2026, 10, 26, 9, 21)
    assert mc.freeze_slot(at(2026, 10, 26, 18, 30)) == at(2026, 10, 26, 21, 16)
    assert mc.freeze_slot(at(2026, 10, 26, 21, 15, 59)) == at(2026, 10, 26, 21, 16)
    assert mc.freeze_slot(at(2026, 10, 26, 21, 16)) == at(2026, 10, 26, 21, 16)
    assert mc.in_freeze_window(at(2026, 10, 26, 8, 0)) and mc.in_freeze_window(at(2026, 10, 26, 9, 20, 30))
    assert not mc.in_freeze_window(at(2026, 10, 26, 12, 0)) and not mc.in_freeze_window(at(2026, 10, 26, 9, 21))


@pytest.mark.parametrize(("now", "slot"), [((8, 0), "09:21"), ((19, 0), "21:16")])
def test_a_heavy_gold_job_inside_a_freeze_window_defers_itself(ctl, svc, monkeypatch, now, slot):
    fake_clock(monkeypatch, at(2026, 10, 26, *now))
    asyncio.run(mc.gold_job("gold_overnight"))
    assert svc.posts(mc.GOLD_INGEST_PATH) == []
    [(name, kw)] = ctl["sched"].added
    assert (name, kw["id"], kw["args"], kw["run_date"].strftime("%H:%M")) == ("gold_job", "gold_overnight_deferred", ["gold_overnight"], slot)
    assert kw["replace_existing"] is True and kw["coalesce"] is True and kw["misfire_grace_time"] >= 3600
    assert f"deferred to {slot}" in " ".join(log_lines())


def test_the_cot_job_defers_too_and_a_light_job_runs_inside_the_window(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 26, 8, 35))
    asyncio.run(mc.gold_cot_weekly())
    [(name, kw)] = ctl["sched"].added
    assert (name, kw["id"], kw["args"]) == ("gold_cot_weekly", "gold_cot_weekly_deferred", [])
    asyncio.run(mc.gold_job("gold_mcx_master"))                             # the 08:35 retry PLAN §c.3 allows
    [(query, body)] = svc.posts(mc.GOLD_INGEST_PATH)
    assert query == "job=gold_mcx_master" and body == {"job": "gold_mcx_master", "groups": ["mcx_master", "margins"]}
    assert svc.posts(mc.GOLD_INVALIDATE_PATH) == [("", {"job": "gold_mcx_master"})]
    assert mc._latency.stats()["gold_mcx_master"]["last_status"] == "done"


def test_the_bars_job_runs_only_while_comex_trades_and_is_quiet(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 24, 12, 0))                        # Saturday
    asyncio.run(mc.gold_job("gold_intraday_bars"))
    assert svc.posts(mc.GOLD_INGEST_PATH) == []
    fake_clock(monkeypatch, at(2026, 10, 26, 12, 0))
    asyncio.run(mc.gold_job("gold_intraday_bars"))
    [(query, body)] = svc.posts(mc.GOLD_INGEST_PATH)
    assert query == "job=gold_intraday_bars" and body["groups"] == ["bars_1m"]
    assert mc._latency.stats()["gold_intraday_bars"]["last_status"] == "done"       # SYS sees it
    assert log_lines() == [], "a 5-minute job writes neither a 'started' nor a 'Finished' line (288 a day)"
    svc.job_status, svc.job_error = "error", "Yahoo 429"
    for _ in range(3):
        asyncio.run(mc.gold_job("gold_intraday_bars"))
    assert mc._latency.stats()["gold_intraday_bars"]["last_status"] == "error"
    assert ctl["alerts"].sent == [] and len([ln for ln in log_lines() if "Yahoo 429" in ln]) == 1, \
        "a quiet job never alerts and repeats its failure line at most once an hour"


def test_disabled_flags_stop_every_gold_run(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 26, 12, 0))
    monkeypatch.setattr(mc, "GOLD_JOBS_ENABLED", False)
    asyncio.run(mc.gold_job("gold_asia_close"))
    asyncio.run(mc.gold_cot_weekly())
    assert svc.calls == [] and ctl["sched"].added == []


# ── failures: a 404 pauses, an error is logged once a day and shows in SYS ────────────────────────────────────

def test_a_404_from_data_service_pauses_the_gold_jobs_for_an_hour(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 26, 12, 0))
    svc.ingest_status = 404
    asyncio.run(mc.gold_job("gold_asia_close"))
    assert mc._latency.stats()["gold_asia_close"]["last_status"] == "error"
    assert mc._GOLD_PAUSED_UNTIL > 0 and ctl["alerts"].sent == []
    assert any("gold jobs paused for an hour" in ln for ln in log_lines())
    n = len(svc.calls)
    asyncio.run(mc.gold_job("gold_india_midday"))                            # paused: no request at all
    asyncio.run(mc.gold_cot_weekly())
    assert len(svc.calls) == n


def test_a_failed_fetch_is_an_error_in_sys_and_one_telegram_line_a_day(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 26, 12, 0))
    svc.job_status, svc.job_error = "error", "SGE 503"
    asyncio.run(mc.gold_job("gold_asia_close"))
    asyncio.run(mc.gold_job("gold_asia_close"))
    assert len(svc.posts(mc.GOLD_INGEST_PATH)) == 2, "a failure is not a pause: the next run tries again"
    assert svc.posts(mc.GOLD_INVALIDATE_PATH) == [], "no cache invalidation after a failed ingest"
    assert mc._latency.stats()["gold_asia_close"]["last_status"] == "error"
    assert [(lvl, t) for lvl, t, _ in ctl["alerts"].sent] == [("info", "Gold data job gold_asia_close failed")]
    assert "SGE 503" in ctl["alerts"].sent[0][2] and "STALE" in ctl["alerts"].sent[0][2]
    assert not DIRECTION_WORDS.search(ctl["alerts"].sent[0][2])
    errors = [ln for ln in log_lines() if ln.startswith("FAILED: RuntimeError")]
    assert len(errors) == 2 and "SGE 503" in errors[0], "every failed daily run is an ERROR line; Telegram once a day"


def test_result_helpers_tolerate_any_shape():
    assert mc.gold_result_digest(None) == "done (no result body)"
    assert mc.gold_result_digest({"groups": {"etf": {"status": "ok"}, "fed_path": {"error": "boom"}, "gpr": {"skipped": True}},
                                  "tables": {"gold_etf_holdings": {"last": "2026-10-23"}}}) == \
        "groups error=1 ok=2; failed: fed_path; through etf_holdings=2026-10-23"
    assert mc.gold_result_digest({"note": "already up to date"}) == "done: note"
    assert mc.gold_result_rows({"groups": {"cot": {"new_rows": 8, "rows": 1063}}, "inserted": 2}) == 10
    assert mc.gold_result_rows({"rows": 1063}) == 0 and mc.gold_result_rows("x") == 0


B1_MCX_RESULT: dict[str, Any] = {       # data-service gold.jobs.run_job's shape (B1): groups{status, inserted, …}, rows_total, tables
    "job": "gold_mcx_master",
    "groups": {"mcx_master": {"status": "not_modified", "inserted": 0, "seconds": 0.21},
               "margins": {"status": "ok", "inserted": 3, "seconds": 1.4}},
    "rows_total": 3,
    "tables": {"gold_curve": {"first": "2026-09-01 00:00:00", "last": "2026-10-23 00:00:00", "rows": 1210},
               "gold_cot": {"first": None, "last": None, "rows": 0, "error": "CatalogException"}},
}


def test_b1_result_shape_is_read_as_the_controller_reads_it():
    """B1's run_job contract: `rows_total` wins over any nested count; `not_modified` / `skipped` / `dormant` are
    outcomes; error / unknown / degraded / http_<code> are failures; `tables` carries 'YYYY-MM-DD HH:MM:SS' dates."""
    assert mc.gold_result_rows(B1_MCX_RESULT) == 3 and mc.gold_result_rows({"rows_total": 0, "groups": {"x": {"inserted": 9}}}) == 0
    assert mc.gold_result_digest(B1_MCX_RESULT) == "groups not_modified=1 ok=1; rows +3; through curve=2026-10-23"
    assert not mc.gold_result_all_failed(B1_MCX_RESULT)
    for status in ("error", "unknown", "degraded", "http_404", "http_503"):
        assert mc._gold_group_failed({"status": status}), status
    for status in ("ok", "skipped", "dormant", "not_modified", "not_trading", "have"):
        assert not mc._gold_group_failed({"status": status}), status
    assert mc._gold_group_failed({"status": "ok", "error": "boom"}), "an error key is a failure whatever the status"
    failed = {"groups": {"sge_daily": {"status": "http_403"}, "shfe": {"status": "error", "error": "timeout"}}}
    assert mc.gold_result_all_failed(failed) and "failed: sge_daily, shfe" in mc.gold_result_digest(failed)


def test_a_304_from_the_mcx_master_loader_is_an_outcome_not_a_failure(ctl, svc, monkeypatch):
    """T5 'conditional-GET master loader (304 path)', the controller's side: B1's mcx_master group answers
    not_modified on a 304 (its own test covers the If-Modified-Since request); here that run is done, not an error:
    no ERROR line, no Telegram, SYS says done, the cache invalidation still happens (the margins leg stored rows)."""
    fake_clock(monkeypatch, at(2026, 10, 26, 7, 35))
    svc.result = B1_MCX_RESULT
    asyncio.run(mc.gold_job("gold_mcx_master"))
    assert mc._latency.stats()["gold_mcx_master"]["last_status"] == "done"
    assert ctl["alerts"].sent == [] and not [ln for ln in log_lines() if ln.startswith("FAILED")]
    assert "groups not_modified=1 ok=1; rows +3; through curve=2026-10-23" in log_lines()
    assert svc.posts(mc.GOLD_INVALIDATE_PATH) == [("", {"job": "gold_mcx_master"})]
    # negative control: every group failing is a failure (ERROR line + the one Telegram line a day)
    svc.result = {"job": "gold_mcx_master", "groups": {"mcx_master": {"status": "http_503"}, "margins": {"status": "error", "error": "x"}},
                  "rows_total": 0, "tables": {}}
    asyncio.run(mc.gold_job("gold_mcx_master"))
    assert mc.gold_result_all_failed(svc.result)
    assert "failed: mcx_master, margins" in " ".join(log_lines()), "the digest names the groups that did not deliver"


def test_every_controller_group_name_resolves_in_b1s_gold_jobs():
    """The controller's group names (GOLD_JOBS + GOLD_DAY_GROUPS) all resolve, through B1's ALIASES, to a GROUPS entry
    of data-service gold.jobs — the names data-service's POST /jobs/ingest-gold accepts (an unknown name is 422 when
    none resolves, 'unknown' per group otherwise). The dormant ids are B1's DORMANT ones, never registered."""
    sys.path.insert(0, str(ROOT / "services" / "data-service"))
    try:
        from gold import jobs as b1
    finally:
        sys.path.pop(0)
    names = {g for spec in mc.GOLD_JOBS.values() for g in spec.groups} | {g for g, _ in mc.GOLD_DAY_GROUPS.values()}
    unresolved = sorted(n for n in names if b1.resolve(n) not in b1.GROUPS)
    assert unresolved == [], f"data-service does not know: {unresolved}"
    assert {b1.resolve(n) for n in ("cme_voi_final", "etf", "fed_path", "bars_1m", "gpr_daily", "margins", "lbma_wgc")} <= set(b1.GROUPS)
    assert not any(b1.resolve(n) in b1.DORMANT for n in names), "no scheduled job asks for a dormant (O-8) group"
    assert {"mcx_official", "mcx_category", "breeze_daily"} <= set(b1.DORMANT), "B1's dormant set is the controller's GOLD_DORMANT_JOBS"


# ── MCX holiday gating of the pre-open desk jobs ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("day", "open_", "snapshot", "capture_at", "closure"), [
    (date(2026, 10, 20), True, False, "17:10", "morning"),    # Dussehra: evening session only
    (date(2026, 10, 2), False, False, None, "full"),          # Gandhi Jayanti
    (date(2026, 10, 23), True, True, "09:10", None),          # an ordinary Friday
    (date(2026, 1, 1), True, True, "09:10", "evening"),       # New Year: morning session runs, evening shut
    (date(2026, 10, 24), False, False, None, "weekend"),
])
def test_mcx_day_plan(day, open_, snapshot, capture_at, closure):
    plan = mc.mcx_day_plan(day)
    assert (plan["open"], plan["snapshot"], plan["capture_at"], plan["closure"]) == (open_, snapshot, capture_at, closure)


def _desk_routes(svc: Services) -> None:
    svc.routes[("POST", f"{mc.GOLD_DESK_API}/snapshot")] = {"date": "2026-10-23", "contract": "GOLD DEC-26", "fair_open": 144181.0,
                                                           "baseline": 146079.0, "baseline_source": "ICICI master band",
                                                           "baseline_session": "2026-10-22"}
    svc.routes[("GET", f"{mc.GOLD_DESK_API}/log")] = {"rows": [], "stats": {"days": 4, "median_abs_error": 2880.0,
                                                                            "mean_abs_error": 3010.5, "p90_abs_error": 3518.0,
                                                                            "threshold": 300}}
    svc.routes[("POST", f"{mc.GOLD_DESK_API}/capture-open")] = {"date": "2026-10-23", "actual_open": 142058.0,
                                                               "fair_open": 144938.0, "error": -2880.0}


@pytest.mark.parametrize("day", [(2026, 10, 20), (2026, 10, 2)])
def test_the_0845_snapshot_skips_morning_closure_and_full_holidays(ctl, svc, monkeypatch, day):
    _desk_routes(svc)
    fake_clock(monkeypatch, at(*day, 8, 45))
    asyncio.run(mc.gold_preopen_snapshot())
    asyncio.run(mc.gold_preopen_snapshot())
    assert svc.calls == [] and ctl["alerts"].sent == []
    skips = [ln for ln in log_lines() if ln.startswith("skipped: MCX")]
    assert len(skips) == 1, "logged once per day"
    assert ("Dussehra" in skips[0] and "opens 17:00" in skips[0]) if day[1:] == (10, 20) else "closed today" in skips[0]


def test_the_0845_snapshot_on_a_trading_day_carries_the_measured_miss_as_context(ctl, svc, monkeypatch):
    _desk_routes(svc)
    fake_clock(monkeypatch, at(2026, 10, 23, 8, 45))
    asyncio.run(mc.gold_preopen_snapshot())
    assert [p for m, p, _, _ in svc.calls] == [f"{mc.GOLD_DESK_API}/snapshot", f"{mc.GOLD_DESK_API}/log"]
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("info", "Gold pre-open")
    assert body == ("GOLD DEC-26: fair open ₹144,181 (−1,898 vs Thu 22 Oct settlement ₹146,079). Don't chase more than ₹300 "
                    "above it (house rule, heuristic: unproven). Model miss so far: median ₹2,880 over 4 days (p90 ₹3,518) "
                    "— describes past calls, not today's direction.")
    assert not DIRECTION_WORDS.search(body)
    assert mc._latency.stats()["gold_preopen_snapshot"]["last_status"] == "done"


def test_the_0845_wording_without_a_log_and_with_a_session_label():
    row = {"contract": "GOLD DEC-26", "fair_open": 144181.0, "baseline": 146079.0, "baseline_session_label": "Thu 22 Oct settlement"}
    text = mc.compose_gold_preopen_alert(row, None)
    assert "vs Thu 22 Oct settlement ₹146,079" in text and text.endswith("No measured miss yet: the accuracy log has no completed day.")
    text = mc.compose_gold_preopen_alert({"fair_open": 144181.0}, {"days": 1, "median_abs_error": 3518})
    assert text.startswith("GOLD: fair open ₹144,181.") and "median ₹3,518 over 1 day —" in text
    assert not DIRECTION_WORDS.search(text)
    text = mc.compose_gold_preopen_alert({"fair_open": 144181.0, "threshold": 500}, None)
    assert "₹500 above it" in text and "₹300" not in text, "the desk's own chase limit wins over the default"


def test_the_open_is_captured_at_0910_normally_and_at_1710_on_a_morning_closure_day(ctl, svc, monkeypatch):
    _desk_routes(svc)
    capture = f"{mc.GOLD_DESK_API}/capture-open"
    fake_clock(monkeypatch, at(2026, 10, 20, 9, 10))                        # Dussehra 09:10: nothing to capture
    asyncio.run(mc.gold_open_capture())
    assert svc.posts(capture) == [] and any("opens 17:00" in ln for ln in log_lines())
    fake_clock(monkeypatch, at(2026, 10, 20, 17, 10))
    asyncio.run(mc.gold_open_capture(evening=True))
    assert len(svc.posts(capture)) == 1 and mc._latency.stats()["gold_open_capture_evening"]["last_status"] == "done"
    fake_clock(monkeypatch, at(2026, 10, 23, 17, 10))                       # an ordinary day: the evening run is silent
    asyncio.run(mc.gold_open_capture(evening=True))
    assert len(svc.posts(capture)) == 1
    fake_clock(monkeypatch, at(2026, 10, 23, 9, 10))
    asyncio.run(mc.gold_open_capture())
    assert len(svc.posts(capture)) == 2 and any("open=142058.0" in ln for ln in log_lines())
    fake_clock(monkeypatch, at(2026, 10, 2, 9, 10))                         # full closure: neither run posts
    asyncio.run(mc.gold_open_capture())
    asyncio.run(mc.gold_open_capture(evening=True))
    assert len(svc.posts(capture)) == 2


# ── COT: expected week, digest wording, the job's flow ──────────────────────────────────────────────────────

@pytest.mark.parametrize(("now", "tue"), [
    ((2026, 10, 24, 2, 30), date(2026, 10, 20)),   # Saturday run: Friday's release carries Tuesday 20 Oct
    ((2026, 10, 25, 12, 0), date(2026, 10, 20)),
    ((2026, 10, 26, 6, 30), date(2026, 10, 20)),   # Monday catch-up
    ((2026, 10, 27, 6, 30), date(2026, 10, 20)),   # Tuesday catch-up: 27 Oct's report comes Saturday
    ((2026, 10, 30, 23, 0), date(2026, 10, 20)),
    ((2026, 10, 31, 2, 30), date(2026, 10, 27)),
    ((2026, 11, 17, 6, 30), date(2026, 11, 10)),   # the holiday-delayed Monday release (16 Nov ET) lands for the Tue retry
])
def test_cot_expected_report_date(now, tue):
    assert mc.cot_expected_report_date(at(*now)) == tue


def test_cot_digest_from_the_20_oct_week_is_description_not_direction():
    line = mc.compose_cot_digest(COT_20_OCT)
    assert line == ("COT 20 Oct (Tue positions, released Fri 23 Oct) · funds net +104.2k (−2.9k w/w) — closed 3,777 longs, "
                    "covered 894 shorts · long liquidation · OI 402,279 (+5,934) · next Sat 31 Oct 01:00 IST · "
                    "explains the week — does not forecast")
    assert not DIRECTION_WORDS.search(line) and "index" not in line, "26.3 is no extreme: no positioning note"


def test_cot_digest_extremes_note_is_context_only_and_tolerates_missing_fields():
    crowded = {**COT_20_OCT, "crowd": {"cot_index_52": 94.0, "z156": 2.3}}
    line = mc.compose_cot_digest(crowded)
    assert "52-w COT index 94, z156 +2.3 — historically crowded; context only: no forecasting power 2006–2026 (G-STUDY)" in line
    washed = {**COT_20_OCT, "crowd": {"cot_index_52": 6.0}}
    assert "historically washed-out; context only" in mc.compose_cot_digest(washed)
    for text in (line, mc.compose_cot_digest(washed)):
        assert not DIRECTION_WORDS.search(text) and text.endswith("explains the week — does not forecast")
    bare = mc.compose_cot_digest({"latest": {"report_date": "2026-10-27"}, "groups": [{"key": "managed_money", "net": -1500}]})
    assert bare == "COT 27 Oct (Tue positions) · funds net −1.5k · explains the week — does not forecast"
    assert mc.cot_report_date(COT_20_OCT) == "2026-10-20" and mc.cot_report_date(None) is None and mc.cot_report_date({}) is None


def test_relayed_strings_with_a_direction_word_are_dropped_not_quoted(ctl):
    """PLAN §f / O-14: who_did, the driver label and the desk's session label come from ui-api; a fragment carrying a
    direction word is dropped (one WARNING), the rest of the line stands. Negative control: the clean fragments pass."""
    mm = dict(next(g for g in COT_20_OCT["groups"] if g["key"] == "mm"))
    mm["who_did"] = ["closed 3,777 longs", "go long now"]
    loud = {**COT_20_OCT, "groups": [mm], "driver_label": "bullish build-up"}
    line = mc.compose_cot_digest(loud)
    assert "closed 3,777 longs" in line and "go long" not in line and "bullish" not in line
    assert not DIRECTION_WORDS.search(line) and line.endswith("explains the week — does not forecast")
    warned = [ln for ln in log_lines() if ln.startswith("dropped a relayed fragment with a direction word")]
    assert len(warned) == 1, "one WARNING per job per 10 minutes, whatever the number of fragments"
    row = {"contract": "GOLD DEC-26", "fair_open": 144181.0, "baseline": 146079.0, "baseline_session": "2026-10-22",
           "baseline_session_label": "Thu 22 Oct settlement, buy the dip"}
    text = mc.compose_gold_preopen_alert(row, None)
    assert "vs Thu 22 Oct settlement ₹146,079" in text and "buy" not in text, "falls back to the label derived from the session date"
    assert mc.compose_cot_digest(COT_20_OCT).count("closed 3,777 longs, covered 894 shorts") == 1, "clean fragments pass"


def test_cot_job_skips_when_the_week_is_already_stored(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 24, 2, 30))
    svc.routes[("GET", "/api/gold/cot")] = COT_20_OCT
    asyncio.run(mc.gold_cot_weekly())
    assert svc.posts(mc.GOLD_INGEST_PATH) == [] and ctl["alerts"].sent == []
    assert any("already stored" in ln for ln in log_lines())
    assert mc._latency.stats()["gold_cot_weekly"]["last_status"] == "done"


def test_cot_job_fetches_and_sends_the_saturday_digest_once(ctl, svc, monkeypatch):
    """Sat 02:30: ui-api still serves the 13 Oct week → the ingest runs → ui-api now serves 20 Oct → ONE digest line;
    the 03:30 retry finds the week stored and sends nothing."""
    fake_clock(monkeypatch, at(2026, 10, 24, 2, 30))
    stored = {"n": 0}
    old = {**COT_20_OCT, "latest": {**COT_20_OCT["latest"], "report_date": "2026-10-13"}}
    svc.routes[("GET", "/api/gold/cot")] = lambda r: httpx.Response(200, json=COT_20_OCT if stored["n"] else old)
    svc.on_ingest = lambda r: stored.__setitem__("n", stored["n"] + 1)
    asyncio.run(mc.gold_cot_weekly())
    [(query, body)] = svc.posts(mc.GOLD_INGEST_PATH)
    assert query == "job=gold_cot_weekly" and body == {"job": "gold_cot_weekly", "groups": ["cot"]}
    assert svc.posts(mc.GOLD_INVALIDATE_PATH) == [("", {"job": "gold_cot_weekly"})]
    assert ctl["alerts"].sent == [("info", "COT weekly (context)", mc.compose_cot_digest(COT_20_OCT))]
    assert mc._latency.stats()["gold_cot_weekly"]["last_status"] == "done"
    asyncio.run(mc.gold_cot_weekly())                                         # the 03:30 retry: stored → silent
    assert len(ctl["alerts"].sent) == 1 and len(svc.posts(mc.GOLD_INGEST_PATH)) == 1


def test_cot_rows_stored_while_ui_api_still_serves_the_older_week_is_the_fallback_line(ctl, svc, monkeypatch):
    """B3's stored-read cache may lag the ingest by up to 120 s: the line reports the rows and names the lag instead of
    quoting last week's numbers as this week's."""
    fake_clock(monkeypatch, at(2026, 10, 24, 2, 30))
    svc.routes[("GET", "/api/gold/cot")] = {**COT_20_OCT, "latest": {**COT_20_OCT["latest"], "report_date": "2026-10-13"}}
    asyncio.run(mc.gold_cot_weekly())
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("info", "COT weekly (context)")
    assert body.startswith("COT: 8 new row(s) stored") and "still serving the 13 Oct week" in body
    assert "104" not in body and not DIRECTION_WORDS.search(body)


def test_cot_job_not_yet_published_is_no_alert_and_the_fallback_when_ui_api_lacks_the_route(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 24, 2, 30))
    svc.routes[("GET", "/api/gold/cot")] = {**COT_20_OCT, "latest": {**COT_20_OCT["latest"], "report_date": "2026-10-13"}}
    svc.result = {"groups": {"cot": {"status": "ok", "new_rows": 0}}}
    asyncio.run(mc.gold_cot_weekly())
    assert ctl["alerts"].sent == [] and any("not published yet" in ln for ln in log_lines())
    del svc.routes[("GET", "/api/gold/cot")]                                  # ui-api without B3's router → 404
    svc.result = {"groups": {"cot": {"status": "ok", "new_rows": 8}}}
    asyncio.run(mc.gold_cot_weekly())
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("info", "COT weekly (context)") and body.startswith("COT: 8 new row(s) stored")
    assert body.endswith("explains the week — does not forecast") and not DIRECTION_WORDS.search(body)


# ── catch-up: missed_jobs(), the downtime report ────────────────────────────────────────────────────────────

def _history_file(root: Path, jobs: dict[str, str]) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / ".scheduler_history.json").write_text(json.dumps(
        {"version": 1, "jobs": {k: {"last_run_ts": v, "last_status": "done", "last_ms": 1.0, "runs": 1} for k, v in jobs.items()}}))


def test_missed_jobs_lists_the_gold_ids_from_the_persisted_history(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "terminal_missed_jobs", lambda now, h: [])   # the terminal slots: test_terminal_v2_controller
    (tmp_path / "data" / "nse_archive" / "preopen").mkdir(parents=True)
    (tmp_path / "reports" / "daily_wrap").mkdir(parents=True)
    mon = at(2026, 10, 26, 10, 0)
    assert mc.missed_jobs(mon, tmp_path) == ["preopen_capture"], "no history file: no evidence of a gold miss"
    _history_file(tmp_path, {"gold_overnight": "2026-10-24T03:11:00+05:30", "gold_mcx_master": "2026-10-26T07:36:00+05:30",
                             "gold_cot_weekly": "2026-10-24T02:31:00+05:30"})
    assert mc.missed_jobs(mon, tmp_path) == ["preopen_capture", "gold_overnight"]       # Monday 03:10 passed, Sat's run is old
    assert mc.missed_jobs(datetime(2026, 10, 26, 10, 0), tmp_path) == ["preopen_capture", "gold_overnight"]   # naive clock too
    _history_file(tmp_path, {"gold_overnight": "2026-10-26T03:11:00+05:30", "gold_mcx_master": "2026-10-23T07:36:00+05:30",
                             "gold_cot_weekly": "2026-10-17T02:31:00+05:30"})
    assert mc.missed_jobs(mon, tmp_path) == ["preopen_capture", "gold_mcx_master", "gold_cot_weekly"]
    # the weekend, seen from a history whose last overnight run was Friday's and whose last COT week is 17 Oct
    _history_file(tmp_path, {"gold_overnight": "2026-10-23T03:11:00+05:30", "gold_mcx_master": "2026-10-23T07:36:00+05:30",
                             "gold_cot_weekly": "2026-10-17T02:31:00+05:30"})
    assert mc.missed_jobs(at(2026, 10, 24, 3, 0), tmp_path) == ["gold_cot_weekly"]      # Sat 03:00: COT slot passed, 03:10 not
    assert mc.missed_jobs(at(2026, 10, 24, 3, 20), tmp_path) == ["gold_overnight", "gold_cot_weekly"]
    assert mc.missed_jobs(at(2026, 10, 25, 12, 0), tmp_path) == ["gold_cot_weekly"]     # Sunday: no overnight run
    _history_file(tmp_path, {"gold_overnight": "2026-10-24T03:11:00+05:30", "gold_cot_weekly": "2026-10-24T02:31:00+05:30"})
    assert mc.missed_jobs(at(2026, 10, 24, 3, 20), tmp_path) == [], "both ran this morning"
    _history_file(tmp_path, {"eod_data_pipeline": "2026-10-23T18:31:00+05:30"})           # a history that never saw gold
    assert mc.missed_jobs(at(2026, 10, 28, 12, 0), tmp_path) == ["preopen_capture", "gold_overnight", "gold_mcx_master"]
    assert mc.gold_missed_jobs(mon, None) == [] and mc.read_job_history(tmp_path / "nowhere") is None


def test_downtime_catchup_reruns_the_key_gold_jobs_with_backfill_from(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 26, 10, 0))
    svc.routes[("GET", "/db/market-monitor")] = {"as_of": "2026-10-23"}
    for path in ("/jobs/ingest-bhavcopy", "/jobs/ingest-nse-positions", "/jobs/ingest-nse-events"):
        svc.routes[("POST", path)] = {"job_id": "j1"}
    svc.routes[("GET", "/api/gold/cot")] = COT_20_OCT
    missed = {"gold_overnight": 2, "gold_mcx_master": 2, "gold_cot_weekly": 6, "move_alerts": 40}
    asyncio.run(mc._startup_catchup_run("2026-10-23T23:00:00+05:30", "2026-10-26T09:53:00+05:30", missed, "nse", None))
    gold_posts = svc.posts(mc.GOLD_INGEST_PATH)
    assert [q for q, _ in gold_posts] == ["job=gold_overnight", "job=gold_mcx_master"]
    assert all(b["backfill_from"] == "2026-10-23" for _, b in gold_posts)
    assert gold_posts[0][1]["groups"] == list(mc.gold_groups("gold_overnight", at(2026, 10, 26, 10, 0), backfill=True))
    assert "fred_weekly" in gold_posts[0][1]["groups"], "a multi-day backfill asks for the Tue/Fri group on a Monday too"
    assert mc.gold_groups("gold_overnight", at(2026, 10, 26, 3, 10)) == mc.GOLD_JOBS["gold_overnight"].groups, "not on a plain Monday run"
    assert mc._latency.stats()["gold_overnight"]["last_status"] == "done", "the catch-up run is recorded like a scheduled one"
    assert mc._latency.stats()["gold_mcx_master"]["last_status"] == "done"
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("warning", "Stack was down — catching up")
    assert "gold catch-up from 2026-10-23: gold_overnight: ok" in body and "gold_cot_weekly: ran" in body
    assert "already stored" in " ".join(log_lines()), "the COT job ran itself and found the week stored"
    assert ctl["sched"].added == []


@pytest.mark.parametrize(("now", "mode", "slot"), [((19, 0), "skip", "21:16"), ((18, 35), "nse", "21:16"), ((8, 0), "nse", "09:21")])
def test_downtime_gold_catchup_never_runs_inside_a_freeze_window(ctl, svc, monkeypatch, now, mode, slot):
    fake_clock(monkeypatch, at(2026, 10, 26, *now))
    svc.routes[("GET", "/db/market-monitor")] = {"as_of": "2026-10-23"}
    for path in ("/jobs/ingest-bhavcopy", "/jobs/ingest-nse-positions", "/jobs/ingest-nse-events"):
        svc.routes[("POST", path)] = {"job_id": "j1"}
    asyncio.run(mc._startup_catchup_run("2026-10-23T23:00:00+05:30", "2026-10-26T18:59:00+05:30",
                                        {"gold_overnight": 2, "gold_cot_weekly": 6}, mode, None))
    assert svc.posts(mc.GOLD_INGEST_PATH) == []
    [(name, kw)] = ctl["sched"].added
    assert (name, kw["id"], kw["args"], kw["run_date"].strftime("%H:%M")) == (
        "gold_downtime_catchup", "gold_downtime_catchup", [["gold_overnight", "gold_cot_weekly"], "2026-10-23"], slot)
    assert f"one run at {slot} with backfill from 2026-10-23" in ctl["alerts"].sent[0][2]


def test_gold_downtime_catchup_reports_each_job(ctl, svc, monkeypatch):
    fake_clock(monkeypatch, at(2026, 10, 26, 12, 0))
    svc.ingest_status = 404
    line = asyncio.run(mc.gold_downtime_catchup(["gold_overnight", "gold_mcx_master"], "2026-10-23"))
    assert line.startswith("gold catch-up from 2026-10-23: gold_overnight: data-service has no /jobs/ingest-gold")
    assert "gold_mcx_master" not in line, "one 404 stops the loop"
    assert mc._latency.stats()["gold_overnight"]["last_status"] == "error", "a failed catch-up is an error in SYS, not done"


def test_downtime_catchup_waits_for_a_held_lock_and_the_backfill_run_happens(ctl, svc, monkeypatch):
    """Wave-1 review: the run carrying backfill_from used to be skipped ('already running') when another run held the
    job's lock. Now it waits: exactly one POST per job, and it carries backfill_from."""
    fake_clock(monkeypatch, at(2026, 10, 26, 10, 0))
    lock = mc._get_lock("gold_overnight")

    async def scenario() -> str:
        await lock.acquire()
        task = asyncio.create_task(mc.gold_downtime_catchup(["gold_overnight"], "2026-10-23"))
        await asyncio.sleep(0.01)
        assert svc.posts(mc.GOLD_INGEST_PATH) == [], "waiting for the lock, not skipping"
        lock.release()
        return await task
    line = asyncio.run(scenario())
    [(query, body)] = svc.posts(mc.GOLD_INGEST_PATH)
    assert query == "job=gold_overnight" and body["backfill_from"] == "2026-10-23"
    assert "already running" not in line and line.startswith("gold catch-up from 2026-10-23: gold_overnight: ok")


def test_lifespan_leaves_the_gold_ids_the_downtime_catchup_owns_to_it(monkeypatch, tmp_path):
    """Both catch-up paths armed (a weekend outage: the heartbeat gap counts the key gold jobs AND missed_jobs() lists
    them): lifespan schedules no plain '<id>_catchup' one-off for those ids — gold_downtime_catchup, which carries
    backfill_from, owns them; a non-gold missed job and a gold id the heartbeat did not count still get their one-off."""
    class Paused(mc.AsyncIOScheduler):
        def start(self, paused: bool = False) -> None:
            super().start(paused=True)
    started = at(2030, 3, 4, 21, 20)                                        # Monday evening
    fake_clock(monkeypatch, started)
    monkeypatch.setattr(mc, "_alerts", _Alerts())
    monkeypatch.setattr(mc, "HEARTBEAT_FILE", tmp_path / "hb.json")
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(mc, "_history", mc.JobHistory(tmp_path / "history.json"))
    monkeypatch.setattr(mc, "_log", mc.LogRingBuffer())
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: ["gold_overnight", "gold_cot_weekly", "daily_wrap"])
    monkeypatch.setattr(mc, "scheduler", None)
    monkeypatch.setattr(mc, "AsyncIOScheduler", Paused)
    mc.write_heartbeat(tmp_path / "hb.json", at(2030, 3, 1, 23, 0))        # down since Friday night

    async def no_bot() -> None:
        return None
    monkeypatch.setattr(mc, "telegram_poller", no_bot)

    async def scenario():
        async with mc.lifespan(mc.app):
            return {j.id: j for j in mc.scheduler.get_jobs()}
    jobs = asyncio.run(scenario())
    assert "startup_catchup" in jobs and set(jobs["startup_catchup"].args[2]) >= {"gold_overnight", "gold_cot_weekly", "gold_mcx_master"}
    assert "gold_overnight_catchup" not in jobs and "gold_cot_weekly_catchup" not in jobs
    assert "daily_wrap_catchup" in jobs, "the non-gold missed job keeps its one-off"
    lines = " ".join(log_lines())
    assert "missed today: gold_overnight → left to the downtime catch-up (backfill from 2030-03-01)" in lines
    # no heartbeat gap (a plain restart): the one-off path still owns a gold id missed_jobs() lists
    monkeypatch.setattr(mc, "missed_jobs", lambda now, root: ["gold_overnight"])
    mc.write_heartbeat(tmp_path / "hb.json", started - timedelta(minutes=2))
    jobs = asyncio.run(scenario())
    assert "gold_overnight_catchup" in jobs and "startup_catchup" not in jobs
    assert jobs["gold_overnight_catchup"].next_run_time.strftime("%H:%M") == "21:21", "21:20 is inside the EOD window: the slot after it"


# ── ICICI: ?force=1, the market-hours refusal, _mark_failed on rc 2, the OTP hint ──────────────────────────

@pytest.fixture
def refresh(monkeypatch: pytest.MonkeyPatch, ctl: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {"calls": [], "rc": 0, "result": {"status": "valid", "detail": "current token still works"}}

    async def fake_run(extra: tuple[str, ...] = ()) -> tuple[int, dict]:
        state["calls"].append(extra)
        return state["rc"], state["result"]

    async def live(*a: Any, **k: Any) -> bool:
        return True

    async def nosleep(_s: float) -> None:
        return None
    monkeypatch.setattr(mc, "_run_session_refresh", fake_run)
    monkeypatch.setattr(mc, "_ensure_live_prices", live)
    monkeypatch.setattr(mc.asyncio, "sleep", nosleep)
    monkeypatch.setattr(mc, "ICICI_AUTO_LOGIN", True)
    monkeypatch.setattr(mc, "_login_task", None)
    return state


def test_force_passes_force_to_the_refresh_script(refresh, ctl):
    asyncio.run(mc.icici_session_refresh(force=True))
    asyncio.run(mc.icici_session_refresh())
    asyncio.run(mc.icici_session_refresh(startup=True, force=True))
    assert refresh["calls"] == [("--force",), (), ("--quiet-minutes", "30", "--force")]
    assert mc._latency.stats()["icici_session_refresh"]["last_status"] == "done"


def test_rc2_is_recorded_as_an_error_with_the_right_hint(refresh, ctl):
    refresh["rc"], refresh["result"] = 2, {"status": "needs_human", "detail": "ICICI_TOTP_SECRET is unusable: not valid base32"}
    asyncio.run(mc.icici_session_refresh())
    assert mc._latency.stats()["icici_session_refresh"]["last_status"] == "error"
    [(level, title, body)] = ctl["alerts"].sent
    assert (level, title) == ("critical", "ICICI login needs you")
    # an unusable authenticator key is not a password problem, and the SMS code only comes after the key is replaced or
    # removed (an empty .env value falls through to the Keychain copy, so the fix is the Keychain item itself)
    assert "TOTP setup key" in body and "/password" not in body and "add-generic-password -U" in body
    assert "delete-generic-password" in body and body.index("delete-generic-password") < body.index("SMS code")
    assert mc.otp_hint("ICICI sent an SMS OTP; nobody replied") == "Send /login when you can reply with the SMS code."
    assert mc.otp_hint("ICICI_TOTP_SECRET is unusable") .startswith("The stored authenticator key is not a TOTP setup key")
    assert "/password" not in mc.otp_hint("ICICI_TOTP_SECRET is unusable: TOTP secret is not valid base32")
    # negative controls: a rejected password still points at /password; an SMS OTP still points at /login
    assert mc.otp_hint("ICICI rejected the login: wrong password") == "On Telegram: /password (or /userid) to fix it, then /login."
    assert mc.otp_hint("no OTP received in time") == "Send /login when you can reply with the SMS code."


def test_a_retry_that_still_fails_is_an_error(refresh, ctl):
    refresh["rc"], refresh["result"] = 3, {"status": "retry", "detail": "refresh script timed out after 8 min"}
    asyncio.run(mc.icici_session_refresh())
    assert len(refresh["calls"]) == 2 and mc._latency.stats()["icici_session_refresh"]["last_status"] == "error"
    assert ctl["alerts"].sent == [("critical", "ICICI session refresh FAILED", "refresh script timed out after 8 min")]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, ctl: dict[str, Any]) -> tuple[TestClient, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    async def _noop() -> None:
        return None

    def fake_refresh(*a: Any, **k: Any) -> Any:
        seen.append(k)
        return _noop()
    monkeypatch.setattr(mc, "icici_session_refresh", fake_refresh)
    monkeypatch.setattr(mc, "_login_task", None)
    return TestClient(mc.app), seen


def test_force_query_reaches_the_job_and_is_refused_in_market_hours(api, monkeypatch):
    client, seen = api
    fake_clock(monkeypatch, at(2026, 10, 26, 16, 0))
    r = client.post("/api/scheduler/icici-refresh?force=1", headers={"host": "localhost:8008"})
    assert r.status_code == 200 and r.json()["started"] is True and r.json()["force"] is True and "forced" in r.json()["detail"]
    assert seen == [{"force": True}]
    r = client.post("/api/scheduler/icici-refresh", headers={"host": "localhost:8008"})
    assert r.json()["started"] is True and r.json()["force"] is False and seen == [{"force": True}, {"force": False}]
    fake_clock(monkeypatch, at(2026, 10, 26, 11, 0))                        # Monday 11:00: trading
    r = client.post("/api/scheduler/icici-refresh?force=1", headers={"host": "localhost:8008"})
    assert r.status_code == 200 and r.json()["started"] is False and "refused 09:00–15:30" in r.json()["detail"]
    assert len(seen) == 2
    r = client.post("/api/scheduler/icici-refresh", headers={"host": "localhost:8008"})   # a plain check is fine then
    assert r.json()["started"] is True and len(seen) == 3
    assert mc.force_refusal(at(2026, 10, 24, 11, 0)) is None, "Saturday: no session to end"


def test_cross_site_force_is_still_refused_by_the_guard(api):
    client, seen = api
    for url in ("/api/scheduler/icici-refresh?force=1", "/api/scheduler/icici-refresh"):
        r = client.post(url, headers={"origin": "https://evil.example"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "unauthorized"
        r = client.post(url, headers={"sec-fetch-site": "cross-site"})
        assert r.status_code == 403
    assert seen == []


def test_force_while_a_login_runs_is_not_started(api):
    client, seen = api

    async def scenario() -> dict:
        async with mc._get_lock("icici_session_refresh"):
            return client.post("/api/scheduler/icici-refresh?force=1", headers={"host": "localhost:8008"}).json()
    body = asyncio.run(scenario())
    assert body == {"started": False, "force": True, "detail": "already running"} and seen == []


# ── Telegram /status and the freshness alert ───────────────────────────────────────────────────────────────

def test_gold_freshness_line():
    today = date(2026, 10, 26)
    tables = {"nse_bhavcopy": {"last": "2026-10-23"}, "gold_cot": {"last": "2026-10-20"}, "gold_cme_daily_voi": {"last": "2026-10-23"},
              "gold_curve": {"last": "2026-10-16"}, "gold_daily_bars": {"last": None}, "gold_etf_holdings": {"last": "2026-10-23"}}
    assert mc.gold_freshness_line(tables, today) == \
        "Gold through: COT 20 Oct · COMEX OI 23 Oct · MCX curve 16 Oct ⚠ STALE (10 d) · bars — · ETF 23 Oct"
    assert mc.gold_freshness_line({"gold_cot": {"last": "2026-10-13"}}, today) == "Gold through: COT 13 Oct ⚠ STALE (13 d)"
    assert mc.gold_freshness_line({"gold_cot": {"last": "2026-10-17"}}, today) == "Gold through: COT 17 Oct"   # 9 days: weekly + holiday
    assert mc.gold_freshness_line({"nse_bhavcopy": {"last": "2026-10-23"}}, today) == \
        "Gold data: not ingested yet (data-service has no gold tables)"


def test_bot_status_carries_the_gold_line(monkeypatch):
    def healthy(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/ready":
            return httpx.Response(200, json={"status": "ready", "ui": "ok", "ui_build_id": "b1"})
        if path == "/api/positions/open-positions":
            return httpx.Response(200, json={"connected": True})
        if path == "/api/config/setup-status":
            return httpx.Response(200, json={"checks": []})
        if path == "/db/nse-positions-meta":
            return httpx.Response(200, json={"nse_bhavcopy": {"last": "2026-10-23"}, "gold_cot": {"last": "2026-10-20"},
                                             "gold_curve": {"last": "2026-10-24"}})
        return httpx.Response(404)
    real = httpx.AsyncClient
    monkeypatch.setattr(mc.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(healthy), timeout=k.get("timeout")))
    monkeypatch.setattr(mc, "DATA_SVC", "http://127.0.0.1:8001")
    monkeypatch.setattr(mc, "UI_API", "http://127.0.0.1:8010")
    monkeypatch.setattr(mc, "scheduler", _FakeScheduler())
    monkeypatch.setattr(mc.tgbot, "otp_pending", lambda: False)
    monkeypatch.setattr(mc, "_mac_lines", list)
    monkeypatch.setattr(mc, "_login_task", None)
    fake_clock(monkeypatch, at(2026, 10, 26, 10, 0))
    reply = asyncio.run(mc._bot_status([]))
    assert "Data through: bhavcopy 2026-10-23" in reply and "Gold through: COT 20 Oct · MCX curve 24 Oct" in reply


def _health(rows: list[dict]) -> dict:
    return {"as_of": "2026-10-26T08:30:00+05:30", "rows": rows, "last_session": "2026-10-23",
            "summary": {"green": 0, "amber": 0, "red": len(rows), "gaps": 0, "rows": len(rows)}}


def test_freshness_alert_names_gold_and_nse_rows(ctl, svc, monkeypatch):
    """Terminal v2 1.4: the check reads ui-api's /api/data/health (expected_by + max_age sessions, B3's classification)
    instead of the retired flat DATASET_MAX_AGE_DAYS; only red rows alert, with the dictionary each row names."""
    fake_clock(monkeypatch, at(2026, 10, 26, 8, 30))
    gold_red = {"id": "gold_cot", "state": "red", "note": "stored 13 Oct · expected by 07:00 Sat · 9 sessions behind",
                "dictionary_anchor": "GOLD_DATA_DICTIONARY.md#cot"}
    nse_red = {"id": "nse_bhavcopy", "state": "red", "note": "stored 13 Oct · expected by 19:00 · 9 sessions behind",
               "dictionary_anchor": "NSE_DATA_DICTIONARY.md#bhavcopy"}
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health([gold_red])
    stale = asyncio.run(mc._check_dataset_freshness("pre_market_sync"))
    assert stale == ["gold_cot: stored 13 Oct · expected by 07:00 Sat · 9 sessions behind"]
    assert ctl["alerts"].sent[-1][:2] == ("critical", "Gold data feed stale") and "docs/GOLD_DATA_DICTIONARY.md" in ctl["alerts"].sent[-1][2]
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health([gold_red, nse_red])
    asyncio.run(mc._check_dataset_freshness("pre_market_sync"))
    assert ctl["alerts"].sent[-1][1] == "Data feed stale"
    assert "docs/GOLD_DATA_DICTIONARY.md, docs/NSE_DATA_DICTIONARY.md" in ctl["alerts"].sent[-1][2]
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health([nse_red])
    asyncio.run(mc._check_dataset_freshness("pre_market_sync"))
    assert ctl["alerts"].sent[-1][1] == "NSE data feed stale" and "GOLD" not in ctl["alerts"].sent[-1][2]
    # negative controls: amber (due, within max_age) and gap (explicit, unrecoverable) rows never alert as "stale";
    # a view that is not served (ui-api without B3) is a log line, no alert, no error
    n_alerts = len(ctl["alerts"].sent)
    svc.routes[("GET", mc.DATA_HEALTH_API)] = _health([{"id": "nse_mtf", "state": "amber", "note": "stored 22 Oct · 1 session behind"},
                                                       {"id": "archive:preopen", "state": "gap", "note": "explicit gap row"}])
    assert asyncio.run(mc._check_dataset_freshness("pre_market_sync")) == []
    del svc.routes[("GET", mc.DATA_HEALTH_API)]
    monkeypatch.setattr(mc, "_FRESHNESS_BLIND_WARNED", {})
    assert asyncio.run(mc._check_dataset_freshness("pre_market_sync")) == []
    assert asyncio.run(mc._check_dataset_freshness("pre_market_sync")) == []        # twice: still one line a day
    assert len(ctl["alerts"].sent) == n_alerts + 1
    assert ctl["alerts"].sent[-1][:2] == ("warning", "Freshness check has no data-health view")
    assert any("/api/data/health → HTTP 404" in ln for ln in log_lines())


# ── the nightly backup already covers the gold tables ──────────────────────────────────────────────────────

def test_gold_tables_live_in_the_duckdb_the_nightly_backup_copies():
    """PLAN §c.1 puts the 19 gold tables in data/market.duckdb; scripts/db_backup.py copies that whole file (and the
    settings store), so no backup change is needed for gold."""
    assert db_backup.snap.DB == ROOT / "data" / "market.duckdb"
    assert db_backup.run.__defaults__[0] == db_backup.snap.DB


def test_quiet_track_records_the_run_without_a_log_line(ctl):
    async def run() -> None:
        async with mc._track("five_minute_job", quiet=True):
            pass
        async with mc._track("daily_job"):
            pass
    asyncio.run(run())
    assert mc._latency.stats()["five_minute_job"]["last_status"] == "done"
    assert [ln for ln in log_lines() if "Finished" in ln] == ["Finished in " + log_lines()[-1].split("Finished in ")[1]]
    assert json.loads(mc._log.tail(1)[0])["job"] == "daily_job"
