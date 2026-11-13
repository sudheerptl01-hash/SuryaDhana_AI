"""Job-vs-catalog watermark check (FINAL P0-2, the 5 Nov review's M33 asked server-side): after an ingest job reports
done, every catalogued dataset it claims (``dataset_catalog.ingest_job``) must stand at its *due session* — judged by
the same ``expected_by`` / trading-day logic the health view uses, so a holiday, a weekend, an early run before the
deadline or a structurally-lagged file (``expected_offset_days``) is never a failure. A dataset still ``red`` or
``gap`` after the run means the table did not move although it should have: the check's status is ``FAILED`` with
reason ``table_unmoved:<dataset>`` and one deduped escalation record per (dataset, session).

Judged cadences are ``daily`` / ``session`` / ``derived`` only (the ones with session semantics). ``weekly`` /
``monthly`` / ``quarterly`` budgets (COT reads amber every Friday by design), ``static`` constants, ``manual``
entries, ``live`` feeds and ``endpoint`` rows are reported as ``unjudged`` — never failed (the checker's rule:
datasets legitimately unchanged are not failures).

The outcome is persisted in ``terminal_ingest_state`` under ``job_check:<job_id>`` so ``/db/data-health`` can show
each row's last job verdict, and the controller turns a FAILED into its job status + one Telegram line.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from data_health import calendar, db, escalations, reads

JUDGED_CADENCES = ("daily", "session", "derived")
STATE_KEY = "job_check:{job}"


def job_rows(store: Any, job_id: str) -> list[dict[str, Any]]:
    df = db.query_df(store, "SELECT * FROM dataset_catalog WHERE ingest_job = ? ORDER BY id", [job_id])
    return db.records(df)


def _gap_days(store: Any, dataset: str) -> set[date]:
    df = db.query_df(store, "SELECT date FROM data_gaps WHERE dataset = ?", [dataset])
    return {d for d in (db.to_date(v) for v in df["date"]) if d is not None} if not df.empty else set()


def verify_job(store: Any, archive_root: Path, job_id: str, *, now: datetime | None = None,
               holidays: Iterable[date] = (), extra_sessions: Iterable[date] = (),
               before: Mapping[str, Any] | None = None, persist: bool = True) -> dict[str, Any]:
    """The check: one verdict per catalogued dataset of ``job_id``, overall ``FAILED`` when a judged dataset did not
    advance although an advance was expected.

    * With ``before`` (the caller's pre-run watermarks, ``{dataset: as_of}``): a dataset fails when a session was due
      past its prior watermark (``due_session`` beyond ``before[ds]``) and the stored as-of did not move past it —
      the exact "did not advance past the prior watermark" rule.
    * Without ``before``: a dataset fails when it stands ``red`` or ``gap`` after the run; ``amber`` (behind but
      inside the row's own lag budget, e.g. a structural T+1 file) is listed under ``behind`` and does not fail."""
    now_ist = calendar.now_ist(now)
    hol, extra = set(holidays), set(extra_sessions)
    rows = job_rows(store, job_id)
    datasets: list[dict[str, Any]] = []
    reasons: list[str] = []
    behind: list[str] = []
    judged = 0
    for row in rows:
        ds = str(row["id"])
        if row.get("freshness_kind") == "endpoint" or row.get("cadence") not in JUDGED_CADENCES:
            datasets.append({"dataset": ds, "verdict": "unjudged", "note": f"cadence {row.get('cadence')} / kind "
                             f"{row.get('freshness_kind')}: no session deadline to judge against"})
            continue
        as_of = reads.as_of_for(store, row, archive_root)
        st = reads.state_for(row, as_of, now_ist, holidays=hol, extra_sessions=extra, gap_days=_gap_days(store, ds))
        judged += 1
        rec = {"dataset": ds, "state": st["state"], "as_of": st["as_of"], "due_session": st["due_session"],
               "expected_at": st["expected_at"], "note": st["note"]}
        due = db.to_date(st["due_session"])
        unmoved = st["state"] in ("red", "gap")
        if before is not None and ds in before:
            b = db.to_date(before.get(ds))
            expected = due is not None and (b is None or b < due)          # a holiday / pre-deadline run expects nothing
            moved = as_of is not None and (b is None or as_of > b)
            unmoved = (expected and not moved) or unmoved
            rec["before"] = b.isoformat() if b else None
        if unmoved:
            rec["verdict"] = "table_unmoved"
            reasons.append(f"table_unmoved:{ds}")
            if persist:
                session = due or calendar.last_completed_session(now_ist, hol, extra)
                detail = (f"job {job_id} reported done but {ds} stands at {st['as_of'] or 'nothing stored'}"
                          f" (due session {st['due_session']}; {st['note'] or st['state']})")
                escalations.record(store, ds, "table_unmoved", session=session, detail=detail)
        elif st["state"] == "amber":
            rec["verdict"] = "behind"
            behind.append(ds)
        else:
            rec["verdict"] = "ok"
        datasets.append(rec)
    status = "FAILED" if reasons else ("ok" if judged else "no_judged_dataset")
    out = {"job": job_id, "status": status, "reasons": reasons, "behind": behind, "datasets": datasets,
           "checked_at": db.iso_utc(db.utcnow()), "note": "holiday / weekend / pre-deadline runs are never failed: "
           "the due session comes from the catalog's expected_by + trading-day calendar"}
    if persist:
        compact = {"at": out["checked_at"], "status": status, "reasons": reasons, "behind": behind}
        db.set_state(store, STATE_KEY.format(job=job_id), json.dumps(compact, separators=(",", ":")))
    return out


def last_checks(store: Any) -> dict[str, dict[str, Any]]:
    """{job_id: {at, status, reasons, behind}} of the last persisted check per job."""
    if not db.table_exists(store, "terminal_ingest_state"):
        return {}
    df = db.query_df(store, "SELECT key, value FROM terminal_ingest_state WHERE key LIKE 'job_check:%'")
    out: dict[str, dict[str, Any]] = {}
    for r in df.itertuples(index=False):
        try:
            out[str(r.key).split(":", 1)[1]] = json.loads(str(r.value))
        except (ValueError, IndexError):
            continue
    return out
