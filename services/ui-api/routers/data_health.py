"""GET /api/data/health — the data-health view (Terminal v2 PLAN 1.4, B3; R-DATA §10 spec).

One row per catalogued dataset: publisher, when it is published (IST), when the terminal expects it stored
(`expected_by`, trading-day aware), what is actually stored (`as_of`), how many sessions behind the last close it is,
a state (live | fresh | amber | red | gap), the ingest job's last run and next run, the catch-up slot, and the
dictionary anchor. Honest wording, no composite score: the page says "stored 30 Oct · expected by 21:00 ·
3 sessions behind · catch-up 19:30 tomorrow".

Two sources, said in `catalog_source`:

* **data-service `/db/data-health`** (B1 `data_health/`, the `dataset_catalog` rows with as-of / lag / state computed where
  the tables live — `MAX(column)` per table, dated archive files, NSE trading-day deadlines, the `data_gaps` rows). This
  view keeps B1's state and adds what only ui-api / the controller know: the job's last and next run, the catch-up slot,
  the honest sentence, and the rows B1 marks `unknown` (`freshness_kind = endpoint` / `cadence = live`): a job-backed row
  is judged by its job's last run against the due session, a never-stored live feed is `live` (its age is the page's
  SourceChip), anything else stays `unknown` and is counted as such — never guessed green.
* until B1 is deployed (`/db/data-health` 404), the built-in seed below (R-DATA §3's rows that the existing endpoints can
  already evaluate) classified here by `classify()`.

Nothing is fetched from a publisher on the request path: inputs are data-service `/db/data-health`,
`/db/nse-positions-meta`, `/db/freshness`, `/db/archive-meta`, `/db/market-holidays`, `/db/data-health/ingest-log`
(B1, optional) and master-controller `/api/scheduler/status`, each through the process-wide client and one
stale-while-revalidate cache (60 s refresh, 10 min bound).

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
STATES = ("live", "fresh", "amber", "red", "gap", "unknown")
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
    CatalogRow("nse_insider_trades", "Insider trades (PIT)", ("INSD",), "NSE API (single-filing feed)", "intimation ≈ T+2", "22:30", 4,
               "nse_insider_daily", "positions_meta", "nse_insider_trades", "NSE_DATA_DICTIONARY.md#insider"),
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


def _expected_at(row: CatalogRow, session: date, holidays: Iterable[date] = ()) -> datetime | None:
    """When `session`'s data is expected stored, as an IST datetime: `expected_by` on the session itself, or on the NEXT
    TRADING DAY (NSE holiday calendar, weekends skipped) for T+1 files and morning slots — a T−1 file for Friday is due
    Monday evening, not Saturday (check:B3-API: a Monday 20:00 MTF row was amber against a Saturday deadline)."""
    if not row.expected_by:
        return None
    hhmm = row.expected_by.split()[0]
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return None
    day = session
    if row.t_plus or time(h, m) < MARKET_CLOSE:        # a morning slot / T−1 file belongs to the next trading day
        day = next_trading_day(session, holidays)
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
    exp_at = _expected_at(row, target, hol)
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
    """The row's job from the controller: last run, next run, and a run in flight (m113: SYS › DATA said "last run 30 Oct"
    while tonight's capture was running; the controller's `running_since`, 6 Nov O-OPS)."""
    j = next((j for j in jobs if j.get("id") == job_id), None) if job_id else None
    if not j:
        return {"job_id": job_id, "last_run": None, "next_run": None, "running_since": None}
    running = j.get("running_since")
    last = ({"ts": running, "status": "running", "ms": None} if running
            else {"ts": j.get("last_run_ts"), "status": j.get("last_status"), "ms": j.get("last_latency_ms")})
    return {"job_id": job_id, "last_run": last, "next_run": j.get("next_run_ist"), "running_since": running}


# jobs whose next scheduled run itself catches every missed session up (they resume after the last stored day or replay
# from stored closes): their next run IS the catch-up. Any other job shows a catch-up only when the controller has one
# scheduled for it (`catchup_at` on /api/scheduler/status, M30: never a claim for a run that will not happen).
SELF_CATCHUP_JOBS = frozenset({"nse_positions_catchup", "eod_data_pipeline", "desk_daily", "alpha_shadow_daily",
                               "index_valuation_daily"})


def _catchup_at(jobs: list[dict[str, Any]], job_id: str | None = None) -> str | None:
    """When the row's dataset will actually be caught up: the controller's pending catch-up of its job, else the job's
    own next run for a self-catching job, else None (5 Nov review M30: every amber / red row used to show the 20:30
    pass's next run, even the S1 shadow's, which that pass never runs)."""
    j = next((x for x in jobs if job_id and x.get("id") == job_id), None)
    if j is None:
        return None
    if j.get("catchup_at"):
        return str(j["catchup_at"])
    return str(j["next_run_ist"]) if job_id in SELF_CATCHUP_JOBS and j.get("next_run_ist") else None


def _sentence(as_of: date | None, expected_by: str | None, lag: int | None, state: str, extra: str | None = None) -> str:
    """The honest line: "stored 30 Oct · expected by 21:00 · 3 sessions behind" (+ B1's own reason when it adds one)."""
    if as_of is None:
        words = "nothing stored"
    else:
        words = f"stored {as_of.strftime('%d %b')}"
        if expected_by:
            words += f" · expected by {expected_by}"
        if lag:
            words += f" · {lag} session{'s' if lag != 1 else ''} behind"
    if extra and extra not in words:
        words += f" · {extra}"
    return words


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=IST)


def _due_session(expected_by: Any, offset: Any, now: datetime, holidays: list[date]) -> date:
    """The latest session whose `expected_by` deadline (on the session, or `offset` trading days / a morning slot after
    it) has passed — the session a job-backed row must cover by now. Without a deadline: the last close."""
    last = last_close_session(now, holidays)
    if not expected_by:
        return last
    probe = CatalogRow(id="_", label="", pages=(), publisher="", publish_time_ist="", expected_by=str(expected_by), max_age=1,
                       ingest_job=None, source_kind="", source_key="", dictionary_anchor="", t_plus=int(offset or 0))
    s, hol = last, set(holidays)
    for _ in range(12):
        at = _expected_at(probe, s, holidays)
        if at is None or at <= now:
            return s
        s -= timedelta(days=1)
        while s.weekday() >= 5 or s in hol:
            s -= timedelta(days=1)
    return s


def _complete_unknown(r: dict[str, Any], jobs: list[dict[str, Any]], holidays: list[date], now: datetime) -> tuple[str, str]:
    """State + note for a row B1 reports `unknown` (endpoint / live): judged by its job's last run against the session it
    must cover by now (its `expected_by`, trading-day aware), never guessed green."""
    job_id = r.get("job_id")
    j = next((j for j in jobs if job_id and j.get("id") == job_id), None)
    if j is not None:
        ran = _parse_ts(j.get("last_run_ts"))
        due = _due_session(r.get("expected_by"), r.get("expected_offset_days"), now, holidays)
        if ran is None:
            return "red", f"job {job_id} has not run"
        ok = str(j.get("last_status") or "").lower() in ("ok", "success", "done")
        on_time = ran.astimezone(IST).date() >= due
        if ok and on_time:
            return "fresh", f"job {job_id} ran {ran.astimezone(IST).strftime('%d %b %H:%M')} (ok)"
        return "amber", f"job {job_id} last ran {ran.astimezone(IST).strftime('%d %b %H:%M')} ({j.get('last_status') or 'unknown'})"
    if str(r.get("cadence")) == "live" or not job_id:
        return "live", "live feed, not stored: its age is the page's SourceChip"
    return "unknown", f"job {job_id} not in the controller's schedule"


def compose_b1_health(payload: Any, jobs: list[dict[str, Any]], holidays: list[date], now: datetime,
                      page: str | None = None) -> dict[str, Any] | None:
    """data-service `/db/data-health` (B1: state computed where the tables live) → this view's rows; None when the payload
    carries no rows (B1 not deployed → the caller falls back to the seed)."""
    rows_in = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows_in, list) or not rows_in:
        return None
    rows: list[dict[str, Any]] = []
    for r in rows_in:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        pages = r.get("pages") or []
        pages = [p for p in (pages.split(",") if isinstance(pages, str) else pages) if p]
        if page and page.upper() not in pages:
            continue
        as_of = _d(r.get("as_of"))
        state = str(r.get("state") or "unknown")
        lag = r.get("lag_sessions") if isinstance(r.get("lag_sessions"), int) else None
        if state == "unknown":
            state, why = _complete_unknown(r, jobs, holidays, now)
            note = why if as_of is None else _sentence(as_of, r.get("expected_by"), lag, state, why)
        elif state == "gap":
            note = r.get("note") or "no capture for the session (gap row)"
        else:
            note = _sentence(as_of, r.get("expected_by"), lag, state, r.get("note"))
        if state not in STATES:
            state = "unknown"
        rows.append({"id": str(r["id"]), "label": str(r.get("label") or r["id"]), "pages": pages, "publisher": r.get("publisher"),
                     "published_ist": r.get("published_ist"), "expected_by": r.get("expected_by"), "as_of": as_of.isoformat() if as_of else None,
                     "lag_sessions": lag, "state": state, "unrecoverable": bool(r.get("unrecoverable")),
                     **_job_info(jobs, r.get("job_id")), "catchup_at": _catchup_at(jobs, r.get("job_id")) if state in ("amber", "red") else None,
                     "note": note, "dictionary_anchor": r.get("dictionary_anchor") or "", "badge": r.get("badge") or "context",
                     "max_age_sessions": r.get("max_age_sessions"), "job_check": r.get("job_check")})
    return {"rows": _sorted(rows), "summary": _summary(rows),
            "last_session": str(payload.get("last_session") or last_close_session(now, holidays).isoformat())}


def _sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"gap": 0, "red": 1, "amber": 2, "unknown": 3, "fresh": 4, "live": 5}
    return sorted(rows, key=lambda r: (order[r["state"]], -(r["lag_sessions"] or 0), r["id"]))


def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {"green": sum(r["state"] in ("fresh", "live") for r in rows), "amber": sum(r["state"] == "amber" for r in rows),
            "red": sum(r["state"] == "red" for r in rows), "gaps": sum(r["state"] == "gap" for r in rows),
            "unknown": sum(r["state"] == "unknown" for r in rows), "rows": len(rows)}


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
                     **_job_info(jobs, row.ingest_job), "catchup_at": _catchup_at(jobs, row.ingest_job) if cls["state"] in ("amber", "red") else None,
                     "note": cls["note"], "dictionary_anchor": row.dictionary_anchor, "badge": row.badge, "max_age_sessions": row.max_age})
    return {"rows": _sorted(rows), "summary": _summary(rows), "last_session": last_close_session(now, holidays).isoformat()}


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
    hol_payload = await inputs.get("holidays", f"{DATA_SVC}/db/market-holidays") or {}
    sched = await inputs.get("scheduler", f"{MASTER_CTL}/api/scheduler/status", route="live") or {}
    b1_health = await inputs.get("b1_health", f"{DATA_SVC}/db/data-health")
    holidays = [d for d in (_d(h.get("date")) for h in (hol_payload.get("holidays") or []) if isinstance(h, dict)) if d]
    jobs = [j for j in (sched.get("jobs") or []) if isinstance(j, dict)]
    built = compose_b1_health(b1_health, jobs, holidays, now, page)
    if built is not None:
        catalog_source = "data-service dataset_catalog (/db/data-health)"
        reachable = True
    else:
        b1_err = inputs.errors.get("b1_health", "")
        if b1_err.startswith("404"):                       # expected until B1's package is deployed: not an input failure
            inputs.errors.pop("b1_health")
            catalog_source = "ui-api fallback seed (R-DATA §3; B1 dataset_catalog not deployed)"
        else:
            catalog_source = f"ui-api fallback seed (R-DATA §3; data-service /db/data-health unavailable: {b1_err or 'no rows'})"
        meta = await inputs.get("positions_meta", f"{DATA_SVC}/db/nse-positions-meta") or {}
        fresh = await inputs.get("freshness", f"{DATA_SVC}/db/freshness") or {}
        archive = await inputs.get("archive_meta", f"{DATA_SVC}/db/archive-meta") or {}
        ingest_log = await inputs.get("ingest_log", f"{DATA_SVC}/db/data-health/ingest-log", {"days": 3})
        gaps: set[str] = set()
        last = last_close_session(now, holidays).isoformat()
        for r in (ingest_log.get("rows") if isinstance(ingest_log, dict) else ingest_log) or []:
            if isinstance(r, dict) and str(r.get("status")) == "gap" and str(r.get("date") or "")[:10] == last:
                gaps.add(str(r.get("dataset")))
        built = build_health(list(FALLBACK_CATALOG), meta if isinstance(meta, dict) else {}, fresh if isinstance(fresh, dict) else {},
                             archive if isinstance(archive, dict) else {}, holidays, jobs, gaps, now, page)
        reachable = "positions_meta" not in inputs.errors
    cache_headers(response, merge_served(inputs.served))
    return {
        "as_of": now.isoformat(timespec="seconds"), **built, "catalog_source": catalog_source,
        "inputs_unavailable": dict(inputs.errors), "controller_online": "scheduler" not in inputs.errors,
        "status": "ok" if reachable else "degraded", "service": "data-health",
        "data_service": {"reachable": reachable, "url_role": "data-service"},
        "note": f"state = stored vs expected (trading-day aware); lag in sessions behind {built['last_session']}; {DESCRIBES}",
        "badge": "arithmetic", "ok": not inputs.errors,
    }
