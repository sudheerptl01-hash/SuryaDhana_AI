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

- M42 (5 Nov review: "CHRT cannot chart an index, a future, IV or OI"):
  * an NSE index (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 and their NSE / Yahoo spellings) charts from
    data-service `/db/index-ohlc/{name}` (`index_ohlc_daily`: NSE's daily index file; the oldest rows are close-only and
    are counted in `close_only`), and its intraday bars from the tick store under NSE's index name;
  * GET /overlay?symbol=&kind=iv|oi|future&days=N — the lower pane / price-pane overlays, all from stored tables:
    `iv` = `iv_summary_daily` (iv30_cm, the near ATM IV, RV20 cc; `arithmetic`), `oi` = `nse_fo_daily` aggregate call /
    put / futures OI (`/db/fo/pcr-history`, shares; `context`), `future` = the near-month future's close and basis
    (`/db/fo/basis-history`; `arithmetic`). A missing series degrades to `ok: false` with the reason, never a 500.
- intraday bars outside 09:15–15:30 IST are dropped (the tick store keeps post-close prints), the VWAP is then recomputed
  from the bars shown, and a session that starts late says so (`coverage_note`: 5 Nov's bars began at 13:00, after a
  midday deploy, so its "session VWAP" was an afternoon VWAP).

Event-loop purity: every route is a sync `def` (FastAPI threadpool), so the
blocking httpx calls and the pandas resample never touch the event loop.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

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

# NSE index underlyings (the F&O symbol) and every spelling the terminal / Yahoo / NSE use for them
INDEX_NAMES: dict[str, str] = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FINANCIAL SERVICES",
                               "MIDCPNIFTY": "NIFTY MIDCAP SELECT", "NIFTYNXT50": "NIFTY NEXT 50"}
INDEX_ALIASES: dict[str, str] = {
    **{k: k for k in INDEX_NAMES}, **{v: k for k, v in INDEX_NAMES.items()},
    "NIFTY50": "NIFTY", "NSEI": "NIFTY", "^NSEI": "NIFTY", "NIFTYBANK": "BANKNIFTY", "^NSEBANK": "BANKNIFTY", "NSEBANK": "BANKNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY", "NIFTY MID SELECT": "MIDCPNIFTY", "NIFTY NEXT50": "NIFTYNXT50",
}
OVERLAYS = ("iv", "oi", "future")
SESSION = ("09:15", "15:30")
LATE_START = "09:20"


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
    if sym in INDEX_ALIASES:
        return INDEX_ALIASES[sym]
    if not _SYMBOL_RE.match(sym):
        fail(400, "invalid", f"'{symbol}' is not an NSE symbol",
             hint="Plain NSE ticker, e.g. RELIANCE or BAJAJ-AUTO (no .NS suffix needed), or an index: NIFTY, BANKNIFTY, FINNIFTY")
    return sym


def is_index(sym: str) -> bool:
    return sym in INDEX_NAMES


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


def _fetch_json(path: str, params: dict) -> dict:
    """One data-service read (index OHLC, the IV summary, the F&O aggregates), cached 60 s per (path, params)."""
    key = (path, repr(sorted(params.items())))
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]  # type: ignore[return-value]
    try:
        r = httpx.get(f"{DATA_SVC}{path}", params=params, timeout=_TIMEOUT)
    except httpx.RequestError as exc:
        raise UpstreamError(None, f"data-service unreachable: {exc.__class__.__name__}") from exc
    if r.status_code >= 400:
        raise UpstreamError(r.status_code, str(upstream_detail(r)))
    body = r.json()
    body = body if isinstance(body, dict) else {"rows": body}
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (now, body)  # type: ignore[assignment]
    return body


def _fetch_index_daily(sym: str, days: int) -> tuple[list[dict], int]:
    """Daily bars of an NSE index from `index_ohlc_daily` (NSE's daily index file). Rows with no open / high / low (the
    close-only history) are drawn as a close-only bar and counted."""
    body = _fetch_json(f"/db/index-ohlc/{quote(INDEX_NAMES[sym])}", {"days": min(10000, max(10, int(days * 0.75) + 10))})
    start = (date.today() - timedelta(days=days)).isoformat()
    rows, close_only = [], 0
    for r in body.get("rows") or []:
        d, c = str(r.get("date") or "")[:10], r.get("close")
        if not d or d < start or c is None:
            continue
        o, h, lo = r.get("open"), r.get("high"), r.get("low")
        if o is None or h is None or lo is None:
            close_only += 1
            o = h = lo = c
        rows.append({"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 0})
    return rows, close_only


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
    close_only = 0
    try:
        if is_index(sym):
            rows, close_only = _fetch_index_daily(sym, days)
        else:
            rows = _fetch_daily(sym, start)
    except UpstreamError as exc:
        if exc.status == 404:
            fail(404, "not_found", exc.detail or f"No OHLCV data for {sym}",
                 hint="NSE ticker as in the EQS screener, e.g. RELIANCE, TCS, M&M; or an index: NIFTY, BANKNIFTY")
        fail(502, "upstream_down", exc.detail, hint="./start-local.sh status — is data-service (:8001) up?")
    if is_index(sym) and not rows:
        fail(404, "not_found", f"No index bars stored for {sym} ({INDEX_NAMES[sym]})", hint="index_ohlc_daily is filled by the 19:15 index-file job")
    bars = _resample(rows, tf)
    out = {
        "symbol": sym,
        "tf": tf,
        "days": days,
        "bars": bars,
        "rows": len(bars),
        "as_of": bars[-1]["t"] if bars else None,
        "source": "duckdb-eod",  # data-service DuckDB ohlcv (yahoo history), not live ticks
    }
    if is_index(sym):
        out.update(kind="index", index_name=INDEX_NAMES[sym], source="nse-index-file", close_only=close_only)
    return out


def overlay_points(kind: str, body: dict) -> list[dict]:
    """The overlay's points by date from a data-service payload (pure; unit-tested)."""
    rows = body.get("rows") or body.get("data") or []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = str(r.get("date") or "")[:10]
        if not d:
            continue
        if kind == "iv":
            p = {"t": d, "iv30": r.get("iv30_cm"), "near": r.get("near_atm_iv"), "rv20": r.get("rv20_cc")}
        elif kind == "oi":
            c, pu = r.get("call_oi"), r.get("put_oi")
            p = {"t": d, "call_oi": c, "put_oi": pu, "fut_oi": r.get("fut_oi"),
                 "pcr": round(pu / c, 3) if isinstance(c, (int, float)) and isinstance(pu, (int, float)) and c else None}
        else:
            p = {"t": d, "fut": r.get("fut"), "spot": r.get("spot"), "basis_pct": r.get("basis_pct"),
                 "basis_ann_pct": r.get("basis_ann_pct"), "dte": r.get("dte")}
        out.append(p)
    out.sort(key=lambda p: p["t"])
    return out


_OVERLAY_SPEC = {
    "iv": ("/db/iv/summary", "arithmetic", "iv_summary_daily (Black-76 on the parity forward, b76-pcp-v1)", "% annualised"),
    "oi": ("/db/fo/pcr-history", "context", "NSE F&O bhavcopy aggregates (nse_fo_daily): every strike and expiry", "shares"),
    "future": ("/db/fo/basis-history", "arithmetic", "NSE F&O bhavcopy near-month future close (nse_fo_daily) vs spot", "₹ / % basis"),
}


@router.get("/overlay")
def get_overlay(symbol: str = "NIFTY", kind: str = "iv", days: int = 365) -> dict:
    """A daily overlay for the chart from stored tables: IV30 (iv), F&O open interest (oi) or the near future (future)."""
    sym = _norm_symbol(symbol)
    kind = (kind or "").strip().lower()
    if kind not in OVERLAYS:
        fail(400, "invalid", f"kind must be one of {', '.join(OVERLAYS)} (got '{kind}')")
    days = max(_DAYS_MIN, min(int(days), _DAYS_MAX))
    path, badge, source, unit = _OVERLAY_SPEC[kind]
    sessions = max(20, min(2000, int(days * 0.75) + 10))
    params = {"symbol": sym, "days": sessions}
    base = {"symbol": sym, "kind": kind, "days": days, "points": [], "as_of": None, "badge": badge, "source": source, "unit": unit,
            "note": "describes, does not predict"}
    try:
        body = _fetch_json(path, params)
    except UpstreamError as exc:
        why = exc.detail if exc.status is not None else f"data-service unreachable ({exc.detail})"
        if exc.status == 404 and kind == "future" and is_index(sym) and sym != "NIFTY":
            why = (f"no near-future series served for {sym}: data-service's basis read joins a spot series it holds for "
                   "NIFTY and the stocks only")
        return degraded({**base, "note": why}, "degraded" if exc.status == 404 else "upstream_down", why)
    start = (date.today() - timedelta(days=days)).isoformat()
    pts = [p for p in overlay_points(kind, body) if p["t"] >= start]
    return {**base, "points": pts, "as_of": pts[-1]["t"] if pts else None}


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

    base: dict[str, Any] = {"symbol": sym, "date": day, "interval": interval, "bars": [], "vwap": None, "source": None}
    try:
        body = _fetch_ticks(INDEX_NAMES.get(sym, sym), day, interval)
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
    raw = body.get("bars") or []
    bars = in_session(raw)
    vwap = body.get("vwap")
    if len(bars) != len(raw):
        vwap = bars_vwap(bars)                               # the upstream VWAP included the dropped bars
    out = {
        "symbol": sym,
        "date": body.get("date", day),
        "interval": body.get("interval", interval),
        "bars": bars,
        "vwap": vwap,
        "source": body.get("source"),
    }
    if len(bars) != len(raw):
        out["dropped_outside_session"] = len(raw) - len(bars)
    if bars and str(bars[0].get("t", "")) > LATE_START:
        out["coverage_note"] = (f"the tick store holds nothing before {bars[0]['t']} IST for this session: the VWAP and the "
                                f"session range are since {bars[0]['t']}")
    note = body.get("note")
    if note is None and not bars:
        note = "no ticks stored for this session"
    if note is not None:
        out["note"] = note
    return out


def in_session(bars: list[dict]) -> list[dict]:
    """Bars stamped 09:15–15:30 IST only (the tick store keeps post-close prints: 5 Nov's bars ran to 15:55)."""
    return [b for b in bars if SESSION[0] <= str(b.get("t", ""))[:5] <= SESSION[1]]


def bars_vwap(bars: list[dict]) -> float | None:
    """Volume-weighted typical price of the bars shown; None without volume (an index has none)."""
    num = den = 0.0
    for b in bars:
        try:
            v = float(b.get("v") or 0)
            tp = (float(b["h"]) + float(b["l"]) + float(b["c"])) / 3
        except (KeyError, TypeError, ValueError):
            continue
        if v > 0:
            num += tp * v
            den += v
    return round(num / den, 2) if den else None
