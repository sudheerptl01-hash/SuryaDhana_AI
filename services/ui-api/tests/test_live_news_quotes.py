"""/api/news-scanner/quotes for '.NS' symbols answers from the live NSE hub (LV-API): ZERO Yahoo calls for an NSE stock
under a fake transport (every client in the process is routed through it), the body keys the hover card / WTCH / ALRT /
BRF / BRKR / the news dock read are kept (+ source, state, age_s, ltt), the stored EOD context fills the spark and the
52-week range, every fallback state stays honest, and a DECIDING read (price alerts) never acts on a stale price."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
import test_live_support as sup
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import alerts, live
from routers import news_scanner as ns


@pytest.fixture
def clock() -> sup.Clock:
    return sup.Clock()


@pytest.fixture
def ds(monkeypatch: pytest.MonkeyPatch, clock: sup.Clock) -> sup.FakeDataService:
    fake = sup.install(monkeypatch, clock=clock)
    fake.rows = {"RELIANCE": sup.row(1311.0, change_pct=1.0, prev_close=1298.0, name="RELIANCE INDUSTRIES"),
                 "TCS": sup.row(3050.0, state="delayed", source="nse_api", age_s=49.0),
                 "INFY": sup.row(1490.0, state="stale", source="eod", age_s=None, ltt="2026-11-04T15:29:59+05:30")}
    fake.histories = {"RELIANCE": sup.history("RELIANCE", [1298.0, 1290.0, 1280.0, 1270.0], high=1611.8, low=1152.2)}
    return fake


@pytest.fixture
def yahoo(monkeypatch: pytest.MonkeyPatch) -> sup.YahooSpy:
    return sup.spy_yahoo(monkeypatch)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def legacy_keys() -> set[str]:
    """The keys the Yahoo path has always put on an available quote (derived from the code, not retyped)."""
    chart = run(sup.YahooSpy()("X", "1mo", "1d"))
    return set(ns._quote_from(chart, ns._candles(chart))) | {"available", "resolved_symbol", "spark"}


def test_ns_symbols_make_zero_yahoo_calls_and_keep_every_body_key(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    out = run(ns.get_quotes(symbols="RELIANCE.NS,TCS.NS,^GSPC"))
    assert set(out) == {"quotes", "as_of"} and list(out["quotes"]) == ["RELIANCE.NS", "TCS.NS", "^GSPC"]
    assert yahoo.calls == ["^GSPC"]                                         # the US index only
    assert ds.foreign == []                                                 # nothing else left for any outside host
    rel = out["quotes"]["RELIANCE.NS"]
    assert legacy_keys() <= set(rel), legacy_keys() - set(rel)
    assert {"source", "state", "age_s", "ltt"} <= set(rel)
    assert (rel["price"], rel["change_pct"], rel["prev_close"], rel["available"]) == (1311.0, 1.0, 1298.0, True)
    assert (rel["source"], rel["state"], rel["age_s"], rel["currency"], rel["exchange"]) == ("breeze_ws", "live", 0.6, "INR", "NSE")
    assert rel["name"] == "RELIANCE INDUSTRIES" and rel["resolved_symbol"] == "RELIANCE.NS" and rel["stale"] is False
    assert rel["market_date"] == "2026-11-05" and rel["prev_date"] == "2026-11-04" and rel["prev_source"] == "NSE"
    assert rel["market_time"] == int(sup.NOW.timestamp()) - 1
    tcs = out["quotes"]["TCS.NS"]
    assert (tcs["source"], tcs["state"], tcs["age_s"], tcs["available"]) == ("nse_api", "delayed", 49.0, True)
    gspc = out["quotes"]["^GSPC"]
    assert gspc["source"] == "yahoo" and gspc["state"] == "delayed" and gspc["available"] is True


def test_negative_control_the_kill_switch_puts_ns_back_on_yahoo(ds: sup.FakeDataService, yahoo: sup.YahooSpy,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """LIVE_QUOTES_NSE=0 (the rollback lever) is the old path: the spy sees the NSE stock, so the test above can see a
    Yahoo call for one."""
    monkeypatch.setenv("LIVE_QUOTES_NSE", "0")
    out = run(ns.get_quotes(symbols="RELIANCE.NS"))
    assert yahoo.calls == ["RELIANCE.NS"] and out["quotes"]["RELIANCE.NS"]["source"] == "yahoo"
    assert ds.quote_calls() == []


def test_spark_and_52_week_range_come_from_the_stored_bhavcopy(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    # a 1:1 bonus on 3 Nov (row index 1 = 2026-11-03 carries action_k 0.5): older closes are halved, no fake crash
    ds.histories["RELIANCE"] = sup.history("RELIANCE", [1298.0, 1290.0, 2560.0, 2540.0], action_k={1: 0.5},
                                           high=1400.0, low=1200.0)
    rel = run(ns.get_quotes(symbols="RELIANCE.NS"))["quotes"]["RELIANCE.NS"]
    assert rel["spark"] == [1270.0, 1280.0, 1290.0, 1298.0, 1311.0]          # oldest first, today's live point last
    assert rel["eod_as_of"] == "2026-11-04"
    assert rel["high_52w"] == 1400.0 and rel["low_52w"] == 1200.0
    assert ds.calls_to("/db/security/RELIANCE/history") == 1 and yahoo.calls == []
    run(ns.get_quotes(symbols="RELIANCE.NS"))
    assert ds.calls_to("/db/security/RELIANCE/history") == 1                 # cached (EOD data change once a day)


def test_the_live_day_range_widens_the_stored_52_week_range(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    ds.rows["RELIANCE"] = sup.row(1700.0, change_pct=2.0, day_high=1720.0, day_low=1650.0)
    rel = run(ns.get_quotes(symbols="RELIANCE.NS"))["quotes"]["RELIANCE.NS"]
    assert rel["high_52w"] == 1720.0 and rel["low_52w"] == 1152.2


def test_a_failing_context_never_blocks_the_price(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    ds.history_status = 500
    rel = run(ns.get_quotes(symbols="RELIANCE.NS"))["quotes"]["RELIANCE.NS"]
    assert rel["price"] == 1311.0 and rel["available"] is True and rel["spark"] == [] and rel["eod_as_of"] is None
    assert rel["high_52w"] == rel["day_high"] and yahoo.calls == []


def test_a_slow_context_is_not_waited_for(ds: sup.FakeDataService, yahoo: sup.YahooSpy,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "CTX_WAIT_S", 0.01)
    real = ds.handler

    async def slow_history(request: Any) -> Any:
        if "/history" in request.url.path:
            await asyncio.sleep(0.2)
        return await real(request)
    monkeypatch.setattr(ds, "handler", slow_history)
    sup.install(monkeypatch, ds)              # re-route the clients through the slow handler
    rel = run(ns.get_quotes(symbols="RELIANCE.NS"))["quotes"]["RELIANCE.NS"]
    assert rel["price"] == 1311.0 and rel["spark"] == []


def test_fallback_states_stay_honest_and_never_reach_yahoo(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    out = run(ns.get_quotes(symbols="INFY.NS,WIPRO.NS"))["quotes"]
    infy, wipro = out["INFY.NS"], out["WIPRO.NS"]
    # an EOD close during the session: shown, labelled stale, dated by its own ltt
    assert (infy["available"], infy["state"], infy["stale"], infy["source"]) == (True, "stale", True, "eod")
    assert infy["market_date"] == "2026-11-04"
    # data-service has nothing for it: not available, with the reason, never a Yahoo price
    assert wipro == {"symbol": "WIPRO.NS", "available": False, "source": None, "state": "unavailable", "age_s": None,
                     "ltt": None, "reason": "not in the data-service answer"}
    ds.down = True
    live.hub().reset()
    down = run(ns.get_quotes(symbols="RELIANCE.NS"))["quotes"]["RELIANCE.NS"]
    assert down["available"] is False and down["state"] == "unavailable" and "ConnectError" in down["reason"]
    assert yahoo.calls == [] and ds.foreign == []


def test_a_deciding_read_never_gets_a_stale_price(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    out = run(ns.get_quotes(symbols="RELIANCE.NS,TCS.NS,INFY.NS", fresh=True))["quotes"]
    assert out["RELIANCE.NS"]["available"] and out["TCS.NS"]["available"]          # live, delayed
    assert out["INFY.NS"]["available"] is False and out["INFY.NS"]["state"] == "stale"


def test_the_price_alert_check_prices_nse_stocks_from_the_live_hub(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    alerts._write({"alerts": {"RELIANCE": {"above": 1300.0, "yahoo": "RELIANCE.NS"},
                              "INFY": {"below": 1500.0, "yahoo": "INFY.NS"}}, "history": []})
    res = run(alerts.run_alerts())
    assert [(h["sym"], h["side"], h["price"]) for h in res["hits"]] == [("RELIANCE", "above", 1311.0)]
    assert res["priced"] == 1                          # INFY's EOD close (stale in session) is not acted on
    assert yahoo.calls == [] and ds.foreign == []


def test_index_and_odd_symbols(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    out = run(ns.get_quotes(symbols="^NSEI,A=B.NS,BHEL.BO"))["quotes"]
    assert yahoo.calls == ["^NSEI", "BHEL.BO"]                        # not '.NS': the Yahoo path, as before
    assert out["A=B.NS"]["available"] is False and out["A=B.NS"]["reason"] == "not an NSE symbol"
    assert ds.quote_calls() == []


def test_over_http_the_body_shape_and_cache_headers(ds: sup.FakeDataService, yahoo: sup.YahooSpy, clock: sup.Clock) -> None:
    app = FastAPI()
    app.include_router(ns.router, prefix="/api/news-scanner")
    with TestClient(app, base_url="http://127.0.0.1:8010") as c:
        a = c.get("/api/news-scanner/quotes", params={"symbols": "RELIANCE.NS"})
        clock.t += 1.0
        b = c.get("/api/news-scanner/quotes", params={"symbols": "RELIANCE.NS"})
    assert set(a.json()) == {"quotes", "as_of"} and a.headers["x-cache"] == "miss"
    assert b.headers["x-cache"] == "hit" and b.headers["x-cache-age"] == "1"
    assert b.json()["quotes"]["RELIANCE.NS"]["age_s"] == 1.6            # the 1 s in ui-api's cache is in the age
    assert len(ds.quote_calls()) == 1 and yahoo.calls == []


def test_news_row_computes_change_when_the_row_has_only_prev_close() -> None:
    r = live.news_row("X", {"price": 110.0, "prev_close": 100.0, "state": "live", "source": "breeze_ws", "age_s": 1.0,
                            "ltt": None}, None, {"state": "open", "session_date": "2026-11-05"})
    assert r["change"] == 10.0 and r["change_pct"] == 10.0 and r["market_date"] == "2026-11-05"
    assert r["spark"] == [] and r["high_52w"] is None and r["market_time"] is None


def test_an_eod_row_is_dated_by_its_own_session_not_today(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    """data-service's EOD rows carry no ltt but their ``date``: the hover card must say 4 Nov, not today."""
    ds.rows["INFY"] = sup.row(1490.0, state="stale", source="eod", age_s=70_000.0, ltt=None, date="2026-11-04",
                              reason="no live source answered; last close 2026-11-04")
    q = run(ns.get_quotes(symbols="INFY.NS"))["quotes"]["INFY.NS"]
    assert (q["market_date"], q["market_time"], q["stale"]) == ("2026-11-04", None, True)
    assert q["reason"] == "no live source answered; last close 2026-11-04" and yahoo.calls == []
