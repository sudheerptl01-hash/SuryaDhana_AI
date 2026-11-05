"""GET /api/market/closes (routers/markets.py; L2-API, live NSE round 2): NSE's stored daily closes for history panes
(COMP, sparks) from data-service /db/closes, in one read, behind a 10-minute SWR cache. The contract body {as_of,
source: 'nse_bhavcopy', series: {SYM: [{date, close}]}} plus meta / missing / aliases; request order kept; Yahoo-style
index tickers answered under the NSE name; invalid requests refused before any upstream call; malformed upstream rows
dropped; a missing route is a 503 with a deploy hint; the body never claims to be live; never Yahoo."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
import test_live_support as sup
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import markets


@pytest.fixture
def clock() -> sup.Clock:
    return sup.Clock()


@pytest.fixture
def ds(monkeypatch: pytest.MonkeyPatch, clock: sup.Clock) -> sup.FakeDataService:
    fake = sup.install(monkeypatch, clock=clock)
    fake.closes = {"TCS": sup.closes([3000.0, 3010.0, 3050.0], name="Tata Consultancy Services Limited", high=3100.0, low=2900.0),
                   "INFY": sup.closes([1480.0, 1490.0]),
                   "NIFTY 50": sup.closes([23900.0, 24010.0], source="nse_index_file", name="NIFTY 50")}
    monkeypatch.setattr(markets._CLOSES, "_clock", clock)
    markets._CLOSES.invalidate()
    return fake


@pytest.fixture
def client(ds: sup.FakeDataService) -> Any:
    app = FastAPI()
    app.include_router(markets.router, prefix="/api/market")
    with TestClient(app, base_url="http://127.0.0.1:8010") as c:
        yield c


def test_contract_body_request_order_aliases_and_missing(client: Any, ds: sup.FakeDataService) -> None:
    r = client.get("/api/market/closes", params={"symbols": "infy.ns,TCS,^NSEI,NOPE", "days": 366})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"as_of", "source", "series"} <= set(body) and body["source"] == "nse_bhavcopy"
    assert list(body["series"]) == ["INFY", "TCS", "NIFTY 50"]                 # request order, canonical NSE names
    assert body["series"]["TCS"] == [{"date": "2026-11-02", "close": 3000.0}, {"date": "2026-11-03", "close": 3010.0},
                                     {"date": "2026-11-04", "close": 3050.0}]
    assert body["as_of"] == "2026-11-04"                                      # the newest stored session, a date
    assert body["meta"]["TCS"]["name"] == "Tata Consultancy Services Limited" and body["meta"]["TCS"]["high"] == 3100.0
    assert body["meta"]["NIFTY 50"]["source"] == "nse_index_file"
    assert body["aliases"] == {"infy.ns": "INFY", "^NSEI": "NIFTY 50"}
    assert set(body["missing"]) == {"NOPE"} and "bhavcopy" in body["missing"]["NOPE"]
    assert "never live" in body["note"] and "live" not in {str(m.get("source")) for m in body["meta"].values()}
    assert ds.closes_calls() == [["INFY", "NIFTY 50", "NOPE", "TCS"]] and ds.foreign == []
    req = next(x for x in ds.requests if x.url.path == "/db/closes")
    assert req.url.params["days"] == "366" and "tail" not in req.url.params


def test_one_read_per_ten_minutes_then_a_background_refresh(client: Any, ds: sup.FakeDataService, clock: sup.Clock) -> None:
    q = {"symbols": "TCS,INFY", "days": 92}
    a = client.get("/api/market/closes", params=q)
    clock.t += 60
    b = client.get("/api/market/closes", params={"symbols": "INFY,TCS", "days": 92})   # same set, other order: one key
    assert a.headers["x-cache"] == "miss" and b.headers["x-cache"] == "hit" and b.headers["x-cache-age"] == "60"
    assert list(b.json()["series"]) == ["INFY", "TCS"] and len(ds.closes_calls()) == 1
    clock.t += markets.CLOSES_REFRESH_S
    c = client.get("/api/market/closes", params=q)
    assert c.headers["x-cache"] == "stale"                                     # served at once, refreshed behind
    for _ in range(200):                                                       # the refresh runs on the app's loop
        if len(ds.closes_calls()) == 2:
            break
        time.sleep(0.005)
    assert len(ds.closes_calls()) == 2
    clock.t += markets.CLOSES_MAX_AGE_S + 1
    ds.closes["TCS"] = sup.closes([3000.0, 3010.0, 3050.0, 3075.0], last_day=5)
    d = client.get("/api/market/closes", params=q)
    assert d.headers["x-cache"] == "miss" and d.json()["series"]["TCS"][-1] == {"date": "2026-11-05", "close": 3075.0}


def test_tail_is_passed_through(client: Any, ds: sup.FakeDataService) -> None:
    body = client.get("/api/market/closes", params={"symbols": "TCS", "days": 366, "tail": 2}).json()
    assert [p["close"] for p in body["series"]["TCS"]] == [3010.0, 3050.0] and body["tail"] == 2


@pytest.mark.parametrize(("params", "needle"), [
    ({"symbols": "TCS,DROP TABLE;"}, "invalid NSE symbol"),
    ({"symbols": "AAPL.US"}, "invalid NSE symbol"),
    ({"symbols": ",".join(f"S{i}" for i in range(301))}, "at most 300"),
    ({"symbols": ",".join(f"S{i}" for i in range(40)), "days": 3700}, "symbol-day budget"),
], ids=["bad-symbol", "not-nse", "over-300", "over-budget"])
def test_bad_requests_are_422_without_an_upstream_call(client: Any, ds: sup.FakeDataService, params: dict[str, Any],
                                                       needle: str) -> None:
    r = client.get("/api/market/closes", params=params)
    assert r.status_code == 422 and needle in r.text and ds.closes_calls() == []


def test_upstream_failures_are_structured_and_never_fall_back(client: Any, ds: sup.FakeDataService) -> None:
    ds.closes_status = 404
    r = client.get("/api/market/closes", params={"symbols": "TCS"})
    assert r.status_code == 503 and "deploy data-service" in r.text and ds.foreign == []
    ds.closes_status = 500
    r = client.get("/api/market/closes", params={"symbols": "INFY"})
    err = r.json().get("error") or r.json()["detail"]                        # the app's handler adds "error" (errors.py)
    assert r.status_code == 503 and err["code"] == "upstream_down"


def test_malformed_upstream_rows_are_dropped() -> None:
    body = {"series": {"TCS": [{"date": "2026-11-03", "close": 3010.0}, {"date": "bad", "close": 1.0},
                               {"date": "2026-11-02", "close": -5}, {"date": "2026-11-01", "close": "nan"},
                               {"date": "2026-11-04", "close": 3050.0}, "junk"],
                       "INFY": "not a list"},
            "meta": {"TCS": {"name": "x" * 500, "high": 3100.0, "evil": {"nested": 1}}}}
    out = markets.coerce_closes(body, ["TCS", "INFY"])
    assert out["series"] == {"TCS": [{"date": "2026-11-03", "close": 3010.0}, {"date": "2026-11-04", "close": 3050.0}]}
    assert out["meta"]["TCS"] == {"high": 3100.0, "last_date": "2026-11-04"}          # long name and unknown keys dropped
    assert out["missing"] == {"INFY": "not in the data-service answer"}
    with pytest.raises(markets._UpstreamError):
        markets.coerce_closes({"quotes": {}}, ["TCS"])


def test_the_route_reaches_no_yahoo_fetcher() -> None:
    """Static: nothing /api/market/closes calls talks to Yahoo (the live-gates call graph covers it too)."""
    import inspect
    src = inspect.getsource(markets.market_closes) + inspect.getsource(markets._fetch_closes) + \
        inspect.getsource(markets.coerce_closes)
    assert "finance.yahoo" not in src and "_yahoo" not in src and "news_scanner" not in src and "/db/closes" in src


def test_concurrent_identical_requests_share_one_read(ds: sup.FakeDataService) -> None:
    async def go() -> list[dict[str, Any]]:
        from starlette.responses import Response
        return list(await asyncio.gather(*(markets.market_closes(Response(), symbols="TCS,INFY", days=31, tail=None)
                                           for _ in range(5))))
    out = asyncio.run(go())
    assert len(ds.closes_calls()) == 1 and all(o["series"] == out[0]["series"] for o in out)
