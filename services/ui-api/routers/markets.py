"""Market Monitor proxy: breadth, regime score, sectors and movers (computed by data-service)."""
from __future__ import annotations

import functools
import math
import os
import re
from datetime import date, datetime
from datetime import timedelta as _timedelta
from zoneinfo import ZoneInfo
from typing import Any

import httpx

from shared import http_client
from cache import SWRCache, cache_headers
from fastapi import APIRouter, HTTPException, Query, Response

from routers import live as _live   # the live NSE hub: results-reacting prices and /closes symbols (L2-API)
from routers._upstream import upstream_detail

router = APIRouter()
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")


# ── Short stale-while-revalidate caches (desktop review C-PERF-01) ───────────────────────────
# These reads took 0.7-1.1 s on EVERY call (DuckDB in data-service) and dominated the data-settled time of
# EQS, WTCH, EVTS, BRF and SCRN. Each is now served from a single-flight SWR cache (cache.SWRCache): a call
# within REFRESH_AFTER of the last fetch is served as is; up to MAX_AGE it is served at once AND refreshed in
# the background; past MAX_AGE the caller waits for a fresh read. So no response is ever older than MAX_AGE
# (5 min), far inside the data's own cadence: nse_results is written by the 20:45 results job (and the PIPE
# page), reactions and valuations by the EOD bhavcopy, the F&O chain by the EOD F&O bhavcopy, financials by
# the results-filing reads. Keys include today's date where the upstream window does (since = today - days),
# so a cached answer never crosses midnight. Responses are byte-identical to the uncached ones; only the age
# changes, and it is in the X-Cache-Age header (seconds), never in the body. UI_API_SWR=0 turns them off.
MARKET_REFRESH_AFTER_S = 60.0
MARKET_MAX_AGE_S = 300.0
_RESULTS_RECENT = SWRCache("market.results_recent", max_items=16, refresh_after=MARKET_REFRESH_AFTER_S,
                           max_age=MARKET_MAX_AGE_S)
_IMPLIED_MOVES = SWRCache("market.results_implied_moves", max_items=8, refresh_after=MARKET_REFRESH_AFTER_S,
                          max_age=MARKET_MAX_AGE_S)
_FUNDAMENTALS = SWRCache("market.fundamentals_screen", max_items=8, refresh_after=MARKET_REFRESH_AFTER_S,
                         max_age=MARKET_MAX_AGE_S)
# results-reacting follows live quotes in the session: same 60 s bound as its old cache, now single flight + SWR.
_REACTING = SWRCache("market.results_reacting", max_items=2, refresh_after=30.0, max_age=60.0)


def _today() -> str:
    """The cache-key day: the machine's local date, the same clock data-service uses for its `days` window."""
    return date.today().isoformat()  # noqa: DTZ011 — local on purpose (data-service computes since from it)


# ── `fields=core` payload trims (W7 — bloomberg_verdict.md D5/S6) ────────────────────────────
# Default responses stay byte-identical (the ohlcv-meta lesson: default-full breaks nobody);
# `?fields=core` is opt-in per consumer. Core = columnar rows ({"columns","data"} — drops the
# per-row key repetition that dominates these payloads) minus only fields NO ui/ consumer
# reads. Consumer census: reports/worldclass_program/build_w7.md §2. The api.ts helper
# `fromColumnar` restores row objects, so components are unchanged.

CORE_FIELDS = Query(None, pattern="^core$", description="opt-in trimmed payload (S6)")


def ordered_columns(rows: list[dict]) -> list[str]:
    """Union of row keys in first-seen order (rows are near-homogeneous; order is the contract)."""
    cols: dict[str, None] = {}
    for r in rows:
        for k in r:
            cols.setdefault(k, None)
    return list(cols)


def columnar(rows: list[dict], columns: list[str] | None = None) -> dict:
    """rows → {"columns": [...], "data": [[...], ...]}; missing keys become None."""
    cols = ordered_columns(rows) if columns is None else columns
    return {"columns": cols, "data": [[r.get(c) for c in cols] for r in rows]}


_EVENTS_CORE_DROP = {"sources", "announced_at", "first_seen"}  # read by no ui/ consumer


def events_core_rows(rows: list[dict]) -> list[dict]:
    """Core EVTS rows: drop the unread fields; null `purpose` where it duplicates `detail`
    (the api.ts fetcher restores `purpose ??= detail`, so consumers see identical values)."""
    out = []
    for r in rows:
        slim = {k: v for k, v in r.items() if k not in _EVENTS_CORE_DROP}
        if slim.get("purpose") == slim.get("detail"):
            slim["purpose"] = None
        out.append(slim)
    return out


def mtf_core(body: dict) -> dict:
    """MRGN core: `stocks` goes columnar with display-precision floats (2 dp); the small
    `market` block (~250 rows, already ≤2 dp upstream) is kept as-is."""
    stocks = body.get("stocks") or []
    cols = ordered_columns(stocks)
    data = [[round(v, 2) if isinstance(v, float) else v for v in (r.get(c) for c in cols)]
            for r in stocks]
    return {**body, "stocks": {"columns": cols, "data": data}}


@router.get("/monitor")
async def market_monitor(as_of: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """Breadth, regime, sectors and movers; `as_of` asks for the snapshot of a past session (review M10: the wrap's
    backfill). The payload's own `as_of` is the session it describes: a caller checks it, never assumes it."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0 if as_of else 60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/market-monitor", params={"as_of": as_of} if as_of else None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


_SOURCE_RANK = {"board": 0, "action": 1, "calendar": 2}   # board intimations carry the filing PDF
# NSE's board-intimation boilerplate: "X has informed the Exchange about Board Meeting to be held on … to consider
# Other business." The calendar feed's line ("To consider and approve the Company's expansion plans…") says more.
_GENERIC = ("has informed the exchange about board meeting", "board meeting intimation")


def _generic(text: str | None) -> bool:
    return not text or any(g in text.lower() for g in _GENERIC)


def merge_events(rows: list[dict]) -> list[dict]:
    """One row per (symbol, date, kind): the same meeting is often in both the calendar and the board feed."""
    out: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: _SOURCE_RANK.get(str(r.get("source")), 9)):
        key = (r.get("symbol"), r.get("event_date"), r.get("kind"))
        if key not in out:
            out[key] = {**r, "sources": [r.get("source")]}
            continue
        m = out[key]
        m["sources"].append(r.get("source"))
        tags = {t for t in f"{m.get('tags') or ''},{r.get('tags') or ''}".split(",") if t}
        m["tags"] = ",".join(sorted(tags))
        for f in ("company", "url", "announced_at", "record_date"):
            m[f] = m.get(f) or r.get(f)
        for f in ("detail", "purpose"):              # keep the specific wording over the boilerplate
            if _generic(m.get(f)) and not _generic(r.get(f)):
                m[f] = r.get(f)
        seen = [x for x in (m.get("first_seen"), r.get("first_seen")) if x]
        m["first_seen"] = min(seen) if seen else None
    return sorted(out.values(), key=lambda r: (r.get("event_date") or "", -(r.get("turnover_cr") or 0), r.get("symbol") or ""))


_IST_EVENTS = ZoneInfo("Asia/Kolkata")


def keep_nearest_events(rows: list[dict], limit: int, today: date) -> list[dict]:
    """The `limit` rows a calendar needs when it must cut: every event from today on first (nearest first, the farthest
    future dropped), then the most recent past ones with what is left, returned date-ascending. The old cut kept the
    first `limit` rows of a list that starts a week back, so in results season (1,737 rows on 5 Nov 2026) it kept only
    the past week: EVTS read "0 upcoming" and every NEXT EVENT column (DEAL, INSD, EQS, BRF) was blank."""
    if len(rows) <= limit:
        return rows

    def day(r: dict) -> str:
        return str(r.get("event_date") or "")[:10]

    iso = today.isoformat()
    ordered = sorted(rows, key=day)
    future = [r for r in ordered if day(r) >= iso]
    past = [r for r in ordered if day(r) < iso]
    kept = future[:limit]
    room = limit - len(kept)
    if room > 0:
        kept = past[-room:] + kept
    return sorted(kept, key=day)


@router.get("/events")
async def market_events(start: str | None = None, end: str | None = None,
                        limit: int = Query(2000, ge=1, le=5000),
                        fields: str | None = CORE_FIELDS) -> dict:
    """NSE corporate calendar (results, dividends, splits, bonuses, buybacks…) from data-service.

    Payload budget (S2): rows capped at `limit` after merging. In results season the window holds 1,700+ rows (5 Nov
    2026), so the default is 2,000 (≈ 480 KB as `fields=core`) and a cut keeps upcoming events first
    (`keep_nearest_events`): never the past week instead of the next five.
    """
    params = {k: v for k, v in {"start": start, "end": end}.items() if v}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/events", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    body = r.json()
    rows = merge_events(body.get("rows", []))
    truncated = len(rows) > limit
    if truncated:
        rows = keep_nearest_events(rows, limit, datetime.now(_IST_EVENTS).date())
    if fields == "core":  # columnar + drop unread fields; default below stays byte-identical
        meta = {k: v for k, v in body.items() if k != "rows"}
        return {**meta, **columnar(events_core_rows(rows)), "count": len(rows),
                **({"truncated": True} if truncated else {})}
    return {**body, "rows": rows, "count": len(rows), **({"truncated": True} if truncated else {})}


@router.get("/crash-filter")
async def crash_filter() -> dict:
    """Decision Desk crash filter now: NIFTY 50 vs its 200-day average and the next monthly signal date."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/crash-filter")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


async def _fetch_results_recent(days: int) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/results-recent", params={"days": days})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/results-recent")
async def results_recent(days: int = 10,
                         response: Response = None) -> dict:  # type: ignore[assignment]  # injected; None if called directly
    """Results released in the last `days` and how each stock reacted (EVTS scoreboard). SWR-cached (C-PERF-01)."""
    served = await _RESULTS_RECENT.get((days, _today()), lambda: _fetch_results_recent(days))
    cache_headers(response, served)
    return served.value


@router.get("/option-chain/{symbol}")
async def option_chain(symbol: str, expiry: str | None = None) -> dict:
    """End-of-day option chain (OMON) from NSE's F&O bhavcopy, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/option-chain/{symbol}", params={"expiry": expiry} if expiry else None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.json().get("detail", r.text[:200]) if r.headers.get(
            "content-type", "").startswith("application/json") else r.text[:200])
    return r.json()


@router.get("/participants")
async def participants(days: int = 250) -> dict:
    """Index F&O positioning by participant (FII / DII / Pro / Client), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/participant-positioning", params={"days": days})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/option-history/{symbol}")
async def option_history(symbol: str, days: int = Query(260, ge=1, le=3000)) -> dict:
    """Daily ATM IV, PCR and max pain history (NIFTY / BANKNIFTY), via data-service — through the process-wide
    client (shared.http_client, PLAN 1.5) with the IV routes' UpstreamError → fail() mapping (errors.py)."""
    import re

    from errors import code_for_status, fail
    if not re.fullmatch(r"[A-Za-z0-9&\-]{1,20}", symbol):
        fail(422, "invalid", f"Bad symbol {symbol!r}", "NSE underlyings look like NIFTY, BANKNIFTY")
    try:
        body = await http_client.get_json(f"{DATA_SVC}/db/option-history/{symbol.upper()}", route="read",
                                          params={"days": days}, timeout=20.0)
    except http_client.UpstreamError as exc:
        if exc.status_code == 503:
            fail(503, "upstream_down", f"data-service unreachable: {exc.detail}", "is data-service on :8001 up?")
        fail(exc.status_code, code_for_status(exc.status_code), exc.detail)
    return with_iv_rank_and_percentile(body if isinstance(body, dict) else {"rows": body})


def with_iv_rank_and_percentile(payload: dict) -> dict:
    """Wave 0.6 (server side): the OMON history chart printed a PERCENTILE under the name "IV rank". Both numbers are
    now served, each with its definition, on the near-expiry ATM IV rows the payload already carries (additive keys;
    the rows are untouched). The UI relabels (B4)."""
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return payload
    iv = [r.get("atm_iv") for r in rows if isinstance(r, dict) and isinstance(r.get("atm_iv"), (int, float))]
    window = iv[-252:]
    rank = pctile = None
    if len(window) >= 2:
        lo, hi, today = min(window), max(window), window[-1]
        rank = round((today - lo) / (hi - lo) * 100, 1) if hi > lo else None
        prior = window[:-1]
        pctile = round(sum(1 for v in prior if v < today) / len(prior) * 100, 1)
    payload["iv_rank_252"] = rank
    payload["iv_pctile_252"] = pctile
    payload["rank_window_sessions"] = min(len(window), 252)
    payload["rank_series"] = "near-expiry ATM IV (saw-tooth; iv30_cm on /api/derivatives/iv/{symbol} is the constant-maturity series)"
    payload["definitions"] = {
        "iv_rank_252": "IV rank: where today's IV sits between its 252-session minimum (0) and maximum (100).",
        "iv_pctile_252": "IV percentile: the share of the past 252 sessions whose IV was below today's.",
    }
    payload["badges"] = {"iv_rank_252": "arithmetic", "iv_pctile_252": "arithmetic"}
    return payload


MARKET_TOPICS = [  # (label, Google News query, a word the title must contain) — same relevance filter as the gold desk
    ("Markets", "Sensex OR Nifty", r"sensex|nifty|market|stocks|shares"),
    ("RBI", '"RBI" policy OR repo OR inflation', r"rbi|repo|inflation|cpi|monetary"),
    ("FII flows", "FII OR FPI India equities", r"fii|fpi|foreign"),
    ("Results", "quarterly results profit India", r"result|profit|q[1-4]|quarter|earnings"),
    ("IPO", "IPO listing NSE", r"ipo|listing|subscri"),
    ("Global", '"Wall Street" OR "crude oil" OR "US Fed"', r"wall street|crude|oil|fed|dow|nasdaq|s&p"),
]


@router.get("/headlines")
async def market_headlines() -> dict:
    """Last-24-hour Indian market headlines from Google News, de-duplicated, newest first (5-minute cache per topic)."""
    import asyncio
    from routers.gold_preopen import _UA, _headlines
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), headers=_UA, follow_redirects=True) as client:
        res = await asyncio.gather(*(asyncio.wait_for(_headlines(client, f"mkt:{label}", q, must), 10)
                                     for label, q, must in MARKET_TOPICS), return_exceptions=True)
    seen: set[str] = set()
    out: list[dict] = []
    for lst in res:
        if isinstance(lst, list):
            for h in lst:
                if h["title"] not in seen:
                    seen.add(h["title"])
                    out.append({**h, "topic": h["topic"].removeprefix("mkt:")})
    out.sort(key=lambda h: h["published_at"], reverse=True)
    return {"headlines": out[:20]}


@router.get("/insider-buys")
async def insider_buys(days: int = 60, min_value: float = 1e6) -> dict:
    """Recent insider open-market buying (promoters / directors / KMP), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/insider-buys", params={"days": days, "min_value": min_value})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/short-selling")
async def short_selling(days: int = Query(20, ge=1, le=120)) -> dict:
    """Institutional short selling per stock over the last `days` sessions (NSE disclosure), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/short-selling", params={"days": days})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/deals")
async def deals(days: int = 10, min_value: float = 1e7, kind: str = "all") -> dict:
    """Market-wide bulk / block deals, netted per client, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/deals", params={"days": days, "min_value": min_value, "kind": kind})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/preopen")
async def preopen(key: str = "FO") -> dict:
    """NSE pre-open call auction (IEP, gap, buy/sell imbalance), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/preopen", params={"key": key})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/fii-dii-cash")
async def fii_dii_cash(days: int = 90) -> dict:
    """FII / DII cash-market net buying, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/fii-dii-cash", params={"days": days})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/ipo")
async def ipo(months: int = 24, kind: str = "Mainboard") -> dict:
    """IPO monitor (open / forthcoming issues, listing scorecard), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/ipo", params={"months": months, "kind": kind})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/live-movers")
async def live_movers(universe: str = "FOSec") -> dict:
    """NSE live movers, volume surges, 52-week highs / lows, OI spurts, index breadth, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/live-movers", params={"universe": universe})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


# ── daily market wraps (scripts/daily_wrap.py → reports/daily_wrap/<date>.md) ───────────────────────────────

def _wrap_dir():
    from routers.research import _root
    return _root() / "reports" / "daily_wrap"


WRAP_MARKER = "<!-- wrap-sections "     # scripts/daily_wrap.py: each section's status ('ok' / 'not_stored')
WRAP_SCHEDULED = "21:00"


def split_wrap(text: str) -> tuple[str, dict[str, str] | None]:
    """(markdown without the machine marker, the marker's section status or None for a legacy wrap)."""
    import json as _json
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        ln = lines[i].strip()
        if ln.startswith(WRAP_MARKER) and ln.endswith("-->"):
            try:
                status = _json.loads(ln[len(WRAP_MARKER):-3].strip())
            except ValueError:
                status = None
            return "\n".join(lines[:i] + lines[i + 1:]).rstrip() + "\n", status
    return text, None


def wrap_entry(day: str, text: str) -> dict[str, Any]:
    """One archive row: date, teaser, and whether every section was stored for that day (legacy wraps: whether the
    header's end-of-day date is the wrap's own day)."""
    body, status = split_wrap(text)
    teaser = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("- ")), "")
    if status is not None:
        missing = sorted(k for k, v in status.items() if v == "not_stored")
    else:
        m = re.search(r"NSE end of day (\d{4}-\d{2}-\d{2})", body)
        missing = ["all end-of-day sections (written from " + m.group(1) + ")"] if m and m.group(1) != day else []
    return {"date": day, "teaser": teaser[:160], "complete": not missing, "not_stored": missing}


def wrap_archive_status(dates: list[str], sessions: list[str], today: str, today_is_session: bool) -> dict[str, Any]:
    """Archive gaps (stored NSE sessions with no wrap, inside the archive's span) and today's pending note (m022)."""
    have = set(dates)
    first = min(dates) if dates else None
    gaps = [d for d in sessions if first and first <= d < today and d not in have]
    pending = today_is_session and today not in have
    note = f"today's wrap is written after {WRAP_SCHEDULED} IST once the evening NSE files land" if pending else None
    return {"missing_sessions": gaps, "today": today, "today_written": today in have, "today_pending": pending,
            "scheduled": f"{WRAP_SCHEDULED} IST", "note": note}


@router.get("/wraps")
async def list_wraps(limit: int = 60) -> dict:
    """Dates of the saved daily wraps, newest first, with each wrap's first content line as a teaser, whether its
    sections were all stored for that day, the archive's missing sessions and today's pending note (review M10, m022)."""
    import asyncio
    d = _wrap_dir()

    def _read() -> list[dict[str, Any]]:
        files = sorted(d.glob("????-??-??.md"), reverse=True)[: max(1, min(limit, 400))] if d.is_dir() else []
        return [wrap_entry(f.stem, f.read_text(encoding="utf-8", errors="replace")) for f in files]

    out = await asyncio.to_thread(_read)
    sessions: list[str] = []
    holidays: set[str] = set()
    got = await asyncio.gather(
        http_client.get_json(f"{DATA_SVC}/db/index-daily", route="read", params={"symbol": "NIFTY50", "days": 120}),
        http_client.get_json(f"{DATA_SVC}/db/market-holidays", route="read"), return_exceptions=True)
    if isinstance(got[0], dict):                    # the archive still lists without them; gaps unknown
        sessions = [str(r.get("date"))[:10] for r in got[0].get("rows") or []]
    if isinstance(got[1], dict):
        holidays = {str(h.get("date")) for h in got[1].get("holidays") or []}
    now = datetime.now(_IST_EVENTS)
    today = now.date().isoformat()
    is_session = now.weekday() < 5 and today not in holidays
    status = wrap_archive_status([w["date"] for w in out], sessions, today, is_session)
    return {"wraps": out, **status, "sessions_known": bool(sessions)}


@router.get("/wraps/{day}")
def get_wrap(day: str) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    f = _wrap_dir() / f"{day}.md"
    if not f.is_file():
        raise HTTPException(status_code=404, detail=f"No wrap for {day}")
    text = f.read_text(encoding="utf-8", errors="replace")
    body, status = split_wrap(text)
    entry = wrap_entry(day, text)
    return {"date": day, "markdown": body, "sections": status, "complete": entry["complete"], "not_stored": entry["not_stored"]}


@router.get("/live-quotes")
async def live_quotes() -> dict:
    """Live quotes for ~300 large and mid caps (NSE heatmap lists), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/live-quotes")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/basket-risk")
async def basket_risk(symbols: str, days: int = 365, weights: str | None = None) -> dict:
    """Risk profile of a basket of NSE symbols (vol, beta, drawdown, correlation), via data-service."""
    params: dict = {"symbols": symbols, "days": days}
    if weights:
        params["weights"] = weights
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/basket-risk", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


ANNOUNCEMENTS_DEFAULT_LIMIT = 5000      # 1,421 filings on 5 Nov 2026 (results season); NSE's busiest days stay well under it
_HHMM = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")


def page_announcements(items: list[dict], limit: int, before: str | None = None) -> tuple[list[dict], dict[str, Any]]:
    """Newest-first filings cut to `limit`, optionally only those older than the cursor `before`: a clock ('HH:MM',
    'HH:MM:SS', or the items' own 'YYYY-MM-DD HH:MM:SS' time), optionally '#k' = k filings stamped that same time were
    already returned (ties never fall between pages). Returns (page, meta): how many the day has, how many came back,
    the oldest returned and the cursor for the next page (review M11: the old 1,000 cap silently dropped everything
    filed before ≈ 14:40 on a results day)."""
    def clock(t: Any) -> str:
        t = str(t or "")
        return t[12:20] if len(t) >= 20 and t[2] == "-" else t[11:19] if len(t) >= 19 and t[4] == "-" else t[:8]

    rows = items
    if before:
        at, _, k = before.partition("#")
        cut = at if _HHMM.match(at) else clock(at)
        cut = (cut + ":00")[:8] if len(cut) == 5 else cut
        skip = int(k) if k.isdigit() else 0
        ties = [it for it in items if clock(it.get("time")) == cut][skip:] if k else []
        rows = ties + [it for it in items if clock(it.get("time")) < cut]
    page = rows[:limit]
    truncated = len(rows) > limit
    oldest = page[-1].get("time") if page else None
    cursor = None
    if truncated and oldest is not None:
        last = clock(oldest)
        before_ties = int(before.partition("#")[2] or 0) if before and clock(before.partition("#")[0]) == last else 0
        cursor = f"{oldest}#{before_ties + sum(1 for it in page if clock(it.get('time')) == last)}"
    return page, {"total": len(items), "matching": len(rows), "returned": len(page), "truncated": truncated,
                  "oldest": oldest, "newest": page[0].get("time") if page else None, "next_before": cursor}


@router.get("/announcements")
async def announcements(day: str | None = None,
                        limit: int = Query(ANNOUNCEMENTS_DEFAULT_LIMIT, ge=1, le=20000),
                        before: str | None = Query(None, max_length=28, pattern=r"^[0-9A-Za-z: \-]+(#\d{1,5})?$"),
                        full: bool = False,
                        fields: str | None = CORE_FIELDS) -> dict:
    """The day's NSE company filings, categorised, newest first, via data-service.

    The whole day by default (review M11): `limit` 5,000 is far above a results-season day (1,421 on 5 Nov 2026), and
    `before` pages back by time when a caller wants smaller pages. `total` / `returned` / `oldest` / `next_before` say
    what came back and `truncated` is true only when filings were left out; `counts` stays the whole-day count either
    way, so a category chip and the list can be reconciled. Filing text trimmed to 400 chars unless `full=true`;
    `fields=core` returns {symbol, time, category} items only (the EVTS / BRIEF pollers).
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/announcements", params={"day": day} if day else None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    body = r.json()
    items, meta = page_announcements(body.get("items", []), limit, before)
    flag = {"truncated": True} if meta["truncated"] else {}
    if fields == "core":  # new dicts — never mutate the full items
        core = [{"symbol": it.get("symbol"), "time": it.get("time"), "category": it.get("category")}
                for it in items]
        return {**body, "items": core, **meta, **flag}
    if not full:
        for it in items:
            t = it.get("text")
            if isinstance(t, str) and len(t) > 400:
                it["text"] = t[:400] + "…"
    return {**body, "items": items, **meta, **flag}


@router.get("/option-chain-live/{symbol}")
async def option_chain_live(symbol: str, expiry: str | None = None) -> dict:
    """Live NSE option chain computed like the EOD one (IV, PCR, max pain, walls), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/option-chain-live/{symbol}", params={"expiry": expiry} if expiry else None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/index-members")
async def index_members(index: str, group: str = "SECTORAL INDICES") -> dict:
    """Live members of an NSE index, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-members", params={"index": index, "group": group})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


_STOCK_NEWS: dict[str, tuple[float, list]] = {}
_NAME_NOISE = {"the", "ltd", "limited", "india", "indian", "company", "corporation", "industries", "and", "of"}


def _news_terms(symbol: str, name: str | None) -> tuple[str, str]:
    """Google News query and the relevance regex for one stock: the company name (minus 'Limited') or the ticker,
    and a title must mention the ticker or the name's first distinctive word."""
    import re
    clean = re.sub(r"\b(limited|ltd\.?)\b", "", name or "", flags=re.I).strip(" .,")
    words = [w for w in re.findall(r"[A-Za-z0-9&]+", clean) if w.lower() not in _NAME_NOISE and len(w) > 2]
    must = "|".join(re.escape(x) for x in dict.fromkeys([symbol, *(words[:1])]))
    query = f'"{clean}"' if clean else symbol
    return f"{query} share OR stock OR results", must


@router.get("/stock-news/{symbol}")
async def stock_news(symbol: str, name: str | None = None, days: int = 7) -> dict:
    """Recent headlines for one stock from Google News (relevance-filtered, 15-minute cache)."""
    import re
    import time as _t
    import xml.etree.ElementTree as ET
    from datetime import datetime, timedelta, timezone
    from email.utils import parsedate_to_datetime
    from routers.gold_preopen import _UA
    if not re.fullmatch(r"[A-Za-z0-9&\-]{1,20}", symbol):
        raise HTTPException(status_code=422, detail="Bad symbol")
    if not name:      # callers like the wrap pass only the ticker: "AEROFLEX" alone matched an "Aeroflex Airport" story
        try:
            from routers.stocks import _load_universe_metadata
            n = (_load_universe_metadata().get(symbol.upper()) or {}).get("company_name")
            name = n if n and n.upper() != symbol.upper() else None
        except Exception:  # noqa: BLE001 — the ticker alone still works
            name = None
    key = f"{symbol.upper()}|{name}|{days}"
    hit = _STOCK_NEWS.get(key)
    if hit and _t.time() - hit[0] < 900:
        return {"symbol": symbol.upper(), "headlines": hit[1]}
    query, must = _news_terms(symbol.upper(), name)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), headers=_UA, follow_redirects=True) as client:
            r = await client.get("https://news.google.com/rss/search",
                                 params={"q": f"{query} when:{max(1, min(days, 30))}d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        root = ET.fromstring(r.content)
    except (httpx.HTTPError, ET.ParseError) as exc:
        raise HTTPException(status_code=503, detail=f"news unavailable: {exc}") from exc
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out, seen = [], set()
    for it in root.findall("./channel/item"):
        title, publisher = it.findtext("title") or "", it.findtext("source") or ""
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        try:
            when = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if when < cutoff or title in seen or not re.search(must, title, re.I):
            continue
        seen.add(title)
        out.append({"title": title, "publisher": publisher, "link": it.findtext("link"),
                    "published_at": when.astimezone(timezone.utc).isoformat()})
    out.sort(key=lambda x: x["published_at"], reverse=True)
    out = out[:10]
    _STOCK_NEWS[key] = (_t.time(), out)
    return {"symbol": symbol.upper(), "headlines": out}


@router.get("/mtf-monitor")
async def mtf_monitor(lookback: int = 20, min_amount_cr: float = 0,
                      fields: str | None = CORE_FIELDS) -> dict:
    """Margin-trading crowding monitor, via data-service. `fields=core`: columnar stocks, 2 dp."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/mtf-monitor", params={"lookback": lookback, "min_amount_cr": min_amount_cr})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    if fields == "core":
        return mtf_core(r.json())
    return r.json()


# ── US Fed meetings (WEI): federalreserve.gov FOMC calendar, parsed, cached a day ────────────────────────────────
_FOMC_CACHE: dict = {}
_MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                       "September", "October", "November", "December"], 1)}


def parse_fomc(html: str) -> list[dict]:
    """FOMC calendar page → [{start, end (decision day, US), projections}]; '*' marks a Summary of Economic
    Projections meeting. Month cells like 'Apr/May' and dates like '30-1' span two months."""
    import re
    from datetime import date
    out: list[dict] = []
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r"(\d{4}) FOMC Meetings", html)]
    for i, (pos, year) in enumerate(heads):
        seg = html[pos: heads[i + 1][0] if i + 1 < len(heads) else len(html)]
        for mon, days in re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<", seg, re.S):
            months = [_MONTHS.get(next((k for k in _MONTHS if k[:3] == x.strip()[:3]), "")) for x in mon.split("/")]  # "Apr/May"
            nums = [int(x) for x in re.findall(r"\d+", days)]
            if not nums or not months[0]:
                continue
            m1, m2 = months[0], (months[-1] or months[0])
            d1, d2 = nums[0], nums[-1]
            try:
                start, end = date(year, m1, d1), date(year, m2 if d2 < d1 or m2 != m1 else m1, d2)
            except ValueError:
                continue
            out.append({"start": start.isoformat(), "end": end.isoformat(), "projections": "*" in days})
    return sorted({x["end"]: x for x in out}.values(), key=lambda x: x["end"])


@router.get("/fomc")
async def fomc() -> dict:
    """US FOMC meeting dates (decision on the second day, ~23:30–00:00 IST), from federalreserve.gov."""
    import time as _t
    from datetime import date
    from routers.gold_preopen import _UA
    if _FOMC_CACHE.get("at", 0) > _t.time() - 86400:
        rows = _FOMC_CACHE["rows"]
    else:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=_UA, follow_redirects=True) as client:
                r = await client.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
            rows = parse_fomc(r.text)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail=f"Fed calendar unavailable: {exc}") from exc
        if rows:
            _FOMC_CACHE.update(at=_t.time(), rows=rows)
    today = date.today().isoformat()  # noqa: DTZ005,DTZ011 — local clock on purpose (data-service computes its windows from it)
    upcoming = [x for x in rows if x["end"] >= today]
    return {"next": upcoming[0] if upcoming else None, "upcoming": upcoming[:6], "source": "federalreserve.gov"}



@router.get("/rbi-mpc")
def rbi_mpc() -> dict:
    """RBI Monetary Policy Committee meetings (data/reference/rbi_mpc.json, from RBI's published schedule)."""
    import json
    from datetime import date
    from routers.research import _root
    try:
        ref = json.loads((_root() / "data" / "reference" / "rbi_mpc.json").read_text())
    except (OSError, ValueError):
        return {"next": None, "upcoming": [], "source": None, "stale": True}
    today = date.today().isoformat()  # noqa: DTZ005,DTZ011 — local clock on purpose (data-service computes its windows from it)
    upcoming = [m for m in ref.get("meetings", []) if m["end"] >= today]
    return {"next": upcoming[0] if upcoming else None, "upcoming": upcoming, "source": ref.get("source"),
            "stale": not upcoming}          # schedule ran out: RBI publishes the next year's in March


# ── ECO: economic calendar (India data releases + RBI + Fed decisions) ─────────────────────────────────────────────
def _next_working_day(d: date) -> date:
    """Official releases planned on a Saturday / Sunday come out on the next working day (gazetted holidays are not
    known here, so a release planned on one shows a day early)."""
    from datetime import timedelta
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def build_eco_calendar(ref: dict, rbi: list[dict], fomc_rows: list[dict], start: date, end: date,
                       holidays: list[dict] | None = None) -> list[dict]:
    """Every economic event dated in [start, end], sorted: MoSPI releases (explicit dates), DPIIT fixed-day releases
    (WPI on the 14th, core industries on the 20th: for the previous month), RBI policy decisions and Fed decisions.
    Times are IST."""
    from datetime import timedelta
    out: list[dict] = []
    for r in ref.get("releases") or []:
        planned = date.fromisoformat(r["date"])
        out.append({"date": _next_working_day(planned).isoformat(), "time": r.get("time"), "kind": r["kind"], "what": r["what"],
                    "country": "IN", "source": "MoSPI", "moved": _next_working_day(planned) != planned})
    valid_until = date.fromisoformat(ref.get("valid_until") or "2000-01-01")
    m = date(start.year, start.month, 1)
    while m <= end:
        prev = (m - timedelta(days=1)).strftime("%b %Y")
        for rule in ref.get("monthly_rules") or []:
            planned = date(m.year, m.month, int(rule["day"]))
            if planned <= valid_until:
                d = _next_working_day(planned)
                out.append({"date": d.isoformat(), "time": rule.get("time"), "kind": rule["kind"], "what": f"{rule['what']} · {prev}",
                            "country": "IN", "source": rule.get("source"), "moved": d != planned})
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    out += [{"date": x["end"], "time": "10:00", "kind": "RBI", "what": "RBI policy decision (repo rate)", "country": "IN",
             "source": "RBI", "moved": False} for x in rbi]
    # Fed decision: 14:00 Washington = 23:30 IST in US summer time, 00:30 IST the next day in winter
    for x in fomc_rows:
        d = date.fromisoformat(x["end"])
        summer = date(d.year, 3, 8) <= d < date(d.year, 11, 1)          # US DST: 2nd Sun of Mar → 1st Sun of Nov (approx.)
        out.append({"date": (d if summer else d + timedelta(days=1)).isoformat(), "time": "23:30" if summer else "00:30",
                    "kind": "FED", "what": "US Fed rate decision" + (" + projections" if x.get("projections") else ""),
                    "country": "US", "source": "federalreserve.gov", "moved": False})
    out += [{"date": h["date"], "time": None, "kind": "HOLIDAY", "what": f"NSE closed · {h['description']}", "country": "IN",
             "source": "NSE", "moved": False} for h in holidays or []]
    s, e = start.isoformat(), end.isoformat()
    return sorted((x for x in out if s <= x["date"] <= e), key=lambda x: (x["date"], x["time"] or ""))


# ── ECO additions (review M28): US releases, F&O expiries, exchange special sessions ─────────────────────────────
US_ECO_IMPACT = ("High", "Medium")              # ForexFactory's impact; "Low" (weekly API stocks, speeches) stays on GOLD
US_ECO_PER_DAY = 5
FO_MONTHLY_WHAT = "F&O monthly expiry: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY and stock futures & options"
FO_WEEKLY_WHAT = "NIFTY weekly options expiry"
FO_RULE = "rule: NIFTY weekly options on Tuesday, every monthly contract on the month's last Tuesday; an NSE holiday moves it to the previous session"
# Exchange special sessions, dated constants with their circulars (MCX: shared/mcx_specs.SPECIAL_SESSIONS_2026). NSE's own
# Muhurat window is set by an NSE circular not stored yet (owner action O-11): the row says so instead of guessing a time.
NSE_SPECIAL_SESSIONS: tuple[dict[str, Any], ...] = (
    {"date": "2026-11-08", "name": "Muhurat trading (Diwali Laxmi Pujan)", "time": None, "circular": None,
     "note": "NSE timing by NSE circular (not stored yet: owner action O-11)"},
)
_ECO_EXTRA_CACHE: dict[str, tuple[float, Any]] = {}
_ECO_EXTRA_TTL_S = 3600.0


def _eco_id(kind: str, day: str) -> str:
    return f"{kind}-{day}"


def us_release_rows(events: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """The gold calendar's stored US releases (gold_events, ForexFactory weekly feed) as ECO rows: one row per date (the
    table keys rows by kind and date), High / Medium impact only, each release with its time, forecast, previous and,
    once stored, the actual print. Fed decisions stay on ECO's own federalreserve.gov rows."""
    by_day: dict[str, list[dict[str, Any]]] = {}
    s, e = start.isoformat(), end.isoformat()
    for ev in events:
        kind, day = str(ev.get("kind") or ""), str(ev.get("event_date") or "")[:10]
        if not kind.startswith("US_") or not (s <= day <= e) or str(ev.get("impact")) not in US_ECO_IMPACT:
            continue
        by_day.setdefault(day, []).append(ev)
    out = []
    for day, evs in sorted(by_day.items()):
        evs.sort(key=lambda x: (0 if x.get("impact") == "High" else 1, 0 if x.get("kind") == "US_NFP" else 1, str(x.get("time_ist") or "99:99")))
        items = [{"name": x.get("name"), "time": x.get("time_ist"), "impact": x.get("impact"), "forecast": x.get("forecast"),
                  "previous": x.get("previous"), "actual": x.get("actual")} for x in evs]

        def part(i: dict[str, Any]) -> str:
            nums = [f"{k} {i[k]}" for k in ("actual", "forecast", "previous") if i.get(k) not in (None, "")]
            return f"{i['name']}" + (f" {i['time']}" if i.get("time") else "") + (f" ({', '.join(nums)})" if nums else "")
        shown = items[:US_ECO_PER_DAY]
        high = [i for i in items if i.get("impact") == "High"]
        times = sorted(str(i["time"]) for i in (high or items) if i.get("time"))
        out.append({"id": _eco_id("US", day), "date": day, "time": times[0] if times else None, "kind": "US",
                    "what": "US data: " + " · ".join(part(i) for i in shown) + (f" · +{len(items) - len(shown)} more" if len(items) > len(shown) else ""),
                    "country": "US", "impact": "High" if high else "Medium", "items": items,
                    "source": "ForexFactory weekly calendar (stored as gold_events; forecast / previous as published, actual once stored)",
                    "moved": False})
    return out


def _prev_session(d: date, holidays: set[str]) -> date:
    from datetime import timedelta
    while d.weekday() >= 5 or d.isoformat() in holidays:
        d -= timedelta(days=1)
    return d


def fo_expiry_rows(listed: list[str], holidays: set[str], start: date, end: date) -> list[dict[str, Any]]:
    """NIFTY weekly and the monthly F&O expiries in [start, end], holiday-shifted. Each week's rule date is Tuesday (the
    month's last Tuesday is the monthly), moved to the previous session on an NSE holiday. A listed NIFTY expiry in
    that week (the NSE F&O bhavcopy's series) confirms or replaces the date; weeks beyond the listed ones (and past
    weeks) keep the rule date, labelled as the rule."""
    from datetime import timedelta
    listed_d = sorted({date.fromisoformat(x[:10]) for x in listed if x})
    weekly_hi = listed_d[0] if listed_d else None          # the end of the contiguous weekly listing
    for a, b in zip(listed_d, listed_d[1:], strict=False):
        if (b - a).days > 8:
            break
        weekly_hi = b
    rows: dict[str, dict[str, Any]] = {}
    d = start - timedelta(days=(start.weekday() - 1) % 7)            # the Tuesday on or before start
    while d <= end + timedelta(days=7):
        monthly = (d + timedelta(days=7)).month != d.month
        rule_day = _prev_session(d, holidays)
        got = [x for x in listed_d if d - timedelta(days=6) <= x <= d]
        if got:
            actual, source = got[-1], "NSE F&O bhavcopy (listed NIFTY expiries)"
        elif weekly_hi is not None and listed_d[0] <= d <= weekly_hi:
            actual, source = None, ""                                    # inside the listed weeks: NSE lists none this week
        else:
            actual, source = rule_day, FO_RULE
        if actual is not None and start <= actual <= end:
            moved = actual != d
            rows[actual.isoformat()] = {
                "id": _eco_id("EXPIRY", actual.isoformat()), "date": actual.isoformat(), "time": "15:30", "kind": "EXPIRY",
                "what": (FO_MONTHLY_WHAT if monthly else FO_WEEKLY_WHAT)
                + (f" (moved from Tue {d:%d %b}: NSE holiday)" if moved and d.isoformat() in holidays else ""),
                "country": "IN", "monthly": monthly, "moved": False, "shifted": moved, "moved_from": d.isoformat() if moved else None,
                "source": source}
        d += timedelta(days=7)
    return sorted(rows.values(), key=lambda r: r["date"])


def special_session_rows(mcx_sessions: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """Exchange special sessions (Muhurat) from dated constants: one row per date with each exchange's window and the
    circular it comes from (MCX's from shared/mcx_specs; NSE's when its circular is stored, else 'timing to confirm')."""
    by_day: dict[str, dict[str, Any]] = {}
    for x in NSE_SPECIAL_SESSIONS:
        by_day.setdefault(x["date"], {"name": x["name"], "parts": [], "sources": []})
        by_day[x["date"]]["parts"].append(f"NSE {x['time']} ({x['circular']})" if x.get("time") else f"NSE: {x['note']}")
        by_day[x["date"]]["sources"].append(x.get("circular") or "NSE circular pending (O-11)")
    for x in mcx_sessions:
        day = str(x.get("date"))
        by_day.setdefault(day, {"name": x.get("name"), "parts": [], "sources": []})
        by_day[day]["parts"].append(f"MCX: {x.get('note')}")
        by_day[day]["sources"].append("shared/mcx_specs (MCX circular)")
    s, e = start.isoformat(), end.isoformat()
    return [{"id": _eco_id("SESSION", day), "date": day, "time": None, "kind": "SESSION",
             "what": f"{v['name']} · " + " · ".join(v["parts"]), "country": "IN", "source": " + ".join(v["sources"]), "moved": False}
            for day, v in sorted(by_day.items()) if s <= day <= e]


async def _eco_cached(key: str, fn: Any) -> Any:
    """One-hour cache for the ECO extras (gold_events, listed expiries), shared with the commodity lane."""
    import time as _t
    hit = _ECO_EXTRA_CACHE.get(key)
    if hit and hit[0] > _t.time() - _ECO_EXTRA_TTL_S:
        return hit[1]
    val = await fn()
    _ECO_EXTRA_CACHE[key] = (_t.time(), val)
    return val


async def _gold_events_window(start: date, end: date) -> list[dict[str, Any]]:
    """gold_events rows in [start, end] via data-service (a stored table, no new fetch), cached an hour.
    The ECO feed and the EVTS commodity lane read the same cache keys."""
    async def gold() -> list[dict[str, Any]]:
        body = await http_client.get_json(f"{DATA_SVC}/db/gold/events", route="read",
                                          params={"from": start.isoformat(), "to": end.isoformat()})
        return list((body or {}).get("rows") or [])
    return await _eco_cached(f"gold:{start}:{end}", gold)


async def _eco_extra_inputs(start: date, end: date) -> tuple[list[dict[str, Any]], list[str], str | None, str | None]:
    """(gold_events rows, listed NIFTY expiries, errors) — each cached an hour; a missing source drops only its rows."""
    errs: dict[str, str] = {}

    async def chain() -> list[str]:
        body = await http_client.get_json(f"{DATA_SVC}/db/option-chain/NIFTY", route="read")
        return [str(x)[:10] for x in (body or {}).get("expiries") or []]

    events: list[dict[str, Any]] = []
    listed: list[str] = []
    try:
        events = await _gold_events_window(start, end)
    except http_client.UpstreamError as exc:
        errs["us"] = f"gold_events unavailable ({exc.status_code})"
    try:
        listed = await _eco_cached("chain", chain)
    except http_client.UpstreamError as exc:
        errs["expiries"] = f"listed expiries unavailable ({exc.status_code}): the rule fills every week"
    return events, listed, errs.get("us"), errs.get("expiries")


# ── Commodity calendar (final round R5-EVTS): the commodity desk's dated events, one lane on EVTS ────────────────
# Sources are dated constants and stored tables only (no new fetches; O-8: the MCX website is never read):
# shared/mcx_specs (MCX holidays + special sessions, each with its circular) and gold_events (the gold program's
# stored ForexFactory weekly calendar). Each row names its source; `covers_eco_id` is the eco-calendar row id that
# carries the same event, so EVTS draws each event once (the five-week grid's ◆ line skips covered ids).
# Context only: dates, trading hours and stored prints — never a call, no direction words, nothing feeds the Desk,
# the S1 shadow, an alert direction or a ticket price.
MCX_CLOSURE_WHAT: dict[str, str] = {"full": "MCX closed all day",
                                    "morning": "MCX morning session closed (the evening session trades)",
                                    "evening": "MCX evening session closed (the morning session trades)"}
_MCX_SPECS_SOURCE = "shared/mcx_specs (dated constants from MCX circulars)"
_GOLDEV_SOURCE = ("gold_events (ForexFactory weekly calendar, stored; forecast / previous as published, "
                  "actual once stored)")


def mcx_holiday_rows(start: date, end: date) -> list[dict[str, Any]]:
    """MCX trade holidays in [start, end] (weekday holidays with their closure kind: full / morning / evening).
    These are MCX's own closures — an NSE HOLIDAY row the same day is a different exchange, not a duplicate."""
    try:
        from shared.mcx_specs import MCX_HOLIDAYS_2026
    except ImportError:
        return []
    s, e = start.isoformat(), end.isoformat()
    return [{"id": f"MCXHOL-{d.isoformat()}", "date": d.isoformat(), "time": None, "kind": "MCX_HOLIDAY",
             "what": f"{name} · {MCX_CLOSURE_WHAT.get(closure, closure)}", "closure": closure, "circular": None,
             "impact": None, "forecast": None, "previous": None, "actual": None,
             "source": _MCX_SPECS_SOURCE, "covers_eco_id": None}
            for d, (name, closure) in sorted(MCX_HOLIDAYS_2026.items()) if s <= d.isoformat() <= e]


def mcx_session_rows(start: date, end: date) -> list[dict[str, Any]]:
    """MCX dated special sessions (a trading session on an otherwise-closed day). The eco calendar's SESSION row
    carries the same event (merged with NSE's), so the row covers it; when NSE holds its own session that day the
    `what` says so instead of listing it twice."""
    try:
        from shared.mcx_specs import SPECIAL_SESSIONS_2026
    except ImportError:
        return []
    nse_days = {x["date"] for x in NSE_SPECIAL_SESSIONS}
    s, e = start.isoformat(), end.isoformat()
    out: list[dict[str, Any]] = []
    for x in SPECIAL_SESSIONS_2026:
        day = str(x.get("date"))
        if not s <= day <= e:
            continue
        what = f"{x.get('name')} · MCX trades {x.get('opens')}–{x.get('closes')}"
        if x.get("pre_open"):
            what += f" (pre-open {x['pre_open']})"
        if day in nse_days:
            what += " · NSE holds its own session (timing: ECO)"
        out.append({"id": f"MCXSES-{day}", "date": day, "time": x.get("opens"), "kind": "MCX_SESSION", "what": what,
                    "closure": None, "circular": x.get("circular"), "impact": None, "forecast": None,
                    "previous": None, "actual": None, "source": _MCX_SPECS_SOURCE,
                    "covers_eco_id": _eco_id("SESSION", day)})
    return out


def gold_event_lane_rows(events: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """The gold program's stored calendar rows (gold_events) as lane rows: one per release, High / Medium impact
    only (Low stays on GOLD, M28). A US_* row's day is the eco calendar's aggregated `US-<date>` row and a FOMC
    row is its `FED-<date>` row (federalreserve.gov serves the same decision there) — covered, drawn once."""
    s, e = start.isoformat(), end.isoformat()
    out: list[dict[str, Any]] = []
    for ev in events:
        day, kind = str(ev.get("event_date") or "")[:10], str(ev.get("kind") or "")
        if not (s <= day <= e) or str(ev.get("impact")) not in US_ECO_IMPACT \
                or not (kind.startswith("US_") or kind == "FOMC"):
            continue
        slug = re.sub(r"[^A-Za-z0-9]+", "", str(ev.get("name") or ""))[:24]      # stable id: PK is (date, kind, name)
        out.append({"id": f"GOLDEV-{day}-{kind}-{slug}", "date": day, "time": ev.get("time_ist"),
                    "kind": "FED" if kind == "FOMC" else kind, "what": str(ev.get("name") or kind),
                    "closure": None, "circular": None, "impact": ev.get("impact"), "forecast": ev.get("forecast"),
                    "previous": ev.get("previous"), "actual": ev.get("actual"), "source": _GOLDEV_SOURCE,
                    "covers_eco_id": _eco_id("FED" if kind == "FOMC" else "US", day)})
    return out


def merge_commodity_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per id (first wins), sorted by date then time: the same event never twice in the lane."""
    seen: dict[str, dict[str, Any]] = {}
    for g in groups:
        for r in g:
            seen.setdefault(r["id"], r)
    return sorted(seen.values(), key=lambda r: (r["date"], r.get("time") or "99:99", r["id"]))


@router.get("/commodity-calendar")
async def commodity_calendar(back: int = Query(7, ge=0, le=120), ahead: int = Query(60, ge=1, le=366)) -> dict:
    """The commodity lane for EVTS (R5-EVTS): MCX trade holidays and special sessions (shared/mcx_specs, dated
    constants with their circulars) and the US releases the gold program already stores (gold_events) — stored
    tables and constants only, no new fetches. `covers_eco_ids` lists the eco-calendar row ids these rows carry,
    so the page draws each event once (the five-week grid's ◆ line skips them). Context: dates, hours and stored
    prints — it describes the calendar, never a call."""
    today = date.today()  # noqa: DTZ005,DTZ011 — local clock on purpose, the same clock eco_calendar uses
    start, end = today - _timedelta(days=back), today + _timedelta(days=ahead)
    err: str | None = None
    gold_rows: list[dict[str, Any]] = []
    try:
        gold_rows = await _gold_events_window(start, end)
    except http_client.UpstreamError as exc:
        err = f"gold_events unavailable ({exc.status_code}): MCX rows still shown"
    rows = merge_commodity_rows(mcx_holiday_rows(start, end), mcx_session_rows(start, end),
                                gold_event_lane_rows(gold_rows, start, end))
    try:
        from shared.mcx_specs import CALENDAR_YEARS
        years = list(CALENDAR_YEARS)
    except ImportError:
        years = []
    return {"today": today.isoformat(), "from": start.isoformat(), "to": end.isoformat(), "rows": rows,
            "covers_eco_ids": sorted({r["covers_eco_id"] for r in rows if r.get("covers_eco_id")}),
            "mcx_calendar_years": years, "badges": {"calendar": "context"},
            "note": ("dates, trading hours and stored prints only (context): the lane describes the calendar, "
                     "never a call"),
            "errors": {"us": err} if err else None}


@router.get("/eco-calendar")
async def eco_calendar(back: int = Query(14, ge=0, le=120), ahead: int = Query(60, ge=1, le=366)) -> dict:
    """Economic calendar for the last `back` and next `ahead` days: India CPI / WPI / IIP / core / GDP (official
    release calendars, data/reference/india_data_calendar.json), RBI policy decisions, US Fed decisions, NSE holidays,
    and (review M28) the US data releases the gold calendar stores (forecast / previous / actual), the F&O expiries
    (listed, holiday-shifted) and exchange special sessions (Muhurat). Every row has a unique `id`."""
    import json
    from datetime import date, timedelta
    from routers.research import _root
    try:
        ref = json.loads((_root() / "data" / "reference" / "india_data_calendar.json").read_text())
    except (OSError, ValueError):
        ref = {}
    try:
        rbi = json.loads((_root() / "data" / "reference" / "rbi_mpc.json").read_text()).get("meetings") or []
    except (OSError, ValueError):
        rbi = []
    try:
        await fomc()                               # fills the day-long cache with every meeting, past ones included
        fed = _FOMC_CACHE.get("rows") or []
    except HTTPException:
        fed = []                                   # Fed page unreachable: the India events still show
    holidays: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/market-holidays")
        if r.status_code == 200:
            holidays = r.json().get("holidays") or []
    except httpx.HTTPError:
        pass                                       # holidays are optional context
    today = date.today()  # noqa: DTZ005,DTZ011 — local clock on purpose (data-service computes its windows from it)
    start, end = today - timedelta(days=back), today + timedelta(days=ahead)
    events = build_eco_calendar(ref, rbi, fed, start, end, holidays)
    for e in events:
        e.setdefault("id", _eco_id(e["kind"], e["date"]))
    gold_rows, listed, us_err, exp_err = await _eco_extra_inputs(start, end)
    try:
        from shared.mcx_specs import SPECIAL_SESSIONS_2026 as _MCX_SPECIAL
    except ImportError:
        _MCX_SPECIAL = []
    hol = {h["date"] for h in holidays}
    extra = us_release_rows(gold_rows, start, end) + fo_expiry_rows(listed, hol, start, end) + special_session_rows(list(_MCX_SPECIAL), start, end)
    events = sorted(events + extra, key=lambda x: (x["date"], x.get("time") or ""))
    return {"today": today.isoformat(), "events": events, "sources": ref.get("sources") or {}, "note": ref.get("note"),
            "valid_until": ref.get("valid_until"), "fed_available": bool(fed),
            "us_available": us_err is None, "expiries_source": "listed + rule" if listed else "rule",
            "errors": {k: v for k, v in (("us", us_err), ("expiries", exp_err)) if v} or None,
            "holidays_known": bool(holidays), "badges": {"calendar": "context", "forecast": "context"},
            "note_us": "forecast / previous as ForexFactory publishes them (context): dates and consensus, never a call"}


@router.get("/gift-nifty")
async def gift_nifty() -> dict:
    """GIFT NIFTY and the implied gap for the next NIFTY open, via data-service."""
    try:
        return await http_client.get_json(f"{DATA_SVC}/db/gift-nifty", route="live", stale_for=120)
    except http_client.UpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/fii-dii-cash/refresh")
async def fii_dii_cash_refresh() -> dict:
    """Fetch today's FII / DII cash figures from NSE now (the 21:00 wrap calls this first), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as client:
            r = await client.post(f"{DATA_SVC}/db/fii-dii-cash/refresh")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/holding-changes")
async def holding_changes() -> dict:
    """Quarterly ownership shifts (promoter, FPI, MF, retail, holders), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/holding-changes")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/nifty-live")
async def nifty_live() -> dict:
    """NIFTY 50 from NSE (≈1 min delayed), via data-service."""
    try:
        return await http_client.get_json(f"{DATA_SVC}/db/nifty-live", route="live", stale_for=120)
    except http_client.UpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/index-intraday")
async def index_intraday(index: str = "NIFTY 50", minutes: int = 1) -> dict:
    """Intraday path of an NSE index (latest session) for the BRIEF / MKT chart, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-intraday", params={"index": index, "minutes": minutes})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/internals")
async def market_internals(day: str | None = None) -> dict:
    """Breadth and segment moves sampled through the session (data/nse_archive/internals), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/internals", params={"day": day} if day else None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/financials-latest")
async def financials_latest(symbols: str) -> dict:
    """Latest cached quarter (revenue / profit vs a year ago) per company, no network: for the wrap and alerts."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/financials-latest", params={"symbols": symbols})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.post("/financials/prefetch")
async def financials_prefetch(symbols: str) -> dict:
    """Queue companies for a background read of their results filings (e.g. a stock's peers)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.post(f"{DATA_SVC}/db/financials/prefetch", params={"symbols": symbols})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/fundamentals-screen")
async def fundamentals_screen(limit: int = Query(2500, ge=1, le=10000),
                              fields: str | None = CORE_FIELDS,
                              response: Response = None) -> dict:  # type: ignore[assignment]  # injected by FastAPI
    """EQS: every company with its results filings read — latest quarter growth, margin, valuation, industry.

    Payload budget (S2): floats rounded to 2 dp (display precision — cuts the ~584 KB
    body materially) and rows capped at `limit`; the default (2500) covers the whole
    ~1,600-company universe, so the EQS client-side filter keeps seeing everything.
    `fields=core` (W7): the same rows columnar — all 17 fields, values untouched; the
    per-row key repetition alone is ~60% of the body. SWR-cached per (limit, fields) (C-PERF-01).
    """
    served = await _FUNDAMENTALS.get((limit, fields), lambda: _fundamentals_screen(limit, fields))
    cache_headers(response, served)
    return served.value


async def _fundamentals_screen(limit: int, fields: str | None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/financials-universe")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    body = r.json()
    rows = body.get("rows", [])
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]
    for row in rows:
        for k, v in row.items():
            if isinstance(v, float):
                row[k] = round(v, 2)
    if fields == "core":
        meta = {k: v for k, v in body.items() if k != "rows"}
        return {**meta, **columnar(rows), "count": len(rows),
                **({"truncated": True} if truncated else {})}
    return {**body, "rows": rows, "count": len(rows), **({"truncated": True} if truncated else {})}


@router.get("/indices-live")
async def indices_live(names: str = "NIFTY 50,NIFTY BANK,INDIA VIX") -> dict:
    """NSE indices (one allIndices read) for the macro tape, via data-service."""
    try:
        return await http_client.get_json(f"{DATA_SVC}/db/indices-live", route="live", params={"names": names}, stale_for=120)
    except http_client.UpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def prefer_stored_contribution(live: dict[str, Any], stored: list[dict[str, Any]], fit_row: dict[str, Any] | None) -> dict[str, Any]:
    """m029: once the session is closed and the 19:25 drivers job has stored it, the stored (calibrated) attribution is
    the one number app-wide (MEMB, MOV, BRF and the wrap): each member's points / weight and `explained_points` come from
    index_contribution_daily and the fit; during the session the live rebuild stays, labelled. `explained_source` says
    which."""
    t = str(live.get("time") or "")
    try:
        day = datetime.strptime(t[:11], "%d-%b-%Y").date().isoformat()  # noqa: DTZ007 — NSE's IST wall date
    except ValueError:
        day = None
    rows = [r for r in stored if _day(r.get("date")) == day and _num(r.get("points")) is not None]
    if not day or t[12:17] < "15:30" or not rows:
        return live_on_stored_weights(live, stored, day) or {**live, "explained_source": live_rebuild_source(live)}
    by = {str(r.get("symbol")): r for r in rows}
    members = []
    for m in live.get("members") or []:
        st = by.get(str(m.get("symbol")))
        members.append({**m, "points": round(float(st["points"]), 2), "weight_pct": round(float(st["weight_pct"]), 2)} if st else m)
    members.sort(key=lambda m: -(m.get("points") or 0))
    explained = _num((fit_row or {}).get("explained_points"))
    summary = live.get("summary")
    if isinstance(summary, dict) and "top5_weight_pct" in summary:          # MEMB's tile: the same weights as the table
        ws = sorted((float(m["weight_pct"]) for m in members if _num(m.get("weight_pct")) is not None), reverse=True)
        summary = {**summary, "top5_weight_pct": round(sum(ws[:5]), 1)}
    return {**live, "members": members, **({"summary": summary} if summary is not None else {}),
            "explained_points": round(explained if explained is not None else sum(float(r["points"]) for r in rows), 1),
            "explained_source": f"stored attribution for {day} ({(fit_row or {}).get('weight_method') or rows[0].get('weight_method')}; "
                                "the same figure as MEMB)"}


STORED_WEIGHTS_MAX_AGE_DAYS = 7      # a weekend + a holiday; older stored weights are not used for today's points
STORED_WEIGHTS_MIN_COVER = 0.9       # share of the live members the stored weights must cover
STORED_WEIGHT_METHODS = frozenset({"rebuilt_calibrated", "rebuilt_fitted", "rebuilt_capped", "official_top10"})


def live_rebuild_source(live: dict[str, Any]) -> str:
    """The label of the uncalibrated live rebuild; for NIFTY BANK it also says the caps are not applied (M46)."""
    capped = " and NIFTY BANK's 20 % / 45 % caps not applied" if str(live.get("index") or "").upper() == "NIFTY BANK" else ""
    return f"live rebuild (free-float weights from filings; not calibrated{capped})"


def live_on_stored_weights(live: dict[str, Any], stored: list[dict[str, Any]], day: str | None) -> dict[str, Any] | None:
    """Checker 6 Nov (M46 / m029, in the session): today's points on the LAST STORED session's weights (capped and fitted
    for NIFTY BANK, calibrated to NSE's top-10 for NIFTY 50) drifted to that session's close by its stored returns,
    w_i ∝ w_i,d−1 × (1 + r_i,d−1), times the live prices: points_i = L_{d−1} × w_i × change_i. The uncapped live rebuild
    (ICICIBANK 27.5 % of NIFTY BANK at 09:07 on 6 Nov, above the 20 % cap) is used only when no recent stored session
    covers the members. None = keep the live rebuild."""
    if not day:
        return None
    prev_days = sorted({d for d in (_day(r.get("date")) for r in stored) if d and d < day})
    if not prev_days:
        return None
    sd = prev_days[-1]
    try:
        if (date.fromisoformat(day) - date.fromisoformat(sd)).days > STORED_WEIGHTS_MAX_AGE_DAYS:
            return None
    except ValueError:
        return None
    method = next((str(r.get("weight_method")) for r in stored if _day(r.get("date")) == sd and r.get("weight_method")), "")
    if method not in STORED_WEIGHT_METHODS:      # a plain 'rebuilt' row is the same uncapped, uncalibrated rebuild: no gain
        return None
    w: dict[str, float] = {}
    for r in stored:
        wp, rp = _num(r.get("weight_pct")), _num(r.get("ret_pct"))
        if _day(r.get("date")) == sd and wp is not None and rp is not None and wp > 0:
            w[str(r.get("symbol"))] = wp * (1 + rp / 100)
    members = live.get("members") or []
    if not members or not w:
        return None
    covered = [m for m in members if str(m.get("symbol")) in w and _num(m.get("change_pct")) is not None]
    if len(covered) < STORED_WEIGHTS_MIN_COVER * len(members):
        return None
    last, chg = _num(live.get("last")), _num(live.get("change"))
    if last is None or chg is None:
        return None
    prev_level = last - chg
    tot = sum(w[str(m["symbol"])] for m in covered)
    out = []
    for m in members:
        sym = str(m.get("symbol"))
        c = _num(m.get("change_pct"))
        if sym in w and c is not None and tot > 0:
            wt = w[sym] / tot
            out.append({**m, "weight_pct": round(wt * 100, 2), "points": round(prev_level * wt * c / 100, 2)})
        else:
            out.append({**m, "weight_pct": None, "points": None})
    out.sort(key=lambda m: -(m.get("points") or 0))
    summary = live.get("summary")
    if isinstance(summary, dict) and "top5_weight_pct" in summary:
        ws = sorted((float(m["weight_pct"]) for m in out if m.get("weight_pct") is not None), reverse=True)
        summary = {**summary, "top5_weight_pct": round(sum(ws[:5]), 1)}
    return {**live, "members": out, **({"summary": summary} if summary is not None else {}),
            "explained_points": round(sum(m["points"] or 0 for m in out), 1),
            "explained_source": f"live prices × the stored weights of {sd} ({method}, drifted to that close)"}


@router.get("/index-contribution")
async def index_contribution(index: str = "NIFTY 50") -> dict:
    """Who moved the index today, in points, via data-service: the live rebuild in the session, the stored calibrated
    attribution once the close is stored (m029: one 'explained' number app-wide)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-contribution", params={"index": index})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    live = r.json()
    name = str(index).strip().upper()
    if name not in DRIVER_INDICES:
        return live
    reads = _DriverReads()
    stored = await reads.get("contribution", index=name, days=1)
    fit = await reads.get("fit", index=name, days=1)
    return prefer_stored_contribution(live, stored, fit[-1] if fit else None)


@router.get("/index-valuation")
async def index_valuation() -> dict:
    """NSE's P/E, P/B and dividend yield per index, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-valuation")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/index-valuation-history")
async def index_valuation_history(index: str = Query("NIFTY 50", max_length=40),
                                  metric: str = Query("pe", pattern="^(pe|pb|dy|rel)$")) -> dict:
    """Weekly P/E, P/B or dividend-yield history of one index (NSE daily index files), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-valuation-history", params={"index": index, "metric": metric})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/index-memb")
async def index_memb(index: str = Query("NIFTY 50", pattern="^(NIFTY 50|NIFTY BANK|NIFTY NEXT 50|NIFTY IT)$")) -> dict:
    """MEMB: index members with weight, today's points, returns, distance from high, P/E and growth, via data-service.
    Once the close is stored, each member's weight / points and the 'explained' figure are the stored attribution's
    (m029 / M46: the live rebuild is uncapped for NIFTY BANK — HDFCBANK 30.5 % — while the stored weights are capped)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-memb", params={"index": index})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    live = r.json()
    reads = _DriverReads()
    stored = await reads.get("contribution", index=index, days=1)
    fit = await reads.get("fit", index=index, days=1)
    return memb_outlier_flags(prefer_stored_contribution(live, stored, fit[-1] if fit else None))


GROWTH_OUTLIER_PCT = 200.0          # m027: COALINDIA profit +261 % / revenue +200 % y/y — check the filing (one-off, base effect)
PE_DISTORTED = (3.0, 150.0)         # ETERNAL 669×, TMPV 1.4×: a filing-based P/E outside this range describes the filing, not value


def memb_outlier_flags(body: dict[str, Any]) -> dict[str, Any]:
    """m027: per-member `flags` (heuristic) on figures a filing distorts: |profit or revenue growth| above 200 % y/y, or a
    filing-based P/E below 3× or above 150×. The numbers stay; the flag says read the filing first."""
    out = []
    for m in body.get("members") or []:
        flags = []
        for k in ("pat_yoy", "revenue_yoy"):
            v = _num(m.get(k))
            if v is not None and abs(v) > GROWTH_OUTLIER_PCT:
                flags.append(f"{k}_outlier")
        pe = _num(m.get("pe"))
        if pe is not None and pe > 0 and not (PE_DISTORTED[0] <= pe <= PE_DISTORTED[1]):
            flags.append("pe_distorted")
        out.append({**m, "flags": flags})
    return {**body, "members": out, "flag_badge": "heuristic",
            "flag_rule": f"growth beyond ±{GROWTH_OUTLIER_PCT:.0f} % y/y or a P/E outside {PE_DISTORTED[0]:.0f}–{PE_DISTORTED[1]:.0f}×: "
                         "read the filing (one-off items, a base effect, a loss year) before the number"}


@router.get("/index-daily")
async def index_daily(symbol: str = Query("NIFTY50", pattern="^[A-Z0-9]{3,20}$"), days: int = Query(1500, ge=5, le=6000)) -> dict:
    """Daily index closes (NIFTY50 …) for relative-strength charts, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-daily", params={"symbol": symbol, "days": days})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/surveillance")
async def surveillance(symbols: str = Query("", max_length=8000), all_flagged: bool = False) -> dict:
    """NSE surveillance / risk flags per stock (ASM, GSM, ESM, bands, T2T, F&O ban), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/surveillance", params={"symbols": symbols, "all_flagged": all_flagged})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


def mark_post_event(rows: list[dict[str, Any]], releases: list[dict[str, Any]], fo_date: str | None) -> list[dict[str, Any]]:
    """m043: a row whose results were filed before the F&O file's close (an intraday reporter, e.g. M&M at 12:57 on
    5 Nov 2026) is priced from post-event options: `post_event` true, `filed_at`, and a note; its event-move figures
    describe leftover volatility, not a priced event. Release times are nse_results' (the results filing)."""
    if not fo_date:
        return rows
    close = f"{fo_date} 15:30"
    filed: dict[str, str] = {}
    for r in releases:
        t = str(r.get("released_at") or "")
        if t and t < close and r.get("symbol"):
            filed[str(r["symbol"])] = max(filed.get(str(r["symbol"]), ""), t)
    out = []
    for row in rows:
        t = filed.get(str(row.get("symbol")))
        rd = str(row.get("results_date") or "")
        if t and rd and t[:10] >= (date.fromisoformat(rd[:10]) - _timedelta(days=3)).isoformat():
            row = {**row, "post_event": True, "filed_at": t,
                   "post_event_note": f"results filed {t[11:16]} on {t[:10]}, before the {fo_date} close: these options are post-event"}
        else:
            row = {**row, "post_event": False}
        out.append(row)
    return out


async def _fetch_implied_moves(days: int) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/results-implied-moves", params={"days": days})
            releases: list[dict[str, Any]] = []
            try:                                         # optional: without release times nothing is marked post-event
                rr = await client.get(f"{DATA_SVC}/db/results-recent", params={"days": 4})
                releases = rr.json().get("rows", []) if rr.status_code == 200 else []
            except Exception:  # noqa: BLE001
                releases = []
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    body = r.json()
    return {**body, "rows": mark_post_event(body.get("rows") or [], releases, body.get("fo_date"))}


@router.get("/results-implied-moves")
async def results_implied_moves(days: int = Query(10, ge=1, le=30),
                                response: Response = None) -> dict:  # type: ignore[assignment]  # injected by FastAPI
    """F&O stocks reporting soon: the results-day move their options price vs their usual reaction, via data-service.
    SWR-cached (C-PERF-01)."""
    served = await _IMPLIED_MOVES.get((days, _today()), lambda: _fetch_implied_moves(days))
    cache_headers(response, served)
    return served.value


@router.get("/yield-gap")
async def yield_gap() -> dict:
    """NIFTY earnings yield minus India's 10-year bond yield, monthly, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/yield-gap")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


@router.get("/seasonality")
async def seasonality(symbol: str = Query("NIFTY 50", max_length=40)) -> dict:
    """SEAG: month-by-month returns of an index or stock, with per-month averages and hit rates, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/seasonality", params={"symbol": symbol})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


def results_filed_since_close(prev_items: list[dict], today_items: list[dict], close: str = "15:30") -> dict[str, str]:
    """Symbol → first filing time ('YYYY-MM-DD HH:MM') of results filed after the previous session's close or today."""
    filed: dict[str, str] = {}
    for items, after in ((prev_items, close), (today_items, "00:00")):
        for f in items:
            ts = f.get("time") or ""
            if f.get("category") == "results" and ts[11:16] >= after and f.get("symbol") and f["symbol"] not in filed:
                filed[f["symbol"]] = ts[:16]
    return filed


def numbers_status(sym: str, fresh: dict, cached: dict) -> str:
    """'ok' = this filing's numbers are read; 'not_on_feed' = the company was read but NSE's results feed has no
    newer quarter yet (the XBRL often lands hours after the PDF); 'pending' = not read yet."""
    return "ok" if sym in fresh else "not_on_feed" if sym in cached else "pending"


def reaction_phase(now: datetime) -> str:
    """'session' from 09:15 on a weekday (live quotes are today's), 'preopen' 09:00–09:15 (the auction price is
    today's), 'closed' otherwise (quotes still show the previous session: no reaction to show yet)."""
    if now.weekday() >= 5:
        return "closed"
    hm = (now.hour, now.minute)
    return "session" if hm >= (9, 15) else "preopen" if hm >= (9, 0) else "closed"


def reacting_rows(filed: dict[str, str], typical: dict[str, dict], chg: dict[str, float],
                  nifty_pct: float | None = None) -> list[dict]:
    """Today's move against the typical results-day move; biggest surprise first (no history → |move| ÷ 3%)."""
    rows = []
    for s in sorted(filed):
        t = (typical.get(s) or {}).get("typical_move_pct")
        c = chg.get(s)
        c = round(c, 2) if c is not None else None
        rows.append({"symbol": s, "filed_at": filed[s], "change_pct": c, "typical_move_pct": t,
                     "vs_nifty_pct": round(c - nifty_pct, 2) if c is not None and nifty_pct is not None else None,
                     "vs_typical": round(abs(c) / t, 2) if c is not None and t else None})
    rows.sort(key=lambda r: -(r["vs_typical"] if r["vs_typical"] is not None else abs(r["change_pct"] or 0) / 3))
    return rows


# Prices (live NSE program round 2, L2-API): every filer and the NIFTY 50 are priced by the live NSE hub (routers/live.py:
# Breeze websocket tick -> NSE website copy -> the stored EOD close, each row with its source / state / age), never
# Yahoo. A change counts as TODAY's reaction only when the row is live or delayed, or the session's close dated today; a
# stale EOD row carries the previous session's change and is never shown as today's move. On an NSE holiday (the hub's
# market says the last session was another day) there is no reaction yet.
REACT_MOVE_STATES = frozenset({"live", "delayed", "closed"})
REACT_INDEX = "NIFTY 50"
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _row_day(row: dict[str, Any]) -> str | None:
    """The session date a hub row's price belongs to: its ltt's IST date (the contract stamps +05:30), else ``date``."""
    for v in (row.get("ltt"), row.get("date")):
        if isinstance(v, str) and _ISO_DAY.match(v):
            return v[:10]
    return None


def todays_move(row: Any, today: str) -> float | None:
    """A live-hub row's change_pct when it is TODAY's move, else None (stale / unavailable rows, a close of another
    session, a row without a finite change)."""
    if not isinstance(row, dict) or row.get("state") not in REACT_MOVE_STATES or row.get("price") is None:
        return None
    c = row.get("change_pct")
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c):
        return None
    day = _row_day(row)
    if day != today and (day is not None or row.get("state") == "closed"):
        return None
    return float(c)


def price_fields(row: Any, *, reason: str | None = None) -> dict[str, Any]:
    """source / state / age_s / ltt (+ reason) of the price behind a results-reacting row (all None when there is none)."""
    if not isinstance(row, dict):
        return {"source": None, "state": None, "age_s": None, "ltt": None, **({"reason": reason} if reason else {})}
    out = {"source": row.get("source"), "state": row.get("state"), "age_s": row.get("age_s"), "ltt": row.get("ltt")}
    why = reason or row.get("reason")
    if why:
        out["reason"] = str(why)[:200]
    return out


def preopen_fields(stamp: str, now: datetime) -> dict[str, Any]:
    """The pre-open auction price's labels: NSE's website copy, aged from the book's own timestamp ('05-Nov-2026 09:07:58')."""
    try:
        at = datetime.strptime(stamp[:20], "%d-%b-%Y %H:%M:%S")  # noqa: DTZ007 — NSE's IST wall time, compared with the local clock
    except ValueError:
        return {"source": "nse_api", "state": "delayed", "age_s": None, "ltt": None,
                "reason": "NSE pre-open auction price (IEP); the session opens 09:15"}
    age = max(0.0, (now - at).total_seconds())
    return {"source": "nse_api", "state": "delayed" if age <= 90 else "stale", "age_s": round(age, 1),
            "ltt": at.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
            "reason": f"NSE pre-open auction price (IEP) at {at:%H:%M:%S}; the session opens 09:15"}


def _react_now() -> datetime:
    """The local wall clock (IST on the owner's Mac, the clock data-service computes its windows from); tests pin it."""
    return datetime.now()  # noqa: DTZ005 — local clock on purpose


def price_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Which sources priced the rows and the oldest price age: the panel's SourceChip."""
    counts: dict[str, int] = {}
    for r in rows:
        k = r.get("source") or "none"
        counts[k] = counts.get(k, 0) + 1
    ages = [r["age_s"] for r in rows if isinstance(r.get("age_s"), (int, float)) and r.get("change_pct") is not None]
    return {"sources": counts, "max_age_s": max(ages) if ages else None}


TYPICAL_CHUNK = 150                    # data-service's /db/typical-results-moves reads at most 200 symbols a request


def session_labels(now: datetime, today: str) -> dict[str, Any]:
    """m042: the reaction's own date (today's session, not the window start `since`) and whether it is still trading:
    after 15:30 the moves are the session's close ('reacted today'), not live."""
    open_ = (9, 15) <= (now.hour, now.minute) < (15, 30)
    return {"data_date": today, "session_open": open_,
            "label": "reacting today · live session" if open_ else "reacted today · session closed (end-of-day moves)"}


@router.get("/results-reacting")
async def results_reacting(response: Response = None) -> dict:  # type: ignore[assignment]  # injected by FastAPI
    """Cached at most 60 s as before; now single flight with a background refresh after 30 s (C-PERF-01)."""
    served = await _REACTING.get("reacting", _results_reacting)
    cache_headers(response, served)
    return served.value


async def _results_reacting() -> dict:
    """Results filed since the last close (after 15:30 on the previous trading day, or today), with today's live move
    against the stock's typical results-day move. Filings: NSE announcements (results category); prices: the live NSE
    hub (Breeze tick -> NSE website -> stored close, with source / state / age per row; never Yahoo), the pre-open
    auction before 09:15; typical moves: past reactions in nse_results."""
    import asyncio
    from datetime import timedelta
    now = _react_now()
    today = now.date()
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as client:
        a_prev, a_today = await asyncio.gather(
            client.get(f"{DATA_SVC}/db/announcements", params={"day": prev.isoformat()}),
            client.get(f"{DATA_SVC}/db/announcements"), return_exceptions=True)
        def items(resp: Any) -> list[dict]:
            return [] if isinstance(resp, Exception) or resp.status_code != 200 else resp.json().get("items", [])
        filed = results_filed_since_close(items(a_prev), items(a_today))
        if not filed:
            return {"rows": [], "since": f"{prev.isoformat()} 15:30"}
        syms = sorted(filed)
        chunks = [syms[i:i + TYPICAL_CHUNK] for i in range(0, len(syms), TYPICAL_CHUNK)]
        got = await asyncio.gather(
            client.get(f"{DATA_SVC}/db/financials-latest", params={"symbols": ",".join(syms)}),
            *(client.get(f"{DATA_SVC}/db/typical-results-moves", params={"symbols": ",".join(c)}) for c in chunks),
            return_exceptions=True)
        fl, tms = got[0], got[1:]
        fin_latest = fl.json().get("latest", {}) if not isinstance(fl, Exception) and fl.status_code == 200 else {}
        # the numbers for this filing: cached quarter filed since the previous close; queue the rest for a background read
        fresh = {s: f for s, f in fin_latest.items() if (f.get("filed_at") or "")[:16].replace("T", " ") >= f"{prev.isoformat()} 15:30"}
        missing = [s for s in syms if s not in fresh]
        if missing:
            try:
                await client.post(f"{DATA_SVC}/db/financials/prefetch", params={"symbols": ",".join(missing)})
            except httpx.HTTPError:
                pass
    typical: dict[str, Any] = {}
    for tm in tms:                                     # every chunk: a failed one leaves only its own names blank
        if not isinstance(tm, Exception) and tm.status_code == 200:
            typical.update(tm.json().get("moves", {}))
    phase = reaction_phase(now)
    names: dict[str, str] = {}
    for s in syms:
        try:
            names[s] = _live.normalize_symbol(s)
        except ValueError:
            continue                                   # an announcement code that is not an NSE symbol: never priced
    quotes: dict[str, Any] = {}
    market: dict[str, Any] | None = None
    if phase == "session":
        snap = await _live.hub().quotes(list(dict.fromkeys([*names.values(), REACT_INDEX])))
        quotes, market = snap.payload["quotes"], snap.payload["market"]
        if market.get("state") == "closed" and market.get("session_date") not in (None, today.isoformat()):
            phase = "holiday"                          # NSE's holiday master: no session today, no reaction yet
    base = {"since": f"{prev.isoformat()} 15:30", "market": market}
    chg: dict[str, float] = {}
    if phase != "session":
        # before 09:15 live quotes still show yesterday's move: use today's pre-open auction price, or nothing
        labels: dict[str, dict[str, Any]] = {}
        if phase == "preopen":
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                    po = (await client.get(f"{DATA_SVC}/db/preopen", params={"key": "ALL"})).json()
                stamp = str(po.get("timestamp", ""))
                if stamp[:11] == now.strftime("%d-%b-%Y"):
                    chg = {r["symbol"]: r["change_pct"] for r in po.get("rows") or [] if r.get("symbol") in filed and r.get("change_pct") is not None}
                    labels = {s: preopen_fields(stamp, now) for s in chg}
            except (httpx.HTTPError, ValueError):
                chg = {}
        why = {"preopen": "no NSE pre-open auction price for it (yet)", "holiday": "no NSE session today: no reaction yet"}.get(
            phase, "the session has not opened: no reaction yet")
        rows = reacting_rows(filed, typical, chg, None)
        for r in rows:
            f = fresh.get(r["symbol"]) or {}
            r.update(revenue_yoy=f.get("revenue_yoy"), pat_yoy=f.get("pat_yoy"), pat_turn=f.get("pat_yoy_turn"), quarter=f.get("period_end"),
                     numbers=numbers_status(r["symbol"], fresh, fin_latest))
            r.update(labels.get(r["symbol"]) or price_fields(None, reason=why))
        return {"rows": rows, "phase": "closed" if phase == "holiday" else phase, "nifty_change_pct": None, **base,
                "nifty": price_fields(None, reason=why), "price_source": price_summary(rows),
                "as_of": now.isoformat(timespec="seconds"), "data_date": None, "session_open": False,
                "label": "no reaction yet (the session has not opened)" if phase != "holiday" else "no NSE session today"}
    today_s = today.isoformat()
    prices: dict[str, dict[str, Any]] = {}
    for s in syms:
        row = quotes.get(names[s]) if s in names else None
        prices[s] = price_fields(row, reason=None if s in names else "not an NSE symbol")
        c = todays_move(row, today_s)
        if c is not None:
            chg[s] = c
    nifty_row = quotes.get(REACT_INDEX)
    nifty = todays_move(nifty_row, today_s)
    # filed after today's close: today's move happened before the results, so there is no reaction to show yet
    after_close = f"{today_s} 15:30"
    chg = {s: v for s, v in chg.items() if filed[s] < after_close}
    rows = reacting_rows(filed, typical, chg, nifty)
    for r in rows:
        r["reacts_next_session"] = r["filed_at"] >= after_close
        f = fresh.get(r["symbol"]) or {}
        r.update(revenue_yoy=f.get("revenue_yoy"), pat_yoy=f.get("pat_yoy"), pat_turn=f.get("pat_yoy_turn"), quarter=f.get("period_end"),
                 numbers=numbers_status(r["symbol"], fresh, fin_latest))
        r.update(prices[r["symbol"]])
    return {"rows": rows, "phase": phase, "nifty_change_pct": nifty, **base, "nifty": price_fields(nifty_row),
            "price_source": price_summary(rows), "as_of": now.isoformat(timespec="seconds"), **session_labels(now, today_s)}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Terminal v2 — NIFTY drivers (PLAN 1.2, B3): "who drives NIFTY", from the nightly point-in-time tables
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# data-service (B1 `index_drivers/`) writes `index_constituents_daily`, `index_weights_daily`,
# `index_contribution_daily`, `index_contribution_fit`, `index_driver_state` at 19:25 and serves them as
# /db/index-drivers/{contribution|fit|state|weights|constituents}?index=&from=&to=  (rows ascending by date).
# This module only SLICES: points are additive (L_{d-1} × w × r), so every horizon is a sum — the prototype's
# `summarise` math (reports/terminal_v2/R-DRIVERS/evidence/drivers_proto.py) reused as pure functions below.
# DuckDB only on the request path (through one SWR cache); nothing here enters momentum.py, decision_desk.py,
# a directional alert or the ticket. Badges: members / sectors / concentration `arithmetic` (an identity with its
# residual shown), regime / breadth / monthly leader `context`; no colour on the leader; every regime sentence ends
# "describes, does not predict".
import math as _math  # noqa: E402
import sys as _sys  # noqa: E402
from collections import defaultdict as _defaultdict  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

from cache import TTLCache as _TTLCache  # noqa: E402
from errors import fail as _fail  # noqa: E402
from cache import merge_served as _merge_served  # noqa: E402

for _p in (_Path(__file__).resolve().parents[3], _Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in _sys.path:
        _sys.path.insert(0, str(_p))

from shared.http_client import UpstreamError as _UpstreamError  # noqa: E402
from shared.http_client import get_json as _get_json  # noqa: E402

DRIVERS_STORE = SWRCache("market.index_drivers", max_items=128, refresh_after=60.0, max_age=600.0)
_drivers_ttl = _TTLCache("market.index_drivers.down", max_items=32, default_ttl=15.0)
DRIVER_INDICES = ("NIFTY 50", "NIFTY BANK", "NIFTY NEXT 50", "NIFTY IT")   # NEXT 50 / IT only on O-T12
HORIZONS: dict[str, int | str] = {"1d": 1, "5d": 5, "1m": 21, "3m": 63, "ytd": "ytd", "since_change": "since_change"}
DRIVER_DESCRIBES = "describes, does not predict"
FIT_DEGRADED_MAE = 25.0                       # PLAN G3: 60-session MAE ≤ 25 pts else fit.degraded
BREADTH_NARROW_PP, BREADTH_BROAD_PP = -1.0, 1.0
DRIVER_BADGES = {"members": "arithmetic", "sectors": "arithmetic", "concentration": "arithmetic", "fit": "arithmetic",
                 "driver": "context", "breadth": "context", "monthly": "context"}


class _DriversStoreUnavailable(RuntimeError):
    pass


async def _drivers_fetch(path: str, params: dict[str, Any]) -> Any:
    try:
        return await _get_json(f"{DATA_SVC}{path}", route="read", params=params)
    except _UpstreamError as exc:
        if exc.status_code == 404:
            raise _DriversStoreUnavailable("data-service has no index_drivers tables yet (404)") from exc
        raise _DriversStoreUnavailable(f"data-service {exc.status_code}: {exc.detail[:120]}") from exc


class _DriverReads:
    def __init__(self) -> None:
        self.served: list[Any] = []
        self.errors: dict[str, str] = {}

    async def get(self, table: str, **params: Any) -> list[dict[str, Any]]:
        return await self.get_path(f"/db/index-drivers/{table}", **params)

    async def get_path(self, path: str, **params: Any) -> list[dict[str, Any]]:
        clean = {k: v for k, v in params.items() if v is not None}
        key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
        down = _drivers_ttl.get(f"down:{path}")
        if down is not None:
            self.errors[path] = str(down)
            return []
        try:
            served = await DRIVERS_STORE.get(key, lambda: _drivers_fetch(path, clean))
        except _DriversStoreUnavailable as exc:
            _drivers_ttl.set(f"down:{path}", str(exc))
            self.errors[path] = str(exc)
            return []
        except Exception as exc:  # noqa: BLE001
            self.errors[path] = type(exc).__name__
            return []
        self.served.append(served)
        return _driver_rows(served.value)

    def headers(self, response: Response | None) -> None:
        cache_headers(response, _merge_served(self.served))

    def meta(self) -> dict[str, Any]:
        return {"ok": not self.errors, "store_errors": dict(self.errors)}


def _driver_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("rows"), list):
        return [r for r in payload["rows"] if isinstance(r, dict)]
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], list) and isinstance(payload.get("columns"), list):
        return [dict(zip(payload["columns"], row, strict=False)) for row in data]
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if _math.isfinite(x) else None


def _day(v: Any) -> str | None:
    s = str(v) if v is not None else ""
    return s[:10] if len(s) >= 10 else None


def _check_index(index: str) -> str:
    name = index.strip().upper()
    if name not in DRIVER_INDICES:
        _fail(422, "invalid", f"unknown index {index!r}", "NIFTY 50 or NIFTY BANK (NEXT 50 / IT on O-T12)")
    return name


# ── pure slicing (unit-tested) ───────────────────────────────────────────────────────────────────────────────
def horizon_window(dates: list[str], horizon: str, change_date: str | None = None) -> list[str]:
    """The session dates a horizon covers (ascending): the last n sessions, the calendar year to date, or since the
    driver changed (falls back to 20 sessions when no change date is known)."""
    if not dates:
        return []
    spec = HORIZONS[horizon]
    if isinstance(spec, int):
        return dates[-spec:]
    if spec == "ytd":
        year = dates[-1][:4]
        return [d for d in dates if d[:4] == year]
    if change_date:
        return [d for d in dates if d >= change_date]
    return dates[-20:]


def slice_contributions(contrib: list[dict[str, Any]], fit: list[dict[str, Any]], weights: list[dict[str, Any]],
                        window: list[str]) -> dict[str, Any]:
    """Members, sectors, concentration and breadth over ``window`` (the prototype's `summarise` for one horizon)."""
    wset = set(window)
    rows = [r for r in contrib if _day(r.get("date")) in wset]
    pts: dict[str, float] = _defaultdict(float)
    growth: dict[str, float] = _defaultdict(lambda: 1.0)
    industry: dict[str, str] = {}
    flagged: set[str] = set()
    for r in rows:
        s = str(r.get("symbol") or "")
        if not s:
            continue
        p, ret = _num(r.get("points")), _num(r.get("ret_pct"))
        if r.get("flag"):
            flagged.add(s)
        if p is not None:
            pts[s] += p
        if ret is not None:
            growth[s] *= 1 + ret / 100
        if r.get("industry"):
            industry[s] = str(r["industry"])
    last_day = window[-1] if window else None
    w_latest: dict[str, float] = {}
    for r in rows:                                   # the weight each point was computed with (one method per day)
        if _day(r.get("date")) == last_day and _num(r.get("weight_pct")) is not None:
            w_latest[str(r.get("symbol"))] = float(r["weight_pct"])
    rank: dict[str, int] = {}
    for r in weights:                                # members without a contribution row: the best stored method
        sym = str(r.get("symbol"))
        if r.get("industry"):
            industry.setdefault(sym, str(r["industry"]))
        if sym in w_latest and sym not in rank:
            continue
        if _day(r.get("date")) == last_day or last_day is None:
            w = _num(r.get("weight_pct"))
            pr = METHOD_RANK.get(str(r.get("method")), 9)
            if w is not None and pr < rank.get(sym, 99):
                w_latest[sym], rank[sym] = w, pr
    total_abs = sum(abs(v) for v in pts.values())
    members = []
    for s, p in pts.items():
        members.append({"symbol": s, "industry": industry.get(s), "weight_pct": w_latest.get(s),
                        "ret_pct": round((growth[s] - 1) * 100, 2) if s in growth else None, "points": round(p, 1),
                        "share_abs": round(abs(p) / total_abs, 4) if total_abs else None, "flag": s in flagged or None})
    members.sort(key=lambda m: -m["points"])
    sec_pts: dict[str, float] = _defaultdict(float)
    sec_w: dict[str, float] = _defaultdict(float)
    for m in members:
        ind = m["industry"] or "Unknown"
        sec_pts[ind] += m["points"]
        sec_w[ind] += m["weight_pct"] or 0.0
    sectors = sorted(({"industry": k, "points": round(v, 1), "weight_pct": round(sec_w[k], 2)} for k, v in sec_pts.items()),
                     key=lambda x: -x["points"])
    abs_sorted = sorted((abs(v) for v in pts.values()), reverse=True)
    top5_abs = sum(abs_sorted[:5]) / total_abs if total_abs else None
    hhi_c = sum((a / total_abs) ** 2 for a in abs_sorted) if total_abs else None
    wsum = sum(w_latest.values())
    hhi_w = sum((w / wsum) ** 2 for w in w_latest.values()) if wsum else None
    top5_w = sum(sorted(w_latest.values(), reverse=True)[:5]) if w_latest else None
    fit_rows = [f for f in fit if _day(f.get("date")) in wset]
    actual = sum(_num(f.get("actual_points")) or 0 for f in fit_rows) if fit_rows else None
    explained = round(sum(pts.values()), 1)
    first_level = None
    for f in sorted(fit_rows, key=lambda x: _day(x.get("date")) or ""):
        first_level = _num(f.get("prev_index_level"))
        if first_level:
            break
    if first_level is None:
        for r in sorted(rows, key=lambda x: _day(x.get("date")) or ""):
            first_level = _num(r.get("prev_index_level"))
            if first_level:
                break
    cw = (actual / first_level * 100) if (actual is not None and first_level) else None
    rets = [(growth[s] - 1) * 100 for s in growth]
    ew = sum(rets) / len(rets) if rets else None
    return {
        "index_move_pts": round(actual, 1) if actual is not None else None, "explained_pts": explained,
        "residual_pts": round(actual - explained, 1) if actual is not None else None,
        "members": members, "sectors": sectors,
        "concentration": {"top5_abs_share": round(top5_abs, 3) if top5_abs is not None else None,
                          "hhi_contrib": round(hhi_c, 4) if hhi_c is not None else None,
                          "weight_hhi": round(hhi_w, 4) if hhi_w is not None else None,
                          "effective_n": round(1 / hhi_w, 1) if hhi_w else None,
                          "top5_weight_pct": round(top5_w, 2) if top5_w is not None else None},
        "breadth": {"ew_pct": round(ew, 2) if ew is not None else None, "cw_pct": round(cw, 2) if cw is not None else None,
                    "ew_minus_cw_pp": round(ew - cw, 2) if (ew is not None and cw is not None) else None,
                    "up": sum(1 for r in rets if r > 0), "down": sum(1 for r in rets if r < 0),
                    "word": breadth_word(ew - cw) if (ew is not None and cw is not None) else None},
        "members_priced": len(pts),
    }


def breadth_word(ew_minus_cw_pp: float | None) -> str | None:
    """Thresholded words, no colour: narrow below −1 pp, broad above +1 pp, else even (R-DRIVERS §3)."""
    if ew_minus_cw_pp is None:
        return None
    if ew_minus_cw_pp < BREADTH_NARROW_PP:
        return "narrow"
    if ew_minus_cw_pp > BREADTH_BROAD_PP:
        return "broad"
    return "even"


def fit_summary(fit: list[dict[str, Any]], sessions: int = 60) -> dict[str, Any]:
    rows = sorted((f for f in fit if _day(f.get("date"))), key=lambda f: _day(f.get("date")) or "")[-sessions:]
    res = [(_num(f.get("actual_points")), _num(f.get("residual_points"))) for f in rows]
    res = [(a, r) for a, r in res if a is not None and r is not None]
    if not res:
        return {"mae_60s": None, "r2_60s": None, "residual_today": None, "degraded": True, "sessions": 0,
                "note": "no fit rows stored yet"}
    mae = sum(abs(r) for _, r in res) / len(res)
    mean_a = sum(a for a, _ in res) / len(res)
    ss_tot = sum((a - mean_a) ** 2 for a, _ in res)
    r2 = 1 - sum(r ** 2 for _, r in res) / ss_tot if ss_tot else None
    today = rows[-1]
    return {"mae_60s": round(mae, 1), "r2_60s": round(r2, 4) if r2 is not None else None,
            "residual_today": _num(today.get("residual_points")), "degraded": mae > FIT_DEGRADED_MAE, "sessions": len(res),
            "members_priced": today.get("members_priced"), "members_total": today.get("members_total"),
            "note": (f"explains the index move with a mean absolute residual of {mae:.0f} pts/day over {len(res)} sessions"
                     + ("; degraded (> 25 pts) — weights need recalibration" if mae > FIT_DEGRADED_MAE else ""))}


CHALLENGER_CONFIRM = {20: 5, 60: 5}         # compute.WINDOWS: consecutive sessions a challenger must lead


def challenger_of(rows: list[dict[str, Any]], leader: Any, window: int) -> dict[str, Any] | None:
    """m028: the raw leader when it is not the hysteresis leader, with how many consecutive stored sessions it has led
    and how many more the rule needs ("challenger pending"); None when the leader also leads raw."""
    seen: dict[str, dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: (_day(r.get("date")) or "", str(r.get("computed_at") or ""))):
        seen[_day(r.get("date")) or ""] = r
    ordered = [seen[d] for d in sorted(seen)]
    if not ordered:
        return None
    raw = ordered[-1].get("raw_leader")
    if not raw or raw == leader:
        return None
    streak = 0
    for r in reversed(ordered):
        if r.get("raw_leader") != raw or r.get("leader") != leader:
            break
        streak += 1
    need = CHALLENGER_CONFIRM.get(window, 5)
    return {"symbol": raw, "sessions_leading": streak, "sessions_needed": max(0, need - streak),
            "sentence": f"{raw} leads the raw {window}-session points; the label changes after {need} consecutive sessions "
                        f"({streak} so far) — {DRIVER_DESCRIBES}"}


#: indices whose members are known only from their first archived constituent list, so earlier sessions are never computed
#: (point-in-time; the rule and its owner opt-out O-T13 live in data-service `index_drivers/jobs.py` PIT_MEMBERS_ONLY).
#: For these, a short history is the archive's limit, NOT a backfill that has not run — the sentence must not blame the job.
PIT_MEMBERS_ONLY = frozenset({"NIFTY BANK"})


def tab_state(fit: dict[str, Any], horizon_sessions: int, stored_sessions: int, history_since: str | None,
              index: str | None = None) -> dict[str, Any]:
    """M46: how far the page can be read. 'insufficient' when fewer than 20 fit sessions are stored, 'degraded' when the
    60-session MAE is above the 25-pt bar, else 'ok'; a sentence says which and why.

    8 Nov 2026: the insufficient sentence named one cause ("the backfill has not run") for two different situations. After
    the 2019 backfill ran, NIFTY BANK still had 3 sessions — correctly, because nothing earlier than its first archived
    constituent list is computed — and the page blamed a job that had just finished. A PIT index now says the real reason."""
    n = int(fit.get("sessions") or 0)
    mae = fit.get("mae_60s")
    if n < 20:
        pit = index in PIT_MEMBERS_ONLY
        since = history_since or "—"
        head = (f"only {n} session{'s' if n != 1 else ''} of attribution stored (since {since}"
                f"{', its first archived constituent list' if pit else ''})")
        why = ("earlier sessions are not computed because that day's members are not known (point-in-time)"
               if pit else "the backfill has not run")
        return {"state": "insufficient", "sessions": n, "limit": "archive" if pit else "backfill",
                "sentence": f"{head}: {why}, so horizons longer than that are not shown in full"}
    if fit.get("degraded"):
        return {"state": "degraded", "sessions": n,
                "sentence": f"the weights miss the index by {mae:.0f} pts a day on average over {n} sessions (bar 25): "
                            "members' points are approximate; the residual is shown"}
    return {"state": "ok", "sessions": n, "sentence": f"weights explain the index within {mae:.0f} pts a day over {n} sessions"}


def driver_state_row(state: list[dict[str, Any]], window: int) -> dict[str, Any] | None:
    rows = [s for s in state if _num(s.get("window_sessions")) == window and _day(s.get("date"))]
    if not rows:
        return None
    s = max(rows, key=lambda r: (_day(r.get("date")) or "", str(r.get("computed_at") or "")))
    tenure = _num(s.get("tenure_sessions"))
    share = _num(s.get("leader_share"))
    return {"window": window, "as_of": _day(s.get("date")), "leader": s.get("leader"),
            "leader_points": _num(s.get("leader_points")), "leader_share": share,
            "tenure": int(tenure) if tenure is not None else None, "changed_from": s.get("changed_from"),
            "change_date": _day(s.get("change_date")), "top5_share": _num(s.get("top5_share")),
            "hhi_contrib": _num(s.get("hhi_contrib")), "ew_minus_cw_pp": _num(s.get("ew_minus_cw_pp")),
            "members_up": s.get("members_up"), "members_down": s.get("members_down"),
            "sentence": regime_sentence(window, s.get("leader"), tenure, share, _num(s.get("ew_minus_cw_pp"))),
            "challenger": challenger_of(rows, s.get("leader"), window)}


def regime_sentence(window: int, leader: Any, tenure: float | None, share: float | None, ew_minus_cw_pp: float | None) -> str:
    if not leader:
        return f"no {window}-session leader stored yet — {DRIVER_DESCRIBES}"
    bits = [f"{window}-session leader {leader}"]
    if tenure is not None:
        bits.append(f"for {int(tenure)} sessions")
    if share is not None:
        bits.append(f"{share * 100:.1f} % of member points")
    word = breadth_word(ew_minus_cw_pp)
    if word and ew_minus_cw_pp is not None:
        bits.append(f"EW − CW {ew_minus_cw_pp:+.2f} pp: {word}")
    return ", ".join(bits) + f" — {DRIVER_DESCRIBES}"


MONTHLY_BAD_SESSION_PTS = 150.0             # m026: one failed session (2 Feb 2026: −492 pts) breaks a month's "explained"


def monthly_leaderboard(contrib: list[dict[str, Any]], fit: list[dict[str, Any]], months: int) -> list[dict[str, Any]]:
    by_month: dict[str, dict[str, float]] = _defaultdict(lambda: _defaultdict(float))
    sessions: dict[str, set[str]] = _defaultdict(set)
    for r in contrib:
        d, s, p = _day(r.get("date")), str(r.get("symbol") or ""), _num(r.get("points"))
        if d and s and p is not None:
            by_month[d[:7]][s] += p
            sessions[d[:7]].add(d)
    actual: dict[str, float] = _defaultdict(float)
    bad: dict[str, list[str]] = _defaultdict(list)
    for f in fit:
        d, a = _day(f.get("date")), _num(f.get("actual_points"))
        if d and a is not None:
            actual[d[:7]] += a
        res = _num(f.get("residual_points"))
        if d and res is not None and abs(res) > MONTHLY_BAD_SESSION_PTS:
            bad[d[:7]].append(d)
    out = []
    prev_leader = None
    for ym in sorted(by_month):
        m = by_month[ym]
        ranked = sorted(m.items(), key=lambda kv: -kv[1])
        leader = max(m.items(), key=lambda kv: abs(kv[1]))[0]
        tot_abs = sum(abs(v) for v in m.values())
        out.append({"month": ym, "sessions": len(sessions[ym]), "index_move_pts": round(actual[ym], 1) if ym in actual else None,
                    "explained_pts": round(sum(m.values()), 1), "leader": leader, "leader_pts": round(m[leader], 1),
                    "leader_share": round(abs(m[leader]) / tot_abs, 3) if tot_abs else None,
                    "leader_changed": prev_leader is not None and leader != prev_leader,
                    "top3_add": [{"symbol": s, "points": round(v, 1)} for s, v in ranked[:3]],
                    "top3_drag": [{"symbol": s, "points": round(v, 1)} for s, v in ranked[-3:][::-1]],
                    "residual_pts": round(actual[ym] - sum(m.values()), 1) if ym in actual else None,
                    "bad_sessions": bad.get(ym) or [],
                    "note": (f"{len(bad[ym])} session(s) the weights missed by > {MONTHLY_BAD_SESSION_PTS:.0f} pts "
                             f"({', '.join(bad[ym][:3])}): the month's 'explained' is not reliable" if bad.get(ym) else None)})
        prev_leader = leader
    return out[-months:]


def _history_since(contrib: list[dict[str, Any]]) -> str | None:
    days = sorted(d for d in (_day(r.get("date")) for r in contrib) if d)
    return days[0] if days else None


METHOD_RANK = {"rebuilt_fitted": 0, "rebuilt_calibrated": 1, "rebuilt_capped": 2, "rebuilt": 3, "official_top10": 4}


def _weight_method(weights: list[dict[str, Any]], day: str | None) -> dict[str, Any]:
    rows = [w for w in weights if _day(w.get("date")) == day] if day else []
    methods = {str(w.get("method")) for w in rows if w.get("method")}
    if "rebuilt_fitted" in methods:
        return {"method": "rebuilt_fitted", "label": f"weights rebuilt from filings, capped, corrected by a 60-session fit to the "
                                                     f"index's own closes (fitted before {day}, applied on it)"}
    if "rebuilt_capped" in methods:
        return {"method": "rebuilt_capped", "label": f"weights rebuilt from filings and capped (dated cap schedule; no fit on {day})"}
    if "rebuilt_calibrated" in methods:
        return {"method": "rebuilt_calibrated", "label": f"weights rebuilt, calibrated to NSE's top-10 on {day}"}
    if "rebuilt" in methods:
        return {"method": "rebuilt", "label": f"weights rebuilt from filings (no top-10 calibration on {day})"}
    if "official_top10" in methods:
        return {"method": "official_top10", "label": "NSE's top-10 file only"}
    return {"method": None, "label": "no weight rows stored for this date"}


# ── routes ───────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/index-drivers")
async def index_drivers(response: Response, index: str = Query("NIFTY 50"),
                        horizon: str = Query("1m", pattern="^(1d|5d|1m|3m|ytd|since_change)$"),
                        window: int = Query(20, ge=20, le=60),
                        as_of: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """Who drove the index over `horizon` (PLAN 1.2): members (points, weight, return, share), sectors, concentration,
    breadth, the fit (MAE / R² over 60 sessions, today's residual), the driver state with hysteresis, badges.
    `as_of` ends the horizon on a past stored session (the wrap's backfill reads one day's attribution with it);
    `tab` says whether the stored fit supports reading the page (M46)."""
    name = _check_index(index)
    reads = _DriverReads()
    contrib = await reads.get("contribution", index=name, days=400)
    fit = await reads.get("fit", index=name, days=400)
    state = await reads.get("state", index=name, days=12)
    if as_of:
        contrib = [r for r in contrib if (_day(r.get("date")) or "") <= as_of]
        fit = [f for f in fit if (_day(f.get("date")) or "") <= as_of]
        state = [x for x in state if (_day(x.get("date")) or "") <= as_of]
    dates = sorted({d for d in (_day(r.get("date")) for r in contrib) if d})
    driver = driver_state_row(state, window if window in (20, 60) else 20)
    win = horizon_window(dates, horizon, driver["change_date"] if driver else None)
    weights = await reads.get("weights", index=name, date=win[-1]) if win else []
    sliced = slice_contributions(contrib, fit, weights, win)
    reads.headers(response)
    fs = fit_summary(fit)
    since = _history_since(contrib)
    return {
        "as_of": win[-1] if win else None, "index": name,
        "horizon": {"name": horizon, "from": win[0] if win else None, "to": win[-1] if win else None, "sessions": len(win)},
        **sliced, "fit": fs, "weight_method": _weight_method(weights, win[-1] if win else None),
        "tab": tab_state(fs, len(win), len(dates), since, index=name),
        "driver": driver, "history_since": since, "badges": DRIVER_BADGES,
        "note": f"points = previous index level × weight × return (additive; the residual is shown); {DRIVER_DESCRIBES}",
        "precedent": "Bloomberg MEMB / IMAP contribution; NSE daily top-10 file (display-only, O-T11)",
        **reads.meta(),
    }


@router.get("/index-drivers/timeline")
async def index_drivers_timeline(response: Response, index: str = Query("NIFTY 50"), window: int = Query(20, ge=20, le=60),
                                 days: int = Query(250, ge=20, le=2000)) -> dict:
    """The leader timeline + concentration / breadth series for the chart (from `index_driver_state`)."""
    name = _check_index(index)
    reads = _DriverReads()
    state = await reads.get("state", index=name, days=days)
    rows = sorted((s for s in state if _num(s.get("window_sessions")) == window and _day(s.get("date"))),
                  key=lambda s: (_day(s.get("date")) or "", str(s.get("computed_at") or "")))
    seen: dict[str, dict[str, Any]] = {}
    for s in rows:                                   # revisions are new rows by computed_at: the latest per date wins
        seen[_day(s.get("date")) or ""] = s
    points = [{"date": d, "leader": s.get("leader"), "leader_share": _num(s.get("leader_share")),
               "top5_share": _num(s.get("top5_share")), "hhi_contrib": _num(s.get("hhi_contrib")),
               "effective_n": _num(s.get("effective_n")), "ew_minus_cw_pp": _num(s.get("ew_minus_cw_pp")),
               "changed": bool(s.get("change_date") and _day(s.get("change_date")) == d)} for d, s in sorted(seen.items())]
    changes = [{"date": p["date"], "to": p["leader"]} for p in points if p["changed"]]
    reads.headers(response)
    return {"index": name, "window": window, "as_of": points[-1]["date"] if points else None, "points": points,
            "changes": changes, "badge": "context", "note": f"hysteresis: a challenger must lead ≥ 1.3× (20 s) / 1.2× (60 s) "
            f"for 5 consecutive sessions; {DRIVER_DESCRIBES}", **reads.meta()}


@router.get("/index-drivers/monthly")
async def index_drivers_monthly(response: Response, index: str = Query("NIFTY 50"), months: int = Query(12, ge=1, le=60)) -> dict:
    """The monthly leaderboard: leader by |points|, top-3 add / drag, the index move and what the members explain."""
    name = _check_index(index)
    reads = _DriverReads()
    days = months * 23 + 10
    contrib = await reads.get("contribution", index=name, days=days)
    fit = await reads.get("fit", index=name, days=days)
    rows = monthly_leaderboard(contrib, fit, months)
    reads.headers(response)
    last = max((d for d in (_day(r.get("date")) for r in contrib) if d), default=None)
    return {"index": name, "months": rows, "n": len(rows), "as_of": last, "as_of_month": rows[-1]["month"] if rows else None,
            "badge": "context",
            "note": f"monthly sums of stored daily points; {DRIVER_DESCRIBES}", **reads.meta()}


# ── /api/market/index-drivers/intraday (FINAL round R2-DRIV; RATING R9-I3) ──────────────────────────────────
# The within-day contribution timeline: data-service composes it from the tick store's minute closes × the stored
# point-in-time weights (the 2-min tape as fallback; honest gaps, never interpolated); this route only proxies through
# one SWR cache and degrades like the other drivers reads (ok: false + store_errors, never a raw transport error).
INTRADAY_STORE = SWRCache("market.index_drivers.intraday", max_items=16, refresh_after=45.0, max_age=240.0)
_INTRADAY_EMPTY: dict[str, Any] = {"minutes": [], "actual_pts": [], "explained_pts": [], "residual_pts": [], "priced": [],
                                   "others_pts": [], "members": {"add": [], "drag": [], "rest": []},
                                   "coverage": {"members_total": 0, "members_priced": 0, "gaps": []},
                                   "date": None, "prev_index_level": None, "residual_now": None, "index_source": None,
                                   "weight_method": None, "weights_as_of": None, "first_minute": None, "last_minute": None,
                                   "badges": {"timeline": "context", "members": "arithmetic", "fit": "arithmetic"},
                                   "note": f"no intraday contribution available — {DRIVER_DESCRIBES}"}


@router.get("/index-drivers/intraday")
async def index_drivers_intraday(response: Response, index: str = Query("NIFTY 50"),
                                 date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                                 interval: str = Query("1m", pattern="^(1m|5m)$"),
                                 top: int = Query(7, ge=3, le=15)) -> dict:
    """Who is moving the index through the day: per-minute member points (prev close level × weight × intraday return
    from the tick store), the index's own move, the explained sum and the residual — stacked-timeline data for MEMB.
    Works closed-market from the stored session; `context`/`arithmetic` badged; describes, does not predict."""
    name = _check_index(index)
    params: dict[str, Any] = {"index": name, "interval": interval, "top": top}
    if date:
        params["date"] = date
    key = ("intraday", tuple(sorted((k, str(v)) for k, v in params.items())))
    try:
        served = await INTRADAY_STORE.get(key, lambda: _drivers_fetch("/db/index-drivers/intraday", params))
    except _DriversStoreUnavailable as exc:
        return {**_INTRADAY_EMPTY, "index": name, "interval": interval, "ok": False,
                "store_errors": {"/db/index-drivers/intraday": str(exc)}}
    except Exception as exc:  # noqa: BLE001 — degrade, never a raw transport error on the wire
        return {**_INTRADAY_EMPTY, "index": name, "interval": interval, "ok": False,
                "store_errors": {"/db/index-drivers/intraday": type(exc).__name__}}
    cache_headers(response, served)
    body = served.value if isinstance(served.value, dict) else {}
    return {**_INTRADAY_EMPTY, **body, "index": body.get("index") or name, "ok": True, "store_errors": {}}


# ── /api/desk/attribution (mounted by main.py at /api/desk; PLAN 1.2) ────────────────────────────────────────
attribution_router = APIRouter()
_DESK_STORE = SWRCache("desk.attribution", max_items=8, refresh_after=60.0, max_age=600.0)


async def _desk_status() -> dict[str, Any]:
    """The Decision Desk's paper book (routers/desk.py → shared/decision_desk.py) read on a worker thread."""
    import asyncio

    from routers import desk as _desk
    return await asyncio.to_thread(lambda: _desk.get_desk().status())


def desk_attribution(status: dict[str, Any], closes: dict[str, list[dict[str, Any]]], window: list[str],
                     nifty: dict[str, Any] | None) -> dict[str, Any]:
    """Real lots × stored closes in pp of NAV over ``window``; `{risk_off: true, since}` when the book is in cash."""
    positions = status.get("positions") or []
    nav_rows = status.get("nav") or []
    latest = status.get("latest") or {}
    if not positions:
        since = None
        for r in reversed(nav_rows):
            if (r.get("positions") or 0) > 0:
                break
            since = r.get("date")
        return {"risk_off": True, "since": since, "rows": [], "book_pp": 0.0, "nav": latest.get("nav"),
                "note": f"book = liquid fund since {since or '—'}; nothing to attribute", "nifty": nifty}
    from_day = window[0] if window else None
    nav_from = next((r.get("nav") for r in nav_rows if r.get("date") == from_day), None) or latest.get("nav")
    rows = []
    for p in positions:
        sym = p["symbol"]
        hist = sorted((c for c in closes.get(sym, []) if _day(c.get("date"))), key=lambda c: _day(c.get("date")) or "")
        inside = [c for c in hist if from_day and (_day(c.get("date")) or "") >= from_day]
        c_from = _num(inside[0].get("close")) if inside else None
        c_to = _num(inside[-1].get("close")) if inside else None
        pnl = (c_to - c_from) * (p.get("qty") or 0) if (c_from is not None and c_to is not None) else None
        rows.append({"symbol": sym, "sector": p.get("sector"), "qty": p.get("qty"), "close_from": c_from, "close_to": c_to,
                     "pnl_inr": round(pnl, 2) if pnl is not None else None,
                     "pp_of_nav": round(pnl / nav_from * 100, 2) if (pnl is not None and nav_from) else None})
    rows.sort(key=lambda r: -(r["pp_of_nav"] or 0))
    return {"risk_off": False, "since": None, "rows": rows, "book_pp": round(sum(r["pp_of_nav"] or 0 for r in rows), 2),
            "nav": latest.get("nav"), "nav_from": nav_from, "note": "real lots × stored closes, in pp of NAV", "nifty": nifty}


@attribution_router.get("/attribution")
async def desk_attribution_route(response: Response, horizon: str = Query("1m", pattern="^(1d|5d|1m|3m|ytd|since_change)$")) -> dict:
    """The Desk's real lots × stored closes in pp of NAV beside NIFTY's leaderboard over the same window (PLAN 1.2).
    `{risk_off: true, since}` when the paper book is in the liquid fund (as it is today)."""
    reads = _DriverReads()
    contrib = await reads.get("contribution", index="NIFTY 50", days=400)
    fit = await reads.get("fit", index="NIFTY 50", days=400)
    state = await reads.get("state", index="NIFTY 50", days=5)
    dates = sorted({d for d in (_day(r.get("date")) for r in contrib) if d})
    driver = driver_state_row(state, 20)
    win = horizon_window(dates, horizon, driver["change_date"] if driver else None)
    nifty = slice_contributions(contrib, fit, [], win) if win else None
    nifty_board = None if nifty is None else {"index_move_pts": nifty["index_move_pts"], "explained_pts": nifty["explained_pts"],
                                              "top5_add": nifty["members"][:5], "top5_drag": nifty["members"][-5:][::-1]}
    try:
        status = await _DESK_STORE.get("status", _desk_status)
        book = status.value
    except Exception as exc:  # noqa: BLE001 — the desk ledger may not exist on a fresh checkout
        reads.errors["desk"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        book = {"positions": [], "nav": [], "latest": {}}
    closes: dict[str, list[dict[str, Any]]] = {}
    for p in book.get("positions") or []:
        closes[p["symbol"]] = await reads.get_path(f"/db/security/{p['symbol']}/history", days=max(len(win) + 5, 30))
    out = desk_attribution(book, closes, win, nifty_board)
    reads.headers(response)
    return {"as_of": win[-1] if win else None, "horizon": {"name": horizon, "from": win[0] if win else None,
                                                             "to": win[-1] if win else None, "sessions": len(win)},
            **out, "badges": {"book": "arithmetic", "nifty": "arithmetic"}, "paper_only": True,
            "note_rules": "reads the paper ledger only; writes nothing; the Desk's rules are frozen", **reads.meta()}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Live NSE program round 2 (L2-API, 5 Nov 2026) — stored NSE closes for history panes: GET /api/market/closes
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# COMP's history, WTCH / news-dock sparks and any other daily-history pane read NSE's own stored closes here: data-service
# /db/closes (nse_bhavcopy EQ/BE, split/bonus-adjusted as shared.nse_panel does it, only sessions already stored; index
# names from NSE's daily index file). End of day, published once a day: the body says so (source 'nse_bhavcopy', as_of =
# the newest stored session) and never claims to be live. One SWR cache keyed by the request (10 min, then a background
# refresh; never older than 1 h), so N windows on the same view cost one DuckDB read per 10 min. Never Yahoo.
CLOSES_REFRESH_S = 600.0
CLOSES_MAX_AGE_S = 3600.0
CLOSES_MAX_SYMBOLS = 300
CLOSES_MAX_SYMBOL_DAYS = 120_000          # data-service's per-request budget (symbols × calendar days)
CLOSES_UPSTREAM = "data-service-closes"
_CLOSES = SWRCache("market.closes", max_items=64, refresh_after=CLOSES_REFRESH_S, max_age=CLOSES_MAX_AGE_S)
_CLOSES_META_KEYS = ("source", "name", "first_date", "last_date", "sessions", "high", "low", "last_series", "actions")
_CLOSE_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def closes_symbols(raw: str) -> tuple[list[str], dict[str, str]]:
    """'TCS,infy.ns,^NSEI' → (['TCS', 'INFY', 'NIFTY 50'], {'infy.ns': 'INFY', '^NSEI': 'NIFTY 50'}): canonical NSE names
    in request order + the spellings that changed. ValueError on a bad symbol, none, or more than 300."""
    asked = [x.strip() for x in raw.split(",") if x.strip()]
    names: list[str] = []
    aliases: dict[str, str] = {}
    for a in asked:
        n = _live.nse_name(a)
        names.append(n)
        if n != a:
            aliases[a] = n
    out = list(dict.fromkeys(names))
    if not out:
        raise ValueError("no symbols given")
    if len(out) > CLOSES_MAX_SYMBOLS:
        raise ValueError(f"at most {CLOSES_MAX_SYMBOLS} symbols per request ({len(out)} given)")
    return out, aliases


def _small(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str)) and (not isinstance(v, str) or len(v) <= 160)


def coerce_closes(body: Any, syms: list[str]) -> dict[str, Any]:
    """data-service's /db/closes body → the route's body, validated (never trust the upstream): finite positive closes
    on ISO dates, oldest first, one per date; meta trimmed to known small fields; every asked symbol either in
    ``series`` or in ``missing`` with a reason."""
    if not isinstance(body, dict) or not isinstance(body.get("series"), dict):
        raise _UpstreamError(502, "data-service /db/closes answered without a series map", upstream=CLOSES_UPSTREAM)
    series_in: dict[str, Any] = body["series"]
    meta_raw, missing_raw = body.get("meta"), body.get("missing")
    meta_in: dict[str, Any] = meta_raw if isinstance(meta_raw, dict) else {}
    missing_in: dict[str, Any] = missing_raw if isinstance(missing_raw, dict) else {}
    series: dict[str, list[dict[str, Any]]] = {}
    meta: dict[str, dict[str, Any]] = {}
    for s in syms:
        pts: dict[str, float] = {}
        raw_pts = series_in.get(s)
        for p in raw_pts if isinstance(raw_pts, list) else []:
            if isinstance(p, dict) and isinstance(p.get("date"), str) and _CLOSE_DAY.fullmatch(p["date"]):
                c = _num(p.get("close"))
                if c is not None and c > 0:
                    pts[p["date"]] = c
        if not pts:
            continue
        series[s] = [{"date": d, "close": c} for d, c in sorted(pts.items())]
        m_raw = meta_in.get(s)
        m: dict[str, Any] = m_raw if isinstance(m_raw, dict) else {}
        meta[s] = {k: m[k] for k in _CLOSES_META_KEYS if k in m and (_small(m[k]) or k == "actions" and isinstance(m[k], list)
                                                                      and len(m[k]) <= 50 and all(isinstance(a, dict) for a in m[k]))}
        meta[s]["last_date"] = series[s][-1]["date"]
    missing = {s: str(missing_in.get(s) or "not in the data-service answer")[:200] for s in syms if s not in series}
    last = [v[-1]["date"] for v in series.values()]
    return {"as_of": max(last) if last else None, "source": "nse_bhavcopy", "series": series, "meta": meta, "missing": missing,
            "from": body.get("from") if _small(body.get("from")) else None, "to": body.get("to") if _small(body.get("to")) else None,
            "tail": body.get("tail") if isinstance(body.get("tail"), int) else None,
            "generated_at": body.get("generated_at") if _small(body.get("generated_at")) else None,
            "note": "end of day: NSE's stored closes (bhavcopy / daily index file), split/bonus-adjusted; never live"}


async def _fetch_closes(syms: tuple[str, ...], days: int, tail: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {"symbols": ",".join(syms), "days": days}
    if tail:
        params["tail"] = tail
    body = await _get_json(f"{_live.data_svc()}/db/closes", route="read", params=params, upstream=CLOSES_UPSTREAM)
    return coerce_closes(body, list(syms))


@router.get("/closes")
async def market_closes(response: Response, symbols: str = Query(..., min_length=1, max_length=12000),
                        days: int = Query(365, ge=5, le=3700), tail: int | None = Query(None, ge=1, le=3700)) -> dict:
    """NSE's stored daily closes for up to 300 symbols / index names: ``{as_of, source: 'nse_bhavcopy', series: {SYM:
    [{date, close}]}, meta, missing, aliases}`` (oldest first; ``days`` = calendar days back, ``tail`` = only the last N
    sessions). End of day, never live, never Yahoo. The cache age is in X-Cache-Age."""
    try:
        syms, aliases = closes_symbols(symbols)
    except ValueError as exc:
        _fail(422, "invalid", str(exc), "NSE symbols (TCS, M&M) or index names ('NIFTY 50'), comma-separated, at most 300")
    if len(syms) * days > CLOSES_MAX_SYMBOL_DAYS:
        _fail(422, "invalid", f"{len(syms)} symbols × {days} days is over the {CLOSES_MAX_SYMBOL_DAYS:,} symbol-day budget",
              "ask fewer symbols or a shorter window")
    key = (tuple(sorted(syms)), days, tail)
    try:
        served = await _CLOSES.get(key, functools.partial(_fetch_closes, key[0], days, tail))
    except _UpstreamError as exc:
        hint = ("data-service has no /db/closes yet: deploy data-service with the live-NSE round 2 build"
                if exc.status_code == 404 else "data-service is down or busy; retry shortly")
        _fail(503 if exc.status_code in (404, 503) or exc.status_code >= 500 else 502, "upstream_down",
              f"stored closes unavailable: HTTP {exc.status_code}: {exc.detail}"[:300], hint)
    cache_headers(response, served)
    body = served.value
    return {**body, "series": {s: body["series"][s] for s in syms if s in body["series"]},
            "meta": {s: body["meta"][s] for s in syms if s in body["meta"]},
            "missing": {s: body["missing"][s] for s in syms if s in body["missing"]}, "aliases": aliases}
