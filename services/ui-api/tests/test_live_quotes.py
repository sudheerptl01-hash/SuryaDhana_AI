"""GET /api/live/quotes and /api/live/status (routers/live.py, LV-API): the contract body passes through typed, a symbol
is asked of data-service at most once per 2 s app-wide (single flight), ages include the cache time, and when
data-service fails the last good row is served re-stated (live -> delayed -> stale -> unavailable) with a reason."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
import test_live_support as sup
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import live
from shared import http_client

CONTRACT_ROW_KEYS = {"price", "change", "change_pct", "prev_close", "open", "day_high", "day_low", "volume", "value_cr",
                     "bid", "ask", "ltt", "source", "age_s", "state"}


@pytest.fixture
def clock() -> sup.Clock:
    return sup.Clock()


@pytest.fixture
def ds(monkeypatch: pytest.MonkeyPatch, clock: sup.Clock) -> sup.FakeDataService:
    fake = sup.install(monkeypatch, clock=clock)
    fake.rows = {"RELIANCE": sup.row(1311.0), "TCS": sup.row(3050.0, state="delayed", source="nse_api", age_s=49.0),
                 "NIFTY 50": sup.row(24350.5, change_pct=0.4), "INFY": sup.row(1490.0, state="closed", source="eod",
                                                                                 age_s=None)}
    return fake


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(live.router, prefix="/api/live")
    return app


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_rows_pass_through_with_source_age_and_state(ds: sup.FakeDataService) -> None:
    with TestClient(_app(), base_url="http://127.0.0.1:8010") as c:
        r = c.get("/api/live/quotes", params={"symbols": "reliance.ns,TCS, nifty  50 ,INFY"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"as_of", "market", "quotes", "feed", "upstream"} and body["feed"] is None
    assert body["market"] == {"state": "open", "session_date": "2026-11-05"} and body["upstream"]["ok"] is True
    assert list(body["quotes"]) == ["RELIANCE", "TCS", "NIFTY 50", "INFY"]            # request order, normalised
    for q in body["quotes"].values():
        assert CONTRACT_ROW_KEYS <= set(q)
    rel, tcs, nifty, infy = (body["quotes"][s] for s in ("RELIANCE", "TCS", "NIFTY 50", "INFY"))
    assert (rel["price"], rel["source"], rel["state"], rel["age_s"]) == (1311.0, "breeze_ws", "live", 0.6)
    assert (tcs["source"], tcs["state"], tcs["age_s"]) == ("nse_api", "delayed", 49.0)
    assert nifty["price"] == 24350.5 and infy["state"] == "closed" and infy["age_s"] is None
    assert r.headers["x-cache"] == "miss" and r.headers["x-cache-age"] == "0"
    assert ds.quote_calls() == [["RELIANCE", "TCS", "NIFTY 50", "INFY"]] and ds.foreign == []


def test_a_symbol_is_asked_at_most_once_per_2_s_app_wide(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    h = live.hub()

    async def go() -> None:
        await h.quotes(["RELIANCE", "TCS"])
        clock.t += 1.0
        await h.quotes(["RELIANCE", "TCS"])               # inside 2 s: the cache
        await h.quotes(["TCS", "INFY"])                    # only INFY is new
        clock.t += 1.1                                     # RELIANCE/TCS now 2.1 s old, INFY 1.1 s
        await h.quotes(["RELIANCE", "TCS", "INFY"])
    run(go())
    assert ds.quote_calls() == [["RELIANCE", "TCS"], ["INFY"], ["RELIANCE", "TCS"]]


def test_negative_control_without_the_window_every_ask_goes_upstream(ds: sup.FakeDataService,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "REFRESH_S", 0.0)

    async def go() -> None:
        for _ in range(3):
            await live.hub().quotes(["RELIANCE"])
    run(go())
    assert len(ds.quote_calls()) == 3                  # the test above can see a missing cache


def test_concurrent_askers_share_one_batch(ds: sup.FakeDataService) -> None:
    ds.delay = 0.05

    async def go() -> list[live.Snapshot]:
        h = live.hub()
        return list(await asyncio.gather(h.quotes(["RELIANCE", "TCS"]), h.quotes(["TCS", "RELIANCE"]),
                                         h.quotes(["RELIANCE"]), h.quotes(["TCS", "INFY"])))
    snaps = run(go())
    calls = ds.quote_calls()
    asked = [s for c in calls for s in c]
    assert sorted(asked) == ["INFY", "RELIANCE", "TCS"], calls          # each symbol asked exactly once
    assert len(calls) == 2 and live.hub().counts["coalesced"] >= 3
    assert all(s.payload["quotes"]["RELIANCE"]["price"] == 1311.0 for s in snaps[:3])


def test_age_includes_the_time_in_the_cache(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    async def go() -> dict[str, Any]:
        await live.hub().quotes(["RELIANCE"])
        clock.t += 1.5
        return (await live.hub().quotes(["RELIANCE"])).payload["quotes"]["RELIANCE"]
    q = run(go())
    assert q["age_s"] == 2.1 and q["state"] == "live" and "reason" not in q


def test_a_cache_hit_that_crosses_the_refresh_window_while_waiting_is_not_a_failure(ds: sup.FakeDataService,
                                                                                     clock: sup.Clock) -> None:
    """5 Nov race: RELIANCE cached 1.99 s (a hit, no refresh due) + INFY needing a fetch that takes 50 ms → RELIANCE was
    assembled at 2.04 s and re-stated 'delayed: data-service did not answer' although every upstream call succeeded."""
    h = live.hub()
    orig = h._fetch

    async def slow_fetch(chunk: tuple[str, ...]) -> None:
        clock.t += 0.05                       # the other symbol's batch takes 50 ms
        await orig(chunk)

    async def go() -> tuple[dict[str, Any], dict[str, Any]]:
        await h.quotes(["RELIANCE"])
        clock.t += 1.99
        h._fetch = slow_fetch                 # type: ignore[method-assign]
        hit = (await h.quotes(["RELIANCE", "INFY"])).payload["quotes"]["RELIANCE"]
        ds.down = True                        # negative control: a symbol whose refresh really fails IS flagged
        clock.t += 2.5
        failed = (await h.quotes(["RELIANCE"])).payload["quotes"]["RELIANCE"]
        return hit, failed
    hit, failed = run(go())
    assert hit["state"] == "live" and "reason" not in hit and hit["age_s"] > 2.0          # age honest, state not degraded
    assert failed["state"] == "delayed" and "did not answer" in failed["reason"]


def test_data_service_down_serves_the_last_row_restated_then_unavailable(ds: sup.FakeDataService,
                                                                        clock: sup.Clock) -> None:
    h = live.hub()

    async def go() -> list[dict[str, Any]]:
        out = []
        await h.quotes(["RELIANCE", "TCS"])
        ds.down = True
        for dt in (3.0, 100.0, 1000.0):
            clock.t += dt
            out.append((await h.quotes(["RELIANCE", "TCS"])).payload)
        return out
    a, b, c = run(go())
    rel = a["quotes"]["RELIANCE"]
    assert (rel["state"], rel["age_s"], rel["price"]) == ("delayed", 3.6, 1311.0)      # was live 0.6 s + 3 s cache
    assert "did not answer" in rel["reason"]
    assert (a["quotes"]["TCS"]["state"], a["quotes"]["TCS"]["age_s"]) == ("delayed", 52.0)   # delayed 49 s + 3 s <= 90 s
    assert b["quotes"]["RELIANCE"]["state"] == "stale" and b["upstream"]["ok"] is False
    assert (b["quotes"]["TCS"]["state"], b["quotes"]["TCS"]["age_s"]) == ("stale", 152.0)
    assert "ConnectError" in b["upstream"]["error"]
    assert c["quotes"]["RELIANCE"]["state"] == "unavailable" and c["quotes"]["RELIANCE"]["price"] is None
    assert "did not answer" in c["quotes"]["RELIANCE"]["reason"]


def test_a_symbol_never_answered_is_unavailable_and_the_market_comes_from_the_clock(ds: sup.FakeDataService) -> None:
    ds.down = True
    with TestClient(_app(), base_url="http://127.0.0.1:8010") as c:
        r = c.get("/api/live/quotes", params={"symbols": "RELIANCE"})
    assert r.status_code == 200
    q = r.json()["quotes"]["RELIANCE"]
    assert q["state"] == "unavailable" and q["price"] is None and "ConnectError" in q["reason"]
    m = r.json()["market"]
    assert (m["state"], m["session_date"]) == ("open", "2026-11-05") and "clock" in m["reason"]


def test_the_route_not_deployed_says_so(ds: sup.FakeDataService) -> None:
    ds.quotes_status = 404
    q = run(live.hub().quotes(["RELIANCE"])).payload["quotes"]["RELIANCE"]
    assert q["state"] == "unavailable" and "not deployed" in q["reason"]


def test_malformed_upstream_rows_are_coerced_never_trusted(ds: sup.FakeDataService) -> None:
    ds.rows = {"RELIANCE": {"price": "1,311.5", "change_pct": "nan", "bid": 0, "ask": "", "state": "bogus",
                            "source": "breeze_ws", "age_s": -3, "ltt": 12, "name": "Reliance Industries",
                            "hint": "x", "blob": {"a": 1}, "Bad Key": 1},
               "TCS": {"price": None, "state": "live", "source": "nse_api"},
               "INFY": "not a row"}
    out = run(live.hub().quotes(["RELIANCE", "TCS", "INFY", "WIPRO"])).payload["quotes"]
    rel = out["RELIANCE"]
    assert rel["price"] == 1311.5 and rel["change_pct"] is None and rel["bid"] is None and rel["ask"] is None
    assert rel["state"] == "unavailable" and rel["age_s"] is None and rel["ltt"] is None
    assert rel["name"] == "Reliance Industries" and rel["hint"] == "x" and "blob" not in rel and "Bad Key" not in rel
    assert out["TCS"]["state"] == "unavailable" and "no price" in out["TCS"]["reason"]
    assert out["INFY"]["state"] == "unavailable" and "malformed" in out["INFY"]["reason"]
    assert out["WIPRO"]["state"] == "unavailable" and "not in the data-service answer" in out["WIPRO"]["reason"]


def test_a_body_without_quotes_is_an_upstream_failure(ds: sup.FakeDataService) -> None:
    ds.raw_body = {"oops": True}
    p = run(live.hub().quotes(["RELIANCE"])).payload
    assert p["quotes"]["RELIANCE"]["state"] == "unavailable" and p["upstream"]["ok"] is False


@pytest.mark.parametrize("symbols", ["../../etc/passwd", "^GSPC", "BHEL.BO", "RELIANCE,BAD SYM!", ",".join(f"S{i}" for i in range(301))])
def test_bad_or_too_many_symbols_are_422_and_never_leave(ds: sup.FakeDataService, symbols: str) -> None:
    with TestClient(_app(), base_url="http://127.0.0.1:8010") as c:
        r = c.get("/api/live/quotes", params={"symbols": symbols})
    assert r.status_code == 422, r.text
    assert ds.quote_calls() == []


def test_three_hundred_symbols_go_in_one_batch(ds: sup.FakeDataService) -> None:
    syms = [f"S{i}" for i in range(300)]
    out = run(live.hub().quotes(syms)).payload["quotes"]
    assert len(out) == 300 and len(ds.quote_calls()) == 1


def test_status_is_typed_served_stale_for_60_s_then_503(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    ds.status = {**ds.status, "subscribed": "101", "ticks_per_min": "NaN", "extra_note": "ok", "no_first_tick": {"count": 2},
                 "big": {"x": "y" * 5000}, "nse_fallback": {**ds.status["nse_fallback"], "polls": 7, "huge": "z" * 2000}}
    with TestClient(_app(), base_url="http://127.0.0.1:8010") as c:
        a = c.get("/api/live/status")
        ds.status_status = 500
        clock.t += 30.0
        b = c.get("/api/live/status")
        clock.t += 40.0
        d = c.get("/api/live/status")
    assert a.status_code == 200, a.text
    s = a.json()
    assert (s["state"], s["subscribed"], s["ticks_per_min"], s["cap"], s["breeze_session"]) == ("LIVE", 101, None, 535, True)
    assert s["nse_fallback"] == {"ok": True, "last_ok_at": "2026-11-05T10:59:30+05:30", "polls": 7}
    assert s["extra_note"] == "ok" and s["no_first_tick"] == {"count": 2} and "big" not in s
    assert s["stale"] is False and "ui_api" in s
    assert b.status_code == 200 and b.json()["stale"] is True and b.json()["last_tick_age_s"] == 30.2
    assert d.status_code == 503 and "live status unavailable" in d.json()["detail"]["message"]


def test_status_is_single_flight_inside_2_s(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    ds.delay = 0.03

    async def go() -> None:
        await asyncio.gather(*(live.status_cache().get() for _ in range(5)))
        clock.t += 1.0
        await live.status_cache().get()
    run(go())
    assert ds.calls_to("/live/status") == 1


def test_a_failing_live_route_opens_only_its_own_breaker(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    ds.quotes_status = 500

    async def go() -> None:
        for _ in range(6):
            clock.t += 2.5
            await live.hub().quotes(["RELIANCE"])
    run(go())
    assert http_client.breaker_for(live.UPSTREAM).state() == "open"
    assert http_client.breaker_for(http_client.upstream_of(sup.DS + "/db/x")).state() == "closed"
    assert ds.calls_to("/live/quotes") == 5                     # the 6th never left: breaker open


def test_index_and_stock_symbol_normalisation() -> None:
    assert live.normalize_symbols("reliance.ns, M&M ,BAJAJ-AUTO,nifty   bank,India Vix,RELIANCE") == [
        "RELIANCE", "M&M", "BAJAJ-AUTO", "NIFTY BANK", "INDIA VIX"]
    for bad in ("^GSPC", "A.B", "BHEL.BO", "X" * 21, "", "NIFTY 50; DROP", "X " * 40):
        with pytest.raises(ValueError):
            live.normalize_symbols(bad)
    # data-service's canonical index names (live_ticks.canonical): both sides key the answer the same way
    assert live.normalize_symbols("^NSEI,NIFTY,BANKNIFTY,^INDIAVIX,NIFTY500 MULTICAP 50:25:25") == [
        "NIFTY 50", "NIFTY BANK", "INDIA VIX", "NIFTY500 MULTICAP 50:25:25"]
    assert live.is_stock_symbol("M&M") and not live.is_stock_symbol("NIFTY 50")


def test_clock_market_states() -> None:
    d = sup.NOW.replace
    assert live.clock_market(d(hour=9, minute=5))["state"] == "pre-open"
    assert live.clock_market(d(hour=15, minute=29))["state"] == "open"
    assert live.clock_market(d(hour=15, minute=30))["state"] == "closed"
    sat = live.clock_market(d(day=7, hour=11))
    assert (sat["state"], sat["session_date"]) == ("closed", "2026-11-06")
    early = live.clock_market(d(hour=8, minute=0))
    assert (early["state"], early["session_date"]) == ("closed", "2026-11-04")


def test_the_feed_block_passes_through_while_fresh(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    ds.raw_body = {"as_of": "x", "market": ds.market, "quotes": {"RELIANCE": ds.rows["RELIANCE"]},
                   "feed": {"breeze": "LIVE", "heartbeat_age_s": 0.1, "healthy": True, "nse_ok": True}}

    async def go() -> tuple[dict[str, Any], dict[str, Any]]:
        a = (await live.hub().quotes(["RELIANCE"])).payload
        ds.down = True
        clock.t += 5.0
        return a, (await live.hub().quotes(["RELIANCE"])).payload
    a, b = run(go())
    assert a["feed"] == {"breeze": "LIVE", "heartbeat_age_s": 0.1, "healthy": True, "nse_ok": True}
    assert b["feed"] is None                         # an old health block is not shown as current
