"""charts.py — CHRT chart studio data (worldclass W1).

Two reads, both proxying data-service (:8001 owns DuckDB — never opened here):

- GET /ohlcv?symbol=&tf=D|W|M&days=N — daily EOD bars from data-service
  `/ohlcv/{ticker}`, resampled to weekly/monthly in pandas. Each W/M bar is
  labelled with the LAST TRADING DAY of its bucket (what the exchange actually
  traded — never a synthetic Sunday or calendar month-end).

- GET /intraday?symbol=&date=&interval=1m|5m|15m — proxy of data-service
  `/ticks/bars` (W6 tick store). Until that endpoint is live, a 404 (or an
  unreachable data-service) degrades to HTTP 200 with `bars: []` and
  `note: "tick store not live"` via errors.degraded() — the chart falls back
  to daily instead of showing a red error.

Event-loop purity: every route is a sync `def` (FastAPI threadpool), so the
blocking httpx calls and the pandas resample never touch the event loop.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, timedelta

import httpx
import pandas as pd
from fastapi import APIRouter, Query

from errors import degraded, fail
from routers._upstream import upstream_detail

router = APIRouter()

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
_TIMEOUT = httpx.Timeout(20.0)

TIMEFRAMES = ("D", "W", "M")
INTERVALS = ("1m", "5m", "15m")
_SYMBOL_RE = re.compile(r"^[A-Z0-9&.\-]{1,20}$")

# tf → pandas Period alias for the resample buckets (ISO week Mon–Sun / calendar month;
# a Mon–Fri trading week always lands inside one W-SUN period).
_PERIOD = {"W": "W", "M": "M"}

_DAYS_MIN, _DAYS_MAX = 10, 7320  # ~20 years; the panel starts 2010


class UpstreamError(Exception):
    """A data-service call that did not yield usable JSON. status=None → unreachable."""

    def __init__(self, status: int | None, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _norm_symbol(symbol: str) -> str:
    sym = (symbol or "").strip().upper()
    if sym.endswith(".NS"):
        sym = sym[:-3]
    if not _SYMBOL_RE.match(sym):
        fail(400, "invalid", f"'{symbol}' is not an NSE symbol",
             hint="Plain NSE ticker, e.g. RELIANCE or BAJAJ-AUTO (no .NS suffix needed)")
    return sym


# ── upstream fetches (monkeypatched in tests; the 60 s cache lives inside) ───────

_CACHE_TTL = 60.0
_CACHE_MAX = 64
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def _fetch_daily(symbol: str, start: date) -> list[dict]:
    """Daily OHLCV rows from data-service, cached 60 s per (symbol, start) so a D→W→M
    timeframe flip re-resamples the same pull instead of re-reading DuckDB."""
    key = (symbol, start.isoformat())
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    try:
        r = httpx.get(f"{DATA_SVC}/ohlcv/{symbol}", params={"start": start.isoformat()},
                      timeout=_TIMEOUT)
    except httpx.RequestError as exc:
        raise UpstreamError(None, f"data-service unreachable: {exc.__class__.__name__}") from exc
    if r.status_code >= 400:
        raise UpstreamError(r.status_code, str(upstream_detail(r)))
    rows = r.json().get("data", [])
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (now, rows)
    return rows


def _fetch_ticks(symbol: str, day: str, interval: str) -> dict:
    """One session of tick-built bars from data-service /ticks/bars (W6 contract)."""
    try:
        r = httpx.get(f"{DATA_SVC}/ticks/bars",
                      params={"symbol": symbol, "date": day, "interval": interval},
                      timeout=_TIMEOUT)
    except httpx.RequestError as exc:
        raise UpstreamError(None, f"data-service unreachable: {exc.__class__.__name__}") from exc
    if r.status_code >= 400:
        raise UpstreamError(r.status_code, str(upstream_detail(r)))
    body = r.json()
    return body if isinstance(body, dict) else {}


# ── resample ─────────────────────────────────────────────────────────────────────

def _resample(rows: list[dict], tf: str) -> list[dict]:
    """Daily rows → bars for tf. W/M aggregate open=first, high=max, low=min,
    close=last, volume=sum over the bucket's trading days; the bar's `t` is the
    bucket's last trading day."""
    if not rows:
        return []
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"].astype(str).str[:10])
    df = df.sort_values("date")
    if tf != "D":
        df = (
            df.groupby(df["date"].dt.to_period(_PERIOD[tf]), sort=True)
            .agg(date=("date", "max"), open=("open", "first"), high=("high", "max"),
                 low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
            .reset_index(drop=True)
        )
    return [
        {
            "t": d.strftime("%Y-%m-%d"),
            "o": round(float(o), 2),
            "h": round(float(h), 2),
            "l": round(float(lo), 2),
            "c": round(float(c), 2),
            "v": int(v) if pd.notna(v) else 0,
        }
        for d, o, h, lo, c, v in zip(df["date"], df["open"], df["high"], df["low"],
                                     df["close"], df["volume"])
    ]


# ── routes (sync def on purpose: threadpool, loop stays free) ────────────────────

@router.get("/ohlcv")
def get_ohlcv(symbol: str = "RELIANCE", tf: str = "D", days: int = 365) -> dict:
    """Resampled OHLCV for the chart studio. `days` is the EOD lookback window in
    calendar days (clamped to 10…7320) that the W/M bars are built from."""
    sym = _norm_symbol(symbol)
    tf = tf.strip().upper()
    if tf not in TIMEFRAMES:
        fail(400, "invalid", f"tf must be one of D, W, M (got '{tf}')",
             hint="Intraday goes through /api/charts/intraday")
    days = max(_DAYS_MIN, min(int(days), _DAYS_MAX))
    start = date.today() - timedelta(days=days)
    try:
        rows = _fetch_daily(sym, start)
    except UpstreamError as exc:
        if exc.status == 404:
            fail(404, "not_found", exc.detail or f"No OHLCV data for {sym}",
                 hint="NSE ticker as in the EQS screener, e.g. RELIANCE, TCS, M&M")
        fail(502, "upstream_down", exc.detail, hint="./start-local.sh status — is data-service (:8001) up?")
    bars = _resample(rows, tf)
    return {
        "symbol": sym,
        "tf": tf,
        "days": days,
        "bars": bars,
        "rows": len(bars),
        "as_of": bars[-1]["t"] if bars else None,
        "source": "duckdb-eod",  # data-service DuckDB ohlcv (yahoo history), not live ticks
    }


@router.get("/intraday")
def get_intraday(symbol: str = "RELIANCE", interval: str = "1m",
                 day: str | None = Query(None, alias="date")) -> dict:
    """Intraday bars for one session from the W6 tick store, degraded-200 until it lands."""
    sym = _norm_symbol(symbol)
    interval = interval.strip().lower()
    if interval not in INTERVALS:
        fail(400, "invalid", f"interval must be one of 1m, 5m, 15m (got '{interval}')")
    day = (day or "").strip()
    if not day:
        day = date.today().isoformat()
    else:
        try:
            date.fromisoformat(day)
        except ValueError:
            fail(400, "invalid", f"date must be YYYY-MM-DD (got '{day}')")

    base = {"symbol": sym, "date": day, "interval": interval, "bars": [], "vwap": None, "source": None}
    try:
        body = _fetch_ticks(sym, day, interval)
    except UpstreamError as exc:
        if exc.status == 404:
            # W6's /ticks/bars is not integrated yet (or holds nothing for this session):
            # a usable 200 so the chart falls back to daily without a red error state.
            return degraded({**base, "note": "tick store not live"}, "degraded",
                            "tick store not live",
                            hint="Intraday bars appear once tick persistence (W6) is integrated")
        if exc.status is None:
            return degraded({**base, "note": "data-service unreachable"}, "upstream_down",
                            exc.detail, hint="./start-local.sh status — is data-service (:8001) up?")
        fail(502, "upstream_down", exc.detail)
    bars = body.get("bars") or []
    out = {
        "symbol": body.get("symbol", sym),
        "date": body.get("date", day),
        "interval": body.get("interval", interval),
        "bars": bars,
        "vwap": body.get("vwap"),
        "source": body.get("source"),
    }
    note = body.get("note")
    if note is None and not bars:
        note = "no ticks stored for this session"
    if note is not None:
        out["note"] = note
    return out
