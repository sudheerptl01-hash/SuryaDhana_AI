"""
GOLD — the gold terminal page's API (GOLD program phase 2, PLAN §d), mounted at /api/gold.

Composes, never re-implements (PLAN §d rules):
  * gold_preopen — the fair-open model, the ICICI master, the ONE Yahoo fetcher (`gold_preopen._yahoo_bars_cached`),
    the accuracy log, the duty constant, the MCX calendar helpers;
  * mcx — the Breeze quote path (its 15 s TTL and the 10-min broken memory stay), the contract family (incl. GOLDTEN),
    the cost card;
  * shared/mcx_specs — sessions, expiries, costs;
  * data-service `/db/gold/*` (B1) — every stored series, read through one stale-while-revalidate cache
    (`SWRCache("gold.store")`, refresh 120 s, bound 900 s), never a publisher on the request path (PLAN 0.1 #3).

Honesty rules baked in (PLAN §f): every block carries `freshness {source, as_of, age_s, state}` where state is
live | delayed | stale | unavailable; a series renders only when the catalog carries a PUBLISH-* verdict for it
(`published: false` otherwise — "no verdict — not published"); context metrics carry the `context` badge with the
study that failed them; the health verdict is a sentence of thresholded clauses, has NO score key and ends
"describes, does not predict". Nothing here feeds the Decision Desk, the S1 shadow, directional alerts or the paper
ticket's price (PLAN 0.1 #7).

Purity: async handlers never block — the master and Breeze go through asyncio.to_thread (inside gold_preopen / mcx),
data-service through httpx.AsyncClient, the LEARN files through to_thread. Headers: X-Cache / X-Cache-Age say how old
the oldest stored piece of a response is (cache.cache_headers), never the body.

Every number is a number; dates are ISO strings; IST timestamps carry the offset. The contract as implemented is
written to reports/gold_program/API_CONTRACT.md (B4A/B4B read it).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import statistics
import sys
import time
from collections.abc import Awaitable, Iterable
from datetime import date, datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import httpx
from cache import Served, SWRCache, TTLCache, cache_headers, merge_served
from errors import degraded, fail
from fastapi import APIRouter, Body, Query, Response

from routers import gold_preopen as gp
from routers import mcx as mcxr
from routers._upstream import upstream_detail

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared import mcx_specs as specs

router = APIRouter()
_log = logging.getLogger("ui-api.gold")

IST = gp.IST
NY = gp.NY
LONDON = ZoneInfo("Europe/London")
SHANGHAI = ZoneInfo("Asia/Shanghai")
GRAMS_PER_TROY_OZ = gp.GRAMS_PER_TROY_OZ
OZ_PER_CONTRACT = 100.0  # COMEX GC
TONNES_PER_MOZ = 31.1034768  # 1 million troy oz = 31.1 t
USDINR_LOT_USD = 1000.0  # NSE currency futures lot

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
_DB_TIMEOUT = httpx.Timeout(10.0, read=25.0)
STORE = SWRCache("gold.store", max_items=256, refresh_after=120.0, max_age=900.0)
_ttl = TTLCache("gold", max_items=64, default_ttl=60.0)
HEALTH_TTL_S = 60.0
CATALOG_TTL_S = 3600.0
OVERVIEW_TTL_S = 30.0
LEARN_TTL_S = 3600.0
STORE_DOWN_TTL_S = 15.0  # one failed data-service call per path per 15 s, not one per gauge
CHASE_LIMIT_INR = 300.0  # the desk's chase limit (gold_preopen's default `threshold`): a house rule, badge `heuristic`
TREND_BARS_DAYS = 1100  # the TREND gauge's daily-bar window: 3 y for percentile_3y (≈ 760 sessions), 200 d MA, 52-w high

BADGE_CONTEXT, BADGE_ARITH, BADGE_HEURISTIC = "context", "arithmetic", "heuristic"
EVIDENCE_CONTEXT = "context · G-STUDY 26 Oct 2026: no forecasting power"
CROWD_LABEL = "crowdedness, not a signal — no forecasting power 2006–2026 (G-STUDY)"
DESCRIBES = "describes, does not predict"
COT_FOOTER = (
    "weekly, Tuesday positions, released Friday 15:30 ET; no daily, no OTC, categories only; "
    "our test found no timing value (G-STUDY 26 Oct 2026)"
)
COT_RAW_URL = "https://www.cftc.gov/dea/futures/deacmxsf.htm"
COT_API_QUERY = (
    "https://publicreporting.cftc.gov/resource/72hh-3qpy.json?cftc_contract_market_code=088691"
    "&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=2"
)
REUTERS_LINK = "https://www.reuters.com/markets/commodities/"  # link-only: never fetched
LEARN_DIR_DEFAULT = Path(__file__).resolve().parents[3] / "reports" / "gold_program" / "G-EDU"

# DXY weights (ICE): EUR 57.6 %, JPY 13.6 %, GBP 11.9 %, CAD 9.1 %, SEK 4.2 %, CHF 3.6 % — the replicable basket of the
# KGX split (SOURCES.md M56; PLAN j.2 #11: DXY weights + a separate rupee leg).
DXY_WEIGHTS: dict[str, tuple[float, int]] = {  # series_id → (weight, +1 when the quote is foreign-per-USD)
    "FX_EURUSD": (0.576, -1),
    "FX_JPY": (0.136, +1),
    "FX_GBPUSD": (0.119, -1),
    "FX_CAD": (0.091, +1),
    "FX_SEK": (0.042, +1),
    "FX_CHF": (0.036, +1),
}

# COT trader groups (disaggregated report) in the order the "who is long / who is short" bars show them.
COT_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("mm", "Managed money (funds / CTAs)", "mm"),
    ("or", "Other reportables", "or"),
    ("nr", "Non-reportable (small specs)", "nr"),
    ("sd", "Swap dealers (banks' OTC book)", "sd"),
    ("pm", "Producer / merchant (miners, refiners, jewellers)", "pm"),
)
COT_SERIES_ID = "COT_DISAGG_F"  # the catalog row the positioning panels are gated on (B1 catalog seed)
GC_FRONT = "GC=F"  # data-service stores Yahoo symbols in gold_daily_bars / gold_bars_intraday
GC_FRONT_SERIES = "COMEX_GC_FRONT"  # … and catalogs them under this series_id (gate + max_age)
DXY_SYMBOL = "DX-Y.NYB"  # the DXY_CLOSE catalog row's Yahoo symbol in gold_daily_bars (the dollar gauge's fallback read)
DXY_SOURCE_LABEL = {  # the dollar tile is labelled by the series actually used (C-DATA-4): never DTWEXBGS under the DXY name
    "DXY_CLOSE": "Dollar index (DXY)",
    "FRED_DTWEXBGS": "Fed broad USD index (DTWEXBGS, weekly lag — not DXY)",
}
CME_GOLD_PRODUCTS = ("GC", "MGC", "1OZ", "QO", "OG")
MICRO_GOLD_CODE, GOLD_CODE = "088695", "088691"
STALE_COT_DAYS = 10.0  # a release older than this = catch-up / shutdown flag (PLAN c.3)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# data-service reads: store, then show
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


class StoreUnavailable(RuntimeError):
    """data-service could not answer (down, no gold tables yet, or an error): the block degrades, never the page."""


async def _db_fetch(path: str, params: dict[str, Any]) -> Any:
    try:
        async with httpx.AsyncClient(timeout=_DB_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}{path}", params=params)
    except httpx.HTTPError as exc:
        raise StoreUnavailable(f"data-service unreachable ({type(exc).__name__})") from exc
    if r.status_code == 404:
        raise StoreUnavailable("data-service has no gold tables yet (404)")
    if r.status_code != 200:
        raise StoreUnavailable(f"data-service {r.status_code}: {str(upstream_detail(r, 120))[:120]}")
    try:
        return r.json()
    except ValueError as exc:
        raise StoreUnavailable("data-service answered non-JSON") from exc


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Rows from any of data-service's reply shapes ({rows:[…]}, {data:[…]}, {columns, data}, a bare list)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("rows"), list):
        return [r for r in payload["rows"] if isinstance(r, dict)]
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], list) and isinstance(payload.get("columns"), list):
        cols = payload["columns"]
        return [dict(zip(cols, row)) for row in data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


class Reads:
    """What one request read from the store: the Served entries (for X-Cache headers) and the per-path errors."""

    def __init__(self) -> None:
        self.served: list[Served[Any]] = []
        self.errors: dict[str, str] = {}

    async def get(self, path: str, **params: Any) -> Any | None:
        clean = {k: v for k, v in params.items() if v is not None}
        key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
        down = _ttl.get(f"down:{path}")
        if down is not None:
            self.errors[path] = str(down)
            return None
        try:
            served = await STORE.get(key, lambda: _db_fetch(path, clean))
        except StoreUnavailable as exc:
            _ttl.set(f"down:{path}", str(exc), ttl=STORE_DOWN_TTL_S)
            self.errors[path] = str(exc)
            return None
        except Exception as exc:  # noqa: BLE001
            self.errors[path] = f"{type(exc).__name__}"
            return None
        self.served.append(served)
        return served.value

    def headers(self, response: Response | None) -> None:
        cache_headers(response, merge_served(self.served))


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# pure helpers (unit-tested): dates, points, resampling, PIT, freshness, labels
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _d(value: Any) -> date | None:
    """A date from an ISO date / datetime string or a date; None when it is not one."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _dt(value: Any) -> datetime | None:
    """An aware datetime (UTC when naive) from an ISO string / datetime; None otherwise."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _f(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _dd(value: Any) -> date:
    """A date, or date.min when `value` is not one (for rows a caller has already filtered with `_d`)."""
    return _d(value) or date.min


def _ff(value: Any) -> float:
    """A float, or 0.0 when `value` is not one (callers guard with `_f(...) is not None` / truthiness first)."""
    v = _f(value)
    return 0.0 if v is None else v


async def _gather(*aws: Awaitable[Any]) -> list[Any]:
    """asyncio.gather with return_exceptions=True as a plain list (one shape for every route's reads)."""
    pending = asyncio.gather(*aws, return_exceptions=True)
    return list(await pending)


def _r(value: float | None, nd: int = 2) -> float | None:
    return None if value is None else round(value, nd)


def _now_ist() -> datetime:
    return datetime.now(IST)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(IST).isoformat(timespec="seconds") if dt else None


def _iso_any(value: Any) -> str | None:
    """Every datetime the page receives carries an offset (critics C-TRADER-1 / C-DATA-1 / C-DATA-6, 5 Nov 2026): a stored
    zone-less timestamp is UTC (data-service writes `tz_convert('UTC').tz_localize(None)`) and comes out as IST ISO with
    `+05:30`; a date-only string (`YYYY-MM-DD`) is a date and passes through unchanged; anything else → None."""
    if value is None:
        return None
    s = str(value)
    if len(s) == 10 and "T" not in s and " " not in s:
        return s if _d(s) else None
    return _iso(_dt(value))


def _points(rows: Iterable[dict[str, Any]], date_key: str = "report_date", value_key: str = "value") -> list[dict[str, Any]]:
    """Sorted {report_date, value, release_at} points from rows (rows without a date or a finite value are dropped)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        d, v = _d(r.get(date_key)), _f(r.get(value_key))
        if d is None or v is None:
            continue
        out.append({"report_date": d.isoformat(), "value": v, "release_at": r.get("release_at")})
    out.sort(key=lambda p: (p["report_date"], str(p.get("release_at") or "")))
    return out


def asof_filter(points: list[dict[str, Any]], asof: datetime | None) -> list[dict[str, Any]]:
    """Point-in-time: keep the latest release of each report_date that was public at `asof` (PLAN 0.1 #4). Points
    without a release_at are treated as always public."""
    best: dict[str, dict[str, Any]] = {}
    for p in points:
        rel = _dt(p.get("release_at"))
        if asof is not None and rel is not None and rel > asof:
            continue
        cur = best.get(p["report_date"])
        if cur is None or (_dt(p.get("release_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= (
            _dt(cur.get("release_at")) or datetime.min.replace(tzinfo=timezone.utc)
        ):
            best[p["report_date"]] = p
    return [best[k] for k in sorted(best)]


def week_end(d: date) -> date:
    """The Friday that ends the week of `d` (Saturday/Sunday points belong to the following week's Friday)."""
    return d + timedelta(days=(4 - d.weekday()) % 7)


def month_end(d: date) -> date:
    import calendar

    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def resample_points(points: list[dict[str, Any]], freq: str, how: str = "last") -> list[dict[str, Any]]:
    """D: as is. W: one point per Friday-ending week. M: one per month end. `how` = last | sum | mean (the catalog's
    `resample`). The bucket's release_at is the latest of its members."""
    freq = (freq or "D").upper()
    if freq == "D" or not points:
        return list(points)
    bucket_of = week_end if freq == "W" else month_end
    buckets: dict[str, list[dict[str, Any]]] = {}
    for p in points:
        d = _d(p["report_date"])
        if d is None:
            continue
        buckets.setdefault(bucket_of(d).isoformat(), []).append(p)
    out: list[dict[str, Any]] = []
    for key in sorted(buckets):
        members = buckets[key]
        vals = [m["value"] for m in members]
        value = sum(vals) if how == "sum" else (sum(vals) / len(vals) if how == "mean" else vals[-1])
        rel = max((str(m.get("release_at") or "") for m in members), default="") or None
        out.append({"report_date": key, "value": value, "release_at": rel, "n": len(members)})
    return out


def change_over(points: list[dict[str, Any]], days: int) -> tuple[float | None, float | None, str | None]:
    """(latest value, value `days` calendar days earlier or the nearest before, that date)."""
    if not points:
        return None, None, None
    last = points[-1]
    target = _dd(last["report_date"]) - timedelta(days=days)
    earlier = [p for p in points if _dd(p["report_date"]) <= target]
    if not earlier:
        return last["value"], None, None
    return last["value"], earlier[-1]["value"], earlier[-1]["report_date"]


def pct_rank(values: list[float], x: float) -> float | None:
    """Percentile (0–100) of x within values."""
    if not values:
        return None
    return round(100.0 * sum(1 for v in values if v <= x) / len(values), 1)


def window_values(points: list[dict[str, Any]], days: int) -> list[float]:
    if not points:
        return []
    cutoff = _dd(points[-1]["report_date"]) - timedelta(days=days)
    return [p["value"] for p in points if _dd(p["report_date"]) >= cutoff]


def cot_index(values: list[float], n: int) -> float | None:
    """100 × (N − min) / (max − min) over the last n reports (SOURCES.md M17)."""
    tail = values[-n:]
    if len(tail) < max(2, n // 2) or max(tail) == min(tail):
        return None
    return round(100.0 * (tail[-1] - min(tail)) / (max(tail) - min(tail)), 1)


def zscore(values: list[float], n: int) -> float | None:
    tail = values[-n:]
    if len(tail) < max(3, n // 2):
        return None
    sd = statistics.pstdev(tail)
    return round((tail[-1] - statistics.fmean(tail)) / sd, 2) if sd > 0 else None


def quadrant_label(dprice: float | None, doi: float | None) -> str | None:
    """OI × price (SOURCES.md M28): + + long build-up · − + short build-up · + − short covering · − − long unwinding."""
    if dprice is None or doi is None:
        return None
    if doi >= 0:
        return "long build-up" if dprice >= 0 else "short build-up"
    return "short covering" if dprice >= 0 else "long unwinding"


def who_did(d_long: float | None, d_short: float | None) -> list[str]:
    """ΔL < 0 closed longs · ΔS < 0 covered shorts · ΔL > 0 new longs · ΔS > 0 new shorts (M14)."""
    out: list[str] = []
    if d_long is not None and d_long != 0:
        out.append(f"{'new' if d_long > 0 else 'closed'} {abs(d_long):,.0f} longs")
    if d_short is not None and d_short != 0:
        out.append(f"{'new' if d_short > 0 else 'covered'} {abs(d_short):,.0f} shorts")
    return out or ["no change"]


# ── the weekly fund-driver label: a byte-for-byte MIRROR of data-service `gold/driver_rule.py` (B1, wave 1c — the ONE rule;
# critics C-TRADER-3 / C-BEGINNER-1 / C-DATA-15: the old rule said "new shorts" on the 27 Oct 2026 week where funds added
# 1,538 longs and 182 shorts). `test_driver_label_mirrors_data_service` loads that file by path and checks every branch —
# change both or neither. The net-sign test comes FIRST (a label never contradicts the net change printed under it), then
# the bigger bearish (bullish) leg; a tie goes to the closing leg. No word without a price change or when neither leg moved.
DRIVER_LABELS_DOWN: tuple[str, str, str] = ("funds bought the dip", "long liquidation", "new shorts")
DRIVER_LABELS_UP: tuple[str, str, str] = ("funds sold into it", "short covering", "new longs")
DRIVER_LABELS: frozenset[str] = frozenset(DRIVER_LABELS_DOWN + DRIVER_LABELS_UP)
DRIVER_RULE_TEXT = (
    "down week: funds bought the dip if the net rose; else long liquidation if ΔL<0 and |ΔL| ≥ max(ΔS,0); else new shorts · "
    "up week, mirrored: funds sold into it if the net fell; else short covering if ΔS<0 and |ΔS| ≥ max(ΔL,0); else new longs "
    "— the label is the bigger of the two legs and never contradicts the net change"
)


def _rule_num(v: Any) -> float | None:
    """driver_rule._num: a finite float, never a bool, else None."""
    return None if isinstance(v, bool) else _f(v)


def driver_label(d_long: float | None, d_short: float | None, price_chg_pct: float | None) -> str | None:
    """The fund-driver word for one COT week (`DRIVER_RULE_TEXT`; data-service `driver_rule.driver_label(dp, dl, ds)` with
    ui-api's historical argument order). None without all three inputs, on a week with no price change or when neither
    leg moved — the page then prints the who-did counts alone. Worked example, 27 Oct 2026: ΔL +1,538, ΔS +182, price
    −1.64 % → "funds bought the dip" (net +1,356); its mirror (ΔL −1,538, ΔS −182, price up) → "funds sold into it"."""
    dp, dl, ds = _rule_num(price_chg_pct), _rule_num(d_long), _rule_num(d_short)
    if dp is None or dl is None or ds is None or dp == 0.0 or (dl == 0.0 and ds == 0.0):
        return None
    net = dl - ds
    if dp < 0:
        if net > 0:
            return DRIVER_LABELS_DOWN[0]
        if dl < 0 and abs(dl) >= max(ds, 0.0):
            return DRIVER_LABELS_DOWN[1]
        return DRIVER_LABELS_DOWN[2]
    if net < 0:
        return DRIVER_LABELS_UP[0]
    if ds < 0 and abs(ds) >= max(dl, 0.0):
        return DRIVER_LABELS_UP[1]
    return DRIVER_LABELS_UP[2]


def driver_clause(label: str | None) -> str | None:
    """The verdict's H3 wording of the driver label — the disagreement labels read as a verb phrase, the leg labels as is."""
    if not label:
        return None
    return {"funds bought the dip": "bought the dip", "funds sold into it": "sold into it"}.get(label, label)


def annualised_carry_pct(f1: float | None, f2: float | None, days: int | None) -> float | None:
    """(F2/F1 − 1) × 365 / days, in % (SOURCES.md M31)."""
    if not f1 or not f2 or not days or days <= 0:
        return None
    return round((f2 / f1 - 1) * 365 / days * 100, 2)


def freshness(
    as_of: Any, max_age_days: float | None, source: str, now: datetime | None = None, live: bool = False
) -> dict[str, Any]:
    """{source, as_of, age_s, state} — live (from a live feed just now) · delayed (stored, inside the catalog's
    max_age_days) · stale (older) · unavailable (no value)."""
    now = now or _now_ist()
    if as_of is None:
        return {"source": source, "as_of": None, "age_s": None, "state": "unavailable"}
    dt = _dt(as_of)
    if dt is None:
        d = _d(as_of)
        dt = datetime.combine(d, datetime.min.time(), tzinfo=IST) if d else None
    if dt is None:
        return {"source": source, "as_of": None, "age_s": None, "state": "unavailable"}
    age_s = max(0.0, (now - dt).total_seconds())
    if live:
        state = "live"
    elif max_age_days is not None and age_s > max_age_days * 86400:
        state = "stale"
    else:
        state = "delayed"
    return {
        "source": source,
        "as_of": _iso(dt) if isinstance(as_of, str) and "T" in as_of else str(as_of)[:10],
        "age_s": int(age_s),
        "state": state,
    }


def _window_days(window: str) -> int:
    return {"D": 1, "W": 7, "M": 30}.get((window or "W").upper(), 7)


def window_anchor(points: list[dict[str, Any]], window: str, today: date) -> dict[str, Any]:
    """The verdict window's "then" point (critic C-TRADER-16, 5 Nov 2026 — the old trailing-7-calendar-day window called
    a +4.6 % calendar week "+0.7 % over the week"). `W` = Monday-to-date once the week has a session: the last close BEFORE
    this week's Monday (a Sat/Sun reads the full week); before the week's first session (a Monday pre-bar) the trailing
    5 sessions, labelled so. `M` = month-to-date the same way (else 30 calendar days). `D` = the previous session.
    Returns {then: point|null, from_date, label, sessions} — `sessions` is how many stored sessions the window spans."""
    w = (window or "W").upper()
    if not points:
        return {"then": None, "from_date": None, "label": None, "sessions": 0}
    last = points[-1]
    if w == "D":
        then = points[-2] if len(points) > 1 else None
        return {"then": then, "from_date": then["report_date"] if then else None, "label": "vs the previous session", "sessions": 1}
    start = today - timedelta(days=today.weekday()) if w == "W" else today.replace(day=1)
    in_window = [p for p in points if _dd(p["report_date"]) >= start]
    before = [p for p in points if _dd(p["report_date"]) < start]
    if in_window and before and _dd(last["report_date"]) >= start:
        then = before[-1]
        word = "week" if w == "W" else "month"
        return {
            "then": then,
            "from_date": then["report_date"],
            "label": f"{word} to date (since the {_day_label(then['report_date'])} close)",
            "sessions": len(in_window),
        }
    if w == "W":
        then = points[-6] if len(points) >= 6 else None
        return {"then": then, "from_date": then["report_date"] if then else None, "label": "5 sessions", "sessions": 5}
    _, _, from_date = change_over(points, 30)
    then = next((p for p in reversed(points) if p["report_date"] == from_date), None) if from_date else None
    return {"then": then, "from_date": from_date, "label": "30 days", "sessions": len(window_values(points, 30))}


def session_bands(day: date) -> list[dict[str, Any]]:
    """The 24-h chart's session bands in IST for `day` (PLAN a.3, DST-aware via zoneinfo; fixed where the exchange
    has no DST): Sydney/Tokyo · Shanghai (SGE) day + night · London · New York · COMEX maintenance hour · MCX."""

    def local(tz: ZoneInfo, hh: int, mm: int, offset_days: int = 0) -> str:
        d = day + timedelta(days=offset_days)
        return datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(IST).isoformat(timespec="minutes")

    bands: list[dict[str, Any]] = [
        {"name": "Sydney / Tokyo", "start_ist": local(IST, 3, 30), "end_ist": local(IST, 11, 30)},
        {"name": "Shanghai (SGE) day", "start_ist": local(SHANGHAI, 9, 0), "end_ist": local(SHANGHAI, 15, 30)},
        {"name": "Shanghai (SGE) night", "start_ist": local(SHANGHAI, 20, 0), "end_ist": local(SHANGHAI, 2, 30, 1)},
        {"name": "London", "start_ist": local(LONDON, 8, 0), "end_ist": local(LONDON, 16, 30)},
        {"name": "New York (COMEX floor hours)", "start_ist": local(NY, 9, 0), "end_ist": local(NY, 13, 30)},
        {"name": "COMEX maintenance (no Globex)", "start_ist": local(NY, 17, 0), "end_ist": local(NY, 18, 0), "hatched": True},
    ]
    win = specs.trading_window(day)
    bands.append(
        {
            "name": "MCX",
            "start_ist": win[0].isoformat(timespec="minutes") if win else None,
            "end_ist": win[1].isoformat(timespec="minutes") if win else None,
            "closed": win is None,
            "bar": True,
        }
    )
    return bands


# ── CFTC COT release calendar (SOURCES.md B10, G-COT §3.5) — the same rule data-service stamps release_at with ────────
# (services/data-service/gold/pit.py: tests/test_gold.py::test_cot_release_calendar_matches_data_service keeps the two
# equal). Tuesday positions are released Friday 15:30 ET; a federal holiday later in the report week (Wed–Fri, or the
# Tuesday itself) pushes the release to the following Monday. The CFTC's published 2026 schedule is pinned explicitly so
# a drift in the holiday rule can never move a published date. The stored row's release_at stays the truth for the
# CURRENT report; this calendar is for the NEXT one (and for /calendar's COT_RELEASE rows before the store has them).
COT_RELEASE_PUBLISHED: dict[date, date] = {
    date(2025, 12, 30): date(2026, 1, 5),
    date(2026, 6, 16): date(2026, 6, 22),
    date(2026, 6, 30): date(2026, 7, 6),
    date(2026, 11, 10): date(2026, 11, 16),
    date(2026, 11, 24): date(2026, 11, 30),
    date(2026, 12, 22): date(2026, 12, 28),
}


def _observed_holiday(d: date) -> date:
    """A federal holiday on a Saturday is observed on the Friday, on a Sunday on the Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def us_federal_holidays(year: int) -> set[date]:
    """The observed US federal holidays (the CFTC's closures): New Year, MLK, Presidents, Memorial, Juneteenth (2021→),
    Independence, Labor, Columbus, Veterans, Thanksgiving, Christmas."""
    hol = {
        _observed_holiday(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed_holiday(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed_holiday(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        _observed_holiday(date(year, 12, 25)),
    }
    if year >= 2021:
        hol.add(_observed_holiday(date(year, 6, 19)))
    return hol


def cot_release_date(report_date: date) -> tuple[date, str]:
    """(release date, source) for a COT report_date: `published` (the CFTC's 2026 schedule) or `rule` (Friday 15:30 ET;
    the Monday after a federal holiday that falls Wed–Fri of the report week or on the Tuesday itself)."""
    if report_date in COT_RELEASE_PUBLISHED:
        return COT_RELEASE_PUBLISHED[report_date], "published"
    days_to_friday = (4 - report_date.weekday()) % 7 or 7  # a Friday-dated report releases the next Friday
    friday = report_date + timedelta(days=days_to_friday)
    hol = us_federal_holidays(report_date.year) | us_federal_holidays(friday.year)
    if any((report_date + timedelta(days=i)) in hol for i in range(1, days_to_friday + 1)):
        return friday + timedelta(days=3), "rule"
    return friday, "rule"


def cot_release_at_ist(report_date: date) -> datetime:
    """15:30 ET on the release date, as an IST datetime (DST-aware: 01:00 IST in summer, 02:00 IST in winter)."""
    rel, _ = cot_release_date(report_date)
    return datetime(rel.year, rel.month, rel.day, 15, 30, tzinfo=NY).astimezone(IST)


def cot_release_label(dt: datetime) -> str:
    """How a release instant is named on the page and in the Saturday digest (PLAN a.6 p.hero): `Sat 31 Oct 01:00 IST`."""
    return f"{dt.astimezone(IST):%a %d %b %H:%M} IST"


def next_cot_release(report_date: date, now: datetime | None = None, release_at: Any = None) -> dict[str, Any]:
    """The NEXT scheduled COT release after the current report's own release (and after `now`, so a stale store still
    names an upcoming date): `{report_date, at, ist, source}` — `at` ISO with the IST offset, `ist` the label."""
    now = now or _now_ist()
    floor = _dt(release_at) or cot_release_at_ist(report_date)
    floor = max(floor, now)
    rd = report_date
    for _ in range(60):  # a shutdown catch-up can leave the store a year behind; never loop forever
        rd = rd + timedelta(days=7)
        at = cot_release_at_ist(rd)
        if at > floor:
            return {
                "report_date": rd.isoformat(),
                "at": at.isoformat(timespec="minutes"),
                "ist": cot_release_label(at),
                "source": cot_release_date(rd)[1],
            }
    at = cot_release_at_ist(rd)
    return {"report_date": rd.isoformat(), "at": at.isoformat(timespec="minutes"), "ist": cot_release_label(at), "source": "rule"}


def next_cot_release_ist(report_date: date) -> str:
    """The release instant (ISO, IST offset) of the report dated `report_date` by the holiday-aware calendar."""
    return cot_release_at_ist(report_date).isoformat(timespec="minutes")


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# catalog + rendering gate
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


async def catalog(reads: Reads) -> dict[str, dict[str, Any]]:
    hit = _ttl.get("catalog")
    if hit is not None:
        return hit
    rows = _rows(await reads.get("/db/gold/catalog"))
    cat = {str(r["series_id"]): r for r in rows if r.get("series_id")}
    if cat:
        _ttl.set("catalog", cat, ttl=CATALOG_TTL_S)
    return cat


def is_published(cat: dict[str, dict[str, Any]], series_id: str) -> bool:
    """PLAN f.2, strict: a series renders only with a PUBLISH-* catalog row. An EMPTY catalog (data-service down before
    the 3600 s memo filled, or the seed not yet run) publishes NOTHING — the block says why (`unpublished_note`)."""
    row = cat.get(series_id)
    return row is not None and str(row.get("verdict") or "").upper().startswith("PUBLISH")


def unpublished_note(cat: dict[str, dict[str, Any]], series_id: str) -> str:
    """The reason a block renders no number: no catalog at all, or no PUBLISH-* verdict for this series."""
    if not cat:
        return "catalog unavailable — not published"
    return "no verdict — not published"


def badge_of(cat: dict[str, dict[str, Any]], series_id: str, default: str = BADGE_CONTEXT) -> str:
    row = cat.get(series_id) or {}
    return str(row.get("badge") or default)


def max_age_of(cat: dict[str, dict[str, Any]], series_id: str, default: float = 4.0) -> float:
    row = cat.get(series_id) or {}
    v = _f(row.get("max_age_days"))
    return v if v is not None else default


def catalog_about(cat: dict[str, dict[str, Any]], series_id: str) -> dict[str, Any] | None:
    row = cat.get(series_id)
    if not row:
        return None
    return {
        k: row.get(k)
        for k in (
            "publisher",
            "verdict",
            "badge",
            "lag_note",
            "terms",
            "freq",
            "unit",
            "evidence",
            "beginner_note",
            "pro_note",
            "how_pros_use_it",
            "url",
            "source_entry",
        )
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# stored-series access
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def series_map(payload: Any) -> dict[str, list[dict[str, Any]]]:
    """{series_id: sorted points} from either reply shape: {series:[{series_id, points:[…]}]} or long rows."""
    out: dict[str, list[dict[str, Any]]] = {}
    if isinstance(payload, dict) and isinstance(payload.get("series"), list):
        for s in payload["series"]:
            if isinstance(s, dict) and s.get("series_id"):
                out[str(s["series_id"])] = _points(s.get("points") or [])
        return out
    for r in _rows(payload):
        sid = r.get("series_id")
        if sid:
            out.setdefault(str(sid), []).append(r)
    return {sid: _points(rows) for sid, rows in out.items()}


async def fetch_series(
    reads: Reads, ids: list[str], days: int = 400, asof: datetime | None = None, freq: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    if not ids:
        return {}
    start = (_now_ist().date() - timedelta(days=days)).isoformat()
    payload = await reads.get(
        "/db/gold/series", ids=",".join(ids), **{"from": start}, asof=asof.isoformat() if asof else None, freq=freq
    )
    return {sid: asof_filter(pts, asof) for sid, pts in series_map(payload).items()}


def latest(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    return points[-1] if points else None


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# the fair block (no Breeze on this path: master + the cached Yahoo fetcher only)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


async def fair_block(contract: str = "GOLD", expiry: str | None = None) -> dict[str, Any]:
    """`/health.fair`: fair_value, premium vs the LIVE MCX price when the quote cache holds one (no quote call here), the
    duty leg, the basis vs the landed price of the contract's purity, and the settlement block of the wave-1d CONTRACT: the
    latest completed session's last-30-min VWAP (ONE Breeze historical call per contract per session, cached all night,
    waited for at most `gp.SETTLE_WAIT_S`) else the band midpoint labelled with its real session, plus `settlement_check`."""
    code = contract.upper() if contract and contract.upper() in mcxr.contract_specs() else "GOLD"
    asked = _d(expiry) if expiry else None
    now_ist = _now_ist()
    today = now_ist.date()
    got = await asyncio.to_thread(mcxr._master_gold_family)
    family, published = got if got else (None, None)
    exp, exp_source, row = mcxr._resolve_expiry(code, today, asked, family)
    settle = await mcxr.resolve_settlement(code, exp, row, published, now_ist)
    fair = await mcxr._fair_value(code, exp, settle)  # ONE Yahoo fetcher (PLAN 0.1 #2)
    live: float | None = None
    live_source = None
    live_at = None
    # the quote cache is keyed by the expiry string the page asked with (`mcx_quote(expiry=selected)` → `quote:GOLD:2026-12-04`)
    # OR by 'front' (C-DATA-13: the desk said NEED_PRICE on one panel and WAIT on another from the same page) — look under
    # both the resolved expiry and the alias, newest live quote wins
    for key in dict.fromkeys((f"quote:{code}:{expiry or 'front'}", f"quote:{code}:{exp.isoformat()}", f"quote:{code}:front")):
        cached_quote = mcxr._cache.get(key)
        if isinstance(cached_quote, dict) and cached_quote.get("available") and (cached_quote.get("quote") or {}).get("ltp"):
            if str(cached_quote.get("expiry") or exp.isoformat()) != exp.isoformat():
                continue  # a 'front' entry for another expiry is not this contract's price
            live, live_source = float(cached_quote["quote"]["ltp"]), cached_quote["quote"].get("source")
            live_at = _iso_any(cached_quote["quote"].get("time") or cached_quote.get("as_of"))
            break
    today_row = next((r for r in gp.log_rows(1) if r.get("date") == today.isoformat()), None)
    hol = specs.holiday_on(today)
    win = specs.trading_window(today)
    out: dict[str, Any] = {
        "contract": code,
        "expiry": exp.isoformat(),
        "expiry_source": exp_source,
        "fair_value": (fair or {}).get("fair"),
        "mcx_live": live,
        "mcx_live_source": live_source,
        "mcx_live_as_of": live_at,
        "premium_rupees": None,
        "premium_pct": None,
        "comex": (fair or {}).get("comex"),
        "comex_symbol": ((fair or {}).get("comex") or {}).get("symbol"),
        "usdinr": (fair or {}).get("usdinr"),
        "landed": (fair or {}).get("landed"),
        "duty_pct": (fair or {}).get("duty_pct"),
        "duty_effective": (fair or {}).get("duty_effective"),
        "duty_note": (fair or {}).get("duty_note"),
        "duty_paid_landed": (fair or {}).get("duty_paid_landed"),
        # the basis divides by the landed price × THIS contract's purity / 1000 (D1): 995 GOLD / GOLDM, 999 TEN / PETAL / GUINEA
        "purity": gp.fineness_of(code),
        "basis_reference": gp.basis_reference(code),
        # every rupee price in this block is in the contract's quotation unit (₹ per 1 g PETAL, per 8 g GUINEA, else 10 g)
        "quote_unit": f"₹ per {mcxr.contract_specs()[code].quote_per_grams} g",
        "duty_paid_landed_purity": (fair or {}).get("duty_paid_landed_purity"),
        "duty_paid_landed_at_settlement": (fair or {}).get("duty_paid_landed_at_settlement"),
        "basis_pct": (fair or {}).get("basis_pct"),
        "basis_clock": "settlement" if (fair or {}).get("basis_pct") is not None else None,
        **{k: settle.get(k) for k in mcxr.SETTLE_KEYS},
        "gap_vs_settlement": (fair or {}).get("gap_vs_settlement"),
        "implied_premium_pct": (fair or {}).get("implied_premium_pct"),  # deprecated alias of basis_pct (one release)
        # today's captured open (09:10 job or a manual entry) → BRF's "Gold opened … vs fair … (miss …)" line
        "actual_open": (today_row or {}).get("actual_open"),
        "actual_open_source": (today_row or {}).get("actual_source"),
        "snapshot_fair": (today_row or {}).get("fair_open"),
        "snapshot_error": (today_row or {}).get("error"),
        "mcx_holiday": (
            {"name": hol[0], "closure": hol[1], "opens_at": win[0].isoformat(timespec="minutes") if win else None}
            if hol
            else None
        ),
        "badge": BADGE_ARITH,
        "freshness": freshness(((fair or {}).get("comex") or {}).get("as_of"), 1, "Yahoo (cached fetcher)", live=bool(fair)),
    }
    if live and out["fair_value"]:
        out["premium_rupees"] = round(live - out["fair_value"], 0)
        out["premium_pct"] = round((live / out["fair_value"] - 1) * 100, 2)
    # the desk's verdict rule (₹300 chase limit, `heuristic`) on the same inputs: OK / WAIT once a price exists,
    # AWAITING_OPEN / NEED_PRICE before — BRF's line prints OK/WAIT only when the rule produced one (API_CONTRACT §7)
    now_ist = _now_ist()
    opened = win is not None and now_ist >= win[0] and (hol is None or hol[1] != "full")
    out["desk_verdict_state"] = (
        gp._verdict_body(out["fair_value"], live, CHASE_LIMIT_INR, opened)["state"] if out["fair_value"] else None
    )
    if fair is None:
        out["freshness"] = {"source": "Yahoo (cached fetcher)", "as_of": None, "age_s": None, "state": "unavailable"}
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# HEALTH — eight gauges and a rule-based descriptive verdict (no score)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════

HEALTH_RULES: list[dict[str, Any]] = [
    {
        "rule_id": "H1",
        "clause": "week label · trend",
        "series_id": "COMEX_GC_FRONT",
        "rule": "gold's change over the window: ≤ −2 % WEAK · ≥ +2 % STRONG · |Δ| < 0.5 % FLAT · else QUIET/FIRM; then the "
        "trend sentence from the TREND gauge's values: the price vs its 20-d and 200-d averages ('below both averages' / "
        "'between' / 'above both', with both % printed) and the drawdown from the 52-week high — a description, no "
        "threshold of its own",
        "threshold": {"weak_pct": -2.0, "strong_pct": 2.0, "flat_pct": 0.5},
    },
    {
        "rule_id": "H2",
        "clause": "driver label",
        "series_id": "DXY_CLOSE",
        "rule": "DOLLAR-DRIVEN when the dollar effect (KGX split) is ≥ 40 % of gold's move and |move| ≥ 0.5 %; "
        "YIELD-DRIVEN when the 10-y real yield moved ≥ 5 bp against gold; GOLD-SPECIFIC only when BOTH legs were tested "
        "and neither explains the move; no driver word (driver untested) when either leg is missing",
        "threshold": {"usd_share": 0.4, "min_move_pct": 0.5, "real_yield_bp": 5.0},
    },
    {
        "rule_id": "H3",
        "clause": "funds",
        "series_id": COT_SERIES_ID,
        "rule": "managed-money net and its w/w change in % with the fund-driver label (G-STUDY §5.1)",
        "threshold": None,
    },
    {
        "rule_id": "H4",
        "clause": "India basis",
        "series_id": "MCX_BASIS_PCT",
        "rule": "the contract's settlement (last-30-min VWAP, else the band of its real session), in ₹/10 g, vs the duty-paid "
        "landed price × purity/1000 (GOLD / GOLDM 995, GOLDTEN / PETAL / GUINEA 999; landed is per fine gold) at that "
        "session's close — or the live price vs now while a quote exists; one value per clock (duty dated); stated, not judged",
        "threshold": None,
    },
    {
        "rule_id": "H5",
        "clause": "roll",
        "series_id": "COMEX_CARRY_ANN_PCT",
        "rule": "front → next calendar spread as % and annualised; days to first notice",
        "threshold": None,
    },
    {
        "rule_id": "H6",
        "clause": "ETF",
        "series_id": "GLD_TONNES",
        "rule": "GLD tonnes change on the latest day; ≥ 5 t is called 'notable'",
        "threshold": {"notable_t": 5.0},
    },
    {
        "rule_id": "H0",
        "clause": "closing words",
        "series_id": None,
        "rule": f"every verdict ends '{DESCRIBES}'; stale or unavailable gauges contribute no clause",
        "threshold": None,
    },
]


def _gauge(
    key: str,
    label: str,
    series_id: str | None,
    value: float | None,
    unit: str,
    change: float | None,
    change_window: str,
    report_date: Any,
    release_at: Any,
    max_age_days: float | None,
    source: str,
    direction_for_gold: str | None,
    rule: str,
    badge: str,
    evidence: str,
    extra: dict[str, Any] | None = None,
    live: bool = False,
    change_unit: str | None = None,
) -> dict[str, Any]:
    """One HEALTH tile. `change_unit` says what `change` is in (critic C-DATA-7: the Shanghai tile's $47/oz week change
    rendered as "+47.36 %"): `%` a percentage change, else the difference in that unit (`$/oz`, `bp`, `contracts`, `t`).
    `release_at` is re-stamped with its offset (`_iso_any`)."""
    fr: dict[str, Any] = (
        freshness(release_at or report_date, max_age_days, source, live=live)
        if value is not None
        else {"source": source, "as_of": None, "age_s": None, "state": "unavailable"}
    )
    age_days = None if fr["age_s"] is None else round(fr["age_s"] / 86400, 2)
    out = {
        "key": key,
        "label": label,
        "value": _r(value, 4) if value is not None else None,
        "unit": unit,
        "change": _r(change, 4) if change is not None else None,
        "change_unit": change_unit if change is not None else None,
        "change_window": change_window,
        "report_date": str(report_date)[:10] if report_date else None,
        "release_at": _iso_any(release_at),
        "age_days": age_days,
        "state": fr["state"],
        "direction_for_gold": direction_for_gold,
        "rule": rule,
        "percentile_1y": None,
        "percentile_3y": None,
        "series_id": series_id,
        "source": source,
        "badge": badge,
        "evidence": evidence,
    }
    if extra:
        out.update(extra)
    return out


def _week_label(chg_pct: float | None, window: str) -> str | None:
    th = HEALTH_RULES[0]["threshold"]
    if chg_pct is None:
        return None
    word = {"D": "DAY", "W": "WEEK", "M": "MONTH"}.get(window.upper(), "WEEK")
    if chg_pct <= th["weak_pct"]:
        return f"WEAK {word}"
    if chg_pct >= th["strong_pct"]:
        return f"STRONG {word}"
    if abs(chg_pct) < th["flat_pct"]:
        return f"FLAT {word}"
    return f"{'FIRM' if chg_pct > 0 else 'SOFT'} {word}"


def _driver_word(gold_pct: float | None, usd_effect_pct: float | None, real_yield_bp: float | None) -> str | None:
    """H2. `GOLD-SPECIFIC` is a claim that BOTH legs were tested and neither explains the move: when either leg is None
    the word is omitted (critics C-TRADER-7 / C-DATA-2, 5 Nov 2026 — the headline asserted GOLD-SPECIFIC with the dollar
    gauge offline); `driver_note` says which leg was missing."""
    th = HEALTH_RULES[1]["threshold"]
    if gold_pct is None or abs(gold_pct) < th["min_move_pct"]:
        return None
    if (
        usd_effect_pct is not None
        and abs(usd_effect_pct) >= th["usd_share"] * abs(gold_pct)
        and math.copysign(1, usd_effect_pct) == math.copysign(1, gold_pct)
    ):
        return "DOLLAR-DRIVEN"
    if (
        real_yield_bp is not None
        and abs(real_yield_bp) >= th["real_yield_bp"]
        and math.copysign(1, -real_yield_bp) == math.copysign(1, gold_pct)
    ):
        return "YIELD-DRIVEN"
    if usd_effect_pct is None or real_yield_bp is None:
        return None
    return "GOLD-SPECIFIC"


def driver_note(
    gold_pct: float | None, usd_effect_pct: float | None, real_yield_bp: float | None, usd_missing: str | None = None
) -> str | None:
    """Why H2 printed no driver word: the untested leg(s) (`usd_missing` names the dollar leg's reason when the tile shows a
    stand-in index), or the move too small to call."""
    th = HEALTH_RULES[1]["threshold"]
    if gold_pct is None or abs(gold_pct) < th["min_move_pct"]:
        return None
    missing = [
        name
        for name, v in ((usd_missing or "dollar series offline", usd_effect_pct), ("real-yield series offline", real_yield_bp))
        if v is None
    ]
    if missing and _driver_word(gold_pct, usd_effect_pct, real_yield_bp) is None:
        return "driver untested: " + ", ".join(missing)
    return None


def verdict_sentence(gauges: list[dict[str, Any]], window: str, extras: dict[str, Any]) -> dict[str, Any]:
    """The rule-based sentence: thresholded clauses from the gauges that are not stale/unavailable; NO score; ends
    'describes, does not predict'. Pure: tested with synthetic gauges."""
    g = {x["key"]: x for x in gauges if x.get("state") not in ("stale", "unavailable")}
    clauses: list[dict[str, Any]] = []
    trend = g.get("trend")
    gold_pct = trend.get("change") if trend else None
    label = _week_label(gold_pct, window)
    ry_bp = (g.get("real_yield") or {}).get("change_bp")
    driver = _driver_word(gold_pct, extras.get("usd_effect_pct"), ry_bp)
    note = driver_note(gold_pct, extras.get("usd_effect_pct"), ry_bp, extras.get("usd_missing"))
    head = ", ".join(x for x in (label, driver) if x)
    if head:
        clauses.append(
            {
                "text": head,
                "rule_id": "H1/H2",
                "series_id": "COMEX_GC_FRONT",
                "value": _r(gold_pct),
                "threshold": HEALTH_RULES[0]["threshold"],
                "note": note,
            }
        )
    # the trend in the gauge's own numbers right after the head (wave 1d): a 'STRONG WEEK' inside a market below both of its
    # averages reads as a rebound, not an uptrend — the sentence now says which
    tt = trend_clause_text(trend) if trend else None
    if tt:
        clauses.append(
            {
                "text": tt,
                "rule_id": "H1",
                "rule_part": "trend sentence (HEALTH_RULES H1: the TREND gauge's values, no threshold of its own)",
                "series_id": "COMEX_GC_FRONT",
                "value": trend.get("vs_200d_pct") if trend else None,
                "threshold": None,
                "trend_words": trend.get("trend_words") if trend else None,
            }
        )
    if trend and gold_pct is not None:
        # the window's own words ("week to date (since the Fri 30 Oct close)" / "5 sessions"), never a vague "over the week"
        span = trend.get("window_label") or {"D": "vs the previous session", "W": "over the week", "M": "over the month"}.get(
            window.upper(), "over the window"
        )
        bits = [f"gold {gold_pct:+.1f} % {span}"]
        usd = extras.get("usd_effect_pct")
        if usd is not None:
            bits.append(f"of which the dollar {usd:+.1f} %")
        if ry_bp is not None:
            bits.append(f"real yield {ry_bp:+.0f} bp")
        if note:
            bits.append(note)
        clauses.append(
            {
                "text": " · ".join(bits),
                "rule_id": "H2",
                "series_id": "FRED_DFII10",
                "value": _r(usd),
                "threshold": HEALTH_RULES[1]["threshold"],
            }
        )
    pos = g.get("positioning")
    if pos and pos.get("value") is not None:
        # the net itself is on the strip and the tile (PLAN f.6: once per page); the clause carries the change and the label
        pct, chg = pos.get("change_pct"), pos.get("change")
        text = f"funds {pct:+.1f} % w/w" if pct is not None else (f"funds {chg:+,.0f} w/w" if chg is not None else "funds unchanged")
        lab = driver_clause(extras.get("driver_label"))
        if lab and chg:  # a week without a change in either leg gets no word (who_did says "no change")
            text += f" ({lab})"
        clauses.append({"text": text, "rule_id": "H3", "series_id": COT_SERIES_ID, "value": pos["value"], "threshold": None})
    basis = g.get("india_basis")
    if basis and basis.get("value") is not None:
        # the gauge's ONE value with its clock and purity named (5 Nov review: +0.72 / 0.02 / +0.0 / −2.1 / +0.7 % in ten minutes)
        clock = "live" if basis.get("clock") == "now" else (basis.get("settle_basis_session_label") or "settlement")
        ref = str(basis.get("basis_reference") or "").replace("landed_", "")
        clauses.append(
            {
                "text": f"India basis {basis['value']:+.1f} % vs duty-paid landed{f' {ref}' if ref else ''} ({clock})",
                "rule_id": "H4",
                "series_id": "MCX_BASIS_PCT",
                "value": basis["value"],
                "threshold": None,
                "clock": basis.get("clock"),
            }
        )
    roll = g.get("curve_roll")
    if roll and roll.get("value") is not None:
        text = f"roll {roll.get('front') or 'front'}→{roll.get('next') or 'next'} costs {roll['value']:+.2f} %"
        if roll.get("annualised_pct") is not None:
            text += f" ({roll['annualised_pct']:+.1f} %/yr)"
        if roll.get("days_to_fnd") is not None:
            text += f", FND in {roll['days_to_fnd']} d"
        clauses.append(
            {"text": text, "rule_id": "H5", "series_id": "COMEX_CARRY_ANN_PCT", "value": roll["value"], "threshold": None}
        )
    etf = g.get("etf")
    if etf and etf.get("change") is not None:
        notable = abs(etf["change"]) >= HEALTH_RULES[5]["threshold"]["notable_t"]
        clauses.append(
            {
                "text": f"GLD {etf['change']:+.1f} t on the day{' (notable)' if notable else ''}",
                "rule_id": "H6",
                "series_id": "GLD_TONNES",
                "value": etf["change"],
                "threshold": HEALTH_RULES[5]["threshold"],
            }
        )
    if not clauses:
        clauses.append(
            {
                "text": "no fresh gauge: every input is stale or unavailable",
                "rule_id": "H0",
                "series_id": None,
                "value": None,
                "threshold": None,
            }
        )
    line = " · ".join(c["text"] for c in clauses) + f" · {DESCRIBES}"
    return {"line": line, "clauses": clauses, "headline": head or None, "badge": BADGE_CONTEXT, "ends_with": DESCRIBES}


def _day_label(iso: str | None) -> str:
    """'Mon 30 Nov' for an ISO date (PLAN §b: the WEI/BRF line never prints a raw ISO date); the input on failure."""
    if not iso:
        return ""
    try:
        d = _dd(iso)
    except (ValueError, TypeError):
        return str(iso)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def health_line(verdict: dict[str, Any], gauges: list[dict[str, Any]], roll_date: str | None) -> str:
    """The WEI second line / BRF line (PLAN §b): verdict words (≤ 24 chars) · basis · COT MM · roll · GOLD ›."""
    g = {x["key"]: x for x in gauges}
    words = (verdict.get("headline") or "NO FRESH READ").strip(" ,")
    if len(words) > 28:   # the line budget (PLAN §b): cut at a word boundary, never 'GOLD-SPECIF' (re-review minor)
        words = words[:28].rsplit(" ", 1)[0].rstrip(" ,") or words[:28]
    parts = [f"GOLD · {words}"]
    basis = g.get("india_basis", {})
    if basis.get("value") is not None:
        parts.append(f"basis {basis['value']:+.1f} %")
    pos = g.get("positioning", {})
    if pos.get("value") is not None:
        chg = pos.get("change")
        parts.append(f"COT MM {pos['value'] / 1000:+.0f}k" + (f" ({chg / 1000:+.1f}k)" if chg is not None else ""))
    roll = g.get("curve_roll", {})
    if roll.get("front") and roll.get("next"):
        parts.append(f"roll {roll['front']}→{roll['next']}" + (f" · FND {_day_label(roll_date)}" if roll_date else ""))
    parts.append("GOLD ›")
    return " · ".join(parts)


def _closes_from_bars(payload: Any) -> list[dict[str, Any]]:
    rows = _rows(payload) if not (isinstance(payload, dict) and isinstance(payload.get("bars"), list)) else payload["bars"]
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _d(r.get("trade_date") or r.get("ts") or r.get("t"))
        c = _f(r.get("close") if r.get("close") is not None else r.get("c"))
        if d and c is not None:
            out.append(
                {
                    "report_date": d.isoformat(),
                    "value": c,
                    "release_at": None,
                    "open": _f(r.get("open", r.get("o"))),
                    "high": _f(r.get("high", r.get("h"))),
                    "low": _f(r.get("low", r.get("l"))),
                    "volume": _f(r.get("volume", r.get("v"))),
                    "partial": r.get("partial"),  # the store's flag (a bar fetched before the Globex close), kept
                }
            )
    out.sort(key=lambda p: p["report_date"])
    return out


def _cot_rows(payload: Any) -> list[dict[str, Any]]:
    rows = [r for r in _rows(payload) if _d(r.get("report_date"))]
    rows.sort(key=lambda r: str(r["report_date"])[:10])
    return rows


def _cot_net(row: dict[str, Any], g: str) -> float | None:
    lo, sh = _f(row.get(f"{g}_long")), _f(row.get(f"{g}_short"))
    return None if lo is None or sh is None else lo - sh


def trend_words(vs_20d: float | None, vs_200d: float | None) -> str | None:
    """'above both' | 'between' | 'below both averages' (the wave-1d CONTRACT's words, verbatim) from the close vs its 20- and
    200-day averages (the tile printed only its rule, 'price above its averages = uptrend', while the price was below both)."""
    if vs_20d is None or vs_200d is None:
        return None
    if vs_20d > 0 and vs_200d > 0:
        return "above both"
    if vs_20d < 0 and vs_200d < 0:
        return "below both averages"
    return "between"


TREND_DISPLAY = {"between": "between its 20-d and 200-d averages", "above both": "above both averages"}


def trend_clause_text(g: dict[str, Any]) -> str | None:
    """The verdict's trend clause, the gauge's own numbers: 'price below both averages (−0.5 % vs 20-d, −9.7 % vs 200-d;
    −23.5 % from the 52-w high)'."""
    words = g.get("trend_words")
    if not words:
        return None
    bits = [f"{g['vs_20d_pct']:+.1f} % vs 20-d", f"{g['vs_200d_pct']:+.1f} % vs 200-d"]
    dd = g.get("drawdown_pct")
    tail = f"; {dd:+.1f} % from the 52-w high" if dd is not None else ""
    lead = "price " + TREND_DISPLAY.get(words, words)
    return f"{lead} ({', '.join(bits)}{tail})"


SHANGHAI_MEDIAN_PAIRS = 5


def shanghai_change(g: dict[str, Any], pts: list[dict[str, Any]]) -> dict[str, Any]:
    """The SHANGHAI tile's change: the latest same-date pair vs the MEDIAN of the previous five pairs (re-review C-DATA-2 /
    5 Nov review: '▼−$76.89/oz W' was measured from the Fri 30 Oct pair, +$75.34 — the 14:15 Beijing fix against a London
    fix 7 h later on a −3.3 % day, a timing spike — so one cross-clock pair can never set the change). Pure."""
    if g.get("value") is None or len(pts) < 3:
        return g
    prev = [p["value"] for p in pts[-1 - SHANGHAI_MEDIAN_PAIRS : -1] if p.get("value") is not None]
    if not prev:
        return g
    med = statistics.median(prev)
    g.update(
        change=_r(pts[-1]["value"] - med, 4),
        change_window=f"vs the median of the previous {len(prev)} pairs",
        window_label=f"vs the median of the previous {len(prev)} same-date pairs (a one-day timing spike never sets the change)",
        window_from=pts[-1 - len(prev)]["report_date"],
        median_prev_pairs=_r(med, 2),
    )
    return g


def _bar_partial(p: dict[str, Any]) -> bool | None:
    """The store's own partial flag on a daily bar (data-service marks a bar fetched before the Globex close), None when absent."""
    v = p.get("partial")
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "t", "yes")
    return bool(v)


async def build_health(window: str = "W", contract: str = "GOLD", expiry: str | None = None) -> dict[str, Any]:
    """The HEALTH payload (PLAN §d): gauges, the verdict, the fair block, the one-line echo and the freshness
    summary. Every block is built in its own try so one missing source never blanks the rest. `contract` / `expiry` pick
    the MCX contract whose basis the INDIA BASIS gauge, the H4 clause and the lines print (/overview passes the page's pick,
    so the strip, the gauge and the verdict print ONE basis per clock; /health keeps GOLD, the WEI / BRF echo)."""
    reads = Reads()
    now = _now_ist()
    cat = await catalog(reads)
    start_bars = (now.date() - timedelta(days=TREND_BARS_DAYS)).isoformat()
    bars_t, series_t, cot_t, etf_t, curve_t, events_t, fair_t, dxy_bars_t, prf_t = await _gather(
        reads.get("/db/gold/bars", symbol=GC_FRONT, interval="1d", **{"from": start_bars}),
        fetch_series(
            reads,
            [
                "FRED_DFII10",
                "UST_REAL_10Y",
                "DXY_CLOSE",
                "FRED_DTWEXBGS",
                "USDINR_CLOSE",
                "INDIA_PREMIUM_PCT",
                "MCX_BASIS_PCT",
                "SHANGHAI_PREMIUM_USD",
                "SHANGHAI_PREMIUM_PCT",
                "COMEX_CARRY_ANN_PCT",
            ],
            days=400,
        ),
        reads.get("/db/gold/cot", weeks=160, report="disagg", fut_or_combined="F"),
        reads.get("/db/gold/etf", **{"from": (now.date() - timedelta(days=90)).isoformat()}),
        reads.get("/db/gold/curve", exchange="COMEX"),
        reads.get("/db/gold/events", **{"from": now.date().isoformat(), "to": (now.date() + timedelta(days=60)).isoformat()}),
        fair_block(contract, expiry),
        # the DXY leg from the stored DX-Y.NYB daily bars when the DXY_CLOSE series has no points (C-DATA-2/3/4): same
        # catalog row, the same numbers data-service's bars read serves
        reads.get("/db/gold/bars", symbol=DXY_SYMBOL, interval="1d", **{"from": (now.date() - timedelta(days=400)).isoformat()}),
        reads.get("/db/gold/cme/prf", symbol="GC"),  # FND / LTD of the front month until gold_cme_calendar is stored
    )
    fair: dict[str, Any] = (
        fair_t
        if isinstance(fair_t, dict)
        else {
            "fair_value": None,
            "basis_pct": None,
            "freshness": {"source": "Yahoo", "as_of": None, "age_s": None, "state": "unavailable"},
        }
    )
    gauges: list[dict[str, Any]] = []
    extras: dict[str, Any] = {}

    # 1. TREND
    closes = _closes_from_bars(bars_t) if not isinstance(bars_t, Exception) else []
    try:
        if closes and is_published(cat, GC_FRONT_SERIES):
            last = closes[-1]
            anchor = window_anchor(closes, window, now.date())
            v_now, v_then = last["value"], (anchor["then"] or {}).get("value")
            chg_pct = (v_now / v_then - 1) * 100 if v_now and v_then else None
            vals = [p["value"] for p in closes]
            ma20 = statistics.fmean(vals[-20:]) if len(vals) >= 20 else None
            ma200 = statistics.fmean(vals[-200:]) if len(vals) >= 200 else None
            hi52 = max(window_values(closes, 365)) if closes else None
            # the store's own partial flag wins (re-review: data-service marked the 4 Nov GC=F bar partial — fetched 20 min
            # before the Globex close — and ui-api printed it as final); the clock rule only when the row carries none
            stored_partial = _bar_partial(last)
            partial = (
                stored_partial
                if stored_partial is not None
                else _dd(last["report_date"]) >= now.date() and bool(comex_session(now)["is_open"])
            )
            vs20 = _r((last["value"] / ma20 - 1) * 100) if ma20 else None
            vs200 = _r((last["value"] / ma200 - 1) * 100) if ma200 else None
            dd52 = _r((last["value"] / hi52 - 1) * 100) if hi52 else None
            words_t = trend_words(vs20, vs200)
            gauges.append(
                _gauge(
                    "trend",
                    "TREND",
                    GC_FRONT_SERIES,
                    last["value"],
                    "$/oz",
                    chg_pct,
                    window,
                    last["report_date"],
                    None,
                    max_age_of(cat, GC_FRONT_SERIES),
                    "Yahoo GC=F (stored daily bars)",
                    # the words the values give, never the rule alone (5 Nov review: 'price above its averages = uptrend'
                    # printed while the price sat 9.7 % under its 200-day average)
                    f"{TREND_DISPLAY.get(words_t, words_t)} (a description)" if words_t else None,
                    "close vs 20-day / 200-day average (above both · between · below both); drawdown from the 52-week high",
                    BADGE_CONTEXT,
                    EVIDENCE_CONTEXT,
                    {
                        "vs_20d_pct": vs20,
                        "vs_200d_pct": vs200,
                        "drawdown_pct": dd52,
                        "drawdown_52w_pct": dd52,  # the older name, same number
                        "trend_words": words_t,
                        "ma20": _r(ma20, 2) if ma20 else None,
                        "ma200": _r(ma200, 2) if ma200 else None,
                        "high_52w": _r(hi52, 2) if hi52 else None,
                        "percentile_1y": pct_rank(window_values(closes, 365), last["value"]),
                        "percentile_3y": pct_rank(window_values(closes, 1095), last["value"]) if len(closes) >= 500 else None,
                        "window_label": anchor["label"],
                        "window_from": anchor["from_date"],
                        "window_from_value": v_then,
                        "window_sessions": anchor["sessions"],
                        "last_bar_partial": bool(partial),
                        "last_bar_partial_source": "store" if stored_partial is not None else "clock rule",
                        "last_bar_note": (
                            f"the {_day_label(last['report_date'])} bar is a partial Globex day (fetched before the close), "
                            "not a settlement"
                            if partial
                            else None
                        ),
                    },
                    change_unit="%",
                )
            )
            extras["window_anchor"] = anchor
        else:
            gauges.append(
                _gauge(
                    "trend",
                    "TREND",
                    GC_FRONT_SERIES,
                    None,
                    "$/oz",
                    None,
                    window,
                    None,
                    None,
                    None,
                    "Yahoo GC=F (stored daily bars)",
                    None,
                    "close vs 20/200-day",
                    BADGE_CONTEXT,
                    EVIDENCE_CONTEXT,
                )
            )
            if closes:
                gauges[-1].update(published=False, note=unpublished_note(cat, GC_FRONT_SERIES))
    except Exception as exc:  # noqa: BLE001
        reads.errors["gauge:trend"] = type(exc).__name__

    series = series_t if isinstance(series_t, dict) else {}

    def _series_gauge(
        key: str,
        label: str,
        sid: str,
        alt: str | None,
        unit: str,
        direction: str | None,
        rule: str,
        scale_change: float = 1.0,
        change_unit: str = "%",
    ) -> dict[str, Any]:
        """A tile from a stored series: the change is the DIFFERENCE over the verdict window (the same Monday-to-date /
        5-session anchor as TREND), scaled (`scale_change` 100 → bp) and labelled with `change_unit`; `change_bp` is kept
        on the real-yield tile as an alias (C-DATA-18: the tile showed no Δ while the verdict quoted it)."""
        pts = series.get(sid) or (series.get(alt) if alt else None) or []
        used = sid if series.get(sid) else (alt if alt and series.get(alt) else sid)
        if not pts or not is_published(cat, used):
            g = _gauge(
                key,
                label,
                used,
                None,
                unit,
                None,
                window,
                None,
                None,
                None,
                used,
                direction,
                rule,
                badge_of(cat, used),
                EVIDENCE_CONTEXT,
            )
            if pts and not is_published(cat, used):
                g["published"] = False
                g["note"] = unpublished_note(cat, used)
            return g
        last_p = pts[-1]
        anchor = window_anchor(pts, window, now.date())
        v_now, v_then = last_p["value"], (anchor["then"] or {}).get("value")
        chg = (v_now - v_then) * scale_change if v_now is not None and v_then is not None else None
        g = _gauge(
            key,
            label,
            used,
            last_p["value"],
            unit,
            chg,
            window,
            last_p["report_date"],
            last_p.get("release_at"),
            max_age_of(cat, used, 5.0),
            (cat.get(used) or {}).get("publisher") or used,
            direction,
            rule,
            badge_of(cat, used),
            EVIDENCE_CONTEXT,
            {
                "percentile_1y": pct_rank(window_values(pts, 365), last_p["value"]),
                "percentile_3y": pct_rank(window_values(pts, 1095), last_p["value"]) if len(pts) > 300 else None,
                "window_label": anchor["label"],
                "window_from": anchor["from_date"],
            },
            change_unit=change_unit,
        )
        if change_unit == "bp":
            g["change_bp"] = _r(chg, 2)
        return g

    # 2. REAL YIELD (bp change)   3. DOLLAR (% change)
    try:
        ry = _series_gauge(
            "real_yield",
            "REAL YIELD 10-y",
            "FRED_DFII10",
            "UST_REAL_10Y",
            "%",
            "falling = supportive",
            "10-y TIPS yield; Δ in bp over the window; contemporaneous only (G-MACRO H1)",
            100.0,
            "bp",
        )
        gauges.append(ry)
        dxy_pts = series.get("DXY_CLOSE") or []
        dxy_from = "series DXY_CLOSE"
        if not dxy_pts and not isinstance(dxy_bars_t, Exception):
            dxy_pts = _closes_from_bars(dxy_bars_t)  # the same catalog row, read from gold_daily_bars (DX-Y.NYB)
            dxy_from = f"daily bars {DXY_SYMBOL}"
        if dxy_pts and is_published(cat, "DXY_CLOSE"):
            anchor_d = window_anchor(dxy_pts, window, now.date())
            v_now, v_then = dxy_pts[-1]["value"], (anchor_d["then"] or {}).get("value")
            dxy_chg = (v_now / v_then - 1) * 100 if v_now and v_then else None
            extras["usd_effect_pct"] = _r(-dxy_chg) if dxy_chg is not None else None
            gauges.append(
                _gauge(
                    "dollar",
                    DXY_SOURCE_LABEL["DXY_CLOSE"],
                    "DXY_CLOSE",
                    dxy_pts[-1]["value"],
                    "index",
                    dxy_chg,
                    window,
                    dxy_pts[-1]["report_date"],
                    dxy_pts[-1].get("release_at"),
                    max_age_of(cat, "DXY_CLOSE"),
                    f"Yahoo {DXY_SYMBOL} (stored {dxy_from})",
                    "rising = headwind",
                    "Δ % over the window; the KGX split takes −Δln(DXY) as the dollar effect",
                    BADGE_CONTEXT,
                    EVIDENCE_CONTEXT,
                    {
                        "percentile_1y": pct_rank(window_values(dxy_pts, 365), dxy_pts[-1]["value"]),
                        "window_label": anchor_d["label"],
                        "window_from": anchor_d["from_date"],
                        "read_from": dxy_from,
                    },
                    change_unit="%",
                )
            )
        elif series.get("FRED_DTWEXBGS") and is_published(cat, "FRED_DTWEXBGS"):
            # the stand-in: the Fed's broad index, LABELLED as such (C-DATA-4 / C-BEGINNER-6 — never DTWEXBGS under the DXY
            # name, never a blank tile); a different basket, so it does NOT feed the H2 driver word
            bw = series["FRED_DTWEXBGS"]
            anchor_b = window_anchor(bw, window, now.date())
            v_now, v_then = bw[-1]["value"], (anchor_b["then"] or {}).get("value")
            extras["usd_missing"] = "DXY offline (the dollar tile shows the Fed broad index, a different basket)"
            gauges.append(
                _gauge(
                    "dollar",
                    DXY_SOURCE_LABEL["FRED_DTWEXBGS"],
                    "FRED_DTWEXBGS",
                    v_now,
                    "index",
                    (v_now / v_then - 1) * 100 if v_now and v_then else None,
                    window,
                    bw[-1]["report_date"],
                    bw[-1].get("release_at"),
                    max_age_of(cat, "FRED_DTWEXBGS", 10.0),
                    "FRED DTWEXBGS (stored; weekly lag)",
                    "rising = headwind",
                    "Δ % over the window; a stand-in while DXY_CLOSE has no points — not DXY, not in the KGX split",
                    BADGE_CONTEXT,
                    EVIDENCE_CONTEXT,
                    {
                        "percentile_1y": pct_rank(window_values(bw, 365), v_now),
                        "window_label": anchor_b["label"],
                        "window_from": anchor_b["from_date"],
                        "read_from": "series FRED_DTWEXBGS (stand-in)",
                        "note": f"DXY_CLOSE has no stored points and no {DXY_SYMBOL} daily bars; the Fed broad index stands in, labelled",
                    },
                    change_unit="%",
                )
            )
        else:
            extras["usd_missing"] = "dollar series offline"
            gauges.append(
                _gauge(
                    "dollar",
                    DXY_SOURCE_LABEL["DXY_CLOSE"],
                    "DXY_CLOSE",
                    None,
                    "index",
                    None,
                    window,
                    None,
                    None,
                    None,
                    "Yahoo DX-Y.NYB (stored)",
                    "rising = headwind",
                    "Δ % over the window",
                    BADGE_CONTEXT,
                    EVIDENCE_CONTEXT,
                    {"note": f"no stored DXY_CLOSE points and no {DXY_SYMBOL} daily bars (yahoo_daily job); the driver word is untested"},
                )
            )
    except Exception as exc:  # noqa: BLE001
        reads.errors["gauge:macro"] = type(exc).__name__

    # 4. POSITIONING
    try:
        rows = _cot_rows(cot_t) if not isinstance(cot_t, Exception) else []
        if rows and is_published(cat, COT_SERIES_ID):
            last_r, prev_r = rows[-1], (rows[-2] if len(rows) > 1 else None)
            net = _cot_net(last_r, "mm")
            cl, cs = _f(last_r.get("chg_mm_long")), _f(last_r.get("chg_mm_short"))
            prev_mm = _cot_net(prev_r, "mm") if prev_r else None
            chg = (cl - cs) if cl is not None and cs is not None else _diff(net, prev_mm)
            nets = [n for n in (_cot_net(r, "mm") for r in rows) if n is not None]
            oi = _f(last_r.get("open_interest"))
            prev_net = (net - chg) if net is not None and chg is not None else None
            pct = (chg / abs(prev_net) * 100) if chg is not None and prev_net else None
            # the G-STUDY §5.2 rule needs the week's price: Tue→Tue GC=F close change, exactly as build_cot computes it
            rd_cot = _dd(last_r["report_date"])
            dp_cot = _pct_change(_close_on(closes, rd_cot), _close_on(closes, rd_cot - timedelta(days=7)))
            extras["driver_label"] = driver_label(cl, cs, dp_cot)
            words = None
            idx52 = cot_index(nets, 52)
            if idx52 is not None and net is not None:
                words = (
                    "long, crowded"
                    if net > 0 and idx52 >= 90
                    else "long, not crowded"
                    if net > 0
                    else "short, washed out"
                    if idx52 <= 10
                    else "short"
                )
            gauges.append(
                _gauge(
                    "positioning",
                    "POSITIONING (COT managed money)",
                    COT_SERIES_ID,
                    net,
                    "contracts",
                    chg,
                    "W",
                    last_r["report_date"],
                    last_r.get("release_at"),
                    max_age_of(cat, COT_SERIES_ID, 9.0),
                    "CFTC disaggregated, futures only",
                    None,
                    "net = long − short; Δ w/w; 3-y percentile once 156 reports are stored",
                    BADGE_CONTEXT,
                    "context · G-STUDY 26 Oct 2026: explains the week, does not forecast",
                    {
                        "change_pct": _r(pct, 1),
                        "net_pct_oi": _r(net / oi * 100, 1) if net is not None and oi else None,
                        "cot_index_52": idx52,
                        "words": words,
                        "driver_label": extras["driver_label"],
                        "chg_long": cl,
                        "chg_short": cs,
                        "week_price_chg_pct": _r(dp_cot, 2),
                        "percentile_1y": pct_rank(nets[-52:], net) if net is not None and len(nets) >= 26 else None,
                        "percentile_3y": pct_rank(nets[-156:], net) if net is not None and len(nets) >= 100 else None,
                    },
                    change_unit="contracts",
                )
            )
        else:
            gauges.append(
                _gauge(
                    "positioning",
                    "POSITIONING (COT managed money)",
                    COT_SERIES_ID,
                    None,
                    "contracts",
                    None,
                    "W",
                    None,
                    None,
                    None,
                    "CFTC disaggregated, futures only",
                    None,
                    "net = long − short",
                    BADGE_CONTEXT,
                    "context · G-STUDY 26 Oct 2026: explains the week, does not forecast",
                )
            )
    except Exception as exc:  # noqa: BLE001
        reads.errors["gauge:positioning"] = type(exc).__name__

    # 5. INDIA BASIS — ONE clock per number (C-TRADER-10 / C-DATA-11 / C-BEGINNER-5): the live MCX quote vs the duty-paid
    #    landed computed now while a quote exists; otherwise the stored settlement-session basis (the same MCX_BASIS_PCT
    #    row the ladder and the CONTRACTS footer print); the other clock's figure sits beside it, labelled.  6. SHANGHAI
    try:
        prem_pts = series.get("INDIA_PREMIUM_PCT") or []
        sb = settle_basis(fair, series.get("MCX_BASIS_PCT") or [])
        lb = live_basis(fair)
        shown = lb if lb else sb
        if shown.get("value") is not None and is_published(cat, "MCX_BASIS_PCT"):
            gauges.append(
                _gauge(
                    "india_basis",
                    "INDIA BASIS",
                    "MCX_BASIS_PCT",
                    shown["value"],
                    "%",
                    None,
                    window,
                    now.date().isoformat() if lb else sb["date"],
                    lb["as_of"] if lb else (sb["date"]),
                    2.0,
                    "live MCX (Breeze) vs COMEX × INR × duty, now"
                    if lb
                    else f"MCX {fair.get('settlement_session_label') or 'settlement'} "
                    f"({str(fair.get('settlement_quality') or 'proxy').replace('_', ' ')}) vs that session's duty-paid landed",
                    None,
                    "live MCX ÷ duty-paid landed now − 1 while a quote exists, else settle ÷ that session's duty-paid − 1; "
                    "IBJA premium at its fix minute beside it when stored",
                    BADGE_CONTEXT,
                    "context · no in-house evidence (GS-PREMIUM after 2 y)",
                    {
                        "clock": shown["clock"],
                        "basis_label": shown["label"],
                        "basis_reference": shown.get("basis_reference") or fair.get("basis_reference"),
                        "purity": fair.get("purity"),
                        "basis_contract": f"{fair.get('contract') or 'GOLD'} {_mmy(fair.get('expiry')) or ''}".strip(),
                        "live_basis_pct": lb["value"] if lb else None,
                        "mcx_live": lb["mcx_live"] if lb else None,
                        "duty_paid_landed_now": fair.get("duty_paid_landed"),
                        "duty_paid_landed_purity_now": fair.get("duty_paid_landed_purity"),
                        "settle_basis_pct": sb["value"],
                        "settle_basis_date": sb["date"],
                        "settle_basis_session_label": gp.session_label(_dd(sb["date"])) if sb.get("date") else None,
                        "settle_basis_label": sb["label"],
                        "settle_basis_source": sb["source"],
                        "settlement_source": fair.get("settlement_source"),
                        "settlement_quality": fair.get("settlement_quality"),
                        "settlement_check": fair.get("settlement_check"),
                        "ibja_premium_pct": prem_pts[-1]["value"] if prem_pts else None,
                        "ibja_premium_date": prem_pts[-1]["report_date"] if prem_pts else None,
                        "ibja_premium_note": "IBJA 999 PM vs duty-paid landed at the fix minute (stored INDIA_PREMIUM_PCT)",
                        "duty_pct": fair.get("duty_pct"),
                        "duty_effective": fair.get("duty_effective"),
                        "settlement_session_label": fair.get("settlement_session_label"),
                    },
                    live=bool(lb),
                )
            )
        else:
            gauges.append(
                _gauge(
                    "india_basis",
                    "INDIA BASIS",
                    "MCX_BASIS_PCT",
                    None,
                    "%",
                    None,
                    window,
                    None,
                    None,
                    None,
                    "MCX settlement vs COMEX × INR × duty",
                    None,
                    "settle ÷ duty-paid landed − 1",
                    BADGE_CONTEXT,
                    "context · no in-house evidence",
                )
            )
            if shown.get("value") is not None:
                gauges[-1].update(published=False, note=unpublished_note(cat, "MCX_BASIS_PCT"))
        sh_gauge = _series_gauge(
            "shanghai",
            "SHANGHAI PREMIUM",
            "SHANGHAI_PREMIUM_USD",
            "SHANGHAI_PREMIUM_PCT",
            "$/oz" if series.get("SHANGHAI_PREMIUM_USD") or not series.get("SHANGHAI_PREMIUM_PCT") else "%",
            None,
            "SGE PM (CNY/g → $/oz) − LBMA PM of the same date; Δ vs the median of the previous 5 pairs",
            1.0,
            "$/oz" if series.get("SHANGHAI_PREMIUM_USD") or not series.get("SHANGHAI_PREMIUM_PCT") else "pp",
        )
        gauges.append(shanghai_change(sh_gauge, series.get(sh_gauge.get("series_id") or "") or []))
    except Exception as exc:  # noqa: BLE001
        reads.errors["gauge:premiums"] = type(exc).__name__

    # 7. ETF HOLDINGS (GLD)
    try:
        etf_rows = (
            [r for r in _rows(etf_t) if str(r.get("fund") or "GLD").upper() == "GLD"] if not isinstance(etf_t, Exception) else []
        )
        pts = _points(etf_rows, value_key="tonnes")
        if pts and is_published(cat, "GLD_TONNES"):
            last_p = pts[-1]
            chg_1d = last_p["value"] - pts[-2]["value"] if len(pts) > 1 else None
            gauges.append(
                _gauge(
                    "etf",
                    "ETF HOLDINGS (GLD)",
                    "GLD_TONNES",
                    last_p["value"],
                    "t",
                    chg_1d,
                    "D",
                    last_p["report_date"],
                    last_p.get("release_at"),
                    max_age_of(cat, "GLD_TONNES", 5.0),
                    "SPDR Gold Shares (displayed with attribution)",
                    None,
                    "tonnes in trust; Δ d/d; contemporaneous with price, no lead (G-STUDY, G-MACRO)",
                    BADGE_CONTEXT,
                    EVIDENCE_CONTEXT,
                    {
                        "chg_5d": _diff(change_over(pts, 7)[0], change_over(pts, 7)[1]),
                    },
                    change_unit="t",
                )
            )
        else:
            gauges.append(
                _gauge(
                    "etf",
                    "ETF HOLDINGS (GLD)",
                    "GLD_TONNES",
                    None,
                    "t",
                    None,
                    "D",
                    None,
                    None,
                    None,
                    "SPDR Gold Shares",
                    None,
                    "tonnes in trust; Δ d/d",
                    BADGE_CONTEXT,
                    EVIDENCE_CONTEXT,
                )
            )
    except Exception as exc:  # noqa: BLE001
        reads.errors["gauge:etf"] = type(exc).__name__

    # 8. CURVE / ROLL
    roll_date: str | None = None
    try:
        pts_c = curve_points(curve_t, now.date()) if not isinstance(curve_t, Exception) else []
        events = _rows(events_t) if not isinstance(events_t, Exception) else []
        prf = prf_rows(prf_t) if not isinstance(prf_t, Exception) else []
        # the FRONT month's own first notice (stored event naming it, else the CME PRF row, else the next stored FND) —
        # never the Nov serial's date under the DEC title (C-TRADER-13 / C-DATA-8)
        front_ym = (_dd(pts_c[0]["expiry"]).year, _dd(pts_c[0]["expiry"]).month) if pts_c and _d(pts_c[0].get("expiry")) else None
        fnd_info = _fnd_for_month(events, prf, front_ym, now.date())
        days_to_fnd = fnd_info["days_to_fnd"]
        if len(pts_c) >= 2 and is_published(cat, "COMEX_CARRY_ANN_PCT"):
            f1, f2 = pts_c[0], pts_c[1]
            spread_pct = (
                (f2["settle_or_last"] / f1["settle_or_last"] - 1) * 100 if f1["settle_or_last"] and f2["settle_or_last"] else None
            )
            dd = (_dd(f2["expiry"]) - _dd(f1["expiry"])).days if _d(f2["expiry"]) and _d(f1["expiry"]) else None
            roll_date = fnd_info["fnd_date"]
            gauges.append(
                _gauge(
                    "curve_roll",
                    "CURVE / ROLL (COMEX)",
                    "COMEX_CARRY_ANN_PCT",
                    spread_pct,
                    "%",
                    None,
                    window,
                    f1.get("trade_date"),
                    None,
                    max_age_of(cat, GC_FRONT_SERIES, 4.0),
                    f"Yahoo per-month prices ({f1.get('quality') or 'last trade'})",
                    None,
                    "(F2/F1 − 1) and × 365/days; contango is the normal state",
                    BADGE_ARITH,
                    "arithmetic · a cost, not a forecast",
                    {
                        "front": _mmy(f1["expiry"]),
                        "next": _mmy(f2["expiry"]),
                        "annualised_pct": annualised_carry_pct(f1["settle_or_last"], f2["settle_or_last"], dd),
                        "days_to_fnd": days_to_fnd,
                        "fnd_date": roll_date,
                        "ltd_date": fnd_info["ltd_date"],
                        "fnd_source": fnd_info["source"],
                    },
                )
            )
        else:
            gauges.append(
                _gauge(
                    "curve_roll",
                    "CURVE / ROLL (COMEX)",
                    "COMEX_CARRY_ANN_PCT",
                    None,
                    "%",
                    None,
                    window,
                    None,
                    None,
                    None,
                    "Yahoo per-month prices",
                    None,
                    "(F2/F1 − 1) × 365/days",
                    BADGE_ARITH,
                    "arithmetic · a cost, not a forecast",
                    {"days_to_fnd": days_to_fnd, "fnd_date": fnd_info["fnd_date"], "ltd_date": fnd_info["ltd_date"], "fnd_source": fnd_info["source"]},
                )
            )
            roll_date = fnd_info["fnd_date"]
            if len(pts_c) >= 2:
                gauges[-1].update(published=False, note=unpublished_note(cat, "COMEX_CARRY_ANN_PCT"))
    except Exception as exc:  # noqa: BLE001
        reads.errors["gauge:curve"] = type(exc).__name__

    verdict = verdict_sentence(gauges, window, extras)
    extras["roll_date"] = roll_date
    states = [g["state"] for g in gauges]
    oldest = max((g["age_days"] or 0 for g in gauges if g.get("age_days") is not None), default=None)
    summary = (
        "unavailable"
        if all(s == "unavailable" for s in states)
        else "stale"
        if "stale" in states
        else "delayed"
        if "delayed" in states
        else "live"
    )
    payload: dict[str, Any] = {
        "as_of": now.isoformat(timespec="seconds"),
        "window": window.upper(),
        "verdict": verdict,
        "gauges": gauges,
        "fair": fair,
        "line": health_line(verdict, gauges, roll_date),
        "freshness": {
            "state": summary,
            "oldest": oldest,
            "age_days": oldest,
            "unavailable": [g["key"] for g in gauges if g["state"] == "unavailable"],
            "stale": [g["key"] for g in gauges if g["state"] == "stale"],
        },
        "store_errors": reads.errors or None,
        "_served": reads.served,
        "_extras": extras,  # the verdict's inputs, so /overview can re-run the sentence after applying the live MCX quote
    }
    # the BRF line and the {wei, brf} pair belong to the payload itself, so /overview.health == /health (API_CONTRACT §2.1)
    payload["brf_line"] = brf_line(payload)
    payload["lines"] = {"wei": payload["line"], "brf": payload["brf_line"]}
    return payload


def apply_live_mcx(health: dict[str, Any], live: float | None, source: str | None, live_at: str | None) -> bool:
    """Fold a live MCX quote the page holds into a freshly built HEALTH payload (never a memoised one): the fair block's
    `mcx_live` / premium / desk state, the INDIA BASIS gauge at the live clock and the verdict re-run on the same inputs —
    so the header strip, h.open and the gauge print ONE basis (critics C-TRADER-10 / C-DATA-13: two desk states and two
    basis clocks from one page because the quote cache was filled after the fair block read it). Returns True when applied."""
    fair = health.get("fair") or {}
    if not live or fair.get("mcx_live") or not isinstance(health.get("gauges"), list):
        return False
    fair["mcx_live"], fair["mcx_live_source"], fair["mcx_live_as_of"] = live, source, live_at
    if fair.get("fair_value"):
        fair["premium_rupees"] = round(live - fair["fair_value"], 0)
        fair["premium_pct"] = round((live / fair["fair_value"] - 1) * 100, 2)
        fair["desk_verdict_state"] = gp._verdict_body(fair["fair_value"], live, CHASE_LIMIT_INR, True)["state"]
    lb = live_basis(fair)
    g = next((x for x in health["gauges"] if x.get("key") == "india_basis"), None)
    if lb and g and g.get("value") is not None and g.get("published", True):
        g.update(
            value=_r(lb["value"], 4),
            state="live",
            report_date=_now_ist().date().isoformat(),
            release_at=lb["as_of"],
            source="live MCX (Breeze) vs COMEX × INR × duty, now",
            clock="now",
            basis_label=lb["label"],
            basis_reference=lb.get("basis_reference"),
            live_basis_pct=lb["value"],
            mcx_live=live,
        )
    extras = health.get("_extras") or {}
    health["verdict"] = verdict_sentence(health["gauges"], str(health.get("window") or "W"), extras)
    health["line"] = health_line(health["verdict"], health["gauges"], extras.get("roll_date"))
    health["brf_line"] = brf_line(health)
    health["lines"] = {"wei": health["line"], "brf": health["brf_line"]}
    return True


def _mmy(expiry: Any) -> str | None:
    d = _d(expiry)
    return f"{d:%b-%y}".upper() if d else None


def curve_points(payload: Any, today: date) -> list[dict[str, Any]]:
    """Curve rows → sorted points with days_to_expiry, spread vs front and annualised carry (M31)."""
    rows = [r for r in _rows(payload) if _d(r.get("expiry"))]
    rows.sort(key=lambda r: str(r["expiry"])[:10])
    out: list[dict[str, Any]] = []
    for r in rows:
        px = _f(r.get("settle")) if r.get("settle") is not None else _f(r.get("close"))
        out.append(
            {
                "expiry": str(r["expiry"])[:10],
                "symbol": r.get("symbol"),
                "settle_or_last": px,
                "source": r.get("source"),
                "quality": r.get("quality"),
                "open_interest": _f(r.get("open_interest")),
                "oi_change": _f(r.get("oi_change")),
                "volume": _f(r.get("volume")),
                "trade_date": str(r.get("trade_date") or "")[:10] or None,
                "session_date": str(r.get("session_date") or "")[:10] or None,
                "days_to_expiry": (_dd(r["expiry"]) - today).days,
                "band_lo": _f(r.get("band_lo")),
                "band_hi": _f(r.get("band_hi")),
            }
        )
    if out and out[0]["settle_or_last"]:
        f1 = out[0]
        for p in out:
            p["spread_vs_front"] = _r(p["settle_or_last"] - f1["settle_or_last"], 2) if p["settle_or_last"] else None
            dd = (_dd(p["expiry"]) - _dd(f1["expiry"])).days
            p["annualised_carry_pct"] = annualised_carry_pct(f1["settle_or_last"], p["settle_or_last"], dd) if dd > 0 else None
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# route plumbing: TTL memo + the X-Cache headers of the stored pieces a response was built from
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _served_of(payload: dict[str, Any]) -> Served[None] | None:
    """Pop the `_served` list build_* functions attach and fold it into one summary (never in the body)."""
    served = payload.pop("_served", None)
    return merge_served(served) if served else None


def _memo(key: str, ttl: float, payload: dict[str, Any], served: Served[None] | None) -> None:
    _ttl.set(key, (payload, served), ttl=ttl)


def _memo_hit(key: str, response: Response | None) -> dict[str, Any] | None:
    hit = _ttl.get(key)
    if hit is None:
        return None
    payload, served = hit
    cache_headers(response, served)
    return payload


def _pct_change(now: float | None, then: float | None) -> float | None:
    return round((now / then - 1) * 100, 3) if now and then else None


def _diff(now: float | None, then: float | None) -> float | None:
    return round(now - then, 4) if now is not None and then is not None else None


def _date_arg(value: str | None, what: str) -> date | None:
    if not value:
        return None
    d = _d(value)
    if d is None:
        fail(422, "invalid", f"{what} must be YYYY-MM-DD")
    return d


def _since(rows: list[dict[str, Any]], key: str) -> str | None:
    """'since 27 Oct 2026': the first day a stored history has (PLAN 0.1 #3 — histories begin the day the job starts)."""
    days = sorted(str(r.get(key) or "")[:10] for r in rows if r.get(key))
    return days[0] if days else None


def _freshness_of_rows(rows: list[dict[str, Any]], key: str, max_age_days: float, source: str) -> dict[str, Any]:
    days = sorted(str(r.get(key) or "")[:10] for r in rows if r.get(key))
    return freshness(days[-1] if days else None, max_age_days, source)


def _bar_rows(payload: Any) -> list[dict[str, Any]]:
    """Bars with every intraday `ts` carrying its offset, in IST (`2026-11-04T23:49:57+05:30`): data-service stores naive
    UTC and the chart parsed it as local time, 5 h 30 early (C-TRADER-1 / C-DATA-1). A date-only `ts` (daily bars) stays
    a date. IST-day buckets (`day`, `prev_day`) therefore group by the IST calendar day, as the page's axis does."""
    rows = payload["bars"] if isinstance(payload, dict) and isinstance(payload.get("bars"), list) else _rows(payload)
    out: list[dict[str, Any]] = []
    for r in rows:
        ts = r.get("ts") or r.get("trade_date") or r.get("t")
        if not ts:
            continue
        out.append(
            {
                "ts": _iso_any(ts) or str(ts),
                "o": _f(r.get("open", r.get("o"))),
                "h": _f(r.get("high", r.get("h"))),
                "l": _f(r.get("low", r.get("l"))),
                "c": _f(r.get("close", r.get("c"))),
                "v": _f(r.get("volume", r.get("v"))),
            }
        )
    out.sort(key=lambda b: b["ts"])
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /health · GET /fair
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


@router.get("/health")
async def gold_health(window: str = Query("W", pattern="^[DWMdwm]$"), response: Response = None) -> dict[str, Any]:  # type: ignore[assignment]
    """The HEALTH payload (PLAN §d): eight gauges, the rule-based verdict (NO score, ends 'describes, does not predict'),
    the fair block and the one-line echoes for WEI (`line`) and BRF (`brf_line`). 60 s TTL per window; no Breeze on
    this path (the fair block reads the quote cache only)."""
    key = f"health:{window.upper()}"
    hit = _memo_hit(key, response)
    if hit is not None:
        return hit
    payload = await build_health(window.upper())
    served = _served_of(payload)  # PLAN §f.4 (no score key) is enforced by test_health_verdict_is_descriptive_and_has_no_score
    payload.pop("_extras", None)
    _memo(key, HEALTH_TTL_S, payload, served)
    cache_headers(response, served)
    return payload


def brf_line(health: dict[str, Any]) -> str:
    """BRF's one line (PLAN §b): before the open `Gold open: fair ₹X (gap −Y) · WAIT · <verdict words> · GOLD ›`; after the
    captured open `Gold opened ₹X vs fair ₹Y (miss ₹Z) · … · GOLD ›`; on an MCX holiday `Gold: MCX closed (name, opens
    17:00) · GOLD ›`."""
    fair = health.get("fair") or {}
    words = ((health.get("verdict") or {}).get("headline") or "").strip()
    hol = fair.get("mcx_holiday")
    if hol and hol.get("closure") == "full":
        return f"Gold: MCX closed ({hol['name']}) · GOLD ›"
    if hol and hol.get("closure") == "morning" and (fair.get("actual_open") is None):
        opens = (hol.get("opens_at") or "")[11:16]
        return f"Gold: MCX closed ({hol['name']}, opens {opens or '17:00'}) · GOLD ›"
    parts: list[str]
    if fair.get("actual_open") is not None and fair.get("snapshot_fair"):
        miss = fair.get("snapshot_error")
        miss_txt = f" (miss ₹{miss:+,.0f})".replace("-", "−") if miss is not None else ""
        parts = [f"Gold opened ₹{fair['actual_open']:,.0f} vs fair ₹{fair['snapshot_fair']:,.0f}{miss_txt}"]
    elif fair.get("fair_value"):
        gap = fair.get("gap_vs_settlement")
        gap_txt = f" (gap {gap:+,.0f})".replace("-", "−") if gap is not None else ""
        parts = [f"Gold open: fair ₹{fair['fair_value']:,.0f}{gap_txt}"]
        state = fair.get("desk_verdict_state")
        if state in ("OK", "WAIT"):
            parts.append(str(state))
        elif state is None and fair.get("premium_rupees") is not None:
            parts.append("OK" if abs(fair["premium_rupees"]) <= CHASE_LIMIT_INR else "WAIT")
    else:
        parts = ["Gold open: fair value unavailable"]
    if words:
        parts.append(words)
    parts.append("GOLD ›")
    return " · ".join(parts)


async def build_fair(
    baseline: float | None,
    mcx_price: float | None,
    threshold: float,
    eurusd_trigger: float | None,
    contract: str | None,
    expiry: str | None,
) -> dict[str, Any]:
    """Today's `/api/commodity/gold-preopen` body (GOLD only — the desk's model) + `baseline.session_label` (already there),
    `accuracy{}`, `holiday{}`, `badge` and, for another family or an explicit expiry, `contract_fair` from the same cached
    fetcher scaled to that contract's quotation unit."""
    body = await gp._gold_preopen(baseline, mcx_price, threshold, eurusd_trigger)
    rows = await asyncio.to_thread(gp.log_rows, 400)
    stats = gp.accuracy_stats(rows, threshold)
    today = _now_ist().date().isoformat()
    today_row = next((r for r in rows if r.get("date") == today), None)
    body["accuracy"] = {
        "days": stats.get("days", 0),
        "median_abs_error": stats.get("median_abs_error"),
        "mean_abs_error": stats.get("mean_abs_error"),
        "p90": stats.get("p90_abs_error"),
        "within_threshold_pct": stats.get("within_threshold_pct"),
        "naive_mean_abs_error": stats.get("naive_mean_abs_error"),
        "bias": stats.get("bias"),
        "threshold": threshold,
        # wave 1d round 2 (D2): which mornings a stale settlement decided, the stats without them, and the counterfactual on
        # the labelled sessions' VWAPs (never the score)
        "stale_baseline_count": stats.get("stale_baseline_count"),
        "stale_baseline_dates": stats.get("stale_baseline_dates"),
        "excluding_stale": stats.get("excluding_stale"),
        "on_vwap30": stats.get("on_vwap30"),
        "badge": BADGE_ARITH,
    }
    body["today_log"] = today_row
    body["holiday"] = body.get("holiday") and {
        "closure": body["holiday"]["closure"],
        "note": body["holiday"].get("note"),
        "name": body["holiday"].get("name"),
        "opens_at": body["holiday"].get("opens_at"),
    }
    body["badge"] = BADGE_ARITH
    body.setdefault("verdict", {})["badge"] = BADGE_HEURISTIC
    model = body.get("model") or {}
    body["freshness"] = freshness(
        (model.get("comex") or {}).get("as_of"), 1, "Yahoo (cached fetcher)", live=bool(model.get("fair_open"))
    )
    code = (contract or "GOLD").upper()
    if code != "GOLD" or expiry:
        if code not in mcxr.contract_specs():
            fail(422, "invalid", f"Unknown MCX contract '{contract}'", hint=f"One of {', '.join(mcxr.contract_specs())}")
        body["contract_fair"] = await fair_block(code, expiry)
    return body


@router.get("/fair")
async def gold_fair(
    baseline: float | None = Query(None, gt=0),
    mcx_price: float | None = Query(None, gt=0),
    threshold: float = Query(300, gt=0, le=5000),
    eurusd_trigger: float | None = Query(None, gt=0),
    contract: str | None = Query(None),
    expiry: str | None = Query(None),
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """The pre-open desk's home (h.open): today's `/api/commodity/gold-preopen` body + session label, accuracy, holiday,
    the heuristic badge on the verdict; `eurusd_trigger` and topics come from prefs unless given."""
    served: list[Served[None]] = []
    token = gp._SERVED.set(served)
    try:
        return await build_fair(baseline, mcx_price, threshold, eurusd_trigger, contract, expiry)
    finally:
        gp._SERVED.reset(token)
        cache_headers(response, merge_served(served))


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /series · GET /bars
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


@router.get("/series")
async def gold_series(
    ids: str = Query(..., min_length=1, max_length=2000),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    freq: str = Query("D", pattern="^[DWMdwm]$"),
    asof: str | None = Query(None),
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Stored series, point-in-time (`asof`) and resampled D|W|M with the catalog's `resample` rule. A series whose catalog
    row has no PUBLISH-* verdict is returned with `published: false` and no points (PLAN §f.2); one the store does not
    have comes back empty with `freshness.state = unavailable`."""
    wanted = [s.strip() for s in ids.split(",") if s.strip()][:64]
    start, end = _date_arg(from_, "from"), _date_arg(to, "to")
    asof_dt = _dt(asof) if asof else None
    if asof and asof_dt is None:
        fail(422, "invalid", "asof must be an ISO timestamp")
    reads = Reads()
    cat = await catalog(reads)
    days = (_now_ist().date() - start).days if start else 400
    series = await fetch_series(reads, wanted, days=max(1, days), asof=asof_dt)
    out: list[dict[str, Any]] = []
    for sid in wanted:
        row = cat.get(sid) or {}
        pts = series.get(sid) or []
        if end:
            pts = [p for p in pts if _dd(p["report_date"]) <= end]
        if start:
            pts = [p for p in pts if _dd(p["report_date"]) >= start]
        published = is_published(cat, sid)
        how = str(row.get("resample") or "last")
        res = resample_points(pts, freq, how) if published else []
        last_p = latest(res)
        out.append(
            {
                "series_id": sid,
                "name": row.get("name") or sid,
                "unit": row.get("unit") or "",
                "freq_native": row.get("freq") or "D",
                "quality": row.get("quality") or "official",
                "resample": how,
                "published": published,
                "note": None if published else unpublished_note(cat, sid),
                "points": res if published else [],
                "n": len(res),
                "catalog": {
                    "publisher": row.get("publisher"),
                    "verdict": row.get("verdict"),
                    "badge": row.get("badge"),
                    "lag_note": row.get("lag_note"),
                    "terms": row.get("terms"),
                    "evidence": row.get("evidence"),
                },
                "freshness": freshness(
                    (last_p or {}).get("report_date"), max_age_of(cat, sid, 5.0), row.get("publisher") or "data-service"
                ),
            }
        )
    payload = {
        "as_of": _now_ist().isoformat(timespec="seconds"),
        "asof_applied": _iso(asof_dt),
        "freq": freq.upper(),
        "series": out,
        "store_errors": reads.errors or None,
    }
    reads.headers(response)
    return payload


@router.get("/bars")
async def gold_bars(
    symbol: str = Query(GC_FRONT, max_length=24),
    interval: str = Query("1m", pattern="^(1m|5m|1d)$"),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """The DAILY chart's bars from the store (never a Yahoo call on this path): `bars`, the IST session bands, the previous
    day's closes as the dotted overlay, the last settlement line and the live last from the SWR cache when it holds one."""
    start, end = _date_arg(from_, "from"), _date_arg(to, "to")
    now = _now_ist()
    default_days = {"1m": 7, "5m": 60, "1d": 420}[interval]
    start = start or (now.date() - timedelta(days=default_days))
    reads = Reads()
    daily_symbol = GC_FRONT if symbol.upper() == GC_FRONT or symbol.upper().startswith("GC") else symbol
    bars_t, curve_t, daily_t = await _gather(
        reads.get(
            "/db/gold/bars", symbol=symbol, interval=interval, **{"from": start.isoformat()}, to=end.isoformat() if end else None
        ),
        reads.get("/db/gold/curve", exchange="COMEX"),
        reads.get("/db/gold/bars", symbol=daily_symbol, interval="1d", **{"from": (now.date() - timedelta(days=12)).isoformat()}),
    )
    bars = _bar_rows(bars_t) if not isinstance(bars_t, Exception) else []
    days = sorted({b["ts"][:10] for b in bars})
    prev_day = [{"ts": b["ts"], "c": b["c"]} for b in bars if len(days) > 1 and b["ts"][:10] == days[-2] and b["c"] is not None]
    today_bars = [b for b in bars if days and b["ts"][:10] == days[-1]]
    # the stored daily closes (Yahoo daily bars, not settlements) for the legend and the dashed line: the PREVIOUS
    # session's close, never the live last (C-TRADER-2 / C-TRADER-17); an IST-day bucket's last tick is labelled 'last'
    daily = _closes_from_bars(daily_t) if not isinstance(daily_t, Exception) else []
    comex_open = comex_session(now)["is_open"]
    daily_closes = [
        {
            "date": p["report_date"],
            "close": p["value"],
            "partial": _dd(p["report_date"]) >= now.date() and comex_open,
            "label": f"{_day_label(p['report_date'])} {'last (partial day)' if _dd(p['report_date']) >= now.date() and comex_open else 'close'} (Yahoo daily bar)",
        }
        for p in daily[-4:]
    ]
    prev_close = next((c for c in reversed(daily_closes) if not c["partial"] and (not days or c["date"] < days[-1])), None)
    settle_line = None
    matched_last = None
    pts = curve_points(curve_t, now.date()) if not isinstance(curve_t, Exception) else []
    if pts:
        matched = _curve_point_for_symbol(pts, symbol)
        if matched and matched.get("settle_or_last"):
            is_settle = str(matched.get("source") or "").startswith("cme")
            matched_last = {
                "value": matched["settle_or_last"],
                "label": f"{_mmy(matched['expiry'])} {'settlement' if is_settle else 'last trade (Yahoo), not a settlement'} {matched.get('trade_date') or ''}".strip(),
                "source": matched.get("source"),
                "quality": matched.get("quality"),
                "is_settlement": is_settle,
            }
            if is_settle:
                settle_line = matched_last
    if settle_line is None and prev_close:
        settle_line = {
            "value": prev_close["close"],
            "label": prev_close["label"],
            "source": "data-service gold_daily_bars (Yahoo)",
            "quality": "close",
            "is_settlement": False,
        }
    live = gp._cache.get(f"yahoo:{symbol}:5d:5m")  # peek only: never start a fetch from this route
    last = None
    if live and isinstance(live[1], dict) and live[1].get("price"):
        t = live[1].get("time")
        last = {
            "price": float(live[1]["price"]),
            "as_of": t.isoformat(timespec="seconds") if isinstance(t, datetime) else None,
            "source": "Yahoo (SWR cache)",
            "age_s": int(max(0.0, time.monotonic() - live[0])),
        }
    hi = max((b["h"] for b in today_bars if b["h"] is not None), default=None)
    lo = min((b["l"] for b in today_bars if b["l"] is not None), default=None)
    instrument = (
        "COMEX front GC1 (continuous)"
        if symbol.upper() == GC_FRONT
        else "COMEX matched month"
        if symbol.upper().startswith("GC")
        else "spot proxy"
        if "XAU" in symbol.upper()
        else symbol
    )
    payload = {
        "symbol": symbol,
        "interval": interval,
        "bars": bars,
        "instrument": instrument,
        "day": days[-1] if days else None,
        "hi": hi,
        "lo": lo,
        "sessions": session_bands(now.date()),
        "settle_line": settle_line,
        "matched_last": matched_last,
        "prev_close": prev_close,
        "daily_closes": daily_closes,
        "prev_day": prev_day,
        "last": last,
        "since": days[0] if days else None,
        "freshness": freshness(
            bars[-1]["ts"] if bars else None,
            1.0,
            "data-service gold_bars_intraday" if interval != "1d" else "data-service gold_daily_bars",
            live=bool(last),
        ),
        "note": "stored bars only; the live last is the SWR cache the pre-open desk already fills (PLAN 0.1 #2/#3)",
        "store_errors": reads.errors or None,
    }
    reads.headers(response)
    return payload


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /cot — who is long, who is short (weekly CFTC; descriptive only)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _group_block(
    row: dict[str, Any], prev: dict[str, Any] | None, g: str, label: str, oi: float | None, price: float | None
) -> dict[str, Any]:
    lo, sh, sp = _f(row.get(f"{g}_long")), _f(row.get(f"{g}_short")), _f(row.get(f"{g}_spread"))
    net = None if lo is None or sh is None else lo - sh
    chg_l = _f(row.get(f"chg_{g}_long"))
    chg_s = _f(row.get(f"chg_{g}_short"))
    if chg_l is None and prev is not None and lo is not None and _f(prev.get(f"{g}_long")) is not None:
        chg_l = lo - _ff(prev.get(f"{g}_long"))
    if chg_s is None and prev is not None and sh is not None and _f(prev.get(f"{g}_short")) is not None:
        chg_s = sh - _ff(prev.get(f"{g}_short"))
    chg_net = None if chg_l is None or chg_s is None else chg_l - chg_s
    return {
        "key": g,
        "label": label,
        "long": lo,
        "short": sh,
        "spread": sp,
        "net": net,
        "net_moz": _r(net * OZ_PER_CONTRACT / 1e6, 3) if net is not None else None,
        "net_t": _r(net * OZ_PER_CONTRACT / 32150.7466, 1) if net is not None else None,
        "net_usd_bn": _r(net * OZ_PER_CONTRACT * price / 1e9, 2) if net is not None and price else None,
        "chg_long": chg_l,
        "chg_short": chg_s,
        "chg_net": chg_net,
        "pct_oi_long": _r(lo / oi * 100, 1) if lo is not None and oi else None,
        "pct_oi_short": _r(sh / oi * 100, 1) if sh is not None and oi else None,
        "net_pct_oi": _r(net / oi * 100, 1) if net is not None and oi else None,
        "traders_long": _f(row.get(f"traders_{g}_long")),
        "traders_short": _f(row.get(f"traders_{g}_short")),
        "who_did": who_did(chg_l, chg_s),
    }


_COMEX_MONTH_NO = {v: k for k, v in gp.COMEX_MONTH.items()}


def symbol_expiry_month(symbol: str) -> tuple[int, int] | None:
    """`GCZ26.CMX` / `GCG27` → (2026, 12) / (2027, 2); None for the continuous front (`GC=F`) or a non-GC symbol."""
    s = symbol.upper().split(".")[0]
    if len(s) != 5 or not s.startswith("GC") or s[2] not in _COMEX_MONTH_NO or not s[3:].isdigit():
        return None
    return 2000 + int(s[3:]), _COMEX_MONTH_NO[s[2]]


def _curve_point_for_symbol(pts: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    """The curve point whose expiry falls in the symbol's delivery month (GCG27 → the FEB-27 line, never the front's);
    the front for `GC=F`; None when the month is not on the stored curve (no line rather than the wrong one)."""
    if not pts:
        return None
    ym = symbol_expiry_month(symbol)
    if ym is None:
        return pts[0] if symbol.upper() == GC_FRONT else None
    for p in pts:
        e = _d(p.get("expiry"))
        if e and (e.year, e.month) == ym:
            return p
    return None


# The COMEX month the page matches an MCX expiry to (C-BEGINNER-26; 5 Nov review): ONE helper for GOLD, CONTRACTS and MCXG,
# defined in gold_preopen so mcx.py (which this module imports) uses the very same function.
COMEX_LIQUID_MONTHS = gp.COMEX_LIQUID_MONTHS
comex_liquid_symbol = gp.comex_liquid_symbol


def prf_rows(payload: Any, symbol_root: str = "GC") -> list[dict[str, Any]]:
    """gold_cme_prf rows of one product on its latest business date, sorted by maturity (contract months in order)."""
    rows = [r for r in _rows(payload) if str(r.get("symbol") or "").upper() == symbol_root.upper() and _d(r.get("mat_date"))]
    if not rows:
        return []
    last_biz = max(str(r.get("biz_date") or "") for r in rows)
    rows = [r for r in rows if str(r.get("biz_date") or "") == last_biz]
    rows.sort(key=lambda r: str(r.get("mat_date"))[:10])
    return rows


def prf_row_for_month(rows: list[dict[str, Any]], ym: tuple[int, int] | None) -> dict[str, Any] | None:
    """The PRF row whose contract month (`mmy` = YYYYMM, else the maturity's month) is `ym`; None when not listed."""
    if ym is None:
        return None
    want = f"{ym[0]:04d}{ym[1]:02d}"
    for r in rows:
        mmy = str(r.get("mmy") or "")[:6]
        if (mmy if len(mmy) == 6 and mmy.isdigit() else _dd(r.get("mat_date")).strftime("%Y%m")) == want:
            return r
    return None


def prf_events(rows: list[dict[str, Any]], today: date, months: int = 4) -> list[dict[str, Any]]:
    """COMEX first-notice / last-trade rows computed from the stored PRF (critic C-TRADER-13 / C-DATA-8: no GCZ26 FND anywhere
    while `gold_cme_calendar` is empty). Only months whose last trade is still ahead; the store's own rows win on dedupe."""
    out: list[dict[str, Any]] = []
    n = 0
    for r in rows:
        ltd, fnd = _d(r.get("last_trd")), _d(r.get("first_notice"))
        if not ltd or ltd < today:
            continue
        mat = _dd(r.get("mat_date"))
        ym_label = f"{mat.year:04d}-{mat.month:02d}"  # the same name data-service's compile_events writes (dedupes on it)
        sym = str(r.get("symbol") or "GC").upper()
        if fnd and fnd >= today:
            out.append(
                {
                    "event_date": fnd.isoformat(),
                    "time_ist": None,
                    "kind": "COMEX_FND",
                    "name": f"COMEX {sym} {ym_label} first notice day",
                    "country": "US",
                    "impact": "roll",
                    "in_session": False,
                    "source": "CME PRF (gold_cme_prf, computed)",
                    "contract_month": ym_label,
                }
            )
        out.append(
            {
                "event_date": ltd.isoformat(),
                "time_ist": "23:00",
                "kind": "COMEX_LTD",
                "name": f"COMEX {sym} {ym_label} last trading day",
                "country": "US",
                "impact": "roll",
                "in_session": False,
                "source": "CME PRF (gold_cme_prf, computed)",
                "contract_month": ym_label,
            }
        )
        n += 1
        if n >= months:
            break
    return out


def _fnd_for_month(events: list[dict[str, Any]], rows: list[dict[str, Any]], ym: tuple[int, int] | None, today: date) -> dict[str, Any]:
    """{fnd_date, ltd_date, days_to_fnd, source} for one contract month: a stored FND event naming that month first, then
    the PRF row, then the next stored FND event at or after today (the front's, unlabelled)."""
    label = f"{date(ym[0], ym[1], 1):%b-%y}".upper() if ym else None
    stored = sorted(
        (
            e
            for e in events
            if _d(e.get("event_date"))
            and (str(e.get("kind") or "").upper() in ("COMEX_FND", "FND") or "first notice" in str(e.get("name") or "").lower())
        ),
        key=lambda e: str(e.get("event_date")),
    )

    def _names_month(e: dict[str, Any]) -> bool:
        # data-service names the month `COMEX GC 2026-12 first notice day` (and sets contract_month); older rows and the
        # fixtures say `GCZ26` or `DEC-26` — every spelling of the SAME month matches, no other month does
        if ym is None:
            return False
        text = str(e.get("name") or "").upper()
        ym_iso = f"{ym[0]:04d}-{ym[1]:02d}"
        sym_month = f"GC{gp.COMEX_MONTH[ym[1]]}{ym[0] % 100:02d}"
        return (
            str(e.get("contract_month") or "") in (ym_iso, label)
            or ym_iso in text
            or sym_month in text
            or (label is not None and label in text.replace(" ", "-"))
        )

    hit = next((e for e in stored if _names_month(e)), None)
    if hit:
        fnd = _dd(hit["event_date"])
        return {"fnd_date": fnd.isoformat(), "ltd_date": None, "days_to_fnd": (fnd - today).days, "source": "gold_events"}
    row = prf_row_for_month(rows, ym)
    if row and _d(row.get("first_notice")):
        fnd = _dd(row["first_notice"])
        return {
            "fnd_date": fnd.isoformat(),
            "ltd_date": str(row.get("last_trd") or "")[:10] or None,
            "days_to_fnd": (fnd - today).days,
            "source": "CME PRF",
        }
    nxt = next((e for e in stored if _dd(e["event_date"]) >= today), None)
    if nxt:
        fnd = _dd(nxt["event_date"])
        return {"fnd_date": fnd.isoformat(), "ltd_date": None, "days_to_fnd": (fnd - today).days, "source": "gold_events (next FND)"}
    return {"fnd_date": None, "ltd_date": None, "days_to_fnd": None, "source": None}


def _purity_txt(fair: dict[str, Any]) -> str:
    p = fair.get("purity")
    return f" at {p}" if p else ""


def settle_basis(fair: dict[str, Any], basis_pts: list[dict[str, Any]]) -> dict[str, Any]:
    """ONE settlement-clock MCX basis for the whole page (critics C-TRADER-10 / C-DATA-11 / C-BEGINNER-5; wave 1d): the
    desk's own figure — the settlement (last-30-min VWAP, else the band of its REAL session) ÷ the duty-paid landed price of
    the contract's purity at THAT session's 30-minute close reference − 1: both legs on one clock, purity-correct. The stored
    `MCX_BASIS_PCT` (data-service derive: GOLD's settlement against that day's duty-paid landed × 995/1000 — PM decision D1)
    only stands in when the desk has no model, and only for its own date. {value, date, label, series_id, source, clock,
    basis_reference}."""
    sess = fair.get("settlement_session")
    ref = fair.get("basis_reference")
    if fair.get("basis_pct") is not None and sess:
        src = "last-30-min VWAP (Breeze)" if fair.get("settlement_source") == "breeze_vwap30" else "band midpoint"
        return {
            "value": _r(fair["basis_pct"], 2),
            "date": sess,
            "label": f"at the {fair.get('settlement_session_label') or sess} ({src}, proxy) vs that session's duty-paid "
            f"landed{_purity_txt(fair)}",
            "series_id": "MCX_BASIS_PCT",
            "source": "desk model at the settlement session's 30-min close reference",
            "clock": "settlement",
            "basis_reference": ref,
        }
    stored = next((p for p in reversed(basis_pts) if sess and p["report_date"] == sess), None) if basis_pts else None
    if stored is not None:
        return {
            "value": _r(stored["value"], 2),
            "date": stored["report_date"],
            "label": f"GOLD at the {gp.session_label(_dd(stored['report_date']))} vs that day's duty-paid landed × 995/1000 (stored)",
            "series_id": "MCX_BASIS_PCT",
            "source": "data-service derive (stored)",
            "clock": "settlement",
            "basis_reference": gp.basis_reference("GOLD"),
        }
    return {"value": None, "date": None, "label": None, "series_id": "MCX_BASIS_PCT", "source": None, "clock": None,
            "basis_reference": ref}


def mcx_is_open(now: datetime | None = None) -> bool:
    """True only inside an MCX trading window (shared.mcx_specs.session_state): a quote the cache still holds after the
    23:30/23:55 close, or before the 09:00 open on a logged-in morning, is a frozen LTP and must never be divided by a
    duty-paid landed price that keeps moving with COMEX overnight (wave-1c re-check major)."""
    try:
        return bool(specs.session_state(now or _now_ist())["is_open"])
    except Exception:  # noqa: BLE001 — a holiday-table error never turns a frozen quote into a live basis
        return False


def live_basis(fair: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """The live-clock basis: the cached MCX quote ÷ the duty-paid landed computed now − 1 (both legs 'now'); None without
    a live quote AND outside MCX hours (a cached LTP after the close is not 'now'). Never divided across clocks."""
    live = fair.get("mcx_live")
    dp = fair.get("duty_paid_landed_purity") or fair.get("duty_paid_landed")   # the landed price of the contract's purity
    if not live or not dp or not mcx_is_open(now):
        return None
    return {
        "value": _r((live / dp - 1) * 100, 2),
        "mcx_live": live,
        "duty_paid_landed": dp,
        "basis_reference": fair.get("basis_reference") if fair.get("duty_paid_landed_purity") else "landed_fine",
        "as_of": (fair.get("comex") or {}).get("as_of"),
        "label": f"live MCX ({fair.get('mcx_live_source') or 'quote'}) vs duty-paid landed{_purity_txt(fair)} now",
        "clock": "now",
    }


def _close_on(closes: list[dict[str, Any]], d: date | None) -> float | None:
    """Last close on or before d."""
    if d is None:
        return None
    before = [p for p in closes if _dd(p["report_date"]) <= d]
    return before[-1]["value"] if before else None


def _row_on_or_before(rows: list[dict[str, Any]], d: date) -> dict[str, Any] | None:
    before = [r for r in rows if _d(r.get("report_date")) and _dd(r["report_date"]) <= d]
    return before[-1] if before else None


def cot_identity(row: dict[str, Any]) -> dict[str, Any]:
    """The disaggregated report's OI identity on the long side: pm + sd (long + spread) + mm (long + spread) + or (long +
    spread) + nr long = open interest (C-TRADER-28: the old check needed the legacy `c_long` column the disagg rows lack).
    {identity_check: bool|null, identity_gap, identity_note}."""
    needed = ("pm_long", "sd_long", "sd_spread", "mm_long", "mm_spread", "or_long", "or_spread", "nr_long", "open_interest")
    vals = {k: _f(row.get(k)) for k in needed}
    if all(v is not None for v in vals.values()):
        long_side = sum(v for k, v in vals.items() if k != "open_interest")  # type: ignore[misc]
        gap = round(long_side - _ff(vals["open_interest"]), 0)
        return {
            "identity_check": abs(gap) < 1,
            "identity_gap": gap,
            "identity_note": "pm + sd + mm + or (long + spread) + nr long = OI (disaggregated, long side)",
        }
    if row.get("c_long") is not None and row.get("pm_long") is not None:
        gap = round((_f(row.get("c_long")) or 0) - ((_f(row.get("pm_long")) or 0) + (_f(row.get("sd_long")) or 0) + (_f(row.get("sd_spread")) or 0)), 0)
        return {"identity_check": abs(gap) < 1, "identity_gap": gap, "identity_note": "legacy commercial long = pm + sd long + sd spread"}
    return {"identity_check": None, "identity_gap": None, "identity_note": "columns missing for the identity"}


def build_cot(
    rows_main: list[dict[str, Any]],
    rows_c: list[dict[str, Any]],
    closes: list[dict[str, Any]],
    etf_pts: list[dict[str, Any]],
    weeks: int,
    report: str,
    now: datetime | None = None,
    rows_f: list[dict[str, Any]] | None = None,
    ds_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The POSITIONING payload from gold_cot rows: `rows_main` is the requested report (futures-only or combined, gold +
    micro gold), `rows_c` the combined and `rows_f` the futures-only rows of the same weeks (the options overlay is ALWAYS
    combined − futures, whichever mode the page asked for; `rows_f` defaults to `rows_main`), GC=F daily closes and GLD
    tonnes; `ds_summary` is data-service's own summary block beside the rows (`crowd.percentile_all`,
    `open_interest.pct_rank` over the FULL 1986→ panel — passed through, never recomputed over the fetched window). Pure
    (unit-tested with the 20 Oct 2026 report: OI 402,279, MM net 104,206, closed 3,777 longs / covered 894 shorts). None
    when there is no report."""
    now = now or _now_ist()
    rows_f = rows_main if rows_f is None else rows_f
    ds_summary = ds_summary or {}
    main = [r for r in rows_main if str(r.get("contract_code") or GOLD_CODE).strip() == GOLD_CODE]
    micro = [r for r in rows_main if str(r.get("contract_code") or "").strip() == MICRO_GOLD_CODE]
    if not main:
        return None
    last, prev = main[-1], (main[-2] if len(main) > 1 else None)
    rd = _dd(last["report_date"])
    oi, oi_prev = _f(last.get("open_interest")), _f(prev.get("open_interest")) if prev else None
    oi_chg = _f(last.get("oi_chg"))
    if oi_chg is None and oi is not None and oi_prev is not None:
        oi_chg = oi - oi_prev
    price = _close_on(closes, rd)
    price_prev = _close_on(closes, rd - timedelta(days=7))
    dp = _pct_change(price, price_prev)
    group_defs = list(COT_GROUPS) + (
        [("nc", "Non-commercial (legacy large specs)", "nc"), ("c", "Commercial (legacy)", "c")]
        if report == "legacy" or last.get("nc_long") is not None
        else []
    )
    groups = [_group_block(last, prev, g, label, oi, price) for g, label, _ in group_defs if last.get(f"{g}_long") is not None]
    mm = next((g for g in groups if g["key"] == "mm"), None)
    nets = [
        n
        for n in (
            (_f(r.get("mm_long")) or 0) - (_f(r.get("mm_short")) or 0) if r.get("mm_long") is not None else None for r in main
        )
        if n is not None
    ]
    all_oi = [v for v in (_f(r.get("open_interest")) for r in main) if v is not None]
    rel = _dt(last.get("release_at"))
    age_days = (now - rel).total_seconds() / 86400 if rel else None
    nxt = next_cot_release(rd, now, last.get("release_at"))
    idx52 = cot_index(nets, 52)
    # percentiles: the ALL-history figures are data-service's (expanding, 1986→, stored on the row when it computes them);
    # what ui-api can compute itself is a percentile over the reports it fetched, and it is labelled so (C-DATA-14: "26th
    # all-history percentile" was a 160-report window; the full panel says 50)
    ds_pct = _f((ds_summary.get("crowd") or {}).get("percentile_all"))
    if ds_pct is None:
        ds_pct = _f(last.get("mm_net_pctile_all"))
    ds_oi_pct = _f((ds_summary.get("open_interest") or {}).get("pct_rank"))
    if ds_oi_pct is None:
        ds_oi_pct = _f(last.get("oi_pctile_all"))
    years = max(1, round(len(nets) / 52)) if nets else 0
    crowd = {
        "cot_index_26": cot_index(nets, 26),
        "cot_index_52": idx52,
        "cot_index_156": cot_index(nets, 156),
        "z52": zscore(nets, 52),
        "z156": zscore(nets, 156),
        "percentile_all": ds_pct,
        "percentile_window": pct_rank(nets, nets[-1]) if nets else None,
        "window_reports": len(nets),
        "window_label": f"{years}-y percentile ({len(nets)} reports)" if nets else None,
        "percentile_label": "all-history percentile (1986→, data-service)" if ds_pct is not None else (f"{years}-y percentile ({len(nets)} reports)" if nets else None),
        "n_reports": len(nets),
        "label": CROWD_LABEL,
        "badge": BADGE_CONTEXT,
    }
    # options overlay (M22): combined − futures-only on the same report date, whichever report the page asked for
    overlay: dict[str, Any] = {
        "mm_net_options_only": None,
        "combined_oi": None,
        "line": "options overlay: combined report not stored",
    }

    def _same_week(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next(
            (
                r
                for r in reversed(rows)
                if _d(r.get("report_date")) == rd and str(r.get("contract_code") or GOLD_CODE).strip() == GOLD_CODE
            ),
            None,
        )

    same_c, same_f = _same_week(rows_c), _same_week(rows_f)
    if same_c and same_f and same_c.get("mm_long") is not None and same_f.get("mm_long") is not None:
        net_c = _ff(same_c["mm_long"]) - _ff(same_c["mm_short"])
        net_f = _ff(same_f["mm_long"]) - _ff(same_f["mm_short"])
        opt_only = net_c - net_f
        overlay = {
            "mm_net_options_only": opt_only,
            "combined_oi": _f(same_c.get("open_interest")),
            "mm_net_combined": net_c,
            "line": (
                f"options {'add' if opt_only >= 0 else 'take'} {abs(opt_only):+,.0f}".replace("+", "")
                + f" {'to' if opt_only >= 0 else 'from'} funds' net; combined OI "
                f"{_f(same_c.get('open_interest')) or 0:,.0f} · no information in the options-only leg (G-STUDY)"
            ),
        }
    # history (last `weeks` reports) with a rolling 52-report COT index
    hist_rows = main[-max(weeks, 1) :]
    history: list[dict[str, Any]] = []
    for i, r in enumerate(hist_rows):
        k = len(main) - len(hist_rows) + i + 1
        history.append(
            {
                "report_date": str(r["report_date"])[:10],
                "price": _close_on(closes, _d(r["report_date"])),
                **{f"{g}_net": _cot_net(r, g) for g in ("mm", "or", "nr", "sd", "pm")},
                "oi": _f(r.get("open_interest")),
                "cot_index_52": cot_index(nets[:k], 52) if len(nets) >= k else None,
            }
        )
    # rally / decline decomposition (M24): since the last 2-year low and since the high of that window
    decomposition: list[dict[str, Any]] = []
    window = [p for p in closes if _dd(p["report_date"]) >= rd - timedelta(days=730)]
    if window and mm:
        low = min(window, key=lambda p: p["value"])
        high = max(window, key=lambda p: p["value"])
        for span, anchor in (("since the 2-year low", low), ("since the high", high)):
            base = _row_on_or_before(main, _dd(anchor["report_date"]))
            if not base or base is last:
                continue

            def dnet(g: str, _base: dict[str, Any] = base) -> float | None:
                return _diff(_cot_net(last, g), _cot_net(_base, g))

            gld_from = _close_on(etf_pts, _d(anchor["report_date"]))
            gld_to = etf_pts[-1]["value"] if etf_pts else None
            decomposition.append(
                {
                    "span": span,
                    "from_date": str(base["report_date"])[:10],
                    "to_date": str(rd),
                    "price_from": anchor["value"],
                    "price_to": price,
                    "d_mm_long": _diff(_f(last.get("mm_long")), _f(base.get("mm_long"))),
                    "d_mm_short": _diff(_f(last.get("mm_short")), _f(base.get("mm_short"))),
                    "d_mm_net": dnet("mm"),
                    "d_sd_net": dnet("sd"),
                    "d_pm_net": dnet("pm"),
                    "d_comm_net": _diff(
                        (_cot_net(last, "sd") or 0) + (_cot_net(last, "pm") or 0),
                        (_cot_net(base, "sd") or 0) + (_cot_net(base, "pm") or 0),
                    ),
                    "d_or_net": dnet("or"),
                    "d_nr_net": dnet("nr"),
                    "d_oi": _diff(oi, _f(base.get("open_interest"))),
                    "d_gld_t": _diff(gld_to, gld_from),
                }
            )
    micro_last = micro[-1] if micro else None
    drawer = {
        "traders": {
            k: _f(last.get(f"traders_{k}"))
            for k in (
                "total",
                "mm_long",
                "mm_short",
                "mm_spread",
                "sd_long",
                "sd_short",
                "pm_long",
                "pm_short",
                "or_long",
                "or_short",
            )
        },
        "average_position": {
            g: _r(_ff(last.get(f"{g}_long")) / _ff(last.get(f"traders_{g}_long")), 0)
            for g in ("mm", "sd", "pm", "or")
            if _f(last.get(f"traders_{g}_long")) and _f(last.get(f"{g}_long")) is not None
        },
        "concentration": {
            k: _f(last.get(f"conc_{k}"))
            for k in (
                "gross4_long",
                "gross4_short",
                "gross8_long",
                "gross8_short",
                "net4_long",
                "net4_short",
                "net8_long",
                "net8_short",
            )
        },
        "micro_gold": (
            {
                "report_date": str(micro_last["report_date"])[:10],
                "open_interest": _f(micro_last.get("open_interest")),
                "mm_net": _cot_net(micro_last, "mm"),
                "nr_net": _cot_net(micro_last, "nr"),
                "note": "MGC (088695): the retail read",
            }
            if micro_last
            else None
        ),
        "raw_block_url": COT_RAW_URL,
        "api_query": COT_API_QUERY,
        **cot_identity(last),
    }
    return {
        "as_of": now.isoformat(timespec="seconds"),
        "report": report,
        "latest": {
            "report_date": str(rd),
            "release_at": _iso_any(last.get("release_at")),  # IST ISO with the offset (C-DATA-6: naive UTC printed as IST)
            "release_ist": cot_release_label(rel) if rel else None,
            "next_report_date": nxt["report_date"],
            "next_release_at": nxt["at"],
            "next_release_ist": nxt["ist"],
            "next_release_source": nxt["source"],
            "age_days": _r(age_days, 1),
            "stale": bool(age_days is not None and age_days > STALE_COT_DAYS),
            "catch_up_note": (
                "release older than 10 days: CFTC delay or shutdown — showing the last stored report"
                if age_days is not None and age_days > STALE_COT_DAYS
                else None
            ),
        },
        "open_interest": {
            "total": oi,
            "chg": oi_chg,
            "pct_rank": ds_oi_pct if ds_oi_pct is not None else (pct_rank(all_oi, oi) if oi is not None else None),
            "pct_rank_label": "all-history percentile (1986→, data-service)" if ds_oi_pct is not None else (f"{years}-y percentile ({len(all_oi)} reports)" if all_oi else None),
        },
        "groups": groups,
        "driver_label": driver_label(mm["chg_long"], mm["chg_short"], dp) if mm else None,
        "driver_rule": DRIVER_RULE_TEXT,
        "quadrant_label": quadrant_label(dp, oi_chg),
        "week_price_chg_pct": _r(dp, 2),
        "price_tue": price,
        "price_prev_tue": price_prev,
        "crowd": crowd,
        "options_overlay": overlay,
        "history": history,
        "decomposition": decomposition,
        "drawer": drawer,
        "badge": BADGE_CONTEXT,
        "evidence": "context · G-STUDY 26 Oct 2026: explains the week — does not forecast",
        "footer": COT_FOOTER,
        "freshness": freshness(last.get("release_at") or str(rd), 9.0, "CFTC (data-service gold_cot)"),
    }


@router.get("/cot")
async def gold_cot(
    weeks: int = Query(52, ge=1, le=2000),
    report: str = Query("disagg", pattern="^(disagg|legacy)$"),
    fut_or_combined: str = Query("F", pattern="^[FC]$"),
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Weekly COT: who is long / short, what got opened or closed, the fund-driver label, crowdedness (context only), the
    options overlay line, history, the rally/decline decomposition and the drawer. Badge `context`; never a signal."""
    reads = Reads()
    now = _now_ist()
    need = max(weeks, 160)
    other_mode = "C" if fut_or_combined == "F" else "F"
    main_t, other_t, bars_t, etf_t, micro_t = await _gather(
        reads.get("/db/gold/cot", weeks=need, report=report, fut_or_combined=fut_or_combined),
        reads.get("/db/gold/cot", weeks=4, report=report, fut_or_combined=other_mode),
        reads.get(
            "/db/gold/bars", symbol=GC_FRONT, interval="1d", **{"from": (now.date() - timedelta(days=need * 7 + 30)).isoformat()}
        ),
        reads.get("/db/gold/etf", **{"from": (now.date() - timedelta(days=800)).isoformat()}),
        reads.get("/db/gold/cot", weeks=4, report=report, fut_or_combined=fut_or_combined, contract=MICRO_GOLD_CODE),
    )
    rows_main = _cot_rows(main_t) if not isinstance(main_t, Exception) else []
    micro = [r for r in (_cot_rows(micro_t) if not isinstance(micro_t, Exception) else [])
             if str(r.get("contract_code") or "").strip() == MICRO_GOLD_CODE]
    rows_other = _cot_rows(other_t) if not isinstance(other_t, Exception) else []
    closes = _closes_from_bars(bars_t) if not isinstance(bars_t, Exception) else []
    etf_rows = (
        [r for r in _rows(etf_t) if str(r.get("fund") or "GLD").upper() == "GLD"] if not isinstance(etf_t, Exception) else []
    )
    # the overlay is combined − futures in BOTH modes: name the two reports by what they are, not by what was asked
    rows_f, rows_c = (rows_main, rows_other) if fut_or_combined == "F" else (rows_other, rows_main)
    # data-service merges its full-panel summary beside `rows` (crowd.percentile_all, open_interest.pct_rank, driver_rule)
    ds_summary = {k: v for k, v in main_t.items() if k != "rows"} if isinstance(main_t, dict) else {}
    payload = build_cot(
        rows_main + micro,
        rows_c,
        closes,
        _points(etf_rows, value_key="tonnes"),
        weeks,
        report,
        now,
        rows_f=rows_f,
        ds_summary=ds_summary,
    )
    reads.headers(response)
    if payload is None:
        return degraded(
            {
                "as_of": now.isoformat(timespec="seconds"),
                "latest": None,
                "groups": [],
                "history": [],
                "badge": BADGE_CONTEXT,
                "footer": COT_FOOTER,
                "freshness": freshness(None, 9.0, "CFTC (data-service gold_cot)"),
                "store_errors": reads.errors or None,
            },
            "upstream_down" if reads.errors else "state",
            "no COT report stored yet",
            hint="the Saturday 02:30 job (gold_cot_weekly) fills gold_cot; backfill per PLAN c.4",
        )
    payload["fut_or_combined"] = fut_or_combined
    payload["store_errors"] = reads.errors or None
    return payload


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /positioning/daily — what got opened or closed yesterday (exchange OI, never "who")
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _is_futures(foi: Any) -> bool:
    return str(foi or "F").upper() not in ("C", "P", "O")


def sessions_between(a: date, b: date) -> int:
    """Weekday sessions in (a, b] — how many sessions a stored delta spans when the master skipped days (C-TRADER-18:
    a 29 Oct → 3 Nov OI change printed as one day's). Holidays are not subtracted: an upper bound, labelled 'over N sessions'."""
    if b <= a:
        return 0
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


MIN_AVG_SESSIONS = 5  # an "N-day average" renders only with this many prior sessions (C-DATA-19 / C-TRADER-21)


def mcx_tender_start(expiry: date) -> date:
    """MCX gold futures: the tender period opens on the 1st of the expiry month (contract spec; the MCX circular is the
    legal source) — C-TRADER-28: the old 'expiry − 4 days' was neither the spec nor sessions."""
    return expiry.replace(day=1)


def build_positioning_comex(
    voi_rows: list[dict[str, Any]],
    closes: list[dict[str, Any]],
    curve: list[dict[str, Any]],
    events: list[dict[str, Any]],
    today: date,
    prf: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [r for r in voi_rows if str(r.get("product_code") or "").upper() in CME_GOLD_PRODUCTS and _d(r.get("trade_date"))]
    rows.sort(key=lambda r: (str(r["trade_date"])[:10], str(r.get("product_code")), str(r.get("fut_or_opt") or "F")))
    out_rows = []
    for r in rows:
        code = str(r["product_code"]).upper()
        foi = str(r.get("fut_or_opt") or "F").upper()
        label = code if _is_futures(foi) else f"{code}:{foi}"
        out_rows.append(
            {
                "trade_date": str(r["trade_date"])[:10],
                "symbol_or_product": label,
                "product_desc": r.get("product_desc"),
                "expiry": None,
                "open_interest": _f(r.get("open_interest")),
                "oi_change": _f(r.get("oi_change")),
                "volume": _f(r.get("total_volume")),
                "globex_volume": _f(r.get("globex_volume")),
                "settle_or_close": _close_on(closes, _d(r["trade_date"])) if code == "GC" and _is_futures(foi) else None,
                "quality": "official",
            }
        )
    gc = [r for r in rows if str(r["product_code"]).upper() == "GC" and _is_futures(r.get("fut_or_opt"))]
    mech_days: set[str] = set()
    for e in events:
        kind, name = str(e.get("kind") or "").upper(), str(e.get("name") or "").lower()
        d = _d(e.get("event_date"))
        if d and (kind in ("COMEX_FND", "COMEX_LTD", "FND", "LTD") or "first notice" in name or "last trade" in name):
            for k in range(-3, 2):
                mech_days.add((d + timedelta(days=k)).isoformat())
    tape: list[dict[str, Any]] = []
    for i, r in enumerate(gc):
        d = _dd(r["trade_date"])
        prev_close = _close_on(closes, d - timedelta(days=1))
        close = _close_on(closes, d)
        doi = _f(r.get("oi_change"))
        if doi is None and i > 0:
            doi = _diff(_f(r.get("open_interest")), _f(gc[i - 1].get("open_interest")))
        dpp = _pct_change(close, prev_close) if close != prev_close else 0.0
        vol = _f(r.get("total_volume"))
        vols = [v for v in (_f(x.get("total_volume")) for x in gc[max(0, i - 20) : i]) if v]
        tape.append(
            {
                "trade_date": d.isoformat(),
                "dprice_pct": _r(dpp, 2),
                "doi": doi,
                "label": quadrant_label(dpp, doi),
                # a −0.74 % day with no OI yet is not "flat" (C-BEGINNER-24 / C-DATA-19): say why there is no word
                "label_note": "no OI yet (CME file lands T+1 ≈ 15:30 IST)" if doi is None and dpp is not None else None,
                "mechanical": d.isoformat() in mech_days,
                "volume": vol,
                # an average of one session is the session itself: '—' until 5 prior sessions exist (C-DATA-19)
                "volume_vs_20d": _r(vol / (sum(vols) / len(vols)), 2) if vol and len(vols) >= MIN_AVG_SESSIONS else None,
                "volume_avg_sessions": len(vols),
                "churn": _r(vol / _ff(r.get("open_interest")), 3) if vol and _f(r.get("open_interest")) else None,
            }
        )
    pc = None
    if rows:
        last_day = str(rows[-1]["trade_date"])[:10]
        og = {
            str(r.get("fut_or_opt") or "").upper(): _f(r.get("open_interest"))
            for r in rows
            if str(r["product_code"]).upper() == "OG" and str(r["trade_date"])[:10] == last_day
        }
        if og.get("C") and og.get("P") is not None:
            pc = _r(_ff(og.get("P")) / _ff(og.get("C")), 3)
    front_ym = (_dd(curve[0]["expiry"]).year, _dd(curve[0]["expiry"]).month) if curve and _d(curve[0].get("expiry")) else None
    fnd_info = _fnd_for_month([e for e in events if _d(e.get("event_date")) and _dd(e["event_date"]) >= today], prf or [], front_ym, today)
    roll = {
        "front": _mmy(curve[0]["expiry"]) if curve else None,
        "next": _mmy(curve[1]["expiry"]) if len(curve) > 1 else None,
        "front_oi": curve[0].get("open_interest") if curve else None,
        "next_oi": curve[1].get("open_interest") if len(curve) > 1 else None,
        "ratio": (
            _r(curve[0]["open_interest"] / curve[1]["open_interest"], 2)
            if len(curve) > 1 and curve[0].get("open_interest") and curve[1].get("open_interest")
            else None
        ),
        "days_to_tender_or_fnd": fnd_info["days_to_fnd"],
        "days_unit": "calendar days",
        "fnd_date": fnd_info["fnd_date"],
        "ltd_date": fnd_info["ltd_date"],
        "fnd_source": fnd_info["source"],
        "note": "per-month OI needs the CME bulletin (C7, owner action O-2); product OI meanwhile; FND/LTD of the front month "
        "from gold_events or the CME PRF",
    }
    return {
        "exchange": "COMEX",
        "rows": out_rows,
        "quadrant_tape": tape[-60:],
        "put_call_oi_ratio": pc,
        "roll": roll,
        "since": _since(out_rows, "trade_date"),
        "badge": BADGE_CONTEXT,
        "evidence": "context · weekly quadrant 1 of 12 cells (G-STUDY); daily untested until G-STUDY-2 — folklore meanwhile",
        "read": "OI down = positions closed; OI up = positions opened; T+1; mechanical on expiry / exercise days",
        "freshness": _freshness_of_rows(out_rows, "trade_date", 4.0, "CME FTP daily_volume (data-service gold_cme_daily_voi)"),
    }


def band_row_session(row: dict[str, Any]) -> date | None:
    """The session an ICICI-master curve row's SETTLE (the band midpoint) belongs to (wave 1d): the file of publish day D
    carries the OI at the close of S1 = previous_session(D) — the row's `trade_date`, a label that is RIGHT for the OI
    (data-service checked it against Breeze's closing OI) — and the band in force DURING S1, centred on the settlement of
    the session before S1. So: `gold_preopen.band_session` of the publish date when `release_at` names it, else the
    `session_date` data-service re-keyed (when it is before the trade_date), else previous_session(trade_date). Other
    sources keep their trade_date."""
    td = _d(row.get("trade_date"))
    if str(row.get("source") or "") != "icici_master_band":
        return td
    if _d(row.get("band_session")):          # data-service (wave 1d) names the raw band's session itself
        return _d(row.get("band_session"))
    rel = _dt(row.get("release_at"))
    if rel is not None:
        return gp.band_session((rel if rel.tzinfo else rel.replace(tzinfo=timezone.utc)).astimezone(IST).date())
    sd = _d(row.get("session_date"))
    if td and sd and sd < td:
        return sd
    return gp.previous_session(td) if td else None


def mcx_session_rows(rows: list[dict[str, Any]], vwaps: list[dict[str, Any]] | None = None, family: str | None = None
                     ) -> list[dict[str, Any]]:
    """One row per (session, symbol, expiry) from ICICI-master curve rows: the OI (and its change) of the row whose
    trade_date IS the session, the settle of the row whose band belongs to the session (`band_row_session`: the next
    file's), and — for the sessions no band covers yet — the last-30-min VWAP (`vwaps`: Breeze results with `session` and
    `expiry`; a VWAP wins over a band for its session). `settle_source` / `quality` say which. Pure."""
    oi: dict[tuple[str, str, str], dict[str, Any]] = {}
    st: dict[tuple[str, str, str], dict[str, Any]] = {}
    raw: dict[tuple[str, str, str], dict[str, Any]] = {}   # raw bands from re-keyed rows: only where no settle exists
    for r in rows:
        td, exp = _d(r.get("trade_date")), _d(r.get("expiry"))
        sym = str(r.get("symbol") or family or "").upper()
        if td is None or exp is None:
            continue
        k_oi = (td.isoformat(), sym, exp.isoformat())
        old = oi.get(k_oi)
        if old is None or str(r.get("first_seen_at") or "") >= str(old.get("first_seen_at") or ""):
            oi[k_oi] = r
        band = str(r.get("source") or "") == "icici_master_band"
        if band and ("settle_session" in r or "band_midpoint" in r):
            # data-service already re-keyed this row (wave 1d reads): `settle` IS the settlement of `settle_session` (its
            # VWAP30 or the next file's band, else null) and `band_midpoint` the raw band of `band_session` — never shifted
            # again here
            ss, sv = _d(r.get("settle_session")), _f(r.get("settle"))
            if ss is not None and sv is not None:
                st[(ss.isoformat(), sym, exp.isoformat())] = {
                    "settle": sv, "settle_source": r.get("settle_source") or "band_midpoint",
                    "quality": r.get("settle_quality") or "band_proxy", "from_file_of": None}
            bs, bm = _d(r.get("band_session")), _f(r.get("band_midpoint"))
            if bs is not None and bm is not None:
                raw.setdefault((bs.isoformat(), sym, exp.isoformat()), {
                    "settle": bm, "settle_source": "band_midpoint", "quality": "band_proxy", "from_file_of": td.isoformat()})
            continue
        s = band_row_session(r)
        px = _f(r.get("settle")) if r.get("settle") is not None else _f(r.get("close"))
        if s is not None and px is not None:
            st[(s.isoformat(), sym, exp.isoformat())] = {
                "settle": px, "settle_source": "band_midpoint" if band else str(r.get("source") or "stored"),
                "quality": "band_proxy" if band else (r.get("quality") or "proxy"), "from_file_of": td.isoformat()}
    for k, v in raw.items():
        st.setdefault(k, v)
    for v in vwaps or []:
        if v.get("status") == "ok" and v.get("value") and _d(v.get("session")) and _d(v.get("expiry")) and family:
            st[(_dd(v["session"]).isoformat(), family.upper(), _dd(v["expiry"]).isoformat())] = {
                "settle": _ff(v["value"]), "settle_source": "breeze_vwap30", "quality": "vwap30_proxy", "from_file_of": None}
    out: list[dict[str, Any]] = []
    for key in sorted(set(oi) | set(st)):
        k_sess, sym, k_exp = key
        o, p = oi.get(key) or {}, st.get(key) or {}
        out.append({
            "trade_date": k_sess, "session_date": k_sess, "symbol": sym, "expiry": k_exp,
            "open_interest": _f(o.get("open_interest")), "oi_change": _f(o.get("oi_change")),
            "sessions_spanned": o.get("sessions_spanned"), "volume": _f(o.get("volume")),
            "settle": p.get("settle"), "settle_source": p.get("settle_source"), "quality": p.get("quality") or "proxy",
            "source": o.get("source") or ("breeze_vwap30" if p.get("settle_source") == "breeze_vwap30" else "icici_master_band"),
            "settle_from_file_of": p.get("from_file_of"), "oi_from_file": bool(o),
        })
    return out


def vwap_sessions_needed(rows: list[dict[str, Any]], family: str, latest: date) -> tuple[list[date], date | None]:
    """The sessions after the newest band-covered session up to `latest` (usually one or two) and the front expiry of the
    newest file: the VWAP reads that complete the price tape (one Breeze call each, cached all night)."""
    fam = [r for r in rows if str(r.get("symbol") or "").upper() == family.upper() and _d(r.get("trade_date"))]
    if not fam:
        return [], None
    newest = max(_dd(r["trade_date"]) for r in fam)
    front = min((_dd(r["expiry"]) for r in fam if _dd(r["trade_date"]) == newest and _d(r.get("expiry"))
                 and _dd(r["expiry"]) >= latest), default=None)
    settled = [_d(r.get("settle_session")) for r in fam if r.get("settle") is not None and _d(r.get("settle_session"))]
    covered = max([s for s in (band_row_session(r) for r in fam) if s] + [s for s in settled if s], default=None)
    out: list[date] = []
    d = latest
    while covered is not None and d > covered and len(out) < 3:
        out.append(d)
        d = gp.previous_session(d)
    return sorted(out), front


def tender_state(tender_start: date, expiry: date, today: date) -> dict[str, Any]:
    """{days_to_tender, in_tender, tender_note}: never a negative count for a tender already running (5 Nov review:
    '−4 days to tender · tender from Sun 01 Nov')."""
    days = (tender_start - today).days
    running = days <= 0 <= (expiry - today).days
    note = (
        f"in tender since {tender_start:%a %d %b} ({-days} d)" if running and days < 0
        else f"tender opens today ({tender_start:%a %d %b})" if running
        else f"{days} days to tender (from {tender_start:%a %d %b})" if days > 0
        else None
    )
    return {"days_to_tender": max(days, 0) if running else days, "in_tender": running, "tender_note": note}


def build_positioning_mcx(
    curve_rows: list[dict[str, Any]], today: date, family: str = "GOLD", vwaps: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Daily MCX OI × price for one family from the ICICI-master curve rows re-keyed per session (`mcx_session_rows`, wave
    1d: the OI stays on its session, the band midpoint moves to the session it is the settlement of, the sessions no band
    covers yet take the last-30-min VWAP) — the 'Wed 04 Nov long unwinding −0.51 %' was Tuesday's band against Monday's on a
    +3.31 % COMEX Wednesday. Pure."""
    rows = [
        r
        for r in mcx_session_rows(curve_rows, vwaps, family)
        if str(r.get("symbol") or "").upper() == family.upper() and _d(r.get("trade_date")) and _d(r.get("expiry"))
    ]
    rows.sort(key=lambda r: (str(r["trade_date"])[:10], str(r["expiry"])[:10]))
    by_day: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_day.setdefault(str(r["trade_date"])[:10], []).append(r)
    days = sorted(by_day)
    out_rows: list[dict[str, Any]] = []
    tape: list[dict[str, Any]] = []
    prev_oi_by_exp: dict[str, float] = {}
    prev_front: tuple[float, date, str] | None = None   # (settle, session, expiry) of the last session with a front settle
    prev_oi_day: date | None = None                # the last session that had OI (the delta's own span)
    for d in days:
        day_rows = by_day[d]
        total_doi = 0.0
        have_doi = False
        has_oi = any(r.get("open_interest") is not None for r in day_rows)
        # sessions the OI delta spans (1 = one day): data-service's own count (full closures subtracted) when the row
        # carries it, else the sessions between this OI session and the previous one
        stored_span = next((int(_ff(r["sessions_spanned"])) for r in day_rows if _f(r.get("sessions_spanned"))), None)
        span = stored_span if stored_span else (sessions_between(prev_oi_day, _dd(d)) if prev_oi_day and has_oi else None)
        for r in day_rows:
            exp = str(r["expiry"])[:10]
            oi = _f(r.get("open_interest"))
            doi = _f(r.get("oi_change")) if oi is not None else None
            if doi is None and oi is not None and exp in prev_oi_by_exp:
                doi = oi - prev_oi_by_exp[exp]
            if doi is not None:
                total_doi += doi
                have_doi = True
            if oi is not None:
                prev_oi_by_exp[exp] = oi
            out_rows.append(
                {
                    "trade_date": d,
                    "symbol_or_product": family.upper(),
                    "expiry": exp,
                    "open_interest": oi,
                    "oi_change": doi,
                    "sessions_spanned": span if doi is not None else None,
                    "volume": _f(r.get("volume")),
                    "settle_or_close": _f(r.get("settle")),
                    "settle_source": r.get("settle_source"),
                    "quality": r.get("quality") or "proxy",
                    "source": r.get("source"),
                    "session_date": d,
                }
            )
        live = [r for r in day_rows if _dd(r["expiry"]) >= _dd(d)]
        front = live[0] if live else None                      # the nearest expiry; its settle may be unknown that session
        settle = _f(front.get("settle")) if front else None
        same_contract = bool(front and prev_front and prev_front[2] == str(front["expiry"])[:10])   # never across a roll
        dpp = _pct_change(settle, prev_front[0]) if settle is not None and prev_front and same_contract else None
        price_span = sessions_between(prev_front[1], _dd(d)) if dpp is not None and prev_front else None
        # the quadrant word needs the price and the OI over the SAME span (a band session and an OI session can differ)
        same_span = dpp is not None and have_doi and (price_span or 1) == (span or 1)
        near_expiry = any(abs((_dd(r["expiry"]) - _dd(d)).days) <= 3 for r in day_rows)
        tape_span = span if have_doi else price_span
        multi = bool(tape_span and tape_span > 1 and (dpp is not None or have_doi))
        tape.append(
            {
                "trade_date": d,
                "dprice_pct": _r(dpp, 2),
                "doi": total_doi if have_doi else None,
                "label": quadrant_label(dpp, total_doi) if same_span else None,
                "mechanical": near_expiry,
                # a delta that spans more than one session is said so, and greyed like the mechanical flag (C-TRADER-18)
                "sessions_spanned": tape_span if (dpp is not None or have_doi) else None,
                "multi_session": multi,
                "span_note": f"over {tape_span} sessions (master skipped {tape_span - 1})" if multi and tape_span else None,
                "price_source": front.get("settle_source") if front else None,
                "price_only": dpp is not None and not have_doi,
                "note": (
                    "Δprice from the last-30-min VWAP (Breeze, proxy); ΔOI arrives with the next ICICI master"
                    if front and front.get("settle_source") == "breeze_vwap30" and not have_doi
                    else ("price and OI deltas span different sessions: no quadrant word" if dpp is not None and have_doi
                          and not same_span else None)
                ),
            }
        )
        if settle is not None and front:
            prev_front = (settle, _dd(d), str(front["expiry"])[:10])
        if has_oi:
            prev_oi_day = _dd(d)
    oi_days = [d for d in days if any(r.get("open_interest") is not None for r in by_day[d])]
    last_day = by_day[oi_days[-1]] if oi_days else []
    live = sorted((r for r in last_day if _dd(r["expiry"]) >= today), key=lambda r: str(r["expiry"]))
    front, nxt = (live[0] if live else None), (live[1] if len(live) > 1 else None)
    tender_start = mcx_tender_start(_dd(front["expiry"])) if front else None
    ts = tender_state(tender_start, _dd(front["expiry"]), today) if front and tender_start else {}
    roll = {
        "front": _mmy(front["expiry"]) if front else None,
        "next": _mmy(nxt["expiry"]) if nxt else None,
        "front_oi": _f(front.get("open_interest")) if front else None,
        "next_oi": _f(nxt.get("open_interest")) if nxt else None,
        "ratio": (
            _r(_ff(front["open_interest"]) / _ff(nxt["open_interest"]), 2)
            if front and nxt and _f(front.get("open_interest")) and _f(nxt.get("open_interest"))
            else None
        ),
        "days_to_tender_or_fnd": ts.get("days_to_tender"),
        "in_tender": ts.get("in_tender"),
        "tender_note": ts.get("tender_note"),
        "days_unit": "calendar days",
        "tender_start": tender_start.isoformat() if tender_start else None,
        "expiry": str(front["expiry"])[:10] if front else None,
        "note": "tender period opens on the 1st of the expiry month (contract spec; the MCX circular is the legal source); "
        "the count is calendar days",
    }
    return {
        "exchange": "MCX",
        "family": family.upper(),
        "rows": out_rows,
        "quadrant_tape": tape[-60:],
        "roll": roll,
        "since": days[0] if days else None,
        "badge": BADGE_ARITH,
        "read": "proxy settlement (ICICI band midpoint, labelled with the session it belongs to: two before the file) and OI "
        "in lots from the daily master, plus the latest session's last-30-min VWAP (Breeze) when it is newer; no volume "
        "until F3 (O-8)",
        "freshness": _freshness_of_rows(out_rows, "trade_date", 4.0, "ICICI MCX master (data-service gold_curve, proxy)"),
    }


@router.get("/positioning/daily")
async def gold_positioning_daily(
    exchange: str = Query("COMEX", pattern="^(COMEX|MCX|comex|mcx)$"),
    days: int = Query(60, ge=5, le=400),
    family: str = Query("GOLD"),
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Daily OI × price: COMEX product OI (CME FTP, T+1) or MCX OI per contract (ICICI master, 07:35) with the opened /
    closed read, the quadrant tape (roll days flagged mechanical) and the roll ratio."""
    reads = Reads()
    now = _now_ist()
    start = (now.date() - timedelta(days=days + 10)).isoformat()
    if exchange.upper() == "COMEX":
        voi_t, bars_t, curve_t, events_t, prf_t = await _gather(
            reads.get("/db/gold/cme/voi", **{"from": start}, products=",".join(CME_GOLD_PRODUCTS)),
            reads.get("/db/gold/bars", symbol=GC_FRONT, interval="1d", **{"from": start}),
            reads.get("/db/gold/curve", exchange="COMEX"),
            reads.get("/db/gold/events", **{"from": now.date().isoformat()}, to=(now.date() + timedelta(days=120)).isoformat()),
            reads.get("/db/gold/cme/prf", symbol="GC"),
        )
        prf = prf_rows(prf_t) if not isinstance(prf_t, Exception) else []
        payload = build_positioning_comex(
            _rows(voi_t) if not isinstance(voi_t, Exception) else [],
            _closes_from_bars(bars_t) if not isinstance(bars_t, Exception) else [],
            curve_points(curve_t, now.date()) if not isinstance(curve_t, Exception) else [],
            (_rows(events_t) if not isinstance(events_t, Exception) else []) + prf_events(prf, now.date()),
            now.date(),
            prf,
        )
    else:
        code = family.upper()
        if code not in mcxr.contract_specs():
            fail(422, "invalid", f"Unknown MCX contract '{family}'")
        curve_t = await reads.get("/db/gold/curve/history", exchange="MCX", symbol=code, days=days + 10)
        rows = _rows(curve_t)
        # the sessions no band covers yet (usually the latest one or two) take the front's last-30-min VWAP: one Breeze
        # call per session, cached all night, shared with the fair block
        need, front_exp = vwap_sessions_needed(rows, code, gp.latest_completed_session(now))
        vw: list[dict[str, Any]] = []
        if front_exp is not None and need:
            # the ONE path (round-2 checker): data-service's stored VWAP30 for every needed session in one read, then Breeze
            await mcxr.fill_stored_vwaps([(code, front_exp, sess) for sess in need])
            for sess in need:
                v = await mcxr.session_vwap_any(code, front_exp, sess)
                vw.append({**v, "session": sess.isoformat(), "expiry": front_exp.isoformat()})
        payload = build_positioning_mcx(rows, now.date(), code, vw)
    payload["as_of"] = now.isoformat(timespec="seconds")
    payload["store_errors"] = reads.errors or None
    reads.headers(response)
    return payload


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /curve · GET /contracts (CONTRACTS)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _basis_block(fair: dict[str, Any], carry_pct: float | None, basis_pts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The CONTRACTS footer's basis: the SAME settlement-clock number the HEALTH gauge and the PHYSICAL ladder print
    (`settle_basis`), its clock labelled; the live-clock pair beside it when a quote exists, never divided across clocks."""
    sb = settle_basis(fair, basis_pts or [])
    lb = live_basis(fair)
    basis = sb["value"] if sb["value"] is not None else fair.get("basis_pct")
    return {
        "mcx_front_inr": fair.get("settlement"),
        "mcx_front_session": fair.get("settlement_session"),
        "mcx_front_session_label": fair.get("settlement_session_label"),
        "mcx_front_quality": fair.get("settlement_quality"),
        "mcx_front_source": fair.get("settlement_source"),
        "settlement_check": fair.get("settlement_check"),
        "band_midpoint": fair.get("band_midpoint"),
        "band_session": fair.get("band_session"),
        "purity": fair.get("purity"),
        "basis_reference": sb.get("basis_reference") or fair.get("basis_reference"),
        "duty_paid_landed_purity_inr": fair.get("duty_paid_landed_purity"),
        "landed_inr": fair.get("landed"),
        "duty_pct": fair.get("duty_pct"),
        "duty_effective": fair.get("duty_effective"),
        "duty_notification": gp.DUTY_NOTIFICATION,
        "duty_note": fair.get("duty_note"),
        "duty_paid_landed_inr": fair.get("duty_paid_landed"),
        "basis_pct": basis,
        "basis_clock": "settlement",
        "basis_label": sb["label"] or "settle ÷ that session's duty-paid landed − 1",
        "basis_date": sb["date"] or fair.get("settlement_session"),
        "basis_source": sb["source"],
        "live_basis_pct": lb["value"] if lb else None,
        "live_basis_label": lb["label"] if lb else None,
        "mcx_live": lb["mcx_live"] if lb else None,
        "carry_pct": carry_pct,
        "basis_carry_adj_pct": _r(basis - carry_pct, 2) if basis is not None and carry_pct is not None else None,
        "usdinr": (fair.get("usdinr") or {}).get("price"),
        "usdinr_source": "Yahoo INR=X (cached fetcher)",
        "ts": _iso_any((fair.get("comex") or {}).get("as_of")),
        "ts_note": "landed / duty-paid are now; the basis is at the settlement clock (basis_date)",
        "badge": BADGE_ARITH,
    }


@router.get("/curve")
async def gold_curve(
    exchange: str = Query("COMEX", pattern="^(COMEX|MCX|comex|mcx)$"),
    date_: str | None = Query(None, alias="date"),
    family: str = Query("GOLD"),
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Term structure for one exchange: points with spread vs front and annualised carry (M31), the ghost curve a week ago,
    the India basis block (MCX) and the stored basis / premium history."""
    reads = Reads()
    now = _now_ist()
    ex = exchange.upper()
    day = _date_arg(date_, "date") or now.date()
    ghost_day = day - timedelta(days=7)
    cur_t, ghost_t, hist_t, prf_t = await _gather(
        reads.get("/db/gold/curve", exchange=ex, date=day.isoformat() if date_ else None),
        reads.get("/db/gold/curve", exchange=ex, date=ghost_day.isoformat()),
        fetch_series(reads, ["MCX_BASIS_PCT", "INDIA_PREMIUM_PCT", "COMEX_CARRY_ANN_PCT"], days=400),
        reads.get("/db/gold/cme/prf", symbol="GC") if ex == "COMEX" else asyncio.sleep(0, result=None),
    )
    rows = _rows(cur_t) if not isinstance(cur_t, Exception) else []
    if isinstance(cur_t, dict) and isinstance(cur_t.get("ghost_1w"), list) and cur_t["ghost_1w"]:
        ghost_t = {"rows": cur_t["ghost_1w"]}
    if ex == "MCX":
        # every band row carries the session it really belongs to (two before the file; wave 1d) — the chain is ONE session
        # the chain is ONE session: the raw band (data-service's re-keyed rows carry it as `band_midpoint`), never a mix of
        # re-keyed settles (VWAP for some expiries, nothing for others)
        rows = [
            {**r, "settle": r["band_midpoint"]} if r.get("band_midpoint") is not None else r
            for r in rows
            if str(r.get("symbol") or "").upper() == family.upper()
        ]
    pts = curve_points(rows, day)
    if ex == "MCX":
        # D4: every chain settle names the session it belongs to and its source (the band of its REAL session, never the
        # request date) — per point, so a mixed store can never hide a second session under the chain's one label
        sess_of = {str(r.get("expiry") or "")[:10]: band_row_session(r) for r in rows}
        for p in pts:
            ps = sess_of.get(p["expiry"])
            p["settle_source"] = "band_midpoint" if p.get("settle_or_last") is not None else None
            p["settle_quality"] = "band_proxy" if p.get("settle_or_last") is not None else None
            p["band_session"] = ps.isoformat() if ps else None
            p["settle_session"] = ps.isoformat() if ps and p.get("settle_or_last") is not None else None
            p["settle_session_label"] = gp.session_label(ps) if ps and p.get("settle_or_last") is not None else None
    ghost = curve_points(
        [
            r
            for r in (_rows(ghost_t) if not isinstance(ghost_t, Exception) else [])
            if ex != "MCX" or str(r.get("symbol") or "").upper() == family.upper()
        ],
        ghost_day,
    )
    hist = hist_t if isinstance(hist_t, dict) else {}
    basis = None
    if ex == "MCX":
        try:
            fair = await fair_block(family.upper(), None)
            carry = pts[0].get("annualised_carry_pct") if pts else None
            carry = pts[1].get("annualised_carry_pct") if len(pts) > 1 else carry
            basis = _basis_block(fair, carry, hist.get("MCX_BASIS_PCT") or [])
        except Exception as exc:  # noqa: BLE001
            reads.errors["basis"] = type(exc).__name__
    prf = prf_rows(prf_t) if ex == "COMEX" and prf_t is not None and not isinstance(prf_t, Exception) else []
    for p in pts:
        flags = []
        if p.get("quality") == "proxy":
            flags.append("PROXY")
        if str(p.get("source") or "").startswith("yahoo"):
            flags.append("LAST TRADE")
        if p.get("days_to_expiry") is not None and 0 <= p["days_to_expiry"] <= 7:
            flags.append("EXPIRY WEEK")
        p["flags"] = flags
        if ex == "COMEX":
            # a long must leave by FIRST NOTICE, not the last trade (C-TRADER-24): each month's FND / LTD from the PRF
            e = _d(p.get("expiry"))
            row = prf_row_for_month(prf, (e.year, e.month)) if e else None
            fnd, ltd = _d((row or {}).get("first_notice")), _d((row or {}).get("last_trd"))
            p["first_notice"] = fnd.isoformat() if fnd else None
            p["days_to_fnd"] = (fnd - day).days if fnd else None
            p["last_trade"] = ltd.isoformat() if ltd else None
            p["days_to_ltd"] = (ltd - day).days if ltd else None
    history = (
        [
            {
                "trade_date": a["report_date"],
                "basis_pct": a["value"],
                "premium_pct": _close_on(hist.get("INDIA_PREMIUM_PCT") or [], _d(a["report_date"])),
            }
            for a in (hist.get("MCX_BASIS_PCT") or [])
        ]
        if ex == "MCX"
        else [{"trade_date": a["report_date"], "carry_ann_pct": a["value"]} for a in (hist.get("COMEX_CARRY_ANN_PCT") or [])]
    )
    # the chain's settles are ONE session — the one its band belongs to (wave 1d), the session BEFORE the OI's trade_date
    chain_session = band_row_session(rows[0]) if ex == "MCX" and rows else None
    oi_session = _d(rows[0].get("trade_date")) if ex == "MCX" and rows else None
    price_label = (
        "last trade (Yahoo per-month), not settlement — bulletin settlements wait on O-2"
        if ex == "COMEX" and any(str(p.get("source") or "").startswith("yahoo") for p in pts)
        else (
            f"ICICI band-midpoint settlement of the {gp.session_label(chain_session)} (proxy; the band of a file is the "
            "settlement two sessions before it) until the official bhavcopy (O-8); the basis below uses the latest "
            "session's last-30-min VWAP when it is known"
            if chain_session
            else "ICICI band-midpoint settlement (proxy) until the official bhavcopy (O-8)"
        )
        if ex == "MCX"
        else None
    )
    payload = {
        "exchange": ex,
        "family": family.upper() if ex == "MCX" else None,
        "date": day.isoformat(),
        "points": pts,
        "ghost_1w": ghost,
        "ghost_date": ghost_day.isoformat() if ghost else None,
        "basis": basis,
        "history": history,
        "price_label": price_label,
        "chain_session": chain_session.isoformat() if chain_session else None,
        "chain_session_label": gp.session_label(chain_session) if chain_session else None,
        "oi_session": oi_session.isoformat() if oi_session else None,
        "since": _since(rows, "trade_date"),
        "badge": BADGE_ARITH,
        "freshness": freshness(pts[0].get("trade_date") if pts else None, 4.0, f"data-service gold_curve ({ex})"),
        "store_errors": reads.errors or None,
    }
    reads.headers(response)
    return payload


def _margin_rows(payload: Any) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in _rows(payload):
        key = (str(r.get("symbol") or "").upper(), str(r.get("expiry") or "")[:10])
        if key not in out or str(r.get("trade_date") or "") > str(out[key].get("trade_date") or ""):
            out[key] = r
    return out


async def contract_vwaps(
    family: dict[str, list[dict[str, Any]]] | None, today: date, latest: date
) -> dict[tuple[str, str], dict[str, Any]]:
    """{(family, expiry) → cached VWAP30 result} for the liquid expiries of every family (OI > 0, at most
    CONTRACTS_VWAP_PER_FAMILY by OI): data-service's stored values first (ONE read for all of them), the ones still unknown
    queued on ONE background thread (never waited for here)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    keys: list[tuple[str, date]] = []
    for code, rows in (family or {}).items():
        live = sorted((r for r in rows if r["expiry"] >= today and (r.get("open_interest") or 0) > 0),
                      key=lambda r: -(r.get("open_interest") or 0))[:CONTRACTS_VWAP_PER_FAMILY]
        keys.extend((code, r["expiry"]) for r in live)
    if keys:
        await mcxr.fill_stored_vwaps([(code, exp, latest) for code, exp in keys])
    queue: list[tuple[str, date, date]] = []
    for code, exp in keys:
        stock = mcxr.BREEZE_CODE.get(code, code)
        hit = gp.session_vwap_cached(stock, exp, latest)
        if hit is None:
            queue.append((stock, exp, latest))
        else:
            out[(code, exp.isoformat())] = hit
    if queue:
        gp.prefetch_session_vwaps(queue)
    return out


async def mcx_margin_row(code: str, expiry: date | None) -> dict[str, Any] | None:
    """The stored MCX margin row (Zerodha NRML mirror) of (family, expiry) — the row the CONTRACTS card prints, read through
    the same store cache; the MCXG paper ticket asks for it (one source). None when absent or the store is down."""
    if expiry is None:
        return None
    payload = await Reads().get("/db/gold/margins", exchange="MCX")
    if isinstance(payload, Exception):
        return None
    return _margin_rows(payload).get((code.upper(), expiry.isoformat()))


def _mcx_oi_changes(payload: Any) -> dict[tuple[str, str], float]:
    """{(family, expiry) → oi_change} from the latest stored MCX curve rows (B1 `gold_curve`, exchange=MCX)."""
    out: dict[tuple[str, str], float] = {}
    for r in _rows(payload):
        v = _f(r.get("oi_change"))
        if v is not None and r.get("symbol") and _d(r.get("expiry")):
            out[(str(r["symbol"]).upper(), _dd(r["expiry"]).isoformat())] = v
    return out


CONTRACTS_VWAP_PER_FAMILY = 3  # the liquid expiries per family whose last-30-min VWAP is read (one Breeze call each, all night)
# MCX's carry over COMEX's: a fair MCX carry ≈ COMEX's own annual carry + the INR − USD rate gap (≈ 2.6 pp, a dated estimate)
INR_USD_RATE_GAP_PCT = 2.6


def contract_settles(
    code: str, rows: list[dict[str, Any]], published: date | None, vwaps: dict[tuple[str, str], dict[str, Any]] | None,
    latest: date | None,
) -> list[dict[str, Any]]:
    """Each observed expiry's settle for the CONTRACTS card (wave 1d): the latest session's last-30-min VWAP when it is known
    for that expiry, else the band midpoint labelled with its REAL session (`gold_preopen.band_session`). Every row names
    its `settle_source` / `settle_session`; carry is only ever taken between rows of ONE session. Pure."""
    b_sess = gp.band_session(published) if published else None
    out: list[dict[str, Any]] = []
    sess: date | None
    for r in rows:
        v = (vwaps or {}).get((code, r["expiry"].isoformat())) or {}
        if v.get("status") == "ok" and v.get("value") and latest:
            settle, src, sess, q = v["value"], "breeze_vwap30", latest, "vwap30_proxy"
        else:
            settle, src, sess, q = r["settlement"], "band_midpoint", b_sess, "band_proxy"
        out.append({**r, "settle": settle, "settle_source": src, "settle_session": sess, "settle_quality": q})
    return out


def build_contracts(
    family_rows: dict[str, list[dict[str, Any]]] | None,
    published: date | None,
    margins: dict[tuple[str, str], dict[str, Any]],
    comex_curve: list[dict[str, Any]],
    today: date,
    mcx_oi_changes: dict[tuple[str, str], float] | None = None,
    vwaps: dict[tuple[str, str], dict[str, Any]] | None = None,
    latest: date | None = None,
) -> dict[str, Any]:
    """The selector cards (c.selector): one per MCX family (GOLDTEN included) with expiries (observed from the master, computed
    fallback), economics from shared/mcx_specs and the Zerodha NRML mirror when stored (`mcx.card_margin`, the SAME rule the
    MCXG paper ticket uses). Settles per `contract_settles` (VWAP30 of the latest session, else the band of its real
    session). Pure: unit-tested with the fixture master."""
    families: list[dict[str, Any]] = []
    for code, spec in mcxr.contract_specs().items():
        observed = [r for r in (family_rows or {}).get(code, []) if r["expiry"] >= today]
        computed = mcxr.active_expiries(code, today, count=3)
        src_rows = [
            {
                "expiry": r["expiry"],
                "source": "observed",
                "settle": r["settle"],
                "settle_source": r["settle_source"],
                "settle_session": r["settle_session"],
                "settle_quality": r["settle_quality"],
                "band_mid": r["settlement"],
                "band_lo": r["band_low"],
                "band_hi": r["band_high"],
                "oi": r["open_interest"],
            }
            for r in contract_settles(code, observed, published, vwaps, latest)
        ] or [
            {"expiry": e, "source": "computed", "settle": None, "settle_source": None, "settle_session": None,
             "settle_quality": None, "band_mid": None, "band_lo": None, "band_hi": None, "oi": None}
            for e in computed
        ]
        front_row = next((r for r in src_rows if r["settle"]), None)
        front_settle = front_row["settle"] if front_row else None
        expiries: list[dict[str, Any]] = []
        for i, r in enumerate(src_rows[:6]):
            m = margins.get((code, r["expiry"].isoformat()))
            cm = mcxr.card_margin(spec, r["settle"], m) if (m or r["settle"]) else None
            inr = (cm or {}).get("margin_inr")
            pct = (cm or {}).get("margin_pct")
            # ONE carry convention on the page (C-DATA-16): annualised vs the FRONT, exactly `/curve.annualised_carry_pct`;
            # the front row itself carries none; never across two sessions (a VWAP front vs a band back month is a day's
            # move, not carry — wave 1d)
            same_session = bool(front_row and r["settle_session"] == front_row["settle_session"])
            carry = (
                annualised_carry_pct(front_row["settle"], r["settle"], (r["expiry"] - front_row["expiry"]).days)
                if front_row and r is not front_row and r["settle"] and same_session
                and (r["expiry"] - front_row["expiry"]).days > 0
                else None
            )
            tender = mcx_tender_start(r["expiry"])
            tst = tender_state(tender, r["expiry"], today)
            matched, substitute = comex_liquid_symbol(r["expiry"])
            expiries.append(
                {
                    "expiry": r["expiry"].isoformat(),
                    "source": r["source"],
                    "settle": r["settle"],
                    "settle_quality": r["settle_quality"],
                    "settle_source": r["settle_source"],
                    "settle_session": r["settle_session"].isoformat() if r["settle_session"] else None,
                    "settle_session_label": gp.session_label(r["settle_session"]) if r["settle_session"] else None,
                    "band_midpoint": r["band_mid"],
                    "band_lo": r["band_lo"],
                    "band_hi": r["band_hi"],
                    "oi": r["oi"],
                    "oi_change": (mcx_oi_changes or {}).get((code, r["expiry"].isoformat())),
                    "margin_inr": inr,
                    "margin_pct": pct,
                    "margin_source": (cm or {}).get("margin_source"),
                    "margin_date": (cm or {}).get("margin_date"),
                    "margin_ref_price": (cm or {}).get("margin_ref_price"),
                    "carry_pct": carry,
                    "carry_convention": "annualised vs the front expiry (as /curve), one session only",
                    "carry_note": (
                        None
                        if carry is not None or r is front_row or not r["settle"] or same_session
                        else "front and this expiry settle on different sessions: no carry printed"
                    ),
                    "comex_matched": matched,
                    "comex_matched_calendar": gp.comex_symbol(r["expiry"]),
                    "comex_matched_note": "nearest liquid COMEX month" if substitute else None,
                    "tender_start": tender.isoformat(),
                    "days_to_tender": tst["days_to_tender"],
                    "in_tender": tst["in_tender"],
                    "tender_note": tst["tender_note"],
                    "days_unit": "calendar days",
                    "days_to_expiry": (r["expiry"] - today).days,
                }
            )
        price = front_settle or 0.0
        costs = mcxr.spec_costs(code, price, 1) if price else None
        d = spec.as_dict()
        families.append(
            {
                "code": code,
                "name": spec.name,
                "breeze_code": mcxr.BREEZE_CODE.get(code),
                "lot": d["lot"],
                "lot_grams": spec.lot_grams,
                "quote_unit": d["quotation"],
                "purity": str(gp.fineness_of(code)),   # the basis purity (D1): 995 GOLD / GOLDM, 999 TEN / PETAL / GUINEA
                "basis_reference": gp.basis_reference(code),
                # the price the 1 % move, the notional and the round trip are taken at: the front's settle, named
                "price_basis": (
                    f"{front_row['settle_session'] and gp.session_label(front_row['settle_session'])} "
                    f"({str(front_row['settle_quality']).replace('_', ' ')})"
                    if front_row
                    else None
                ),
                "expiry_rule": d["expiry_rule"],
                "cycle": d["cycle"],
                "expiries": expiries,
                "tick_rupees": spec.tick_rupees,
                "tick_value": spec.tick_value,
                "multiplier": spec.multiplier,
                "round_trip": (
                    {
                        "legs": {"buy": costs["buy"]["total"], "sell": costs["sell"]["total"]},
                        "total": costs["total"],
                        "pct": costs["pct_of_notional"],
                        "breakeven_ticks": costs["breakeven_ticks"],
                        "price": price,
                        "assumptions": costs["assumptions"],
                    }
                    if costs
                    else None
                ),
                "one_pct_move_inr": round(price * spec.multiplier / 100, 0) if price else None,
                "notional_inr": round(price * spec.multiplier, 0) if price else None,
                "hedge_ratio_oz": round(spec.lot_grams / GRAMS_PER_TROY_OZ, 3),
                "delivery_unit": spec.delivery_unit,
                "tender_cutoff_note": "ICICI tender cut-off not in the repo — owner action O-9",
                "options": {
                    "available": code in ("GOLD", "GOLDM"),
                    "expiries": [],
                    "strike_step": None,
                    "note": "an exercised option becomes the future; option expiries precede the future they settle into",
                },
                "notes": spec.notes,
                "badge": BADGE_ARITH,
            }
        )
    matched_by_family = {f["code"]: (f["expiries"][0]["comex_matched"] if f["expiries"] else None) for f in families}
    comex_front = comex_curve[0] if comex_curve else None
    return {
        "exchange": "MCX",
        "families": families,
        "comex_matched_by_family": matched_by_family,
        "comex_front": {
            "expiry": comex_front["expiry"],
            "symbol": comex_front.get("symbol"),
            "price": comex_front.get("settle_or_last"),
            "source": comex_front.get("source"),
        }
        if comex_front
        else None,
        "diff_keys": [
            "lot",
            "tick_value",
            "margin_pct",
            "round_trip.pct",
            "oi",
            "purity",
            "expiry_rule",
            "hedge_ratio_oz",
            "one_pct_move_inr",
        ],
        "other_exchanges": [
            {"exchange": "NSE", "available": False, "reason": "no gold futures listed; GOLDBEES is an ETF (CMDT/WEI)"},
            {"exchange": "BSE", "available": False, "reason": "no gold futures listed"},
        ],
        "master": {
            "available": bool(family_rows),
            "published": published.isoformat() if published else None,
            # the band midpoints are the settlement of THIS session (two before the file; wave 1d), the band itself MCX's
            # price band of `band_applies_to`
            "session": gp.band_session(published).isoformat() if published else None,
            "session_label": gp.session_label(gp.band_session(published)) if published else None,
            "band_applies_to": gp.band_applies_to(published).isoformat() if published else None,
        },
        "latest_session": latest.isoformat() if latest else None,
        "settle_note": "settle = the latest session's last-30-min VWAP (Breeze 1-minute bars, proxy) where read, else the ICICI "
        "band midpoint of its real session (proxy); carry only within one session",
        "carry_fair_note": (
            "MCX carry runs above COMEX's: a fair MCX carry ≈ COMEX's own annual carry + the INR − USD interest-rate gap "
            f"(≈ {INR_USD_RATE_GAP_PCT:g} pp, an estimate); the rest is local demand or the cost of MCX margin — arithmetic, "
            "not a free return"
        ),
        "margin_note": "NRML margin from the Zerodha mirror when stored (dated), else the indicative constant; MCX revises daily; "
        "the MCXG paper ticket uses the same rule (mcx.card_margin)",
        "badge": BADGE_ARITH,
    }


MARGIN_MIN_USD = 1000.0  # a COMEX GC outright margin is ~$20k: rows below this are spreads / stubs, never 'margin history'
SETTL_METHOD = {"P": "physical delivery", "C": "cash settled", "F": "financially settled"}
UOM_LABEL = {"oz_tr": "troy oz", "OZT": "troy oz", "oz": "oz"}


def comex_spec_card(
    prf: list[dict[str, Any]], margins_rows: list[dict[str, Any]], matched_symbol: str | None, today: date, symbol_root: str = "GC"
) -> dict[str, Any] | None:
    """DES-style card of the MATCHED COMEX contract month (C-TRADER-13 / C-DATA-8 / C-BEGINNER-4: the old card took the
    first live PRF row — the Nov serial, FND five days past — under the DEC title): the PRF row whose `mmy` equals the
    matched month (`GCZ26.CMX` → 202612), else the first row whose last trade is ahead; tick = MinPxIncr × the display
    factor (`tick_incr_reg`, 0.1 for GC → $0.10 = $10); margin history = the stored margin rows of THAT month's expiry, one
    per trade date, rows under $1,000 dropped; codes spelled out (`P` → physical delivery, `oz_tr` → troy oz). Pure."""
    rows = prf_rows(prf, symbol_root)
    if not rows:
        return None
    ym = symbol_expiry_month(matched_symbol) if matched_symbol else None
    r = prf_row_for_month(rows, ym)
    picked_by = "matched month"
    if r is None:
        r = next((x for x in rows if _d(x.get("last_trd")) and _dd(x["last_trd"]) >= today), rows[-1])
        picked_by = "first month still trading (matched month not in the PRF)"
    mat = str(r.get("mat_date") or "")[:10]
    margins = sorted(
        (
            m
            for m in margins_rows
            if str(m.get("symbol") or "").upper() == symbol_root
            and str(m.get("expiry") or "")[:10] == mat
            and (_f(m.get("margin_ccy")) or 0) >= MARGIN_MIN_USD
        ),
        key=lambda m: str(m.get("trade_date") or ""),
    )
    by_day: dict[str, dict[str, Any]] = {}
    for m in margins:
        by_day[str(m.get("trade_date"))[:10]] = m  # one row per trade date (the last stored wins)
    hist = [{"trade_date": d, "margin_usd": _f(m.get("margin_ccy"))} for d, m in sorted(by_day.items())][-60:]
    init = _f(r.get("init_margin"))
    if init is not None and init < MARGIN_MIN_USD:
        init = None  # a $25 stub is not an outright margin
    ref = _f((margins[-1] if margins else {}).get("ref_price"))
    mult = _f(r.get("multiplier")) or 100.0
    disp = _f(r.get("tick_incr_reg")) or _f(r.get("display_factor")) or 1.0
    tick = (_f(r.get("min_px_incr")) or 0) * disp
    fnd, ltd = _d(r.get("first_notice")), _d(r.get("last_trd"))
    return {
        "symbol": symbol_root,
        "mmy": r.get("mmy"),
        "month": _mmy(r.get("mat_date")),
        "yahoo_symbol": matched_symbol if picked_by == "matched month" else None,
        "picked_by": picked_by,
        "description": r.get("description"),
        "sec_type": r.get("sec_type"),
        "uom": r.get("uom"),
        "uom_label": UOM_LABEL.get(str(r.get("uom") or ""), str(r.get("uom") or "")),
        "uom_qty": _f(r.get("uom_qty")),
        "multiplier": mult,
        "min_px_incr": _f(r.get("min_px_incr")),
        "display_factor": disp,
        "tick_usd": _r(tick, 4),
        "tick_value_usd": _r(tick * mult, 2),
        "settl_method": r.get("settl_method"),
        "settl_method_label": SETTL_METHOD.get(str(r.get("settl_method") or "").upper(), str(r.get("settl_method") or "")),
        "init_margin_usd": init,
        "margin_pct_of_notional": _r(init / (ref * mult) * 100, 2) if init and ref else None,
        "margin_date": str(r.get("biz_date") or "")[:10] or None,
        "ref_price": ref,
        "first_notice": fnd.isoformat() if fnd else None,
        "days_to_first_notice": (fnd - today).days if fnd else None,
        "last_notice": str(r.get("last_notice") or "")[:10] or None,
        "last_trade": ltd.isoformat() if ltd else None,
        "days_to_last_trade": (ltd - today).days if ltd else None,
        "first_trade": str(r.get("first_trd") or "")[:10] or None,
        "mat_date": mat or None,
        "elig_block": r.get("elig_block"),
        "elig_efp": r.get("elig_efp"),
        "margin_history": hist,
        "margin_history_dates": len(hist),
        "margin_history_note": f"{symbol_root} {mat} outright, one row per trade date, rows under ${MARGIN_MIN_USD:,.0f} dropped",
        # the card's own source and date (re-review: its chip read 'LIVE · ICICI MCX SECURIT…' for a CME-PRF card)
        "freshness": freshness(str(r.get("biz_date") or "")[:10] or None, 4.0, "CME PRF (FTP)"),
        "badge": BADGE_ARITH,
    }


async def _comex_spec(reads: Reads, matched_symbol: str | None, symbol_root: str = "GC") -> dict[str, Any] | None:
    """`comex_spec_card` from the store; None when gold_cme_prf is not readable."""
    prf_t, mg_t = await _gather(reads.get("/db/gold/cme/prf", symbol=symbol_root), reads.get("/db/gold/margins", exchange="COMEX"))
    return comex_spec_card(
        _rows(prf_t) if not isinstance(prf_t, Exception) else [],
        _rows(mg_t) if not isinstance(mg_t, Exception) else [],
        matched_symbol,
        _now_ist().date(),
        symbol_root,
    )


@router.get("/contracts")
async def gold_contracts(
    exchange: str = Query("MCX", pattern="^(MCX|COMEX|mcx|comex)$"), response: Response = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """The contract selector (c.selector): every MCX family incl. GOLDTEN with its expiries, economics, margins, matched COMEX
    month and the diff keys; `?exchange=COMEX` adds the matched contract's DES-style spec card (c.spec)."""
    reads = Reads()
    now = _now_ist()
    got, mg_t, curve_t, mcx_curve_t = await _gather(
        asyncio.to_thread(mcxr._master_gold_family),
        reads.get("/db/gold/margins", exchange="MCX"),
        reads.get("/db/gold/curve", exchange="COMEX"),
        reads.get("/db/gold/curve", exchange="MCX"),
    )
    family, published = got if isinstance(got, tuple) else (None, None)
    latest = gp.latest_completed_session(now)
    vwaps = await contract_vwaps(family, now.date(), latest)
    payload = build_contracts(
        family,
        published,
        _margin_rows(mg_t) if not isinstance(mg_t, Exception) else {},
        curve_points(curve_t, now.date()) if not isinstance(curve_t, Exception) else [],
        now.date(),
        _mcx_oi_changes(mcx_curve_t) if not isinstance(mcx_curve_t, Exception) else {},
        vwaps,
        latest,
    )
    if exchange.upper() == "COMEX":
        payload["comex_spec"] = await _comex_spec(reads, (payload.get("comex_matched_by_family") or {}).get("GOLD"))
    payload["as_of"] = now.isoformat(timespec="seconds")
    payload["freshness"] = freshness(
        published.isoformat() if published else None, 4.0, "ICICI MCX security master", live=bool(family)
    )
    payload["store_errors"] = reads.errors or None
    reads.headers(response)
    return payload


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /premiums · GET /flows (PHYSICAL)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════

FINENESS_ADJ = 999 / 1000  # IBJA 999 vs the per-fine-gold COMEX/LBMA landed price: × 0.999 (PM decision D1)


@router.get("/asia")
async def gold_asia(exchange: str | None = Query(None, pattern="^(SGE|SHFE)$"), from_: str | None = Query(None, alias="from")) -> dict[str, Any]:
    """p.asia (PLAN a.6): a paced read-through of data-service `/db/gold/asia` (gold_asia_daily: SHFE au front OI/Δ, SGE Au(T+D)
    OI and settlement direction, Au99.99 VWAP) under the catalog ids SHFE_DAILY / SGE_DAILY; `freshness` from the newest trade_date.
    Until this exists the release build hides p.asia (C-BEGINNER-16, C-DATA-17)."""
    params: dict[str, Any] = {}
    if exchange:
        params["exchange"] = exchange
    if from_:
        params["from"] = from_
    try:
        payload = await _db_fetch("/db/gold/asia", params)
    except StoreUnavailable as exc:
        return degraded({"rows": [], "freshness": freshness(None, 2.0, "SGE / SHFE"), "badge": BADGE_CONTEXT}, "state", str(exc))
    rows = _rows(payload)
    last = max((str(r.get("trade_date")) for r in rows if r.get("trade_date")), default=None)
    return {
        "rows": rows,
        "freshness": freshness(last, 2.0, "SGE / SHFE daily tables"),
        "badge": BADGE_CONTEXT,
        "catalog_ids": ["SHFE_DAILY", "SGE_DAILY"],
        "as_of": _now_ist().isoformat(),
    }


SH_SPIKE_USD = 25.0  # $/oz away from the neighbours' median: a same-date pair that is most likely a timing artefact


def _timing_spike(pts: list[dict[str, Any]], i: int) -> bool:
    """True when pair i sits more than SH_SPIKE_USD from the median of up to two pairs either side (itself excluded)."""
    nb = [p["value"] for j, p in enumerate(pts[max(0, i - 2) : i + 3], start=max(0, i - 2)) if j != i and p.get("value") is not None]
    if len(nb) < 2 or pts[i].get("value") is None:
        return False
    return abs(pts[i]["value"] - statistics.median(nb)) > SH_SPIKE_USD


def build_premiums(
    fair: dict[str, Any], series: dict[str, list[dict[str, Any]]], cat: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """The India price stack (ladder) and the Shanghai premium from the fair block and stored series. Pure."""

    def last_of(sid: str) -> dict[str, Any] | None:
        return latest(series.get(sid) or []) if is_published(cat, sid) else None

    def pts(sid: str) -> list[dict[str, Any]]:
        return (series.get(sid) or []) if is_published(cat, sid) else []

    ibja = last_of("IBJA_999_PM")
    comex = fair.get("comex") or {}
    usdinr = fair.get("usdinr") or {}
    # every rupee price on the ladder is ₹/10 g (PM decision D3): the fair block of a PETAL (₹/1 g) or GUINEA (₹/8 g) contract
    # is in that contract's quotation unit, so its landed, duty-paid, settle and reference values are scaled × 10 / grams
    # before they sit beside the IBJA ₹/10 g fix, and the MCX step says so
    spec = mcxr.contract_specs().get(str(fair.get("contract") or "GOLD").upper())
    quote_g = float(spec.quote_per_grams) if spec else 10.0
    to10 = 10.0 / quote_g if quote_g else 1.0

    def per10(v: Any) -> float | None:
        return _r(float(v) * to10, 0) if isinstance(v, (int, float)) else None

    scaled_note = f" (₹ per {quote_g:g} g × {to10:g})" if to10 != 1 else ""
    duty_paid = per10(fair.get("duty_paid_landed"))
    # ONE India premium, at ONE clock: the stored INDIA_PREMIUM_PCT (IBJA 999 PM ÷ duty-paid landed at the fix minute,
    # × 0.999, D1) — never the PM fix divided by a landed price computed hours later (C-TRADER-4 / C-BEGINNER-2 / C-DATA-11)
    prem_pts = pts("INDIA_PREMIUM_PCT")
    stored_prem = prem_pts[-1] if prem_pts else None
    premium = _r(stored_prem["value"], 2) if stored_prem else None
    premium_date = stored_prem["report_date"] if stored_prem else None
    premium_note = None
    if ibja and stored_prem and ibja["report_date"] > stored_prem["report_date"]:
        premium_note = (
            f"IBJA {_day_label(ibja['report_date'])} PM is stored; its fix-minute premium is derived by the 21:30 job — "
            f"showing {_day_label(stored_prem['report_date'])}"
        )
    elif ibja and not stored_prem:
        premium_note = "no fix-minute premium stored yet (data-service derive); the live bars are not divided into the fix"
    sb = settle_basis(fair, pts("MCX_BASIS_PCT"))
    basis_txt = f" (basis {sb['value']:+.2f} % {sb['label']})".replace("-", "−") if sb.get("value") is not None else ""
    ibja_txt = (
        f"IBJA 999 PM (premium {premium:+.2f} % at the {_day_label(premium_date)} fix)".replace("-", "−")
        if premium is not None and premium_date
        else "IBJA 999 PM"
    )
    ladder = [
        {
            "step": "comex",
            "label": f"COMEX {comex.get('symbol') or ''} $/oz · now".strip(),
            "value": comex.get("price"),
            "ts": _iso_any(comex.get("as_of")),
            "clock": "now",
            "source": "Yahoo (cached fetcher)",
            "unit": "$/oz",
        },
        {
            "step": "usdinr",
            "label": "× USD/INR · now",
            "value": usdinr.get("price"),
            "ts": _iso_any(usdinr.get("as_of")),
            "clock": "now",
            "source": "Yahoo INR=X",
            "unit": "₹/$",
        },
        {
            "step": "landed",
            "label": "landed ₹/10 g fine gold (ex-duty) · now",
            "value": per10(fair.get("landed")),
            "ts": _iso_any(comex.get("as_of")),
            "clock": "now",
            "source": "M5",
            "unit": "₹/10 g",
        },
        {
            "step": "duty",
            "label": f"+ duty {fair.get('duty_pct')} % ({gp.DUTY_NOTIFICATION}, since {fair.get('duty_effective')})",
            "value": fair.get("duty_pct"),
            "ts": fair.get("duty_effective"),
            "clock": "dated constant",
            "source": "CBIC (confirm: O-3)",
            "unit": "%",
        },
        {
            "step": "duty_paid",
            "label": "duty-paid landed ₹/10 g fine gold · now",
            "value": duty_paid,
            "ts": _iso_any(comex.get("as_of")),
            "clock": "now",
            "source": "M6",
            "unit": "₹/10 g",
        },
        {
            "step": "ibja",
            "label": ibja_txt,
            "value": ibja["value"] if ibja else None,
            "ts": ibja["report_date"] if ibja else None,
            "clock": "fix",
            "source": "IBJA (displayed with attribution)",
            "unit": "₹/10 g",
        },
        {
            "step": "mcx",
            "label": f"MCX {fair.get('contract')} {_mmy(fair.get('expiry')) or ''} settle{scaled_note}{basis_txt}",
            "value": per10(fair.get("settlement")),
            "value_native": fair.get("settlement"),
            "unit_native": f"₹/{quote_g:g} g",
            "scaled_to_10g": to10 != 1,
            "ts": fair.get("settlement_session"),
            "ts_label": fair.get("settlement_session_label"),
            "clock": "settlement",
            "source": (
                "last-30-min VWAP of Breeze 1-minute bars (proxy)"
                if fair.get("settlement_source") == "breeze_vwap30"
                else "ICICI band midpoint (proxy)"
            ),
            "settlement_source": fair.get("settlement_source"),
            "settlement_quality": fair.get("settlement_quality"),
            "settlement_check": fair.get("settlement_check"),
            # the basis divides by the duty-paid landed price OF THIS CONTRACT'S PURITY at that session's close (wave 1d)
            "basis_reference": sb.get("basis_reference"),
            "reference_value": per10(fair.get("duty_paid_landed_at_settlement")),
            "reference_label": (f"duty-paid landed × {fair.get('purity')}/1000 at that session's close"
                                if fair.get("purity") else None),
            "unit": "₹/10 g",
        },
    ]
    # Shanghai: SGE PM and the London PM of the SAME report date only (C-TRADER-5 / C-DATA-10: the Wed SGE against the
    # Tue LBMA after a +3.5 % day printed +$109 while the stored same-day figure was −$1.55). When today's PM is not
    # stored yet, the last stored SHANGHAI_PREMIUM_USD stands, labelled, and the newer SGE fix is shown on its own.
    sge_pts, lbma_pts = pts("SGE_SHAU_PM"), pts("LBMA_PM_USD")
    cny_pts = pts("FX_CNY") or pts("FRED_DEXCHUS")
    sge = sge_pts[-1] if sge_pts else None
    lbma_same = next((p for p in reversed(lbma_pts) if sge and p["report_date"] == sge["report_date"]), None)
    cny_same = next((p for p in reversed(cny_pts) if sge and p["report_date"] <= sge["report_date"]), None) if sge else None
    sh_hist_usd, sh_hist_pct = pts("SHANGHAI_PREMIUM_USD"), pts("SHANGHAI_PREMIUM_PCT")
    stored_sh = sh_hist_usd[-1] if sh_hist_usd else None
    sge_usd = sh_prem = sh_pct = ref_usd = None
    pair_date = pairing = sh_note = None
    if sge and lbma_same and cny_same and cny_same["value"]:
        sge_usd = _r(sge["value"] * GRAMS_PER_TROY_OZ / cny_same["value"], 2)
        ref_usd = lbma_same["value"]
        sh_prem = _r(sge_usd - ref_usd, 2)
        sh_pct = _r(sh_prem / ref_usd * 100, 2) if ref_usd else None
        pair_date, pairing = sge["report_date"], "same report date (SGE PM 14:15 Beijing · LBMA PM 15:00 London)"
    elif stored_sh:
        sh_prem = _r(stored_sh["value"], 2)
        sh_pct = _close_on(sh_hist_pct, _d(stored_sh["report_date"])) if sh_hist_pct else None
        sh_pct = _r(sh_pct, 2) if sh_pct is not None else None
        pair_date, pairing = stored_sh["report_date"], "last stored same-date pair (data-service derive)"
        lb_at = next((p for p in reversed(lbma_pts) if p["report_date"] == stored_sh["report_date"]), None)
        ref_usd = lb_at["value"] if lb_at else None
        sg_at = next((p for p in reversed(sge_pts) if p["report_date"] == stored_sh["report_date"]), None)
        cn_at = next((p for p in reversed(cny_pts) if sg_at and p["report_date"] <= sg_at["report_date"]), None) if sg_at else None
        sge_usd = _r(sg_at["value"] * GRAMS_PER_TROY_OZ / cn_at["value"], 2) if sg_at and cn_at and cn_at["value"] else None
        if sge and sge["report_date"] > stored_sh["report_date"]:
            sh_note = f"awaiting today's PM: SGE {_day_label(sge['report_date'])} is in, its London PM is not stored yet"
    elif sge:
        sh_note = "no same-date London PM stored: no premium (never SGE vs an earlier London fix)"
    # the legs printed beside the premium are the PAIR's legs (same date); a newer SGE print is shown on its own
    # (re-review C-DATA-2 N1: '865.47 CNY/g = $3,935.1' glued a 4 Nov CNY leg to the 3 Nov USD leg)
    sge_shown: dict[str, Any] | None
    cny_shown: dict[str, Any] | None
    if sge and lbma_same and cny_same and cny_same["value"]:
        sge_shown, cny_shown = sge, cny_same
    elif stored_sh:
        sge_shown, cny_shown = sg_at, cn_at
    else:
        sge_shown, cny_shown = None, None
    sge_latest = sge if sge and (not sge_shown or sge["report_date"] > sge_shown["report_date"]) else None
    hist_in = [
        {
            "report_date": p["report_date"],
            "premium_pct": p["value"],
            # the basis of THAT date only — a carried-forward settle basis is not that day's (C-DATA-20)
            "basis_pct": next((b["value"] for b in pts("MCX_BASIS_PCT") if b["report_date"] == p["report_date"]), None),
        }
        for p in prem_pts
    ]
    hist_cn = [
        {
            "report_date": p["report_date"],
            "premium_usd": p["value"],
            "premium_pct": next((q["value"] for q in sh_hist_pct if q["report_date"] == p["report_date"]), None),
            # a pair far from its neighbours' median is most likely the 14:15 Beijing vs 15:00 London timing gap on a big
            # day (+$75.34 on Fri 30 Oct, a −3.3 % day), not a premium: flagged so the chart can mark it (5 Nov review)
            "timing_spike_suspect": _timing_spike(sh_hist_usd, i),
        }
        for i, p in enumerate(sh_hist_usd)
    ]
    duty_hist = [{"effective": d, "pct": p} for d, p in gp.DUTY_HISTORY]
    wgc_in, wgc_cn = last_of("WGC_PREMIUM_IN"), last_of("WGC_PREMIUM_CN")
    return {
        "india": {
            "ladder": ladder,
            "premium_pct": premium,
            "premium_date": premium_date,
            "premium_clock": "IBJA PM fix minute: both legs sampled at the fix (stored INDIA_PREMIUM_PCT)",
            "premium_note": premium_note,
            "ibja_date": ibja["report_date"] if ibja else None,
            "fineness_adjustment": ("stored premium: IBJA 999 PM vs duty-paid landed × 0.999 (landed is per fine gold; IBJA 995 "
                                    "would compare with × 0.995 — PM decision D1, data-service derive)"),
            "basis_reference": sb.get("basis_reference"),
            "basis_purity_note": (
                f"the MCX basis divides by the duty-paid landed price × {fair.get('purity')}/1000 (COMEX × USD/INR is the "
                "price of fine gold; GOLD / GOLDM 995, GOLDTEN / PETAL / GUINEA 999 — PM decision D1)"
                if fair.get("purity")
                else None
            ),
            "unit": "₹/10 g",
            "unit_note": (f"{fair.get('contract')} is quoted per {quote_g:g} g: its prices are scaled × {to10:g} to ₹/10 g here"
                          if to10 != 1 else None),
            "basis_pct": sb["value"],
            "basis_date": sb["date"],
            "basis_label": sb["label"],
            "basis_source": sb["source"],
            "live_basis": live_basis(fair),
            "carry_adj_pct": None,
            "duty": {
                "pct": fair.get("duty_pct"),
                "effective": fair.get("duty_effective"),
                "notification": gp.DUTY_NOTIFICATION,
                "note": fair.get("duty_note"),
                "history": duty_hist,
            },
            "history": hist_in,
            "badge": {"ladder": BADGE_ARITH, "premium": BADGE_CONTEXT},
            "clock_note": "the five left-hand bars are now; IBJA is its PM fix; MCX is the last settlement — every ratio on this "
            "panel is taken at ONE clock (the premium at the fix, the basis at the settlement); never divide across them "
            "(G-INDIA §5.3)",
            "freshness": freshness(
                ibja["report_date"] if ibja else None, max_age_of(cat, "IBJA_999_PM", 4.0), "IBJA (displayed with attribution)"
            ),
        },
        "shanghai": {
            "sge_pm_cny_g": sge_shown["value"] if sge_shown else None,
            "sge_pm_date": sge_shown["report_date"] if sge_shown else None,
            "usdcny": cny_shown["value"] if cny_shown else None,
            "usdcny_date": cny_shown["report_date"] if cny_shown else None,
            "sge_latest_cny_g": sge_latest["value"] if sge_latest else None,
            "sge_latest_date": sge_latest["report_date"] if sge_latest else None,
            "legs_note": "CNY/g, USDCNY and $/oz are the pair date's own legs; a newer SGE print stands alone until its London PM is stored",
            "usdcny_source": "Yahoo CNY=X" if pts("FX_CNY") else ("FRED DEXCHUS" if cny_pts else None),
            "sge_usd_oz": sge_usd,
            "london_pm_usd": ref_usd,
            "comex_at_1415_bj": None,
            "premium_usd": sh_prem,
            "premium_pct": sh_pct,
            "pair_date": pair_date,
            "pairing": pairing,
            "note": sh_note,
            "ts_sge": sge["report_date"] if sge else None,
            "ts_ref": pair_date,
            "history": hist_cn,
            "badge": BADGE_CONTEXT,
            "clock_note": "SGE PM (14:15 Beijing) and the LBMA PM (15:00 London) of the same date, about 7 hours apart: read "
            "changes and sign flips, not the level",
            "freshness": freshness(
                pair_date, max_age_of(cat, "SHANGHAI_PREMIUM_USD", 4.0), "SGE × LBMA (view-only, attributed)"
            ),
        },
        "reference": {
            "wgc_india": wgc_in["value"] if wgc_in else None,
            "wgc_india_week": wgc_in["report_date"] if wgc_in else None,
            "wgc_china": wgc_cn["value"] if wgc_cn else None,
            "wgc_china_week": wgc_cn["report_date"] if wgc_cn else None,
            "reuters_url": REUTERS_LINK,
            "attribution": "World Gold Council weekly premiums, displayed with attribution",
        },
    }


@router.get("/premiums")
async def gold_premiums(
    days: int = Query(365, ge=7, le=3000),
    contract: str = Query("GOLD"),
    expiry: str | None = Query(None),
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """PHYSICAL › the India price stack (ph.ladder), the India premium / MCX basis history, the Shanghai premium and the WGC
    reference lines. `contract` / `expiry` (default GOLD front) pick the MCX bar of the ladder — the page passes its pick so
    the ladder prints the same basis as the strip and the gauge (wave 1d)."""
    if contract.upper() not in mcxr.contract_specs():
        fail(422, "invalid", f"Unknown MCX contract '{contract}'")
    if expiry:
        _date_arg(expiry, "expiry")
    reads = Reads()
    cat = await catalog(reads)
    series_t, fair_t = await _gather(
        fetch_series(
            reads,
            [
                "IBJA_999_PM",
                "INDIA_PREMIUM_PCT",
                "MCX_BASIS_PCT",
                "SGE_SHAU_PM",
                "FX_CNY",
                "FRED_DEXCHUS",
                "LBMA_PM_USD",
                "SHANGHAI_PREMIUM_USD",
                "SHANGHAI_PREMIUM_PCT",
                "WGC_PREMIUM_IN",
                "WGC_PREMIUM_CN",
            ],
            days=days,
        ),
        fair_block(contract.upper(), expiry),
    )
    fair: dict[str, Any] = fair_t if isinstance(fair_t, dict) else {}
    payload = build_premiums(fair, series_t if isinstance(series_t, dict) else {}, cat)
    payload["as_of"] = _now_ist().isoformat(timespec="seconds")
    payload["store_errors"] = reads.errors or None
    reads.headers(response)
    return payload


def build_flows(
    etf_rows: list[dict[str, Any]],
    series: dict[str, list[dict[str, Any]]],
    efrp_rows: list[dict[str, Any]],
    voi_rows: list[dict[str, Any]],
    cat: dict[str, dict[str, Any]],
    months: int,
) -> dict[str, Any]:
    """ETF holdings and flows, the official sector, RBI, the OTC window, physical monthly series and the WGC balance sheet.
    Pure."""

    def pts(sid: str) -> list[dict[str, Any]]:
        return (series.get(sid) or []) if is_published(cat, sid) else []

    def last_of(sid: str) -> dict[str, Any] | None:
        return latest(pts(sid))

    etf: list[dict[str, Any]] = []
    by_fund: dict[str, list[dict[str, Any]]] = {}
    for r in etf_rows:
        by_fund.setdefault(str(r.get("fund") or "GLD").upper(), []).append(r)
    for fund, rows in by_fund.items():
        p = _points(rows, value_key="tonnes")
        if not p:
            continue
        last_p = p[-1]
        etf.append(
            {
                "report_date": last_p["report_date"],
                "fund": fund,
                "tonnes": last_p["value"],
                "chg_1d": _diff(last_p["value"], p[-2]["value"]) if len(p) > 1 else None,
                "chg_5d": _diff(last_p["value"], change_over(p, 7)[1]),
                "chg_1m": _diff(last_p["value"], change_over(p, 30)[1]),
                "chg_ytd": _diff(last_p["value"], _close_on(p, date(_dd(last_p["report_date"]).year - 1, 12, 31))),
                "cumulative_30d": [{"report_date": q["report_date"], "tonnes": q["value"]} for q in p[-30:]],
                "source": "SPDR / iShares (displayed with attribution)",
            }
        )
    wgc_weekly: list[dict[str, Any]] = []
    for region in ("GLOBAL", "NA", "EU", "ASIA", "OTHER"):
        for w in pts(f"WGC_ETF_FLOW_T_{region}")[-26:]:
            wgc_weekly.append(
                {
                    "week_ending": w["report_date"],
                    "region": region,
                    "flow_t": w["value"],
                    "holdings_t": _close_on(pts("WGC_ETF_HOLD_T_GLOBAL"), _d(w["report_date"])) if region == "GLOBAL" else None,
                }
            )
    hold_in = last_of("WGC_ETF_HOLD_T_IN")
    official: list[dict[str, Any]] = []
    for sid, p in series.items():
        if sid.startswith("IMF_GOLD_OZ_") and p and is_published(cat, sid):
            # IMF IFS stores TROY OUNCES (unit 'oz'): Moz = oz ÷ 1e6, t = Moz × 31.1035 (C-TRADER-6 / C-BEGINNER-3 /
            # C-DATA-5 — the old row labelled the raw ounces 'oz_mn' and multiplied by 31.1 for 'tonnes', 10⁶ too large)
            last_p = p[-1]
            oz = last_p["value"]
            chg_oz = _diff(oz, p[-2]["value"]) if len(p) > 1 else None
            chg_12m_oz = _diff(oz, change_over(p, 365)[1])
            official.append(
                {
                    "country": sid.rsplit("_", 1)[-1],
                    "month": last_p["report_date"][:7],
                    "oz": oz,
                    "oz_mn": _r(oz / 1e6, 3),
                    "tonnes": _r(oz / 1e6 * TONNES_PER_MOZ, 1),
                    "chg_oz_mn": _r(chg_oz / 1e6, 3) if chg_oz is not None else None,
                    "chg_t": _r(chg_oz / 1e6 * TONNES_PER_MOZ, 1) if chg_oz is not None else None,
                    "chg_12m_oz_mn": _r(chg_12m_oz / 1e6, 3) if chg_12m_oz is not None else None,
                    "chg_12m_t": _r(chg_12m_oz / 1e6 * TONNES_PER_MOZ, 1) if chg_12m_oz is not None else None,
                    "unit_note": "IMF IFS reports troy ounces; Moz = oz ÷ 1e6; t = Moz × 31.1035",
                }
            )
    official.sort(key=lambda o: -(o["oz_mn"] or 0))
    rbi_usd, rbi_tot = last_of("RBI_GOLD_RESERVES_USD_MN"), last_of("RBI_RESERVES_TOTAL_USD_MN")
    gold_px = last_of("COMEX_GC_FRONT") or last_of("LBMA_PM_USD")
    imf_in = last_of("IMF_GOLD_OZ_IND")
    rbi = {
        "week": rbi_usd["report_date"] if rbi_usd else None,
        "usd_mn": rbi_usd["value"] if rbi_usd else None,
        "share_pct": _r(rbi_usd["value"] / rbi_tot["value"] * 100, 1) if rbi_usd and rbi_tot and rbi_tot["value"] else None,
        # ONE tonnage for India on the page: the IMF's reported ounces (C-TRADER-22 — the price-implied 815 t sat beside the
        # IMF's 880 t); `tonnes_est` stays as a null alias for one release
        "tonnes": _r(imf_in["value"] / 1e6 * TONNES_PER_MOZ, 1) if imf_in else None,
        "tonnes_month": imf_in["report_date"][:7] if imf_in else None,
        "tonnes_source": "IMF IFS official reserves, troy oz (monthly)" if imf_in else None,
        "tonnes_est": None,
        "inr_cr": (last_of("RBI_GOLD_RESERVES_INR_CR") or {}).get("value"),
        "note": "the WSS value is the week's $ mark of the reserve; the tonnage is the IMF's reported ounces, not a price-implied estimate",
    }
    turn, vault = last_of("LBMA_OTC_TURNOVER_USD_BN"), last_of("LBMA_VAULT_GOLD_T")
    gold_efrp = [
        r
        for r in efrp_rows
        if "GOLD" in str(r.get("product") or r.get("product_line") or "").upper() and _d(r.get("process_date"))
    ]
    by_day: dict[str, float] = {}
    for r in gold_efrp:
        by_day[str(r["process_date"])[:10]] = by_day.get(str(r["process_date"])[:10], 0.0) + (_f(r.get("round_turns")) or 0.0)
    days_sorted = sorted(by_day)
    efp_today = by_day[days_sorted[-1]] if days_sorted else None
    # a "20-day average" of one day is that day (C-TRADER-21 / C-DATA-19): null until MIN_AVG_SESSIONS prior days exist
    prior_days = days_sorted[:-1][-20:]
    efp_avg = (sum(by_day[d] for d in prior_days) / len(prior_days)) if len(prior_days) >= MIN_AVG_SESSIONS else None
    gc_vol = next(
        (
            _f(r.get("total_volume"))
            for r in sorted(voi_rows, key=lambda r: str(r.get("trade_date") or ""), reverse=True)
            if str(r.get("product_code") or "").upper() == "GC" and _is_futures(r.get("fut_or_opt"))
        ),
        None,
    )
    otc = {
        "lbma_turnover_usd_bn": turn["value"] if turn else None,
        "week_ending": turn["report_date"] if turn else None,
        "turnover_tonnes_est": _r(turn["value"] * 1e9 / gold_px["value"] / 32150.7466, 0)
        if turn and gold_px and gold_px["value"]
        else None,
        "vault_t": vault["value"] if vault else None,
        "vault_month": vault["report_date"][:7] if vault else None,
        "vault_chg_t": _diff(vault["value"], pts("LBMA_VAULT_GOLD_T")[-2]["value"])
        if vault and len(pts("LBMA_VAULT_GOLD_T")) > 1
        else None,
        "efp": {
            "today_rt": efp_today,
            "date": days_sorted[-1] if days_sorted else None,
            "avg_20d": _r(efp_avg, 0),
            "avg_sessions": len(prior_days),
            "since": days_sorted[0] if days_sorted else None,
            "avg_note": (
                f"average needs {MIN_AVG_SESSIONS} prior sessions; {len(prior_days)} stored since {_day_label(days_sorted[0])}"
                if days_sorted and efp_avg is None
                else None
            ),
            "pct_of_volume": _r(efp_today / gc_vol * 100, 2) if efp_today is not None and gc_vol else None,
        },
        "read": "activity and stock, not positions: there is no COT for London; gross, not netted",
    }
    amfi_net, amfi_aum = last_of("AMFI_GOLD_ETF_NET_CR"), last_of("AMFI_GOLD_ETF_AUM_CR")
    landed = last_of("GOLD_INR_DUTY_PAID") or last_of("GOLD_INR_LANDED")
    physical = {
        "sge_withdrawals_kg": (last_of("SGE_WITHDRAWALS_KG") or {}).get("value"),
        "sge_withdrawals_month": (last_of("SGE_WITHDRAWALS_KG") or {}).get("report_date"),
        "india_imports_usd_bn": (last_of("INDIA_GOLD_IMPORTS_USD_BN") or {}).get("value"),
        "india_imports_month": (last_of("INDIA_GOLD_IMPORTS_USD_BN") or {}).get("report_date"),
        "india_imports_yoy_pct": _pct_change(
            (last_of("INDIA_GOLD_IMPORTS_USD_BN") or {}).get("value"), change_over(pts("INDIA_GOLD_IMPORTS_USD_BN"), 365)[1]
        ),
        "swiss_exports_in_kg": (last_of("SWISS_GOLD_EXPORT_IN_KG") or {}).get("value"),
        "amfi": {
            "net_cr": amfi_net["value"] if amfi_net else None,
            "aum_cr": amfi_aum["value"] if amfi_aum else None,
            "month": amfi_aum["report_date"][:7] if amfi_aum else None,
            "tonnes_est": _r(amfi_aum["value"] * 1e7 / landed["value"] * 10 / 1e6, 1)
            if amfi_aum and landed and landed["value"]
            else None,
            "evidence": "G-INDIA-1 FAIL as timing; context",
        },
    }
    balance = [
        {"period": p["report_date"], "series": sid.removeprefix("WGC_SD_").lower(), "tonnes": p["value"]}
        for sid, ps in series.items()
        if sid.startswith("WGC_SD_") and is_published(cat, sid)
        for p in ps[-months // 3 - 1 :]
    ]
    return {
        "etf": etf,
        "wgc_weekly": wgc_weekly,
        "wgc_india_holdings_t": hold_in["value"] if hold_in else None,
        "official": official[:24],
        "official_months": (
            {"newest": max(str(r.get("month") or "") for r in official), "oldest": min(str(r.get("month") or "") for r in official)}
            if official
            else None
        ),
        "rbi": rbi,
        "otc": otc,
        "physical_monthly": physical,
        "balance_sheet": balance,
        "badge": BADGE_CONTEXT,
        "evidence": "ETF flows: move with the price, do not lead it (G-STUDY, G-MACRO, GS-P1 26 Oct 2026); central banks: GS-P5 pending (not yet pre-registered)",
        "attribution": "WGC / SPDR / iShares / IMF / LBMA / SGE numbers displayed with attribution on this private terminal; "
        "never re-served (O-1)",
        "freshness": {
            "etf": freshness(etf[0]["report_date"] if etf else None, max_age_of(cat, "GLD_TONNES", 5.0), "SPDR / iShares"),
            "wgc_weekly": freshness(wgc_weekly[-1]["week_ending"] if wgc_weekly else None, 10.0, "World Gold Council"),
            # the panel's date is the NEWEST data month (5 Nov review: 'as of Wed 01 Jul' — the first row's, USA 2026-07 — while
            # most rows were 2026-09); `official_months` says the spread
            "official": freshness(
                max(str(r.get("month") or "") for r in official) + "-01" if official else None, 60.0, "IMF IFS"
            ),
            "rbi": freshness(rbi["week"], 10.0, "RBI WSS"),
            "otc": freshness(otc["week_ending"], 10.0, "LBMA"),
        },
    }


@router.get("/flows")
async def gold_flows(months: int = Query(24, ge=1, le=240), response: Response = None) -> dict[str, Any]:  # type: ignore[assignment]
    """PHYSICAL › ETF holdings and flows, the official sector, RBI, the OTC window (LBMA turnover, vaults, CME EFP), the
    physical monthly series and the WGC balance sheet."""
    reads = Reads()
    now = _now_ist()
    cat = await catalog(reads)
    days = months * 31
    ids = [
        "WGC_ETF_FLOW_T_GLOBAL",
        "WGC_ETF_FLOW_T_NA",
        "WGC_ETF_FLOW_T_EU",
        "WGC_ETF_FLOW_T_ASIA",
        "WGC_ETF_FLOW_T_OTHER",
        "WGC_ETF_HOLD_T_GLOBAL",
        "WGC_ETF_HOLD_T_IN",
        "RBI_GOLD_RESERVES_USD_MN",
        "RBI_GOLD_RESERVES_INR_CR",
        "RBI_RESERVES_TOTAL_USD_MN",
        "COMEX_GC_FRONT",
        "LBMA_PM_USD",
        "LBMA_OTC_TURNOVER_USD_BN",
        "LBMA_VAULT_GOLD_T",
        "SGE_WITHDRAWALS_KG",
        "INDIA_GOLD_IMPORTS_USD_BN",
        "SWISS_GOLD_EXPORT_IN_KG",
        "AMFI_GOLD_ETF_NET_CR",
        "AMFI_GOLD_ETF_AUM_CR",
        "GOLD_INR_DUTY_PAID",
        "GOLD_INR_LANDED",
    ]
    ids += [sid for sid in cat if sid.startswith(("IMF_GOLD_OZ_", "WGC_SD_"))]
    series_t, etf_t, efrp_t, voi_t = await _gather(
        fetch_series(reads, ids, days=max(days, 400)),
        reads.get("/db/gold/etf", **{"from": (now.date() - timedelta(days=days)).isoformat()}),
        reads.get("/db/gold/cme/efrp", **{"from": (now.date() - timedelta(days=45)).isoformat()}),
        reads.get("/db/gold/cme/voi", **{"from": (now.date() - timedelta(days=10)).isoformat()}, products="GC"),
        )
    payload = build_flows(
        _rows(etf_t) if not isinstance(etf_t, Exception) else [],
        series_t if isinstance(series_t, dict) else {},
        _rows(efrp_t) if not isinstance(efrp_t, Exception) else [],
        _rows(voi_t) if not isinstance(voi_t, Exception) else [],
        cat,
        months,
    )
    payload["as_of"] = now.isoformat(timespec="seconds")
    payload["store_errors"] = reads.errors or None
    reads.headers(response)
    return payload


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /macro — why gold moved (drivers, the KGX split, currencies, the Fed path, expected move, driver health)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════

MACRO_DRIVERS: tuple[tuple[str, str, str, str, int, str], ...] = (
    # key, label, primary series, alternate series, gold-positive direction (−1: falling is supportive), unit
    ("real_10y", "10-y real yield", "FRED_DFII10", "UST_REAL_10Y", -1, "%"),
    ("nominal_2y", "2-y Treasury", "FRED_DGS2", "UST_NOM_2Y", -1, "%"),
    ("breakeven_10y", "10-y breakeven", "FRED_T10YIE", "", +1, "%"),
    ("dxy", "Dollar index (DXY)", "DXY_CLOSE", "FRED_DTWEXBGS", -1, "index"),
    ("usdinr", "USD/INR", "USDINR_CLOSE", "USDINR_FBIL", +1, "₹/$"),
    ("gvz", "GVZ (gold vol)", "GVZ_CLOSE", "FRED_GVZCLS", 0, "%"),
    ("brent", "Brent", "FRED_DCOILBRENTEU", "BRENT_FRONT", +1, "$/bbl"),   # BZ=F daily (G-DATA); WTI is not Brent
)
TRUE_TWINS = ("brent", "real_10y", "nominal_2y", "gvz")   # the drivers whose alternate series measures the SAME thing
REGIMES: tuple[tuple[str, int, int], ...] = (("2003–09", 2003, 2009), ("2010–21", 2010, 2021), ("2022–26", 2022, 2026))


def _daily_changes(points: list[dict[str, Any]], pct: bool) -> dict[str, float]:
    out: dict[str, float] = {}
    for a, b in pairwise(points):
        if a["value"] and b["value"] is not None:
            out[b["report_date"]] = (b["value"] / a["value"] - 1) * 100 if pct else b["value"] - a["value"]
    return out


def _corr(a: dict[str, float], b: dict[str, float], keys: list[str]) -> float | None:
    xs = [(a[k], b[k]) for k in keys if k in a and k in b]
    if len(xs) < 10:
        return None
    mx, my = statistics.fmean(x for x, _ in xs), statistics.fmean(y for _, y in xs)
    sxx = sum((x - mx) ** 2 for x, _ in xs)
    syy = sum((y - my) ** 2 for _, y in xs)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in xs) / math.sqrt(sxx * syy), 3)


def _beta(y: dict[str, float], x: dict[str, float], keys: list[str]) -> float | None:
    xs = [(x[k], y[k]) for k in keys if k in x and k in y]
    if len(xs) < 20:
        return None
    mx, my = statistics.fmean(a for a, _ in xs), statistics.fmean(b for _, b in xs)
    sxx = sum((a - mx) ** 2 for a, _ in xs)
    return round(sum((a - mx) * (b - my) for a, b in xs) / sxx, 3) if sxx > 0 else None


def kgx_split(
    gold_pts: list[dict[str, Any]], fx: dict[str, list[dict[str, Any]]], days: int, anchor: date | None = None,
    window_label: str | None = None,
) -> dict[str, Any]:
    """ "Gold or the dollar?" (M56): usd_effect = −Σ wᵢ·Δln fᵢ over the DXY basket (foreign-per-USD quotes flipped), pure =
    total − usd_effect; the rupee leg is the USD/INR change (what an MCX holder also sees). Identity, not a forecast.
    `anchor` (the close the window starts from — HEALTH's week-to-date / previous-session anchor, so 'W' means the same on
    both views, 5 Nov review) replaces the calendar-day lookback when given."""

    def span(pts: list[dict[str, Any]]) -> tuple[float | None, float | None, str | None]:
        if anchor is None:
            return change_over(pts, days)
        if not pts:
            return None, None, None
        then = _row_on_or_before(pts, anchor)
        return pts[-1]["value"], (then or {}).get("value"), (then or {}).get("report_date")

    g_now, g_then, from_date = span(gold_pts)
    total = _pct_change(g_now, g_then)
    dln_usd = 0.0  # Δln of the dollar basket, in %: Σ wᵢ · sᵢ · Δln fᵢ (sᵢ = −1 for USD-per-foreign quotes)
    used: dict[str, float] = {}
    for sid, (w, sign) in DXY_WEIGHTS.items():
        pts = fx.get(sid) or []
        v_now, v_then, _ = span(pts)
        if v_now and v_then:
            dln_usd += w * sign * math.log(v_now / v_then) * 100
            used[sid] = w
    inr_now, inr_then, _ = span(fx.get("USDINR_CLOSE") or [])
    inr = _pct_change(inr_now, inr_then)
    usd_effect = -dln_usd if used else None  # a stronger dollar is a NEGATIVE effect on gold's USD price (M56)
    total_r, usd_r = _r(total, 2), _r(usd_effect, 2)
    pure_r = (
        round(total_r - usd_r, 2) if total_r is not None and usd_r is not None else None
    )  # identity holds on the printed numbers
    return {
        "period": {1: "D", 7: "W", 30: "M"}.get(days, f"{days}d"),
        "from_date": from_date,
        "window_label": window_label,
        "total_pct": total_r,
        "usd_effect_pct": usd_r,
        "pure_gold_pct": pure_r,
        "inr_effect_pct": _r(inr, 2),
        "weights": used,
        "badge": BADGE_ARITH,
        "line": (
            f"gold {total_r:+.2f} %: {pure_r:+.2f} % gold, {usd_r:+.2f} % the dollar; rupee {inr:+.2f} %".replace("-", "−")
            if pure_r is not None and inr is not None
            else None
        ),
        # why the split is empty, in words the reader can act on (C-BEGINNER-14): never a developer assertion
        "note": (
            None
            if usd_r is not None
            else "USD effect unavailable: no DXY-basket FX closes stored for this window (the split needs the basket's daily closes)"
        ),
        "inr_note": None if inr is not None else "rupee leg unavailable: no USD/INR daily closes stored for this window",
    }


def build_macro(
    series: dict[str, list[dict[str, Any]]],
    gold_pts: list[dict[str, Any]],
    etf_pts: list[dict[str, Any]],
    fed_rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    mcx_settle: float | None,
    cat: dict[str, dict[str, Any]],
    window: str,
    now: datetime,
) -> dict[str, Any]:
    days = _window_days(window)
    gold_chg = _daily_changes(gold_pts, pct=True)
    keys60 = sorted(gold_chg)[-60:]
    drivers: list[dict[str, Any]] = []
    for key, label, sid, alt, direction, unit in MACRO_DRIVERS:
        used = sid if series.get(sid) else (alt if alt and series.get(alt) else sid)
        # wave 1d (G-DATA's patch, PM decision D6): for a TRUE twin the fresher stored (and published) series wins — Brent's BZ=F
        # front future vs FRED's spot (2–4 d late), the Treasury CSV vs FRED for the yields, Yahoo ^GVZ vs FRED GVZCLS — shown
        # under its own id and date. DXY vs the Fed broad index is not a twin and is excluded on purpose.
        if (key in TRUE_TWINS and alt and series.get(sid) and series.get(alt) and is_published(cat, alt)
                and series[alt][-1]["report_date"] > series[sid][-1]["report_date"]):
            used = alt
        pts = series.get(used) or []
        if pts and not is_published(cat, used):
            pts = []
        if not pts:
            drivers.append(
                {
                    "key": key,
                    "label": label,
                    "value": None,
                    "unit": unit,
                    "series_id": used,
                    "badge": BADGE_CONTEXT,
                    "state": "unavailable",
                }
            )
            continue
        last_p = pts[-1]
        pct_mode = unit in ("index", "₹/$", "$/bbl")
        d1 = (
            _pct_change(last_p["value"], pts[-2]["value"])
            if pct_mode and len(pts) > 1
            else (_diff(last_p["value"], pts[-2]["value"]) if len(pts) > 1 else None)
        )
        d1w = _pct_change(last_p["value"], change_over(pts, 7)[1]) if pct_mode else _diff(last_p["value"], change_over(pts, 7)[1])
        d1m = (
            _pct_change(last_p["value"], change_over(pts, 30)[1]) if pct_mode else _diff(last_p["value"], change_over(pts, 30)[1])
        )
        dwin = (
            _pct_change(last_p["value"], change_over(pts, days)[1])
            if pct_mode
            else _diff(last_p["value"], change_over(pts, days)[1])
        )
        state = freshness(last_p.get("release_at") or last_p["report_date"], max_age_of(cat, used, 5.0), used)["state"]
        tag: str | None = None
        # no supportive / headwind word on a stale driver (5 Nov review: Brent 9 days old tagged SUPPORTIVE after a 20 % fall)
        if direction and dwin and state not in ("stale", "unavailable"):
            tag = "supportive" if dwin * direction > 0 else "headwind"
        vol_index = used in ("GVZ_CLOSE", "FRED_GVZCLS")  # a vol index moves in vol points, not basis points (re-review)
        drivers.append(
            {
                "key": key,
                # the tile is labelled by the series actually used (C-DATA-4 / C-TRADER-8): the Fed broad index is never
                # presented under the DXY name
                "label": DXY_SOURCE_LABEL.get(used, label),
                "label_note": (
                    (f"stand-in: {used} ({sid} has no stored points)" if not series.get(sid)
                     else f"{used}: fresher than {sid} (last {series[sid][-1]['report_date']})")
                    if used != sid else None
                ),
                "value": last_p["value"],
                "unit": unit,
                "report_date": last_p["report_date"],
                "d1": d1,
                "d1w": d1w,
                "d1m": d1m,
                "d_window": dwin,
                "change_unit": "%" if pct_mode else ("vol pts" if vol_index else ("bp" if unit == "%" else unit)),
                "d1_bp": _r(d1 * 100, 1) if d1 is not None and unit == "%" and not vol_index else None,
                "pct_1y": pct_rank(window_values(pts, 365), last_p["value"]),
                "corr_60d": _corr(gold_chg, _daily_changes(pts, pct=pct_mode), keys60),
                "tag": tag,
                "tag_note": "stale: no supportive / headwind word until it is fresh" if direction and state == "stale" else None,
                "rule": (
                    "falling = supportive, rising = headwind"
                    if direction < 0
                    else "rising = supportive"
                    if direction > 0
                    else "size, not direction"
                ),
                "series_id": used,
                "badge": BADGE_CONTEXT,
                "evidence": "contemporaneous (G-MACRO H1/H2); no lead",
                "state": state,
            }
        )
    if etf_pts:
        last_p = etf_pts[-1]
        drivers.append(
            {
                "key": "gld_t",
                "label": "GLD tonnes",
                "value": last_p["value"],
                "unit": "t",
                "report_date": last_p["report_date"],
                "d1": _diff(last_p["value"], etf_pts[-2]["value"]) if len(etf_pts) > 1 else None,
                "d1w": _diff(last_p["value"], change_over(etf_pts, 7)[1]),
                "d1m": _diff(last_p["value"], change_over(etf_pts, 30)[1]),
                "corr_60d": _corr(gold_chg, _daily_changes(etf_pts, pct=False), keys60),
                "tag": None,
                "rule": "contemporaneous; no lead",
                "series_id": "GLD_TONNES",
                "badge": BADGE_CONTEXT,
                "state": "delayed",
            }
        )
    # the KGX window is HEALTH's (week to date since the last Friday close for W, the previous session for D, month to date
    # for M): 'W' printed +0.47 % here from Wed 28 Oct while HEALTH's week said +4.4 % (5 Nov review)
    wa = window_anchor(gold_pts, window, now.date()) if gold_pts else {}
    wa_from = _d(wa.get("from_date"))
    kgx = kgx_split(gold_pts, series, days, wa_from, wa.get("label"))
    currencies: list[dict[str, Any]] = []
    gold_now = gold_pts[-1]["value"] if gold_pts else None
    ccys: list[tuple[str, str | None, bool]] = [
        ("USD", None, True),
        ("INR", "USDINR_CLOSE", True),
        ("EUR", "FX_EURUSD", False),
        ("JPY", "FX_JPY", True),
        ("GBP", "FX_GBPUSD", False),
        ("CNY", "FX_CNY", True),
    ]
    for ccy, fx_sid, per_usd in ccys:
        fxp = series.get(fx_sid) if fx_sid else None
        if fx_sid and not fxp:
            currencies.append({"ccy": ccy, "price": None, "unit": None})
            continue

        def px(days_back: int, _fx: list[dict[str, Any]] | None = fxp, _per_usd: bool = per_usd) -> float | None:
            g = gold_now if days_back == 0 else change_over(gold_pts, days_back)[1]
            if g is None or _fx is None:
                return g
            f = _fx[-1]["value"] if days_back == 0 else change_over(_fx, days_back)[1]
            if not f:
                return None
            return g * f if _per_usd else g / f

        p0 = px(0)
        ytd_anchor = date(now.year - 1, 12, 31)
        g_ytd = _close_on(gold_pts, ytd_anchor)
        f_ytd = _close_on(fxp, ytd_anchor) if fxp else None
        p_ytd = (g_ytd * f_ytd if per_usd else g_ytd / f_ytd) if (g_ytd and f_ytd) else (g_ytd if not fx_sid else None)
        scale = (10 / GRAMS_PER_TROY_OZ) if ccy == "INR" else 1.0
        currencies.append(
            {
                "ccy": ccy,
                "price": _r(p0 * scale, 2) if p0 else None,
                "unit": "₹/10 g (landed, ex-duty)" if ccy == "INR" else f"{ccy}/oz",
                "d1": _pct_change(p0, px(1)),
                "d1w": _pct_change(p0, px(7)),
                "d1m": _pct_change(p0, px(30)),
                "ytd": _pct_change(p0, p_ytd),
                "badge": BADGE_ARITH,
            }
        )
    meetings: list[dict[str, Any]] = []
    fed_sorted = sorted((r for r in fed_rows if _d(r.get("meeting"))), key=lambda r: (str(r.get("as_of")), str(r.get("meeting"))))
    latest_asof = str(fed_sorted[-1].get("as_of"))[:10] if fed_sorted else None
    for r in fed_sorted:
        if str(r.get("as_of"))[:10] == latest_asof and _dd(r["meeting"]) >= now.date() - timedelta(days=1):
            meetings.append(
                {
                    "meeting": str(r["meeting"])[:10],
                    # the tracker's dates are SOFR / IMM horizons (third Wednesdays), NOT FOMC decision days (5 Nov review:
                    # rows dated Wed 16 Dec read like meetings while the next FOMC is 9 Dec); `next_fomc` names the decision
                    "kind": "rate horizon",
                    "label": f"rate path to {_dd(r['meeting']):%a %d %b %Y} (SOFR / IMM horizon, not an FOMC date)",
                    "p_cut": _f(r.get("prob_cut")),
                    "p_hike": _f(r.get("prob_hike")),
                    "p_hold": _f(r.get("prob_hold")),
                    "mean_bp": _f(r.get("rate_mean_bp")),
                    "p10_bp": _f(r.get("p10_bp")),
                    "p90_bp": _f(r.get("p90_bp")),
                }
            )
    # the next FOMC is the next DECISION (statement / rate decision), never a speaker or the minutes (C-TRADER-12 /
    # C-DATA-9: "next FOMC 2026-11-05 19:20" was 'FOMC Member Hammack Speaks'); the Atlanta Fed meeting dates stand in
    # when no decision row is stored; speeches in the next 7 days are listed on their own
    nxt = next_fomc(events, [m["meeting"] for m in meetings], now)
    effr, tgt = latest(series.get("FRED_EFFR") or []), latest(series.get("FRED_DFEDTARU") or [])
    week_end = now.date() + timedelta(days=7)
    speakers = [
        {
            "date": _dd(e["event_date"]).isoformat(),
            "time_ist": str(e.get("time_ist") or "") or None,
            "title": e.get("name"),
            "impact": e.get("impact"),
            "kind": "FOMC_SPEECH",
        }
        for e in sorted(events, key=lambda e: (str(e.get("event_date")), str(e.get("time_ist") or "")))
        if event_kind(e) == "FOMC_SPEECH" and _d(e.get("event_date")) and now.date() <= _dd(e["event_date"]) <= week_end
        and not event_is_past(e, now)
    ]
    fed: dict[str, Any] = {
        "meetings": meetings[:8],
        "meetings_note": "the tracker's rows are rate horizons on SOFR / IMM dates (quarterly third Wednesdays), not FOMC "
        "meeting days — the next FOMC decision is `next_fomc`",
        "as_of": latest_asof,
        "source": "Atlanta Fed Market Probability Tracker (licence: owner reads it, O-10)",
        "zq": [
            {"month": _mmy(p["report_date"]), "implied_pct": _r(100 - p["value"], 3)} for p in (series.get("ZQ_FRONT") or [])[-1:]
        ],
        "effr": effr["value"] if effr else None,
        "effr_date": effr["report_date"] if effr else None,
        "target": f"{tgt['value'] - 0.25:.2f}–{tgt['value']:.2f} %" if tgt else None,
        "next_fomc_ist": nxt["ist"] if nxt else None,
        "after_mcx_close": nxt["after_mcx_close"] if nxt else None,
        "next_fomc": nxt,
        "speakers": speakers,
        "badge": BADGE_CONTEXT,
        "fedwatch_link": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",  # link-only
    }
    calendar: list[dict[str, Any]] = []
    for e in sorted(events, key=lambda e: (str(e.get("event_date")), str(e.get("time_ist") or ""))):
        d = _d(e.get("event_date"))
        if not d or d < now.date() or d > week_end or event_is_past(e, now):  # a release already out is not "next" (C-DATA-21)
            continue
        t = str(e.get("time_ist") or "")
        calendar.append(
            {
                "date": d.isoformat(),
                "time_ist": t or None,
                "title": e.get("name"),
                "kind": event_kind(e),
                "country": e.get("country"),
                "impact": e.get("impact"),
                "impact_rank": impact_rank(e),
                "star": event_star(e),
                "forecast": e.get("forecast"),
                "previous": e.get("previous"),
                "actual": e.get("actual"),
                "in_session": e.get("in_session") if e.get("in_session") is not None else (bool(t) and "09:00" <= t <= "23:55"),
                "days": (d - now.date()).days,
            }
        )
    gvz = latest(series.get("GVZ_CLOSE") or series.get("FRED_GVZCLS") or [])
    sigma = gvz["value"] / math.sqrt(252) if gvz else None
    inr = latest(series.get("USDINR_CLOSE") or [])
    inr_10g = (
        (sigma / 100) * mcx_settle
        if sigma is not None and mcx_settle
        else ((sigma / 100) * gp.landed_inr_per_10g(gold_now, inr["value"]) if sigma is not None and gold_now and inr else None)
    )
    rets = [gold_chg[k] for k in sorted(gold_chg)[-20:]]
    realised = round(statistics.pstdev(rets) * math.sqrt(252), 2) if len(rets) >= 10 else None
    atr_usd = None
    if len(gold_pts) >= 15 and all(k in gold_pts[-1] for k in ("high", "low")):
        trs = []
        for a, b in zip(gold_pts[-15:], gold_pts[-14:]):
            if b.get("high") is not None and b.get("low") is not None and a.get("value") is not None:
                trs.append(max(b["high"] - b["low"], abs(b["high"] - a["value"]), abs(b["low"] - a["value"])))
        atr_usd = statistics.fmean(trs) if trs else None
    atr_inr = _r(gp.landed_inr_per_10g(atr_usd, inr["value"]) * (1 + gp.duty_rate()["pct"] / 100), 0) if atr_usd and inr else None
    move = {
        "gvz": gvz["value"] if gvz else None,
        "gvz_date": gvz["report_date"] if gvz else None,
        "sigma_day_pct": _r(sigma, 3),
        "usd_oz": _r(sigma / 100 * gold_now, 1) if sigma is not None and gold_now else None,
        "inr_10g": _r(inr_10g, 0),
        "per_lot": {
            code: _r(inr_10g * spec.multiplier * spec.quote_per_grams / 10, 0) if inr_10g else None
            for code, spec in mcxr.contract_specs().items()
        },
        "realised_20d": realised,
        "atr14_usd": _r(atr_usd, 2),
        "atr14_inr": atr_inr,
        "read": "how big a normal day is, in rupees per lot — sizing arithmetic, no view on direction",
        "badge": BADGE_ARITH,
    }
    ry_pts = series.get("FRED_DFII10") or series.get("UST_REAL_10Y") or []
    dxy_series = "DXY_CLOSE" if series.get("DXY_CLOSE") else ("FRED_DTWEXBGS" if series.get("FRED_DTWEXBGS") else None)
    dxy_pts = (series.get(dxy_series) or []) if dxy_series else []
    ry_chg, dxy_chg = _daily_changes(ry_pts, pct=False), _daily_changes(dxy_pts, pct=True)
    years = sorted({k[:4] for k in gold_chg})
    rolling = [
        {
            "year": y,
            "real_yield": _corr(gold_chg, ry_chg, [k for k in gold_chg if k.startswith(y)]),
            "dxy": _corr(gold_chg, dxy_chg, [k for k in gold_chg if k.startswith(y)]),
        }
        for y in years[-12:]
    ]
    wk_gold = _daily_changes(resample_points(gold_pts, "W"), pct=True)
    wk_ry = _daily_changes(resample_points(ry_pts, "W"), pct=False)
    wk_dxy = _daily_changes(resample_points(dxy_pts, "W"), pct=True)
    betas: list[dict[str, Any]] = []
    for name, lo, hi in REGIMES:
        keys = [k for k in wk_gold if lo <= int(k[:4]) <= hi]
        b_ry = _beta(wk_gold, wk_ry, keys)
        betas.append({"regime": name, "beta_real_yield_per_100bp": _r(b_ry * 100, 2) if b_ry is not None else None,
                      "beta_dxy": _beta(wk_gold, wk_dxy, keys)})
    si = series.get("COMEX_SI_FRONT") or []
    gsr_series = (
        [
            {"report_date": p["report_date"], "value": p["value"] / s}
            for p in gold_pts
            if (s := _close_on(si, _d(p["report_date"])))
        ]
        if si
        else []
    )
    gpr_m, gpr_d, hy = series.get("GPR_MONTHLY") or [], series.get("GPR_DAILY") or [], latest(series.get("FRED_HY_OAS") or [])
    m2 = series.get("FRED_M2SL") or []
    gm2 = [
        {"report_date": p["report_date"], "value": p["value"] / m}
        for p in resample_points(gold_pts, "M")
        if (m := _close_on(m2, _d(p["report_date"])))
    ]
    context = {
        "gsr": _r(gsr_series[-1]["value"], 2) if gsr_series else None,
        "gsr_pct": pct_rank([p["value"] for p in gsr_series], gsr_series[-1]["value"]) if gsr_series else None,
        "gpr_m": gpr_m[-1]["value"] if gpr_m else None,
        "gpr_pct_m": pct_rank([p["value"] for p in gpr_m], gpr_m[-1]["value"]) if gpr_m else None,
        "gpr_pct_d": pct_rank([p["value"] for p in gpr_d], gpr_d[-1]["value"]) if gpr_d else None,
        "hy_oas": hy["value"] if hy else None,
        "hy_oas_unit": "%",  # FRED BAMLH0A0HYM2 is in percent (3.40 = 340 bp); 5 Nov review: labelled '(bp)'
        "hy_oas_bp": _r(hy["value"] * 100, 0) if hy else None,
        "hy_oas_date": hy["report_date"] if hy else None,
        "gold_m2_pct": pct_rank([p["value"] for p in gm2], gm2[-1]["value"]) if gm2 else None,
        "badge": BADGE_CONTEXT,
    }
    return {
        "as_of": now.isoformat(timespec="seconds"),
        "window": window,
        "drivers": drivers,
        "kgx": kgx,
        "currencies": currencies,
        "fed": fed,
        "calendar": calendar,
        "move": move,
        "driver_health": {
            "rolling_corr": rolling,
            "betas_by_regime": betas,
            "beta_units": {  # the raw keys carry their units (C-DATA-21)
                "beta_real_yield_per_100bp": "% gold per +100 bp in the 10-y real yield (weekly changes)",
                "beta_dxy": f"% gold per +1 % in {DXY_SOURCE_LABEL.get(dxy_series or '', 'the dollar index')} (weekly changes)",
                "rolling_corr": "correlation of daily changes within the year",
            },
            "dxy_series": dxy_series,
            "lesson": "since 2022 the real-yield rule explains a third of what it used to; the dollar never stopped working "
            "(G-MACRO H1)",
        },
        "context": context,
        "badge": BADGE_CONTEXT,
        "freshness": {
            "drivers": freshness(
                max((d.get("report_date") or "" for d in drivers), default=None) or None, 5.0, "FRED / Treasury / Yahoo (stored)"
            ),
            "fed": freshness(latest_asof, 5.0, "Atlanta Fed"),
            "gold": freshness(gold_pts[-1]["report_date"] if gold_pts else None, 4.0, "Yahoo GC=F (stored)"),
        },
    }


@router.get("/macro")
async def gold_macro(window: str = Query("D", pattern="^[DWMdwm]$"), response: Response = None) -> dict[str, Any]:  # type: ignore[assignment]
    """MACRO: the driver strip with supportive/headwind tags (rule shown), the KGX split, gold in six currencies, the Fed path,
    this week's US calendar in IST, the expected move in ₹ per lot, driver health by regime and the collapsed context."""
    reads = Reads()
    now = _now_ist()
    cat = await catalog(reads)
    ids = [sid for _, _, sid, alt, _, _ in MACRO_DRIVERS for sid in (sid, alt) if sid]
    ids += list(DXY_WEIGHTS) + [
        "USDINR_CLOSE",
        "FX_CNY",
        "FRED_EFFR",
        "FRED_DFEDTARU",
        "ZQ_FRONT",
        "COMEX_SI_FRONT",
        "GPR_MONTHLY",
        "GPR_DAILY",
        "FRED_HY_OAS",
        "FRED_M2SL",
    ]
    long_from = (now.date() - timedelta(days=365 * 10)).isoformat()
    series_t, bars_t, etf_t, fed_t, events_t, master_t = await _gather(
        fetch_series(reads, sorted(set(ids)), days=365 * 10),
        reads.get("/db/gold/bars", symbol=GC_FRONT, interval="1d", **{"from": long_from}),
        reads.get("/db/gold/etf", **{"from": (now.date() - timedelta(days=120)).isoformat()}),
        reads.get("/db/gold/fed-path"),
        reads.get("/db/gold/events", **{"from": now.date().isoformat()}, to=(now.date() + timedelta(days=60)).isoformat()),
        asyncio.to_thread(mcxr._master_gold_family),
        )
    settle = None
    if isinstance(master_t, tuple):
        front = next((r for r in master_t[0].get("GOLD", []) if r["expiry"] >= now.date()), None)
        if front:  # the expected move in ₹ scales the latest settlement (VWAP30 when read, else the band of its real session)
            blk = await mcxr.resolve_settlement("GOLD", front["expiry"], front, master_t[1], now, wait=False)
            settle = blk.get("settlement")
    stored_events = _rows(events_t) if not isinstance(events_t, Exception) else []
    etf_rows = (
        [r for r in _rows(etf_t) if str(r.get("fund") or "GLD").upper() == "GLD"] if not isinstance(etf_t, Exception) else []
    )
    payload = build_macro(
        series_t if isinstance(series_t, dict) else {},
        _closes_from_bars(bars_t) if not isinstance(bars_t, Exception) else [],
        _points(etf_rows, value_key="tonnes"),
        _rows(fed_t) if not isinstance(fed_t, Exception) else [],
        merge_events(stored_events, []),   # one row per event, MCX expiries at the session close (5 Nov review)
        settle,
        cat,
        window.upper(),
        now,
    )
    payload["store_errors"] = reads.errors or None
    reads.headers(response)
    return payload


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /calendar · GET/POST /log · GET /catalog · GET /brief · LEARN
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


# ── event kinds, stars and the FOMC decision (critics C-TRADER-11 / C-TRADER-12 / C-DATA-9 / C-DATA-21) ─────────────────
# data-service tags every Forex-Factory title matching "FOMC" as kind FOMC — the statement, the minutes AND every
# 'FOMC Member X Speaks'. The page separates them: a speech is kind FOMC_SPEECH, the minutes FOMC_MINUTES; only the
# decision keeps FOMC. ★ = High impact or an FOMC decision; `impact_rank` orders the strip (decision/High first).
FOMC_SPEECH_RE = re.compile(r"\b(speaks?|speech|speeches|remarks|testif\w*|member|press conference)\b", re.IGNORECASE)
FOMC_MINUTES_RE = re.compile(r"\bminutes\b", re.IGNORECASE)
IMPACT_RANK: dict[str, int] = {"high": 0, "roll": 1, "medium": 2, "closed": 2, "session": 3, "context": 3, "low": 4}


def event_kind(e: dict[str, Any]) -> str:
    kind = str(e.get("kind") or "").upper()
    name = str(e.get("name") or e.get("title") or "")
    if kind == "FOMC":
        if FOMC_MINUTES_RE.search(name):
            return "FOMC_MINUTES"
        if FOMC_SPEECH_RE.search(name):
            return "FOMC_SPEECH"
    return kind


def is_fomc_decision(e: dict[str, Any]) -> bool:
    return event_kind(e) == "FOMC"


def event_star(e: dict[str, Any]) -> bool:
    return str(e.get("impact") or "").lower() == "high" or is_fomc_decision(e)


def impact_rank(e: dict[str, Any]) -> int:
    if is_fomc_decision(e):
        return 0
    return IMPACT_RANK.get(str(e.get("impact") or "").lower(), 5)


def event_is_past(e: dict[str, Any], now: datetime) -> bool:
    """A dated row earlier than today, or today's row whose IST time has passed (a release already out is not 'next')."""
    d = _d(e.get("event_date") or e.get("date"))
    if d is None:
        return False
    if d != now.astimezone(IST).date():
        return d < now.astimezone(IST).date()
    t = str(e.get("time_ist") or "")[:5]
    return bool(t) and t < now.astimezone(IST).strftime("%H:%M")


def decorate_event(e: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The row with its page kind, `kind_stored` when relabelled, `star`, `impact_rank` and `past`."""
    kind = event_kind(e)
    stored = str(e.get("kind") or "").upper()
    return {
        **e,
        "kind": kind,
        "kind_stored": stored if stored and stored != kind else None,
        "star": event_star(e),
        "impact_rank": impact_rank(e),
        "past": event_is_past(e, now),
    }


def fomc_statement_ist(et_day: date) -> datetime:
    """The FOMC statement is 14:00 ET on the decision day: 23:30 IST in summer, 00:30 IST the next day in winter."""
    return datetime(et_day.year, et_day.month, et_day.day, 14, 0, tzinfo=NY).astimezone(IST)


# FOMC decision days (the second day of each two-day meeting, ET), from the Federal Reserve's published calendars; the Atlanta
# Fed tracker's "meetings" are SOFR/IMM horizons (quarterly third Wednesdays), NOT decisions (re-review C-DATA-9 /
# C-TRADER-12: "next FOMC 2026-12-17" vs the 9 Dec decision). Extend each December when the Fed publishes the next year.
FOMC_DECISION_DAYS_ET: tuple[str, ...] = (
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
)


def next_fomc(events: list[dict[str, Any]], meeting_dates: list[str], now: datetime) -> dict[str, Any] | None:
    """The next FOMC DECISION: the first stored decision row at or after now (the 'Federal Funds Rate' row wins on a day with
    several), else the first Atlanta-Fed meeting date at or after today with the statement time computed. None when neither
    is known. `ist` is the page's label (`YYYY-MM-DD HH:MM IST`); `at` / `statement_ist` carry the offset."""
    rows = sorted(
        (e for e in events if is_fomc_decision(e) and _d(e.get("event_date")) and not event_is_past(e, now)),
        key=lambda e: (str(e.get("event_date")), 0 if "funds rate" in str(e.get("name") or "").lower() else 1, str(e.get("time_ist") or "")),
    )
    if rows:
        e = rows[0]
        d, t = _dd(e["event_date"]), str(e.get("time_ist") or "")[:5]
        at = datetime(d.year, d.month, d.day, int(t[:2]), int(t[3:5]), tzinfo=IST) if len(t) == 5 and t[2] == ":" else None
        et_day = at.astimezone(NY).date() if at else d
        statement = at or fomc_statement_ist(et_day)
        source = "gold_events"
        name = e.get("name")
    else:
        today_et = now.astimezone(NY).date()
        published = [d for d in FOMC_DECISION_DAYS_ET if _dd(d) >= today_et]
        if published:
            et_day = _dd(published[0])
            source = "Federal Reserve FOMC calendar (statement time computed)"
        else:
            future = sorted(m for m in meeting_dates if _d(m) and _dd(m) >= now.date())
            if not future:
                return None
            et_day = _dd(future[0])
            source = "Atlanta Fed meeting dates (statement time computed; the published FOMC calendar needs extending)"
        statement = fomc_statement_ist(et_day)
        name = "FOMC statement"
    return {
        "date_et": et_day.isoformat(),
        "ist": f"{statement.date().isoformat()} {statement:%H:%M} IST",
        "at": statement.isoformat(timespec="minutes"),
        "statement_ist": statement.isoformat(timespec="minutes"),
        "name": name,
        "kind": "FOMC",
        "source": source,
        "after_mcx_close": statement.time() >= dtime_(23, 30) or statement.time() < dtime_(9, 0),
        "days": (statement.date() - now.astimezone(IST).date()).days,
    }


def event_dedupe_key(e: dict[str, Any]) -> tuple[str, ...]:
    """One row per real event (re-review minor: the COT release listed twice — 'CFTC COT (positions as of Tue 03 Nov)' stored
    and 'CFTC COT release (Tue 03 Nov positions)' computed — because the dedupe compared names): a COT release is one per
    (date, time); everything else per (date, kind, name)."""
    d = str(e.get("event_date") or e.get("date") or "")[:10]
    kind = str(e.get("kind") or "").upper()
    if kind in ("COT_RELEASE", "COT"):
        return (d, "COT_RELEASE", str(e.get("time_ist") or "")[:5])
    return (d, kind, str(e.get("name") or "").lower())


def mcx_expiry_time(e: dict[str, Any]) -> dict[str, Any]:
    """An MCX expiry row timed at THAT day's session close (23:55 while New York is on standard time, 23:30 in summer,
    17:00 on an evening closure) — never a flat 23:30 (5 Nov review: 'GOLDM Nov-26 expiry 23:30' on a 23:55 evening)."""
    if str(e.get("kind") or "").upper() != "MCX_EXPIRY":
        return e
    d = _d(e.get("event_date") or e.get("date"))
    if d is None:
        return e
    close = gp.session_close_at(d)
    return {**e, "time_ist": f"{close:%H:%M}", "time_note": "the session close that day (expiry is end of trading)"}


def merge_events(stored: list[dict[str, Any]], computed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stored rows first (they win), then the computed ones not already there, deduped by `event_dedupe_key`; MCX expiries
    re-timed to the session close."""
    seen: set[tuple[str, ...]] = set()
    out: list[dict[str, Any]] = []
    for e in stored + computed:
        if not _d(e.get("event_date") or e.get("date")):
            continue
        e2 = mcx_expiry_time(e)
        k = event_dedupe_key(e2)
        if k in seen:
            continue
        seen.add(k)
        out.append(e2)
    return out


def computed_events(today: date, days: int) -> list[dict[str, Any]]:
    """Rows the store may not carry yet: MCX expiries per family, MCX holidays, the next COT release (rule) and the Muhurat
    session."""
    out: list[dict[str, Any]] = []
    horizon = today + timedelta(days=days)
    for code in mcxr.contract_specs():
        for e in mcxr.active_expiries(code, today, count=3):
            if e <= horizon:
                out.append(
                    {
                        "event_date": e.isoformat(),
                        "time_ist": f"{gp.session_close_at(e):%H:%M}",
                        "kind": "MCX_EXPIRY",
                        "name": f"MCX {code} {_mmy(e)} expiry",
                        "country": "IN",
                        "impact": "roll",
                        "in_session": True,
                        "source": "shared/mcx_specs (computed)",
                    }
                )
    for h in specs.upcoming_holidays(today, count=12):
        if _dd(h["date"]) <= horizon:
            out.append(
                {
                    "event_date": h["date"],
                    "time_ist": None,
                    "kind": "MCX_HOLIDAY",
                    "name": f"MCX {h['closure']} closure: {h['name']}",
                    "country": "IN",
                    "impact": "closed",
                    "in_session": False,
                    "source": "shared/mcx_specs",
                }
            )
    for s in specs.SPECIAL_SESSIONS_2026:
        if today <= _dd(s["date"]) <= horizon:
            out.append(
                {
                    "event_date": s["date"],
                    "time_ist": None,
                    "kind": "MCX_SPECIAL",
                    "name": s["name"],
                    "detail": s["note"],
                    "country": "IN",
                    "impact": "session",
                    "in_session": True,
                    "source": "shared/mcx_specs",
                }
            )
    tue = today - timedelta(days=(today.weekday() - 1) % 7)
    for k in range(-1, max(6, days // 7 + 2)):
        rd = tue + timedelta(days=7 * k)
        rel = cot_release_at_ist(rd)
        rel_date, rel_source = cot_release_date(rd)
        if today <= rel.date() <= horizon:
            out.append(
                {
                    "event_date": rel.date().isoformat(),
                    "time_ist": rel.strftime("%H:%M"),
                    "kind": "COT_RELEASE",
                    "name": f"CFTC COT release (Tue {rd:%d %b} positions)",
                    "detail": (
                        f"{rel_date:%a %d %b} 15:30 ET = {cot_release_label(rel)}"
                        + (" — the Monday after a US federal holiday" if rel_date.weekday() == 0 else "")
                    ),
                    "country": "US",
                    "impact": "context",
                    "in_session": False,
                    "source": (
                        "CFTC published 2026 schedule"
                        if rel_source == "published"
                        else "rule: Friday 15:30 ET, the Monday after a US federal holiday (the store's row wins once ingested)"
                    ),
                }
            )
    return out


@router.get("/calendar")
async def gold_calendar(days: int = Query(30, ge=1, le=365), response: Response = None) -> dict[str, Any]:  # type: ignore[assignment]
    """gold_events rows for the next `days` (FOMC, US releases, COT releases, COMEX FND/LTD, MCX expiries and holidays, Indian
    festivals) merged with the computed MCX / COT rows, each with `days` and `in_session`."""
    reads = Reads()
    now = _now_ist()
    stored = _rows(
        await reads.get("/db/gold/events", **{"from": now.date().isoformat()}, to=(now.date() + timedelta(days=days)).isoformat())
    )
    events: list[dict[str, Any]] = []
    for e in merge_events(stored, computed_events(now.date(), days)):
        d = _dd(e.get("event_date"))
        t = str(e.get("time_ist") or "") or None
        in_session = e.get("in_session") if e.get("in_session") is not None else (bool(t) and "09:00" <= (t or "") <= "23:55")
        events.append(
            decorate_event(
                {
                    **e,
                    "event_date": d.isoformat(),
                    "date": d.isoformat(),
                    "time_ist": t,
                    "first_seen_at": _iso_any(e.get("first_seen_at")),
                    "days": (d - now.date()).days,
                    "in_session": in_session,
                    "after_close": bool(t) and (t or "") > "23:30",
                },
                now,
            )
        )
    events.sort(key=lambda e: (e["event_date"], e.get("time_ist") or ""))
    payload = {
        "as_of": now.isoformat(timespec="seconds"),
        "days": days,
        "events": events,
        "count": len(events),
        "badge": BADGE_ARITH,
        "freshness": freshness(now.isoformat(), None, "data-service gold_events + computed rows", live=bool(stored)),
        "store_errors": reads.errors or None,
    }
    reads.headers(response)
    return payload


@router.get("/log")
async def gold_log(days: int = Query(60, ge=1, le=400), threshold: float = Query(300, gt=0)) -> dict[str, Any]:
    """The pre-open accuracy log (h.accuracy): rows with `stale_baseline` and `inputs_json`, and the stats. The JSON log stays
    the source of truth for one release while every row is dual-written to data-service's gold_preopen_log."""
    rows = await asyncio.to_thread(gp.log_rows, days, True)
    stats = gp.accuracy_stats(rows, threshold)
    return {
        "rows": rows,
        "stats": {**stats, "p90": stats.get("p90_abs_error")},
        "badge": BADGE_ARITH,
        "source": "data/gold_preopen/log.json (dual-written to gold_preopen_log)",
        "read": "need ≈ 20 rows before the ₹300 chase limit means anything. A stale-baseline row used a settlement that was not "
        "the one it was labelled with: until 5 Nov every row took the ICICI band of the session BEFORE its label (`band_rule`, "
        "no broker read needed), and the 0.6 % check against that session's last-30-min VWAP measures how much it mattered "
        "(`stale_reasons`): its miss holds a whole session's gold move. Rows keep their recorded numbers; "
        "`stats.excluding_stale` repeats the stats without them; `re_explained` / `stats.on_vwap30` are a counterfactual on the "
        "VWAP of the labelled session — beside the score, never instead of it.",
    }


@router.post("/log/actual")
async def gold_log_actual(payload: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    """Manual entry of the MCX GOLD open for a day: {date, open} (PAPER: a log row, never an order)."""
    return await asyncio.to_thread(gp.gold_set_actual, payload)


@router.get("/catalog")
async def gold_catalog(response: Response = None) -> dict[str, Any]:  # type: ignore[assignment]
    """gold_series_catalog rows (the data dictionary behind every 'about' popover and the rendering gate); 1 h TTL."""
    reads = Reads()
    cat = await catalog(reads)
    rows = sorted(cat.values(), key=lambda r: str(r.get("series_id")))
    reads.headers(response)
    return {
        "as_of": _now_ist().isoformat(timespec="seconds"),
        "rows": rows,
        "count": len(rows),
        "verdicts": {
            v: sum(1 for r in rows if r.get("verdict") == v)
            for v in ("PUBLISH-CORE", "PUBLISH-CONTEXT", "LINK-ONLY", "DO-NOT-PUBLISH")
        },
        "badges": {b: sum(1 for r in rows if r.get("badge") == b) for b in ("signal", "context", "arithmetic", "heuristic")},
        "store_errors": reads.errors or None,
    }


@router.get("/brief")
async def gold_brief(date_: str | None = Query(None, alias="date"), response: Response = None) -> dict[str, Any]:  # type: ignore[assignment]
    """The stored automated brief for a day (gold_brief_docs) with its data_quality block; `available: false` when none."""
    reads = Reads()
    day = _date_arg(date_, "date")
    payload = await reads.get("/db/gold/brief", date=day.isoformat() if day else None)
    rows = _brief_rows(payload)
    reads.headers(response)
    if not rows:
        return {
            "available": False,
            "report_date": day.isoformat() if day else None,
            "doc": None,
            "data_quality": None,
            "note": "no brief stored for that day (the 09:05 gold_brief_ingest job)",
            "store_errors": reads.errors or None,
        }
    r = max(rows, key=lambda x: str(x.get("report_date") or ""))
    doc, stripped = brief_doc(r)
    bb = brief_bias(r, doc)
    return {
        "available": True,
        "report_date": str(r.get("report_date"))[:10],
        "generated_at": _iso_any(r.get("generated_at")),
        "bias": bb["bias"],
        "bias_score": _f(r.get("bias_score")) if bb["bias"] is not None else None,
        "confidence": bb["confidence"],
        "bias_withheld": bb["bias_withheld"],
        "model_fair_open": _f(r.get("model_fair_open")),
        "overnight_summary": doc.get("overnight_summary"),
        "open_plan": doc.get("open_plan"),
        "key_risks_today": doc.get("key_risks_today") or [],
        "doc": doc,
        "data_quality": doc.get("data_quality"),
        "stripped_fields": stripped,
        "label": (f"automated brief, confidence {bb['confidence']}" if bb["bias"] is not None
                  else "automated brief, empty for this date"),
        "badge": BADGE_CONTEXT,
        "store_errors": reads.errors or None,
    }


# the brief is a CONTEXT panel: no field that implies a trade leaves the server (C-TRADER-15 — the stored document carries
# `open_signal: aligned_tradeable`). Keys matching this pattern are dropped at every depth and listed in `stripped_fields`.
TRADE_FIELD_RE = re.compile(r"signal|trade|entry|exit|stop_?loss|target|recommend|position_siz", re.IGNORECASE)


def scrub_trade_fields(obj: Any, path: str = "doc", found: list[str] | None = None) -> tuple[Any, list[str]]:
    """`obj` without any key whose name implies a trade, at every depth; the dropped paths in order."""
    found = [] if found is None else found
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if TRADE_FIELD_RE.search(str(k)):
                found.append(f"{path}.{k}")
                continue
            out[k] = scrub_trade_fields(v, f"{path}.{k}", found)[0]
        return out, found
    if isinstance(obj, list):
        return [scrub_trade_fields(v, f"{path}[{i}]", found)[0] for i, v in enumerate(obj)], found
    return obj, found


# Trade-implying PROSE (re-review C-DATA-2 N8: doc.open_plan read 'Open signal is aligned_tradeable (deviation ~-100 vs a 300
# threshold), so no wait is required'): a sentence carrying one of these words leaves the document, its path listed.
TRADE_PROSE_RE = re.compile(r"aligned_tradeable|\btradeable\b|\bopen signal\b|\bsignal\b|\bno wait is required\b", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def scrub_trade_prose(obj: Any, path: str = "doc", found: list[str] | None = None) -> tuple[Any, list[str]]:
    """`obj` with every sentence that implies a trade dropped from its strings (at every depth); the touched paths."""
    found = [] if found is None else found
    if isinstance(obj, dict):
        return {k: scrub_trade_prose(v, f"{path}.{k}", found)[0] for k, v in obj.items()}, found
    if isinstance(obj, list):
        return [scrub_trade_prose(v, f"{path}[{i}]", found)[0] for i, v in enumerate(obj)], found
    if isinstance(obj, str) and TRADE_PROSE_RE.search(obj):
        kept = [s for s in _SENTENCE_RE.split(obj) if not TRADE_PROSE_RE.search(s)]
        found.append(f"{path} (sentence)")
        return " ".join(kept).strip() or None, found
    return obj, found


def brief_doc(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The brief document of a stored row (JSON text or object), scrubbed of trade-implying keys AND sentences; the row's own
    trade-implying columns count too."""
    doc = row.get("doc")
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except ValueError:
            doc = {"raw": doc}
    doc = doc if isinstance(doc, dict) else {}
    clean, found = scrub_trade_fields(doc)
    clean, found = scrub_trade_prose(clean, "doc", found)
    found += [f"row.{k}" for k in row if TRADE_FIELD_RE.search(str(k)) and row.get(k) is not None]
    return clean, found


BRIEF_EMPTY_NOTE = "the document carries no summary, plan or risk list: no bias or confidence is shown for an empty brief"


def brief_bias(row: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """{bias, confidence, bias_withheld}: an EMPTY brief (no summary, plan or risks) prints no directional word (5 Nov review:
    'bias bullish · confidence 50 % · The document carries no summary, plan or risk list')."""
    has_body = bool(doc.get("overnight_summary") or doc.get("open_plan") or doc.get("key_risks_today"))
    if not has_body:
        return {"bias": None, "confidence": None, "bias_withheld": BRIEF_EMPTY_NOTE}
    return {"bias": row.get("bias"), "confidence": _f(row.get("confidence")), "bias_withheld": None}


def _brief_rows(payload: Any) -> list[dict[str, Any]]:
    """Brief rows from data-service's `{available, report_date, row, doc}` (B1 reads.brief) or a plain rows list."""
    if isinstance(payload, dict) and isinstance(payload.get("row"), dict):
        row = dict(payload["row"])
        if payload.get("doc") is not None and row.get("doc") is None:
            row["doc"] = payload["doc"]
        return [row]
    return _rows(payload)


def learn_dir() -> Path:
    env = os.environ.get("GOLD_LEARN_DIR", "").strip()
    if env:
        return Path(env)
    root = Path(__file__).resolve().parents[3]
    ui_copy = root / "ui" / "lib" / "gold"
    return ui_copy if (ui_copy / "glossary.json").is_file() else LEARN_DIR_DEFAULT


def _load_learn(name: str) -> dict[str, Any]:
    """glossary.json / tooltips.json (B5's copy under ui/lib/gold, else the G-EDU original), cached 1 h. Blocking: to_thread."""
    key = f"learn:{name}"
    hit = _ttl.get(key)
    if hit is not None:
        return hit
    path = learn_dir() / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["_path"] = str(path)
    _ttl.set(key, data, ttl=LEARN_TTL_S)
    return data


def search_glossary(terms: list[dict[str, Any]], q: str, limit: int = 40) -> list[dict[str, Any]]:
    """Ranked like ui/lib/gold/learn.ts: exact → starts with → contains → short contains → long contains; empty q =
    alphabetical."""
    needle = (q or "").strip().lower()
    ordered = sorted(terms, key=lambda t: str(t.get("term", "")).lower())
    if not needle:
        return ordered[:limit]

    def rank(t: dict[str, Any]) -> int:
        term = str(t.get("term", "")).lower()
        if term == needle:
            return 0
        if term.startswith(needle):
            return 1
        if needle in term:
            return 2
        if needle in str(t.get("short", "")).lower():
            return 3
        if needle in str(t.get("long", "")).lower():
            return 4
        return 9

    scored = [(rank(t), t) for t in ordered]
    return [t for r, t in sorted(scored, key=lambda x: x[0]) if r < 9][:limit]


@router.get("/learn/glossary")
async def gold_glossary(q: str | None = Query(None, max_length=80), limit: int = Query(40, ge=1, le=400)) -> dict[str, Any]:
    data = await asyncio.to_thread(_load_learn, "glossary")
    terms = [t for t in (data.get("terms") or []) if isinstance(t, dict) and t.get("term")]
    have = {t["term"] for t in terms}
    dangling = sorted({s for t in terms for s in (t.get("see_also") or []) if s not in have})
    return {
        "version": data.get("version"),
        "count": len(terms),
        "query": q,
        "terms": search_glossary(terms, q or "", limit),
        "dangling_see_also": dangling,
        "source": data.get("_path"),
    }


@router.get("/learn/tooltips")
async def gold_tooltips() -> dict[str, Any]:
    data = await asyncio.to_thread(_load_learn, "tooltips")
    tips = (
        {k: v for k, v in (data.get("tooltips") or {}).items() if isinstance(v, str)}
        if isinstance(data.get("tooltips"), dict)
        else {
            k: v
            for k, v in data.items()
            if isinstance(v, str) and not k.startswith("_") and k not in ("version", "agent", "note")
        }
    )
    return {
        "version": data.get("version"),
        "count": len(tips),
        "panels": data.get("panels") or [],
        "tooltips": tips,
        "source": data.get("_path"),
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# POST /snapshot · POST /capture-open · POST /invalidate
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


@router.post("/snapshot")
async def gold_snapshot(force: bool = Query(False)) -> dict[str, Any]:
    """Today's 08:45 prediction (alias of /api/commodity/gold-preopen/snapshot; MCX-holiday aware; dual-written)."""
    return await gp.gold_snapshot(force=force)


@router.post("/capture-open")
async def gold_capture_open() -> dict[str, Any]:
    """Today's actual open from Breeze (alias of /api/commodity/gold-preopen/capture-open; 17:10 on a morning closure)."""
    return await gp.gold_capture_open()


@router.post("/invalidate")
async def gold_invalidate(what: str = Query("all", pattern="^(all|store|memo)$")) -> dict[str, Any]:
    """Drop the stored-read SWR cache and the memoised payloads after an ingest (master-controller calls it; loopback only
    by construction — ui-api binds 127.0.0.1 and the Host guard refuses anything else)."""
    before = {"store": len(STORE), "memo": len(_ttl)}
    if what in ("all", "store"):
        STORE.invalidate()
    if what in ("all", "memo"):
        _ttl.clear()
    _log.info(json.dumps({"event": "gold_cache_invalidated", "what": what, **before}))
    return {"invalidated": what, "before": before, "at": _now_ist().isoformat(timespec="seconds")}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# GET /overview — the page frame: contract, session, the five-number strip, health, fair, quote, headlines, brief, calendar
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def comex_session(now: datetime) -> dict[str, Any]:
    """CME Globex metals: Sun 18:00 → Fri 17:00 ET with a 17:00–18:00 ET maintenance hour each day."""
    ny = now.astimezone(NY)
    wd, t = ny.weekday(), ny.time()
    if wd == 5 or (wd == 6 and t < dtime_(18, 0)) or (wd == 4 and t >= dtime_(17, 0)):
        return {"is_open": False, "note": "weekend close (reopens Sunday 18:00 ET)"}
    if dtime_(17, 0) <= t < dtime_(18, 0):
        return {"is_open": False, "note": "daily maintenance hour 17:00–18:00 ET"}
    return {"is_open": True, "note": "Globex electronic session (nearly 23 h)"}


def dtime_(hh: int, mm: int):
    from datetime import time as _t

    return _t(hh, mm)


async def build_overview(contract: str, expiry: str | None, window: str) -> dict[str, Any]:
    now = _now_ist()
    code = contract.upper()
    if code not in mcxr.contract_specs():
        fail(422, "invalid", f"Unknown MCX contract '{contract}'", hint=f"One of {', '.join(mcxr.contract_specs())}")
    reads = Reads()
    health_t, fair_t, quote_t, brief_t, events_t, series_t, cot_t, curve_t = await _gather(
        build_health(window, code, expiry),   # the page's contract: ONE basis per clock on strip, gauge and verdict (wave 1d)
        build_fair(None, None, 300.0, None, code if code != "GOLD" else None, expiry),
        asyncio.wait_for(mcxr.mcx_quote(contract=code, expiry=expiry), 12.0),
        reads.get("/db/gold/brief"),
        reads.get("/db/gold/events", **{"from": now.date().isoformat()}, to=(now.date() + timedelta(days=7)).isoformat()),
        fetch_series(reads, ["FRED_DFII10", "UST_REAL_10Y", "XAU_CROSSCHECK", "USDINR_CLOSE"], days=30),
        reads.get("/db/gold/cot", weeks=2, report="disagg", fut_or_combined="F"),
        reads.get("/db/gold/curve", exchange="COMEX"),  # the matched month's own stored price for the strip (C-TRADER-9)
    )
    health = health_t if isinstance(health_t, dict) else None
    fair = fair_t if isinstance(fair_t, dict) else None
    quote: dict[str, Any] = (
        quote_t if isinstance(quote_t, dict) else {"available": False, "reason": f"quote path {type(quote_t).__name__}"}
    )
    series = series_t if isinstance(series_t, dict) else {}
    # the live MCX quote the page holds (Breeze through mcx_quote) folded into THIS health payload: one basis, one desk
    # state on the page (C-TRADER-10 / C-DATA-13); the memoised /health is untouched (it reads the quote cache itself)
    q: dict[str, Any] = (quote.get("quote") or {}) if quote.get("available") else {}
    mcx_live = _f(q.get("ltp"))
    mcx_live_at = _iso_any(q.get("time")) or _iso_any(quote.get("as_of"))
    mcx_open = mcx_is_open(now)
    if health is not None and mcx_live and mcx_open:   # a frozen LTP outside hours is never folded in (re-check major)
        apply_live_mcx(health, mcx_live, q.get("source"), mcx_live_at)
    hf: dict[str, Any] = (health or {}).get("fair") or {}
    cf: dict[str, Any] = (fair or {}).get("contract_fair") or hf
    ib: dict[str, Any] = next((g for g in (health or {}).get("gauges") or [] if g.get("key") == "india_basis"), {})
    got = await asyncio.to_thread(mcxr._master_gold_family)
    family, published = got if got else (None, None)
    exp, exp_source, row = mcxr._resolve_expiry(code, now.date(), _d(expiry) if expiry else None, family)
    spec = mcxr.contract_specs()[code]
    ry = latest(series.get("FRED_DFII10") or series.get("UST_REAL_10Y") or [])
    xc = latest(series.get("XAU_CROSSCHECK") or [])
    cot_rows = _cot_rows(cot_t) if not isinstance(cot_t, Exception) else []
    cot_last = cot_rows[-1] if cot_rows else None
    mm_net = _cot_net(cot_last, "mm") if cot_last else None
    mm_chg = _diff(_f(cot_last.get("chg_mm_long")), _f(cot_last.get("chg_mm_short"))) if cot_last else None
    comex_live = (cf.get("comex") or {}).get("price")
    model = (fair or {}).get("model") or {}
    comex_ref = (model.get("comex") or {}).get("ref")
    # the matched COMEX month: the liquid cycle month (never the thin serial under a GOLDM / GUINEA pick, C-BEGINNER-26) and
    # ITS stored price — a bulletin settlement when one is stored (O-2), else the last trade labelled so (C-TRADER-9)
    matched_sym, matched_sub = comex_liquid_symbol(exp)
    curve_pts = curve_points(curve_t, now.date()) if not isinstance(curve_t, Exception) else []
    matched_pt = _curve_point_for_symbol(curve_pts, matched_sym)
    matched_is_settle = bool(matched_pt and str(matched_pt.get("source") or "").startswith("cme"))
    matched_px = (matched_pt or {}).get("settle_or_last")
    # ONE basis on the strip, its clock named: the INDIA BASIS gauge's own value and clock (live MCX ÷ duty-paid landed of
    # the contract's purity now while a quote exists, else the settlement-clock figure) — the gauge, the verdict and the strip
    # are built on the same contract, so they cannot differ (C-TRADER-10 / C-BEGINNER-5; wave 1d: five values in ten minutes)
    hf_live = live_basis(hf) if hf.get("mcx_live") else None
    live_basis_pct = (
        ib.get("value") if ib and ib.get("clock") == "now" else (hf_live["value"] if hf_live else None)
    )
    settle_basis_pct = ib.get("settle_basis_pct") if ib else None
    if settle_basis_pct is None:
        settle_basis_pct = cf.get("basis_pct")
    strip = {
        "comex_matched": matched_sym,
        "comex_matched_calendar": gp.comex_symbol(exp),
        "comex_matched_note": "nearest liquid COMEX month (Feb/Apr/Jun/Aug/Oct/Dec)" if matched_sub else None,
        "comex_matched_settle": matched_px if matched_is_settle else None,
        "comex_matched_settle_date": (matched_pt or {}).get("trade_date") if matched_is_settle else None,
        "comex_matched_last": matched_px if matched_pt and not matched_is_settle else None,
        "comex_matched_last_date": (matched_pt or {}).get("trade_date") if matched_pt and not matched_is_settle else None,
        "comex_matched_last_label": (
            "last trade (Yahoo per-month daily bar), not a settlement" if matched_pt and not matched_is_settle else None
        ),
        "comex_matched_last_source": "Yahoo" if matched_pt and not matched_is_settle else None,
        "comex_live": comex_live,
        "comex_live_symbol": cf.get("comex_symbol"),
        "comex_live_as_of": _iso_any((cf.get("comex") or {}).get("as_of")),
        "comex_live_chg_pct": _pct_change(comex_live, comex_ref),
        "comex_ref_note": "vs the 30-min reference before the last MCX close",
        "usdinr": (cf.get("usdinr") or {}).get("price"),
        "usdinr_as_of": _iso_any((cf.get("usdinr") or {}).get("as_of")),
        "real_10y": ry["value"] if ry else None,
        "real_10y_date": ry["report_date"] if ry else None,
        "mcx_live": mcx_live,
        "mcx_live_source": q.get("source") if mcx_live else None,
        "mcx_live_as_of": mcx_live_at if mcx_live else None,
        "mcx_live_vs_settle_pct": _pct_change(mcx_live, cf.get("settlement")) if mcx_live else None,
        "mcx_shown": "live" if mcx_live and mcx_open else "settlement",
        # the wave-1d CONTRACT on the strip: the settlement (VWAP30 of the latest session, else the band of its real session)
        **{k: cf.get(k) for k in mcxr.SETTLE_KEYS},
        "mcx_settle": cf.get("settlement"),
        "mcx_settle_session": cf.get("settlement_session"),
        "mcx_settle_session_label": cf.get("settlement_session_label"),
        "mcx_settle_quality": cf.get("settlement_quality"),
        "mcx_settle_source": cf.get("settlement_source"),
        # the unit every MCX price on the strip is in (₹ per 10 g for GOLD / GOLDM / GOLDTEN, per 1 g PETAL, per 8 g GUINEA)
        "mcx_quote_unit": cf.get("quote_unit"),
        "basis_pct": live_basis_pct if live_basis_pct is not None else settle_basis_pct,
        "basis_clock": "now" if live_basis_pct is not None else "settlement",
        "basis_label": (
            f"live MCX ({q.get('source') or 'quote'}) vs duty-paid landed at {cf.get('purity')} now"
            if live_basis_pct is not None
            else (ib.get("settle_basis_label") or "settle ÷ that session's duty-paid landed − 1")
        ),
        "basis_reference": (ib.get("basis_reference") if ib else None) or cf.get("basis_reference"),
        "basis_contract": f"{code} {_mmy(exp) or ''}".strip(),
        "purity": cf.get("purity"),
        "basis_live_pct": live_basis_pct,
        "basis_settle_pct": settle_basis_pct,
        "basis_settle_date": (ib.get("settle_basis_date") if ib else None) or cf.get("settlement_session"),
        # the names the header component already reads (ui/components/gold/HealthStrip.tsx, wave 1c): aliases of the above.
        # `basis_session_label` is the SESSION only ('Wed 04 Nov settlement'): the strip wraps it in its own 'at the … vs
        # that session's duty-paid' (re-review minor: the full sentence printed 'at the at the … duty-paid landed vs …')
        "basis_session": (ib.get("settle_basis_date") if ib else None) or cf.get("settlement_session"),
        "basis_session_label": (ib.get("settle_basis_session_label") if ib else None) or cf.get("settlement_session_label"),
        "cot_mm_net": mm_net,
        "cot_mm_chg": mm_chg,
        "cot_as_of": str(cot_last.get("report_date"))[:10] if cot_last else None,
        "crosscheck": {
            "price": xc["value"] if xc else None,
            "at": _iso_any(xc.get("release_at")) or xc["report_date"] if xc else None,
            "source": "gold-api.com (A12)",
        }
        if xc
        else None,
        "instruments": {
            "spot": "spot proxy (gold-api cross-check)",
            "front": "COMEX front GC1 (continuous GC=F)",
            "matched": f"COMEX matched month {matched_sym}",
            "mcx": f"MCX {code} {_mmy(exp)}",
        },
    }
    session = specs.session_state(now)
    headlines = (fair or {}).get("headlines") or []
    brief_rows = _brief_rows(brief_t) if not isinstance(brief_t, Exception) else []
    brief: dict[str, Any] = {"available": False}
    if brief_rows:
        b = max(brief_rows, key=lambda x: str(x.get("report_date") or ""))
        doc, stripped = brief_doc(b)
        bb = brief_bias(b, doc)
        brief = {
            "available": True,
            "report_date": str(b.get("report_date"))[:10],
            "bias": bb["bias"],
            "confidence": bb["confidence"],
            "bias_withheld": bb["bias_withheld"],
            "overnight_summary": doc.get("overnight_summary"),
            "open_plan": doc.get("open_plan"),
            "key_risks_today": doc.get("key_risks_today") or [],
            "stripped_fields": stripped,
        }
    # the event strip: the FULL next 7 days (stored rows + the computed MCX / COT rows), nothing already past, ordered by
    # impact (FOMC decision / High first) then time; ★ only on High impact or an FOMC decision (C-TRADER-11 / C-DATA-21)
    stored_events = [e for e in (_rows(events_t) if not isinstance(events_t, Exception) else []) if _d(e.get("event_date"))]
    calendar: list[dict[str, Any]] = []
    for e in merge_events(stored_events, computed_events(now.date(), 7)):
        d = _d(e.get("event_date"))
        if d is None or d > now.date() + timedelta(days=7) or event_is_past(e, now):
            continue
        calendar.append(
            decorate_event(
                {**e, "event_date": d.isoformat(), "first_seen_at": _iso_any(e.get("first_seen_at")), "days": (d - now.date()).days},
                now,
            )
        )
    calendar.sort(key=lambda e: (e["impact_rank"], e["event_date"], e.get("time_ist") or ""))
    if health is not None:
        health.pop("_served", None)
        health.pop("_extras", None)
    return {
        "as_of": now.isoformat(timespec="seconds"),
        "window": window,
        "contract": {
            "mcx": code,
            "name": spec.name,
            "expiry": exp.isoformat(),
            "expiry_source": exp_source,
            "comex_matched": matched_sym,
            "comex_matched_calendar": gp.comex_symbol(exp),
            "comex_matched_note": strip["comex_matched_note"],
            "comex_front": GC_FRONT,
            "spot_proxy_note": "no free spot feed: the gold-api cross-check chip (A12) is the spot proxy",
            "lot": spec.as_dict()["lot"],
            "tick_value": spec.tick_value,
            "quote_unit": spec.as_dict()["quotation"],
            "master_published": published.isoformat() if published else None,
            "band": row,
            # the band's midpoint is the settlement of `band_session`; the band itself MCX's price band of `band_applies_to`
            "band_session": gp.band_session(published).isoformat() if published else None,
            "band_applies_to": gp.band_applies_to(published).isoformat() if published else None,
            "purity": gp.fineness_of(code),
        },
        "session": {
            "mcx": {
                "is_open": session["is_open"],
                "segment": session.get("segment"),
                "opens_at": session["opens_at"],
                "closes_at": session["closes_at"],
                "holiday": session.get("holiday"),
                "seconds_to_open": session.get("seconds_to_open"),
                "seconds_to_close": session.get("seconds_to_close"),
                "weekend": session.get("weekend"),
            },
            "comex": comex_session(now),
        },
        "strip": strip,
        "health": health,
        "fair": fair,
        "quote": quote,
        "headlines": headlines[:12],
        "brief": brief,
        "calendar": calendar,
        "freshness": {
            "health": (health or {}).get("freshness"),
            "fair": (fair or {}).get("freshness"),
            "quote": freshness(
                (quote.get("quote") or {}).get("time") if quote.get("available") else None,
                1.0,
                "ICICI Breeze",
                live=bool(quote.get("available")),
            ),
            "cot": freshness(cot_last.get("release_at") if cot_last else None, 9.0, "CFTC"),
            "brief": freshness(brief.get("report_date"), 2.0, "gold_brief_docs"),
        },
        "errors": {
            k: v
            for k, v in {
                "health": None if health else type(health_t).__name__,
                "fair": None if fair else type(fair_t).__name__,
                **reads.errors,
            }.items()
            if v
        },
        "_served": reads.served,
    }


@router.get("/overview")
async def gold_overview(
    contract: str = Query("GOLD"),
    expiry: str | None = Query(None),
    window: str = Query("W", pattern="^[DWMdwm]$"),
    response: Response = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """The GOLD page frame in one call (PLAN §d): contract, sessions, the five-number header strip, health, fair, the MCX quote,
    headlines, today's brief and the next week's events; 30 s TTL per (contract, expiry, window)."""
    if expiry:
        _date_arg(expiry, "expiry")
    key = f"overview:{contract.upper()}:{expiry or 'front'}:{window.upper()}"
    hit = _memo_hit(key, response)
    if hit is not None:
        return hit
    payload = await build_overview(contract, expiry, window.upper())
    served = _served_of(payload)
    _memo(key, OVERVIEW_TTL_S, payload, served)
    cache_headers(response, served)
    return payload


async def overview() -> dict[str, Any]:
    """Warm-up entry point for routers/_cache_warm.py (`("gold_overview", gold.overview)`): fills the memo and the SWR store."""
    return await gold_overview(contract="GOLD", expiry=None, window="W", response=None)  # type: ignore[arg-type]
