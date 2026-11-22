"""22 Nov spec: a genuinely quiet NSE stock stays LIVE past QUIET_LIVE_S only on NSE's own confirmation. One test (or more)
per defect the two reviews verified (wf_2d40b24a-03b, wf_45861533-2e5). Fakes: tests/unit/test_live_quotes.py (FakeTicks,
FakeNse, Clock, engine, tick) and the REAL LiveTicks with FakeBreeze/FakeProvider from tests/unit/test_live_ticks_tokens.py;
a real python-socketio Client (never connected) stands in for the handler's sio so the one-handler-per-event rule is real."""
from __future__ import annotations

import inspect
import math
import re
import sys
from pathlib import Path

from datetime import datetime

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tests/unit"))
from test_live_quotes import IST, Clock, FakeNse, FakeTicks, at, engine, tick  # noqa: E402
from test_live_ticks_tokens import FakeBreeze, FakeProvider  # noqa: E402

import live_quotes as lq  # noqa: E402
import live_ticks as lt  # noqa: E402
import nse_live as nl  # noqa: E402

socketio = pytest.importorskip("socketio")


# ── fakes on top of the suite's ───────────────────────────────────────────────────────────────────────────────────────

class VTicks(FakeTicks):
    """FakeTicks + the vouched_since accessor (a real engine with transport-gap detection)."""

    def __init__(self, clock, rows=None, vouch=None, **kw):
        super().__init__(clock, rows, **kw)
        self.vouch = vouch or {}

    def vouched_since(self, s):
        if s not in self.subs:
            return None
        return self.vouch.get(s, self.since.get(s, -math.inf))

    def transport(self):
        return {"gap_open": False, "gap_at": None, "cause": None, "vouch_from": None, "gaps": 0}


class SioHandler:
    def __init__(self):
        self.sio = socketio.Client()                 # real: one handler per event
        self.tokenlist: set[str] = set()
        self.rewatched = 0

    def rewatch(self):
        self.rewatched += 1


class SioBreeze(FakeBreeze):
    """FakeBreeze whose handler has a real socketio.Client and, like SocketEventBreeze.watch, registers 'connect' → rewatch
    on every subscribe."""

    def ws_connect(self):
        h = SioHandler()
        self.sio_rate_refresh_handler = h
        self.handlers.append(h)

    def subscribe_feeds(self, stock_token="", **kw):
        r = super().subscribe_feeds(stock_token, **kw)
        self.sio_rate_refresh_handler.sio.on("connect", self.sio_rate_refresh_handler.rewatch)
        return r


def real_ticks(clock, market=True):
    fake = SioBreeze()
    prov = FakeProvider(fake)
    obj = lt.LiveTicks(lambda: prov, clock=clock, enabled_fn=lambda: True, market_hours_fn=lambda: market,
                       pins_fn=lambda: ["NIFTY 50"])
    obj._primed = True                                                  # no prime thread, no worker thread: _step by hand
    obj._kick = lambda resync=True: obj._resync.set() if resync else None
    obj.ensure(["TATASTEEL"])
    obj._resync.set()
    assert obj._step() is True
    return obj, fake


def emit(fake, obj, sym, price, ttq):
    tok = obj._subscribed[sym]
    fake.emit({"symbol": tok, "last": str(price), "ttq": "" if " " in sym else str(ttq), "ltt": "Thu Nov  5 10:00:00 2026",
               "close": "179.93"})


def quiet_engine(clock, *, tick_age=600.0, ttq=1200, vouch_age=3600.0, price=55.0, state_t=None, sym="ILLIQ"):
    ticks = VTicks(clock, {sym: tick(price, clock.t - tick_age, 54.0, ttq=ttq, avg=price)}, subscribed=[sym],
                   vouch={sym: clock.t - vouch_age})
    return engine(clock, ticks=ticks), ticks


def put(e, sym, *, price, volume, kind, fetched, stamp=None):
    e._store_eq({sym: {"price": price, "volume": volume, "prev_close": 54.0, "stamp_epoch": stamp, "kind": kind}}, fetched)


# ── 1. transport gaps the tick engine cannot see ──────────────────────────────────────────────────────────────────────

def test_a_socketio_disconnect_unvouches_every_cached_tick_until_the_first_tick_after():
    clock = Clock(at(10, 0))
    obj, fake = real_ticks(clock)
    clock.t += 1
    emit(fake, obj, "NIFTY 50", 24000, 0)
    emit(fake, obj, "TATASTEEL", 180.5, 1000)
    sub = obj.subscribed_since("TATASTEEL")
    assert obj.vouched_since("TATASTEEL") == sub                       # no gap yet: the subscription stamp
    h = fake.sio_rate_refresh_handler
    assert set(h.sio.handlers["/"]) >= {"connect", "disconnect"}       # ours beside Breeze's rewatch
    clock.t += 30
    h.sio._trigger_event("disconnect", "/", "transport error")         # python-socketio, no _teardown_ws
    assert obj.vouched_since("TATASTEEL") == math.inf and not obj.feed_healthy()
    assert obj.subscribed_since("TATASTEEL") == sub                    # the ledger never saw it: that was the defect
    emit(fake, obj, "NIFTY 50", 24000.5, 0)                            # a late tick handled after the drop (engineio
    assert obj.vouched_since("TATASTEEL") == math.inf                  # threads; review D6): the gap stays open
    clock.t += 1.5
    h.sio.connected = True                                             # python-socketio sets this on a reconnect
    h.sio._trigger_event("connect", "/")
    assert h.rewatched == 1                                            # Breeze's 'connect' handler survived ours
    emit(fake, obj, "NIFTY 50", 24001, 0)                              # first tick after the gap
    assert obj.vouched_since("TATASTEEL") == clock.t
    assert not lq.tick_vouched(obj.snapshot(["TATASTEEL"])["TATASTEEL"]["ts"], obj.vouched_since("TATASTEEL"))
    old = h
    obj._teardown_ws(); obj._resync.set(); obj._step()                 # a torn-down socket's late event is ignored
    old.sio._trigger_event("disconnect", "/", "transport error")
    assert obj.transport()["gap_open"] is False


def test_a_silence_of_the_whole_socket_in_session_moves_the_vouched_start():
    clock = Clock(at(10, 0))
    obj, fake = real_ticks(clock)
    emit(fake, obj, "TATASTEEL", 180.5, 1000)
    for dt, moves in ((1.5, False), (2.5, True)):
        before = obj.vouched_since("TATASTEEL")
        clock.t += dt
        emit(fake, obj, "NIFTY 50", 24000, 0)
        assert (obj.vouched_since("TATASTEEL") == clock.t) is moves and (before != obj.vouched_since("TATASTEEL")) is moves
    obj2, fake2 = real_ticks(clock, market=False)                       # outside 09:15-15:30: no trade can be lost
    emit(fake2, obj2, "NIFTY 50", 24000, 0)
    clock.t += 30
    emit(fake2, obj2, "NIFTY 50", 24001, 0)
    assert obj2.transport()["gaps"] == 0


def test_after_a_transport_gap_a_quiet_tick_is_neither_live_nor_covered():
    clock = Clock(at(10, 0))
    obj, fake = real_ticks(clock)
    emit(fake, obj, "TATASTEEL", 180.5, 1000)
    clock.t += 40
    fake.sio_rate_refresh_handler.sio._trigger_event("disconnect", "/", "transport error")
    fake.sio_rate_refresh_handler.sio.connected = True                 # the reconnect (python-socketio sets it)
    clock.t += 2
    emit(fake, obj, "NIFTY 50", 24000, 0)                              # reconnected; TATASTEEL's trade in the gap was lost
    e = engine(clock, ticks=obj)
    q = e.quotes(["TATASTEEL"])["quotes"]["TATASTEEL"]
    assert q["state"] != "live" and q["reason"].startswith("reconnected 0 s ago")
    assert "TATASTEEL" not in e._covered_by_ticks(["TATASTEEL"])       # NSE's copy is fetched at once


def test_breeze_registers_no_disconnect_handler_so_ours_is_never_replaced():
    import breeze_connect.breeze_connect as bc
    src = inspect.getsource(bc.SocketEventBreeze)
    assert not re.search(r"""\.on\(\s*['"]disconnect['"]""", src)     # SDK 1.0.69: only connect_error / order / stock / connect
    c = socketio.Client()
    c.on("disconnect", lambda *a: None)
    c.on("connect", lambda: None)
    c.on("connect", lambda: None)                                      # Breeze re-registers 'connect' on every subscribe
    assert set(c.handlers["/"]) == {"connect", "disconnect"}


# ── 2. a conservative NextApi age for confirmation ────────────────────────────────────────────────────────────────────

def test_a_nextapi_copy_is_credited_only_up_to_fetch_minus_66_s():
    clock = Clock(at(10, 16))
    for fetched_after_tick, confirms in ((60.0, False), (65.9, False), (66.5, True)):
        e, _ = quiet_engine(clock, tick_age=150.0)
        t_tick = clock.t - 150.0
        put(e, "ILLIQ", price=55.0, volume=1200, kind="equity_quote", fetched=t_tick + fetched_after_tick,
            stamp=t_tick + fetched_after_tick - 8)                     # lastUpdateTime claims 8 s
        q = e.quotes(["ILLIQ"])["quotes"]["ILLIQ"]
        assert (q["state"] == "live") is confirms, (fetched_after_tick, q)
    assert lq.NEXTAPI_CONFIRM_LAG_S >= 65.2 and lq.NEXTAPI_MIN_LAG_S == 50.0   # display floor unchanged


# ── 3. copies whose age basis is the fetch time ───────────────────────────────────────────────────────────────────────

def test_a_heatmap_row_without_a_usable_stamp_never_confirms():
    clock = Clock(at(10, 16))
    e, _ = quiet_engine(clock)
    put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=clock.t - 2, stamp=None)
    q = e.quotes(["ILLIQ"])["quotes"]["ILLIQ"]
    assert q["state"] != "live" and "no time stamp" in q["reason"] and "confirmed_by" not in q
    e2, _ = quiet_engine(clock)
    put(e2, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=clock.t - 2, stamp=clock.t - 50)   # positive control
    assert e2.quotes(["ILLIQ"])["quotes"]["ILLIQ"]["state"] == "live"


# ── 4. _store_eq: honest data time, monotonic volume ──────────────────────────────────────────────────────────────────

def test_store_eq_never_lets_an_optimistic_nextapi_copy_undo_a_higher_volume():
    clock = Clock(at(10, 30))
    e, _ = quiet_engine(clock, tick_age=900.0, ttq=1200)
    t0 = clock.t - 900
    put(e, "ILLIQ", price=55.5, volume=1250, kind="heatmap", fetched=t0 + 660, stamp=t0 + 626)   # shows the missed trade
    put(e, "ILLIQ", price=55.0, volume=1200, kind="equity_quote", fetched=t0 + 675, stamp=t0 + 667)  # values ~ +610
    assert e._nse_eq["ILLIQ"]["volume"] == 1250
    q = e.quotes(["ILLIQ"])["quotes"]["ILLIQ"]
    assert (q["state"], q["source"], q["price"]) != ("live", "breeze_ws", 55.0)
    put(e, "ILLIQ", price=55.5, volume=1250, kind="heatmap", fetched=t0 + 720, stamp=t0 + 690)
    assert e._nse_eq["ILLIQ"]["kind"] == "heatmap" and e._nse_eq["ILLIQ"]["data_t"] == t0 + 690 - lq.HEATMAP_STAMP_SLACK_S
    assert e._data_t({"kind": "equity_quote", "stamp_epoch": t0 + 667}, t0 + 675) == t0 + 675 - lq.NEXTAPI_CONFIRM_LAG_S


# ── 5. non-zero volume, the open session only, the NSE copy after the vouched start and after the tick ───────────────────────────────

@pytest.mark.parametrize("label,kw,copy,live", [
    ("positive control", {}, {}, True),
    ("zero volume both sides", {"ttq": 0}, {"volume": 0}, False),
    ("different volume", {}, {"volume": 1250}, False),
    ("different price", {}, {"price": 55.05}, False),
    ("copy before the tick", {}, {"stamp_off": -10}, False),
    # variant B (owner, 22 Nov): a tick older than the vouched start is fine when NSE's copy is newer than that start
    ("tick before the vouched start, copy after it", {"vouch_age": 300.0}, {}, True),
    ("copy before the vouched start", {"vouch_age": 50.0}, {}, False),
])
def test_confirmation_gates(label, kw, copy, live):
    clock = Clock(at(10, 16))
    e, _ = quiet_engine(clock, **kw)
    t_tick = clock.t - kw.get("tick_age", 600.0)
    stamp = t_tick + copy.get("stamp_off", 500)                          # 100 s old: inside QUIET_CONFIRM_MAX_S
    put(e, "ILLIQ", price=copy.get("price", 55.0), volume=copy.get("volume", kw.get("ttq", 1200)), kind="heatmap",
        fetched=t_tick + copy.get("fetched_off", 540), stamp=stamp)
    q = e.quotes(["ILLIQ"])["quotes"]["ILLIQ"]
    assert (q["state"] == "live") is live, (label, q)
    assert len(q.get("reason", "")) <= 200


def test_no_confirmation_in_the_pre_open_or_for_a_pre_open_tick():
    pre = Clock(at(9, 12))
    e, _ = quiet_engine(pre, tick_age=200.0)
    put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=pre.t - 5, stamp=pre.t - 20)
    assert e.quotes(["ILLIQ"])["quotes"]["ILLIQ"]["state"] != "live"
    opn = Clock(at(9, 22))
    e2, _ = quiet_engine(opn, tick_age=opn.t - at(9, 10))                # last tick 09:10, in the pre-open buffer
    put(e2, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=opn.t - 5, stamp=opn.t - 20)
    q = e2.quotes(["ILLIQ"])["quotes"]["ILLIQ"]
    assert q["state"] != "live" and "pre-open" in q["reason"]


def test_an_engine_without_vouched_since_never_confirms():
    clock = Clock(at(10, 16))
    ticks = FakeTicks(clock, {"ILLIQ": tick(55.0, clock.t - 600, 54.0, ttq=1200)}, subscribed=["ILLIQ"])
    e = engine(clock, ticks=ticks)
    put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=clock.t - 5, stamp=clock.t - 50)
    assert e.quotes(["ILLIQ"])["quotes"]["ILLIQ"]["state"] != "live"


def test_quiet_confirm_max_is_a_fixed_cap(monkeypatch):
    """Round 2: the bound grew with the LIVE_NSE_QUOTE_TTL_S override (420 s at 300, 1020 s at 900). A fresh copy of the
    module under another name, so the suite's live_quotes is untouched."""
    import importlib.util
    monkeypatch.setenv("LIVE_NSE_QUOTE_TTL_S", "900")
    spec = importlib.util.spec_from_file_location("live_quotes_ttl900", lq.__file__)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.QUIET_CONFIRM_MAX_S == 240.0 and m.NEXTAPI_TTL_S == 900.0


# ── 6. the NextApi queue: every name served, NSE's rate unchanged ─────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [25, 40])
def test_nextapi_queue_serves_every_name_without_raising_the_rate(n):
    clock = Clock(at(10, 16))
    nse = FakeNse(clock)
    e = engine(clock, nse=nse)
    names = [f"SMALL{i}" for i in range(n)]
    for _ in range(int(3 * 120 * n / 20 / lq.POLL_EVERY_S)):
        e.quotes(names)
        e.poll_nse_once()
        clock.t += lq.POLL_EVERY_S
    qs = [t for t, p in nse.calls if p.startswith("NextApi")]
    assert all(b - a >= lq.NEXTAPI_SPACING_S - 1e-6 for a, b in zip(qs, qs[1:], strict=False))
    assert max(sum(1 for x in qs if a <= x < a + 120) for a in qs) <= lq.NEXTAPI_MAX_SYMBOLS   # today's ceiling
    served = {p.split("symbol=")[1] for _, p in nse.calls if p.startswith("NextApi")}
    assert served == set(names)                                          # nobody waits for ever (names 21+ used to)


# ── 7. no flap at the 120 s boundary ──────────────────────────────────────────────────────────────────────────────────

def test_a_quiet_nextapi_name_is_confirmed_before_it_reaches_120_s():
    clock = Clock(at(10, 16))
    vouch = clock.t - 3600
    rows = {"SMALL1": tick(55.0, clock.t, 54.0, ttq=1200)}
    ticks = VTicks(clock, rows, subscribed=["SMALL1"], vouch={"SMALL1": vouch})
    nse = FakeNse(clock)
    claim = lambda: datetime.fromtimestamp(clock.t - 8, IST).strftime("%d-%b-%Y %H:%M:%S")   # NSE's stamp claims ~8 s
    nse.payload = (lambda orig: lambda path: ({"equityResponse": [{"metaData": {"symbol": "SMALL1", "previousClose": "54"},
                                                                    "orderBook": {"lastPrice": "55.0"},
                                                                    "tradeInfo": {"totalTradedVolume": "1200"},
                                                                    "lastUpdateTime": claim()}]}
                                              if path.startswith("NextApi") else orig(path)))(nse.payload)
    e = engine(clock, ticks=ticks, nse=nse)
    states = []
    for _ in range(int(300 / lq.POLL_EVERY_S)):
        q = e.quotes(["SMALL1"])["quotes"]["SMALL1"]
        states.append((round(clock.t - rows["SMALL1"]["ts"]), q["state"]))
        e.poll_nse_once()
        clock.t += lq.POLL_EVERY_S
    assert all(st == "live" for _, st in states), [x for x in states if x[1] != "live"][:3]


# ── 9 (data-service half): quiet and confirmed rows carry the socket's heartbeat age ─────────────────────────────────

def test_quiet_and_confirmed_rows_carry_vouched_age_s():
    clock = Clock(at(10, 16))
    e, _ = quiet_engine(clock)
    put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=clock.t - 5, stamp=clock.t - 50)
    q = e.quotes(["ILLIQ"])["quotes"]["ILLIQ"]
    assert q["state"] == "live" and q["confirmed_by"] == "nse_heatmap" and q["vouched_age_s"] == 0.1
    assert q["confirmed_age_s"] == round(50 + lq.HEATMAP_STAMP_SLACK_S, 1)


def test_an_empty_heatmap_answer_keeps_the_list_members_off_nextapi():
    """Round 1: one [] response dropped a list's members to the NextApi queue for up to an hour (LIST_RELEARN_S)."""
    clock = Clock(at(10, 16))
    nse = FakeNse(clock)
    e = engine(clock, nse=nse)
    e.quotes(["RELIANCE"])
    e.poll_nse_once()
    path = nl.heatmap_path("Broad Market Indices", "NIFTY 50")
    assert e._sym_list["RELIANCE"] == path
    orig = nse.payload
    nse.payload = lambda p: [] if p == path else orig(p)
    for _ in range(40):
        clock.t += lq.POLL_EVERY_S
        e.quotes(["RELIANCE"])
        e.poll_nse_once()
    assert e._sym_list.get("RELIANCE") == path
    assert not any(p.startswith("NextApi") for _, p in nse.calls)


# ── 22 Nov adversarial review (D1-D5): guards the first test set did not pin ─────────────────────────────────────────

def _confirmed(e, sym="ILLIQ"):
    return e.quotes([sym])["quotes"][sym]


def test_a_resubscription_no_tick_has_proven_is_never_confirmed():
    """D1: after a lapse / eviction / re-login the tick predates the subscription; a dead re-joined token would otherwise
    read LIVE for up to 180 s on NSE copies that cannot see the trade the socket never delivered."""
    clock = Clock(at(10, 16))
    e, ticks = quiet_engine(clock, tick_age=600.0, vouch_age=300.0)
    ticks.since["ILLIQ"] = clock.t - 300.0                               # re-subscribed 300 s ago, no tick since
    t_tick = clock.t - 600.0
    put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=t_tick + 540, stamp=t_tick + 500)
    assert _confirmed(e)["state"] != "live"
    ticks.since["ILLIQ"] = clock.t - 3600.0                              # control: subscribed long before the tick
    assert _confirmed(e)["state"] == "live"


def test_across_a_transport_gap_the_copy_must_clear_the_gap_by_the_margin():
    """D2: variant B only for transport gaps, and only with NSE's copy ≥ B_GAP_MARGIN_S past the gap's end."""
    clock = Clock(at(10, 16))
    t_tick = clock.t - 600.0
    gap_end = t_tick + 400.0
    for off, live in ((lq.B_GAP_MARGIN_S - 5, False), (lq.B_GAP_MARGIN_S + 5, True)):
        e, ticks = quiet_engine(clock, tick_age=600.0, vouch_age=clock.t - gap_end)
        ticks.since["ILLIQ"] = t_tick - 3600.0                           # subscribed long before: only the gap matters
        data_t = gap_end + off
        put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=data_t + 20,
            stamp=data_t + lq.HEATMAP_STAMP_SLACK_S)
        assert (_confirmed(e)["state"] == "live") is live, off
    assert lq.B_GAP_MARGIN_S >= 30.0                                      # literal: the review's margin


def test_an_unhealthy_feed_or_an_over_age_copy_never_confirms():
    clock = Clock(at(10, 16))
    t_tick = clock.t - 600.0
    e, ticks = quiet_engine(clock)
    put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=t_tick + 540, stamp=t_tick + 500)
    assert _confirmed(e)["state"] == "live"                               # positive control
    ticks.healthy = False                                                # D5: a stall with no disconnect
    assert _confirmed(e)["state"] != "live"
    e2, _ = quiet_engine(clock)
    old = clock.t - 245.0                                                 # D5: past the fixed 240 s cap
    put(e2, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=old + 20, stamp=old + lq.HEATMAP_STAMP_SLACK_S)
    assert _confirmed(e2)["state"] != "live" and lq.QUIET_CONFIRM_MAX_S == 240.0


def test_heatmap_data_time_is_capped_below_the_fetch():
    """D2: a stamp at or after the fetch is credited no later than fetch − 10 s (heatmap data is 10-68 s old when fetched)."""
    assert lq.LiveQuotes._data_t({"kind": "heatmap", "stamp_epoch": 1000.0}, 1000.0) == 1000.0 - 10.0
    assert lq.LiveQuotes._data_t({"kind": "heatmap", "stamp_epoch": 950.0}, 1000.0) == 950.0 - 5.0


def test_a_higher_volume_wins_even_from_an_older_copy():
    """D5: the session-monotonic volume rule on its own (data-time order would keep the newer, lower volume)."""
    clock = Clock(at(10, 16))
    e, _ = quiet_engine(clock)
    t0 = clock.t - 300.0
    put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=t0 + 120, stamp=t0 + 100)   # newer data, 1200
    put(e, "ILLIQ", price=55.5, volume=1250, kind="heatmap", fetched=t0 + 70, stamp=t0 + 50)     # older data, 1250
    assert e._nse_eq["ILLIQ"]["volume"] == 1250


def test_an_engine_with_a_subscription_stamp_but_no_vouched_since_never_confirms():
    """D5: the accessor's absence (FakeTicks has subscribed_since only), not a missing stamp, must stop confirmation."""
    clock = Clock(at(10, 16))
    t_tick = clock.t - 600.0
    ticks = FakeTicks(clock, {"ILLIQ": tick(55.0, t_tick, 54.0, ttq=1200, avg=55.0)}, subscribed=["ILLIQ"],
                      since={"ILLIQ": t_tick - 3600.0})
    e = engine(clock, ticks=ticks)
    put(e, "ILLIQ", price=55.0, volume=1200, kind="heatmap", fetched=t_tick + 540, stamp=t_tick + 500)
    assert not hasattr(ticks, "vouched_since") and _confirmed(e)["state"] != "live"


def test_nse_call_spacing_is_six_seconds_literally():
    assert lq.NEXTAPI_SPACING_S >= 6.0 and lq.QUIET_PREFETCH_S >= 100.0  # D3 / D5: literals, not the constant vs itself
