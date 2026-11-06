"""FastAPI router for the gold package: ``POST /jobs/ingest-gold`` (the controller's contract: ``?job=<id>`` + body
``{"job", "groups", "backfill_from"?, "force"?, "params"?}`` → a JobManager job polled on ``GET /jobs/{job_id}``),
``POST /jobs/gold-log`` (ui-api's dual write of the fair-open log) and the ``GET /db/gold/*`` reads (PLAN §c.5).

``configure`` is called by data-service ``main.py`` with its ``get_store`` and ``_submit`` so this module owns no
global store. All routes are additive; nothing existing changes.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from gold import backfill, ingest_local, jobs, reads
from gold.db import utcnow

router = APIRouter(tags=["gold"])

_get_store: Callable[[], Any] | None = None
_submit: Callable[[str, Callable[[Callable[[int, int], None]], dict[str, Any]]], dict[str, Any]] | None = None
_http: Any = None
_get_breeze: Callable[[], Any] | None = None


def configure(*, get_store: Callable[[], Any], submit: Callable[..., dict[str, Any]], http: Any = None,
              get_breeze: Callable[[], Any] | None = None) -> None:
    """``get_breeze`` returns data-service's live BreezeConnect (or None without a session); only the read-only
    ``mcx_close_vwap30`` (wave 1d) and ``breeze_daily`` (O-8, 6 Nov 2026) groups call it."""
    global _get_store, _submit, _http, _get_breeze
    _get_store, _submit, _http, _get_breeze = get_store, submit, http, get_breeze


def _store() -> Any:
    if _get_store is None:
        raise HTTPException(status_code=503, detail="gold package not configured")
    return _get_store()


def _client() -> Any:
    global _http
    if _http is None:
        _http = jobs.default_http()
    return _http


class GoldIngestRequest(BaseModel):
    job: str | None = None
    groups: list[str] = Field(default_factory=list)
    backfill_from: date | None = None
    force: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/jobs/ingest-gold")
def ingest_gold(req: GoldIngestRequest | None = None, job: str | None = Query(None),
                backfill_from: date | None = Query(None), force: bool = Query(False)) -> dict[str, Any]:  # noqa: B008
    """Start a gold ingest job (groups run in order with failure isolation; see ``gold.jobs``)."""
    body = req or GoldIngestRequest()
    job_id = job or body.job or "gold_adhoc"
    groups = [g for g in body.groups if g]
    if not groups:
        raise HTTPException(status_code=422, detail="groups must name at least one ingest group")
    unknown = [g for g in groups if jobs.resolve(g) not in jobs.GROUPS and jobs.resolve(g) not in jobs.DORMANT]
    if len(unknown) == len(groups):
        raise HTTPException(status_code=422, detail=f"no known group in {groups}; known: {sorted(jobs.GROUPS)}")
    start = backfill_from or body.backfill_from
    forced = force or body.force
    params = dict(body.params)
    store, http = _store(), _client()
    if _submit is None:
        raise HTTPException(status_code=503, detail="gold package not configured")

    def _run(progress: Callable[[int, int], None]) -> dict[str, Any]:
        res = jobs.run_job(store, http, job_id, groups, backfill_from=start, force=forced, params=params, progress=progress,
                           breeze=_get_breeze)
        reads.invalidate_catalog_cache()
        return res

    return _submit(f"gold:{job_id}", _run)


class GoldLogRequest(BaseModel):
    day: date | None = None
    date_: date | None = Field(default=None, alias="date")
    contract: str | None = None
    expiry: date | None = None
    baseline: float | None = None
    baseline_source: str | None = None
    comex_symbol: str | None = None
    comex_ref: float | None = None
    comex_now: float | None = None
    inr_ref: float | None = None
    inr_now: float | None = None
    fair_open: float | None = None
    threshold: float | None = None
    event_risk: int | None = None
    actual_open: float | None = None
    actual_source: str | None = None
    snapshot_at: datetime | str | None = None
    captured_at: datetime | str | None = None
    error: float | None = None
    naive_error: float | None = None
    stale_baseline: bool | None = None
    inputs_json: dict[str, Any] | list[Any] | str | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


@router.post("/jobs/gold-log")
def gold_log(req: GoldLogRequest) -> dict[str, Any]:
    """Write/merge one accuracy-log row (today's 08:45 snapshot or the 09:10 captured open)."""
    payload = req.model_dump(by_alias=True, exclude_none=True)
    payload["day"] = req.day or req.date_
    if payload["day"] is None:
        raise HTTPException(status_code=422, detail="day (or date) is required")
    store = _store()
    if getattr(store, "_read_only", False):
        raise HTTPException(status_code=503, detail="DuckDB is read-only")
    out = ingest_local.upsert_preopen_log(store, payload)
    with contextlib.suppress(Exception):
        store.checkpoint()
    return out


def _dates(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad date {s!r}") from exc


def _asof(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad asof {s!r}") from exc
    if dt.tzinfo is not None:
        from zoneinfo import ZoneInfo

        dt = dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return dt


@router.get("/db/gold/catalog")
def gold_catalog() -> dict[str, Any]:
    return reads.catalog(_store())


@router.get("/db/gold/series")
def gold_series(ids: str = Query(..., min_length=1, max_length=4000), from_: str | None = Query(None, alias="from"),
                to: str | None = Query(None), asof: str | None = Query(None), freq: str = Query("D", pattern="^[DWM]$")) -> dict[str, Any]:
    id_list = [s.strip() for s in ids.split(",") if s.strip()][:200]
    return reads.series(_store(), id_list, start=_dates(from_), end=_dates(to), asof=_asof(asof), freq=freq)


@router.get("/db/gold/cot")
def gold_cot(weeks: int = Query(52, ge=1, le=3000), report: str = Query("disagg", pattern="^(disagg|legacy)$"),
             fut_or_combined: str = Query("F", pattern="^[FC]$"), contract: str = Query("088691", max_length=8)) -> dict[str, Any]:
    return reads.cot(_store(), weeks=weeks, report=report, fut_or_combined=fut_or_combined, contract=contract)


@router.get("/db/gold/cme/voi")
def gold_cme_voi(from_: str | None = Query(None, alias="from"), products: str | None = Query(None)) -> dict[str, Any]:
    return reads.cme_voi(_store(), start=_dates(from_), products=[p.strip() for p in products.split(",")] if products else None)


@router.get("/db/gold/cme/efrp")
def gold_cme_efrp(from_: str | None = Query(None, alias="from")) -> dict[str, Any]:
    return reads.cme_efrp(_store(), start=_dates(from_))


@router.get("/db/gold/curve")
def gold_curve(exchange: str = Query("COMEX", pattern="^(COMEX|MCX)$"), date_: str | None = Query(None, alias="date")) -> dict[str, Any]:
    return reads.curve(_store(), exchange=exchange, day=_dates(date_))


@router.get("/db/gold/mcx/settlement")
def gold_mcx_settlement(symbol: str = Query("GOLD", pattern="^(GOLD|GOLDM|GOLDTEN|GOLDPETAL|GOLDGUINEA)$"),
                        expiry: str | None = Query(None), date_: str | None = Query(None, alias="date"),
                        asof: str | None = Query(None)) -> dict[str, Any]:
    """The latest COMPLETED session's settlement proxy for one MCX contract (wave 1d, API_CONTRACT fair block):
    ``settlement`` = the Breeze last-30-min VWAP when stored, else the ICICI band midpoint, with ``settlement_source``,
    ``settlement_session`` (+ label), ``settlement_quality``, ``band_midpoint`` / ``band_session`` (the band labelled
    with the session it really belongs to) and ``settlement_check``. ``expiry`` defaults to the front month."""
    return reads.mcx_settlement(_store(), symbol=symbol, expiry=_dates(expiry), day=_dates(date_), asof=_asof(asof))


@router.get("/db/gold/mcx/daily")
def gold_mcx_daily(family: str | None = Query(None, pattern="^(GOLD|GOLDM|GOLDTEN|GOLDPETAL|GOLDGUINEA)$"),
                   expiry: str | None = Query(None), from_: str | None = Query(None, alias="from"),
                   to: str | None = Query(None)) -> dict[str, Any]:
    """MCX gold futures daily bars per expiry from ICICI Breeze (gold_mcx_daily, O-8): OHLC, volume and OI in lots,
    ``release_at`` / ``first_seen_at`` with ``+00:00``; ``from`` defaults to 180 days back."""
    return reads.mcx_daily(_store(), family=family, expiry=_dates(expiry), start=_dates(from_), end=_dates(to))


@router.get("/db/gold/curve/history")
def gold_curve_history(exchange: str = Query("MCX", pattern="^(COMEX|MCX)$"), symbol: str = Query("GOLD", max_length=12),
                       days: int = Query(120, ge=1, le=3000)) -> dict[str, Any]:
    return reads.curve_history(_store(), exchange=exchange, symbol=symbol, days=days)


@router.get("/db/gold/margins")
def gold_margins(date_: str | None = Query(None, alias="date"), exchange: str | None = Query(None, pattern="^(COMEX|MCX)$")) -> dict[str, Any]:
    return reads.margins(_store(), day=_dates(date_), exchange=exchange)


@router.get("/db/gold/bars")
def gold_bars(symbol: str = Query(..., max_length=32), interval: str = Query("1d", pattern="^(1d|1m|5m)$"),
              from_: str | None = Query(None, alias="from"), to: str | None = Query(None)) -> dict[str, Any]:
    start: Any = _asof(from_) if interval != "1d" else _dates(from_)
    end: Any = _asof(to) if interval != "1d" else _dates(to)
    return reads.bars(_store(), symbol=symbol, interval=interval, start=start, end=end)


@router.get("/db/gold/asia")
def gold_asia(from_: str | None = Query(None, alias="from"), exchange: str | None = Query(None, pattern="^(SGE|SHFE)$")) -> dict[str, Any]:
    return reads.asia(_store(), start=_dates(from_), exchange=exchange)


@router.get("/db/gold/etf")
def gold_etf(from_: str | None = Query(None, alias="from"), fund: str | None = Query(None, max_length=8)) -> dict[str, Any]:
    return reads.etf(_store(), start=_dates(from_), fund=fund)


@router.get("/db/gold/fed-path")
def gold_fed_path(asof: str | None = Query(None)) -> dict[str, Any]:
    return reads.fed_path(_store(), asof=_dates(asof))


@router.get("/db/gold/events")
def gold_events(from_: str | None = Query(None, alias="from"), to: str | None = Query(None), kinds: str | None = Query(None)) -> dict[str, Any]:
    return reads.events(_store(), start=_dates(from_), end=_dates(to), kinds=[k.strip() for k in kinds.split(",")] if kinds else None)


@router.get("/db/gold/log")
def gold_log_read(days: int = Query(60, ge=1, le=3650)) -> dict[str, Any]:
    return reads.log(_store(), days=days)


@router.get("/db/gold/brief")
def gold_brief(date_: str | None = Query(None, alias="date")) -> dict[str, Any]:
    return reads.brief(_store(), day=_dates(date_))


@router.get("/db/gold/cme/prf")
def gold_cme_prf(symbol: str = Query("GC", max_length=12)) -> dict[str, Any]:
    """gold_cme_prf rows for one root symbol (the matched contract's DES card on GOLD › CONTRACTS, ui-api /api/gold/contracts?exchange=COMEX)."""
    return reads.cme_prf(_store(), symbol=symbol)


@router.get("/db/gold/cme/calendar")
def gold_cme_calendar(symbol: str = Query("GC", max_length=12), as_of: str | None = Query(None)) -> dict[str, Any]:
    """gold_cme_calendar rows (FND / LTD / first intent per delivery month) for one root symbol on the latest ``as_of``
    (wave 1c: lets the page and an operator verify the Sunday job without opening the store)."""
    return reads.cme_calendar(_store(), symbol=symbol, as_of=_dates(as_of))


@router.get("/db/gold/health-daily")
def gold_health_daily(from_: str | None = Query(None, alias="from")) -> dict[str, Any]:
    return reads.health_daily(_store(), start=_dates(from_))


@router.get("/db/gold/meta")
def gold_meta() -> dict[str, Any]:
    return reads.meta(_store())


@router.get("/db/gold/groups")
def gold_groups() -> dict[str, Any]:
    """The ingest groups data-service knows (for the controller and the WHSE panel)."""
    return {"groups": {k: {"cadence": g.cadence, "table": g.table, "heavy": g.heavy, "note": g.note} for k, g in jobs.GROUPS.items()},
            "aliases": jobs.ALIASES, "dormant": jobs.DORMANT, "as_of": utcnow().isoformat()}


@router.get("/db/gold/backfill-plan")
def gold_backfill_plan() -> dict[str, Any]:
    return {"steps": backfill.steps()}
