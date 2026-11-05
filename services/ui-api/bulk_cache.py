"""bulk_cache.py — one shared, TTL-cached copy of data-service's bulk OHLCV frame (W7, D3).

Both heavy scan routes (alpha `/universe` + `/scan`, lw `/screener` + the cycle scan) used to
pull the ~70–84 MB `GET /db/ohlcv-bulk` payload and re-parse ~0.4M JSON rows PER CALL
(1.4 s / 2.9 s warm, perfectly serialized under concurrency — bloomberg_verdict.md D3).
This module owns that fetch instead:

- one module-level ``TTLCache`` (cache.py → visible at ``/api/telemetry/caches`` as
  ``bulk_ohlcv``), keyed by ``(days, equity_only)``, TTL 60 s, max 2 entries — the two keys
  live traffic uses: alpha's ``(400, all)`` and lw's ``(530, eq)``. Measured (build_w7.md):
  the PARSED frames are light — 28 MB + 34 MB deep for the two defaults (the 70–84 MB is
  JSON wire overhead) — so two cached frames cost ~62 MB steady; a third ad-hoc ``days``
  key LRU-evicts. The transient JSON-parse spike now happens once per key per 60 s instead
  of on every request, so peak memory pressure strictly drops versus the per-call pulls.
- single-flight per key: concurrent callers for the same key queue on a per-key lock while
  one of them fetches; the rest are then served from the cache (no duplicate 70 MB pulls —
  the critic's 8×-concurrent probe serialized at ~0.73 s/request before).
- thread-safe for BOTH caller styles: lw's sync ``def`` routes run in FastAPI's threadpool
  and call :func:`get_bulk_ohlcv` directly; alpha's async routes call it via
  ``asyncio.to_thread`` — never on the event loop (tests/test_event_loop_purity.py and
  scripts/check_event_loop.py stay green).

READ-ONLY DISCIPLINE: the cached frame is shared across requests. :func:`get_bulk_ohlcv`
returns a SHALLOW copy (independent index/column structure, shared data blocks): adding
columns, ``set_index``, ``sort_values`` on the returned frame are all safe; writing INTO
values (``df.loc[...] = …``, ``inplace=True`` mutation) is NOT — boolean-mask-select (which
copies) or ``.copy()`` first, as both current callers already do.

Transport errors (``httpx.*``) propagate unchanged so each caller keeps its own error
contract. Empty frames are returned but NOT cached (a transient upstream hiccup must not
poison 60 s of scans).
"""
from __future__ import annotations

import os
import threading

import httpx
import pandas as pd

from cache import TTLCache

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
TTL_SECONDS = 60.0
MAX_KEYS = 2
_TIMEOUT = httpx.Timeout(120.0)

_CACHE = TTLCache("bulk_ohlcv", max_items=MAX_KEYS, default_ttl=TTL_SECONDS)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        if len(_LOCKS) > 32:                   # C2 E1: per-key locks leaked; distinct keys are
            _LOCKS.clear()                     # few in practice — clearing is safe (worst case
                                               # one duplicate upstream fetch on a cleared key)
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _parse(payload: dict) -> pd.DataFrame:
    """Bulk payload → canonical tidy frame: datetime dates, numeric prices, (ticker, date)-sorted.

    Exactly alpha.py's old ``_payload_to_frame`` (the superset format). lw's old parse was a
    column subset of this and is order-insensitive: it mask-filters (which copies) and then
    re-sorts / re-indexes itself, so one canonical layout serves both callers.
    """
    df = pd.DataFrame(payload.get("data", []))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close", "volume", "adjusted_close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values(["ticker", "date"], kind="mergesort").reset_index(drop=True)


def _fetch(days: int, equity_only: bool) -> pd.DataFrame:
    """One real pull from data-service. Raises httpx errors unchanged (callers map them)."""
    params: dict = {"days": days}
    if equity_only:
        params["equity_only"] = True          # match lw's old request exactly; alpha sent days only
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(f"{DATA_SVC}/db/ohlcv-bulk", params=params)
    r.raise_for_status()
    return _parse(r.json())


def get_bulk_ohlcv(days: int, equity_only: bool = False) -> pd.DataFrame:
    """The bulk OHLCV frame for ``(days, equity_only)``, at most :data:`TTL_SECONDS` old.

    Sync and blocking by design: call it directly from threadpool (``def``) routes, and via
    ``asyncio.to_thread`` from async ones. Returns a shallow copy — see the module docstring
    for the read-only discipline on values.
    """
    key = f"{int(days)}|{'eq' if equity_only else 'all'}"
    df = _CACHE.get(key)
    if df is None:
        with _lock_for(key):
            df = _CACHE.get(key)              # single-flight: the lock winner fetched for everyone
            if df is None:
                df = _fetch(int(days), bool(equity_only))
                if not df.empty:
                    _CACHE.set(key, df)
    return df.copy(deep=False)                # callers may add columns / reindex, never touch the cache
