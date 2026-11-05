"""
commodity.py — Commodity Desk data router.

Surfaces the data sources catalogued in `docs/PROGRAMMATIC_DATA_ACCESS.md` into a
single UI tab so commodities can be viewed (and traded off) alongside the NSE book.

Three legs, all async via httpx (zero new Python deps — httpx already ships in ui-api):

  • PRICE      — global futures (WTI/Brent/COMEX gold/silver/copper/Henry-Hub gas)
                 via Yahoo's v8 chart JSON. NO API KEY. This is the tradeable leg and
                 is also this project's existing historical price provider (yfinance
                 wraps the same endpoint), so it is the natural free proxy.
  • EIA        — energy FUNDAMENTALS (crude/gas inventories & production) via EIA v2
                 REST. Requires EIA_API_KEY (free). Gated: returns available=false with
                 the exact wiring when the key is unset — never fabricated numbers.
  • FRED       — commodity / macro CONTEXT indices. With FRED_API_KEY (free) the REST API;
                 WITHOUT a key the keyless `fredgraph.csv` download (GOLD program PLAN §b:
                 the "key required" message is gone; same series, same points, plain UA
                 because FRED stalls browser-like user agents).

The Gold Pre-Open desk that used to sit at the top of the CMDT page lives on the GOLD page
(GOLD › HEALTH) since the gold program; its routes stay mounted under /api/commodity as
aliases for one release (routers/gold_preopen.py) and this router no longer advertises it.

Caching: a small in-process TTL cache (per-worker) — robust, no Redis coupling for a
read-only dashboard. Redis (already in the stack) is the obvious later upgrade if this
needs to be shared across workers.

⚠️ Look-ahead discipline: this router serves LATEST values for LIVE viewing, which is
correct for a dashboard. Any *backtested* commodity factor must instead use point-in-time
vintages (ALFRED for FRED legs) — see docs/PROGRAMMATIC_DATA_ACCESS.md §3.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from cache import TTLCache
from fastapi import APIRouter, HTTPException, Query

from routers._upstream import upstream_detail

router = APIRouter()

# ── Config (env-driven; keys NEVER hardcoded) ───────────────────────────────────
EIA_API_KEY = os.environ.get("EIA_API_KEY", "").strip()
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()

_TIMEOUT = httpx.Timeout(15.0)
_UA = {"User-Agent": "Mozilla/5.0 (SuryaDhana-CommodityDesk)"}

# ── Tradeable global-futures universe (Yahoo symbols) ───────────────────────────
# label, Yahoo symbol, category, quote unit. Priced in USD.
FUTURES: list[dict[str, str]] = [
    {"symbol": "CL=F", "label": "WTI Crude",   "category": "Energy",  "unit": "USD/bbl"},
    {"symbol": "BZ=F", "label": "Brent Crude",  "category": "Energy",  "unit": "USD/bbl"},
    {"symbol": "NG=F", "label": "Nat Gas (HH)", "category": "Energy",  "unit": "USD/MMBtu"},
    {"symbol": "GC=F", "label": "Gold",         "category": "Metals",  "unit": "USD/oz"},
    {"symbol": "SI=F", "label": "Silver",       "category": "Metals",  "unit": "USD/oz"},
    {"symbol": "HG=F", "label": "Copper",       "category": "Metals",  "unit": "USD/lb"},
]
_SYMBOLS = {f["symbol"] for f in FUTURES}
_META_BY_SYMBOL = {f["symbol"]: f for f in FUTURES}

# Curated FRED commodity / macro context series (real FRED series IDs).
FRED_SERIES: list[dict[str, str]] = [
    {"id": "DCOILWTICO",  "label": "WTI Spot (FRED)",      "unit": "USD/bbl"},
    {"id": "DCOILBRENTEU", "label": "Brent Spot (FRED)",    "unit": "USD/bbl"},
    {"id": "DHHNGSP",     "label": "Henry Hub Gas (FRED)",  "unit": "USD/MMBtu"},
    {"id": "DTWEXBGS",    "label": "USD Broad Index",       "unit": "index"},
]

# Curated EIA v2 energy-fundamentals series (route + facets confirmed against EIA v2).
# Each maps to a v2 data route; parsed generically from response.data[].
EIA_SERIES: list[dict[str, str]] = [
    {"id": "crude_stocks", "label": "US Crude Stocks (excl. SPR)", "unit": "Mbbl",
     "route": "petroleum/stoc/wstk/data", "facet": "WCESTUS1", "freq": "weekly"},
    {"id": "crude_prod",   "label": "US Crude Production",          "unit": "Mbbl/d",
     "route": "petroleum/crd/crpdn/data", "facet": "MCRFPUS2", "freq": "monthly"},
]

# ── In-process TTL cache (bounded, F2.1; semantics unchanged) ───────────────────
_CACHE = TTLCache("commodity", max_items=64, default_ttl=600)


def _cache_get(key: str) -> Any | None:
    return _CACHE.get(key)


def _cache_set(key: str, value: Any, ttl: float) -> None:
    _CACHE.set(key, value, ttl)


# ── Yahoo chart fetch (price leg) ───────────────────────────────────────────────
async def _yahoo_chart(symbol: str, rng: str, interval: str) -> dict[str, Any]:
    """Fetch one Yahoo v8 chart payload, trying both hosts before giving up."""
    last_exc: Exception | None = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
                r = await client.get(url, params={"range": rng, "interval": interval})
            if r.status_code == 200:
                return r.json()
            last_exc = HTTPException(status_code=r.status_code, detail=upstream_detail(r, 200))
        except httpx.RequestError as exc:
            last_exc = exc
    raise HTTPException(status_code=502, detail=f"Yahoo chart unreachable for {symbol}: {last_exc}")


def _parse_quote(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Turn a Yahoo chart payload into a quote + sparkline. Tolerant of nulls."""
    meta_in: dict[str, str] = _META_BY_SYMBOL.get(symbol, {"label": symbol, "category": "", "unit": ""})
    out: dict[str, Any] = {
        "symbol": symbol, "label": meta_in.get("label", symbol),
        "category": meta_in.get("category", ""), "unit": meta_in.get("unit", ""),
        "currency": "USD",
        "price": None, "prev_close": None, "change": None, "change_pct": None,
        "spark": [], "as_of": None, "stale": True,
    }
    try:
        result = payload["chart"]["result"][0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        closes = (result.get("indicators", {}).get("quote", [{}])[0].get("close") or [])
        spark = [round(c, 4) for c in closes if c is not None][-40:]
        if price is None and spark:
            price = spark[-1]
        # SESSION change — prefer the true prior-session close, then the 2nd-to-last
        # daily close. NEVER chartPreviousClose first: on a multi-day range that is the
        # close *before the whole window* (≈1mo ago here), which would mislabel a monthly
        # move as the daily change. chartPreviousClose is only a last-resort fallback.
        prev = meta.get("previousClose")
        if prev is None and len(spark) >= 2:
            prev = spark[-2]
        if prev is None:
            prev = meta.get("chartPreviousClose")
        ts = meta.get("regularMarketTime")
        out.update({
            "price": price,
            "prev_close": prev,
            "change": (price - prev) if (price is not None and prev) else None,
            "change_pct": ((price - prev) / prev * 100.0) if (price is not None and prev) else None,
            "spark": spark,
            "as_of": int(ts) if ts else None,
            "stale": price is None,
        })
    except (KeyError, IndexError, TypeError):
        pass  # leave nulls — honest "no data" rather than fabricated
    return out


# ── FRED fetch (context indices) ────────────────────────────────────────────────
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fred_mode() -> str:
    """'rest' with a FRED_API_KEY, else 'csv' (keyless fredgraph.csv)."""
    return "rest" if FRED_API_KEY else "csv"


def parse_fredgraph_csv(text: str) -> list[dict[str, Any]]:
    """`DATE,<SERIES>` rows → chronological points; '.' (missing) rows are skipped. Pure, tested."""
    points: list[dict[str, Any]] = []
    for line in text.strip().splitlines()[1:]:
        d, _, v = line.partition(",")
        try:
            points.append({"date": d.strip(), "value": float(v)})
        except ValueError:
            continue
    return points


async def _fred_series_csv(series_id: str, limit: int = 120) -> list[dict[str, Any]]:
    """Keyless path: the last ~`limit` observations of a daily series (cosd = today − 1.6 × limit days, so weekends
    and holidays still leave `limit` points), plain client (a browser UA makes FRED stall for 20 s+)."""
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=int(limit * 1.6) + 7)).isoformat()  # noqa: DTZ011 — FRED dates are US calendar days
    async with httpx.AsyncClient(timeout=_TIMEOUT) as plain:
        r = await plain.get(FRED_CSV_URL, params={"id": series_id, "cosd": start})
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"FRED {series_id}: {r.text[:200]}")
    return parse_fredgraph_csv(r.text)[-limit:]


async def _fred_series(series_id: str, limit: int = 120) -> list[dict[str, Any]]:
    if not FRED_API_KEY:
        return await _fred_series_csv(series_id, limit)
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json",
        "sort_order": "desc", "limit": str(limit),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(url, params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"FRED {series_id}: {r.text[:200]}")
    obs = r.json().get("observations", [])
    points = [
        {"date": o["date"], "value": float(o["value"])}
        for o in obs if o.get("value") not in (None, ".", "")
    ]
    points.reverse()  # chronological
    return points


# ── EIA v2 fetch (energy fundamentals) ──────────────────────────────────────────
async def _eia_series(route: str, facet: str, freq: str, length: int = 60) -> list[dict[str, Any]]:
    url = f"https://api.eia.gov/v2/{route}/"
    params = {
        "api_key": EIA_API_KEY, "frequency": freq, "data[0]": "value",
        "facets[series][]": facet, "sort[0][column]": "period",
        "sort[0][direction]": "desc", "length": str(length),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(url, params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"EIA {route}: {r.text[:200]}")
    rows = r.json().get("response", {}).get("data", [])
    points = [
        {"date": str(row.get("period")), "value": float(row["value"])}
        for row in rows if row.get("value") not in (None, "")
    ]
    points.reverse()  # chronological
    return points


# ── Endpoints ───────────────────────────────────────────────────────────────────

@router.get("/health")
async def commodity_health() -> dict[str, Any]:
    """Which legs are live. Price needs no key; EIA/FRED gate on their env keys."""
    return {
        "status": "ok",
        "price_feed": "yahoo-futures (no key)",
        "eia_enabled": bool(EIA_API_KEY),
        "fred_enabled": True,                       # keyless fredgraph.csv when FRED_API_KEY is unset
        "fred_mode": fred_mode(),
        "futures_universe": [f["label"] for f in FUTURES],
    }


@router.get("/overview")
async def commodity_overview() -> dict[str, Any]:
    """
    One aggregated payload for the Commodity tab: the live futures board plus
    EIA/FRED context (when keyed). The board always returns (free price feed);
    fundamentals degrade gracefully to available=false when keys are unset.
    """
    cached = _cache_get("overview")
    if cached is not None:
        return cached

    # Price board — fetch all symbols concurrently (one 1mo/1d call each → price + spark)
    charts = await asyncio.gather(
        *[_yahoo_chart(f["symbol"], "1mo", "1d") for f in FUTURES],
        return_exceptions=True,
    )
    futures: list[dict[str, Any]] = []
    for f, payload in zip(FUTURES, charts):
        if isinstance(payload, BaseException):
            futures.append({**_parse_quote(f["symbol"], {}), "stale": True})
        else:
            futures.append(_parse_quote(f["symbol"], payload))

    # FRED context: REST with a key, keyless fredgraph.csv without one (never a "key required" message)
    fred: dict[str, Any] = {"available": True, "mode": fred_mode(), "series": []}
    results = await asyncio.gather(
        *[_fred_series(s["id"], limit=90) for s in FRED_SERIES],
        return_exceptions=True,
    )
    for s, pts in zip(FRED_SERIES, results):
        if isinstance(pts, BaseException):
            fred["series"].append({**s, "error": str(pts)[:160], "points": []})
        else:
            latest = pts[-1] if pts else None
            fred["series"].append({**s, "latest": latest, "points": pts})
    if all(x.get("error") for x in fred["series"]):
        fred["available"] = False
        fred["reason"] = "FRED unreachable right now (every series failed); the board and EIA legs are unaffected."

    # EIA fundamentals (keyed)
    eia: dict[str, Any] = {"available": bool(EIA_API_KEY), "series": []}
    if EIA_API_KEY:
        results = await asyncio.gather(
            *[_eia_series(s["route"], s["facet"], s["freq"]) for s in EIA_SERIES],
            return_exceptions=True,
        )
        for s, pts in zip(EIA_SERIES, results):
            meta = {k: s[k] for k in ("id", "label", "unit")}
            if isinstance(pts, BaseException):
                eia["series"].append({**meta, "error": str(pts)[:160], "points": []})
            else:
                latest = pts[-1] if pts else None
                eia["series"].append({**meta, "latest": latest, "points": pts})
    else:
        eia["reason"] = "EIA_API_KEY not set — add it to .env to enable (free key)."

    out = {
        "as_of": int(time.time()),
        "futures": futures,
        "fundamentals": {"fred": fred, "eia": eia},
        "sources": {
            "price": "yahoo-futures",
            "eia": bool(EIA_API_KEY),
            "fred": fred["available"],
            "fred_mode": fred_mode(),
        },
        "note": "Live LATEST values for viewing. Backtested factors must use PIT/ALFRED vintages.",
    }
    _cache_set("overview", out, ttl=60.0)
    return out


@router.get("/price/{symbol}")
async def commodity_price(
    symbol: str,
    rng: str = Query(default="6mo", alias="range"),
    interval: str = Query(default="1d"),
) -> dict[str, Any]:
    """Historical OHLC series for one futures symbol (for the detail chart)."""
    if symbol not in _SYMBOLS:
        raise HTTPException(status_code=404, detail=f"unknown symbol '{symbol}'; allowed: {sorted(_SYMBOLS)}")
    ckey = f"price:{symbol}:{rng}:{interval}"
    cached = _cache_get(ckey)
    if cached is not None:
        return cached

    payload = await _yahoo_chart(symbol, rng, interval)
    try:
        result = payload["chart"]["result"][0]
        ts = result.get("timestamp", []) or []
        q = result.get("indicators", {}).get("quote", [{}])[0]
        candles = [
            {
                "t": int(t),
                "o": q.get("open", [None] * len(ts))[i],
                "h": q.get("high", [None] * len(ts))[i],
                "l": q.get("low", [None] * len(ts))[i],
                "c": q.get("close", [None] * len(ts))[i],
            }
            for i, t in enumerate(ts)
        ]
        candles = [c for c in candles if c["c"] is not None]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"malformed chart for {symbol}: {exc}")

    meta = _META_BY_SYMBOL.get(symbol, {})
    out = {
        "symbol": symbol, "label": meta.get("label", symbol),
        "unit": meta.get("unit", ""), "currency": "USD",
        "range": rng, "interval": interval, "candles": candles,
    }
    _cache_set(ckey, out, ttl=300.0)
    return out
