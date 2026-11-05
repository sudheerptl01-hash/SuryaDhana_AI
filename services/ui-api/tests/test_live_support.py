"""Shared fakes for the LV-API tests (test_live_*.py; this file holds no tests).

``FakeDataService`` answers data-service's ``/live/quotes``, ``/live/status`` and ``/db/security/{sym}/history`` on an
``httpx.MockTransport``; ``install`` routes the process-wide client (``shared.http_client.get_async_client``) AND every
``httpx.AsyncClient`` a router builds itself (news_scanner's Yahoo / prev-close clients) through it, so any request to a
host that is not data-service -- Yahoo above all -- is recorded in ``fake.foreign`` instead of leaving the machine.
``YahooSpy`` replaces news_scanner's one Yahoo chart fetch and records every symbol it was asked for.
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import live  # noqa: E402
from routers import news_scanner as ns  # noqa: E402
from shared import http_client  # noqa: E402

DS = "http://data-service:8001"
REAL_ASYNC_CLIENT = httpx.AsyncClient
NOW = datetime(2026, 11, 5, 11, 0, 0, tzinfo=live.IST)          # Thu 5 Nov 2026 11:00 IST, market open
_HISTORY = re.compile(r"^/db/security/(.+)/history$")


class Clock:
    def __init__(self, t: float = 10_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def row(price: float | None, *, state: str = "live", source: str = "breeze_ws", age_s: float = 0.6,
        change_pct: float | None = 1.25, prev_close: float | None = None, ltt: str = "2026-11-05T10:59:59+05:30",
        **kw: Any) -> dict[str, Any]:
    """A data-service /live/quotes row as the contract writes it."""
    prev = prev_close if prev_close is not None else (round(price / (1 + (change_pct or 0) / 100), 2) if price else None)
    out = {"price": price, "change": round(price - prev, 2) if price and prev else None, "change_pct": change_pct,
           "prev_close": prev, "open": price, "day_high": (price or 0) * 1.01 or None, "day_low": (price or 0) * 0.99 or None,
           "volume": 1_234_567, "value_cr": 321.5, "bid": price, "ask": price, "ltt": ltt, "source": source,
           "age_s": age_s, "state": state}
    out.update(kw)
    return out


def history(sym: str, closes_newest_first: list[float], *, start_day: int = 4, action_k: dict[int, float] | None = None,
            high: float | None = None, low: float | None = None) -> dict[str, Any]:
    """A data-service HP body (rows newest first). ``action_k`` maps a row index to its ex-date multiplier."""
    rows = []
    for i, c in enumerate(closes_newest_first):
        day = start_day - i
        d = f"2026-11-{day:02d}" if day > 0 else f"2026-10-{31 + day:02d}"
        rows.append({"date": d, "open": c, "high": c, "low": c, "close": c, "change_pct": 0.0, "volume": 1,
                     "action_k": (action_k or {}).get(i)})
    return {"symbol": sym, "found": True, "rows": rows, "actions": [],
            "summary": {"high": high if high is not None else max(closes_newest_first),
                        "low": low if low is not None else min(closes_newest_first)}}


class FakeDataService:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.market: dict[str, Any] = {"state": "open", "session_date": "2026-11-05"}
        self.status: dict[str, Any] = {"state": "LIVE", "subscribed": 101, "ticks_per_min": 3400.0, "last_tick_age_s": 0.2,
                                       "cap": 535, "breeze_session": True,
                                       "nse_fallback": {"ok": True, "last_ok_at": "2026-11-05T10:59:30+05:30"}}
        self.histories: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.foreign: list[str] = []
        self.quotes_status: int | None = None        # answer /live/quotes with this status instead of 200
        self.status_status: int | None = None
        self.history_status: int | None = None
        self.down = False                            # every data-service request fails at the transport
        self.delay = 0.0
        self.raw_body: Any = None                    # answer /live/quotes with exactly this JSON when set

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host != "data-service":
            self.foreign.append(str(request.url))
            return httpx.Response(599, json={"detail": "the test network has no route to this host"})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/live/quotes":
            if self.quotes_status:
                return httpx.Response(self.quotes_status, json={"detail": f"boom {self.quotes_status}"})
            if self.raw_body is not None:
                return httpx.Response(200, json=self.raw_body)
            syms = [s for s in request.url.params.get("symbols", "").split(",") if s]
            return httpx.Response(200, json={"as_of": "2026-11-05T11:00:00+05:30", "market": self.market,
                                             "quotes": {s: self.rows[s] for s in syms if s in self.rows}})
        if path == "/live/status":
            if self.status_status:
                return httpx.Response(self.status_status, json={"detail": "status boom"})
            return httpx.Response(200, json=self.status)
        m = _HISTORY.match(request.url.raw_path.decode().split("?")[0])
        if m:
            if self.history_status:
                return httpx.Response(self.history_status, json={"detail": "history boom"})
            sym = unquote(m.group(1))
            body = self.histories.get(sym)
            return httpx.Response(200, json=body) if body else httpx.Response(404, json={"detail": f"{sym} not found"})
        if path == "/db/prev-close":
            return httpx.Response(200, json={"before": "x", "prev": {}})
        return httpx.Response(404, json={"detail": f"no fake for {path}"})

    def quote_calls(self) -> list[list[str]]:
        return [[s for s in r.url.params.get("symbols", "").split(",") if s] for r in self.requests
                if r.url.host == "data-service" and r.url.path == "/live/quotes"]

    def calls_to(self, path_prefix: str) -> int:
        return sum(1 for r in self.requests if r.url.host == "data-service" and r.url.path.startswith(path_prefix))


class YahooSpy:
    """Stands in for news_scanner._yahoo_chart (the only Yahoo quote fetch) and records every symbol asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, symbol: str, rng: str, interval: str) -> dict[str, Any] | None:
        self.calls.append(symbol)
        t0 = int(time.time()) - 600
        ts = [t0 - 2 * 86400, t0 - 86400, t0]
        return {"meta": {"symbol": symbol, "regularMarketPrice": 101.0, "regularMarketTime": t0, "gmtoffset": 0,
                         "currency": "USD"},
                "timestamp": ts,
                "indicators": {"quote": [{"open": [99.0, 100.0, 101.0], "high": [99.0, 100.0, 101.0],
                                          "low": [99.0, 100.0, 101.0], "close": [99.0, 100.0, 101.0], "volume": [1, 2, 3]}]}}


def install(monkeypatch: Any, fake: FakeDataService | None = None, *, clock: Clock | None = None,
            wall: datetime = NOW) -> FakeDataService:
    """Route every HTTP client through ``fake``; fresh hub / status cache / contexts / push loops (fake clock if given)."""
    fake = fake or FakeDataService()
    clients: dict[int, httpx.AsyncClient] = {}

    def fake_client() -> httpx.AsyncClient:
        try:
            key = id(asyncio.get_running_loop())
        except RuntimeError:
            key = 0
        c = clients.get(key)
        if c is None or c.is_closed:
            c = clients[key] = REAL_ASYNC_CLIENT(transport=httpx.MockTransport(fake.handler))
        return c

    def guarded(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return REAL_ASYNC_CLIENT(*args, transport=httpx.MockTransport(fake.handler), **kwargs)

    monkeypatch.setattr(http_client, "get_async_client", fake_client)
    monkeypatch.setattr(httpx, "AsyncClient", guarded)
    monkeypatch.setenv("DATA_SERVICE_URL", DS)
    monkeypatch.delenv("LIVE_QUOTES_NSE", raising=False)
    http_client.reset_state()
    live.reset_for_tests()
    clk = clock or Clock()
    monkeypatch.setattr(live, "_hub", live.LiveQuotesHub(clock=clk, wall=lambda: wall))
    monkeypatch.setattr(live, "_status", live.LiveStatusCache(clock=clk))
    monkeypatch.setattr(live, "now_ist", lambda: wall)
    ns._cache.clear()
    return fake


def spy_yahoo(monkeypatch: Any) -> YahooSpy:
    spy = YahooSpy()
    monkeypatch.setattr(ns, "_yahoo_chart", spy)
    return spy
