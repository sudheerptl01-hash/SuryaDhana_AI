"""Gold Pre-Open desk: MCX baseline, contract mapping, reference window, fair open, verdict."""
import asyncio
import json
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
import routers.gold_preopen as g

HEADER = ('"Token","InstrumentName","ShortName","Series","CompanyName","TickSize","LotSize","ExpiryDate","OptionType",'
          '"StrikePrice","StartDate","EndDate","ExpiryMonth","MarketLot","MarginPercentage","LowerCktLimit","UpperCktLimit",'
          '"OpenInterest","LifeTimeLow","LifeTimeHigh","LowPriceRange","HighPriceRange","QuantityUnit","PriceUnit",'
          '"DeliveryUnit","Exchange","ExchangeCode"\n')
ROWS = ('"495213","FUTSTK","GOLD","FUTURE","GOLD",100,1,"04-Dec-2026","XX",0,"","","","",16574,"","","","","",144630,153576,"KGS","RS/10GRMS","KGS","","GOLD"\n'
        '"559933","FUTSTK","GOLD","FUTURE","GOLD",100,1,"05-Feb-2027","XX",0,"","","","",519,"","","","","",146640,155710,"KGS","RS/10GRMS","KGS","","GOLD"\n'
        '"580006","OPTSTK","GOLD","OPTION","GOLD",50,1,"30-Oct-2026","CE",116500,"","","","",0,"","","","","",6049.5,59227,"KGS","RS/10GRMS","KGS","","GOLD"\n'
        '"111","FUTSTK","GOLDM","FUTURE","GOLDM",100,1,"05-Nov-2026","XX",0,"","","","",900,"","","","","",1,2,"KGS","RS/10GRMS","KGS","","GOLDM"\n')
IST = g.IST


def test_settlement_is_the_band_midpoint_and_options_are_ignored():
    c = g.parse_mcx_gold(HEADER + ROWS)
    assert [x["expiry"] for x in c] == [date(2026, 12, 4), date(2027, 2, 5)]
    assert c[0]["settlement"] == 149103.0 and c[0]["band_pct"] == 3.0
    assert c[0]["open_interest"] == 16574


def test_the_traded_contract_is_picked_and_rolled_before_expiry():
    c = g.parse_mcx_gold(HEADER + ROWS)
    assert g.pick_contract(c, date(2026, 10, 9))["expiry"] == date(2026, 12, 4)
    assert g.pick_contract(c, date(2026, 12, 1))["expiry"] == date(2027, 2, 5)     # Dec is in expiry week


def test_comex_month_matches_mcx_month():
    assert g.comex_symbol(date(2026, 12, 4)) == "GCZ26.CMX"
    assert g.comex_symbol(date(2027, 2, 5)) == "GCG27.CMX"


def test_mcx_close_follows_us_daylight_time():
    assert g.mcx_close_time(date(2026, 10, 8)).strftime("%H:%M") == "23:30"
    assert g.mcx_close_time(date(2026, 12, 1)).strftime("%H:%M") == "23:55"


def test_previous_session_skips_weekends():
    assert g.previous_session(date(2026, 10, 12)) == date(2026, 10, 9)        # Monday → Friday
    assert g.previous_session(date(2026, 10, 9)) == date(2026, 10, 8)


def test_reference_is_the_last_30_minutes_or_the_last_print():
    close = datetime(2026, 10, 8, 23, 30, tzinfo=IST)
    bars = [(close - timedelta(minutes=m), v) for m, v in ((40, 100.0), (25, 110.0), (5, 120.0))] + [(close, 999.0)]
    value, how = g.reference_price(sorted(bars), close)
    assert value == 115.0 and "2-bar average" in how
    sparse = [(close - timedelta(minutes=50), 96.5)]
    assert g.reference_price(sparse, close)[0] == 96.5


def test_fair_open_matches_the_hand_calculation_and_splits_exactly():
    m = g.fair_open(149103, 4155.4, 4210.9, 96.77, 96.725)
    assert m["fair_open"] == pytest.approx(149103 * 4210.9 / 4155.4 * 96.725 / 96.77, abs=1)
    assert m["comex_part"] + m["inr_part"] == pytest.approx(m["gap"], abs=2)
    assert 35 < m["rs_per_comex_dollar"] < 37 and 1500 < m["rs_per_inr_rupee"] < 1560   # the checklist's 35.6 / 1,521


def test_verdict_states():
    open_t = datetime(2026, 10, 9, 9, 5, tzinfo=IST)
    pre_t = datetime(2026, 10, 9, 8, 40, tzinfo=IST)
    assert g.verdict(151000, 151250, 300, open_t)["state"] == "OK"
    wait = g.verdict(151000, 151400, 300, open_t)
    assert wait["state"] == "WAIT" and "Don't chase" in wait["title"] and wait["diff"] == 400
    assert g.verdict(151000, None, 300, pre_t)["state"] == "AWAITING_OPEN"
    assert g.verdict(151000, None, 300, open_t)["state"] == "NEED_PRICE"
    assert g.verdict(None, 151000, 300, open_t)["state"] == "NO_MODEL"


# ── accuracy log ──────────────────────────────────────────────────────────────

def test_log_records_snapshot_then_actual_and_computes_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLD_LOG_PATH", str(tmp_path / "log.json"))
    g._update_day("2026-10-12", fair_open=125_400.0, baseline=125_000.0, snapshot_at="2026-10-12T08:45:00+05:30")
    row = g._update_day("2026-10-12", actual_open=125_650.0, actual_source="manual")
    assert row["fair_open"] == 125_400.0                  # earlier fields kept
    assert row["error"] == 250.0 and row["naive_error"] == 650.0
    out = g.gold_log(days=60, threshold=300)
    assert out["rows"][0]["date"] == "2026-10-12"
    assert out["stats"]["days"] == 1 and out["stats"]["within_threshold_pct"] == 100.0
    assert out["stats"]["naive_mean_abs_error"] == 650.0


def test_manual_actual_validates_price(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLD_LOG_PATH", str(tmp_path / "log.json"))
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        g.gold_set_actual({"date": "2026-10-12", "open": 52})        # not a ₹/10 g gold price
    with pytest.raises(HTTPException):
        g.gold_set_actual({"date": "12/10/2026", "open": 125_000})
    assert g.gold_set_actual({"date": "2026-10-12", "open": 125_000})["actual_open"] == 125_000


def test_accuracy_stats_empty_and_bias():
    assert g.accuracy_stats([]) == {"days": 0}
    s = g.accuracy_stats([{"error": 100, "naive_error": 400}, {"error": -400, "naive_error": -100}], threshold=300)
    assert s["bias"] == -150.0 and s["mean_abs_error"] == 250.0 and s["within_threshold_pct"] == 50.0


# ── Yahoo series cache + single flight (desktop review C2-performance-04) ─────────────────────────

NOW = datetime(2026, 10, 26, 8, 40, tzinfo=IST)
YAHOO_SYMBOLS = {"GCZ26.CMX", "INR=X", "DX-Y.NYB", "EURUSD=X", "^TNX", "SI=F"}


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


def _chart(symbol: str) -> dict:
    base = {"GCZ26.CMX": 4150.0, "INR=X": 88.1, "DX-Y.NYB": 99.2, "EURUSD=X": 1.16, "^TNX": 4.1, "SI=F": 48.0}[symbol]
    close = g.mcx_close_time(date(2026, 10, 23))
    stamps = [int((close + timedelta(minutes=m)).timestamp()) for m in range(-60, 30, 5)]
    closes = [round(base * (1 + 0.0005 * i), 4) for i in range(len(stamps))]
    return {"chart": {"result": [{"meta": {"regularMarketPrice": closes[-1] * 1.002, "regularMarketTime": stamps[-1]},
                                  "timestamp": stamps, "indicators": {"quote": [{"close": closes}]}}]}}


class _Upstream:
    """httpx.MockTransport handler for every source of the desk; counts Yahoo chart requests per symbol."""

    def __init__(self, delay: float = 0.0, fail: set[str] | None = None, news_delay: float = 0.0) -> None:
        self.delay = delay
        self.fail = set(fail or ())
        self.yahoo: dict[str, int] = {}
        self.news_delay = news_delay
        self.news = 0
        self.fred = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.delay:
            await asyncio.sleep(self.delay)
        host, path = request.url.host, request.url.path
        if host == "query1.finance.yahoo.com" and path.startswith("/v8/finance/chart/"):
            symbol = unquote(path.rsplit("/", 1)[1])
            self.yahoo[symbol] = self.yahoo.get(symbol, 0) + 1
            if symbol in self.fail:
                return httpx.Response(500, json={"chart": {"result": None}})
            return httpx.Response(200, json=_chart(symbol))
        if host == "fred.stlouisfed.org":
            self.fred += 1
            return httpx.Response(200, text="DATE,DFII10\n2026-10-21,1.71\n2026-10-22,1.69\n")
        if host == "news.google.com":
            self.news += 1
            if self.news_delay:
                await asyncio.sleep(self.news_delay)
            return httpx.Response(200, text="<rss><channel></channel></rss>")
        return httpx.Response(404)

    @property
    def total(self) -> int:
        return sum(self.yahoo.values())


@pytest.fixture
def desk(monkeypatch: pytest.MonkeyPatch):
    """The gold desk with every upstream replaced: ICICI master, Breeze and the treasury fetch stubbed, httpx
    pointed at _Upstream, the clock frozen. Yields a function that installs an _Upstream and returns it."""
    g._cache.clear()
    g._yahoo_inflight.clear()
    g._bg_inflight.clear()
    monkeypatch.setattr(g, "_load_mcx_master", lambda: (HEADER + ROWS, date(2026, 10, 26)))
    monkeypatch.setattr(g, "_breeze_mcx_quote", lambda expiry: None)
    monkeypatch.setattr(g, "_breeze_mcx_open", lambda expiry, day: None)
    monkeypatch.setattr(g, "_refresh_treasury_in_background", lambda: None)
    monkeypatch.setattr(g, "datetime", _FrozenDatetime)
    monkeypatch.setattr(g, "YAHOO_TTL_S", 30.0)
    real_client = httpx.AsyncClient

    def install(upstream: _Upstream) -> _Upstream:
        transport = httpx.MockTransport(upstream)
        monkeypatch.setattr(g.httpx, "AsyncClient", lambda *a, **k: real_client(*a, **{**k, "transport": transport}))
        return upstream
    yield install
    g._cache.clear()
    g._yahoo_inflight.clear()
    g._bg_inflight.clear()


def _call() -> dict:
    return asyncio.run(g.gold_preopen(baseline=None, mcx_price=None, threshold=300, eurusd_trigger=1.1161))


def _enc(x: dict) -> str:
    return json.dumps(x, default=str, sort_keys=True)


def test_repeated_calls_reuse_the_six_yahoo_series(desk) -> None:
    up = desk(_Upstream())
    first = _call()
    assert set(up.yahoo) == YAHOO_SYMBOLS and up.total == 6
    assert first["model"]["fair_open"] and first["verdict"]["state"]
    second = _call()
    assert up.total == 6                                   # nothing re-fetched inside the TTL
    assert _enc(second) == _enc(first)


def test_cached_answer_equals_the_uncached_and_the_original_wiring(desk, monkeypatch: pytest.MonkeyPatch) -> None:
    up = desk(_Upstream())
    _call()
    cached = _call()                                       # served from the cache
    monkeypatch.setattr(g, "YAHOO_TTL_S", 0.0)             # cache off: every call fetches
    uncached = _call()
    assert up.total == 12
    shared: dict = {}

    async def original(symbol: str, rng: str = "5d", interval: str = "5m") -> dict:
        # the pre-change wiring: _yahoo_bars on the endpoint's own client, no cache
        client = shared.setdefault("c", g.httpx.AsyncClient(timeout=g._TIMEOUT, headers=g._UA, follow_redirects=True))
        return await g._yahoo_bars(client, symbol, rng, interval)
    monkeypatch.setattr(g, "_yahoo_bars_cached", original)
    old = _call()
    assert _enc(cached) == _enc(uncached) == _enc(old)


def test_concurrent_calls_share_one_fetch_per_series(desk) -> None:
    up = desk(_Upstream(delay=0.05))

    async def both() -> list:
        return await asyncio.gather(
            g.gold_preopen(baseline=None, mcx_price=None, threshold=300, eurusd_trigger=1.1161),
            g.gold_preopen(baseline=None, mcx_price=None, threshold=300, eurusd_trigger=1.1161))
    a, b = asyncio.run(both())
    assert up.total == 6 and _enc(a) == _enc(b)
    assert g._yahoo_inflight == {}                         # finished fetches leave nothing behind


def _desk_call() -> Any:
    return g.gold_preopen(baseline=None, mcx_price=None, threshold=300, eurusd_trigger=1.1161)


async def _background_refreshes() -> None:
    tasks = [t for _, t in list(g._yahoo_inflight.values())]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def test_series_are_refreshed_in_the_background_after_the_ttl(desk, monkeypatch: pytest.MonkeyPatch) -> None:
    """C-PERF-02: past YAHOO_TTL_S a series is still served at once and re-fetched behind the caller, so a 60 s UI
    refresher never waits on Yahoo; the answer is the same computation on the cached series."""
    up = desk(_Upstream())
    clock = [1000.0]
    monkeypatch.setattr(g.time, "monotonic", lambda: clock[0])

    async def scenario() -> tuple[dict, dict, int, int]:
        first = await _desk_call()
        clock[0] += 29.0
        await _desk_call()
        assert up.total == 6                               # fresh: nothing re-fetched
        clock[0] += 2.0                                    # 31 s after the fetch: stale
        stale = await _desk_call()
        during = up.total + sum(1 for _ in g._yahoo_inflight)
        await _background_refreshes()
        return first, stale, during, up.total
    first, stale, during, after = asyncio.run(scenario())
    assert _enc(stale) == _enc(first)                      # served from the cached series
    assert during == 12 and after == 12                    # all six refreshed, nobody waited for them


def test_series_older_than_max_age_are_never_served(desk, monkeypatch: pytest.MonkeyPatch) -> None:
    up = desk(_Upstream())
    clock = [1000.0]
    monkeypatch.setattr(g.time, "monotonic", lambda: clock[0])

    async def scenario() -> int:
        await _desk_call()
        clock[0] += g.YAHOO_MAX_AGE_S                      # at the bound: the call waits for new series
        await _desk_call()
        return up.total
    assert asyncio.run(scenario()) == 12 and g._yahoo_inflight == {}
    assert g.YAHOO_MAX_AGE_S >= 2 * 60                     # at least two of the UI's 60 s refreshes


def test_the_0845_snapshot_never_uses_a_stale_series(desk, monkeypatch: pytest.MonkeyPatch) -> None:
    """The recorded prediction keeps the old rule: nothing older than YAHOO_TTL_S."""
    up = desk(_Upstream())
    clock = [1000.0]
    monkeypatch.setattr(g.time, "monotonic", lambda: clock[0])

    async def scenario() -> tuple[int, dict]:
        await _desk_call()
        clock[0] += 31.0
        row = await g.gold_snapshot(force=False)          # frozen clock: 08:40 IST, before the open
        return up.total, row
    total, row = asyncio.run(scenario())
    assert total == 12 and g._yahoo_inflight == {}        # waited for six fresh series, none left behind
    assert row["fair_open"] and row["snapshot_at"].startswith("2026-10-26T08:40")


def test_the_desk_reports_the_oldest_series_age_in_headers(desk) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    desk(_Upstream())
    app = FastAPI()
    app.include_router(g.router, prefix="/api/commodity")
    with TestClient(app, base_url="http://127.0.0.1:8010") as c:
        a = c.get("/api/commodity/gold-preopen")
        b = c.get("/api/commodity/gold-preopen")
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert a.headers["x-cache"] == "miss" and a.headers["x-cache-age"] == "0"
    assert b.headers["x-cache"] == "hit" and int(b.headers["x-cache-age"]) < 30
    assert "x-cache" not in a.text


def test_warm_series_fetches_exactly_the_desks_six_series(desk) -> None:
    up = desk(_Upstream())
    assert asyncio.run(g.warm_series()) == 6
    assert set(up.yahoo) == YAHOO_SYMBOLS and up.total == 6


def test_failed_series_are_not_cached(desk) -> None:
    up = desk(_Upstream(fail={"INR=X"}))
    first = _call()
    assert "COMEX or USD/INR prices could not be fetched from Yahoo." in first["notes"]
    _call()
    assert up.yahoo["INR=X"] == 2 and up.yahoo["GCZ26.CMX"] == 1   # the failure is retried, the rest reused


def test_a_caller_deadline_does_not_cancel_the_shared_fetch(desk) -> None:
    up = desk(_Upstream(delay=0.2))

    async def scenario() -> dict:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(g._yahoo_bars_cached("INR=X"), 0.01)
        await asyncio.sleep(0.4)                           # the fetch finished on its own and was cached
        return await g._yahoo_bars_cached("INR=X")
    result = asyncio.run(scenario())
    assert up.yahoo == {"INR=X": 1} and result["price"] is not None


# ── headlines + FRED: stale-while-revalidate inside their old bounds (C-PERF-02 follow-up) ─────────────────────

async def _all_background() -> None:
    tasks = [t for _, t in list(g._yahoo_inflight.values()) + list(g._bg_inflight.values())]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def test_headlines_and_fred_refresh_behind_the_caller_inside_their_old_bounds(desk, monkeypatch) -> None:
    """Before: every 5 min one CMDT/BRF refresh waited on six Google News reads (and on FRED every 6 h). Now past
    half the bound the cached copy is served at once and re-read in the background; never older than the bound."""
    up = desk(_Upstream(news_delay=0.2))
    clock = [0.0]                         # an offset on the real clock: the event loop's own timers must keep running
    real = time.monotonic
    monkeypatch.setattr(g.time, "monotonic", lambda: real() + clock[0])
    topics = len(g.HEADLINE_TOPICS)

    async def scenario() -> dict:
        out: dict = {}
        first = await _desk_call()
        out["first"] = (up.news, up.fred)
        clock[0] += g.NEWS_REFRESH_AFTER_S - 1                   # fresh: no headline read at all
        await _desk_call()
        await _all_background()
        out["fresh"] = up.news
        clock[0] += 2                                            # past the refresh point, inside the 300 s bound
        t0 = time.perf_counter()
        stale = await _desk_call()
        out["stale_wait_s"] = time.perf_counter() - t0          # news_delay is 0.2 s: the caller did not wait for it
        out["inflight"] = sum(1 for k in g._bg_inflight if k.startswith("news:"))
        await _all_background()
        out["after_refresh"] = up.news
        out["same_body"] = _enc(stale) == _enc(first)
        clock[0] += g.NEWS_MAX_AGE_S                             # past the bound: the caller reads them itself
        await _desk_call()
        out["past_bound"] = up.news
        clock[0] += g.FRED_REFRESH_AFTER_S                       # FRED: background after 3 h ...
        await _desk_call()
        await _all_background()
        out["fred_bg"] = up.fred
        return out
    out = asyncio.run(scenario())
    assert out["first"] == (topics, 1)
    assert out["fresh"] == topics
    assert out["stale_wait_s"] < 0.15 and out["inflight"] == topics
    assert out["after_refresh"] == 2 * topics and out["same_body"]
    assert out["past_bound"] == 3 * topics
    assert out["fred_bg"] == 2
    assert g.NEWS_MAX_AGE_S == 300.0 and g.FRED_MAX_AGE_S == 6 * 3600.0     # the old bounds, unchanged


def test_a_stale_headline_list_is_refreshed_once_for_concurrent_callers(desk, monkeypatch) -> None:
    up = desk(_Upstream(news_delay=0.05))
    clock = [0.0]                         # an offset on the real clock: the event loop's own timers must keep running
    real = time.monotonic
    monkeypatch.setattr(g.time, "monotonic", lambda: real() + clock[0])

    async def scenario() -> int:
        await _desk_call()
        clock[0] += g.NEWS_REFRESH_AFTER_S + 1
        await asyncio.gather(_desk_call(), _desk_call(), _desk_call())
        await _all_background()
        return up.news
    assert asyncio.run(scenario()) == 2 * len(g.HEADLINE_TOPICS)          # one background read per topic
    assert g._bg_inflight == {}


def test_market_headlines_use_the_same_cache(desk, monkeypatch) -> None:
    """BRF's /api/market/headlines shares _headlines: its topics keep their own 'mkt:' keys and labels."""
    from routers import markets
    up = desk(_Upstream())
    a = asyncio.run(markets.market_headlines())
    b = asyncio.run(markets.market_headlines())
    assert up.news == len(markets.MARKET_TOPICS) and a == b
