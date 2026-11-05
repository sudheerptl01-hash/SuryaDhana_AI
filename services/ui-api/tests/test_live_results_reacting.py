"""EVTS / BRF 'results reacting' (routers/markets.py) priced by the live NSE hub (L2-API, live NSE round 2): every filer
and the NIFTY 50 come from data-service /live/quotes (Breeze tick -> NSE website -> stored close) with source / state /
age on each row, never Yahoo and never the old heatmap + Yahoo pair; a change counts as TODAY's reaction only when the
row is live / delayed or the session's close dated today (a stale EOD row's change is the previous session's); an NSE
holiday shows no reaction; the pre-open auction rows say where they come from. The response keys the UI reads stay.
Negative control: the same fakes see a Yahoo call when the old path (news-scanner quotes under the rollback lever) is
used, so the zero below is not a blind tripwire."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
import pytest
import test_live_support as sup
from routers import markets
from routers import news_scanner as ns

LEGACY_ROW_KEYS = {"symbol", "filed_at", "change_pct", "typical_move_pct", "vs_nifty_pct", "vs_typical", "revenue_yoy",
                   "pat_yoy", "pat_turn", "quarter", "numbers", "reacts_next_session"}
LEGACY_TOP_KEYS = {"rows", "phase", "nifty_change_pct", "since", "as_of"}


class ReactingDataService(sup.FakeDataService):
    """The fake data-service plus the routes results-reacting reads (announcements, typical moves, financials, pre-open)."""

    def __init__(self) -> None:
        super().__init__()
        self.announcements: dict[str, list[dict[str, Any]]] = {"2026-11-04": [], "today": []}
        self.preopen: dict[str, Any] = {"timestamp": "", "rows": []}

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "data-service" and path in ("/db/announcements", "/db/typical-results-moves",
                                                           "/db/financials-latest", "/db/financials/prefetch",
                                                           "/db/preopen", "/db/live-quotes", "/db/nifty-live"):
            self.requests.append(request)
            if path == "/db/announcements":
                return httpx.Response(200, json={"items": self.announcements.get(request.url.params.get("day") or "today", [])})
            if path == "/db/typical-results-moves":
                return httpx.Response(200, json={"moves": {"AAA": {"typical_move_pct": 2.5, "quarters": 8}}})
            if path == "/db/financials-latest":
                return httpx.Response(200, json={"latest": {}})
            if path == "/db/financials/prefetch":
                return httpx.Response(200, json={"queued": 0})
            if path == "/db/preopen":
                return httpx.Response(200, json=self.preopen)
            return httpx.Response(500, json={"detail": "results-reacting must not read this any more"})
        return await super().handler(request)


def results(sym: str, at: str) -> dict[str, Any]:
    return {"symbol": sym, "category": "results", "time": at}


@pytest.fixture
def ds(monkeypatch: pytest.MonkeyPatch) -> ReactingDataService:
    fake = sup.install(monkeypatch, ReactingDataService())
    monkeypatch.setattr(markets, "DATA_SVC", sup.DS)
    markets._REACTING.invalidate()
    fake.announcements = {"2026-11-04": [results("AAA", "2026-11-04 16:48:00"), results("OLD", "2026-11-04 11:00:00")],
                          "today": [results("BBB", "2026-11-05 08:15:00"), results("DDD", "2026-11-05 07:00:00"),
                                    results("EEE", "2026-11-05 07:30:00"), results("FFF", "2026-11-05 08:00:00")]}
    fake.rows = {"AAA": sup.row(812.0, change_pct=5.0),
                 "BBB": sup.row(410.0, state="delayed", source="nse_api", age_s=48.0, change_pct=-3.0),
                 "DDD": sup.row(99.0, state="stale", source="eod", age_s=None, ltt=None, change_pct=2.0, date="2026-11-04",
                                reason="no live source answered; last close 2026-11-04"),
                 "FFF": sup.row(55.0, state="closed", source="eod", age_s=None, ltt=None, change_pct=1.5, date="2026-11-04"),
                 "NIFTY 50": sup.row(24010.0, change_pct=0.5)}
    return fake


@pytest.fixture
def yahoo(monkeypatch: pytest.MonkeyPatch) -> sup.YahooSpy:
    return sup.spy_yahoo(monkeypatch)


def at(h: int, m: int, s: int = 0, day: int = 5) -> datetime:
    return datetime(2026, 11, day, h, m, s)  # noqa: DTZ001 — the naive local (IST) wall clock the route reads


def react(monkeypatch: pytest.MonkeyPatch, now: datetime) -> dict[str, Any]:
    monkeypatch.setattr(markets, "_react_now", lambda: now)
    return asyncio.run(markets._results_reacting())


def test_session_rows_are_priced_by_the_live_hub_with_source_state_and_age(ds: ReactingDataService, yahoo: sup.YahooSpy,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    out = react(monkeypatch, at(11, 0))
    rows = {r["symbol"]: r for r in out["rows"]}
    assert set(rows) == {"AAA", "BBB", "DDD", "EEE", "FFF"}                    # OLD filed before the close: priced in
    assert LEGACY_TOP_KEYS <= set(out) and all(LEGACY_ROW_KEYS <= set(r) for r in out["rows"])
    a, b, d, e, f = (rows[k] for k in ("AAA", "BBB", "DDD", "EEE", "FFF"))
    assert (a["change_pct"], a["source"], a["state"], a["age_s"]) == (5.0, "breeze_ws", "live", 0.6)
    assert a["vs_typical"] == 2.0 and a["vs_nifty_pct"] == 4.5 and out["nifty_change_pct"] == 0.5
    assert (b["change_pct"], b["source"], b["state"], b["age_s"]) == (-3.0, "nse_api", "delayed", 48.0)
    # a stale EOD close carries YESTERDAY's change: never shown as today's reaction, and it says why
    assert (d["change_pct"], d["state"], d["source"]) == (None, "stale", "eod") and "last close" in d["reason"]
    assert (e["change_pct"], e["state"], e["source"]) == (None, "unavailable", None) and e["reason"]
    assert f["change_pct"] is None and f["state"] == "closed"                  # a close of another session
    assert out["nifty"]["source"] == "breeze_ws" and out["market"]["state"] == "open"
    assert out["price_source"] == {"sources": {"breeze_ws": 1, "nse_api": 1, "eod": 2, "none": 1}, "max_age_s": 48.0}
    # one hub read for every filer + the index; never Yahoo, never the old heatmap / nifty-live reads
    assert ds.quote_calls() == [["AAA", "BBB", "DDD", "EEE", "FFF", "NIFTY 50"]]
    assert yahoo.calls == [] and ds.foreign == []
    assert ds.calls_to("/db/live-quotes") == 0 and ds.calls_to("/db/nifty-live") == 0


def test_negative_control_the_old_quote_path_reaches_yahoo_under_the_rollback_lever(ds: ReactingDataService,
                                                                                   yahoo: sup.YahooSpy,
                                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """results-reacting used to price non-heatmap filers through news-scanner quotes, which LIVE_QUOTES_NSE=0 sends to
    Yahoo; the spy sees that path. results-reacting itself never reaches Yahoo, lever or not."""
    monkeypatch.setenv("LIVE_QUOTES_NSE", "0")
    asyncio.run(ns.get_quotes(symbols="EEE.NS"))
    assert yahoo.calls == ["EEE.NS"]
    yahoo.calls.clear()
    out = react(monkeypatch, at(11, 0))
    assert yahoo.calls == [] and {r["symbol"]: r["source"] for r in out["rows"]}["AAA"] == "breeze_ws"


def test_after_the_close_todays_close_counts_and_a_late_filing_reacts_next_session(ds: ReactingDataService,
                                                                                 yahoo: sup.YahooSpy,
                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    ds.market = {"state": "closed", "session_date": "2026-11-05"}
    ds.announcements["today"].append(results("LATE", "2026-11-05 15:45:00"))
    ds.rows.update({"AAA": sup.row(812.0, state="closed", change_pct=5.0, ltt="2026-11-05T15:29:59+05:30"),
                    "LATE": sup.row(70.0, state="closed", change_pct=-1.0, ltt="2026-11-05T15:29:58+05:30")})
    out = react(monkeypatch, at(16, 30))
    rows = {r["symbol"]: r for r in out["rows"]}
    assert out["phase"] == "session" and rows["AAA"]["change_pct"] == 5.0 and rows["AAA"]["state"] == "closed"
    assert rows["LATE"]["change_pct"] is None and rows["LATE"]["reacts_next_session"] is True
    assert rows["FFF"]["change_pct"] is None                                   # closed, but dated 4 Nov


def test_an_nse_holiday_shows_no_reaction(ds: ReactingDataService, yahoo: sup.YahooSpy,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    ds.market = {"state": "closed", "session_date": "2026-11-04"}            # data-service's holiday master
    ds.rows["AAA"] = sup.row(812.0, state="closed", change_pct=5.0, ltt="2026-11-04T15:29:59+05:30")
    out = react(monkeypatch, at(11, 0))
    assert out["phase"] == "closed" and out["nifty_change_pct"] is None
    assert all(r["change_pct"] is None and "no NSE session today" in r["reason"] for r in out["rows"])


def test_pre_open_rows_say_they_are_the_nse_auction_price(ds: ReactingDataService, yahoo: sup.YahooSpy,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    ds.preopen = {"timestamp": "05-Nov-2026 09:04:30", "rows": [{"symbol": "AAA", "change_pct": 4.2},
                                                                {"symbol": "ZZZ", "change_pct": 9.0}]}
    out = react(monkeypatch, at(9, 5))
    rows = {r["symbol"]: r for r in out["rows"]}
    assert out["phase"] == "preopen" and rows["AAA"]["change_pct"] == 4.2
    assert (rows["AAA"]["source"], rows["AAA"]["state"], rows["AAA"]["age_s"]) == ("nse_api", "delayed", 30.0)
    assert "pre-open auction" in rows["AAA"]["reason"] and rows["AAA"]["ltt"] == "2026-11-05T09:04:30+05:30"
    assert rows["BBB"]["change_pct"] is None and rows["BBB"]["source"] is None
    assert ds.quote_calls() == [] and yahoo.calls == []                       # no hub read before the session
    later = react(monkeypatch, at(9, 12))
    assert {r["symbol"]: r for r in later["rows"]}["AAA"]["state"] == "stale"   # past 90 s: the label ages honestly


def test_before_the_pre_open_nothing_is_priced(ds: ReactingDataService, yahoo: sup.YahooSpy,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    out = react(monkeypatch, at(8, 30))
    assert out["phase"] == "closed" and all(r["change_pct"] is None and r["source"] is None for r in out["rows"])
    assert ds.quote_calls() == [] and ds.calls_to("/db/preopen") == 0


@pytest.mark.parametrize(("row", "expected"), [
    ({"state": "live", "price": 1.0, "change_pct": 2.0, "ltt": "2026-11-05T11:00:00+05:30"}, 2.0),
    ({"state": "delayed", "price": 1.0, "change_pct": -1.5}, -1.5),                       # no date: the session's
    ({"state": "closed", "price": 1.0, "change_pct": 1.0, "date": "2026-11-05"}, 1.0),
    ({"state": "closed", "price": 1.0, "change_pct": 1.0}, None),                         # a close needs its date
    ({"state": "closed", "price": 1.0, "change_pct": 1.0, "date": "2026-11-04"}, None),
    ({"state": "live", "price": 1.0, "change_pct": 1.0, "ltt": "2026-11-04T15:29:59+05:30"}, None),
    ({"state": "stale", "price": 1.0, "change_pct": 1.0, "date": "2026-11-05"}, None),
    ({"state": "unavailable", "price": None, "change_pct": None}, None),
    ({"state": "live", "price": 1.0, "change_pct": float("nan")}, None),
    ({"state": "live", "price": 1.0, "change_pct": True}, None),
    (None, None),
], ids=["live", "delayed-undated", "close-today", "close-undated", "close-yesterday", "live-yesterday", "stale",
        "unavailable", "nan", "bool", "none"])
def test_todays_move(row: Any, expected: float | None) -> None:
    assert markets.todays_move(row, "2026-11-05") == expected
