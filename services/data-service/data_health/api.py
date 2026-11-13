"""FastAPI router for data health: ``POST /jobs/data-health?job=data_health_refresh`` (seed the catalog, sync the gold
pre-open log into its table, write the gap rows for the sessions since ``since`` and clear the recovered ones),
``job=job_watermark_check`` (FINAL P0-2: the table-unmoved verdict for one ingest job), ``job=escalations_scan``
(P0-2/P0-3: red-row ageing + the intraday tape gap, deduped per dataset per day), ``GET /db/data-health``,
``/db/data-health/catalog``, ``/db/data-health/ingest-log``, ``/db/data-health/gaps``, ``/db/data-health/escalations``.
``configure`` is called by data-service ``main.py`` with its ``get_store`` / ``_submit`` and a holidays provider so this
module owns no global store. Additive; nothing existing changes.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from data_health import calendar, catalog, db, escalations, gaps, ingest_log, reads, watermarks

router = APIRouter(tags=["data-health"])

_get_store: Callable[[], Any] | None = None
_submit: Callable[..., dict[str, Any]] | None = None
_archive_root: Callable[[], Path] | None = None
_holidays: Callable[[], set[date]] | None = None

JOB_IDS = ("data_health_refresh", "job_watermark_check", "escalations_scan")


def configure(*, get_store: Callable[[], Any], submit: Callable[..., dict[str, Any]], archive_root: Callable[[], Path],
              holidays: Callable[[], set[date]] | None = None) -> None:
    global _get_store, _submit, _archive_root, _holidays
    _get_store, _submit, _archive_root, _holidays = get_store, submit, archive_root, holidays


def _store() -> Any:
    if _get_store is None:
        raise HTTPException(status_code=503, detail="data_health package not configured")
    return _get_store()


def _root() -> Path:
    if _archive_root is None:
        raise HTTPException(status_code=503, detail="data_health package not configured")
    return _archive_root()


def holidays() -> set[date]:
    if _holidays is None:
        return set()
    try:
        return set(_holidays())
    except Exception:  # noqa: BLE001 — the holiday master is a convenience; weekdays-only is the fallback
        return set()


class DataHealthJobRequest(BaseModel):
    job: str | None = None
    since: date | None = None
    sessions: int = Field(default=10, ge=1, le=120)
    reason: str = "stack down (no capture)"
    datasets: list[str] = Field(default_factory=list)
    ingest_job: str | None = Field(default=None, max_length=64)
    before: dict[str, str | None] | None = None        # pre-run watermarks {dataset: as_of} for the exact unmoved rule
    preopen_log_path: str | None = Field(default=None, max_length=512)


def _sync_gold_preopen(store: Any, path: str | None) -> dict[str, Any] | None:
    """P0-11: keep the table the catalog watches complete from the accuracy log's file store (missing days only; the
    gold package may be absent on a stripped deployment — then this is a no-op, said in the result)."""
    try:
        from gold import ingest_local
    except ImportError:
        return None
    try:
        return ingest_local.sync_preopen_log(store, path)
    except Exception as exc:  # noqa: BLE001 — the sync is a safety net; its failure never blocks the gap scan
        return {"inserted": 0, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def refresh(store: Any, archive_root: Path, *, since: date | None, sessions: int, reason: str, datasets: list[str] | None,
            hol: set[date], preopen_log_path: str | None = None) -> dict[str, Any]:
    n = catalog.seed(store)
    preopen = _sync_gold_preopen(store, preopen_log_path)
    now_ist = calendar.now_ist()
    last = calendar.last_completed_session(now_ist, hol)
    start = since or (last - timedelta(days=int(sessions * 1.6) + 3))
    found = gaps.detect_session_gaps(store, archive_root, start, last, holidays=hol, reason=reason, datasets=datasets or None)
    recovered = gaps.clear_recovered(store, archive_root)
    return {"catalog_rows": n, "gold_preopen_sync": preopen, "gap_scan": {"from": start.isoformat(), "to": last.isoformat(), "gaps": found},
            "gaps_recovered": recovered, "summary": reads.health(store, archive_root, holidays=hol)["summary"]}


@router.post("/jobs/data-health")
def data_health_job(req: DataHealthJobRequest | None = None, job: str | None = Query(None),
                    ingest_job: str | None = Query(None, max_length=64)) -> dict[str, Any]:
    body = req or DataHealthJobRequest()
    job_id = job or body.job or "data_health_refresh"
    if job_id not in JOB_IDS:
        raise HTTPException(status_code=422, detail=f"unknown job {job_id!r}; known: {list(JOB_IDS)}")
    store, root, hol = _store(), _root(), holidays()
    if _submit is None:
        raise HTTPException(status_code=503, detail="data_health package not configured")

    read_only = bool(getattr(store, "_read_only", False))
    if job_id == "job_watermark_check":
        target = ingest_job or body.ingest_job
        if not target:
            raise HTTPException(status_code=422, detail="job_watermark_check needs ingest_job=<the job that just ran>")
        # synchronous on purpose: the controller wants the verdict in the response, and the check is a few reads
        return watermarks.verify_job(store, root, target, holidays=hol, before=body.before, persist=not read_only)

    if job_id == "escalations_scan":
        if read_only:
            raise HTTPException(status_code=503, detail="DuckDB is read-only — escalation records cannot be written")
        # gap hygiene rides the hourly scan (P0-11): sync the pre-open accuracy log into its table and clear the
        # gap rows whose capture exists now, BEFORE judging — a false gap must never age into an escalation
        preopen = _sync_gold_preopen(store, body.preopen_log_path)
        recovered = gaps.clear_recovered(store, root)
        return {**escalations.scan(store, root, holidays=hol), "gold_preopen_sync": preopen, "gaps_recovered": recovered}

    def _run(progress: Callable[[int, int], None]) -> dict[str, Any]:
        out = refresh(store, root, since=body.since, sessions=body.sessions, reason=body.reason, datasets=body.datasets,
                      hol=hol, preopen_log_path=body.preopen_log_path)
        progress(1, 1)
        return out

    return _submit(f"data_health:{job_id}", _run)


@router.get("/db/data-health")
def data_health() -> dict[str, Any]:
    return reads.health(_store(), _root(), holidays=holidays())


@router.get("/db/data-health/catalog")
def data_health_catalog() -> dict[str, Any]:
    return reads.catalog(_store())


@router.get("/db/data-health/ingest-log")
def data_health_ingest_log(days: int = Query(7, ge=1, le=365), dataset: str | None = Query(None, max_length=64),
                           limit: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
    rows = ingest_log.recent(_store(), days=days, dataset=dataset, limit=limit)
    return {"rows": rows, "count": len(rows), "as_of": db.iso_utc(db.utcnow())}


@router.get("/db/data-health/escalations")
def data_health_escalations(since: str | None = Query(None), kind: str | None = Query(None, max_length=32)) -> dict[str, Any]:
    s = date.fromisoformat(since[:10]) if since else None
    rows = escalations.list_escalations(_store(), since=s, kind=kind)
    return {"rows": rows, "count": len(rows), "as_of": db.iso_utc(db.utcnow())}


@router.get("/db/data-health/gaps")
def data_health_gaps(since: str | None = Query(None), dataset: str | None = Query(None, max_length=64)) -> dict[str, Any]:
    s = date.fromisoformat(since[:10]) if since else None
    rows = gaps.gaps(_store(), since=s, dataset=dataset)
    return {"rows": rows, "count": len(rows)}
