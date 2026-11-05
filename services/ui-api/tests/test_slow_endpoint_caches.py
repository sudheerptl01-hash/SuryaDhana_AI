"""C-PERF-01: the slow uncached endpoints are served from single-flight stale-while-revalidate caches.

Each test checks that the cached response is byte-identical to the uncached one (UI_API_SWR=0 is the
negative control: every call reaches the upstream), that concurrent callers share one upstream read, that the
staleness bound (MAX_AGE) holds, and that the age travels in the X-Cache / X-Cache-Age headers, never in the
body. Upstreams are faked; nothing here reaches data-service, Yahoo or ICICI."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import gold_preopen as gp
from routers import markets
from routers import news_scanner as ns

BASE = "http://127.0.0.1:8010"


class Clock:
    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t


class FakeDataService:
    """Stands in for httpx.AsyncClient against data-service: counts GETs per path; answers from `routes`."""

    def __init__(self, routes: dict[str, Callable[[dict], httpx.Response]]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.lock = threading.Lock()
        outer = self

        class _Client:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *a: object) -> bool:
                return False

            async def get(self, url: str, params: dict | None = None) -> httpx.Response:
                path = urlsplit(url).path
                with outer.lock:
                    outer.calls.append(path)
                    n = outer.calls.count(path)
                return outer.routes[path]({**(params or {}), "_n": n})

        self.client_class = _Client

    def count(self, path: str) -> int:
        with self.lock:
            return self.calls.count(path)


def _json(body: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("GET", "http://data-service"))


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(markets.router, prefix="/api/market")
    app.include_router(ns.router, prefix="/api/news-scanner")
    app.include_router(gp.router, prefix="/api/commodity")
    return app


@pytest.fixture
def data_service(monkeypatch: pytest.MonkeyPatch):
    def install(routes: dict[str, Callable[[dict], httpx.Response]]) -> FakeDataService:
        fake = FakeDataService(routes)
        monkeypatch.setattr(markets.httpx, "AsyncClient", fake.client_class)
        return fake
    return install


def _wait(cond: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.01)


def _recent(params: dict) -> httpx.Response:
    days = int(params["days"])
    return _json({"days": days, "rows": [{"symbol": "TCS", "released_at": "2026-10-09 16:00", "read": params["_n"]}],
                  "count": 1})


# ── results-recent ────────────────────────────────────────────────────────────────────────────────

def test_results_recent_is_served_from_cache_with_an_identical_body(data_service, monkeypatch) -> None:
    ds = data_service({"/db/results-recent": _recent})
    with TestClient(_app(), base_url=BASE) as c:
        a = c.get("/api/market/results-recent", params={"days": 95})
        b = c.get("/api/market/results-recent", params={"days": 95})
    assert ds.count("/db/results-recent") == 1
    assert a.status_code == b.status_code == 200 and a.content == b.content
    assert (a.headers["x-cache"], a.headers["x-cache-age"]) == ("miss", "0")
    assert b.headers["x-cache"] == "hit" and int(b.headers["x-cache-age"]) < 5
    assert "x-cache" not in a.text and "age" not in json.loads(a.text)       # the age is never in the body

    monkeypatch.setenv("UI_API_SWR", "0")                    # negative control: the uncached path
    with TestClient(_app(), base_url=BASE) as c:
        u1 = c.get("/api/market/results-recent", params={"days": 95})
        u2 = c.get("/api/market/results-recent", params={"days": 95})
    assert ds.count("/db/results-recent") == 3
    assert json.loads(u1.content)["rows"][0]["read"] == 2 and json.loads(u2.content)["rows"][0]["read"] == 3
    assert {k: v for k, v in json.loads(u1.content).items() if k != "rows"} == \
           {k: v for k, v in json.loads(a.content).items() if k != "rows"}
    assert u1.headers["x-cache"] == "bypass"


def test_results_recent_is_refreshed_in_the_background_and_never_older_than_max_age(data_service, monkeypatch) -> None:
    ds = data_service({"/db/results-recent": _recent})
    clock = Clock()
    monkeypatch.setattr(markets._RESULTS_RECENT, "_clock", clock)
    with TestClient(_app(), base_url=BASE) as c:
        first = c.get("/api/market/results-recent?days=10").json()
        clock.t += markets.MARKET_REFRESH_AFTER_S + 1             # stale: served at once, refreshed behind
        stale = c.get("/api/market/results-recent?days=10")
        assert stale.json() == first and stale.headers["x-cache"] == "stale"
        assert int(stale.headers["x-cache-age"]) == int(markets.MARKET_REFRESH_AFTER_S + 1)
        _wait(lambda: ds.count("/db/results-recent") == 2)
        time.sleep(0.05)
        refreshed = c.get("/api/market/results-recent?days=10")
        assert refreshed.json()["rows"][0]["read"] == 2 and refreshed.headers["x-cache"] == "hit"
        clock.t += markets.MARKET_MAX_AGE_S                       # past the bound: the caller waits
        late = c.get("/api/market/results-recent?days=10")
        assert late.headers["x-cache"] == "miss" and late.json()["rows"][0]["read"] == 3
    assert markets.MARKET_MAX_AGE_S <= 300                        # inside the data's cadence (see markets.py)


def test_results_recent_never_crosses_midnight(data_service, monkeypatch) -> None:
    ds = data_service({"/db/results-recent": _recent})

    class Day1(date):
        @classmethod
        def today(cls) -> date:
            return date(2026, 10, 26)

    class Day2(date):
        @classmethod
        def today(cls) -> date:
            return date(2026, 10, 27)
    with TestClient(_app(), base_url=BASE) as c:
        monkeypatch.setattr(markets, "date", Day1)
        c.get("/api/market/results-recent?days=5")
        c.get("/api/market/results-recent?days=5")
        monkeypatch.setattr(markets, "date", Day2)
        c.get("/api/market/results-recent?days=5")
    assert ds.count("/db/results-recent") == 2                    # the new day's window is read, not served old


def test_upstream_errors_are_passed_through_and_not_cached(data_service) -> None:
    def flaky(params: dict) -> httpx.Response:
        return _json({"detail": "DuckDB busy"}, 503) if params["_n"] == 1 else _recent(params)
    ds = data_service({"/db/results-recent": flaky})
    with TestClient(_app(), base_url=BASE) as c:
        assert c.get("/api/market/results-recent?days=10").status_code == 503
        assert c.get("/api/market/results-recent?days=10").status_code == 200
    assert ds.count("/db/results-recent") == 2


# ── results-implied-moves / fundamentals-screen ─────────────────────────────────────────────────────

def test_implied_moves_are_cached_and_their_validation_is_unchanged(data_service) -> None:
    ds = data_service({"/db/results-implied-moves": lambda p: _json({"rows": [{"symbol": "INFY", "ratio": 1.2}],
                                                                       "fo_date": "2026-10-23", "days": int(p["days"])})})
    with TestClient(_app(), base_url=BASE) as c:
        assert c.get("/api/market/results-implied-moves?days=31").status_code == 422
        a = c.get("/api/market/results-implied-moves?days=10")
        b = c.get("/api/market/results-implied-moves?days=10")
        c.get("/api/market/results-implied-moves?days=7")
    assert a.content == b.content and b.headers["x-cache"] == "hit"
    assert ds.count("/db/results-implied-moves") == 2               # one per days value


def test_fundamentals_screen_is_cached_per_variant_with_the_same_bodies(data_service, monkeypatch) -> None:
    row = {"symbol": "20MICRONS", "industry": None, "pe": 10.3456, "revenue": 2447203000.0}
    data_service({"/db/financials-universe": lambda p: _json({"rows": [dict(row)]})})
    with TestClient(_app(), base_url=BASE) as c:
        full = [c.get("/api/market/fundamentals-screen").content for _ in range(2)]
        core = [c.get("/api/market/fundamentals-screen?fields=core").content for _ in range(2)]
    monkeypatch.setenv("UI_API_SWR", "0")
    with TestClient(_app(), base_url=BASE) as c:
        full_u = c.get("/api/market/fundamentals-screen").content
        core_u = c.get("/api/market/fundamentals-screen?fields=core").content
    assert full[0] == full[1] == full_u and core[0] == core[1] == core_u
    assert json.loads(full_u)["rows"][0]["pe"] == 10.35 and "columns" in json.loads(core_u)


# ── results-reacting (was a 60 s dict cache without single flight) ───────────────────────────────────

def test_results_reacting_keeps_its_60_s_bound_and_is_single_flight(monkeypatch) -> None:
    calls = {"n": 0}

    async def slow() -> dict:
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return {"rows": [], "n": calls["n"]}
    monkeypatch.setattr(markets, "_results_reacting", slow)
    clock = Clock()
    monkeypatch.setattr(markets._REACTING, "_clock", clock)

    async def run() -> list[dict]:
        out = list(await asyncio.gather(*(markets.results_reacting() for _ in range(5))))
        clock.t += 61.0
        out.append(await markets.results_reacting())
        return out
    out = asyncio.run(run())
    assert calls["n"] == 2 and [o["n"] for o in out] == [1, 1, 1, 1, 1, 2]
    assert markets._REACTING.max_age == 60.0


# ── news-scanner quotes: per symbol, single flight, the 60 s bound unchanged ────────────────────────

def _chart(sym: str, price: float) -> dict:
    t0 = int(time.time()) - 3 * 86400
    ts = [t0 + i * 86400 for i in range(3)]
    return {"meta": {"symbol": sym, "regularMarketPrice": price, "regularMarketTime": ts[-1], "gmtoffset": 0,
                     "currency": "USD"},
            "timestamp": ts,
            "indicators": {"quote": [{"open": [1.0, 2.0, 3.0], "high": [1.0, 2.0, 3.0], "low": [1.0, 2.0, 3.0],
                                      "close": [1.0, 2.0, 3.0], "volume": [1, 2, 3]}]}}


@pytest.fixture
def yahoo(monkeypatch: pytest.MonkeyPatch):
    state: dict[str, Any] = {"calls": {}, "available": True, "delay": 0.0}

    async def resolve(sym: str, rng: str, interval: str):
        state["calls"][sym] = state["calls"].get(sym, 0) + 1
        if state["delay"]:
            await asyncio.sleep(state["delay"])
        if not state["available"]:
            return sym, None
        return sym, _chart(sym, 100.0 + state["calls"][sym])

    async def passthrough(pairs):
        return pairs
    monkeypatch.setattr(ns, "_resolve_chart", resolve)
    monkeypatch.setattr(ns, "_official_prev_close", passthrough)
    clock = Clock()
    monkeypatch.setattr(ns._quotes, "_clock", clock)
    state["clock"] = clock
    return state


def test_concurrent_quote_requests_share_one_yahoo_fetch_per_symbol(yahoo) -> None:
    yahoo["delay"] = 0.05

    async def run() -> list[dict]:
        return list(await asyncio.gather(ns.get_quotes(symbols="^GSPC,INR=X"), ns.get_quotes(symbols="^GSPC"),
                                         ns.get_quotes(symbols="INR=X,^GSPC")))
    a, b, c = asyncio.run(run())
    assert yahoo["calls"] == {"^GSPC": 1, "INR=X": 1}
    assert a["quotes"]["^GSPC"] == b["quotes"]["^GSPC"] == c["quotes"]["^GSPC"]


def test_quotes_keep_the_old_60_s_bound_and_refresh_after_30_s(yahoo) -> None:
    clock = yahoo["clock"]

    async def run() -> list[float]:
        prices = [(await ns.get_quotes(symbols="^GSPC"))["quotes"]["^GSPC"]["price"]]
        clock.t += 31.0                                       # still inside the old 60 s TTL: served at once ...
        prices.append((await ns.get_quotes(symbols="^GSPC"))["quotes"]["^GSPC"]["price"])
        for _ in range(5):
            await asyncio.sleep(0)                            # ... and refreshed in the background
        prices.append((await ns.get_quotes(symbols="^GSPC"))["quotes"]["^GSPC"]["price"])
        clock.t += 60.0                                       # 60 s after the refresh: never served, re-fetched
        prices.append((await ns.get_quotes(symbols="^GSPC"))["quotes"]["^GSPC"]["price"])
        return prices
    assert asyncio.run(run()) == [101.0, 101.0, 102.0, 103.0]
    assert ns.QUOTE_MAX_AGE_S == 60.0 and yahoo["calls"]["^GSPC"] == 3


def test_unavailable_quotes_are_kept_120_s_without_an_early_refresh(yahoo) -> None:
    yahoo["available"] = False
    clock = yahoo["clock"]

    async def run() -> None:
        await ns.get_quotes(symbols="NOPE.L")
        clock.t += 61.0
        q = (await ns.get_quotes(symbols="NOPE.L"))["quotes"]["NOPE.L"]
        assert q == {"symbol": "NOPE.L", "available": False}
        for _ in range(5):
            await asyncio.sleep(0)
        assert yahoo["calls"]["NOPE.L"] == 1
        clock.t += 60.0
        await ns.get_quotes(symbols="NOPE.L")
    asyncio.run(run())
    assert yahoo["calls"]["NOPE.L"] == 2


def test_quotes_over_http_carry_the_oldest_age_in_a_header(yahoo) -> None:
    with TestClient(_app(), base_url=BASE) as c:
        a = c.get("/api/news-scanner/quotes", params={"symbols": "^GSPC,INR=X"})
        yahoo["clock"].t += 12.0
        b = c.get("/api/news-scanner/quotes", params={"symbols": "^GSPC,INR=X"})
    assert set(a.json()) == {"quotes", "as_of"} and a.json()["quotes"] == b.json()["quotes"]
    assert a.headers["x-cache"] == "miss" and (b.headers["x-cache"], b.headers["x-cache-age"]) == ("hit", "12")


# ── MCX master (/api/mcx/specs, the gold desk): re-read in the background inside the old 10-min bound ─

@pytest.fixture
def master(monkeypatch: pytest.MonkeyPatch):
    state = {"loads": 0, "delay": 0.0}

    def load() -> tuple[str, date]:
        state["loads"] += 1
        if state["delay"]:
            time.sleep(state["delay"])
        return f"master #{state['loads']}", date(2026, 10, 26)
    gp._cache.clear()
    monkeypatch.setattr(gp, "_load_mcx_master", load)
    yield state
    gp._cache.clear()


def _age_master(seconds: float) -> None:
    stored_at, value = gp._cache.get(gp.MASTER_KEY)
    gp._cache.set(gp.MASTER_KEY, (stored_at - seconds, value))


def test_master_is_reread_in_the_background_inside_its_bound(master) -> None:
    assert gp.mcx_master()[0] == "master #1"
    assert gp.mcx_master()[0] == "master #1" and master["loads"] == 1        # fresh: no load
    _age_master(gp.MASTER_REFRESH_AFTER_S + 1)
    assert gp.mcx_master()[0] == "master #1"                                  # served at once ...
    _wait(lambda: gp._cache.get(gp.MASTER_KEY)[1][0] == "master #2")          # ... and re-read behind
    _age_master(gp.MASTER_MAX_AGE_S + 1)
    assert gp.mcx_master()[0] == "master #3"                                  # past 600 s: the caller loads
    assert gp.MASTER_MAX_AGE_S == 600.0


def test_concurrent_master_loads_share_one_download(master) -> None:
    master["delay"] = 0.2
    got: list[str] = []
    threads = [threading.Thread(target=lambda: got.append(gp.mcx_master()[0])) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert master["loads"] == 1 and got == ["master #1"] * 5
