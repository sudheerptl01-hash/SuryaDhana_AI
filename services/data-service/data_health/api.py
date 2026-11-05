"""FastAPI router for data health: ``POST /jobs/data-health?job=data_health_refresh`` (seed the catalog, write the gap rows
for the sessions since ``since``), ``GET /db/data-health``, ``/db/data-health/catalog``, ``/db/data-health/ingest-log``,
``/db/data-health/gaps``. ``configure`` is called by data-service ``main.py`` with its ``get_store`` / ``_submit`` and a
holidays provider so this module owns no global store. Additive; nothing existing changes.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from data_health import calendar, catalog, db, gaps, ingest_log, reads

router = APIRouter(tags=["data-health"])

_get_store: Callable[[], Any] | None = None
_submit: Callable[..., dict[str, Any]] | None = None
_archive_root: Callable[[], Path] | None = None
_holidays: Callable[[], set[date]] | None = None

JOB_IDS = ("data_health_refresh",)


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


def refresh(store: Any, archive_root: Path, *, since: date | None, sessions: int, reason: str, datasets: list[str] | None,
            hol: set[date]) -> dict[str, Any]:
    n = catalog.seed(store)
    now_ist = calendar.now_ist()
    last = calendar.last_completed_session(now_ist, hol)
    start = since or (last - timedelta(days=int(sessions * 1.6) + 3))
    found = gaps.detect_session_gaps(store, archive_root, start, last, holidays=hol, reason=reason, datasets=datasets or None)
    return {"catalog_rows": n, "gap_scan": {"from": start.isoformat(), "to": last.isoformat(), "gaps": found},
            "summary": reads.health(store, archive_root, holidays=hol)["summary"]}


@router.post("/jobs/data-health")
def data_health_job(req: DataHealthJobRequest | None = None, job: str | None = Query(None)) -> dict[str, Any]:
    body = req or DataHealthJobRequest()
    job_id = job or body.job or "data_health_refresh"
    if job_id not in JOB_IDS:
        raise HTTPException(status_code=422, detail=f"unknown job {job_id!r}; known: {list(JOB_IDS)}")
    store, root, hol = _store(), _root(), holidays()
    if _submit is None:
        raise HTTPException(status_code=503, detail="data_health package not configured")

    def _run(progress: Callable[[int, int], None]) -> dict[str, Any]:
        out = refresh(store, root, since=body.since, sessions=body.sessions, reason=body.reason, datasets=body.datasets, hol=hol)
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


@router.get("/db/data-health/gaps")
def data_health_gaps(since: str | None = Query(None), dataset: str | None = Query(None, max_length=64)) -> dict[str, Any]:
    s = date.fromisoformat(since[:10]) if since else None
    rows = gaps.gaps(_store(), since=s, dataset=dataset)
    return {"rows": rows, "count": len(rows)}
