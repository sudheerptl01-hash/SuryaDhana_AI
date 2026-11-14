"""The ``/db/data-health`` read (PLAN 1.4): one row per catalogued dataset with the stored as-of, the lag in sessions
behind the last close, the IST deadline it is measured against and the state ``fresh | amber | red | gap | unknown``.
Honest wording is the page's job; this module gives it the numbers ("stored 30 Oct · expected by 21:00 · 3 sessions
behind"). No composite score. ``endpoint`` rows (telemetry, ui-api's own stores) are ``unknown`` here and completed by
ui-api's ``/api/data/health`` (B3).
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_health import calendar, db, gaps, ingest_log
from data_health.calendar import IST

STATES = ("fresh", "amber", "red", "gap", "unknown")


def _table_as_of(store: Any, table: str, column: str, where: str | None) -> date | None:
    if not db.table_exists(store, table):
        return None
    try:
        v = db.max_of(store, table, column, where or "")
    except Exception:  # noqa: BLE001 — a column that does not exist on an older schema
        return None
    if v is None:
        return None
    if isinstance(v, (datetime, pd.Timestamp)) and column in ("first_seen_at", "fetched_at", "ts", "first_seen"):
        return pd.Timestamp(v).tz_localize("UTC").tz_convert(IST).date()     # UTC-naive store timestamp → IST calendar day
    return db.to_date(v)


def _archive_as_of(root: Path, folder: str) -> date | None:
    days = gaps.archive_days(root, folder)
    return max(days) if days else None


def _file_as_of(root: Path, rel: str, column: str | None) -> date | None:
    p = root / rel
    if not p.exists():
        return None
    try:
        if column == "csv:date":
            s = pd.read_csv(p, usecols=["date"])["date"]
            return db.to_date(s.max())
        if column == "json:date":
            payload = json.loads(p.read_text(encoding="utf-8"))
            dates = [r.get("date") for rows in payload.values() for r in rows] if isinstance(payload, dict) else []
            return db.to_date(max(d for d in dates if d)) if any(dates) else None
        return datetime.fromtimestamp(p.stat().st_mtime, tz=IST).date()
    except Exception:  # noqa: BLE001 — an unreadable derived file is "unknown", not a crash
        return None


def as_of_for(store: Any, row: dict[str, Any], archive_root: Path) -> date | None:
    kind = row["freshness_kind"]
    if kind == "table":
        return _table_as_of(store, str(row["table_name"]), str(row["freshness_column"]), row.get("freshness_where"))
    if kind == "archive":
        return _archive_as_of(archive_root, str(row["table_name"]))
    if kind == "file":
        return _file_as_of(archive_root, str(row["table_name"]), row.get("freshness_column"))
    return None


def due_session(now_ist: datetime, last_session: date, expected_by: str | None, offset: int,
                holidays: Iterable[date] = (), extra: Iterable[date] = ()) -> tuple[date | None, datetime | None]:
    """The latest session S whose deadline (expected_by on S + offset trading days) has passed, and that deadline."""
    if not expected_by:
        return None, None
    s = last_session
    for _ in range(12):
        dl = calendar.deadline_for(s, expected_by, offset, holidays, extra)
        if dl is None:
            return None, None
        if dl <= now_ist:
            return s, dl
        s = calendar.prev_trading_day(s, holidays, extra)
    return None, None


def state_for(row: dict[str, Any], as_of: date | None, now_ist: datetime, *, holidays: Iterable[date] = (),
              extra_sessions: Iterable[date] = (), gap_days: Iterable[date] = ()) -> dict[str, Any]:
    """The RAG state of one catalog row given its stored as-of (pure; tested with negative controls)."""
    hol, extra = set(holidays), set(extra_sessions)
    cadence = row["cadence"]
    kind = row["freshness_kind"]
    last = calendar.last_completed_session(now_ist, hol, extra)
    out: dict[str, Any] = {"as_of": as_of.isoformat() if as_of else None, "last_session": last.isoformat(), "lag_sessions": None,
                           "due_session": None, "expected_at": None, "state": "unknown", "note": None}
    if kind == "endpoint" or cadence == "live":
        out["note"] = "composed by ui-api (telemetry / live feed)"
        return out
    if as_of is not None:
        out["lag_sessions"] = max(0, calendar.sessions_between(as_of, last, hol, extra))
    if cadence in ("daily", "session", "derived"):
        s, dl = due_session(now_ist, last, row.get("expected_by"), int(row.get("expected_offset_days") or 0), hol, extra)
        out["due_session"] = s.isoformat() if s else None
        out["expected_at"] = dl.isoformat() if dl else None
        if s is not None and s in set(gap_days) and (as_of is None or as_of < s):
            out["state"] = "gap"
            out["note"] = "no capture for the session (gap row)"
            return out
        if as_of is None:
            out["state"] = "red"
            out["note"] = "nothing stored"
            return out
        if s is None:                                    # no deadline known: judge on the lag alone
            out["state"] = "fresh" if out["lag_sessions"] == 0 else ("amber" if out["lag_sessions"] <= int(row["max_age_sessions"]) else "red")
            return out
        behind = max(0, calendar.sessions_between(as_of, s, hol, extra))
        if behind == 0:
            out["state"] = "fresh"
            if out["lag_sessions"]:
                out["note"] = f"due by {dl.strftime('%H:%M') if dl else row.get('expected_by')} IST for the last session"
        elif behind <= int(row["max_age_sessions"]):
            out["state"] = "amber"
            out["note"] = f"{behind} session(s) behind the expected one"
        else:
            out["state"] = "red"
            out["note"] = f"{behind} session(s) behind the expected one"
        return out
    # weekly / monthly / quarterly / static / manual: calendar-day age against the budget
    if as_of is None:
        out["state"] = "red"
        out["note"] = "nothing stored"
        return out
    age = (now_ist.date() - as_of).days
    if cadence == "static":
        # a dated constant (the 6.5 % rate_curve, O-T5) holds until a new dated row replaces it: its effective date is not
        # an age (5 Nov: the DATA page read the 2019-10-01 seed as "2592 days old", red)
        out["state"] = "fresh"
        out["note"] = f"dated constant in force since {as_of.isoformat()} (a change is a new dated row)"
        return out
    budget = int(row["max_age_sessions"])
    out["state"] = "fresh" if age <= budget else ("amber" if age <= 2 * budget else "red")
    out["note"] = f"{age} days old (budget {budget})"
    return out


def health(store: Any, archive_root: Path, *, now: datetime | None = None, holidays: Iterable[date] = (),
           extra_sessions: Iterable[date] = (), rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every catalog row with as_of / lag / state plus the newest ingest_log row per dataset and the summary counts."""
    now_ist = calendar.now_ist(now)
    cat = rows if rows is not None else db.records(db.query_df(store, "SELECT * FROM dataset_catalog ORDER BY id"))
    gap_rows = db.query_df(store, "SELECT dataset, date FROM data_gaps")
    gap_map: dict[str, set[date]] = {}
    for g in gap_rows.itertuples(index=False):
        d = db.to_date(g.date)
        if d:
            gap_map.setdefault(str(g.dataset), set()).add(d)
    last_fetch = ingest_log.last_fetch_by_dataset(store)
    from data_health import watermarks                 # local import: watermarks imports reads (cycle-safe at call time)
    job_checks = watermarks.last_checks(store)
    failures, failures_since = job_failures()
    out_rows: list[dict[str, Any]] = []
    summary = {"fresh": 0, "amber": 0, "red": 0, "gap": 0, "unknown": 0}
    for row in cat:
        as_of = as_of_for(store, row, archive_root)
        st = state_for(row, as_of, now_ist, holidays=holidays, extra_sessions=extra_sessions, gap_days=gap_map.get(str(row["id"]), ()))
        summary[st["state"]] += 1
        rec = {"id": row["id"], "label": row["label"], "pages": [p for p in str(row["pages"]).split(",") if p], "publisher": row["publisher"],
               "published_ist": row.get("publish_time_ist"), "expected_by": row.get("expected_by"), "expected_offset_days": row.get("expected_offset_days"),
               "cadence": row["cadence"], "max_age_sessions": row["max_age_sessions"], "unrecoverable": bool(row.get("unrecoverable")),
               "job_id": row.get("ingest_job"), "freshness_kind": row["freshness_kind"], "dictionary_anchor": row.get("dictionary_anchor"),
               "verdict": row["verdict"], "badge": row["badge"], "catalog_note": row.get("note"),
               "last_fetch": last_fetch.get(str(row["id"])), "gap_dates": sorted(d.isoformat() for d in gap_map.get(str(row["id"]), ())),
               "job_check": job_checks.get(str(row.get("ingest_job") or "")),
               # F11-06: the row's state is "is the DATA fresh"; this is "did the JOB that produces it crash".
               # They differ exactly when a later run papers over an earlier failure — which is what happened
               # to nse_results on 13 Nov, read as FRESH while its job had died twice.
               "job_failures": failures.get(str(row.get("ingest_job") or ""), 0),
               **st}
        out_rows.append(rec)
    return {"as_of": db.iso_utc(now or db.utcnow()), "now_ist": now_ist.isoformat(), "last_session": calendar.last_completed_session(now_ist, holidays, extra_sessions).isoformat(),
            "rows": out_rows, "summary": summary, "badges": {"state": "arithmetic"},
            # the window the failure counts can speak for — without it a 0 claims more than the store knows
            "failures_since": failures_since,
            "note": "no composite score; endpoint rows are completed by ui-api"}


def job_failures(db_path: Path | None = None) -> tuple[dict[str, int], str | None]:
    """``({job_id: failures}, oldest_row_iso)`` from the durable job store.

    A failure is `status = 'error'` OR a row requeued after a crash — `resume_on_start` rewrites a job killed
    mid-run (which every restart does) back to 'queued', so 'error' alone misses the status a crash actually
    produces. The second element is the oldest row the store still holds: the counts cannot speak for anything
    before it, and a page that renders 0 without saying so is making a claim the data does not support.
    """
    import sqlite3

    path = db_path or (Path(__file__).resolve().parents[3] / "data" / "job_queue.sqlite")
    if not path.exists():
        return {}, None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:                                      # pragma: no cover — a locked or missing store
        return {}, None
    try:
        counts: dict[str, int] = {}
        for kind, n in con.execute(
                "SELECT kind, COUNT(*) FROM jobs WHERE status = 'error' OR (status = 'queued' AND requeued > 0)"
                " GROUP BY kind"):
            # job kinds are "<job_id>" or "<group>:<job_id>" (e.g. fo_iv:iv_repair) — count against both
            k = str(kind)
            counts[k] = counts.get(k, 0) + int(n)
            if ":" in k:
                tail = k.split(":", 1)[1]
                counts[tail] = counts.get(tail, 0) + int(n)
        oldest = con.execute("SELECT MIN(submitted_at) FROM jobs").fetchone()[0]
        return counts, (str(oldest) if oldest else None)
    except sqlite3.Error:                                      # pragma: no cover
        return {}, None
    finally:
        con.close()


def catalog(store: Any) -> dict[str, Any]:
    rows = db.records(db.query_df(store, "SELECT * FROM dataset_catalog ORDER BY id"))
    return {"rows": rows, "count": len(rows)}
