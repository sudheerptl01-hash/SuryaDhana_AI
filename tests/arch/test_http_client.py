"""shared/http_client.py (Terminal v2 PLAN §0.6 + 1.5): the allowlist refuses before any socket opens, Yahoo only by
explicit opt-in, per-host pacing, the NSE 403/429 → 600 s breaker, one AsyncClient per loop, per-route timeouts, the
per-upstream circuit breaker (closed → open → half-open probe) and stale-serve. Negative controls: a 4xx never trips
the breaker; without ``stale_for`` a 5xx is an error; a stale body older than ``stale_for`` is not served."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared import http_client as hc  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    hc.reset_state()
    yield
    hc.reset_state()


# ── allowlist ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_allowlist_and_forbidden_publishers():
    assert hc.is_allowed("https://nsearchives.nseindia.com/content/fo/x.zip")
    assert hc.is_allowed("https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv")
    assert hc.is_allowed("http://127.0.0.1:8001/db/stats") and hc.is_allowed("http://data-service:8001/health")
    for bad in ("https://www.mcxindia.com/x", "https://www.cmegroup.com/x", "https://kitco.com/x", "https://stooq.com/q",
                "https://in.investing.com/x", "https://goldprice.org/x", "https://prices.lbma.org.uk/x", "https://example.com/"):
        assert not hc.is_allowed(bad), bad
        with pytest.raises(hc.HostNotAllowed):
            hc.assert_allowed(bad)
    # Yahoo: refused by default (PLAN §0.7 — no new caller), accepted only by the explicit opt-in of the one gold fetcher
    y = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
    assert not hc.is_allowed(y) and hc.is_allowed(y, allow_yahoo=True)
    with pytest.raises(hc.HostNotAllowed, match="Yahoo"):
        hc.assert_allowed(y)
    assert set(hc.FORBIDDEN_HOST_FRAGMENTS) >= {"mcxindia.com", "www.cmegroup.com", "kitco.com", "stooq.com"}


def test_paced_client_refuses_before_any_socket_opens():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="ok")

    c = hc.PacedClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(hc.HostNotAllowed):
        c.get("https://www.mcxindia.com/market-data")
    with pytest.raises(hc.HostNotAllowed):
        c.get("https://query2.finance.yahoo.com/v8/finance/chart/%5ENSEI")
    assert calls == []
    r = c.get("https://nsearchives.nseindia.com/content/indices/ind_close_all_04112026.csv")
    assert r.status_code == 200 and calls == ["https://nsearchives.nseindia.com/content/indices/ind_close_all_04112026.csv"]


def test_paced_client_paces_per_host_and_sends_the_browser_ua_to_nse():
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    clock = {"t": 100.0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="ok")

    def sleep(s: float) -> None:
        sleeps.append(s)
        clock["t"] += s

    c = hc.PacedClient(transport=httpx.MockTransport(handler), sleep=sleep, clock=lambda: clock["t"])
    c.get("https://www.nseindia.com/api/allIndices")
    c.get("https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY")
    c.get("https://home.treasury.gov/x.csv")                       # another host: no wait
    assert len(sleeps) == 1 and abs(sleeps[0] - hc.MIN_GAP_S) < 1e-6
    assert seen[0].headers["user-agent"] == hc.BROWSER_UA and "SuryaDhana" in seen[0].headers["user-agent"]
    assert seen[2].headers["user-agent"] == hc.PLAIN_UA
    assert hc.user_agent_for("fred.stlouisfed.org") is None        # FRED: library default UA


def test_nse_403_opens_a_600s_breaker_and_a_4xx_elsewhere_does_not():
    clock = {"t": 0.0}
    status = {"code": 403}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status["code"], text="blocked")

    c = hc.PacedClient(transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: clock["t"])
    r = c.get("https://www.nseindia.com/api/allIndices")
    assert r.status_code == 403
    with pytest.raises(hc.UpstreamError) as ei:
        c.get("https://www.nseindia.com/api/allIndices")
    assert ei.value.status_code == 503 and "backing off" in ei.value.detail
    assert c.blocked_until("www.nseindia.com") == pytest.approx(hc.NSE_BLOCK_S)
    clock["t"] = hc.NSE_BLOCK_S + 1
    status["code"] = 200
    assert c.get("https://www.nseindia.com/api/allIndices").status_code == 200
    # negative control: a 404 from a non-NSE host never opens a breaker
    status["code"] = 404
    c.get("https://home.treasury.gov/missing.csv")
    assert c.blocked_until("home.treasury.gov") == 0.0
    assert c.get("https://home.treasury.gov/missing.csv").status_code == 404


# ── async half ──────────────────────────────────────────────────────────────────────────────────────────────────
def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_one_async_client_per_loop():
    async def main():
        a = hc.get_async_client()
        b = hc.get_async_client()
        assert a is b and not a.is_closed
        await hc.aclose_async_client()
        assert a.is_closed
        c = hc.get_async_client()
        assert c is not a
        await hc.aclose_async_client()

    asyncio.run(main())
    assert hc.LIMITS.max_connections == 32 and hc.LIMITS.max_keepalive_connections == 16
    assert hc.ROUTE_TIMEOUTS["live"].read == 15.0 and hc.ROUTE_TIMEOUTS["job"].read == 600.0


def test_get_json_ok_and_error_mapping():
    async def main():
        state = {"code": 200}

        def handler(request: httpx.Request) -> httpx.Response:
            if state["code"] == 200:
                return httpx.Response(200, json={"last": 25000.5, "q": request.url.params.get("names")})
            return httpx.Response(state["code"], json={"detail": "NSE flaked"})

        async with _client(handler) as c:
            body = await hc.get_json("http://127.0.0.1:8001/db/indices-live", route="live", params={"names": "NIFTY 50"},
                                     client=c)
            assert body == {"last": 25000.5, "q": "NIFTY 50"}
            state["code"] = 404
            with pytest.raises(hc.UpstreamError) as ei:
                await hc.get_json("http://127.0.0.1:8001/db/indices-live", route="live", client=c)
            assert ei.value.status_code == 404 and ei.value.detail == "NSE flaked"
            state["code"] = 502
            with pytest.raises(hc.UpstreamError) as ei:            # negative control: no stale_for → the 5xx surfaces
                await hc.get_json("http://127.0.0.1:8001/db/indices-live", route="live", client=c)
            assert ei.value.status_code == 502

    asyncio.run(main())


def test_stale_serve_and_circuit_breaker():
    async def main():
        state = {"code": 200, "calls": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["calls"] += 1
            if state["code"] == 200:
                return httpx.Response(200, json={"last": 1.0})
            return httpx.Response(state["code"], text="upstream down")

        url = "http://127.0.0.1:8001/db/nifty-live"
        async with _client(handler) as c:
            assert await hc.get_json(url, route="live", stale_for=120, client=c) == {"last": 1.0}
            state["code"] = 503
            body = await hc.get_json(url, route="live", stale_for=120, client=c)
            assert body["last"] == 1.0 and body["stale"] is True and "stale_age_s" in body
            # five failures in the window open the breaker; then no call reaches the transport
            for _ in range(4):
                await hc.get_json(url, route="live", stale_for=120, client=c)
            br = hc.breaker_for("127.0.0.1:8001")
            assert br.state() == "open"
            calls_before = state["calls"]
            body = await hc.get_json(url, route="live", stale_for=120, client=c)
            assert body["stale"] is True and state["calls"] == calls_before, "an open breaker serves stale without a call"
            with pytest.raises(hc.UpstreamError) as ei:          # a route with no stale body → 503 with the wait
                await hc.get_json("http://127.0.0.1:8001/db/other", route="live", client=c)
            assert ei.value.status_code == 503 and "circuit open" in ei.value.detail and ei.value.retry_after_s > 0
            # half-open after open_s: exactly one probe goes out; success closes the breaker
            br.clock = lambda: time.monotonic() + 1000.0          # the open period has elapsed
            assert br.state() == "half-open"
            state["code"] = 200
            calls_before = state["calls"]
            body = await hc.get_json(url, route="live", stale_for=120, client=c)
            assert body == {"last": 1.0} and state["calls"] == calls_before + 1 and br.state() == "closed"

    asyncio.run(main())


def test_a_4xx_never_trips_the_breaker():
    br = hc.CircuitBreaker("x", threshold=2)
    for _ in range(10):
        br.record(True)
    assert br.state() == "closed"

    async def main():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "bad symbol"})

        async with _client(handler) as c:
            for _ in range(8):
                with pytest.raises(hc.UpstreamError):
                    await hc.get_json("http://127.0.0.1:8001/db/security/XX/history", route="read", client=c)
        assert hc.breaker_for("127.0.0.1:8001").state() == "closed"

    asyncio.run(main())


def test_stale_body_expires():
    async def main():
        state = {"code": 200}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"v": 1}) if state["code"] == 200 else httpx.Response(500, text="x")

        url = "http://127.0.0.1:8001/db/gift-nifty"
        async with _client(handler) as c:
            await hc.get_json(url, route="live", stale_for=0.05, client=c)
            await asyncio.sleep(0.08)
            state["code"] = 500
            with pytest.raises(hc.UpstreamError) as ei:
                await hc.get_json(url, route="live", stale_for=0.05, client=c)
            assert ei.value.status_code == 500

    asyncio.run(main())


def test_transport_error_is_503_with_stale_fallback():
    async def main():
        state = {"fail": False}

        def handler(request: httpx.Request) -> httpx.Response:
            if state["fail"]:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json={"ok": 1})

        url = "http://data-service:8001/db/nifty-live"
        async with _client(handler) as c:
            with pytest.raises(hc.UpstreamError) as ei:
                state["fail"] = True
                await hc.get_json(url, route="live", client=c)
            assert ei.value.status_code == 503 and "unreachable" in ei.value.detail and ei.value.upstream == "data-service"
            state["fail"] = False
            await hc.get_json(url, route="live", stale_for=60, client=c)
            state["fail"] = True
            assert (await hc.get_json(url, route="live", stale_for=60, client=c))["stale"] is True

    asyncio.run(main())


def test_get_json_refuses_forbidden_hosts_without_a_call():
    async def main():
        with pytest.raises(hc.HostNotAllowed):
            await hc.get_json("https://www.mcxindia.com/api/x", route="live")

    asyncio.run(main())
