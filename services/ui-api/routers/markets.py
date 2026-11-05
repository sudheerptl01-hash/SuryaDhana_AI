"""Market Monitor proxy: breadth, regime score, sectors and movers (computed by data-service)."""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import httpx

from shared import http_client
from cache import SWRCache, cache_headers
from fastapi import APIRouter, HTTPException, Query, Response

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
async def market_monitor() -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/market-monitor")
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


@router.get("/events")
async def market_events(start: str | None = None, end: str | None = None,
                        limit: int = Query(500, ge=1, le=5000),
                        fields: str | None = CORE_FIELDS) -> dict:
    """NSE corporate calendar (results, dividends, splits, bonuses, buybacks…) from data-service.

    Payload budget (S2): rows capped at `limit` after merging — the calendar comes
    date-ascending, so a cut drops only the farthest-future events (today's full
    window is ~470 rows, under the default).
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
        rows = rows[:limit]
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


@router.get("/wraps")
def list_wraps(limit: int = 60) -> dict:
    """Dates of the saved daily wraps, newest first, with each wrap's first content line as a teaser."""
    d = _wrap_dir()
    files = sorted(d.glob("????-??-??.md"), reverse=True)[: max(1, min(limit, 400))] if d.is_dir() else []
    out = []
    for f in files:
        teaser = next((ln[2:].strip() for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()
                       if ln.startswith("- ")), "")
        out.append({"date": f.stem, "teaser": teaser[:160]})
    return {"wraps": out}


@router.get("/wraps/{day}")
def get_wrap(day: str) -> dict:
    import re
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    f = _wrap_dir() / f"{day}.md"
    if not f.is_file():
        raise HTTPException(status_code=404, detail=f"No wrap for {day}")
    return {"date": day, "markdown": f.read_text(encoding="utf-8", errors="replace")}


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


@router.get("/announcements")
async def announcements(day: str | None = None,
                        limit: int = Query(1000, ge=1, le=5000),
                        full: bool = False,
                        fields: str | None = CORE_FIELDS) -> dict:
    """Today's NSE company filings, categorised, via data-service.

    Payload budget (S2): filing text trimmed to 400 chars unless `full=true`; items
    capped at `limit` — the default (1000) keeps a whole normal day (~500 filings),
    it only guards pathological days. `counts` stays whole-day truth either way.
    `fields=core` (W7): items carry only {symbol, time, category} — for the EVTS/BRIEF
    pollers (every 2 min), which read nothing else; it overrides `full`.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/announcements", params={"day": day} if day else None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    body = r.json()
    items = body.get("items", [])
    truncated = len(items) > limit
    if truncated:
        items = items[:limit]
    if fields == "core":  # new dicts — never mutate the full items
        core = [{"symbol": it.get("symbol"), "time": it.get("time"), "category": it.get("category")}
                for it in items]
        return {**body, "items": core, **({"truncated": True} if truncated else {})}
    if not full:
        for it in items:
            t = it.get("text")
            if isinstance(t, str) and len(t) > 400:
                it["text"] = t[:400] + "…"
    return {**body, "items": items, **({"truncated": True} if truncated else {})}


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


@router.get("/eco-calendar")
async def eco_calendar(back: int = Query(14, ge=0, le=120), ahead: int = Query(60, ge=1, le=366)) -> dict:
    """Economic calendar for the last `back` and next `ahead` days: India CPI / WPI / IIP / core / GDP (official
    release calendars, data/reference/india_data_calendar.json), RBI policy decisions and US Fed decisions."""
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
    events = build_eco_calendar(ref, rbi, fed, today - timedelta(days=back), today + timedelta(days=ahead), holidays)
    return {"today": today.isoformat(), "events": events, "sources": ref.get("sources") or {}, "note": ref.get("note"),
            "valid_until": ref.get("valid_until"), "fed_available": bool(fed)}


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


@router.get("/index-contribution")
async def index_contribution(index: str = "NIFTY 50") -> dict:
    """Who moved the index today, in points (rebuilt free-float weights), via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-contribution", params={"index": index})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


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
    """MEMB: index members with weight, today's points, returns, distance from high, P/E and growth, via data-service."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/index-memb", params={"index": index})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


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


async def _fetch_implied_moves(days: int) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/results-implied-moves", params={"days": days})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 300))
    return r.json()


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


@router.get("/results-reacting")
async def results_reacting(response: Response = None) -> dict:  # type: ignore[assignment]  # injected by FastAPI
    """Cached at most 60 s as before; now single flight with a background refresh after 30 s (C-PERF-01)."""
    served = await _REACTING.get("reacting", _results_reacting)
    cache_headers(response, served)
    return served.value


async def _results_reacting() -> dict:
    """Results filed since the last close (after 15:30 on the previous trading day, or today), with today's live move
    against the stock's typical results-day move. Filings: NSE announcements (results category); prices: NSE heatmap
    lists, Yahoo for the rest; typical moves: past reactions in nse_results."""
    import asyncio
    from datetime import date, datetime, timedelta
    from routers.news_scanner import get_quotes
    today = date.today()  # noqa: DTZ005,DTZ011 — local clock on purpose (data-service computes its windows from it)
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
        tm, lq, nl, fl = await asyncio.gather(
            client.get(f"{DATA_SVC}/db/typical-results-moves", params={"symbols": ",".join(syms)}),
            client.get(f"{DATA_SVC}/db/live-quotes"), client.get(f"{DATA_SVC}/db/nifty-live"),
            client.get(f"{DATA_SVC}/db/financials-latest", params={"symbols": ",".join(syms)}), return_exceptions=True)
        fin_latest = fl.json().get("latest", {}) if not isinstance(fl, Exception) and fl.status_code == 200 else {}
        # the numbers for this filing: cached quarter filed since the previous close; queue the rest for a background read
        fresh = {s: f for s, f in fin_latest.items() if (f.get("filed_at") or "")[:16].replace("T", " ") >= f"{prev.isoformat()} 15:30"}
        missing = [s for s in syms if s not in fresh]
        if missing:
            try:
                await client.post(f"{DATA_SVC}/db/financials/prefetch", params={"symbols": ",".join(missing)})
            except httpx.HTTPError:
                pass
    nifty = nl.json().get("change_pct") if not isinstance(nl, Exception) and nl.status_code == 200 else None
    typical = tm.json().get("moves", {}) if not isinstance(tm, Exception) and tm.status_code == 200 else {}
    live = lq.json().get("quotes", {}) if not isinstance(lq, Exception) and lq.status_code == 200 else {}
    phase = reaction_phase(datetime.now())  # noqa: DTZ005,DTZ011 — local clock on purpose (data-service computes its windows from it)
    chg: dict[str, float] = {}
    if phase != "session":
        # before 09:15 live quotes still show yesterday's move: use today's pre-open auction price, or nothing
        if phase == "preopen":
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                    po = (await client.get(f"{DATA_SVC}/db/preopen", params={"key": "ALL"})).json()
                if str(po.get("timestamp", ""))[:11] == datetime.now().strftime("%d-%b-%Y"):  # noqa: DTZ005,DTZ011 — local clock on purpose (data-service computes its windows from it)
                    chg = {r["symbol"]: r["change_pct"] for r in po.get("rows") or [] if r.get("symbol") in filed and r.get("change_pct") is not None}
            except (httpx.HTTPError, ValueError):
                chg = {}
        rows = reacting_rows(filed, typical, chg, None)
        for r in rows:
            f = fresh.get(r["symbol"]) or {}
            r.update(revenue_yoy=f.get("revenue_yoy"), pat_yoy=f.get("pat_yoy"), pat_turn=f.get("pat_yoy_turn"), quarter=f.get("period_end"),
                     numbers=numbers_status(r["symbol"], fresh, fin_latest))
        return {"rows": rows, "phase": phase, "nifty_change_pct": None, "since": f"{prev.isoformat()} 15:30",
                "as_of": datetime.now().isoformat(timespec="seconds")}  # noqa: DTZ005,DTZ011 — local clock on purpose (data-service computes its windows from it)
    chg = {s: live[s]["change_pct"] for s in syms if (live.get(s) or {}).get("change_pct") is not None}
    rest = [s for s in syms if s not in chg]
    for i in range(0, len(rest), 60):
        q = (await get_quotes(symbols=",".join(f"{s}.NS" for s in rest[i:i + 60])))["quotes"]
        for s in rest[i:i + 60]:
            v = q.get(f"{s}.NS") or {}
            if v.get("available") and v.get("change_pct") is not None and v.get("state") not in ("stale", "unavailable"):
                chg[s] = v["change_pct"]
    # filed after today's close: today's move happened before the results, so there is no reaction to show yet
    after_close = f"{today.isoformat()} 15:30"
    chg = {s: v for s, v in chg.items() if filed[s] < after_close}
    rows = reacting_rows(filed, typical, chg, nifty)
    for r in rows:
        r["reacts_next_session"] = r["filed_at"] >= after_close
        f = fresh.get(r["symbol"]) or {}
        r.update(revenue_yoy=f.get("revenue_yoy"), pat_yoy=f.get("pat_yoy"), pat_turn=f.get("pat_yoy_turn"), quarter=f.get("period_end"),
                 numbers=numbers_status(r["symbol"], fresh, fin_latest))
    return {"rows": rows, "phase": phase, "nifty_change_pct": nifty, "since": f"{prev.isoformat()} 15:30", "as_of": datetime.now().isoformat(timespec="seconds")}  # noqa: DTZ005 — local clock on purpose


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
    for r in weights:
        if _day(r.get("date")) == last_day or last_day is None:
            w = _num(r.get("weight_pct"))
            if w is not None:
                w_latest[str(r.get("symbol"))] = w
                if r.get("industry"):
                    industry.setdefault(str(r.get("symbol")), str(r["industry"]))
    for r in rows:                                   # the contribution rows carry the day's weight too
        if _day(r.get("date")) == last_day and str(r.get("symbol")) not in w_latest and _num(r.get("weight_pct")) is not None:
            w_latest[str(r.get("symbol"))] = float(r["weight_pct"])
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
            "sentence": regime_sentence(window, s.get("leader"), tenure, share, _num(s.get("ew_minus_cw_pp")))}


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


def monthly_leaderboard(contrib: list[dict[str, Any]], fit: list[dict[str, Any]], months: int) -> list[dict[str, Any]]:
    by_month: dict[str, dict[str, float]] = _defaultdict(lambda: _defaultdict(float))
    sessions: dict[str, set[str]] = _defaultdict(set)
    for r in contrib:
        d, s, p = _day(r.get("date")), str(r.get("symbol") or ""), _num(r.get("points"))
        if d and s and p is not None:
            by_month[d[:7]][s] += p
            sessions[d[:7]].add(d)
    actual: dict[str, float] = _defaultdict(float)
    for f in fit:
        d, a = _day(f.get("date")), _num(f.get("actual_points"))
        if d and a is not None:
            actual[d[:7]] += a
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
                    "top3_drag": [{"symbol": s, "points": round(v, 1)} for s, v in ranked[-3:][::-1]]})
        prev_leader = leader
    return out[-months:]


def _history_since(contrib: list[dict[str, Any]]) -> str | None:
    days = sorted(d for d in (_day(r.get("date")) for r in contrib) if d)
    return days[0] if days else None


def _weight_method(weights: list[dict[str, Any]], day: str | None) -> dict[str, Any]:
    rows = [w for w in weights if _day(w.get("date")) == day] if day else []
    methods = {str(w.get("method")) for w in rows if w.get("method")}
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
                        window: int = Query(20, ge=20, le=60)) -> dict:
    """Who drove the index over `horizon` (PLAN 1.2): members (points, weight, return, share), sectors, concentration,
    breadth, the fit (MAE / R² over 60 sessions, today's residual), the driver state with hysteresis, badges."""
    name = _check_index(index)
    reads = _DriverReads()
    contrib = await reads.get("contribution", index=name, days=400)
    fit = await reads.get("fit", index=name, days=400)
    state = await reads.get("state", index=name, days=5)
    dates = sorted({d for d in (_day(r.get("date")) for r in contrib) if d})
    driver = driver_state_row(state, window if window in (20, 60) else 20)
    win = horizon_window(dates, horizon, driver["change_date"] if driver else None)
    weights = await reads.get("weights", index=name, date=win[-1]) if win else []
    sliced = slice_contributions(contrib, fit, weights, win)
    reads.headers(response)
    return {
        "as_of": win[-1] if win else None, "index": name,
        "horizon": {"name": horizon, "from": win[0] if win else None, "to": win[-1] if win else None, "sessions": len(win)},
        **sliced, "fit": fit_summary(fit), "weight_method": _weight_method(weights, win[-1] if win else None),
        "driver": driver, "history_since": _history_since(contrib), "badges": DRIVER_BADGES,
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
    return {"index": name, "months": rows, "n": len(rows), "as_of": rows[-1]["month"] if rows else None, "badge": "context",
            "note": f"monthly sums of stored daily points; {DRIVER_DESCRIBES}", **reads.meta()}


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
