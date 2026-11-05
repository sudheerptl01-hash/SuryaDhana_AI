"""The price-alert check prices with FRESH quotes (round 3 review of C-PERF-01, major).

The news-scanner quote cache is stale-while-revalidate (refresh after 30 s, never older than 60 s). At the
scheduler's 60 s cadence a display-style read gets the quote the previous minute fetched (about 58 s old) every
time. POST /api/alerts/run decides on prices, so it asks get_quotes(fresh=True): a quote at or past 30 s is a
miss it waits for. Fake clock; each Yahoo fetch takes FETCH_S of fake time and returns the time it finished as
the price, so the age of the quote a decision used is (decision time - price)."""
from __future__ import annotations

import asyncio
import math
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import alerts
from routers import news_scanner as ns

FETCH_S = 1.5
CADENCE_S = 60.0                     # master_controller.price_alerts_check: CronTrigger(minute='*')
MINUTES = 12
SYMS = ("TCS.NS", "INFY.NS", "^NSEI")


class Clock:
    def __init__(self) -> None:
        self.t = 10_000.0

    def __call__(self) -> float:
        return self.t

    def at_least(self, t: float) -> None:
        self.t = max(self.t, t)                               # a fetch may already have moved time past t


def _chart(sym: str, price: float) -> dict[str, Any]:
    t0 = int(time.time()) - 3 * 86400
    ts = [t0 + i * 86400 for i in range(3)]
    return {"meta": {"symbol": sym, "regularMarketPrice": price, "regularMarketTime": ts[-1], "gmtoffset": 0},
            "timestamp": ts,
            "indicators": {"quote": [{"open": [1.0] * 3, "high": [1.0] * 3, "low": [1.0] * 3, "close": [1.0] * 3,
                                      "volume": [1] * 3}]}}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    clock = Clock()
    fetches: dict[str, int] = {}

    async def resolve(sym: str, rng: str, interval: str) -> tuple[str, dict[str, Any]]:
        fetches[sym] = fetches.get(sym, 0) + 1
        await asyncio.sleep(0)
        clock.t += FETCH_S                                    # Yahoo takes FETCH_S; the data are as of the answer
        return sym, _chart(sym, clock.t)

    async def passthrough(pairs: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
        return pairs
    monkeypatch.setattr(ns, "_resolve_chart", resolve)
    monkeypatch.setattr(ns, "_official_prev_close", passthrough)
    monkeypatch.setattr(ns._quotes, "_clock", clock)
    monkeypatch.setenv("ALERTS_PATH", str(tmp_path / "price_alerts.json"))
    # levels nobody reaches: the check prices every symbol every minute and never removes an alert
    alerts._write({"alerts": {s.removesuffix(".NS"): {"above": 1e12, "yahoo": s} for s in SYMS}, "history": []})

    decisions: list[float] = []
    real_check = alerts.check_levels

    def spy(levels: dict, prices: dict, now: Any = None, changes: Any = None) -> Any:
        decisions.extend(clock.t - p for p in prices.values() if p is not None)
        return real_check(levels, prices, now, changes)
    monkeypatch.setattr(alerts, "check_levels", spy)
    return {"clock": clock, "decisions": decisions, "fetches": fetches}


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def _minute_loop(world: dict[str, Any], display_offsets: tuple[float, ...]) -> list[float]:
    """MINUTES scheduler runs at a 60 s cadence; display pollers (WTCH / WEI: 60 s) at the given offsets."""
    clock = world["clock"]
    start = clock.t
    for k in range(MINUTES):
        clock.at_least(start + k * CADENCE_S)
        world["decisions"].append(float("nan"))               # minute separator
        await alerts.run_alerts()
        for off in display_offsets:
            clock.at_least(start + k * CADENCE_S + off)
            await ns.get_quotes(symbols=",".join(SYMS))
            await _settle()                                   # the background refresh, if one started
    return world["decisions"]


def _ages(decisions: list[float]) -> list[float]:
    return [round(a, 1) for a in decisions if not math.isnan(a)]


@pytest.mark.parametrize("display_offsets", [(), (20.0,), (45.0,), (5.0, 29.0, 59.0)])
def test_every_60_s_alert_check_prices_with_a_quote_under_30_s_old(world: dict[str, Any],
                                                                     display_offsets: tuple[float, ...]) -> None:
    ages = _ages(asyncio.run(_minute_loop(world, display_offsets)))
    assert len(ages) == MINUTES * len(SYMS)
    assert max(ages) < ns.QUOTE_REFRESH_AFTER_S == 30.0, ages


def test_negative_control_the_display_path_would_price_alerts_with_the_previous_minute(
        world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The same loop with the fresh flag dropped (the round-3 code): from the 2nd minute on, every check used the
    quote fetched a minute earlier (about 58.5 s old). Guards that the test above can see the defect."""
    real = ns.get_quotes

    async def display_only(symbols: str, response: Any = None, fresh: bool = False) -> dict[str, Any]:
        return await real(symbols=symbols, response=response)
    monkeypatch.setattr(ns, "get_quotes", display_only)
    ages = _ages(asyncio.run(_minute_loop(world, (20.0,))))
    first, steady = ages[:len(SYMS)], ages[len(SYMS):]
    assert max(first) < ns.QUOTE_REFRESH_AFTER_S                       # the very first check was a miss ...
    assert min(steady) >= CADENCE_S - 2 * FETCH_S, steady                # ... every later one a minute old


def test_the_fresh_path_costs_at_most_one_fetch_per_symbol_per_check(world: dict[str, Any]) -> None:
    asyncio.run(_minute_loop(world, (20.0, 45.0)))
    # one fetch per symbol for each alert check plus at most one background refresh per minute from the pollers
    assert all(n <= 2 * MINUTES for n in world["fetches"].values()), world["fetches"]


def test_the_alert_route_asks_for_fresh_quotes(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    async def fake(symbols: str, response: Any = None, fresh: bool = False) -> dict[str, Any]:
        seen.append(fresh)
        return {"quotes": {s: {"available": True, "price": 1.0} for s in symbols.split(",")}}
    monkeypatch.setattr(ns, "get_quotes", fake)
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api/alerts")
    with TestClient(app, base_url="http://127.0.0.1:8010") as c:
        assert c.post("/api/alerts/run").status_code == 200
    assert seen == [True]


def test_fresh_over_http_waits_and_the_display_read_does_not(world: dict[str, Any]) -> None:
    """GET /api/news-scanner/quotes?fresh=1 (for the controller's move check) never answers with a quote at or past
    30 s; the plain display read keeps stale-while-revalidate. X-Cache says which."""
    clock = world["clock"]
    app = FastAPI()
    app.include_router(ns.router, prefix="/api/news-scanner")
    with TestClient(app, base_url="http://127.0.0.1:8010") as c:
        first = c.get("/api/news-scanner/quotes", params={"symbols": "TCS.NS"})
        clock.t += 31.0
        shown = c.get("/api/news-scanner/quotes", params={"symbols": "TCS.NS"})
        clock.t += 31.0
        decided = c.get("/api/news-scanner/quotes", params={"symbols": "TCS.NS", "fresh": "1"})
    p0 = first.json()["quotes"]["TCS.NS"]["price"]
    assert shown.headers["x-cache"] == "stale" and shown.json()["quotes"]["TCS.NS"]["price"] == p0
    assert decided.headers["x-cache"] == "miss" and decided.headers["x-cache-age"] == "0"
    assert clock.t - decided.json()["quotes"]["TCS.NS"]["price"] < 30.0
    assert set(decided.json()) == {"quotes", "as_of"}                       # the body shape is unchanged
