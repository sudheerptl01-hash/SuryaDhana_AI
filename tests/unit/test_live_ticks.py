"""services/data-service/live_ticks.py: subscription union+TTL+cap (A1), chg_pct preference+clamp (A5),
watchdog with flip-back (minor 15), strikes/cool-off, kill switch, teardown — all against a fake Breeze."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/data-service"))

import live_ticks as lt  # noqa: E402


class FakeBreeze:
    def __init__(self, fail_connect: int = 0):
        self.on_ticks = None
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.connects = 0
        self.disconnects = 0
        self._fail_connect = fail_connect

    def ws_connect(self):
        self.connects += 1
        if self.connects <= self._fail_connect:
            raise RuntimeError("Failed to connect to live stream")

    def ws_disconnect(self):
        self.disconnects += 1

    def subscribe_feeds(self, **kw):
        self.subscribed.append(kw["stock_code"])

    def unsubscribe_feeds(self, **kw):
        self.unsubscribed.append(kw["stock_code"])


class FakeProvider:
    def __init__(self, breeze, connected=True):
        self._breeze = breeze
        self._connected = connected

    def is_connected(self):
        return self._connected

    def _resolve_isec_code(self, sym):
        if sym == "FAILME":
            raise RuntimeError("no isec mapping")
        return {"TCS": "TATCON", "CUPID": "CUPID", "INFY": "INFTEC"}.get(sym, sym)


def make(clock, breeze=None, holdings=(), prev=None, enabled=True, hours=True):
    prov = FakeProvider(breeze or FakeBreeze())
    obj = lt.LiveTicks(lambda: prov, prev_close_fn=lambda syms: dict(prev or {}),
                       holdings_fn=lambda: list(holdings), clock=lambda: clock[0],
                       enabled_fn=lambda: enabled, market_hours_fn=lambda: hours)
    return obj, prov


def test_kill_switch_never_touches_the_provider(monkeypatch):
    monkeypatch.delenv("LIVE_TICKS", raising=False)
    assert lt.enabled() is False                                   # gate condition: default OFF
    boom = lambda: (_ for _ in ()).throw(AssertionError("provider touched"))  # noqa: E731
    obj = lt.LiveTicks(boom, enabled_fn=lt.enabled)
    st = obj.ensure(["TCS"])
    assert st["state"] == "OFF" and obj._thread is None


def test_union_ttl_cap_and_pinned_holdings():
    clock = [1000.0]
    obj, _ = make(clock, holdings=["CUPID"])
    obj.ensure(["TCS", "INFY"])
    clock[0] += 601                                                # TTL: both requests age out (10 min)
    obj.ensure(["INFY"])                                           # refresh INFY only
    target = obj._target_set()
    assert target[0] == "CUPID" and "INFY" in target and "TCS" not in target
    # cap 50, most-recently-requested first, holdings always pinned
    obj2, _ = make(clock, holdings=["CUPID"])
    for i in range(60):
        clock[0] += 1
        obj2.ensure([f"S{i:02d}"])
    tgt = obj2._target_set()
    assert len(tgt) == lt.MAX_SYMBOLS and tgt[0] == "CUPID" and "S59" in tgt and "S05" not in tgt


def test_subscribe_uses_isec_codes_diff_and_per_symbol_failure():
    clock = [0.0]
    fake = FakeBreeze()
    obj, prov = make(clock, breeze=fake, holdings=[])
    obj.ensure(["TCS", "FAILME"])
    obj._sync_subscriptions(prov)
    assert fake.subscribed == ["TATCON"]                           # ISEC code on the wire
    assert "FAILME" in obj._sub_errors                             # non-fatal
    obj.ensure(["INFY"])                                           # union grows; TCS stays (within TTL)
    obj._sync_subscriptions(prov)
    assert "INFTEC" in fake.subscribed
    clock[0] += 601
    obj.ensure(["INFY"])                                           # TCS ages out → unsubscribed
    obj._sync_subscriptions(prov)
    assert "TATCON" in fake.unsubscribed


def test_tick_ingestion_prefers_tick_close_then_fallback_and_clamps():
    clock = [100.0]
    obj, prov = make(clock, prev={"TCS": 2000.0})
    obj.ensure(["TCS", "INFY"])
    obj._sync_subscriptions(prov)
    obj._on_tick({"stock_code": "TATCON", "last": 2100.0, "close": 2100.0, "ttq": 5})
    snap = obj.snapshot(["TCS"])["TCS"]
    assert snap["prev_close"] == 2100.0 and snap["chg_pct"] == 0.0  # tick close wins over bhavcopy 2000
    obj._on_tick({"stock_code": "INFTEC", "ltp": 150.0})            # no close on tick, no bhavcopy row
    assert obj.snapshot(["INFY"])["INFY"]["chg_pct"] is None
    obj._prev_close["INFY"] = 100.0                                 # bhavcopy fallback: +50% → clamped (A5)
    s2 = obj.snapshot(["INFY"])["INFY"]
    assert s2["chg_pct"] is None and s2["hint"] == "possible corporate action"
    obj._prev_close["INFY"] = 140.0                                 # +7.1% → fine
    assert abs(obj.snapshot(["INFY"])["INFY"]["chg_pct"] - (150 / 140 - 1) * 100) < 1e-3   # snapshot rounds to 4dp


def test_watchdog_degrades_and_next_tick_flips_back():
    clock = [0.0]
    obj, prov = make(clock, hours=True)
    obj.state, obj._ws_up = lt.LIVE, True
    obj.last_tick_at = 0.0
    clock[0] = 121.0
    obj._watchdog_check()
    assert obj.state == lt.DEGRADED
    obj._isec_to_sym["TATCON"] = "TCS"
    obj._on_tick({"stock_code": "TATCON", "last": 10.0})
    assert obj.state == lt.LIVE                                     # minor 15: flip back on next tick
    # outside market hours the watchdog never fires
    obj2, _ = make(clock, hours=False)
    obj2.state, obj2.last_tick_at = lt.LIVE, 0.0
    obj2._watchdog_check()
    assert obj2.state == lt.LIVE


def test_three_strikes_cooloff_blocks_kick():
    clock = [0.0]
    obj, _ = make(clock)
    for _ in range(3):
        clock[0] += 10
        obj._register_strike("boom")
    assert obj.state == lt.DEGRADED and obj._cooloff_until == clock[0] + lt.COOLOFF_S
    obj._kick()                                                     # inside cool-off: no thread spawned
    assert obj._thread is None
    clock[0] = obj._cooloff_until + 1
    assert obj._clock() >= obj._cooloff_until                       # next kick after cool-off is allowed


def test_shutdown_is_idempotent_and_disconnects():
    clock = [0.0]
    fake = FakeBreeze()
    obj, _ = make(clock, breeze=fake)
    obj._ws_up = True
    obj.shutdown()
    obj.shutdown()
    assert obj.state == lt.OFF and fake.disconnects == 1


def test_requested_ledger_is_bounded_even_while_disabled():
    """bloomberg_verdict defect #5 (S1): with LIVE_TICKS off no worker runs, so ensure() itself
    must TTL-prune and hard-cap the request ledger instead of growing per distinct symbol forever."""
    clock = [0.0]
    obj, _ = make(clock)                                            # kill switch off in make()
    for i in range(600):                                            # 600 distinct symbols, 50/call max
        obj.ensure([f"SYM{i}"])
    assert len(obj._requested) <= lt.REQUESTED_CAP
    clock[0] += lt.SYMBOL_TTL_S + 1                                 # everything expires…
    obj.ensure(["FRESH"])                                           # …and one new ask prunes the rest
    assert set(obj._requested) == {"FRESH"}
