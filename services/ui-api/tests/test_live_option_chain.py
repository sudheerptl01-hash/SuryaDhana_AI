"""GET /api/live/option-chain/{symbol} (routers/live_option_chain.py, 22 Nov 2026): data-service's Breeze-overlaid chain
(/live/option-chain) passed through unchanged plus ``served_by`` / ``fallback_reason``; NSE's v3 chain
(/db/option-chain-live) when the live route is not deployed (404), fails (5xx / transport / timeout / open breaker) or
answers without rows; both through the process-wide client (no AsyncClient per call), the live read on a breaker of its
own. Fakes only: an httpx.MockTransport plays data-service; nothing leaves the machine."""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import live_option_chain as loc
from shared import http_client

DS = "http://data-service:8001"
REAL_ASYNC_CLIENT = httpx.AsyncClient
UI_API = Path(__file__).resolve().parents[1]

# a /live/option-chain body as live_chain.py writes it (two band strikes; 24500 CE ticks but has not traded today)
LIVE_BODY: dict[str, Any] = {
    "symbol": "NIFTY", "found": True, "date": "2026-11-23", "expiry": "2026-11-25", "expiries": ["2026-11-25"],
    "days_to_expiry": 2, "t_days": 2.3, "spot": 24412.5, "future": 24440.0, "forward": 24431.2, "forward_source": "parity",
    "atm": 24400.0, "lot": 65, "atm_iv": 12.4, "expected_move_pct": 1.1, "pcr_oi": 0.92, "max_pain": 24300.0,
    "call_oi_total": 1.0e8, "put_oi_total": 9.2e7, "resistance": [24500.0], "support": [24300.0],
    "live": True, "as_of": "2026-11-23T10:20:30+05:30", "base": "nse",
    "rows": [
        {"strike": 24400.0, "band": True,
         "ce": {"price": 120.5, "oi": 6.5e6, "oi_chg": 65000.0, "volume": 1200.0, "iv": 12.1, "source": "breeze_ws", "price_source": "breeze_ws", "age_s": 0.6,
                "tick_state": "live", "key": "NFO:NIFTY:2026-11-25:24400:CE", "ltp": 120.5, "bid": 120.4, "ask": 120.6,
                "bid_qty": 650, "ask_qty": 1300, "ltt": "2026-11-23T10:20:29+05:30", "prev_close": 110.0},
         "pe": {"price": 101.0, "oi": 5.2e6, "oi_chg": -13000.0, "volume": 900.0, "iv": 12.6, "source": "nse", "price_source": "nse", "age_s": 48.0,
                "tick_state": "waiting_first_tick", "key": "NFO:NIFTY:2026-11-25:24400:PE", "ltp": None, "bid": 100.5, "ask": 101.5,
                "bid_qty": 65, "ask_qty": 130, "ltt": None, "prev_close": None}},
        {"strike": 24500.0, "band": True,
         "ce": {"price": 70.0, "oi": 9.1e6, "oi_chg": 0.0, "volume": 800.0, "iv": 12.0, "source": "breeze_ws", "price_source": "nse", "age_s": 0.9,
                "tick_state": "live", "key": "NFO:NIFTY:2026-11-25:24500:CE", "ltp": None, "bid": None, "ask": None,
                "bid_qty": None, "ask_qty": None, "ltt": None, "prev_close": None},
         "pe": {"price": 160.0, "oi": 3.0e6, "oi_chg": 0.0, "volume": 300.0, "iv": None, "source": "nse", "price_source": "nse", "age_s": 48.0,
                "tick_state": "outside_band", "key": "NFO:NIFTY:2026-11-25:24500:PE", "ltp": None, "bid": None, "ask": None,
                "bid_qty": None, "ask_qty": None, "ltt": None, "prev_close": None}},
    ],
    "feed": {"as_of": "2026-11-23T10:20:30+05:30", "nse_as_of": "23-Nov-2026 10:19:42", "eod_date": None, "base": "nse",
             "base_error": None, "base_age_s": 48.0, "counts": {"breeze_ws": 2, "nse": 2, "eod": 0}, "master_error": None,
             "band": {"centre": 24400.0, "atm": 24400.0, "step": 50.0, "width": 10, "strikes": [24400.0, 24500.0],
                      "recentred_at": "2026-11-23T09:15:05+05:30", "pending_s": None},
             "expiry": {"chosen": "2026-11-25", "source": "master", "requested": None, "note": None,
                        "master_expiries": ["2026-11-25", "2026-12-02", "2026-12-30"]},
             "subscription": {"engine": "LIVE", "enabled": True, "healthy": True, "keys": 4, "live": 1, "subscribed": 4,
                              "waiting_first_tick": 1, "over_cap": 0},
             "rules": {"fresh_s": 5.0, "quiet_live_s": 120.0, "recentre_strikes": 1.5, "recentre_hold_s": 30.0, "memo_s": 1.0}},
}
# a /db/option-chain-live body (NSE v3 through nse_live, no feed block)
NSE_BODY: dict[str, Any] = {
    "symbol": "NIFTY", "found": True, "date": "2026-11-23", "expiry": "2026-11-25", "expiries": ["2026-11-25", "2026-12-02"],
    "days_to_expiry": 2, "spot": 24410.0, "forward": 24430.0, "atm": 24400.0, "lot": 65, "atm_iv": 12.5,
    "rows": [{"strike": 24400.0, "ce": {"price": 119.0, "oi": 6.4e6, "oi_chg": 0.0, "volume": 1100.0, "iv": 12.2},
              "pe": {"price": 101.0, "oi": 5.2e6, "oi_chg": 0.0, "volume": 900.0, "iv": 12.6}}],
    "resistance": [24500.0], "support": [24300.0], "live": True, "as_of": "23-Nov-2026 10:19:42",
}


class FakeDataService:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.live_status: int | None = None
        self.live_detail = "Not Found"
        self.live_body: Any = copy.deepcopy(LIVE_BODY)
        self.live_raise: type[Exception] | None = None
        self.nse_status: int | None = None
        self.nse_raise: type[Exception] | None = None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host != "data-service":
            return httpx.Response(599, json={"detail": "the test network has no route to this host"})
        path = request.url.path
        if path.startswith("/live/option-chain/"):
            if self.live_raise is not None:
                raise self.live_raise("boom", request=request)
            if self.live_status:
                return httpx.Response(self.live_status, json={"detail": self.live_detail})
            return httpx.Response(200, json=self.live_body)
        if path.startswith("/db/option-chain-live/"):
            if self.nse_raise is not None:
                raise self.nse_raise("nse boom", request=request)
            if self.nse_status:
                return httpx.Response(self.nse_status, json={"detail": f"NSE live option chain unavailable ({self.nse_status})"})
            return httpx.Response(200, json=NSE_BODY)
        return httpx.Response(404, json={"detail": "Not Found"})

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


class Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(loc, "_clock", c)
    return c


@pytest.fixture
def ds(monkeypatch: pytest.MonkeyPatch, clock: Clock) -> FakeDataService:
    fake = FakeDataService()
    clients: dict[int, httpx.AsyncClient] = {}
    fake.shared_calls = 0            # type: ignore[attr-defined]
    fake.constructed = 0             # type: ignore[attr-defined]

    def shared_client() -> httpx.AsyncClient:
        fake.shared_calls += 1       # type: ignore[attr-defined]
        try:
            key = id(asyncio.get_running_loop())
        except RuntimeError:
            key = 0
        c = clients.get(key)
        if c is None or c.is_closed:
            c = clients[key] = REAL_ASYNC_CLIENT(transport=httpx.MockTransport(fake.handler))
        return c

    def counted(*args: Any, **kwargs: Any) -> httpx.AsyncClient:      # any router-built client is counted (and faked)
        fake.constructed += 1        # type: ignore[attr-defined]
        kwargs.pop("transport", None)
        return REAL_ASYNC_CLIENT(*args, transport=httpx.MockTransport(fake.handler), **kwargs)

    monkeypatch.setattr(http_client, "get_async_client", shared_client)
    monkeypatch.setattr(httpx, "AsyncClient", counted)
    monkeypatch.setenv("DATA_SERVICE_URL", DS)
    http_client.reset_state()
    loc.reset_for_tests()
    yield fake
    http_client.reset_state()
    loc.reset_for_tests()


@pytest.fixture
def client(ds: FakeDataService) -> Any:
    app = FastAPI()
    app.include_router(loc.router, prefix="/api/live")
    with TestClient(app, base_url="http://127.0.0.1:8010") as c:
        yield c


def test_the_live_body_passes_through_unchanged_with_the_two_marks(client: Any, ds: FakeDataService) -> None:
    r = client.get("/api/live/option-chain/NIFTY", params={"expiry": "2026-11-25", "width": 12})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {**LIVE_BODY, "served_by": "live_chain", "fallback_reason": None}
    # per side and chain-level fields survive untouched (the UI's chip and dimming read them)
    assert body["rows"][0]["ce"]["source"] == "breeze_ws" and body["rows"][0]["pe"]["tick_state"] == "waiting_first_tick"
    # 23 Nov: an untraded live strike: source breeze_ws (OI / book live), price_source nse (its price is NSE's)
    assert body["rows"][1]["ce"]["source"] == "breeze_ws" and body["rows"][1]["ce"]["price_source"] == "nse"
    assert body["feed"]["counts"] == {"breeze_ws": 2, "nse": 2, "eod": 0} and body["feed"]["expiry"]["master_expiries"][-1] == "2026-12-30"
    assert ds.paths() == ["/live/option-chain/NIFTY"]
    q = ds.requests[0].url.params
    assert q.get("expiry") == "2026-11-25" and q.get("width") == "12"


def test_symbol_is_upper_cased_and_absent_params_are_not_sent(client: Any, ds: FakeDataService) -> None:
    r = client.get("/api/live/option-chain/nifty")
    assert r.status_code == 200 and r.json()["served_by"] == "live_chain"
    assert ds.paths() == ["/live/option-chain/NIFTY"] and not dict(ds.requests[0].url.params)


def test_not_deployed_404_falls_back_and_is_not_reprobed_for_a_minute(client: Any, ds: FakeDataService, clock: Clock) -> None:
    ds.live_status, ds.live_detail = 404, "Not Found"
    r = client.get("/api/live/option-chain/NIFTY", params={"expiry": "2026-11-25"})
    assert r.status_code == 200
    body = r.json()
    assert body["served_by"] == "nse_fallback" and "not deployed" in body["fallback_reason"]
    assert {k: v for k, v in body.items() if k not in ("served_by", "fallback_reason")} == NSE_BODY   # pass-through
    assert "feed" not in body                                    # the UI labels it DELAYED · NSE, never LIVE
    assert ds.paths() == ["/live/option-chain/NIFTY", "/db/option-chain-live/NIFTY"]
    assert ds.requests[1].url.params.get("expiry") == "2026-11-25"
    clock.t += 30
    assert client.get("/api/live/option-chain/NIFTY").json()["served_by"] == "nse_fallback"
    assert ds.paths()[2:] == ["/db/option-chain-live/NIFTY"], "the missing route was asked again inside the minute"
    clock.t += loc.ROUTE_MISSING_S
    ds.live_status = None                                         # deployed meanwhile
    assert client.get("/api/live/option-chain/NIFTY").json()["served_by"] == "live_chain"
    assert ds.paths()[-1] == "/live/option-chain/NIFTY"


def test_the_routes_own_404_falls_back_but_is_asked_again_next_time(client: Any, ds: FakeDataService) -> None:
    ds.live_status, ds.live_detail = 404, "no option chain for ZZZ: NSE gave nothing; no stored F&O bhavcopy row"
    r = client.get("/api/live/option-chain/NIFTY")
    assert r.json()["served_by"] == "nse_fallback" and "HTTP 404" in r.json()["fallback_reason"]
    client.get("/api/live/option-chain/NIFTY")
    assert ds.paths().count("/live/option-chain/NIFTY") == 2


@pytest.mark.parametrize("failure", ["500", "503", "connect", "timeout", "no_rows", "not_found_body", "not_json_dict"])
def test_live_failures_fall_back_to_nse(client: Any, ds: FakeDataService, failure: str) -> None:
    if failure in ("500", "503"):
        ds.live_status, ds.live_detail = int(failure), "live chain blew up"
    elif failure == "connect":
        ds.live_raise = httpx.ConnectError
    elif failure == "timeout":
        ds.live_raise = httpx.ReadTimeout
    elif failure == "no_rows":
        ds.live_body = {"symbol": "NIFTY", "found": True, "feed": {}}
    elif failure == "not_found_body":
        ds.live_body = {"symbol": "NIFTY", "found": False, "rows": []}
    else:
        ds.live_body = ["not", "a", "chain"]
    r = client.get("/api/live/option-chain/NIFTY")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["served_by"] == "nse_fallback" and body["fallback_reason"], body
    assert body["rows"] == NSE_BODY["rows"] and "feed" not in body
    assert ds.paths() == ["/live/option-chain/NIFTY", "/db/option-chain-live/NIFTY"]


def test_both_failing_is_a_503_naming_both_reasons(client: Any, ds: FakeDataService) -> None:
    ds.live_status, ds.live_detail = 500, "live chain blew up"
    ds.nse_status = 502
    r = client.get("/api/live/option-chain/NIFTY")
    assert r.status_code == 503
    detail = r.json()["detail"]
    text = detail if isinstance(detail, str) else detail["message"]
    assert "live chain unavailable (HTTP 500" in text and "NSE's option chain unavailable too (HTTP 502" in text
    ds.nse_status, ds.nse_raise = None, httpx.ConnectError
    assert client.get("/api/live/option-chain/NIFTY").status_code == 503


def test_an_upstream_no_for_the_symbol_keeps_its_4xx(client: Any, ds: FakeDataService) -> None:
    ds.live_status, ds.live_detail = 404, "no option chain for ZZZ"
    ds.nse_status = 404
    assert client.get("/api/live/option-chain/ZZZ").status_code == 404


@pytest.mark.parametrize("path,params", [("/api/live/option-chain/NIF TY", {}), ("/api/live/option-chain/%3Cimg%3E", {}),
                                         ("/api/live/option-chain/NIFTY", {"expiry": "25NOV"}),
                                         ("/api/live/option-chain/NIFTY", {"width": 0}),
                                         ("/api/live/option-chain/NIFTY", {"width": 21})])
def test_bad_requests_are_422_without_an_upstream_call(client: Any, ds: FakeDataService, path: str, params: dict) -> None:
    assert client.get(path, params=params).status_code == 422
    assert ds.requests == []


def test_an_upstream_422_is_passed_through_not_masked_by_the_fallback(client: Any, ds: FakeDataService) -> None:
    ds.live_status, ds.live_detail = 422, "Bad symbol"
    r = client.get("/api/live/option-chain/NIFTY")
    assert r.status_code == 422 and ds.paths() == ["/live/option-chain/NIFTY"]


def test_every_call_uses_the_shared_client_and_builds_no_async_client(client: Any, ds: FakeDataService) -> None:
    for _ in range(6):
        assert client.get("/api/live/option-chain/NIFTY").status_code == 200
    ds.live_status = 503
    for _ in range(3):
        assert client.get("/api/live/option-chain/BANKNIFTY").json()["served_by"] == "nse_fallback"
    assert ds.constructed == 0, "the route built its own httpx.AsyncClient"           # type: ignore[attr-defined]
    assert ds.shared_calls >= 12 and len(ds.requests) == 12                           # type: ignore[attr-defined]


def test_negative_control_the_counter_sees_a_per_call_client(ds: FakeDataService) -> None:
    """The old /api/market/option-chain-live shape (``async with httpx.AsyncClient(...)``) is what the counter catches."""
    async def old_proxy() -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0)) as c:
            await c.get(f"{DS}/db/option-chain-live/NIFTY")
    asyncio.run(old_proxy())
    assert ds.constructed == 1                                                        # type: ignore[attr-defined]


def test_live_failures_open_only_the_live_chains_breaker(client: Any, ds: FakeDataService) -> None:
    ds.live_raise = httpx.ConnectError
    for _ in range(5):
        assert client.get("/api/live/option-chain/NIFTY").json()["served_by"] == "nse_fallback"
    assert http_client.breaker_for(loc.UPSTREAM).state() == "open"
    assert http_client.breaker_for(http_client.upstream_of(DS)).state() == "closed"    # every other data-service read
    n = len(ds.requests)
    r = client.get("/api/live/option-chain/NIFTY").json()
    assert r["served_by"] == "nse_fallback" and "circuit open" in r["fallback_reason"]
    assert ds.paths()[n:] == ["/db/option-chain-live/NIFTY"], "the open breaker still let a live request out"


def test_the_route_is_mounted_beside_the_live_quotes() -> None:
    main = (UI_API / "main.py").read_text(encoding="utf-8")
    assert "from routers import live_option_chain" in main
    assert 'app.include_router(live_option_chain.router, prefix="/api/live"' in main
    src = (UI_API / "routers" / "live_option_chain.py").read_text(encoding="utf-8")
    assert "httpx.AsyncClient(" not in src and "stale_for" not in src.split('"""', 2)[2]   # shared client, no stale-serve
