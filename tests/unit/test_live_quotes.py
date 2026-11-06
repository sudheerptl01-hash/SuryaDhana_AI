"""LV-DATA (5 Nov 2026): /live/quotes composition (Breeze tick → NSE website copy → EOD close, never Yahoo), the honest
labels (live / delayed / stale / closed / unavailable, ages from each source's own clock), the session clock (pre-open,
close, weekends, holidays), the demand-driven NSE fallback poller (L-CAPACITY cadences, pacing, breaker), the pinned set,
the main.py routes + EOD SQL on a temp DuckDB, and a fake Breeze client end to end with LIVE_TICKS on and off.
Negative controls: the request path never calls NSE or Breeze REST; the poller makes no call without demand, outside the
session or while the NSE breaker is open."""
from __future__ import annotations

import re
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/data-service"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_quotes as lq  # noqa: E402
import live_ticks as lt  # noqa: E402
import nse_live as nl  # noqa: E402
import test_live_fixtures as fx  # noqa: E402
from test_live_ticks_tokens import FakeBreeze, FakeProvider  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 5)                                             # a Thursday, a trading day
KEYS = {"price", "change", "change_pct", "prev_close", "open", "day_high", "day_low", "volume", "value_cr", "bid", "ask",
        "ltt", "source", "age_s", "state"}


def at(h: int, m: int, s: int = 0, day: date = DAY) -> float:
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=IST).timestamp()


# ── fakes ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

class FakeTicks:
    """The LiveTicks surface LiveQuotes uses, with ages set by hand."""

    def __init__(self, clock, rows: dict[str, dict] | None = None, healthy: bool = True, subscribed=(), state="LIVE",
                 since: dict[str, float] | None = None):
        self.clock, self.rows, self.healthy, self.subs, self.state = clock, rows or {}, healthy, set(subscribed), state
        self.since = since or {}                       # sym → when its current subscription started (absent: unknown)
        self.ensured: list[list[str]] = []

    def ensure(self, syms):
        self.ensured.append(list(syms))
        return {"state": self.state}

    def snapshot(self, syms=None):
        now = self.clock()
        out = {}
        for s, r in self.rows.items():
            if syms is None or s in syms:
                out[s] = {**r, "ts_age_s": round(now - r["ts"], 1)}
        return out

    def feed_healthy(self):
        return self.healthy

    def is_subscribed(self, s):
        return s in self.subs

    def subscribed_since(self, s):
        return self.since.get(s) if s in self.subs else None

    def heartbeat_age(self):
        return 0.1 if self.healthy else 30.0

    def status(self):
        return {"state": self.state, "subscribed": len(self.subs), "requested": 0, "ticks_per_min": 600, "last_tick_age_s": 0.1}


def tick(price, ts, prev=None, **kw) -> dict:
    return {"price": price, "ts": ts, "prev_close": prev, "chg_pct": (price / prev - 1) * 100 if prev else None,
            "ttq": kw.get("ttq"), "avg_price": kw.get("avg"), "bid": kw.get("bid"), "ask": kw.get("ask"),
            "open": kw.get("open"), "high": kw.get("high"), "low": kw.get("low"), "ltt_epoch": kw.get("ltt", ts),
            "last_trade_age_s": None, "hint": kw.get("hint")}


class FakeNse:
    """NseLive's surface (get with TTLs, cached_at, heatmap_lists, blocked_until) over recorded payloads."""

    LISTS = [("Broad Market Indices", "NIFTY 50"), ("Broad Market Indices", "NIFTY NEXT 50"), ("Sectoral Indices", "NIFTY BANK")]

    def __init__(self, clock, fail: str | None = None):
        self.clock = clock
        self._cache: dict[str, tuple[float, Any]] = {}
        self.calls: list[tuple[float, str]] = []
        self.blocked_until = 0.0
        self.fail = fail

    def cached_at(self, path):
        hit = self._cache.get(path)
        return hit[0] if hit else None

    def heatmap_lists(self):
        return list(self.LISTS)

    def payload(self, path: str) -> Any:
        if path == "allIndices":
            return fx.ALL_INDICES
        if path.startswith("heatmap-index"):
            return [{"index": "NIFTY BANK"}]
        if path == nl.heatmap_path("Broad Market Indices", "NIFTY 50"):
            return fx.HEATMAP
        if path == nl.heatmap_path("Sectoral Indices", "NIFTY BANK"):
            return [r for r in fx.HEATMAP if r["symbol"] in ("HDFCBANK", "ICICIBANK")]
        if path == nl.heatmap_path("Broad Market Indices", "NIFTY NEXT 50"):
            return [{"symbol": "DMART", "series": "EQ", "lastPrice": "4100", "change": "10", "pChange": "0.24", "high": "4120",
                     "low": "4080", "VWAP": "4101", "totalTradedVolume": "1000", "quantityTraded": "4101000",
                     "lastUpdatedTime": "05-Nov-2026 10:14:30"}]
        if path.startswith("NextApi"):
            sym = re.search(r"symbol=([A-Z0-9%&-]+)", path).group(1)   # type: ignore[union-attr]
            meta = {**fx.NEXTAPI["equityResponse"][0]["metaData"], "symbol": sym}
            return {"equityResponse": [{**fx.NEXTAPI["equityResponse"][0], "metaData": meta}]}
        if path.startswith("holiday-master"):
            return {"CM": [{"tradingDate": "25-Dec-2026", "description": "Christmas"}]}
        raise AssertionError(f"unexpected NSE path {path}")

    def get(self, path, ttl_open=30, ttl_closed=600):
        hit = self._cache.get(path)
        if hit and self.clock() - hit[0] < ttl_open:
            return hit[1]
        if self.fail and self.fail in path:
            raise RuntimeError("NSE 503")
        self.calls.append((self.clock(), path))
        val = self.payload(path)
        self._cache[path] = (self.clock(), val)
        return val


class Clock:
    def __init__(self, t: float):
        self.t = t
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def engine(clock, ticks=None, nse=None, eod=None, **kw) -> lq.LiveQuotes:
    calls: list[list[str]] = []

    def eod_fn(syms):
        calls.append(list(syms))
        return {s: r for s, r in (eod or {}).items() if s in syms}
    e = lq.LiveQuotes(ticks_getter=lambda: ticks, nse_getter=lambda: nse, eod_fn=eod_fn, clock=clock,
                      sleep_fn=getattr(clock, "sleep", None), start_poller=False, **kw)
    e.eod_calls = calls  # type: ignore[attr-defined]
    return e


EOD = {"RELIANCE": {"date": "2026-11-04", "close": 1311.0, "prev_close": 1300.0, "open": 1301.0, "high": 1315.0, "low": 1299.0,
                    "volume": 9_000_000, "value_cr": 1180.0, "table": "nse_bhavcopy"},
       "NIFTY 50": {"date": "2026-11-04", "close": 23960.6, "prev_close": 23810.85, "open": None, "high": None, "low": None,
                    "volume": None, "value_cr": None, "table": "market_index_daily"}}


# ── the market clock ──────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("t,state,session", [
    (at(8, 59, 59), "closed", "2026-11-04"), (at(9, 0), "pre-open", "2026-11-05"), (at(9, 14, 59), "pre-open", "2026-11-05"),
    (at(9, 15), "open", "2026-11-05"), (at(15, 29, 59), "open", "2026-11-05"), (at(15, 30), "closed", "2026-11-05"),
    (at(10, 0, day=date(2026, 11, 7)), "closed", "2026-11-06"),                 # Saturday → Friday's session
    (at(8, 0, day=date(2026, 11, 9)), "closed", "2026-11-06"),                  # Monday before the bell → Friday
])
def test_market_state(t, state, session):
    st, sd = lq.market_state(datetime.fromtimestamp(t, IST), set())
    assert (st, sd.isoformat()) == (state, session)


def test_holiday_closes_the_market_and_points_at_the_previous_session():
    st, sd = lq.market_state(datetime.fromtimestamp(at(11, 0), IST), {"2026-11-05"})
    assert (st, sd.isoformat()) == ("closed", "2026-11-04")
    assert lq.parse_trading_holidays({"CM": [{"tradingDate": "25-Dec-2026"}, {"tradingDate": "junk"}]}) == {"2026-12-25"}


# ── source order and labels (session open) ────────────────────────────────────────────────────────────────────────────

def test_source_order_breeze_live_then_nse_delayed_then_eod_stale():
    clock = Clock(at(10, 15, 20))
    ticks = FakeTicks(clock, {"TATASTEEL": tick(180.57, clock.t - 1, 179.93, ttq=8_712_469, avg=181.62, bid=180.56, ask=180.63,
                                                open=182.29, high=182.66, low=180.3, ltt=clock.t - 2)},
                      subscribed=["TATASTEEL"])
    e = engine(clock, ticks=ticks, eod=EOD)
    e._store_eq(nl.parse_heatmap_rows(fx.HEATMAP), at(10, 15, 7))               # NSE rows stamped 10:14:0x, fetched 10:15:07
    out = e.quotes(["TATASTEEL", "HDFCBANK", "RELIANCE", "NOPE"])
    assert out["market"] == {"state": "open", "session_date": "2026-11-05"}
    q = out["quotes"]
    t = q["TATASTEEL"]
    assert (t["source"], t["state"], t["age_s"], t["price"]) == ("breeze_ws", "live", 1.0, 180.57)
    assert t["change"] == round(180.57 - 179.93, 2) and t["value_cr"] == round(8_712_469 * 181.62 / 1e7, 2)
    assert t["ltt"].endswith("+05:30") and t["volume"] == 8_712_469 and t["bid"] == 180.56 and "reason" not in t
    h = q["HDFCBANK"]
    stamp = nl.nse_time(next(r for r in fx.HEATMAP if r["symbol"] == "HDFCBANK")["lastUpdatedTime"])[0]
    assert (h["source"], h["state"], h["age_basis"]) == ("nse_api", "delayed", "nse_row_time")
    assert h["age_s"] == round(clock.t - stamp, 1) and h["age_s"] <= lq.DELAYED_MAX_S and h["ltt"].endswith("+05:30")
    r = q["RELIANCE"]
    assert r["source"] == "nse_api"                                  # NSE (≤ 90 s) beats yesterday's close
    clock.t = at(10, 19)                                             # the NSE copy is now > 90 s old
    q2 = e.quotes(["HDFCBANK"])["quotes"]["HDFCBANK"]
    assert q2["state"] == "stale" and q2["source"] == "nse_api"
    e2 = engine(clock, ticks=None, eod=EOD)
    r2 = e2.quotes(["RELIANCE", "NOPE"])["quotes"]
    assert (r2["RELIANCE"]["source"], r2["RELIANCE"]["state"], r2["RELIANCE"]["date"]) == ("eod", "stale", "2026-11-04")
    assert "last close 2026-11-04" in r2["RELIANCE"]["reason"]
    assert r2["NOPE"]["state"] == "unavailable" and r2["NOPE"]["price"] is None and r2["NOPE"]["source"] is None
    for qq in list(q.values()) + list(r2.values()):
        assert KEYS <= set(qq) and qq["state"] in {"live", "delayed", "stale", "closed", "unavailable"}
        assert qq["source"] in {"breeze_ws", "nse_api", "eod", None}


def test_quiet_name_on_a_healthy_feed_stays_live_but_not_on_a_sick_one():
    clock = Clock(at(10, 16))
    rows = {"ILLIQ": tick(55.0, clock.t - 40, 54.0), "HDFCBANK": tick(1000.0, clock.t - 30, 990.0)}
    healthy = engine(clock, ticks=FakeTicks(clock, rows, healthy=True, subscribed=["ILLIQ", "HDFCBANK"]))
    q = healthy.quotes(["ILLIQ"])["quotes"]["ILLIQ"]
    assert q["state"] == "live" and q["age_s"] == 40.0 and q["reason"].startswith("quiet")
    sick = engine(clock, ticks=FakeTicks(clock, rows, healthy=False, subscribed=["ILLIQ", "HDFCBANK"]))
    sick._store_eq(nl.parse_heatmap_rows(fx.HEATMAP), at(10, 15, 50))
    q2 = sick.quotes(["ILLIQ", "HDFCBANK"])["quotes"]
    assert (q2["ILLIQ"]["source"], q2["ILLIQ"]["state"]) == ("breeze_ws", "delayed")   # 40 s old tick, no NSE copy
    hdfc_nse_age = round(clock.t - nl.nse_time(next(r for r in fx.HEATMAP if r["symbol"] == "HDFCBANK")["lastUpdatedTime"])[0], 1)
    best = "breeze_ws" if 30.0 <= hdfc_nse_age else "nse_api"
    assert q2["HDFCBANK"]["source"] == best and q2["HDFCBANK"]["state"] == "delayed"   # the fresher of tick and NSE
    unsub = engine(clock, ticks=FakeTicks(clock, rows, healthy=True, subscribed=[]))
    assert unsub.quotes(["ILLIQ"])["quotes"]["ILLIQ"]["state"] == "delayed"   # not subscribed: no quiet-live claim
    too_old = engine(clock, ticks=FakeTicks(clock, {"ILLIQ": tick(55.0, clock.t - 200, 54.0)}, healthy=True, subscribed=["ILLIQ"]))
    assert too_old.quotes(["ILLIQ"])["quotes"]["ILLIQ"]["state"] == "stale"


def _quiet_case(clock, nse_row=None, healthy=True, subscribed=("ILLIQ",), tick_age=600.0, ttq=1200, sub_age=None):
    """ILLIQ last ticked `tick_age` s ago on a (healthy) socket, its current subscription `sub_age` s old (None: unknown);
    `nse_row` is NSE's copy as (price, volume, age_s)."""
    since = {"ILLIQ": clock.t - sub_age} if sub_age is not None else None
    e = engine(clock, ticks=FakeTicks(clock, {"ILLIQ": tick(55.0, clock.t - tick_age, 54.0, ttq=ttq, avg=55.0)},
                                      healthy=healthy, subscribed=list(subscribed), since=since))
    if nse_row is not None:
        price, volume, age = nse_row
        e._store_eq({"ILLIQ": {"price": price, "volume": volume, "prev_close": 54.0, "stamp_epoch": clock.t - age}},
                    clock.t - age)
    return e, e.quotes(["ILLIQ"])["quotes"]["ILLIQ"]


def test_a_tick_older_than_the_subscription_is_never_vouched_for_by_the_socket():
    """6 Nov acceptance: EQS read 24 rows STALE · BREEZE · 22m: subscriptions that lapsed after 10 min without demand
    (asked 09:03, re-asked 09:29) kept their 09:08 auction ticks; the page was captured before the first new tick."""
    clock = Clock(at(10, 16))
    _, lapsed = _quiet_case(clock, tick_age=1300.0, sub_age=5.0)          # re-subscribed 5 s ago, no NSE copy yet
    assert lapsed["state"] == "stale" and lapsed["reason"] == "re-subscribed 5 s ago, waiting for the first tick; last tick 1300 s old"
    _, recent = _quiet_case(clock, tick_age=60.0, sub_age=10.0)           # ≤ 120 s, but the socket only joined 10 s ago
    assert recent["state"] == "delayed" and recent["reason"].startswith("re-subscribed 10 s ago")   # no quiet-LIVE claim
    _, with_nse = _quiet_case(clock, (55.5, 1900, 20.0), tick_age=700.0, sub_age=40.0)
    assert (with_nse["source"], with_nse["state"], with_nse["price"]) == ("nse_api", "delayed", 55.5)
    _, within = _quiet_case(clock, tick_age=60.0, sub_age=300.0)          # subscribed before the tick: the old quiet rule
    assert within["state"] == "live" and within["reason"].startswith("quiet")
    _, unknown = _quiet_case(clock, tick_age=60.0)                        # an engine without the accessor: the old rule
    assert unknown["state"] == "live"
    _, same_ms = _quiet_case(clock, tick_age=60.0, sub_age=60.0)          # the tick landed on the subscription stamp
    assert same_ms["state"] == "live"


def test_fallback_reasons_name_the_cause_and_fit_ui_apis_cap():
    clock = Clock(at(10, 16))
    _, quiet = _quiet_case(clock, sub_age=3600.0)                          # past the quiet bound, no NSE copy
    assert quiet["state"] == "stale" and quiet["reason"] == "no tick for 600 s; last tick 600 s old"
    _, traded = _quiet_case(clock, (55.0, 1250, 70.0), sub_age=3600.0)     # NSE counts more shares than the last tick
    assert (traded["source"], traded["state"]) == ("nse_api", "delayed")
    assert traded["reason"] == "no tick for 600 s; NSE's volume is higher; NSE website copy 70 s old"
    _, sick = _quiet_case(clock, (55.0, 1200, 70.0), healthy=False)
    assert sick["reason"].startswith("the feed is not healthy")
    _, unsub = _quiet_case(clock, (55.0, 1200, 70.0), subscribed=())
    assert unsub["reason"].startswith("not subscribed on the feed")
    pre_clock = Clock(at(9, 6))
    _, pre = _quiet_case(pre_clock, (55.0, 1200, 70.0), tick_age=200.0, sub_age=40.0)
    assert len(pre["reason"]) <= 200 and "(pre-open:" in pre["reason"]
    for q in (quiet, traded, sick, unsub, pre):
        assert "confirmed_by" not in q and "not healthy" not in q["reason"] or q is sick


def test_the_poller_fetches_nse_at_once_for_a_re_subscribed_name():
    clock = Clock(at(10, 16))
    rows = {"ILLIQ": tick(55.0, clock.t - 60, 54.0, ttq=1200), "OLDSUB": tick(70.0, clock.t - 60, 69.0, ttq=10)}
    ticks = FakeTicks(clock, rows, healthy=True, subscribed=["ILLIQ", "OLDSUB"],
                      since={"ILLIQ": clock.t - 10, "OLDSUB": clock.t - 3600})
    e = engine(clock, ticks=ticks)
    assert e._covered_by_ticks(["ILLIQ", "OLDSUB"]) == {"OLDSUB"}         # ILLIQ's tick predates its subscription


def test_live_ticks_reports_when_the_current_subscription_started():
    import live_ticks as lt
    obj = lt.LiveTicks(lambda: None, clock=lambda: 1000.0, enabled_fn=lambda: False, market_hours_fn=lambda: True)
    assert obj.subscribed_since("ABB") is None
    obj._subscribed["ABB"], obj._subscribed_at["ABB"] = "4.1!123", 950.0
    assert obj.subscribed_since("ABB") == 950.0
    obj._subscribed.pop("ABB")                                            # dropped: the stamp no longer counts
    assert obj.subscribed_since("ABB") is None


def test_clamped_corporate_action_move_drops_change_and_says_why():
    clock = Clock(at(10, 16))
    ticks = FakeTicks(clock, {"SPLITCO": {**tick(50.0, clock.t - 1, 100.0), "chg_pct": None, "hint": "possible corporate action"}},
                      subscribed=["SPLITCO"])
    q = engine(clock, ticks=ticks).quotes(["SPLITCO"])["quotes"]["SPLITCO"]
    assert q["change"] is None and q["change_pct"] is None and q["hint"] == "possible corporate action" and q["state"] == "live"


def test_nse_ages_minute_stamp_and_nextapi_floor():
    clock = Clock(at(10, 15))
    e = engine(clock)
    rows = nl.parse_all_indices_rows(fx.ALL_INDICES)                 # stamp '05-Nov-2026 10:13' (minute)
    for r in rows.values():
        r["fetched_at"] = at(10, 14, 30)
    e._nse_idx.update(rows)
    q = e.quotes(["NIFTY 50", "NIFTY CPSE"])["quotes"]
    n = q["NIFTY 50"]
    assert (n["source"], n["age_basis"], n["age_s"]) == ("nse_api", "nse_minute_stamp", 61.0)   # end of the 10:13 minute
    assert n["state"] == "delayed" and n["price"] == 24367.8 and n["prev_close"] == 23960.6
    assert q["NIFTY CPSE"]["source"] == "nse_api"                    # an index Breeze does not stream
    quote = nl.parse_equity_quote(fx.NEXTAPI)                        # lastUpdateTime 10:15:53 (understates the age)
    clock.t = at(10, 16)
    e._store_eq({"RELIANCE": {**quote, "symbol": None}}, at(10, 15, 54))
    r = e.quotes(["RELIANCE"])["quotes"]["RELIANCE"]
    assert r["age_basis"] == "nse_quote_floor" and r["age_s"] == 6.0 + lq.NEXTAPI_MIN_LAG_S
    assert (r["bid"], r["ask"], r["open"], r["prev_close"]) == (1307.8, 1307.9, 1324, 1311)


# ── closed-session labelling ──────────────────────────────────────────────────────────────────────────────────────────

def test_after_the_close_the_last_tick_is_close_until_the_official_close_is_stored():
    clock = Clock(at(16, 0))
    ticks = FakeTicks(clock, {"RELIANCE": tick(1307.0, at(15, 29, 59), 1311.0)}, healthy=False, subscribed=["RELIANCE"])
    e = engine(clock, ticks=ticks, eod=EOD)
    out = e.quotes(["RELIANCE", "NIFTY 50"])
    assert out["market"] == {"state": "closed", "session_date": "2026-11-05"}
    r = out["quotes"]["RELIANCE"]
    assert (r["source"], r["state"], r["price"], r["date"]) == ("breeze_ws", "closed", 1307.0, "2026-11-05")
    assert "official close" in r["reason"]
    n = out["quotes"]["NIFTY 50"]                                    # only yesterday's close: never 'closed' for today
    assert (n["source"], n["state"]) == ("eod", "stale") and "2026-11-05 close is not stored yet" in n["reason"]
    clock.t = at(19, 0)
    e2 = engine(clock, ticks=ticks, eod={"RELIANCE": {**EOD["RELIANCE"], "date": "2026-11-05", "close": 1306.4}})
    r2 = e2.quotes(["RELIANCE"])["quotes"]["RELIANCE"]
    assert (r2["source"], r2["state"], r2["price"]) == ("eod", "closed", 1306.4) and "reason" not in r2   # NSE's official close


def test_weekend_pre_open_and_holiday_labels():
    sat = Clock(at(10, 0, day=date(2026, 11, 7)))
    eod_fri = {"RELIANCE": {**EOD["RELIANCE"], "date": "2026-11-06"}}
    out = engine(sat, eod=eod_fri).quotes(["RELIANCE"])
    assert out["market"] == {"state": "closed", "session_date": "2026-11-06"}
    assert out["quotes"]["RELIANCE"]["state"] == "closed" and out["quotes"]["RELIANCE"]["age_s"] > 0
    pre = Clock(at(9, 5))
    out2 = engine(pre, eod=EOD).quotes(["RELIANCE"])
    assert out2["market"]["state"] == "pre-open"
    assert out2["quotes"]["RELIANCE"]["state"] == "closed" and "previous session close" in out2["quotes"]["RELIANCE"]["reason"]
    pre_tick = engine(pre, ticks=FakeTicks(pre, {"RELIANCE": tick(1320.0, pre.t - 1, 1311.0)}, subscribed=["RELIANCE"]))
    q = pre_tick.quotes(["RELIANCE"])["quotes"]["RELIANCE"]
    assert q["state"] == "live" and "pre-open" in q["reason"]
    hol = Clock(at(11, 0))
    e = engine(hol, eod=EOD, holidays_fn=lambda: {"2026-11-05"})
    e._holidays = {"2026-11-05"}
    out3 = e.quotes(["RELIANCE"])
    assert out3["market"] == {"state": "closed", "session_date": "2026-11-04"} and out3["quotes"]["RELIANCE"]["state"] == "closed"


# ── request path: no NSE, no Breeze REST, no Yahoo ────────────────────────────────────────────────────────────────────

class ExplodingNse(FakeNse):
    def get(self, *a, **k):  # pragma: no cover - must never be reached from quotes()
        raise AssertionError("NSE called on the request path")

    def heatmap_lists(self):  # pragma: no cover
        raise AssertionError("NSE called on the request path")


def test_request_path_never_calls_nse_or_breeze_rest_and_the_poller_does():
    clock = Clock(at(10, 16))
    prov = FakeProvider(FakeBreeze())                                # its get_live_quote raises
    real = lt.LiveTicks(lambda: prov, clock=clock, enabled_fn=lambda: False)
    e = engine(clock, ticks=real, nse=ExplodingNse(clock), eod=EOD)
    out = e.quotes(["RELIANCE", "NIFTY 50", "TATASTEEL"])
    assert out["quotes"]["RELIANCE"]["source"] == "eod" and out["feed"]["breeze"] == "OFF"
    nse = FakeNse(clock)
    e._nse_getter = lambda: nse                                      # positive control: the poller is what talks to NSE
    did = e.poll_nse_once()
    assert nse.calls and did["need_stocks"] == 2 and did["need_indices"] == 1
    assert e.quotes(["TATASTEEL"])["quotes"]["TATASTEEL"]["source"] == "nse_api"


def test_no_yahoo_anywhere_in_the_live_path():
    for name in ("live_quotes.py", "live_ticks.py", "nse_live.py"):
        src = (_ROOT / "services/data-service" / name).read_text()
        for bad in ("query1.finance", "query2.finance", "finance.yahoo", "yfinance", "DirectYahooProvider", "_yahoo"):
            assert bad not in src, (name, bad)
    block = (_ROOT / "services/data-service/main.py").read_text()
    start = block.index("# ── /live/quotes + /live/status")
    end = block.index('@app.get("/provider/status")')
    for bad in ("finance.yahoo", "yfinance", "_yfinance", "DirectYahooProvider", "get_live_quote", "get_quotes("):
        assert bad not in block[start:end], bad                     # no Yahoo caller, no Breeze REST quote in the block


# ── EOD cache ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_eod_rows_are_cached_and_misses_negative_cached():
    clock = Clock(at(10, 16))
    e = engine(clock, eod=EOD)
    e.quotes(["RELIANCE", "NOPE"])
    e.quotes(["RELIANCE", "NOPE"])
    assert e.eod_calls == [["RELIANCE", "NOPE"]]                     # type: ignore[attr-defined]
    clock.t += lq.EOD_TTL_S + 1
    e.quotes(["RELIANCE", "NOPE"])
    assert e.eod_calls[-1] == ["RELIANCE"]                           # type: ignore[attr-defined]  # miss TTL is longer
    boom = lq.LiveQuotes(ticks_getter=lambda: None, nse_getter=lambda: None, eod_fn=lambda s: 1 / 0, clock=clock,
                         start_poller=False)
    assert boom.quotes(["RELIANCE"])["quotes"]["RELIANCE"]["state"] == "unavailable"   # DuckDB failure ≠ crash


def test_request_is_capped_and_normalised():
    clock = Clock(at(10, 16))
    ticks = FakeTicks(clock)
    e = engine(clock, ticks=ticks)
    out = e.quotes([f"S{i:03d}" for i in range(400)] + ["reliance.ns"])
    assert len(out["quotes"]) == lq.MAX_REQUEST and len(ticks.ensured[-1]) == lq.MAX_REQUEST
    assert "RELIANCE" in e.quotes(["reliance.ns", "nifty"])["quotes"] and "NIFTY 50" in e.quotes(["nifty"])["quotes"]


# ── the NSE fallback poller ───────────────────────────────────────────────────────────────────────────────────────────

def _gaps(calls: list[tuple[float, str]]) -> list[float]:
    return [b[0] - a[0] for a, b in zip(calls, calls[1:], strict=False)]


def test_poller_makes_no_call_without_demand_outside_the_session_or_behind_the_breaker():
    clock = Clock(at(10, 16))
    nse = FakeNse(clock)
    e = engine(clock, nse=nse)
    assert e.poll_nse_once() == {"skipped": "no demand"} and nse.calls == []
    e.quotes(["HDFCBANK"])
    nse.blocked_until = time.time() + 600
    assert e.poll_nse_once() == {"skipped": "NSE breaker open"} and nse.calls == []
    assert e.status()["nse_fallback"]["ok"] is False and "breaker" in e.status()["nse_fallback"]["last_error"]
    nse.blocked_until = 0.0
    late = Clock(at(16, 0))
    nse2 = FakeNse(late)
    e2 = engine(late, nse=nse2)
    e2.quotes(["HDFCBANK"])
    assert e2.poll_nse_once() == {"skipped": "outside the session"}
    assert [p for _, p in nse2.calls] == ["holiday-master?type=trading"]   # one calendar read a day, nothing else
    sat = Clock(at(11, 0, day=date(2026, 11, 7)))
    nse3 = FakeNse(sat)
    e3 = engine(sat, nse=nse3)
    e3.quotes(["HDFCBANK"])
    assert e3.poll_nse_once() == {"skipped": "outside the session"} and nse3.calls == []


def test_poller_learns_lists_then_refetches_only_the_covering_list_paced():
    clock = Clock(at(10, 16))
    nse = FakeNse(clock)
    e = engine(clock, nse=nse)
    e.quotes(["HDFCBANK", "RELIANCE", "NIFTY 50"])
    e.poll_nse_once()
    first = [p for _, p in nse.calls]
    assert "allIndices" in first and nl.heatmap_path("Broad Market Indices", "NIFTY 50") in first
    assert len([p for p in first if p.startswith("heatmap-symbols")]) == 3            # every list learned once
    assert all(g >= 1.2 - 1e-9 for g in _gaps(nse.calls))                               # ≥ 1.2 s between network calls
    assert e._sym_list["HDFCBANK"] == nl.heatmap_path("Broad Market Indices", "NIFTY 50")   # broad list first
    n0 = len(nse.calls)
    clock.t += 20
    e.quotes(["HDFCBANK", "RELIANCE", "NIFTY 50"])
    e.poll_nse_once()
    assert [p for _, p in nse.calls[n0:]] == ["allIndices"]                            # heatmap TTL 60 s: cache only
    n1 = len(nse.calls)
    clock.t += 61
    e.quotes(["HDFCBANK", "RELIANCE"])
    e.poll_nse_once()
    again = [p for _, p in nse.calls[n1:] if p != "allIndices"]                       # NIFTY 50 is still in demand (2 min)
    assert again == [nl.heatmap_path("Broad Market Indices", "NIFTY 50")]              # ONE list covers both names
    assert e.status()["nse_fallback"]["ok"] is True and e.status()["nse_fallback"]["lists_known"] == 3


def test_poller_skips_symbols_live_ticks_cover():
    clock = Clock(at(10, 16))
    nse = FakeNse(clock)
    ticks = FakeTicks(clock, {"HDFCBANK": tick(1000.0, clock.t - 1, 990.0), "NIFTY 50": tick(24000.0, clock.t - 0.1, 23960.6)},
                      subscribed=["HDFCBANK", "NIFTY 50"])
    e = engine(clock, ticks=ticks, nse=nse)
    e.quotes(["HDFCBANK", "NIFTY 50"])
    did = e.poll_nse_once()
    assert did["need_stocks"] == 0 and did["need_indices"] == 0
    assert [p for _, p in nse.calls] == ["holiday-master?type=trading"]


def test_nextapi_on_demand_one_name_at_a_time_and_capped():
    clock = Clock(at(10, 16))
    nse = FakeNse(clock)
    e = engine(clock, nse=nse)
    names = [f"SMALL{i}" for i in range(25)]
    e.quotes(names)
    e.poll_nse_once()                                                                  # learns lists, then ONE quote
    quotes = [p for _, p in nse.calls if p.startswith("NextApi")]
    assert len(quotes) == 1
    assert e.quotes([quotes[0].split("symbol=")[1]])["quotes"][quotes[0].split("symbol=")[1]]["source"] == "nse_api"
    clock.t += 1
    e.quotes(names)
    e.poll_nse_once()
    assert len([p for _, p in nse.calls if p.startswith("NextApi")]) == 1              # ≥ 4 s between quotes
    for _ in range(40):
        clock.t += lq.NEXTAPI_GAP_S
        e.quotes(names)
        e.poll_nse_once()
    qs = [(t, p) for t, p in nse.calls if p.startswith("NextApi")]
    assert all(g >= 4.0 - 1e-9 for g in _gaps(qs))                                      # L-CAPACITY floor, literal
    assert len({p for _, p in qs}) <= lq.NEXTAPI_MAX_SYMBOLS                          # at most 20 names served this way
    per = {}
    for t, p in qs:
        per.setdefault(p, []).append(t)
    assert all(g >= 60.0 - 1e-9 for ts in per.values() for g in _gaps([(x, "") for x in ts]))   # ≥ 60 s per symbol


def test_a_failing_nextapi_quote_is_not_retried_every_cycle():
    clock = Clock(at(10, 16))
    nse = FakeNse(clock, fail="NextApi")
    e = engine(clock, nse=nse)
    for _ in range(30):                                                                # a minute of 2 s cycles
        e.quotes(["SMALL1"])
        e.poll_nse_once()
        clock.t += lq.POLL_EVERY_S
    st = e.status()["nse_fallback"]
    assert e._nse["nextapi_calls"] == 1 and "503" in st["last_error"]                 # once per NEXTAPI_TTL_S, error kept


def test_one_nse_error_ends_the_cycle_and_marks_the_fallback_not_ok():
    clock = Clock(at(10, 16))
    nse = FakeNse(clock, fail="allIndices")
    e = engine(clock, nse=nse)
    e.quotes(["NIFTY 50", "HDFCBANK"])
    did = e.poll_nse_once()
    assert "error" in did and not any(p.startswith("heatmap-symbols") for _, p in nse.calls)
    st = e.status()["nse_fallback"]
    assert st["ok"] is False and "503" in st["last_error"]


def test_nse_cadences_never_go_below_l_capacity(monkeypatch):
    assert (lq.ALLINDICES_TTL_S, lq.HEATMAP_TTL_S) >= (15.0, 60.0) and lq.NEXTAPI_TTL_S >= 60.0 and lq.NSE_GAP_S >= 1.2
    monkeypatch.setenv("LIVE_NSE_HEATMAP_TTL_S", "5")
    assert lq._env_floor("LIVE_NSE_HEATMAP_TTL_S", 60.0, 60.0) == 60.0               # config can slow down, never speed up
    monkeypatch.setenv("LIVE_NSE_HEATMAP_TTL_S", "90")
    assert lq._env_floor("LIVE_NSE_HEATMAP_TTL_S", 60.0, 60.0) == 90.0


# ── pins ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_pins_while_open_indices_members_watchlist_and_nothing_after_hours():
    clock = Clock(at(10, 16))
    e = engine(clock, members_fn=lambda ix: ["HDFCBANK", "RELIANCE"] if ix == "NIFTY 50" else ["HDFCBANK", "AXISBANK"],
               watchlist_fn=lambda: ["DMART", "reliance"])
    pins = e.pinned_symbols()
    assert pins[:3] == ["NIFTY 50", "NIFTY BANK", "INDIA VIX"]
    assert pins[3:] == ["HDFCBANK", "RELIANCE", "AXISBANK", "DMART"] and len(pins) <= lq.PIN_CAP
    clock.t = at(18, 0)
    e._pins = (-1e9, [])
    assert e.pinned_symbols() == []
    clock.t = at(10, 16)
    nse = FakeNse(clock)
    e2 = engine(clock, nse=nse, members_fn=lambda ix: [])
    e2.quotes(["HDFCBANK"])
    e2.poll_nse_once()                                                                 # learns the NIFTY 50 heatmap list
    e2._members.clear()
    assert {"HDFCBANK", "RELIANCE", "SHRIRAMFIN"} <= set(e2.pinned_symbols())          # members from the learned list


# ── end to end: a fake Breeze client, LIVE_TICKS on ───────────────────────────────────────────────────────────────────

def test_end_to_end_fake_breeze_live_ticks_on():
    fake = FakeBreeze()
    prov = FakeProvider(fake)
    engine_ticks = lt.LiveTicks(lambda: prov, enabled_fn=lambda: True, market_hours_fn=lambda: True,
                                pins_fn=lambda: ["NIFTY 50"])
    stop = threading.Event()

    def feed():                                                      # the exchange: ticks for whatever is subscribed
        while not stop.is_set():
            h = fake.sio_rate_refresh_handler
            if h is not None and fake.on_ticks is not None:
                for name in ("TATASTEEL", "NIFTY 50"):
                    if fx.TICKS[name]["symbol"] in h.tokenlist:
                        fake.emit(fx.TICKS[name])
            stop.wait(0.05)
    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    e = lq.LiveQuotes(ticks_getter=lambda: engine_ticks, nse_getter=lambda: ExplodingNse(time.time),
                      eod_fn=lambda s: {}, session_fn=prov.is_connected, start_poller=False,
                      clock=lambda: at(10, 30) + (time.time() % 1))           # a session-hours wall clock
    engine_ticks._clock = e._clock
    try:
        deadline = time.time() + 5
        q: dict = {}
        while time.time() < deadline:
            q = e.quotes(["TATASTEEL", "NIFTY 50"])["quotes"]
            if q["TATASTEEL"]["source"] == "breeze_ws" and q["NIFTY 50"]["source"] == "breeze_ws":
                break
            time.sleep(0.1)
        assert q["TATASTEEL"]["state"] == "live" and q["TATASTEEL"]["price"] == 180.57
        assert q["NIFTY 50"]["state"] == "live" and q["NIFTY 50"]["subscribed"] is True
        st = e.status()
        assert st["subscribed"] >= 2 and st["breeze_session"] is True and st["ticks_per_min"] > 0
        assert st["unmapped_ticks"] == 0
    finally:
        stop.set()
        engine_ticks.shutdown()
        feeder.join(timeout=2)
    assert fake.handlers and all(h.sio.connected is False for h in fake.handlers)    # nothing left streaming


def test_live_ticks_off_serves_nse_and_eod_and_never_touches_breeze(monkeypatch):
    monkeypatch.delenv("LIVE_TICKS", raising=False)
    clock = Clock(at(10, 16))
    boom = lambda: (_ for _ in ()).throw(AssertionError("provider touched"))  # noqa: E731
    off = lt.LiveTicks(boom, clock=clock)                            # default kill switch: OFF
    e = engine(clock, ticks=off, eod=EOD)
    e._store_eq(nl.parse_heatmap_rows(fx.HEATMAP), at(10, 15, 20))
    q = e.quotes(["HDFCBANK", "RELIANCE"])
    assert q["feed"]["breeze"] == "OFF" and q["quotes"]["HDFCBANK"]["source"] == "nse_api"
    assert off._thread is None and e.status()["state"] == "OFF" and e.status()["enabled"] is False
    none = engine(clock, ticks=None, eod=EOD)                        # engine not initialised at all
    assert none.quotes(["RELIANCE"])["quotes"]["RELIANCE"]["source"] == "eod"


# ── main.py routes and the EOD SQL (temp DuckDB, never data/) ─────────────────────────────────────────────────────────

def test_routes_registered_and_delegate(monkeypatch):
    import main as data_service
    paths = {getattr(r, "path", None) for r in data_service.app.routes}
    assert {"/live/quotes", "/live/status", "/live/ticks"} <= paths
    clock = Clock(at(10, 16))
    eng = engine(clock, eod=EOD)
    monkeypatch.setattr(data_service, "_live_quotes", eng)
    out = data_service.live_quotes_view(symbols="RELIANCE,NIFTY 50")
    assert set(out["quotes"]) == {"RELIANCE", "NIFTY 50"} and out["market"]["state"] == "open"
    st = data_service.live_status_view()
    assert {"state", "subscribed", "ticks_per_min", "last_tick_age_s", "cap", "breeze_session", "nse_fallback"} <= set(st)
    assert {"ok", "last_ok_at"} <= set(st["nse_fallback"]) and st["cap"] == lt.MAX_SYMBOLS
    assert lt._pins_source is not None                               # main.py registered a pin source …
    pinned = engine(clock, members_fn=lambda ix: ["HDFCBANK"])
    monkeypatch.setattr(lt, "_pins_source", pinned.pinned_symbols)   # (the last data-service main imported owns the slot)
    single = lt.LiveTicks(lambda: None, pins_fn=lt._registered_pins)  # … which only init()'s singleton reads
    assert single._pins()[:4] == ["NIFTY 50", "NIFTY BANK", "INDIA VIX", "HDFCBANK"]
    assert lt.LiveTicks(lambda: None)._pins() == []                  # any other instance: no pins leak in


def test_eod_sql_on_a_temp_duckdb(monkeypatch, tmp_path):
    import main as data_service
    from storage import DuckDBStore
    store = DuckDBStore(str(tmp_path / "t.duckdb"))
    today = datetime.now(IST).date()
    d1, d2 = today.isoformat(), date.fromordinal(today.toordinal() - 1).isoformat()
    with store.writer() as con:
        con.execute("INSERT INTO nse_bhavcopy (symbol, series, date, prev_close, open, high, low, close, volume, turnover_lacs)"
                    " VALUES ('RELIANCE','EQ',?,1300,1301,1315,1299,1311,9000000,118000),"
                    " ('RELIANCE','BE',?,1300,1301,1315,1299,9999,1,1), ('RELIANCE','EQ',?,1290,1291,1301,1289,1300,1,1)",
                    [d1, d1, d2])
        con.execute("INSERT INTO market_index_daily (symbol, date, close, source) VALUES ('NIFTY50',?,23960.6,'t'),"
                    " ('NIFTY50',?,23810.85,'t')", [d1, d2])
    monkeypatch.setattr(data_service, "_store", store)
    try:
        rows = data_service._live_eod_rows(["RELIANCE", "NIFTY 50", "NOPE"])
    finally:
        store.close()
    assert rows["RELIANCE"] == {"date": d1, "close": 1311.0, "prev_close": 1300.0, "open": 1301.0, "high": 1315.0,
                                "low": 1299.0, "volume": 9000000, "value_cr": 1180.0, "table": "nse_bhavcopy"}   # EQ over BE
    assert rows["NIFTY 50"]["close"] == 23960.6 and rows["NIFTY 50"]["prev_close"] == 23810.85
    assert rows["NIFTY 50"]["table"] == "market_index_daily" and "NOPE" not in rows
