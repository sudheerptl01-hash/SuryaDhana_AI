"""FastAPI router for the drivers: ``POST /jobs/index-drivers`` (``?job=index_drivers_daily|index_drivers_backfill``) and the
``GET /db/index-drivers*`` reads. ``configure`` is called by data-service ``main.py``; additive."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from index_drivers import ingest, jobs, reads

router = APIRouter(tags=["index-drivers"])

_get_store: Callable[[], Any] | None = None
_submit: Callable[..., dict[str, Any]] | None = None
_paths: dict[str, Path] = {}
_http_factory: Callable[[], Any] | None = None


def configure(*, get_store: Callable[[], Any], submit: Callable[..., dict[str, Any]], cache_root: Path, financials_root: Path,
              http_factory: Callable[[], Any] | None = None) -> None:
    global _get_store, _submit, _paths, _http_factory
    _get_store, _submit, _http_factory = get_store, submit, http_factory
    _paths = {"cache_root": cache_root, "financials_root": financials_root}


def _store() -> Any:
    if _get_store is None:
        raise HTTPException(status_code=503, detail="index_drivers package not configured")
    return _get_store()


def _http() -> Any:
    if _http_factory is not None:
        return _http_factory()
    from shared.http_client import PacedClient

    return PacedClient()


class DriversJobRequest(BaseModel):
    job: str | None = None
    date_: date | None = Field(default=None, alias="date")
    backfill_from: date | None = None
    backfill_to: date | None = None
    indices: list[str] | None = None
    fetch: bool = True
    resume: bool = True
    allow_pre_list: bool = False      # owner opt-in (O-T13): compute NIFTY BANK before its first archived constituent list
    model_config = {"populate_by_name": True}


@router.post("/jobs/index-drivers")
def index_drivers_job(req: DriversJobRequest | None = None, job: str | None = Query(None), backfill_from: date | None = Query(None)) -> dict[str, Any]:  # noqa: B008
    body = req or DriversJobRequest()
    job_id = job or body.job or "index_drivers_daily"
    if job_id not in jobs.JOBS:
        raise HTTPException(status_code=422, detail=f"unknown job {job_id!r}; known: {list(jobs.JOBS)}")
    indices = tuple(body.indices) if body.indices else ingest.INDICES
    unknown = [ix for ix in indices if ix not in ingest.CONSTITUENT_URLS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown indices {unknown}; known: {sorted(ingest.CONSTITUENT_URLS)}")
    store = _store()
    start = backfill_from or body.backfill_from
    if _submit is None:
        raise HTTPException(status_code=503, detail="index_drivers package not configured")

    def _run(progress: Callable[[int, int], None]) -> dict[str, Any]:
        if job_id == "index_drivers_backfill" or start is not None:
            return jobs.run_backfill(store, start=start or date(2019, 10, 1), end=body.backfill_to or date.today(), indices=indices,  # noqa: DTZ011
                                     financials_root=_paths["financials_root"], progress=progress, resume=body.resume,
                                     allow_pre_list=body.allow_pre_list)
        return jobs.run_daily(store, _http(), day=body.date_, indices=indices, cache_root=_paths["cache_root"], financials_root=_paths["financials_root"],
                              fetch=body.fetch)

    return _submit(f"index_drivers:{job_id}", _run)


@router.get("/db/index-drivers")
def index_drivers(index: str = Query("NIFTY 50", max_length=32),
                  horizon: str = Query("1m", pattern="^(1d|5d|1m|3m|60s|ytd|since_change)$")) -> dict[str, Any]:
    return reads.drivers(_store(), index.upper(), horizon)


@router.get("/db/index-drivers/timeline")
def index_drivers_timeline(index: str = Query("NIFTY 50", max_length=32), window: int = Query(20, ge=5, le=250), days: int = Query(250, ge=1, le=3000)) -> dict[str, Any]:
    if window not in (20, 60):
        raise HTTPException(status_code=422, detail="window must be 20 or 60 (the stored windows)")
    return reads.timeline(_store(), index.upper(), window=window, days=days)


@router.get("/db/index-drivers/monthly")
def index_drivers_monthly(index: str = Query("NIFTY 50", max_length=32), months: int = Query(12, ge=1, le=120)) -> dict[str, Any]:
    return reads.monthly(_store(), index.upper(), months=months)


# API_CONTRACT §6 (what ui-api's routers/markets.py reads); the derived /db/index-drivers payloads above stay
@router.get("/db/index-drivers/contribution")
def index_drivers_contribution(index: str = Query("NIFTY 50", max_length=32), days: int = Query(400, ge=1, le=3000)) -> dict[str, Any]:
    return reads.contract_contribution(_store(), index, days=days)


@router.get("/db/index-drivers/fit")
def index_drivers_fit(index: str = Query("NIFTY 50", max_length=32), days: int = Query(400, ge=1, le=3000)) -> dict[str, Any]:
    return reads.contract_fit(_store(), index, days=days)


@router.get("/db/index-drivers/state")
def index_drivers_state(index: str = Query("NIFTY 50", max_length=32), days: int = Query(5, ge=1, le=3000)) -> dict[str, Any]:
    return reads.contract_state(_store(), index, days=days)


@router.get("/db/index-drivers/weights")
def index_drivers_weights(index: str = Query("NIFTY 50", max_length=32), date_: str | None = Query(None, alias="date")) -> dict[str, Any]:
    try:
        day = date.fromisoformat(date_[:10]) if date_ else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad date {date_!r}") from exc
    return reads.contract_weights(_store(), index, day=day)


# FINAL round R2-DRIV (RATING R9-I3): the within-day contribution timeline — tick-store minute closes × stored
# PIT weights, the 2-min tape as the fallback, honest gaps. Sync def: parquet/pandas run in the threadpool.
@router.get("/db/index-drivers/intraday")
def index_drivers_intraday(index: str = Query("NIFTY 50", max_length=32),
                           date_: str | None = Query(None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
                           interval: str = Query("1m", pattern="^(1m|5m)$"),
                           top: int = Query(7, ge=3, le=15)) -> dict[str, Any]:
    from index_drivers import intraday as _intraday

    try:
        day = date.fromisoformat(date_) if date_ else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad date {date_!r}") from exc
    return _intraday.intraday(_store(), index.upper(), day=day, interval=interval, top=top)


@router.get("/db/index-drivers/catalog")
def index_drivers_catalog() -> dict[str, Any]:
    return reads.catalog()


@router.get("/db/index-drivers/meta")
def index_drivers_meta() -> dict[str, Any]:
    return reads.meta(_store())


@router.get("/db/index-drivers/backfill-plan")
def index_drivers_backfill_plan() -> dict[str, Any]:
    return jobs.backfill_plan(_store())
