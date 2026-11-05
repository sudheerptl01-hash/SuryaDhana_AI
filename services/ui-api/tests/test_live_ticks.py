"""GET /api/quotes/ticks (routers/quotes.py) on the live NSE hub (LV-API): an NSE symbol is never priced from Yahoo (the
inventory's defect D4: Yahoo rows in this map overwrote the stock window's broker price), only prices a consumer may
paint over its own base layer are in the map (live / delayed / closed), every row says its state and age, the B4 wire
key stays `ticks`, and the feed state comes from /live/status (UNREACHABLE when it cannot be read)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
import test_live_support as sup
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import live, quotes


@pytest.fixture
def ds(monkeypatch: pytest.MonkeyPatch) -> sup.FakeDataService:
    fake = sup.install(monkeypatch)
    fake.rows = {"RELIANCE": sup.row(1311.0, change_pct=1.0, prev_close=1298.0),
                 "TCS": sup.row(3050.0, state="delayed", source="nse_api", age_s=49.0),
                 "INFY": sup.row(1490.0, state="stale", source="eod", age_s=None),
                 "HDFCBANK": sup.row(1702.0, state="closed", source="eod", age_s=None, hint="possible corporate action")}
    return fake


@pytest.fixture
def yahoo(monkeypatch: pytest.MonkeyPatch) -> sup.YahooSpy:
    return sup.spy_yahoo(monkeypatch)


def run(symbols: str) -> dict[str, Any]:
    return asyncio.run(quotes.live_quotes(symbols=symbols))


def test_breeze_nse_and_close_rows_overlay_stale_and_missing_rows_do_not(ds: sup.FakeDataService,
                                                                         yahoo: sup.YahooSpy) -> None:
    out = run("RELIANCE.NS,TCS,INFY,HDFCBANK,WIPRO")
    assert out["connected"] is True and out["state"] == "LIVE" and out["market"]["state"] == "open"
    t = out["ticks"]
    assert set(t) == {"RELIANCE", "TCS", "HDFCBANK"}
    assert t["RELIANCE"] == {"price": 1311.0, "chg_pct": 1.0, "prev_close": 1298.0, "ttq": 1_234_567,
                             "as_of": "2026-11-05T10:59:59+05:30", "source": "icici-ws", "feed": "breeze_ws",
                             "state": "live", "age_s": 0.6, "ltt": "2026-11-05T10:59:59+05:30"}
    assert (t["TCS"]["source"], t["TCS"]["state"], t["TCS"]["age_s"]) == ("nse_api", "delayed", 49.0)
    assert t["HDFCBANK"]["state"] == "closed" and t["HDFCBANK"]["hint"] == "possible corporate action"
    assert yahoo.calls == [] and ds.foreign == []


def test_negative_control_the_left_out_rows_exist_upstream(ds: sup.FakeDataService) -> None:
    """INFY (stale) and WIPRO (unavailable) are absent from the overlay by decision, not for lack of data: the same hub
    answers them on /api/live/quotes with their states."""
    run("INFY,WIPRO")
    snap = asyncio.run(live.hub().quotes(["INFY", "WIPRO"]))
    assert snap.payload["quotes"]["INFY"]["state"] == "stale" and snap.payload["quotes"]["INFY"]["price"] == 1490.0
    assert snap.payload["quotes"]["WIPRO"]["state"] == "unavailable"


def test_status_unreachable_keeps_the_prices(ds: sup.FakeDataService) -> None:
    ds.status_status = 500
    out = run("RELIANCE")
    assert out["state"] == "UNREACHABLE" and out["connected"] is False and out["ticks"]["RELIANCE"]["price"] == 1311.0


def test_engine_off_reads_off_and_nse_rows_still_overlay(ds: sup.FakeDataService) -> None:
    ds.status = {**ds.status, "state": "OFF"}
    ds.rows["RELIANCE"] = sup.row(1310.0, state="delayed", source="nse_api", age_s=55.0)
    out = run("RELIANCE")
    assert (out["state"], out["connected"]) == ("OFF", False)
    assert out["ticks"]["RELIANCE"]["source"] == "nse_api" and out["ticks"]["RELIANCE"]["state"] == "delayed"


def test_data_service_down_leaves_the_map_empty_never_yahoo(ds: sup.FakeDataService, yahoo: sup.YahooSpy) -> None:
    ds.down = True
    out = run("RELIANCE,TCS")
    assert out["ticks"] == {} and out["state"] == "UNREACHABLE" and yahoo.calls == []


def test_wire_key_is_ticks_not_quotes(ds: sup.FakeDataService) -> None:
    """Pin the B4 wire contract: ui/lib/liveTicks.ts parses `data.ticks` (bloomberg_verdict defect #1). Never rename."""
    out = run("TCS")
    assert "ticks" in out and "quotes" not in out


def test_tolerant_symbols_and_the_300_cap(ds: sup.FakeDataService) -> None:
    out = run("tcs.ns,,BAD SYM!,TCS,^GSPC")
    assert set(out["ticks"]) == {"TCS"} and ds.quote_calls() == [["TCS"]]
    many = ",".join(f"S{i}" for i in range(400))
    run(many)
    assert len(ds.quote_calls()[-1]) == 300
    empty = run("^GSPC,BAD SYM!")
    assert empty["ticks"] == {} and empty["market"] is None


def test_both_paths_over_http_share_one_handler_and_the_cache(ds: sup.FakeDataService) -> None:
    app = FastAPI()
    app.include_router(quotes.router, prefix="/api/quotes")
    with TestClient(app, base_url="http://127.0.0.1:8010") as c:
        a = c.get("/api/quotes/ticks", params={"symbols": "RELIANCE"})
        b = c.get("/api/quotes/live", params={"symbols": "RELIANCE"})
    assert a.status_code == b.status_code == 200
    assert a.json()["ticks"]["RELIANCE"]["price"] == b.json()["ticks"]["RELIANCE"]["price"] == 1311.0
    assert len(ds.quote_calls()) == 1 and b.headers["x-cache"] == "hit"


def test_a_close_is_dated_by_its_session(ds: sup.FakeDataService) -> None:
    ds.rows["HDFCBANK"] = sup.row(1702.0, state="closed", source="eod", age_s=None, ltt=None, date="2026-11-04")
    t = run("HDFCBANK")["ticks"]["HDFCBANK"]
    assert t["as_of"] == "2026-11-04T15:30:00+05:30" and t["ltt"] is None and t["state"] == "closed"
