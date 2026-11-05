"""GET /api/data/health — the data-health view (Terminal v2 PLAN 1.4, B3; R-DATA §10 spec).

One row per catalogued dataset: publisher, when it is published (IST), when the terminal expects it stored
(`expected_by`, trading-day aware), what is actually stored (`as_of`), how many sessions behind the last close it is,
a state (live | fresh | amber | red | gap), the ingest job's last run and next run, the catch-up slot, and the
dictionary anchor. Honest wording, no composite score: the page says "stored 30 Oct · expected by 21:00 ·
3 sessions behind · catch-up 19:30 tomorrow".

The catalog is data-service's `dataset_catalog` (B1 `data_health/`, served as /db/data-health/catalog); until it is
deployed, the built-in seed below (R-DATA §3's rows that the existing endpoints can already evaluate) is used and
the payload says so (`catalog_source`). Nothing is fetched from a publisher on the request path: inputs are
data-service `/db/nse-positions-meta`, `/db/freshness`, `/db/archive-meta`, `/db/market-holidays`,
`/db/data-health/ingest-log` (B1, optional) and master-controller `/api/scheduler/status`, each through the
process-wide client and one stale-while-revalidate cache (60 s refresh, 10 min bound).

`/api/data/health` was a thin relay of data-service's `/health` (routers/data_proxy.py; defined in ui/lib/api.ts,
called by no component); this view keeps `status` / `data_service` keys so an old caller still sees liveness.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cache import SWRCache, TTLCache, cache_headers, merge_served
from fastapi import APIRouter, Query, Response

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.http_client import UpstreamError, get_json  # noqa: E402

router = APIRouter()
IST = ZoneInfo("Asia/Kolkata")
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
MASTER_CTL = os.environ.get("MASTER_CONTROLLER_URL", "http://localhost:8008").rstrip("/")
STORE = SWRCache("data_health.inputs", max_items=16, refresh_after=60.0, max_age=600.0)
_ttl = TTLCache("data_health", max_items=16, default_ttl=15.0)
MARKET_CLOSE = time(15, 30)
STATES = ("live", "fresh", "amber", "red", "gap")
DESCRIBES = "describes, does not predict"
CATCHUP_JOBS = ("nse_positions_catchup", "startup_catchup", "gold_downtime_catchup")


@dataclass(frozen=True)
class CatalogRow:
    id: str
    label: str
    pages: tuple[str, ...]
    publisher: str
    publish_time_ist: str          # "20:10" or a phrase
    expected_by: str | None        # "HH:MM" IST on the publication day, or None for live rows
    max_age: int                   # sessions behind the last close before red
    ingest_job: str | None
    source_kind: str               # positions_meta | freshness | archive | live | scheduler
    source_key: str                # the key inside that input
    dictionary_anchor: str
    unrecoverable: bool = False
    t_plus: int = 0                # 1 for files published for T−1 (MTF): stored as-of lags one session by design
    badge: str = "context"
    note: str | None = None


# R-DATA §3 rows that the existing endpoints can evaluate today (B1's dataset_catalog replaces this seed when deployed).
FALLBACK_CATALOG: tuple[CatalogRow, ...] = (
    CatalogRow("ohlcv", "Daily bars (ohlcv, 1,496 tickers)", ("EQS", "CHRT", "WHSE", "DESK", "BTST"), "Yahoo Finance (existing scripts)",
               "~18:00", "19:00", 2, "eod_data_pipeline", "freshness", "latest_bar_date", "NSE_DATA_DICTIONARY.md#ohlcv"),
    CatalogRow("nse_bhavcopy", "NSE equity full bhavcopy", ("DES", "EQS", "DEAL", "MKT", "DESK"), "NSE (nsearchives)",
               "18:30; re-published 22:05", "19:00", 2, "eod_data_pipeline", "positions_meta", "nse_bhavcopy", "NSE_DATA_DICTIONARY.md#bhavcopy"),
    CatalogRow("nse_fo_daily", "F&O UDiFF bhavcopy (futures + options)", ("DERV", "OMON", "OSTR", "MKT"), "NSE (nsearchives)",
               "20:10 (measured 4 Nov)", "21:00", 2, "nse_positions_catchup", "positions_meta", "nse_fo_daily", "NSE_DATA_DICTIONARY.md#fo-bhavcopy"),
    CatalogRow("nse_participant_oi", "Participant-wise OI", ("MKT", "DERV"), "NSE (nsearchives)", "20:10", "21:00", 2,
               "nse_positions_catchup", "positions_meta", "nse_participant_oi", "NSE_DATA_DICTIONARY.md#participant-oi"),
    CatalogRow("nse_deals", "Bulk / block / short deals", ("DEAL", "DESK"), "NSE API", "evening", "21:00", 2,
               "nse_positions_catchup", "positions_meta", "nse_deals", "NSE_DATA_DICTIONARY.md#deals"),
    CatalogRow("nse_mtf", "MTF financed positions (T−1 file)", ("MRGN",), "NSE (nsearchives)", "22:12 for T−1 (measured)", "23:00", 3,
               "nse_positions_catchup", "positions_meta", "nse_mtf", "NSE_DATA_DICTIONARY.md#mtf", t_plus=1),
    CatalogRow("nse_fii_dii_cash", "FII / DII cash (provisional)", ("BRF", "WRAP", "MKT"), "NSE API (latest day only)", "evening", "21:00", 2,
               "nse_positions_catchup", "positions_meta", "nse_fii_dii_cash", "NSE_DATA_DICTIONARY.md#fii-dii", unrecoverable=True,
               note="the API serves one day: a missed evening is lost for good"),
    CatalogRow("nse_insider_trades", "Insider trades (PIT)", ("INSD",), "NSE API (per stock)", "intimation ≈ T+2", "08:00", 7,
               "nse_filings_weekly", "positions_meta", "nse_insider_trades", "NSE_DATA_DICTIONARY.md#insider"),
    CatalogRow("nse_shareholding", "Shareholding pattern (XBRL)", ("HDS",), "NSE XBRL", "quarterly, ≤ 21 days", None, 120,
               "nse_filings_weekly", "positions_meta", "nse_shareholding", "NSE_DATA_DICTIONARY.md#shareholding"),
    CatalogRow("nse_results", "Results release times", ("ERN", "EVTS"), "NSE filings (real time)", "filing time", "21:30", 2,
               "results_capture_daily", "positions_meta", "nse_results", "NSE_DATA_DICTIONARY.md#results"),
    CatalogRow("nse_events", "Corporate calendar", ("EVTS", "ERN"), "NSE API", "forward-looking", "19:00", 3,
               "eod_data_pipeline", "positions_meta", "nse_events", "NSE_DATA_DICTIONARY.md#events"),
    CatalogRow("market_index_daily", "Index closes (NIFTY 50, India VIX)", ("DERV", "MKT", "RSK"), "NSE / Yahoo (readers prefer nse_daily_file)",
               "15:30 close", "19:00", 2, "eod_data_pipeline", "freshness", "nifty_index_latest_date", "NSE_DATA_DICTIONARY.md#index-closes"),
    CatalogRow("ml_features", "ML features (dormant pipeline)", ("MLEN", "GBOX"), "derived", "18:30 EOD", "19:00", 3,
               "eod_data_pipeline", "freshness", "ml_features_latest_date", "ML_QUANT_PIPELINE_GUIDE.md"),
    CatalogRow("archive:preopen", "Pre-open book capture", ("PRE",), "NSE live (09:00–09:08)", "09:09:30", "09:15", 1,
               "preopen_capture", "archive", "archive:preopen", "NSE_DATA_DICTIONARY.md#preopen", unrecoverable=True,
               note="session-bound: a missed capture is an explicit gap"),
    CatalogRow("archive:internals", "Intraday breadth samples", ("MOV", "WRAP"), "NSE live (every 2 min)", "in session", "15:35", 1,
               "internals_sample", "archive", "archive:internals", "NSE_DATA_DICTIONARY.md#internals", unrecoverable=True,
               note="session-bound: a missed session is an explicit gap"),
    CatalogRow("gold_cot", "Gold: CFTC COT (weekly)", ("GOLD",), "CFTC Socrata", "Fri 15:30 ET for Tue", "07:00 Sat", 8,
               "gold_cot_weekly", "positions_meta", "gold_cot", "GOLD_DATA_DICTIONARY.md#cot"),
    CatalogRow("gold_series", "Gold: macro / market series", ("GOLD",), "FRED / Treasury / Yahoo (one fetcher)", "continuous", "08:00", 3,
               "gold_overnight", "positions_meta", "gold_series", "GOLD_DATA_DICTIONARY.md"),
    CatalogRow("gold_daily_bars", "Gold: daily bars", ("GOLD", "MCXG"), "Yahoo (the one gold fetcher)", "continuous", "08:00", 2,
               "gold_overnight", "positions_meta", "gold_daily_bars", "GOLD_DATA_DICTIONARY.md#bars"),
    CatalogRow("gold_etf_holdings", "Gold: GLD / IAU holdings", ("GOLD",), "SPDR / iShares", "~06:00 IST", "07:00", 3,
               "gold_morning", "positions_meta", "gold_etf_holdings", "GOLD_DATA_DICTIONARY.md#etf"),
    CatalogRow("gold_health_daily", "Gold: health snapshot", ("GOLD",), "derived", "08:40", "08:45", 1,
               "gold_health_snapshot", "positions_meta", "gold_health_daily", "GOLD_DATA_DICTIONARY.md#health"),
    CatalogRow("iv_summary_daily", "IV history (iv_summary_daily)", ("OMON", "DERV", "EVTS"), "derived from the F&O bhavcopy (B1 fo_iv)",
               "20:30 pass", "21:30", 2, "iv_eod", "positions_meta", "iv_summary_daily", "TERMINAL_DATA_DICTIONARY.md#iv",
               note="starts the day the iv_eod job starts; backfilled from stored files to 2019-10-01 on O-T4"),
    CatalogRow("index_contribution_daily", "Index drivers (index_contribution_daily)", ("MEMB", "DESK"), "derived (B1 index_drivers)",
               "19:25", "20:35", 2, "index_drivers_daily", "positions_meta", "index_contribution_daily", "TERMINAL_DATA_DICTIONARY.md#drivers"),
)


# ── inputs ───────────────────────────────────────────────────────────────────────────────────────────────────
class _Unavailable(RuntimeError):
    pass


async def _fetch(url: str, params: dict[str, Any] | None = None, route: str = "read") -> Any:
    try:
        return await get_json(url, route=route, params=params)
    except UpstreamError as exc:
        raise _Unavailable(f"{exc.status_code}: {exc.detail[:100]}") from exc


class _Inputs:
    def __init__(self) -> None:
        self.served: list[Any] = []
        self.errors: dict[str, str] = {}

    async def get(self, name: str, url: str, params: dict[str, Any] | None = None, route: str = "read") -> Any | None:
        down = _ttl.get(f"down:{name}")
        if down is not None:
            self.errors[name] = str(down)
            return None
        key = (name, tuple(sorted((params or {}).items())))
        try:
            served = await STORE.get(key, lambda: _fetch(url, params, route))
        except _Unavailable as exc:
            _ttl.set(f"down:{name}", str(exc))
            self.errors[name] = str(exc)
            return None
        except Exception as exc:  # noqa: BLE001
            self.errors[name] = type(exc).__name__
            return None
        self.served.append(served)
        return served.value


# ── pure helpers (unit-tested) ───────────────────────────────────────────────────────────────────────────────
def _d(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def trading_days(start: date, end: date, holidays: Iterable[date]) -> list[date]:
    """Weekdays in (start, end] that are not NSE holidays."""
    hol = set(holidays)
    out: list[date] = []
    d = start + timedelta(days=1)
    while d <= end:
        if d.weekday() < 5 and d not in hol:
            out.append(d)
        d += timedelta(days=1)
    return out


def last_close_session(now: datetime, holidays: Iterable[date]) -> date:
    """The last trading day whose 15:30 close has passed (today after 15:30, else the previous trading day)."""
    hol = set(holidays)
    d = now.date()
    if now.time() < MARKET_CLOSE or d.weekday() >= 5 or d in hol:
        d -= timedelta(days=1)
    while d.weekday() >= 5 or d in hol:
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date, holidays: Iterable[date]) -> date:
    hol = set(holidays)
    n = d + timedelta(days=1)
    while n.weekday() >= 5 or n in hol:
        n += timedelta(days=1)
    return n


def _expected_at(row: CatalogRow, session: date, now: datetime) -> datetime | None:
    """When `session`'s data is expected stored, as an IST datetime (publication day = the session, or the next trading
    day for T+1 files and morning slots)."""
    if not row.expected_by:
        return None
    hhmm = row.expected_by.split()[0]
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return None
    day = session
    if row.t_plus or time(h, m) < MARKET_CLOSE:        # a morning slot refers to the next calendar day after the session
        day = session + timedelta(days=1)
    return datetime.combine(day, time(h, m), tzinfo=IST)


def classify(row: CatalogRow, as_of: date | None, now: datetime, holidays: Iterable[date], gap: bool = False) -> dict[str, Any]:
    """state + lag for one row. fresh: nothing missing, or the latest session not yet due; amber: due and 1 session
    behind (or ≤ max_age behind); red: more than max_age sessions behind or nothing stored; gap: an explicit gap row
    for a session-bound capture; live rows are classified by their last sample like any other."""
    hol = list(holidays)
    last = last_close_session(now, hol)
    target = last
    if row.t_plus:
        prev = last - timedelta(days=1)
        while prev.weekday() >= 5 or prev in hol:
            prev -= timedelta(days=1)
        target = prev
    if gap:
        return {"state": "gap", "lag_sessions": None, "expected_by": row.expected_by, "last_session": last.isoformat(),
                "due": True, "note": row.note or "explicit gap row (session-bound capture missed)"}
    if as_of is None:
        return {"state": "red", "lag_sessions": None, "expected_by": row.expected_by, "last_session": last.isoformat(),
                "due": True, "note": "nothing stored"}
    lag = len(trading_days(as_of, target, hol)) if as_of < target else 0
    exp_at = _expected_at(row, target, now)
    due = exp_at is None or now >= exp_at
    if lag == 0 or (lag == 1 and not due):
        state = "fresh"
    elif lag > row.max_age:
        state = "red"
    else:
        state = "amber"
    words = f"stored {as_of.strftime('%d %b')}"
    if row.expected_by:
        words += f" · expected by {row.expected_by}"
    if lag:
        words += f" · {lag} session{'s' if lag != 1 else ''} behind"
        if not due:
            words += " (not due yet)"
    return {"state": state, "lag_sessions": lag, "expected_by": row.expected_by, "last_session": last.isoformat(),
            "due": due, "note": words}


def _as_of_from_inputs(row: CatalogRow, meta: dict[str, Any], fresh: dict[str, Any], archive: dict[str, Any]) -> date | None:
    if row.source_kind == "positions_meta":
        return _d((meta.get(row.source_key) or {}).get("last"))
    if row.source_kind == "freshness":
        return _d(fresh.get(row.source_key))
    if row.source_kind == "archive":
        return _d((archive.get(row.source_key) or {}).get("last"))
    return None


def _job_info(jobs: list[dict[str, Any]], job_id: str | None) -> dict[str, Any]:
    j = next((j for j in jobs if j.get("id") == job_id), None) if job_id else None
    if not j:
        return {"job_id": job_id, "last_run": None, "next_run": None}
    return {"job_id": job_id,
            "last_run": {"ts": j.get("last_run_ts"), "status": j.get("last_status"), "ms": j.get("last_latency_ms")},
            "next_run": j.get("next_run_ist")}


def _catchup_at(jobs: list[dict[str, Any]]) -> str | None:
    nexts = [str(j["next_run_ist"]) for j in jobs if j.get("id") in CATCHUP_JOBS and j.get("next_run_ist")]
    return min(nexts) if nexts else None


def _catalog_rows(payload: Any) -> list[CatalogRow]:
    """B1's catalog rows → CatalogRow (missing fields fall back to sensible defaults)."""
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    out: list[CatalogRow] = []
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        out.append(CatalogRow(
            id=str(r["id"]), label=str(r.get("label") or r["id"]), pages=tuple(r.get("pages") or ()),
            publisher=str(r.get("publisher") or ""), publish_time_ist=str(r.get("publish_time_ist") or ""),
            expected_by=r.get("expected_by"), max_age=int(r.get("max_age") or 2), ingest_job=r.get("ingest_job"),
            source_kind=str(r.get("source_kind") or "positions_meta"), source_key=str(r.get("source_key") or r["id"]),
            dictionary_anchor=str(r.get("dictionary_anchor") or ""), unrecoverable=bool(r.get("unrecoverable")),
            t_plus=int(r.get("t_plus") or 0), badge=str(r.get("badge") or "context"), note=r.get("note")))
    return out


def build_health(catalog: list[CatalogRow], meta: dict[str, Any], fresh: dict[str, Any], archive: dict[str, Any],
                 holidays: list[date], jobs: list[dict[str, Any]], gaps: set[str], now: datetime,
                 page: str | None = None) -> dict[str, Any]:
    rows = []
    for row in catalog:
        if page and page.upper() not in row.pages:
            continue
        as_of = _as_of_from_inputs(row, meta, fresh, archive)
        cls = classify(row, as_of, now, holidays, gap=row.id in gaps)
        rows.append({"id": row.id, "label": row.label, "pages": list(row.pages), "publisher": row.publisher,
                     "published_ist": row.publish_time_ist, "expected_by": row.expected_by, "as_of": as_of.isoformat() if as_of else None,
                     "lag_sessions": cls["lag_sessions"], "state": cls["state"], "unrecoverable": row.unrecoverable,
                     **_job_info(jobs, row.ingest_job), "catchup_at": _catchup_at(jobs) if cls["state"] in ("amber", "red") else None,
                     "note": cls["note"], "dictionary_anchor": row.dictionary_anchor, "badge": row.badge, "max_age_sessions": row.max_age})
    order = {"gap": 0, "red": 1, "amber": 2, "fresh": 3, "live": 4}
    rows.sort(key=lambda r: (order[r["state"]], -(r["lag_sessions"] or 0), r["id"]))
    summary = {"green": sum(r["state"] in ("fresh", "live") for r in rows), "amber": sum(r["state"] == "amber" for r in rows),
               "red": sum(r["state"] == "red" for r in rows), "gaps": sum(r["state"] == "gap" for r in rows), "rows": len(rows)}
    return {"rows": rows, "summary": summary, "last_session": last_close_session(now, holidays).isoformat()}


def now_ist() -> datetime:
    """The clock the view classifies against (tests pin it)."""
    return datetime.now(IST)


# ── the route ────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/health")
async def data_health(response: Response, page: str | None = Query(None, max_length=8, description="filter rows by terminal page")) -> dict:
    """Every catalogued dataset with its stored as-of, lag in sessions, state and job — the SYS › DATA view and the
    `DATA n STALE` header chip (PLAN 1.4). No composite score."""
    inputs = _Inputs()
    now = now_ist()
    meta = await inputs.get("positions_meta", f"{DATA_SVC}/db/nse-positions-meta") or {}
    fresh = await inputs.get("freshness", f"{DATA_SVC}/db/freshness") or {}
    archive = await inputs.get("archive_meta", f"{DATA_SVC}/db/archive-meta") or {}
    hol_payload = await inputs.get("holidays", f"{DATA_SVC}/db/market-holidays") or {}
    sched = await inputs.get("scheduler", f"{MASTER_CTL}/api/scheduler/status", route="live") or {}
    catalog_payload = await inputs.get("catalog", f"{DATA_SVC}/db/data-health/catalog")
    ingest_log = await inputs.get("ingest_log", f"{DATA_SVC}/db/data-health/ingest-log", {"days": 3})
    holidays = [d for d in (_d(h.get("date")) for h in (hol_payload.get("holidays") or []) if isinstance(h, dict)) if d]
    jobs = [j for j in (sched.get("jobs") or []) if isinstance(j, dict)]
    catalog = _catalog_rows(catalog_payload) if catalog_payload else []
    catalog_source = "data-service dataset_catalog" if catalog else "ui-api fallback seed (R-DATA §3; B1 dataset_catalog not deployed)"
    if not catalog:
        catalog = list(FALLBACK_CATALOG)
    gaps: set[str] = set()
    last = last_close_session(now, holidays).isoformat()
    for r in (ingest_log.get("rows") if isinstance(ingest_log, dict) else ingest_log) or []:
        if isinstance(r, dict) and str(r.get("status")) == "gap" and str(r.get("date") or "")[:10] == last:
            gaps.add(str(r.get("dataset")))
    built = build_health(catalog, meta if isinstance(meta, dict) else {}, fresh if isinstance(fresh, dict) else {},
                         archive if isinstance(archive, dict) else {}, holidays, jobs, gaps, now, page)
    cache_headers(response, merge_served(inputs.served))
    reachable = "positions_meta" not in inputs.errors
    return {
        "as_of": now.isoformat(timespec="seconds"), **built, "catalog_source": catalog_source,
        "inputs_unavailable": dict(inputs.errors), "controller_online": "scheduler" not in inputs.errors,
        "status": "ok" if reachable else "degraded", "service": "data-health",
        "data_service": {"reachable": reachable, "url_role": "data-service"},
        "note": f"state = stored vs expected (trading-day aware); lag in sessions behind {built['last_session']}; {DESCRIBES}",
        "badge": "arithmetic", "ok": not inputs.errors,
    }
