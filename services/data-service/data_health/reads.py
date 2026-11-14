"""The ``/db/data-health`` read (PLAN 1.4): one row per catalogued dataset with the stored as-of, the lag in sessions
behind the last close, the IST deadline it is measured against and the state ``fresh | amber | red | gap | unknown``.
Honest wording is the page's job; this module gives it the numbers ("stored 30 Oct · expected by 21:00 · 3 sessions
behind"). No composite score. ``endpoint`` rows (telemetry, ui-api's own stores) are ``unknown`` here and completed by
ui-api's ``/api/data/health`` (B3).
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
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
    failures, failures_since, counted_kinds = job_failures()
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
               # F12: a NUMBER only where this store can actually speak for the dataset, otherwise None (the
               # page renders a dash). Most catalogued datasets are produced by master-controller jobs that
               # never enter the durable queue, and giving those a 0 is the false confidence this column was
               # built to remove.
               "job_failures": _failures_for(row, failures, counted_kinds),
               **st}
        out_rows.append(rec)
    return {"as_of": db.iso_utc(now or db.utcnow()), "now_ist": now_ist.isoformat(), "last_session": calendar.last_completed_session(now_ist, holidays, extra_sessions).isoformat(),
            "rows": out_rows, "summary": summary, "badges": {"state": "arithmetic"},
            # the window the failure counts can speak for — without it a 0 claims more than the store knows
            "failures_since": failures_since,
            "note": "no composite score; endpoint rows are completed by ui-api"}


#: catalog `ingest_job` (a master-controller job id) -> the data-service submit kind it POSTs. F12: the two
#: namespaces are different, and the column was keyed on the wrong one. Read off the controller's own
#: dispatcher (scripts/master_controller.py, the `elif job_id == ...: add(...)` chain).
_JOB_ID_TO_KIND = {
    "results_capture_daily": "nse_results",
    "eod_data_pipeline": "daily_pipeline",
    "nse_positions_catchup": "nse_positions",
    "nse_filings_weekly": "nse_filings",
}

#: dataset id -> the submit kind that PRODUCES it, for the generic kinds. F13-01: the map above held only the
#: four pairs one review happened to name, so the datasets behind data-service's generic kinds stayed dark —
#: `nse_bhavcopy` is produced by kind "bhavcopy" (main.py:672), which is the table every equity panel on the
#: terminal reads, and its row could not light the column no matter how often the job crashed.
_DATASET_TO_KIND = {
    "nse_bhavcopy": "bhavcopy",
    "ohlcv": "refresh",
    "ml_features": "build",
    "market_index_daily": "indices",
    "iv_expiry_replay": "fo_iv:expiry_replay",
}


def _nse_files_datasets() -> tuple[str, ...]:
    """Every dataset produced by the single `nse_files` job, from the job's OWN table.

    R14-A: a crash of /jobs/ingest-nse-files records one kind — `nse_files` — for a job that writes eight
    datasets, so transcribing pairs by hand left all of them dark: the 20:30 evening pass could fail and
    index_ohlc_daily, nse_fo_volt, nse_contract_delta, nse_combined_oi, nse_participant_vol, nse_fii_stats
    and nse_mwpl_clients would every one still read as clean. Derived from TERMINAL_DATASETS rather than
    copied, so a dataset added to that job is covered the day it is added — hand-transcription is the defect
    this whole column has repeated at every level.
    """
    try:
        # EXACTLY the set the job itself validates its input against (fo_iv/api.py:179:
        # `set(nse_positions.TERMINAL_DATASET_NAMES) | {"nse_bhavcopy"}`). R15-A: taking only the first half
        # left `nse_bhavcopy` — the table every equity panel on the terminal reads — showing a positive 0
        # ("its job has not crashed") on a night the If-Modified-Since revision pass did crash. A 0 is a
        # claim; None is the absence of one, and only one of those is true when the job died.
        from nse_positions import TERMINAL_DATASET_NAMES
        return (*TERMINAL_DATASET_NAMES, "nse_bhavcopy")
    except Exception:                                          # pragma: no cover — import shape changed
        return ()


def _keys_for(row: dict[str, Any]) -> list[str]:
    """Every name this dataset's job could appear under in the job store, most specific first."""
    job = str(row.get("ingest_job") or "")
    ident = str(row.get("id") or "")
    out = [k for k in (job, _JOB_ID_TO_KIND.get(job, ""), ident, _DATASET_TO_KIND.get(ident, "")) if k]
    if ident in _nse_files_datasets():            # one job, eight datasets — see _nse_files_datasets
        out.append("nse_files")
    return list(dict.fromkeys(out))


def _failures_for(row: dict[str, Any], failures: dict[str, int], counted: set) -> int | None:
    """The crash count for this dataset, or None when the job store holds no record of its job at all.

    None is the honest answer for a dataset whose job never enters the durable queue — which is most of them,
    because the master-controller runs its own schedule and only some steps submit to data-service. A 0 there
    would say "this job has not crashed" when what is true is "this store has never seen this job".
    """
    # F13-01: resolve EVERY key against the failures first, then fall back to "known but clean". Checking
    # them in one pass per key meant the first key the store merely knew about short-circuited to 0 and hid a
    # crash recorded under a later alias.
    keys = _keys_for(row)
    for key in keys:
        if key in failures:
            return failures[key]
    for key in keys:
        if key in counted:
            return 0                                    # the store knows this job and it has not crashed
    return None


def job_failures(db_path: Path | None = None) -> tuple[dict[str, int], str | None, set]:
    """``({job_id: failures}, oldest_row_iso)`` from the durable job store.

    A failure is `status = 'error'` OR a row requeued after a crash — `resume_on_start` rewrites a job killed
    mid-run (which every restart does) back to 'queued', so 'error' alone misses the status a crash actually
    produces. The second element is the oldest row the store still holds: the counts cannot speak for anything
    before it, and a page that renders 0 without saying so is making a claim the data does not support.
    """
    import sqlite3

    if db_path is None:
        # F12: the same path the queue itself uses — it was hardcoded here, so under either documented
        # override (JOB_QUEUE_DB, or a DuckDB outside the repo) this read silently found nothing and every
        # row printed a confident zero.
        try:
            from shared.config import get_settings

            from job_queue import default_db_path
            db_path = default_db_path(Path(get_settings().duckdb_path).parent)
        except Exception:                                      # pragma: no cover — import shape changed
            db_path = Path(__file__).resolve().parents[3] / "data" / "job_queue.sqlite"
    path = db_path
    if not path.exists():
        return {}, None, set()
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:                                      # pragma: no cover — a locked or missing store
        return {}, None, set()
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
        # every job kind the store has seen, so a dataset it knows can report 0 while one it has never
        # seen reports nothing at all
        counted: set = set()
        for (kind,) in con.execute("SELECT DISTINCT kind FROM jobs"):
            k = str(kind)
            counted.add(k)
            if ":" in k:
                counted.add(k.split(":", 1)[1])
        # F12: the window is when FAILURE RETENTION began, not the oldest row held. Before KEEP_ERRORS went
        # live (the 14 Nov 12:15 data-service restart) `_trim` pruned failures together with successes, so the
        # store cannot speak for anything earlier — the proof is that the 13 Nov nse_results TypeError this
        # column was built for is no longer in it, while 84 same-day successes survive. Claiming the older
        # date flatters the column in exactly the direction that matters.
        floor = _retention_floor(path)
        oldest = con.execute("SELECT MIN(submitted_at) FROM jobs").fetchone()[0]
        # compared as INSTANTS, not strings: the rows are offset-aware UTC and the floor is offset-aware IST,
        # so a lexical max would pick whichever text sorted higher rather than whichever moment came later
        since = _later_iso(str(oldest) if oldest else None, floor)
        return counts, since, counted
    except sqlite3.Error:                                      # pragma: no cover
        return {}, None, set()
    finally:
        con.close()


def _later_iso(a: str | None, b: str | None) -> str | None:
    """The later of two ISO timestamps, compared as moments even when their offsets differ."""
    if not a:
        return b
    if not b:
        return a
    try:
        return a if datetime.fromisoformat(a) >= datetime.fromisoformat(b) else b
    except (ValueError, TypeError):
        # R14-C: TypeError, not just ValueError — comparing a NAIVE datetime with an aware one raises
        # TypeError, and that is precisely the case this function exists to handle (a mark file written by
        # the previous, naive code beside offset-aware job rows). `health()` calls job_failures() unguarded,
        # so the uncaught version would have taken the whole 69-row DATA payload down on the one upgrade
        # path it was written for.
        return b


#: when failure retention began — the first data-service start carrying KEEP_ERRORS. Recorded beside the store
#: on first read so the window survives restarts and is never earlier than the truth.
_RETENTION_MARK = "job_failure_retention_since"


def _retention_floor(store_path: Path) -> str | None:
    """The ISO timestamp from which this store has been keeping failures, created on first read."""
    mark = store_path.with_name(".job_failure_retention")
    try:
        if mark.exists():
            return mark.read_text(encoding="utf-8").strip() or None
        # F13-02: IST, offset-suffixed. `db.utcnow()` is NAIVE, and the page rendered it raw beside times that
        # are all IST — so "crash counting began 2026-11-14 07:17" read as 07:17 in the morning when counting
        # actually began at 12:47 IST. A 5.5 h over-claim, covering the whole morning including the 08:45
        # snapshot: the same defect F12 found in the previous floor, re-expressed in the fix written for it.
        now = datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec="seconds")
        mark.write_text(now, encoding="utf-8")
        return now
    except OSError:                                            # pragma: no cover — read-only volume
        return None


def catalog(store: Any) -> dict[str, Any]:
    rows = db.records(db.query_df(store, "SELECT * FROM dataset_catalog ORDER BY id"))
    return {"rows": rows, "count": len(rows)}
