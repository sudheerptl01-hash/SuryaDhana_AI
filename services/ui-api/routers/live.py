"""Live NSE quotes for every pane: the ui-api half of the live contract (live NSE program, builder LV-API, 5 Nov 2026).

Routes (mounted at ``/api/live`` in main.py):

* ``GET /api/live/quotes?symbols=A,B`` -- at most ``MAX_SYMBOLS`` (300) NSE symbols: stocks (``RELIANCE``, ``M&M``; a
  ``.NS`` suffix is accepted and dropped) and indices by their NSE name (``NIFTY 50``, ``NIFTY BANK``, ``INDIA VIX``).
  The body is data-service's ``/live/quotes`` body, ``{as_of, market: {state, session_date}, quotes: {SYM: {price, change,
  change_pct, prev_close, open, day_high, day_low, volume, value_cr, bid, ask, ltt, source, age_s, state, reason?}}}``,
  plus one ``upstream: {ok, last_ok_at, error}`` block (a superset: nothing the contract names is renamed).
* ``GET /api/live/status`` -- data-service's ``/live/status`` (engine state, subscribed, ticks per minute, last-tick
  age, cap, Breeze session, NSE fallback health) plus ``ui_api``: this hub's counters, for the SYS live-feeds row.

How a quote is served (all on the event loop; nothing here blocks, nothing here calls a publisher):

* **One hub per process** (``hub()``), reached through ``shared.http_client.get_json`` (the process-wide keep-alive
  client, the host allowlist, a breaker of its own named ``data-service-live`` so a failing live route never opens the
  breaker of every other data-service read).
* **Per-symbol cache, at most one data-service request per symbol per ``REFRESH_S`` (2 s) app-wide.** A symbol answered
  less than 2 s ago is served from the cache; the rest of a request goes out as ONE batch; a symbol already in a batch
  that is in flight is not asked again: the caller joins that batch (single flight). Polling windows, the news-scanner
  quote path, ``/api/quotes/ticks`` and the WebSocket push all share it, so N windows cost the same as one.
* **Ages are honest.** ``age_s`` = data-service's age + the time the row spent in this cache. The ``state`` is
  data-service's (it alone knows the Breeze socket and the NSE fallback) as long as the row is inside the 2 s window.
* **Stale-serve with state.** When data-service fails (down, 5xx, breaker open, a malformed body), the last good row of
  each symbol is served for up to ``STALE_SERVE_S`` and re-stated from its total age: ``live`` -> ``delayed`` (<= 90 s)
  -> ``stale``; ``reason`` says why. Beyond that, or for a symbol never answered, the row is ``unavailable`` with the
  reason. There is no other fallback: never Yahoo, never a guessed price (the honesty rules of the live program).

The news-scanner quote path (``news_quotes``) and ``/api/quotes/ticks`` (routers/quotes.py) are built on the hub, so
Yahoo is never the source of an NSE stock's price once this module answers. ``news_quotes`` adds the stored EOD
context the hover card, WTCH and the news dock show beside the price (a 22-session split-adjusted spark, the 52-week
range, the previous session's date) from data-service's NSE bhavcopy history, cached 30 min (SWR, 6 h bound).

Push (optional channel, R-ARCH fix 7): ``QuotesChannel`` is one monitor-socket client of ``QuotesPush``, ONE loop per
process that polls the hub every ``PUSH_INTERVAL_S`` for the union of every subscribed symbol and offers each client
the rows that changed (a full snapshot every ``PUSH_FULL_EVERY_S``) into a bounded queue that drops the oldest message
and counts it. The monitor socket (routers/monitor.py) wires it for ``{"action": "subscribe", "channel": "quotes",
"symbols": [...]}``; polling at 2-5 s stays the baseline.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import math
import os
import re
import sys
import time
import weakref
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote as _urlquote

import httpx
from cache import HIT, MISS, STALE, Served, SWRCache, cache_headers
from errors import fail
from fastapi import APIRouter, Query, Response

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.http_client import UpstreamError, get_json  # noqa: E402

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))
MAX_SYMBOLS = 300                    # per request (the contract's cap); a batch to data-service is at most this
REFRESH_S = 2.0                      # a symbol is asked of data-service at most once per REFRESH_S, app-wide
STALE_SERVE_S = 900.0                # how long a last good row may be served (re-stated) while data-service fails
MAX_ROWS = 3000                      # LRU bound of the per-symbol cache
LIVE_MAX_S = 5.0                     # the contract's "live" bound (data-service decides; used only to re-state)
DELAYED_MAX_S = 90.0                 # the contract's "delayed" bound
LIVE_TIMEOUT = httpx.Timeout(6.0, connect=2.0)
UPSTREAM = "data-service-live"       # breaker name: a failing live route never opens the breaker of other reads
STATUS_REFRESH_S = 2.0
STATUS_STALE_S = 60.0
STATES: tuple[str, ...] = ("live", "delayed", "stale", "closed", "unavailable")
DECISION_STATES: frozenset[str] = frozenset({"live", "delayed", "closed"})   # what a DECIDING read may act on
ENGINE_STATES: tuple[str, ...] = ("OFF", "CONNECTING", "LIVE", "DEGRADED", "DISCONNECTED")
NUM_FIELDS: tuple[str, ...] = ("price", "change", "change_pct", "prev_close", "open", "day_high", "day_low", "volume",
                               "value_cr", "bid", "ask")
_POSITIVE_FIELDS = frozenset({"price", "prev_close", "open", "day_high", "day_low", "bid", "ask"})
KNOWN_FIELDS = frozenset(NUM_FIELDS) | {"ltt", "source", "age_s", "state", "reason"}
MAX_EXTRA_KEYS = 12

_SYM_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")                       # NSE stock symbols: RELIANCE, M&M, BAJAJ-AUTO
_INDEX_RE = re.compile(r"^[A-Z0-9][A-Z0-9 &:/.()%-]{2,59}$")        # NSE index names (with a space): NIFTY 50, INDIA VIX
# The spellings data-service's live_ticks.canonical() maps to NSE index names: asking with the canonical name keys the
# answer the same way on both sides ('NIFTY' and '^NSEI' are answered as 'NIFTY 50').
LEGACY_INDEX_NAMES: dict[str, str] = {"NIFTY": "NIFTY 50", "NIFTY50": "NIFTY 50", "NSEI": "NIFTY 50", "^NSEI": "NIFTY 50",
                                      "BANKNIFTY": "NIFTY BANK", "NIFTYBANK": "NIFTY BANK", "^NSEBANK": "NIFTY BANK",
                                      "INDIAVIX": "INDIA VIX", "^INDIAVIX": "INDIA VIX"}
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,23}$")                 # source / market-state words
_EXTRA_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_ENGINE_RE = re.compile(r"^[A-Z][A-Z_\-]{0,23}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def data_svc() -> str:
    """data-service base URL, read per call (tests and the PM's env override it)."""
    return os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")


def nse_live_enabled() -> bool:
    """Kill switch for the news-scanner quote path: ``LIVE_QUOTES_NSE=0`` puts '.NS' symbols back on the legacy Yahoo
    path (a rollback lever for the deploy, never the default). /api/live/* and /api/quotes/ticks ignore it."""
    return os.environ.get("LIVE_QUOTES_NSE", "1").strip() != "0"


def now_ist() -> datetime:
    return datetime.now(IST)


# ── symbols ───────────────────────────────────────────────────────────────────────────────────────────────────────

def normalize_symbol(raw: Any) -> str:
    """'reliance.ns' -> 'RELIANCE'; ' nifty  50 ' -> 'NIFTY 50'; 'BANKNIFTY' / '^NSEBANK' -> 'NIFTY BANK' (the same
    canonical names as data-service). Raises ValueError for anything else (a '.BO' or '^GSPC' symbol is not NSE)."""
    if not isinstance(raw, str):
        raise ValueError(f"invalid NSE symbol {raw!r}")
    s = " ".join(raw.strip().upper().split())
    if s.endswith(".NS"):
        s = s[:-3].rstrip()
    s = LEGACY_INDEX_NAMES.get(s, s)
    if (_INDEX_RE.fullmatch(s) if " " in s else _SYM_RE.fullmatch(s)):
        return s
    raise ValueError(f"invalid NSE symbol {raw!r}")


def normalize_symbols(raw: str | Iterable[Any], *, limit: int = MAX_SYMBOLS) -> list[str]:
    """Comma-separated text or a list -> unique NSE symbols in request order. Raises ValueError on a bad symbol, an
    empty list or more than ``limit`` symbols (named in the message)."""
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    out = list(dict.fromkeys(normalize_symbol(x) for x in items if not (isinstance(x, str) and not x.strip())))
    if not out:
        raise ValueError("no symbols given")
    if len(out) > limit:
        raise ValueError(f"at most {limit} symbols per request ({len(out)} given)")
    return out


def is_stock_symbol(sym: str) -> bool:
    """A stock symbol (has an NSE bhavcopy history), not an index name."""
    return bool(_SYM_RE.fullmatch(sym))


# ── row validation (never trust the upstream body) ──────────────────────────────────────────────────────────────────

def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.replace(",", "").strip())
        except ValueError:
            return None
    else:
        return None
    return f if math.isfinite(f) else None


def small_json(v: Any, limit: int = 4000) -> bool:
    """A parsed-JSON value small enough to pass through (status extras, the quotes body's feed block)."""
    try:
        return len(json.dumps(v, allow_nan=False)) <= limit
    except (TypeError, ValueError):
        return False


def unavailable_row(reason: str) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(NUM_FIELDS)
    row.update(ltt=None, source=None, age_s=None, state="unavailable", reason=reason[:200])
    return row


def coerce_row(raw: Any) -> dict[str, Any]:
    """One upstream quote row -> the contract row: numbers finite (else None), prices > 0 (index ticks carry '' or 0
    bids), state in STATES (else 'unavailable'), a row without a price is 'unavailable', short scalar extras kept."""
    if not isinstance(raw, dict):
        return unavailable_row("malformed row in the data-service answer")
    row: dict[str, Any] = {}
    for k in NUM_FIELDS:
        v = _num(raw.get(k))
        if v is not None and k in _POSITIVE_FIELDS and v <= 0:
            v = None
        row[k] = v
    vol = row["volume"]
    if vol is not None:
        row["volume"] = int(vol) if vol.is_integer() and vol >= 0 else (None if vol < 0 else vol)
    ltt = raw.get("ltt")
    row["ltt"] = ltt if isinstance(ltt, str) and 0 < len(ltt) <= 40 else None
    src = raw.get("source")
    row["source"] = src if isinstance(src, str) and _TOKEN_RE.fullmatch(src) else None
    age = _num(raw.get("age_s"))
    row["age_s"] = round(age, 1) if age is not None and age >= 0 else None
    state = raw.get("state")
    state = state if isinstance(state, str) and state in STATES else "unavailable"
    reason = raw.get("reason")
    reason = reason[:200] if isinstance(reason, str) and reason.strip() else None
    if row["price"] is None and state != "unavailable":
        state, reason = "unavailable", reason or "no price in the data-service row"
    if state == "unavailable" and reason is None:
        reason = "data-service has no price for this symbol"
    row["state"] = state
    if reason is not None:
        row["reason"] = reason
    extras = 0
    for k, v in raw.items():
        if extras >= MAX_EXTRA_KEYS:
            break
        if k in KNOWN_FIELDS or not isinstance(k, str) or not _EXTRA_KEY_RE.fullmatch(k):
            continue
        scalar = v is None or isinstance(v, bool) or (isinstance(v, str) and len(v) <= 120)
        if not (scalar or (isinstance(v, (int, float)) and math.isfinite(float(v)))):
            continue
        row[k] = v
        extras += 1
    return row


def restate(row: dict[str, Any], extra_s: float, *, upstream_failed: bool) -> dict[str, Any]:
    """The row as served ``extra_s`` after data-service gave it: ``age_s`` grows by the cache time; when the refresh
    failed (served past REFRESH_S) the state is re-derived from the total age and ``reason`` says so."""
    out = dict(row)
    if out.get("age_s") is not None:
        out["age_s"] = round(out["age_s"] + extra_s, 1)
    if upstream_failed and out.get("state") != "unavailable":
        age = out["age_s"] if out.get("age_s") is not None else extra_s
        st = out.get("state")
        if st == "live":
            st = "delayed" if age <= DELAYED_MAX_S else "stale"
        elif st == "delayed" and age > DELAYED_MAX_S:
            st = "stale"
        out["state"] = st
        out["reason"] = f"data-service did not answer; the row it gave {int(extra_s)} s ago is shown"
    return out


def coerce_market(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    st = raw.get("state")
    sd = raw.get("session_date")
    return {"state": st if isinstance(st, str) and _TOKEN_RE.fullmatch(st) else "unknown",
            "session_date": sd if isinstance(sd, str) and _DATE_RE.fullmatch(sd) else None}


def clock_market(now: datetime) -> dict[str, Any]:
    """Market state from the IST clock alone (used only when data-service never answered): NSE holidays not applied."""
    hm = now.hour * 60 + now.minute
    weekday = now.weekday() < 5
    if weekday and 9 * 60 <= hm < 9 * 60 + 15:
        state = "pre-open"
    elif weekday and 9 * 60 + 15 <= hm < 15 * 60 + 30:
        state = "open"
    else:
        state = "closed"
    d = now.date()
    if not (weekday and hm >= 9 * 60):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return {"state": state, "session_date": d.isoformat(),
            "reason": "from the clock: data-service did not answer (NSE holidays not applied)"}


# ── the hub ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class _Cached:
    row: dict[str, Any]
    at: float                         # clock() when data-service answered


@dataclass(frozen=True)
class Snapshot:
    """One hub answer: the contract body, and what was served for the X-Cache headers (oldest cache age)."""

    payload: dict[str, Any]
    served: Served[None]


def _retrieve(task: asyncio.Task[Any]) -> None:
    """Mark a task's exception retrieved (a batch whose every caller gave up)."""
    if not task.cancelled():
        task.exception()


class LiveQuotesHub:
    """Per-symbol cache + single-flight batches in front of data-service ``/live/quotes`` (see the module docstring).
    Event-loop confined (no thread touches it); one instance per process, loops are told apart for in-flight work."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, wall: Callable[[], datetime] = now_ist) -> None:
        self._clock, self._wall = clock, wall
        self._rows: OrderedDict[str, _Cached] = OrderedDict()
        self._inflight: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task[None]]] = {}
        self._market: dict[str, Any] | None = None
        self._market_at: float | None = None
        self._feed: dict[str, Any] | None = None       # the quotes body's feed-health block, when data-service sends one
        self.last_ok_at: str | None = None
        self.last_error: str | None = None
        self.last_call_ok: bool | None = None
        self.counts: dict[str, int] = {"requests": 0, "symbols_asked": 0, "cache_hits": 0, "coalesced": 0,
                                       "upstream_calls": 0, "upstream_symbols": 0, "upstream_errors": 0,
                                       "stale_rows_served": 0, "unavailable_rows_served": 0}

    # ── public ──
    async def quotes(self, symbols: list[str]) -> Snapshot:
        """Rows for already-normalised ``symbols`` (see ``normalize_symbols``), in that order."""
        loop = asyncio.get_running_loop()
        now = self._clock()
        self.counts["requests"] += 1
        self.counts["symbols_asked"] += len(symbols)
        waits: dict[int, asyncio.Task[None]] = {}
        need: list[str] = []
        for s in symbols:
            c = self._rows.get(s)
            if c is not None and now - c.at < REFRESH_S:
                self.counts["cache_hits"] += 1
                continue
            cur = self._inflight.get(s)
            if cur is not None and cur[0] is loop and not cur[1].done():
                waits[id(cur[1])] = cur[1]
                self.counts["coalesced"] += 1
                continue
            need.append(s)
        for i in range(0, len(need), MAX_SYMBOLS):
            chunk = tuple(need[i:i + MAX_SYMBOLS])
            task = loop.create_task(self._fetch(chunk), name="live-quotes-batch")
            for s in chunk:
                self._inflight[s] = (loop, task)
            task.add_done_callback(functools.partial(self._done, chunk))
            waits[id(task)] = task
        if waits:
            # shield: a caller that gives up (client gone) never cancels the batch the others wait for
            await asyncio.gather(*(asyncio.shield(t) for t in waits.values()), return_exceptions=True)
        return self._assemble(symbols, fetched=bool(waits))

    def stats(self) -> dict[str, Any]:
        return {"name": "live.quotes_hub", "kind": "live", "rows_cached": len(self._rows),
                "inflight": sum(1 for _, t in self._inflight.values() if not t.done()),
                "refresh_s": REFRESH_S, "stale_serve_s": STALE_SERVE_S, "max_symbols": MAX_SYMBOLS,
                "last_ok_at": self.last_ok_at, "last_error": self.last_error, **self.counts}

    def reset(self) -> None:
        """Tests: forget every row, the market and the counters."""
        self._rows.clear()
        self._inflight.clear()
        self._market = self._market_at = None
        self._feed = None
        self.last_ok_at = self.last_error = self.last_call_ok = None
        for k in self.counts:
            self.counts[k] = 0

    # ── internals ──
    async def _fetch(self, chunk: tuple[str, ...]) -> None:
        self.counts["upstream_calls"] += 1
        self.counts["upstream_symbols"] += len(chunk)
        try:
            body = await get_json(f"{data_svc()}/live/quotes", route="live", params={"symbols": ",".join(chunk)},
                                  upstream=UPSTREAM, timeout=LIVE_TIMEOUT)
        except UpstreamError as exc:
            hint = " (the live route is not deployed on data-service)" if exc.status_code == 404 else ""
            self._failed(f"HTTP {exc.status_code}: {exc.detail}{hint}")
            return
        except Exception as exc:  # noqa: BLE001 -- an unexpected client error must not reach the callers
            self._failed(f"{type(exc).__name__}: {exc}")
            return
        quotes = body.get("quotes") if isinstance(body, dict) else None
        if not isinstance(quotes, dict):
            self._failed("data-service answered without a quotes map")
            return
        at = self._clock()
        by_upper = {str(k).strip().upper(): v for k, v in quotes.items()}
        market = coerce_market(body.get("market"))
        if market is not None:
            self._market, self._market_at = market, at
        feed = body.get("feed")
        self._feed = dict(feed) if isinstance(feed, dict) and small_json(feed, 2000) else None
        for s in chunk:
            raw = quotes.get(s, by_upper.get(s))
            row = coerce_row(raw) if raw is not None else unavailable_row("not in the data-service answer")
            self._rows[s] = _Cached(row, at)
            self._rows.move_to_end(s)
        self.last_ok_at = self._wall().isoformat(timespec="seconds")
        self.last_error, self.last_call_ok = None, True
        self._evict(at)

    def _failed(self, why: str) -> None:
        self.counts["upstream_errors"] += 1
        self.last_error, self.last_call_ok = why[:300], False

    def _done(self, chunk: tuple[str, ...], task: asyncio.Task[None]) -> None:
        for s in chunk:
            cur = self._inflight.get(s)
            if cur is not None and cur[1] is task:
                del self._inflight[s]
        _retrieve(task)

    def _evict(self, now: float) -> None:
        for s in [s for s, c in self._rows.items() if now - c.at > STALE_SERVE_S]:
            del self._rows[s]
        while len(self._rows) > MAX_ROWS:
            self._rows.popitem(last=False)

    def _why_unavailable(self) -> str:
        if self.last_error:
            return f"data-service did not answer: {self.last_error}"[:200]
        return "no answer from data-service yet"

    def _market_view(self, now: float) -> dict[str, Any]:
        if self._market is not None and self._market_at is not None and now - self._market_at <= STALE_SERVE_S:
            return dict(self._market)
        return clock_market(self._wall())

    def _assemble(self, symbols: list[str], *, fetched: bool) -> Snapshot:
        now = self._clock()
        out: dict[str, dict[str, Any]] = {}
        oldest = 0.0
        any_stale = False
        for s in symbols:
            c = self._rows.get(s)
            if c is None:
                out[s] = unavailable_row(self._why_unavailable())
                self.counts["unavailable_rows_served"] += 1
                continue
            extra = max(0.0, now - c.at)
            failed = extra >= REFRESH_S
            if failed and extra > STALE_SERVE_S:
                out[s] = unavailable_row(self._why_unavailable())
                self.counts["unavailable_rows_served"] += 1
                continue
            out[s] = restate(c.row, extra, upstream_failed=failed)
            oldest = max(oldest, extra)
            if failed:
                any_stale = True
                self.counts["stale_rows_served"] += 1
        state = STALE if any_stale else (MISS if fetched else HIT)
        fresh_market = self._market_at is not None and now - self._market_at < REFRESH_S
        payload = {"as_of": self._wall().isoformat(timespec="seconds"), "market": self._market_view(now), "quotes": out,
                   "feed": dict(self._feed) if self._feed is not None and fresh_market else None,
                   "upstream": {"ok": self.last_call_ok is not False, "last_ok_at": self.last_ok_at,
                                "error": self.last_error}}
        return Snapshot(payload, Served(None, oldest, state))


_hub: LiveQuotesHub | None = None


def hub() -> LiveQuotesHub:
    """The process-wide hub."""
    global _hub
    if _hub is None:
        _hub = LiveQuotesHub()
    return _hub


# ── status ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def coerce_status(raw: Any) -> dict[str, Any]:
    """data-service ``/live/status`` -> the contract fields, typed; short scalar extras kept (error, ...)."""
    if not isinstance(raw, dict):
        raise UpstreamError(502, "data-service live status is not an object", upstream=UPSTREAM)
    st = raw.get("state")
    state = st.upper() if isinstance(st, str) and _ENGINE_RE.fullmatch(st.upper()) else "DEGRADED"
    nse_raw = raw.get("nse_fallback")
    nse: dict[str, Any] = nse_raw if isinstance(nse_raw, dict) else {}
    last_ok = nse.get("last_ok_at")
    nse_extra = {k: v for k, v in nse.items() if isinstance(k, str) and _EXTRA_KEY_RE.fullmatch(k)
                 and k not in ("ok", "last_ok_at") and small_json(v, 1000)}

    def _int(v: Any) -> int | None:
        f = _num(v)
        return int(f) if f is not None and f >= 0 else None

    out: dict[str, Any] = {
        "state": state,
        "subscribed": _int(raw.get("subscribed")),
        "ticks_per_min": _num(raw.get("ticks_per_min")),
        "last_tick_age_s": _num(raw.get("last_tick_age_s")),
        "cap": _int(raw.get("cap")),
        "breeze_session": raw.get("breeze_session") is True,
        "nse_fallback": {**nse_extra, "ok": nse.get("ok") is True,
                         "last_ok_at": last_ok if isinstance(last_ok, str) else None},
    }
    if state not in ENGINE_STATES:
        out["note"] = f"engine state {state} is outside the contract's list"
    known = set(out) | {"note"}
    extras = 0
    for k, v in raw.items():
        if extras >= 2 * MAX_EXTRA_KEYS:
            break
        if k in known or not isinstance(k, str) or not _EXTRA_KEY_RE.fullmatch(k) or not small_json(v):
            continue
        out[k] = v                                   # error, enabled, pinned, unmapped_ticks, no_first_tick, market ...
        extras += 1
    return out


class LiveStatusCache:
    """``/live/status`` behind a 2 s single-flight cache; the last good body is served (marked stale) for 60 s."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._body: dict[str, Any] | None = None
        self._at = 0.0
        self._inflight: tuple[asyncio.AbstractEventLoop, asyncio.Task[None]] | None = None
        self.calls = 0

    async def get(self) -> tuple[dict[str, Any], float, bool]:
        """(body, age_s, stale). Raises UpstreamError when data-service fails and nothing recent is cached."""
        now = self._clock()
        if self._body is not None and now - self._at < STATUS_REFRESH_S:
            return self._body, now - self._at, False
        loop = asyncio.get_running_loop()
        cur = self._inflight
        if cur is None or cur[0] is not loop or cur[1].done():
            task = loop.create_task(self._fetch(), name="live-status")
            task.add_done_callback(_retrieve)
            self._inflight = cur = (loop, task)
        try:
            await asyncio.shield(cur[1])
        except Exception:
            age = self._clock() - self._at
            if self._body is not None and age <= STATUS_STALE_S:
                return self._body, age, True
            raise
        return self._body or {}, max(0.0, self._clock() - self._at), False

    async def _fetch(self) -> None:
        self.calls += 1
        try:
            raw = await get_json(f"{data_svc()}/live/status", route="live", upstream=UPSTREAM, timeout=LIVE_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the caller as one error type
            if isinstance(exc, UpstreamError):
                raise
            raise UpstreamError(503, f"{type(exc).__name__}: {exc}"[:300], upstream=UPSTREAM) from exc
        self._body, self._at = coerce_status(raw), self._clock()

    def reset(self) -> None:
        self._body, self._at, self._inflight, self.calls = None, 0.0, None, 0


_status: LiveStatusCache | None = None


def status_cache() -> LiveStatusCache:
    global _status
    if _status is None:
        _status = LiveStatusCache()
    return _status


def status_view(body: dict[str, Any], age: float, stale: bool) -> dict[str, Any]:
    out = dict(body)
    if out.get("last_tick_age_s") is not None:
        out["last_tick_age_s"] = round(out["last_tick_age_s"] + age, 1)
    out["stale"] = stale
    if stale:
        out["stale_age_s"] = round(age, 1)
    return out


async def status_or_none() -> dict[str, Any] | None:
    """The status view, or None when data-service cannot say (for routes that degrade instead of failing)."""
    try:
        return status_view(*(await status_cache().get()))
    except UpstreamError:
        return None


# ── stored EOD context for the news-scanner quote shape (spark, 52-week range, previous session date) ──────────────

CTX_DAYS = 366                    # 52 weeks of NSE bhavcopy history (data-service /db/security/{sym}/history)
CTX_REFRESH_S = 1800.0            # EOD data change once a day (bhavcopy ~18:30): refresh after 30 min ...
CTX_MAX_AGE_S = 6 * 3600.0        # ... never served older than 6 h
CTX_MISSING_S = 3600.0            # "not in the bhavcopy" is kept an hour
CTX_WAIT_S = 1.5                  # a quote never waits longer than this for its context (the fetch goes on)
CTX_CONCURRENCY = 4
CTX_UPSTREAM = "data-service-eod-context"
SPARK_N = 22


@dataclass(frozen=True)
class EodContext:
    found: bool
    dates: tuple[str, ...] = ()           # newest first (3 sessions)
    spark: tuple[float, ...] = ()         # split/bonus-adjusted closes, oldest first
    high_52w: float | None = None
    low_52w: float | None = None
    last_date: str | None = None


def eod_context_from_history(body: Any) -> EodContext:
    """data-service HP body (rows newest first, ``action_k`` on ex-dates, ``summary.high/low`` adjusted) -> context.
    Closes before an ex-date are multiplied by its ``action_k`` so a split is not drawn as a crash."""
    if not isinstance(body, dict) or not body.get("found"):
        return EodContext(found=False)
    rows = [r for r in body.get("rows") or [] if isinstance(r, dict) and isinstance(r.get("date"), str)
            and _num(r.get("close")) is not None]
    if not rows:
        return EodContext(found=False)
    k = 1.0
    adj: list[float] = []
    for r in rows[:SPARK_N]:
        close = _num(r.get("close"))
        if close is None:                 # filtered above; keeps the type checker honest
            continue
        adj.append(round(close * k, 4))
        ak = _num(r.get("action_k"))
        if ak is not None and ak > 0:
            k *= ak
    summary_raw = body.get("summary")
    summary: dict[str, Any] = summary_raw if isinstance(summary_raw, dict) else {}
    return EodContext(found=True, dates=tuple(r["date"] for r in rows[:3]), spark=tuple(reversed(adj)),
                      high_52w=_num(summary.get("high")), low_52w=_num(summary.get("low")), last_date=rows[0]["date"])


_ctx_cache = SWRCache("live.eod_context", max_items=2000, refresh_after=CTX_REFRESH_S, max_age=CTX_MAX_AGE_S)
_ctx_sems: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _ctx_sem() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _ctx_sems.get(loop)
    if sem is None:
        sem = _ctx_sems[loop] = asyncio.Semaphore(CTX_CONCURRENCY)
    return sem


def _ctx_policy(value: EodContext) -> tuple[float, float]:
    return (CTX_REFRESH_S, CTX_MAX_AGE_S) if value.found else (CTX_MISSING_S, CTX_MISSING_S)


async def _fetch_ctx(base: str) -> EodContext:
    async with _ctx_sem():
        try:
            body = await get_json(f"{data_svc()}/db/security/{_urlquote(base, safe='')}/history", route="read",
                                  params={"days": CTX_DAYS}, upstream=CTX_UPSTREAM)
        except UpstreamError as exc:
            if exc.status_code in (404, 422):
                return EodContext(found=False)
            raise
    return eod_context_from_history(body)


async def _bounded(aw: Awaitable[Any], timeout: float) -> Any:
    task = asyncio.ensure_future(aw)
    task.add_done_callback(_retrieve)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except Exception:  # noqa: BLE001 -- TimeoutError or the fetch's error: the quote goes out without context
        return None


async def eod_contexts(bases: Iterable[str]) -> dict[str, EodContext | None]:
    """Context per stock symbol (indices get None); never raises, never waits longer than CTX_WAIT_S."""
    syms = [b for b in dict.fromkeys(bases) if is_stock_symbol(b)]

    async def one(b: str) -> EodContext | None:
        served = await _bounded(_ctx_cache.get(b, functools.partial(_fetch_ctx, b), policy=_ctx_policy), CTX_WAIT_S)
        return served.value if isinstance(served, Served) else None

    got = await asyncio.gather(*(one(b) for b in syms))
    return dict(zip(syms, got, strict=True))


# ── the news-scanner quote shape for '.NS' symbols ──────────────────────────────────────────────────────────────────

def _epoch(ltt: str | None) -> int | None:
    if not ltt:
        return None
    try:
        dt = datetime.fromisoformat(ltt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)               # the contract stamps +05:30; a bare time is exchange time
    return int(dt.timestamp())


def _date_of(ltt: str | None) -> str | None:
    t = _epoch(ltt)
    return datetime.fromtimestamp(t, IST).date().isoformat() if t is not None else None


def _hi(*vals: float | None) -> float | None:
    got = [v for v in vals if v is not None]
    return max(got) if got else None


def _lo(*vals: float | None) -> float | None:
    got = [v for v in vals if v is not None]
    return min(got) if got else None


def news_row(base: str, row: dict[str, Any], ctx: EodContext | None, market: dict[str, Any], *,
             fresh: bool = False) -> dict[str, Any]:
    """One live row in the body keys ``/api/news-scanner/quotes`` has always had (Yahoo's shape), plus ``source``,
    ``state``, ``age_s``, ``ltt`` (and ``reason``) from the live contract. ``fresh`` (a read that DECIDES: price alerts,
    the controller's move check): a ``stale`` row is not ``available``."""
    sym = f"{base}.NS"
    state = row.get("state") or "unavailable"
    price = row.get("price")
    common: dict[str, Any] = {"source": row.get("source"), "state": state, "age_s": row.get("age_s"), "ltt": row.get("ltt")}
    if row.get("reason"):
        common["reason"] = row["reason"]
    if price is None or state == "unavailable" or (fresh and state not in DECISION_STATES):
        return {"symbol": sym, "available": False, **common}
    prev = row.get("prev_close")
    change = row.get("change")
    if change is None and prev:
        change = price - prev
    change_pct = row.get("change_pct")
    if change_pct is None and change is not None and prev:
        change_pct = change / prev * 100
    row_date = row.get("date") if isinstance(row.get("date"), str) and _DATE_RE.fullmatch(row["date"]) else None
    market_date = _date_of(row.get("ltt")) or row_date or market.get("session_date")
    spark: list[float] = list(ctx.spark) if ctx and ctx.found else []
    if spark and ctx is not None and ctx.last_date and market_date and ctx.last_date < market_date:
        spark = (spark + [price])[-SPARK_N:]                        # today's forming point, as Yahoo's daily bar had
    prev_date = None
    if ctx and ctx.found:
        prev_date = next((d for d in ctx.dates if market_date is None or d < market_date), None)
    return {
        "symbol": sym, "name": row.get("name") if isinstance(row.get("name"), str) else None,
        "currency": "INR", "exchange": "NSE", "price": price, "prev_close": prev, "prev_date": prev_date,
        "market_date": market_date, "change": change, "change_pct": change_pct,
        "day_high": row.get("day_high"), "day_low": row.get("day_low"), "volume": row.get("volume"),
        "high_52w": _hi(ctx.high_52w if ctx else None, row.get("day_high")),
        "low_52w": _lo(ctx.low_52w if ctx else None, row.get("day_low")),
        "market_time": _epoch(row.get("ltt")), "gmtoffset": 19800, "timezone": "Asia/Kolkata",
        "stale": state == "stale", "available": True, "resolved_symbol": sym, "spark": spark,
        "prev_source": "NSE", "eod_as_of": ctx.last_date if ctx and ctx.found else None, **common,
    }


async def news_quotes(symbols: Iterable[str], *, fresh: bool = False) -> tuple[dict[str, dict[str, Any]], Served[None] | None]:
    """'.NS' symbols (as the news-scanner route got them) -> {sym: news row}. A symbol that is not a valid NSE symbol
    gets an unavailable row; nothing here falls back to Yahoo."""
    rows: dict[str, dict[str, Any]] = {}
    bases: dict[str, str] = {}
    for s in symbols:
        try:
            bases[s] = normalize_symbol(s)
        except ValueError:
            rows[s] = {"symbol": s, "available": False, "source": None, "state": "unavailable", "age_s": None,
                       "ltt": None, "reason": "not an NSE symbol"}
    if not bases:
        return rows, None
    uniq = list(dict.fromkeys(bases.values()))
    snap, ctxs = await asyncio.gather(hub().quotes(uniq), eod_contexts(uniq))
    market = snap.payload["market"]
    for s, b in bases.items():
        rows[s] = news_row(b, snap.payload["quotes"][b], ctxs.get(b), market, fresh=fresh)
    return rows, snap.served


# ── push: the 'quotes' channel of the monitor WebSocket ─────────────────────────────────────────────────────────────

PUSH_INTERVAL_S = 2.0
PUSH_FULL_EVERY_S = 10.0
PUSH_QUEUE_MAX = 32               # messages waiting for one slow client; the oldest is dropped beyond this
PUSH_MAX_UNION = 600
PUSH_MAX_CLIENTS = 64
_SIG_FIELDS = ("price", "change_pct", "state", "source", "volume", "bid", "ask", "day_high", "day_low", "ltt")


class PushClient:
    """One socket's subscription: its symbols, a bounded outbox (drop-oldest, counted) and what it was last sent."""

    def __init__(self, *, queue_max: int = PUSH_QUEUE_MAX) -> None:
        self.symbols: list[str] = []
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_max)
        self.dropped = 0
        self.offered = 0
        self._sig: dict[str, tuple[Any, ...]] = {}
        self._last_full = -math.inf

    def set_symbols(self, symbols: list[str]) -> None:
        self.symbols = list(symbols)
        self._sig = {s: v for s, v in self._sig.items() if s in set(symbols)}
        self._last_full = -math.inf                       # a new subscription starts with a full snapshot

    def feed(self, payload: dict[str, Any], now: float, *, full_every: float = PUSH_FULL_EVERY_S) -> None:
        full = now - self._last_full >= full_every
        rows: dict[str, Any] = {}
        for s in self.symbols:
            row = payload["quotes"].get(s)
            if row is None:
                continue
            sig = tuple(row.get(k) for k in _SIG_FIELDS)
            if full or self._sig.get(s) != sig:
                rows[s] = row
                self._sig[s] = sig
        if full:
            self._last_full = now
        if rows:
            self.offer({"type": "quotes", "channel": "quotes", "as_of": payload["as_of"], "market": payload["market"],
                        "full": full, "dropped": self.dropped, "quotes": rows})

    def offer(self, msg: dict[str, Any]) -> None:
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.dropped += 1
            self._last_full = -math.inf                   # rows were lost: the next round re-sends everything
        self.queue.put_nowait(msg)
        self.offered += 1


class QuotesPush:
    """ONE poll loop per event loop for the union of every client's symbols, through the hub (so a push round and the
    pollers share the per-symbol 2 s cache); stops when the last client leaves."""

    def __init__(self, hub_fn: Callable[[], LiveQuotesHub] = hub, *, interval_s: float = PUSH_INTERVAL_S,
                 full_every_s: float = PUSH_FULL_EVERY_S, clock: Callable[[], float] = time.monotonic) -> None:
        self._hub_fn = hub_fn
        self.interval_s, self.full_every_s, self._clock = interval_s, full_every_s, clock
        self.clients: set[PushClient] = set()
        self._task: asyncio.Task[None] | None = None
        self.rounds = 0
        self.errors = 0

    def add(self, client: PushClient) -> None:
        self.clients.add(client)
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name="live-quotes-push")
            self._task.add_done_callback(_retrieve)

    def remove(self, client: PushClient) -> None:
        self.clients.discard(client)

    def stats(self) -> dict[str, Any]:
        return {"clients": len(self.clients), "rounds": self.rounds, "errors": self.errors,
                "dropped": sum(c.dropped for c in self.clients), "interval_s": self.interval_s,
                "running": self._task is not None and not self._task.done()}

    async def _run(self) -> None:
        while self.clients:
            union = list(dict.fromkeys(s for c in list(self.clients) for s in c.symbols))[:PUSH_MAX_UNION]
            if union:
                try:
                    snap = await self._hub_fn().quotes(union)
                except Exception:  # noqa: BLE001 -- the hub never raises by design; a bug must not kill the loop
                    self.errors += 1
                else:
                    self.rounds += 1
                    now = self._clock()
                    for c in list(self.clients):
                        c.feed(snap.payload, now, full_every=self.full_every_s)
            await asyncio.sleep(self.interval_s)


_pushes: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, QuotesPush] = weakref.WeakKeyDictionary()


def quotes_push() -> QuotesPush:
    """The running loop's push loop (one in production; ASGI test clients may run one loop each)."""
    loop = asyncio.get_running_loop()
    p = _pushes.get(loop)
    if p is None:
        p = _pushes[loop] = QuotesPush()
    return p


class QuotesChannel:
    """The 'quotes' channel of ONE monitor socket. ``handle`` answers ``{"action": "subscribe"|"unsubscribe",
    "channel": "quotes", "symbols": [...]}`` (subscribe REPLACES the set, like the monitor's own subscribe; unsubscribe
    without symbols drops all); the pump task sends ``{"type": "quotes", ...}`` messages from the bounded outbox."""

    def __init__(self, send: Callable[[dict[str, Any]], Awaitable[Any]], push: QuotesPush | None = None) -> None:
        self._send = send
        self._push = push if push is not None else quotes_push()
        self.client = PushClient()
        self._pump_task: asyncio.Task[None] | None = None

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        raw = payload.get("symbols")
        if action == "subscribe":
            if not isinstance(raw, list):
                return {"error": "bad_message", "channel": "quotes", "detail": "symbols must be a list"}
            if not raw:
                return await self._drop_all()
            try:
                syms = normalize_symbols(raw)
            except ValueError as exc:
                return {"error": "bad_message", "channel": "quotes", "detail": str(exc)}
            if self.client not in self._push.clients and len(self._push.clients) >= PUSH_MAX_CLIENTS:
                return {"error": "busy", "channel": "quotes", "detail": f"at most {PUSH_MAX_CLIENTS} push clients"}
            self.client.set_symbols(syms)
            self._push.add(self.client)
            if self._pump_task is None or self._pump_task.done():
                self._pump_task = asyncio.get_running_loop().create_task(self._pump(), name="live-quotes-pump")
            return {"ok": True, "channel": "quotes", "subscribed": syms, "interval_s": self._push.interval_s}
        if action == "unsubscribe":
            if raw is None:
                return await self._drop_all()
            if not isinstance(raw, list):
                return {"error": "bad_message", "channel": "quotes", "detail": "symbols must be a list"}
            gone = set()
            for x in raw:
                with contextlib.suppress(ValueError):
                    gone.add(normalize_symbol(x))
            self.client.set_symbols([s for s in self.client.symbols if s not in gone])
            if not self.client.symbols:
                self._push.remove(self.client)
            return {"ok": True, "channel": "quotes", "subscribed": self.client.symbols}
        return {"error": "unknown_action", "channel": "quotes"}

    async def _drop_all(self) -> dict[str, Any]:
        self.client.set_symbols([])
        self._push.remove(self.client)
        return {"ok": True, "channel": "quotes", "subscribed": []}

    async def close(self) -> None:
        self._push.remove(self.client)
        task, self._pump_task = self._pump_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task

    async def _pump(self) -> None:
        while True:
            msg = await self.client.queue.get()
            try:
                await self._send(msg)
            except Exception:  # noqa: BLE001 -- the client is gone; the socket's receive loop cleans up
                return


# ── routes ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/quotes")
async def live_quotes(symbols: str = Query(..., min_length=1, max_length=12000),
                      response: Response = None) -> dict[str, Any]:  # type: ignore[assignment]  # injected by FastAPI
    """Live quotes for up to 300 NSE symbols (stocks, or indices by NSE name) -- see the module docstring. Every row
    carries its ``source`` (breeze_ws / nse_api / eod), ``age_s`` and ``state`` (live / delayed / stale / closed /
    unavailable). The oldest cache age is in ``X-Cache-Age``."""
    try:
        syms = normalize_symbols(symbols)
    except ValueError as exc:
        fail(422, "invalid", str(exc), "NSE symbols such as RELIANCE or 'NIFTY 50', comma-separated, at most 300")
    snap = await hub().quotes(syms)
    cache_headers(response, snap.served)
    return snap.payload


@router.get("/status")
async def live_status() -> dict[str, Any]:
    """The live feed's state (data-service ``/live/status``) and this process's hub and push counters."""
    try:
        body, age, stale = await status_cache().get()
    except UpstreamError as exc:
        fail(503, "upstream_down", f"live status unavailable: {exc.detail}"[:300],
             "data-service is down or has no /live/status; quotes still answer with per-row states")
    out = status_view(body, age, stale)
    pushes = [p.stats() for p in list(_pushes.values())]
    out["ui_api"] = {**hub().stats(), "status_calls": status_cache().calls,
                     "push": pushes[0] if len(pushes) == 1 else {"loops": pushes}}
    return out


def reset_for_tests() -> None:
    """Forget every cached row, status, context and push loop (module-level state; tests only)."""
    hub().reset()
    status_cache().reset()
    _ctx_cache.invalidate()
    _pushes.clear()
