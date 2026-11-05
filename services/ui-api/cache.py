"""Bounded caches for ui-api (Bloomberg program F2.1/S1; desktop review C-PERF-01/-02).

``TTLCache`` replaces the unbounded module dicts (`news_scanner._cache` was the P1 leak: per-symbol
2-year candle frames, never evicted — scale_latency.md §3). Semantics preserved from those call-sites:
expiry checked on read AND write, LRU eviction once `max_items` is exceeded, thread-safe (sync
routes run in FastAPI's threadpool). Stdlib only.

``SWRCache`` is the async stale-while-revalidate cache with single-flight fetches for slow upstream
reads (see its docstring); ``cache_headers`` puts what it served in the response headers.

Every instance self-registers so `/api/telemetry/caches` can report hits/misses/evictions (S1
observability AC).
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

REGISTRY: dict[str, "_Reports"] = {}


class _Reports(Protocol):
    def stats(self) -> dict: ...


class TTLCache:
    def __init__(self, name: str, max_items: int, default_ttl: float, clock=time.monotonic):
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        self.name, self.max_items, self.default_ttl, self._clock = name, max_items, default_ttl, clock
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = self._misses = self._evictions = self._expired = 0
        REGISTRY[name] = self

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                self._misses += 1
                return None
            expires_at, value = hit
            if expires_at <= self._clock():
                del self._store[key]
                self._expired += 1
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._lock:
            self._store[key] = (self._clock() + (self.default_ttl if ttl is None else ttl), value)
            self._store.move_to_end(key)
            while len(self._store) > self.max_items:
                self._store.popitem(last=False)
                self._evictions += 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"name": self.name, "size": len(self._store), "max_items": self.max_items,
                    "hits": self._hits, "misses": self._misses,
                    "evictions": self._evictions, "expired": self._expired}


# ── stale-while-revalidate (desktop review C-PERF-01 / C-PERF-02) ───────────────────────────────

T = TypeVar("T")

HIT, STALE, MISS, BYPASS = "hit", "stale", "miss", "bypass"
ENV_SWR = "UI_API_SWR"            # "0" turns every SWRCache off (each call fetches, as before); read per call
CACHE_STATE_HEADER = "X-Cache"         # hit | stale | miss | bypass
CACHE_AGE_HEADER = "X-Cache-Age"       # whole seconds: age of the oldest data in the response (0 = just fetched)
_ERROR_LOG_EVERY_S = 60.0


class _JsonLineFormatter(logging.Formatter):
    """One JSON object per line (the same shape as shared/http_guard.py's lines)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
                                   "level": record.levelname.lower(), "component": "cache", "event": record.getMessage()}
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, default=str)


log = logging.getLogger("suryadhana.cache")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(_JsonLineFormatter())
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def swr_enabled() -> bool:
    """False when UI_API_SWR=0 (kill switch: every SWRCache then fetches on every call)."""
    return os.environ.get(ENV_SWR, "1").strip() != "0"


@dataclass(frozen=True)
class Served(Generic[T]):
    """What an SWRCache call returned: the value, how old it is, and how it was obtained."""

    value: T
    age_s: float
    state: str


@dataclass
class _Entry:
    value: Any
    stored_at: float
    refresh_after: float
    max_age: float


Policy = Callable[[Any], "tuple[float, float] | None"]


class SWRCache:
    """Async stale-while-revalidate cache with single-flight fetches, for slow upstream reads.

    ``await cache.get(key, fetch)`` for an entry of age ``a``:

    * ``a < refresh_after``: served as is (``hit``);
    * ``refresh_after <= a < max_age``: served as is AND one background refresh starts (``stale``); the
      caller never waits for the upstream, and the next caller gets the refreshed value;
    * no entry, or ``a >= max_age``: the caller waits for the fetch (``miss``). An entry is never served at
      or beyond ``max_age``, so ``max_age`` is the staleness bound of every response.

    ``get(..., fresh=True)`` is for a read that DECIDES on the value (the price-alert check): an entry at or
    past its ``refresh_after`` is not served; the caller waits for a refresh like a miss (joining one that
    is already running), so it only ever acts on a value younger than ``refresh_after``. Display reads keep
    the default stale-while-revalidate answer.

    Concurrent misses and refreshes of one key share ONE fetch (single flight, per event loop); a caller
    that gives up (client gone, its own deadline) does not cancel the fetch the others wait for. A fetch
    that raises stores nothing: its waiters get the exception, a failed background refresh keeps the old
    value until ``max_age`` and is logged (one line per cache per minute). ``policy(value)`` may give a
    value its own ``(refresh_after, max_age)`` or ``None`` (not cached), e.g. to keep a "not available"
    answer only briefly. ``invalidate(key)`` drops that key's entry and a fetch already running for THAT key
    then stores nothing (other keys' fetches are unaffected); ``invalidate()`` does the same for every key.
    LRU-bounded at ``max_items``. ``UI_API_SWR=0`` bypasses every instance. Entries are shared objects:
    callers must not mutate a served value."""

    def __init__(self, name: str, *, max_items: int, refresh_after: float, max_age: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        if not 0 <= refresh_after <= max_age:
            raise ValueError("need 0 <= refresh_after <= max_age")
        self.name, self.max_items = name, max_items
        self.refresh_after, self.max_age = float(refresh_after), float(max_age)
        self._clock = clock
        self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._inflight: dict[Hashable, tuple[asyncio.AbstractEventLoop, asyncio.Task[Any]]] = {}
        self._generation = 0                                    # bumped by invalidate() (all keys)
        self._key_generation: dict[Hashable, int] = {}          # bumped by invalidate(key); reset with the above
        self._lock = threading.Lock()
        self._counts = {HIT: 0, STALE: 0, MISS: 0, BYPASS: 0, "coalesced": 0, "refreshes": 0,
                        "errors": 0, "evictions": 0, "expired": 0, "fresh_waits": 0}
        self._last_error_log = -_ERROR_LOG_EVERY_S
        self._errors_unlogged = 0
        REGISTRY[name] = self

    # ── public ──────────────────────────────────────────────────────────────────────────────

    async def get(self, key: Hashable, fetch: Callable[[], Awaitable[T]], *,
                  policy: Policy | None = None, fresh: bool = False) -> Served[T]:
        """The cached value for ``key`` (see the class docstring); ``fresh=True``: never one at or past its
        ``refresh_after`` (the caller waits for the refresh instead)."""
        if not swr_enabled():
            self._count(BYPASS)
            return Served(await fetch(), 0.0, BYPASS)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and now - entry.stored_at >= entry.max_age:
                del self._entries[key]
                self._counts["expired"] += 1
                entry = None
            if entry is not None:
                self._entries.move_to_end(key)
        if entry is not None:
            age = max(0.0, now - entry.stored_at)
            if age < entry.refresh_after:
                self._count(HIT)
                return Served(entry.value, age, HIT)
            if not fresh:
                self._count(STALE)
                self._start(key, fetch, policy, background=True)
                return Served(entry.value, age, STALE)
            self._count("fresh_waits")              # a decision read: wait for the refresh, like a miss
        self._count(MISS)
        task = self._start(key, fetch, policy, background=False)
        return Served(await asyncio.shield(task), 0.0, MISS)

    def invalidate(self, key: Hashable | None = None) -> None:
        """Drop one entry (or all); a fetch already running for the dropped key(s) stores nothing."""
        with self._lock:
            if key is None:
                self._generation += 1
                self._key_generation.clear()
                self._entries.clear()
            else:
                self._key_generation[key] = self._key_generation.get(key, 0) + 1
                self._entries.pop(key, None)

    clear = invalidate

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> dict:
        with self._lock:
            return {"name": self.name, "kind": "swr", "size": len(self._entries), "max_items": self.max_items,
                    "refresh_after_s": self.refresh_after, "max_age_s": self.max_age,
                    "hits": self._counts[HIT], "stale_hits": self._counts[STALE], "misses": self._counts[MISS],
                    "bypassed": self._counts[BYPASS], "coalesced": self._counts["coalesced"],
                    "refreshes": self._counts["refreshes"], "errors": self._counts["errors"],
                    "evictions": self._counts["evictions"], "expired": self._counts["expired"],
                    "fresh_waits": self._counts["fresh_waits"],
                    "inflight": len(self._inflight)}

    # ── internals ───────────────────────────────────────────────────────────────────────────

    def _count(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counts[name] += n

    def _start(self, key: Hashable, fetch: Callable[[], Awaitable[Any]], policy: Policy | None, *,
               background: bool) -> asyncio.Task[Any]:
        loop = asyncio.get_running_loop()
        current = self._inflight.get(key)
        if current is not None and current[0] is loop and not current[1].done():
            if not background:
                self._count("coalesced")
            return current[1]
        with self._lock:
            generation = (self._generation, self._key_generation.get(key, 0))
        task = loop.create_task(self._run(key, fetch, policy, generation), name=f"swr:{self.name}")
        self._inflight[key] = (loop, task)          # the strong reference that keeps a background task alive
        task.add_done_callback(functools.partial(self._done, key, background))
        if background:
            self._count("refreshes")
        return task

    async def _run(self, key: Hashable, fetch: Callable[[], Awaitable[Any]], policy: Policy | None,
                   generation: tuple[int, int]) -> Any:
        value = await fetch()
        fresh = (self.refresh_after, self.max_age) if policy is None else policy(value)
        if fresh is not None:
            refresh_after, max_age = float(fresh[0]), float(fresh[1])
            with self._lock:
                current = (self._generation, self._key_generation.get(key, 0))
                if generation == current and max_age > 0:
                    self._entries[key] = _Entry(value, self._clock(), min(refresh_after, max_age), max_age)
                    self._entries.move_to_end(key)
                    while len(self._entries) > self.max_items:
                        self._entries.popitem(last=False)
                        self._counts["evictions"] += 1
        return value

    def _done(self, key: Hashable, background: bool, task: asyncio.Task[Any]) -> None:
        current = self._inflight.get(key)
        if current is not None and current[1] is task:
            del self._inflight[key]
        if task.cancelled():
            return
        exc = task.exception()                      # also marks it retrieved (a background task has no awaiter)
        if exc is None:
            return
        self._count("errors")
        if not background:
            return                                  # the waiting callers get the exception themselves
        now = self._clock()
        with self._lock:
            if now - self._last_error_log < _ERROR_LOG_EVERY_S:
                self._errors_unlogged += 1
                return
            self._last_error_log, suppressed, self._errors_unlogged = now, self._errors_unlogged, 0
        log.warning("swr_refresh_failed", extra={"fields": {
            "cache": self.name, "error": type(exc).__name__, "detail": str(exc)[:160],
            "suppressed_since_last": suppressed, "note": "the previous value is served until max_age_s"}})


def merge_served(items: list[Served[Any]]) -> Served[None] | None:
    """One summary for a response built from several cached pieces: the oldest age, and the state that
    matters most (stale > miss > hit > bypass)."""
    if not items:
        return None
    states = {s.state for s in items}
    state = next(s for s in (STALE, MISS, HIT, BYPASS) if s in states)
    return Served(None, max(s.age_s for s in items), state)


def cache_headers(response: Any, served: Served[Any] | None) -> None:
    """Expose what was served in the response headers (never in the body): ``X-Cache`` and ``X-Cache-Age``.
    ``response`` is FastAPI's injected Response, or None when a route function is called directly."""
    if response is None or served is None:
        return
    response.headers[CACHE_STATE_HEADER] = served.state
    response.headers[CACHE_AGE_HEADER] = str(int(served.age_s))


def cache_stats() -> list[dict]:
    """Snapshot of every registered cache, for telemetry."""
    return [c.stats() for c in REGISTRY.values()]
