"""G11 (Terminal v2 PLAN 1.7) additions. B2's ``test_terminal_v2_controller.py`` covers missed_jobs(), the 22:45 / 08:35
passes, the iv_intraday skips (no session, past the budget, outside 09:20–15:30) and the terminal freeze rule; this file
checks the controller's registries against its own schedule, statically, so a future edit cannot drift silently:

* every Wave-1 terminal job is either replayed after downtime (``TERMINAL_TODAY_SLOTS`` / the Saturday ``iv_weekly``
  rule) or named in ``NOT_REPLAYED`` with the reason, and every replay slot equals the job's real CronTrigger time;
* every job that fires inside a freeze window (07:45–09:20 / 18:30–21:15 IST) is in ``KNOWN_IN_WINDOW`` (the pre-v2
  schedule, or a v2 job of the light class) — a NEW job scheduled inside a window fails; the non-light gold jobs fire
  outside both windows; the windows themselves are unchanged.

The schedule is read from ``scripts/master_controller.py`` with ``ast`` (CronTrigger literals) and expanded with
APScheduler over two weeks; the controller module is imported only for its constants (no lifespan, no scheduler)."""
from __future__ import annotations

import ast
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytz
from apscheduler.triggers.cron import CronTrigger

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")
SRC = (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
WAVE1_JOBS = ("index_drivers_daily", "nse_evening_pass", "morning_sweep", "iv_intraday", "iv_weekly", "data_health_check")
NOT_REPLAYED = {
    "iv_intraday": "a session-bound 15-min live poll: a missed tick cannot be fetched later; the EOD file is the record",
    "data_health_check": "hourly: the next run reads the same view",
}
#: jobs that fire inside a freeze window today, and why that is allowed (freeze windows forbid restarts, not light work)
KNOWN_IN_WINDOW: dict[str, str] = {
    "eod_data_pipeline": "the 18:30 EOD pipeline IS the evening window's work",
    "shared_snapshot_build": "19:20 read-only snapshot after the pipeline",
    "index_valuation_daily": "19:15 stored-data job of the evening pass",
    "desk_daily": "19:30 Decision Desk (stored data)",
    "news_track_record_daily": "19:45 stored data",
    "alpha_shadow_daily": "19:50 S1 shadow (stored data)",
    "nse_positions_catchup": "20:30 evening files pass (the F&O files land by 20:10)",
    "results_capture_daily": "20:45 results release times",
    "daily_wrap": "21:00 wrap from stored data",
    "weekly_journal": "Fri 20:10 report",
    "icici_session_refresh": "08:00 ICICI login (the reason the morning window exists)",
    "preopen_capture": "09:09 pre-open capture (session-bound)",
    "internals_sample": "market internals sampler (session-bound)",
    "gold_preopen_snapshot": "08:45 gold pre-open snapshot (exists since the gold program)",
    "gold_open_capture": "09:10 gold open capture (session-bound)",
    "morning_note": "08:50 Telegram note",
    "filing_alerts": "alerts read stored filings",
    "move_alerts": "alerts read live quotes",
    "price_alerts_check": "alerts read live quotes",
    "nse_filings_weekly": "Sat 09:00 (weekend: no ICICI login, no pre-open)",
    "pre_market_sync": "dormant legacy 5-day pipeline",
    "intraday_inference": "dormant legacy 5-day pipeline",
    # Wave 1, the light class by the plan's own words (B2 test_no_terminal_job_fires_inside_a_freeze_window_…)
    "index_drivers_daily": "v2 light: 19:25 stored data + 3 small GETs",
    "morning_sweep": "v2 light: 08:35 ≤ 6 small GET-only fetches",
    "data_health_check": "v2 light: one local GET an hour",
    "iv_intraday": "v2: the 09:05 cron tick is refused by iv_intraday_due before any request",
}


def cron_jobs(src: str) -> dict[str, dict[str, Any]]:
    """``add_job(..., trigger=CronTrigger(<literals>), id="x")`` → {id: CronTrigger kwargs} (timezone dropped)."""
    out: dict[str, dict[str, Any]] = {}
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_job"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        jid, trig = kw.get("id"), kw.get("trigger")
        cron = isinstance(trig, ast.Call) and isinstance(trig.func, ast.Name) and trig.func.id == "CronTrigger"
        if isinstance(jid, ast.Constant) and cron and isinstance(trig, ast.Call):
            out[str(jid.value)] = {k.arg: k.value.value for k in trig.keywords
                                   if k.arg is not None and k.arg != "timezone" and isinstance(k.value, ast.Constant)}
    return out


def fires(kwargs: dict[str, Any], days: int = 14) -> list[datetime]:
    trig = CronTrigger(timezone=IST, **kwargs)
    t = IST.localize(datetime(2026, 11, 2, 0, 0))  # noqa: DTZ001 — pytz: localize, never tzinfo=
    end, prev = t + timedelta(days=days), None
    out: list[datetime] = []
    while True:
        n = trig.get_next_fire_time(prev, t)
        if n is None or n > end:
            return out
        out.append(n)
        prev, t = n, n + timedelta(seconds=1)


def in_window(when: datetime) -> bool:
    hm = when.time().replace(second=0, microsecond=0)
    return any(a <= hm <= b for a, b in mc.FREEZE_WINDOWS)


def window_jobs(jobs: dict[str, dict[str, Any]]) -> set[str]:
    return {jid for jid, kw in jobs.items() if any(in_window(f) for f in fires(kw))}


def slot_mismatches(jobs: dict[str, dict[str, Any]], slots: dict[str, tuple[tuple[int, ...], time]]) -> list[str]:
    """Replay slots that disagree with the real CronTrigger (hour:minute on every weekday the slot claims)."""
    out = []
    for jid, (days, slot) in slots.items():
        if jid not in jobs:
            out.append(f"{jid}: no CronTrigger")
            continue
        times = {(f.weekday(), f.time().replace(second=0)) for f in fires(jobs[jid])}
        missing = [d for d in days if (d, slot) not in times]
        if missing:
            out.append(f"{jid}: slot {slot} on weekdays {missing} is not a fire time")
    return out


def test_every_terminal_job_is_replayed_or_says_why_not():
    jobs = cron_jobs(SRC)
    assert set(WAVE1_JOBS) <= set(jobs), set(WAVE1_JOBS) - set(jobs)
    replayed = set(mc.TERMINAL_TODAY_SLOTS) | {"iv_weekly"}
    silent = [j for j in WAVE1_JOBS if j not in replayed and j not in NOT_REPLAYED]
    assert not silent, f"terminal jobs neither replayed after downtime nor explained: {silent}"
    assert not (set(NOT_REPLAYED) & replayed), "a job cannot be both replayed and 'not replayed'"
    assert slot_mismatches(jobs, mc.TERMINAL_TODAY_SLOTS) == []
    assert mc.IV_WEEKLY_SLOT == time(3, 0) and {(f.weekday(), f.time()) for f in fires(jobs["iv_weekly"])} == {(5, time(3, 0))}


def test_negative_controls_a_drifted_slot_and_an_unexplained_job():
    jobs = cron_jobs(SRC)
    drift = {**mc.TERMINAL_TODAY_SLOTS, "index_drivers_daily": ((0, 1, 2, 3, 4), time(19, 35))}
    assert slot_mismatches(jobs, drift) == ["index_drivers_daily: slot 19:35:00 on weekdays [0, 1, 2, 3, 4] is not a fire time"]
    weekend = {"index_drivers_daily": ((5,), time(19, 25))}
    assert slot_mismatches(jobs, weekend)[0].startswith("index_drivers_daily: slot 19:25:00 on weekdays [5]")
    assert slot_mismatches({}, {"x": ((0,), time(1, 0))}) == ["x: no CronTrigger"]


def test_no_heavy_job_fires_inside_a_freeze_window():
    assert mc.FREEZE_WINDOWS == ((time(7, 45), time(9, 20)), (time(18, 30), time(21, 15))), "the windows are unchanged"
    jobs = cron_jobs(SRC)
    inside = window_jobs(jobs)
    new = sorted(inside - set(KNOWN_IN_WINDOW))
    assert not new, f"job(s) newly scheduled inside a freeze window: {new}"
    stale = sorted(j for j in KNOWN_IN_WINDOW if j not in inside)
    assert not stale, f"prune KNOWN_IN_WINDOW (no longer inside a window): {stale}"
    # the gold jobs: only the light class may fire inside a window (gold PLAN §c.3)
    heavy_gold = [jid for jid, spec in mc.GOLD_JOBS.items()
                  if not spec.light and any(in_window(f) for c in spec.crons for f in fires(c))]
    assert heavy_gold == [], heavy_gold
    # iv_intraday's 09:05 tick is inside the morning window: the gate refuses it before any request
    assert not mc.iv_intraday_due(IST.localize(datetime(2026, 11, 4, 9, 5)))  # noqa: DTZ001
    assert mc.iv_intraday_due(IST.localize(datetime(2026, 11, 4, 9, 20)))  # noqa: DTZ001


def test_negative_control_a_new_job_inside_the_morning_window_is_caught():
    src = 'scheduler.add_job(f, trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=15, timezone=IST), id="brand_new")\n' \
          'scheduler.add_job(g, trigger=CronTrigger(hour=22, minute=0, timezone=IST), id="late_ok")\n'
    jobs = cron_jobs(src)
    assert jobs == {"brand_new": {"day_of_week": "mon-fri", "hour": 8, "minute": 15}, "late_ok": {"hour": 22, "minute": 0}}
    assert window_jobs(jobs) - set(KNOWN_IN_WINDOW) == {"brand_new"}
