"""Silent-rot escalations (FINAL P0-2 / P0-3): deduped records the controller turns into ONE Telegram line each.

* ``record`` — one row per (dataset, session, kind); the PRIMARY KEY is the dedupe, a re-scan the same day inserts
  nothing and reports nothing new.
* ``scan_red_aging`` — a ``/db/data-health`` row that is red *and was already red the previous session* (judged from
  the per-dataset state this module keeps in ``terminal_ingest_state``) gets one ``red_aged`` record per session: the
  hourly transition line fired once when it turned red; this is the "still red a session later" escalation.
* ``tape_gap_check`` — during market hours on a trading day, the newest ``iv_intraday`` snapshot for the tier-1 names
  (NIFTY, BANKNIFTY) older than ``TAPE_GAP_MIN`` minutes writes an explicit ``data_gaps`` row (reason names the last
  snapshot time) and one ``tape_gap`` record for the day.

Everything here describes stored data; nothing fetches, nothing feeds the Desk / shadow / directional alerts.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from data_health import calendar, db, gaps, reads
from data_health.calendar import IST
from data_health.schema import CASTS, COLUMNS

KINDS = ("table_unmoved", "red_aged", "tape_gap")
TIER1: tuple[str, ...] = ("NIFTY", "BANKNIFTY")
TAPE_GAP_MIN = 10
TAPE_WINDOW = (time(9, 30), time(15, 30))        # first tick ~09:16–09:20: judge from 09:30 so the open never false-alarms
SEEN_KEY = "health_seen:{dataset}"


def record(store: Any, dataset: str, kind: str, *, session: date, detail: str, now: datetime | None = None) -> bool:
    """Insert one escalation record; False when (dataset, session, kind) already exists (the per-day dedupe)."""
    assert kind in KINDS, kind
    if db.scalar(store, "SELECT COUNT(*) FROM data_health_escalations WHERE dataset = ? AND date = ? AND kind = ?",
                 [dataset, session, kind]):
        return False
    row = {"dataset": dataset, "date": session, "kind": kind, "detail": detail[:500], "first_seen_at": now or db.utcnow()}
    db.upsert(store, "data_health_escalations", pd.DataFrame([row]), COLUMNS["data_health_escalations"],
              CASTS["data_health_escalations"])
    return True


def list_escalations(store: Any, *, since: date | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if since:
        where.append("date >= ?")
        params.append(since)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    sql = "SELECT dataset, date, kind, detail, first_seen_at FROM data_health_escalations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return db.records(db.query_df(store, sql + " ORDER BY first_seen_at DESC, dataset", params), ("date",))


def _seen(store: Any, dataset: str) -> dict[str, Any] | None:
    raw = db.get_state(store, SEEN_KEY.format(dataset=dataset))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def scan_red_aging(store: Any, archive_root: Path, *, now: datetime | None = None, holidays: Iterable[date] = (),
                   extra_sessions: Iterable[date] = (), health_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One ``red_aged`` record per dataset per session for the red rows that were already red on an earlier session.
    The first session a row turns red is the hourly transition line's business, not an escalation."""
    now_ist = calendar.now_ist(now)
    hol, extra = set(holidays), set(extra_sessions)
    last = calendar.last_completed_session(now_ist, hol, extra)
    rows = health_rows if health_rows is not None else reads.health(store, archive_root, now=now, holidays=hol,
                                                                    extra_sessions=extra)["rows"]
    new: list[dict[str, Any]] = []
    for r in rows:
        ds, state = str(r["id"]), str(r.get("state"))
        prev = _seen(store, ds)
        since = str(prev.get("since") or prev.get("session")) if prev and prev.get("state") == "red" else last.isoformat()
        if state == "red" and prev and prev.get("state") == "red" and str(prev.get("session", "")) < last.isoformat():
            detail = f"{ds} red since {since} ({r.get('note') or 'behind'}); still red at {last.isoformat()}"
            if record(store, ds, "red_aged", session=last, detail=detail, now=now):
                new.append({"dataset": ds, "kind": "red_aged", "date": last.isoformat(), "detail": detail})
        db.set_state(store, SEEN_KEY.format(dataset=ds),
                     json.dumps({"state": state, "session": last.isoformat(), "since": since if state == "red" else None},
                                separators=(",", ":")), now=now)
    return new


def _ist_midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None)


def tape_gap_check(store: Any, *, now: datetime | None = None, holidays: Iterable[date] = (),
                   extra_sessions: Iterable[date] = (), threshold_min: int = TAPE_GAP_MIN,
                   symbols: Iterable[str] = TIER1) -> list[dict[str, Any]]:
    """During market hours: the newest stored ``iv_intraday`` snapshot per tier-1 name older than ``threshold_min``
    (or missing for the day) → one ``data_gaps`` row (reason carries the last snapshot time, IST) and one deduped
    ``tape_gap`` escalation for the day. Outside the window, on a holiday or without the table it reports nothing."""
    now_ist = calendar.now_ist(now)
    today = now_ist.date()
    if not calendar.is_trading_day(today, set(holidays), set(extra_sessions)):
        return []
    if not (TAPE_WINDOW[0] <= now_ist.time() <= TAPE_WINDOW[1]):
        return []
    if not db.table_exists(store, "iv_intraday"):
        return []
    now_utc = now or db.utcnow()
    day_start = _ist_midnight_utc(today)
    stale: list[str] = []
    for sym in symbols:
        newest = db.scalar(store, "SELECT MAX(ts) FROM iv_intraday WHERE symbol = ? AND ts >= ?", [sym, day_start])
        ts = pd.Timestamp(newest).to_pydatetime() if newest is not None else None
        if ts is None:
            stale.append(f"{sym}: no snapshot today")
            continue
        age_min = (now_utc - ts).total_seconds() / 60.0
        if age_min > threshold_min:
            at_ist = ts.replace(tzinfo=timezone.utc).astimezone(IST).strftime("%H:%M")
            stale.append(f"{sym}: newest {at_ist} IST ({age_min:.0f} min ago)")
    if not stale:
        return []
    detail = f"intraday tape gap > {threshold_min} min in market hours — " + "; ".join(stale)
    gaps.write_gaps(store, "iv_intraday", [today], detail, unrecoverable=True, source="tape_gap_check", now=now)
    if record(store, "iv_intraday", "tape_gap", session=today, detail=detail, now=now):
        return [{"dataset": "iv_intraday", "kind": "tape_gap", "date": today.isoformat(), "detail": detail}]
    return []


def scan(store: Any, archive_root: Path, *, now: datetime | None = None, holidays: Iterable[date] = (),
         extra_sessions: Iterable[date] = ()) -> dict[str, Any]:
    """The controller's hourly call: red-row ageing + the tape gap. ``new`` carries only records this scan created
    (the per-day dedupe means a line already sent is never handed over again); ``today`` lists the full current set."""
    new = scan_red_aging(store, archive_root, now=now, holidays=holidays, extra_sessions=extra_sessions)
    new += tape_gap_check(store, now=now, holidays=holidays, extra_sessions=extra_sessions)
    today = calendar.now_ist(now).date()
    return {"new": new, "today": list_escalations(store, since=today - timedelta(days=1)),
            "as_of": db.iso_utc(now or db.utcnow())}
