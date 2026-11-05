"""bulk_cache.py (W7, verdict D3): one 60 s TTL + single-flight frame for the bulk-OHLCV pullers.

Covers: one upstream fetch per (days, equity_only) key inside the TTL, single-flight under
concurrency, copy-on-return isolation, empty-not-cached, error propagation, the LRU cap, and
the alpha / lw wiring contracts (status mapping, column subset, fetch-days headroom).
"""
import sys
import threading
import time
from pathlib import Path

import httpx
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bulk_cache  # noqa: E402
from cache import REGISTRY  # noqa: E402


def _frame(n=6, ticker="TCS"):
    return pd.DataFrame({
        "ticker": [ticker] * n,
        "date": pd.date_range("2026-01-01", periods=n),
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
        "close": [100.5] * n, "volume": [1000] * n,
    })


@pytest.fixture(autouse=True)
def _fresh_cache():
    bulk_cache._CACHE.clear()
    yield
    bulk_cache._CACHE.clear()


def test_registered_for_telemetry():
    assert "bulk_ohlcv" in REGISTRY  # /api/telemetry/caches shows hits/misses/evictions


def test_one_fetch_per_key_within_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr(bulk_cache, "_fetch", lambda d, e: calls.append((d, e)) or _frame())
    for _ in range(5):
        df = bulk_cache.get_bulk_ohlcv(400, False)
        assert len(df) == 6
    assert calls == [(400, False)]
    bulk_cache.get_bulk_ohlcv(530, True)  # a different key fetches separately
    assert calls == [(400, False), (530, True)]


def test_ttl_expiry_refetches(monkeypatch):
    calls = []
    monkeypatch.setattr(bulk_cache, "_fetch", lambda d, e: calls.append(1) or _frame())
    bulk_cache.get_bulk_ohlcv(400)
    # expire the entry without waiting: re-set it with ttl=0 (TTLCache checks expiry on read)
    bulk_cache._CACHE.set("400|all", _frame(), ttl=0)
    bulk_cache.get_bulk_ohlcv(400)
    assert len(calls) == 2


def test_single_flight_under_concurrency(monkeypatch):
    calls = []

    def slow_fetch(d, e):
        calls.append(1)
        time.sleep(0.15)
        return _frame()

    monkeypatch.setattr(bulk_cache, "_fetch", slow_fetch)
    out, threads = [], [threading.Thread(target=lambda: out.append(bulk_cache.get_bulk_ohlcv(400)))
                        for _ in range(8)]
    t0 = time.perf_counter()
    [t.start() for t in threads]
    [t.join() for t in threads]
    took = time.perf_counter() - t0
    assert len(calls) == 1, "8 concurrent callers must share ONE upstream fetch"
    assert len(out) == 8 and all(len(df) == 6 for df in out)
    assert took < 1.0, f"waiters must be served from the winner's fetch, not serialized: {took:.2f}s"


def test_copy_on_return_isolates_callers(monkeypatch):
    monkeypatch.setattr(bulk_cache, "_fetch", lambda d, e: _frame())
    a = bulk_cache.get_bulk_ohlcv(400)
    a["stock_id"] = 7                       # lw's cycle scan adds a column
    a2 = a.set_index(["date", "ticker"])    # the screener re-indexes
    assert a2.index.nlevels == 2
    b = bulk_cache.get_bulk_ohlcv(400)
    assert "stock_id" not in b.columns, "a caller's added column must never reach the cache"
    assert b is not a


def test_empty_frame_is_returned_but_not_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(bulk_cache, "_fetch", lambda d, e: calls.append(1) or pd.DataFrame())
    assert bulk_cache.get_bulk_ohlcv(400).empty
    assert bulk_cache.get_bulk_ohlcv(400).empty
    assert len(calls) == 2, "a transient empty upstream must not poison 60 s of scans"


def test_errors_propagate_and_are_not_cached(monkeypatch):
    calls = []

    def boom(d, e):
        calls.append(1)
        raise httpx.HTTPStatusError("500", request=httpx.Request("GET", "http://x"),
                                    response=httpx.Response(500, text="kaput"))

    monkeypatch.setattr(bulk_cache, "_fetch", boom)
    with pytest.raises(httpx.HTTPStatusError):
        bulk_cache.get_bulk_ohlcv(400)
    with pytest.raises(httpx.HTTPStatusError):
        bulk_cache.get_bulk_ohlcv(400)
    assert len(calls) == 2


def test_lru_caps_at_two_keys(monkeypatch):
    calls = []
    monkeypatch.setattr(bulk_cache, "_fetch", lambda d, e: calls.append(d) or _frame())
    bulk_cache.get_bulk_ohlcv(400)          # key 1
    bulk_cache.get_bulk_ohlcv(530, True)    # key 2
    bulk_cache.get_bulk_ohlcv(430, True)    # key 3 → evicts LRU (400|all)
    assert len(bulk_cache._CACHE) == bulk_cache.MAX_KEYS == 2
    bulk_cache.get_bulk_ohlcv(400)          # refetches after eviction
    assert calls == [400, 530, 430, 400]


# ── wiring: alpha ────────────────────────────────────────────────────────────────────────

def test_alpha_loader_maps_errors_and_uses_the_cache(monkeypatch):
    import asyncio

    from fastapi import HTTPException
    from routers import alpha

    seen = []

    def fake_get(days, equity_only=False):
        seen.append((days, equity_only))
        return _frame()

    monkeypatch.setattr(bulk_cache, "get_bulk_ohlcv", fake_get)
    df = asyncio.run(alpha._load_bulk_ohlcv(400))
    assert seen == [(400, False)] and len(df) == 6  # alpha pulls the FULL universe (no equity_only)

    monkeypatch.setattr(bulk_cache, "get_bulk_ohlcv", lambda d, e=False: pd.DataFrame())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(alpha._load_bulk_ohlcv(400))
    assert exc.value.status_code == 503  # empty → same contract as before

    def raise_status(d, e=False):
        raise httpx.HTTPStatusError("422", request=httpx.Request("GET", "http://x"),
                                    response=httpx.Response(422, text="bad days"))

    monkeypatch.setattr(bulk_cache, "get_bulk_ohlcv", raise_status)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(alpha._load_bulk_ohlcv(400))
    assert exc.value.status_code == 422 and exc.value.detail == "bad days"  # upstream status passthrough

    def raise_conn(d, e=False):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(bulk_cache, "get_bulk_ohlcv", raise_conn)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(alpha._load_bulk_ohlcv(400))
    assert exc.value.status_code == 502


# ── wiring: lw scanner ───────────────────────────────────────────────────────────────────

def test_lw_fetch_keeps_headroom_equity_flag_and_columns(monkeypatch):
    from routers import lw_scanner

    seen = []

    def fake_get(days, equity_only=False):
        seen.append((days, equity_only))
        df = _frame()
        df["adjusted_close"] = df["close"]  # canonical frame carries the extra column
        return df

    monkeypatch.setattr(bulk_cache, "get_bulk_ohlcv", fake_get)
    df = lw_scanner._fetch_ohlcv_bulk(500)
    assert seen == [(530, True)]            # +30 headroom, operating companies only — as before
    assert list(df.columns) == ["ticker", "date", "open", "high", "low", "close", "volume"]

    monkeypatch.setattr(bulk_cache, "get_bulk_ohlcv", lambda days, equity_only=False: pd.DataFrame())
    empty = lw_scanner._fetch_ohlcv_bulk(10)
    assert empty.empty and list(empty.columns) == ["ticker", "date", "open", "high", "low", "close", "volume"]
