"""FastAPI router for the IV store: ``POST /jobs/iv-eod`` (``?job=iv_eod|iv_weekly|iv_backfill|vix_backfill``), ``POST
/jobs/iv-intraday`` (``?job=iv_intraday``), ``POST /jobs/ingest-nse-files`` (the Wave 0 0.5 file ingests incl. the bhavcopy
revision pass) and the ``GET /db/fo-iv/*`` reads (PLAN 1.1 API contract, data-service half). ``configure`` is called by
data-service ``main.py``; this module owns no global store. Additive; nothing existing changes.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from data_health import db
from fo_iv import jobs, reads

router = APIRouter(tags=["fo-iv"])

_get_store: Callable[[], Any] | None = None
_submit: Callable[..., dict[str, Any]] | None = None
_paths: dict[str, Path] = {}
_http_factory: Callable[[], Any] | None = None
_get_breeze: Callable[[], Any] | None = None
_is_live: Callable[[], bool] | None = None
_watchlist: Callable[[], list[str]] | None = None
_surface_symbols: Callable[[], set[str] | None] | None = None


def configure(*, get_store: Callable[[], Any], submit: Callable[..., dict[str, Any]], fo_root: Path, cache_root: Path, parquet_root: Path,
              http_factory: Callable[[], Any] | None = None, get_breeze: Callable[[], Any] | None = None, is_live: Callable[[], bool] | None = None,
              watchlist: Callable[[], list[str]] | None = None, surface_symbols: Callable[[], set[str] | None] | None = None) -> None:
    global _get_store, _submit, _paths, _http_factory, _get_breeze, _is_live, _watchlist, _surface_symbols
    _get_store, _submit = get_store, submit
    _paths = {"fo_root": fo_root, "cache_root": cache_root, "parquet_root": parquet_root}
    _http_factory, _get_breeze, _is_live, _watchlist, _surface_symbols = http_factory, get_breeze, is_live, watchlist, surface_symbols


def _store() -> Any:
    if _get_store is None:
        raise HTTPException(status_code=503, detail="fo_iv package not configured")
    return _get_store()


def _http() -> Any:
    if _http_factory is not None:
        return _http_factory()
    from shared.http_client import PacedClient

    return PacedClient()


def _budget() -> Any:
    """B3's ledger when deployed; ``None`` → the pilot is skipped (never an unmetered Breeze call)."""
    try:
        from shared import breeze_budget  # type: ignore[import-not-found]
    except ImportError:
        return None
    getter = getattr(breeze_budget, "ledger", None)
    return getter() if callable(getter) else None


def _submit_or_503(kind: str, fn: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    if _submit is None:
        raise HTTPException(status_code=503, detail="fo_iv package not configured")
    return _submit(kind, fn)


class IvJobRequest(BaseModel):
    job: str | None = None
    date_: date | None = Field(default=None, alias="date")
    backfill_from: date | None = None
    backfill_to: date | None = None
    surface_symbols: list[str] | None = None
    revalidate: bool = False
    fetch_files: bool = True
    max_files: int | None = Field(default=None, ge=1, le=5000)
    resume: bool = True
    model_config = {"populate_by_name": True}


@router.post("/jobs/iv-eod")
def iv_eod_job(req: IvJobRequest | None = None, job: str | None = Query(None), backfill_from: date | None = Query(None)) -> dict[str, Any]:  # noqa: B008
    body = req or IvJobRequest()
    job_id = job or body.job or "iv_eod"
    if job_id not in jobs.JOBS or job_id == "iv_intraday":
        raise HTTPException(status_code=422, detail=f"unknown job {job_id!r}; known: {[j for j in jobs.JOBS if j != 'iv_intraday']}")
    store = _store()
    start = backfill_from or body.backfill_from
    surface = set(body.surface_symbols) if body.surface_symbols else (_surface_symbols() if _surface_symbols else None)
    fo_root, cache_root = _paths["fo_root"], _paths["cache_root"]

    def _run(progress: Callable[[int, int], None]) -> dict[str, Any]:
        if job_id == "iv_weekly":
            return jobs.run_weekly(store)
        if job_id == "vix_backfill":
            return jobs.run_vix_backfill(store, _http(), start=start or date(2014, 1, 1), end=body.backfill_to or date.today())  # noqa: DTZ011
        if job_id == "iv_backfill" or start is not None:
            return jobs.run_backfill(store, start=start or jobs.LEGACY_START, end=body.backfill_to or date.today(), fo_root=fo_root,  # noqa: DTZ011
                                     surface_symbols=surface, progress=progress, resume=body.resume, max_files=body.max_files,
                                     index_history_csv=cache_root / "nse_archive" / "derived" / "index_valuation_history.csv")
        return jobs.run_eod(store, _http(), day=body.date_, fo_root=fo_root, cache_root=cache_root, surface_symbols=surface,
                            fetch_files=body.fetch_files, revalidate=body.revalidate)

    return _submit_or_503(f"fo_iv:{job_id}", _run)


class IntradayRequest(BaseModel):
    job: str | None = None
    watchlist: list[str] | None = None
    force_window: bool = False


@router.post("/jobs/iv-intraday")
def iv_intraday_job(req: IntradayRequest | None = None, job: str | None = Query(None)) -> dict[str, Any]:
    body = req or IntradayRequest()
    job_id = job or body.job or "iv_intraday"
    if job_id != "iv_intraday":
        raise HTTPException(status_code=422, detail="job must be iv_intraday")
    store = _store()
    breeze = _get_breeze() if _get_breeze else None
    wl = body.watchlist if body.watchlist is not None else (_watchlist() if _watchlist else [])

    def _run(progress: Callable[[int, int], None]) -> dict[str, Any]:
        out = jobs.run_intraday(store, breeze, _budget(), parquet_root=_paths["parquet_root"], watchlist=wl, force_window=body.force_window, is_live=_is_live)
        progress(1, 1)
        return out

    return _submit_or_503("fo_iv:iv_intraday", _run)


class NseFilesRequest(BaseModel):
    job: str | None = None
    datasets: list[str] = Field(default_factory=list)
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    revalidate: bool = False
    model_config = {"populate_by_name": True}


@router.post("/jobs/ingest-nse-files")
def ingest_nse_files(req: NseFilesRequest | None = None, job: str | None = Query(None)) -> dict[str, Any]:
    """The Wave 0 0.5 file ingests: ``datasets`` ⊆ nse_positions.TERMINAL_DATASET_NAMES + ``nse_bhavcopy`` (the If-Modified-Since
    revision pass) for every weekday in [from, to] (default: the last completed session)."""
    import nse_positions

    body = req or NseFilesRequest()
    job_id = job or body.job or "nse_files"
    store = _store()
    known = set(nse_positions.TERMINAL_DATASET_NAMES) | {"nse_bhavcopy"}
    datasets = body.datasets or list(jobs.EOD_FILES)
    unknown = [d for d in datasets if d not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown datasets {unknown}; known: {sorted(known)}")
    end = body.to or date.today()  # noqa: DTZ011
    start = body.from_ or end
    cache_root = _paths["cache_root"]

    def _run(progress: Callable[[int, int], None]) -> dict[str, Any]:
        http = _http()
        out: dict[str, Any] = {"job": job_id, "from": start.isoformat(), "to": end.isoformat()}
        files = [d for d in datasets if d != "nse_bhavcopy"]
        if files:
            out["files"] = nse_positions.ingest_files(store, http, files, start, end, cache_root, revalidate=body.revalidate, progress=progress)["datasets"]
        if "nse_bhavcopy" in datasets:
            days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            out["nse_bhavcopy"] = [nse_positions.revise_bhavcopy(store, http, d, cache_root / "nse_archive" / "bhavcopy") for d in days if d.weekday() < 5]
        try:
            store.checkpoint()
        except Exception:  # noqa: BLE001
            pass
        out["status"] = "ok"
        return out

    return _submit_or_503(f"nse_files:{job_id}", _run)


def _d(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad date {s!r}") from exc


@router.get("/db/fo-iv/summary/{symbol}")
def fo_iv_summary(symbol: str, days: int = Query(750, ge=1, le=5000)) -> dict[str, Any]:
    return reads.summary(_store(), symbol, days=days)


@router.get("/db/fo-iv/surface/{symbol}")
def fo_iv_surface(symbol: str, date_: str | None = Query(None, alias="date"), compare_days: int | None = Query(None, ge=1, le=400)) -> dict[str, Any]:
    return reads.surface(_store(), symbol, day=_d(date_), compare_days=compare_days)


@router.get("/db/fo-iv/cone/{symbol}")
def fo_iv_cone(symbol: str) -> dict[str, Any]:
    return reads.cone(_store(), symbol)


@router.get("/db/fo-iv/events/{symbol}")
def fo_iv_events(symbol: str, n: int = Query(8, ge=1, le=100)) -> dict[str, Any]:
    return reads.events(_store(), symbol, n=n)


@router.get("/db/fo-iv/vol-screen")
def fo_iv_vol_screen(sort: str = Query("iv_pctile", pattern="^(iv_pctile|iv_rank|iv_minus_rv|term_slope|skew|iv30)$"),
                     results_within: int | None = Query(None, ge=0, le=60), date_: str | None = Query(None, alias="date")) -> dict[str, Any]:
    return reads.vol_screen(_store(), sort=sort, results_within=results_within, day=_d(date_))


@router.get("/db/fo-iv/intraday/{symbol}")
def fo_iv_intraday(symbol: str, date_: str | None = Query(None, alias="date")) -> dict[str, Any]:
    return reads.intraday(_store(), symbol, day=_d(date_))


@router.get("/db/fo-iv/catalog")
def fo_iv_catalog() -> dict[str, Any]:
    return reads.catalog()


@router.get("/db/fo-iv/meta")
def fo_iv_meta() -> dict[str, Any]:
    return reads.meta(_store())


@router.get("/db/fo-iv/backfill-plan")
def fo_iv_backfill_plan() -> dict[str, Any]:
    return jobs.backfill_plan(_paths["fo_root"], _store())


@router.get("/db/vix-daily")
def vix_daily(days: int = Query(3000, ge=1, le=10000)) -> dict[str, Any]:
    return reads.vix(_store(), days=days)


@router.get("/db/index-ohlc/{symbol}")
def index_ohlc(symbol: str, days: int = Query(3000, ge=1, le=10000)) -> dict[str, Any]:
    return reads.index_ohlc(_store(), symbol, days=days)


@router.get("/db/fo-iv/jobs")
def fo_iv_jobs() -> dict[str, Any]:
    return {"jobs": list(jobs.JOBS), "eod_files": list(jobs.EOD_FILES), "as_of": db.iso_utc(db.utcnow())}
