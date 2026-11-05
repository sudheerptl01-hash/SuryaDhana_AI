"""LV-DATA (5 Nov 2026): the websocket token mapping that fixes the September "L1 ticks silent" note, the raised cap with
its eviction order, index streams, the teardown zombie fix and the provider's token resolution — against recorded ticks
(test_live_fixtures.TICKS, the L-CAPACITY probe) and a fake Breeze that mimics breeze_connect 1.0.69's websocket API.
Negative controls: the old isec-keyed lookup finds none of the recorded ticks; ws_disconnect alone leaves the socket up."""
from __future__ import annotations

import io
import sys
import time
import types
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/data-service"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_ticks as lt  # noqa: E402
import test_live_fixtures as fx  # noqa: E402
from providers.icici_breeze_provider import ICICIBreezeProvider, parse_nse_master_tokens  # noqa: E402

EQ, IDX = parse_nse_master_tokens(fx.master_rows())


# ── fakes ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

class FakeSio:
    def __init__(self) -> None:
        self.connected = True
        self.disconnects = 0

    def disconnect(self) -> None:
        self.connected = False
        self.disconnects += 1


class FakeHandler:
    def __init__(self) -> None:
        self.sio = FakeSio()
        self.tokenlist: set[str] = set()


class FakeBreeze:
    """breeze_connect 1.0.69's websocket surface: ws_connect builds sio_rate_refresh_handler; subscribe_feeds(stock_token=[…])
    joins the tokens and returns {'message': …} — or, like the SDK, a plain 'Exception while subscribing…' string; ws_disconnect
    drops the handler reference WITHOUT closing its socket (the zombie L-CAPACITY found)."""

    def __init__(self, fail_tokens: tuple[str, ...] = ()) -> None:
        self.on_ticks = None
        self.sio_rate_refresh_handler: FakeHandler | None = None
        self.handlers: list[FakeHandler] = []
        self.calls: list[tuple] = []
        self.fail = set(fail_tokens)

    def ws_connect(self) -> None:
        h = FakeHandler()
        self.sio_rate_refresh_handler = h
        self.handlers.append(h)
        self.calls.append(("ws_connect",))

    def ws_disconnect(self) -> list:
        self.calls.append(("ws_disconnect",))
        self.sio_rate_refresh_handler = None                       # the socket stays connected: the zombie
        return [{"message": "Rate Refresh Disconnected"}]

    def subscribe_feeds(self, stock_token="", **kw):
        toks = list(stock_token)
        self.calls.append(("subscribe", toks, kw))
        if any(t in self.fail for t in toks):
            return "Exception while subscribing to feeds Live stream is not connected"
        assert self.sio_rate_refresh_handler is not None
        self.sio_rate_refresh_handler.tokenlist.update(toks)
        return {"message": f"Stock {toks} subscribed successfully"}

    def unsubscribe_feeds(self, stock_token="", **kw):
        toks = list(stock_token)
        self.calls.append(("unsubscribe", toks))
        if self.sio_rate_refresh_handler is not None:
            self.sio_rate_refresh_handler.tokenlist.difference_update(toks)
        return {"message": "unsubscribed"}

    def emit(self, tick: dict) -> None:
        assert self.on_ticks is not None
        self.on_ticks(dict(tick))

    def subscribed_tokens(self) -> list[str]:
        return [t for c in self.calls if c[0] == "subscribe" for t in c[1]]


class FakeProvider:
    def __init__(self, breeze: FakeBreeze) -> None:
        self._breeze = breeze
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    def _resolve_ws_token(self, name: str) -> str:
        up = name.upper()
        if up in EQ:
            return "4.1!" + EQ[up]
        if up in IDX:
            return "4.1!" + IDX[up]
        if up.startswith("S") and up[1:].isdigit():                 # synthetic names for the cap tests
            return "4.1!9" + up[1:]
        raise LookupError(f"no websocket token for {name}")

    def get_live_quote(self, ticker):  # pragma: no cover - must never be reached
        raise AssertionError("Breeze REST on the tick path")


def make(clock, breeze=None, holdings=(), pins=(), prev=None):
    fake = breeze or FakeBreeze()
    prov = FakeProvider(fake)
    obj = lt.LiveTicks(lambda: prov, prev_close_fn=lambda syms: dict(prev or {}), holdings_fn=lambda: list(holdings),
                       clock=lambda: clock[0], enabled_fn=lambda: False, market_hours_fn=lambda: True,
                       pins_fn=lambda: list(pins))
    return obj, prov, fake


def connect(obj, prov):
    """Drive the worker by hand (no thread): connect + first subscription sync."""
    obj._resync.set()
    assert obj._step() is True
    return obj


# ── security master → tokens ──────────────────────────────────────────────────────────────────────────────────────────

def test_master_maps_the_nse_symbol_to_its_eq_token_never_isec_or_warrant_rows():
    assert EQ["HDFCBANK"] == "1333"                                 # not the W3 warrant row's 17320
    assert (EQ["TATASTEEL"], EQ["ICICIBANK"], EQ["RELIANCE"]) == ("3499", "4963", "2885")
    assert "HDFBAN" not in EQ and "TATSTE" not in EQ                # keyed by the NSE symbol, never the isec ShortName
    assert "ACROPETAL" not in EQ                                    # placeholder token "0" of a dead row
    assert EQ["IFL"] == "00015"                                     # a BE row maps when there is no EQ row
    assert IDX["NIFTY 50"] == "NIFTY 50" and IDX["INDIA VIX"] == "INDIA VIX" and IDX["NIFTY CPSE"] == "Nifty CPSE"


def test_provider_resolves_master_first_then_get_names_first_token_and_caches_misses(monkeypatch):
    class Names:
        calls: list[str] = []

        def get_names(self, exchange_code, stock_code):
            self.calls.append(stock_code)
            if stock_code == "NEWCO":
                return {"isec_token_level1": "4.1!7777 8888 9999", "exchange_stock_code": "NEWCO"}
            if stock_code == "SHORTNM":                             # matched another company's isec ShortName
                return {"isec_token_level1": "4.1!5555", "exchange_stock_code": "OTHERCO"}
            raise RuntimeError("Could not find the stock code")

    prov = ICICIBreezeProvider("k", "s", "t")
    prov._breeze = Names()
    monkeypatch.setattr(prov, "_nse_master_rows", lambda: iter(fx.master_rows()))
    assert prov._resolve_ws_token("HDFCBANK") == "4.1!1333"
    assert prov._resolve_ws_token("hdfcbank.ns") == "4.1!1333"
    assert prov._resolve_ws_token("NIFTY 50") == "4.1!NIFTY 50"
    assert prov._resolve_ws_token("NIFTY FIN SERVICE") == "4.1!NIFTY FIN SERVICE"
    assert prov._resolve_ws_token("NEWCO") == "4.1!7777"           # fallback: the FIRST token only
    with pytest.raises(LookupError):
        prov._resolve_ws_token("SHORTNM")
    with pytest.raises(LookupError):
        prov._resolve_ws_token("NOPE")
    with pytest.raises(LookupError):
        prov._resolve_ws_token("NOPE")                              # cached miss: get_names not called again
    assert prov._breeze.calls == ["NEWCO", "SHORTNM", "NOPE"]       # master hits never touch get_names


def test_master_rows_come_from_memory_or_the_cached_zip_and_never_import_breeze(monkeypatch, tmp_path):
    import shared.breeze_cache as bcache
    monkeypatch.delitem(sys.modules, "breeze_connect.breeze_connect", raising=False)
    monkeypatch.setattr(bcache, "CACHE", tmp_path / "missing.zip")
    prov = ICICIBreezeProvider("k", "s", "t")
    assert list(prov._nse_master_rows()) == []                      # nothing anywhere: no rows, no import, no download
    assert "breeze_connect.breeze_connect" not in sys.modules
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("NSEScripMaster.txt", fx.MASTER)
    (tmp_path / "SecurityMaster.zip").write_bytes(buf.getvalue())
    monkeypatch.setattr(bcache, "CACHE", tmp_path / "SecurityMaster.zip")
    assert prov.ws_token_maps()[0]["HDFCBANK"] == "1333"           # the cached archive, read-only
    mod = types.ModuleType("breeze_connect.breeze_connect")
    mod.zip = zipfile.ZipFile(io.BytesIO(buf.getvalue()))           # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "breeze_connect.breeze_connect", mod)
    assert parse_nse_master_tokens(ICICIBreezeProvider("k", "s", "t")._nse_master_rows())[0]["TATASTEEL"] == "3499"


# ── tick mapping (the root cause) ─────────────────────────────────────────────────────────────────────────────────────

def test_recorded_ticks_map_by_token_and_the_old_isec_lookup_finds_none_of_them():
    clock = [1_000.0]
    obj, prov, fake = make(clock)
    obj.ensure(["TATASTEEL", "ICICIBANK", "NIFTY 50", "NIFTY BANK"])
    connect(obj, prov)
    assert set(fake.subscribed_tokens()) == {"4.1!3499", "4.1!4963", "4.1!NIFTY 50", "4.1!NIFTY BANK"}
    for name in ("TATASTEEL", "ICICIBANK", "NIFTY 50", "NIFTY BANK"):
        fake.emit(fx.TICKS[name])
    snap = obj.snapshot()
    assert snap["TATASTEEL"]["price"] == 180.57 and snap["ICICIBANK"]["price"] == 1466.9
    assert snap["NIFTY 50"]["price"] == 24389.5 and snap["NIFTY BANK"]["price"] == 57107.1
    assert obj.unmapped_ticks == 0

    # NEGATIVE CONTROL 1: the pre-fix lookup (stock_code/symbol/stock_name through an isec-keyed map)
    old_isec_to_sym = {"TATSTE": "TATASTEEL", "ICIBAN": "ICICIBANK", "NIFTY": "NIFTY 50", "CNXBAN": "NIFTY BANK"}
    for name in ("TATASTEEL", "ICICIBANK", "NIFTY 50", "NIFTY BANK"):
        raw = str(lt._first(fx.TICKS[name], ("stock_code", "symbol", "stock_name"))).upper()
        assert old_isec_to_sym.get(raw, raw) != name                # lands under '4.1!…': no consumer finds it

    # NEGATIVE CONTROL 2: an engine that only knows isec codes (the old subscription bookkeeping) maps nothing
    obj2, _, _ = make(clock)
    obj2._isec_to_sym.update(old_isec_to_sym)
    for name in ("TATASTEEL", "ICICIBANK", "NIFTY 50", "NIFTY BANK"):
        obj2._on_tick(dict(fx.TICKS[name]))
    assert obj2.snapshot() == {} and obj2.unmapped_ticks == 4      # counted, never stored under a raw key


def test_tick_fields_units_and_ltt():
    clock = [1_000.0]
    obj, prov, fake = make(clock)
    obj.ensure(["TATASTEEL", "NIFTY 50"])
    connect(obj, prov)
    fake.emit(fx.TICKS["TATASTEEL"])
    fake.emit(fx.TICKS["NIFTY 50"])
    t = obj.snapshot(["TATASTEEL"])["TATASTEEL"]
    assert (t["ttq"], t["avg_price"], t["bid"], t["ask"]) == (8712469.0, 181.62, 180.56, 180.63)
    assert (t["open"], t["high"], t["low"], t["prev_close"]) == (182.29, 182.66, 180.3, 179.93)   # close = previous close
    assert abs(t["chg_pct"] - (180.57 / 179.93 - 1) * 100) < 1e-3
    assert t["ltt_epoch"] == time.mktime(time.strptime("Thu Nov  5 10:21:55 2026", "%a %b %d %H:%M:%S %Y"))
    assert t["token"] == "4.1!3499" and t["kind"] == "equity"
    i = obj.snapshot(["NIFTY 50"])["NIFTY 50"]
    assert i["bid"] is None and i["ask"] is None and i["ttq"] is None and i["kind"] == "index"   # '' on index ticks
    assert lt.parse_ltt("") is None and lt.parse_ltt("garbage") is None and lt._num("15823.59C") == 15823.59


def test_index_names_aliases_legacy_spellings_and_silent_streams():
    clock = [1_000.0]
    obj, prov, fake = make(clock)
    obj.ensure(["NIFTY FINANCIAL SERVICES", "NIFTY CPSE", "nifty", "reliance.ns", "NOT A VALID;NAME"])
    connect(obj, prov)
    toks = set(fake.subscribed_tokens())
    assert "4.1!NIFTY FIN SERVICE" in toks                          # NSE spelling → Breeze's index token
    assert "4.1!NIFTY 50" in toks and "4.1!2885" in toks            # legacy 'NIFTY' and '.NS' normalised
    assert not any("CPSE" in t for t in toks)                       # silent on Breeze (L-CAPACITY): NSE fallback instead
    assert "NIFTY CPSE" in obj.status()["unresolved"]
    fake.emit({**fx.TICKS["NIFTY 50"], "symbol": "4.1!NIFTY FIN SERVICE", "stock_name": "NIFTY FIN SERVICE"})
    assert "NIFTY FINANCIAL SERVICES" in obj.snapshot()
    assert lt.canonical("Nifty  Bank") == "NIFTY BANK" and lt.canonical("M&M") == "M&M" and lt.canonical("A B;C") is None


# ── cap, pins, eviction ───────────────────────────────────────────────────────────────────────────────────────────────

def test_cap_is_l_capacity_safe_and_covers_index_plus_members():
    assert 51 < lt.MAX_SYMBOLS <= 500                               # NIFTY + 50 members fit; ≤ L-CAPACITY's 500
    assert lt.cap_from_env(None) == lt.cap_from_env('') == 300      # default: the live contract's 300
    assert lt.cap_from_env('450') == 450 and lt.cap_from_env(' 500 ') == 500
    # negative controls: never above the measured 500, never below index + members, junk → the default
    assert lt.cap_from_env('1040') == 500 and lt.cap_from_env('10') == 52 and lt.cap_from_env('lots') == 300
    assert lt.REQUESTED_CAP >= lt.MAX_SYMBOLS


def test_eviction_order_holdings_then_pins_then_most_recent_requests():
    clock = [1_000.0]
    pins = ["NIFTY 50", "NIFTY BANK", "INDIA VIX"] + [f"S{i:03d}" for i in range(900, 950)]   # index + 50 members
    obj, prov, fake = make(clock, holdings=["RELIANCE"], pins=pins)
    n = lt.MAX_SYMBOLS + 100                                        # more requests than the cap, whatever it is set to
    for i in range(n):
        clock[0] += 1
        obj.ensure([f"S{i:03d}"])
    target = obj._target_set()
    assert len(target) == lt.MAX_SYMBOLS
    assert target[0] == "RELIANCE" and target[1:1 + len(pins)] == pins
    assert f"S{n - 1:03d}" in target and "S000" not in target        # most recent requests win the remaining slots
    connect(obj, prov)
    subs = [c for c in fake.calls if c[0] == "subscribe"]
    assert all(len(c[1]) <= lt.SUB_CHUNK for c in subs) and sum(len(c[1]) for c in subs) == lt.MAX_SYMBOLS
    assert all(c[2] == {"get_exchange_quotes": True, "get_market_depth": False} for c in subs)
    clock[0] += lt.SYMBOL_TTL_S + 1                                 # every request ages out; pins and holdings stay
    obj._resync.set()
    obj._step()
    assert obj.status()["subscribed"] == 1 + len(pins)
    dropped = [t for c in fake.calls if c[0] == "unsubscribe" for t in c[1]]
    assert len(dropped) == lt.MAX_SYMBOLS - 1 - len(pins) and "4.1!2885" not in dropped


def test_a_failed_subscribe_string_is_not_marked_subscribed_and_is_retried():
    clock = [1_000.0]
    fake = FakeBreeze(fail_tokens=("4.1!3499",))
    obj, prov, _ = make(clock, breeze=fake)
    obj.ensure(["TATASTEEL"])
    connect(obj, prov)
    assert not obj.is_subscribed("TATASTEEL") and "TATASTEEL" in obj.status()["sub_errors"]
    fake.fail.clear()
    obj._resync.set()
    obj._step()
    assert obj.is_subscribed("TATASTEEL") and "TATASTEEL" not in obj.status()["sub_errors"]


def test_ensure_only_forces_a_resync_for_new_symbols():
    clock = [1_000.0]
    obj, prov, fake = make(clock)
    obj._enabled = lambda: True
    obj._kick = lambda resync=True: obj._resync.set() if resync else None     # no thread: record the decision only
    obj._ws_up = True
    obj.ensure(["TATASTEEL"])
    assert obj._resync.is_set()
    obj._resync.clear()
    obj._sync_subscriptions(prov)
    obj.ensure(["TATASTEEL"])                                       # already subscribed: no churn
    assert not obj._resync.is_set()


# ── health: heartbeat, ticks/min, first-tick verification ─────────────────────────────────────────────────────────────

def test_heartbeat_ticks_per_min_and_no_first_tick():
    clock = [10_000.0]
    obj, prov, fake = make(clock)
    obj.ensure(["TATASTEEL", "ICICIBANK", "NIFTY 50"])
    connect(obj, prov)
    for k in range(120):
        clock[0] = 10_000.0 + k / 60                                 # 120 index ticks in 2 s
        fake.emit(fx.TICKS["NIFTY 50"])
    fake.emit(fx.TICKS["TATASTEEL"])
    assert obj.ticks_per_min() == 121 and obj.feed_healthy()
    clock[0] += 61
    st = obj.status()
    assert st["ticks_per_min"] == 0 and not obj.feed_healthy()      # no tick for > 10 s: the feed is not healthy
    assert st["no_first_tick"]["symbols"] == ["ICICIBANK"]          # subscribed > 60 s ago and never ticked
    assert st["cap"] == lt.MAX_SYMBOLS and st["subscribed"] == 3


# ── teardown (the zombie) and provider swap ───────────────────────────────────────────────────────────────────────────

def test_teardown_closes_the_handlers_socket_and_clears_its_tokens():
    clock = [1_000.0]
    obj, prov, fake = make(clock)
    obj.ensure(["TATASTEEL", "NIFTY 50"])
    connect(obj, prov)
    h = fake.handlers[-1]
    assert h.tokenlist == {"4.1!3499", "4.1!NIFTY 50"} and h.sio.connected
    obj.shutdown()
    assert ("ws_disconnect",) in fake.calls
    assert h.sio.connected is False and h.sio.disconnects == 1 and h.tokenlist == set()
    assert obj.status()["subscribed"] == 0 and obj.state == lt.OFF


def test_negative_control_ws_disconnect_alone_leaves_the_socket_up():
    fake = FakeBreeze()
    fake.ws_connect()
    fake.sio_rate_refresh_handler.tokenlist.add("4.1!3499")         # type: ignore[union-attr]
    h = fake.handlers[-1]
    fake.ws_disconnect()
    assert h.sio.connected is True and h.tokenlist == {"4.1!3499"}  # what the old _teardown_ws left behind


def test_a_replaced_broker_client_tears_down_the_old_socket_and_resubscribes_on_the_new_one():
    clock = [1_000.0]
    obj, prov, old = make(clock)
    obj.ensure(["TATASTEEL"])
    connect(obj, prov)
    old_h = old.handlers[-1]
    new = FakeBreeze()
    prov._breeze = new                                              # /provider/configure after the daily login
    obj._step()                                                     # notices the swap, tears down
    obj._step()                                                     # reconnects on the new client
    assert old_h.sio.connected is False and ("ws_disconnect",) in old.calls
    assert ("ws_connect",) in new.calls and "4.1!3499" in new.subscribed_tokens()
    new.emit(fx.TICKS["TATASTEEL"])
    assert obj.snapshot(["TATASTEEL"])["TATASTEEL"]["price"] == 180.57


def test_lost_session_parks_disconnected_and_kill_switch_defaults_off(monkeypatch):
    clock = [1_000.0]
    obj, prov, fake = make(clock)
    obj.ensure(["TATASTEEL"])
    connect(obj, prov)
    prov.connected = False
    assert obj._step() is False and obj.state == lt.DISCONNECTED
    assert fake.handlers[-1].sio.connected is False
    monkeypatch.delenv("LIVE_TICKS", raising=False)
    assert lt.enabled() is False                                    # still default OFF in code; the PM flips .env


# ── 5 Nov: a restart after the close keeps today's last prices (tick-store priming) ──────────────────────────────────

def _tick_parquet(day_dir, rows):
    import pandas as pd

    day_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["symbol", "ts", "price", "qty", "ttq", "bid", "ask", "prev_close"]).to_parquet(day_dir / "part-0000.parquet")


def _closed_engine(clock, market_open=False):
    return lt.LiveTicks(lambda: None, clock=lambda: clock[0], enabled_fn=lambda: False, market_hours_fn=lambda: market_open)


def test_after_the_close_a_restart_primes_todays_last_tick_per_symbol(tmp_path):
    from datetime import datetime as _dt

    t_1730 = _dt.fromisoformat("2026-11-05T17:30:00+05:30").timestamp()
    _tick_parquet(tmp_path / "2026-11-05", [
        ["RELIANCE", "2026-11-05T15:29:58+05:30", 1310.0, 10, 9_000_000, 1309.9, 1310.1, 1311.0],
        ["RELIANCE", "2026-11-05T15:29:59+05:30", 1316.0, 5, 9_100_000, 1315.9, 1316.1, 1311.0],
        ["NIFTY 50", "2026-11-05T16:30:51+05:30", 24536.6, None, None, None, None, 23960.6],
        ["TCS", "2026-11-05T15:29:50+05:30", 3900.0, 1, 100, None, None, 3890.0],
    ])
    obj = _closed_engine([t_1730])
    obj._ticks["TCS"] = {"price": 3999.0, "ts": t_1730 - 5, "prev_close": 3890.0}       # a tick this process received
    assert obj.prime_from_store(tmp_path) == 2
    snap = obj.snapshot(["RELIANCE", "NIFTY 50", "TCS"])
    rel = snap["RELIANCE"]
    assert rel["price"] == 1316.0 and rel["prev_close"] == 1311.0 and rel["ttq"] == 9_100_000
    assert rel["ts"] == _dt.fromisoformat("2026-11-05T15:29:59+05:30").timestamp() and rel["ltt_epoch"] == rel["ts"]
    assert snap["NIFTY 50"]["price"] == 24536.6
    assert snap["TCS"]["price"] == 3999.0                                                # negative control: never over a real tick


def test_priming_never_runs_in_session_or_without_todays_store(tmp_path):
    from datetime import datetime as _dt

    t_1100 = _dt.fromisoformat("2026-11-05T11:00:00+05:30").timestamp()
    _tick_parquet(tmp_path / "2026-11-05", [["RELIANCE", "2026-11-05T10:59:00+05:30", 1316.0, 5, 1, None, None, 1311.0]])
    live = _closed_engine([t_1100], market_open=True)
    assert live.prime_from_store(tmp_path) == 0 and live.snapshot() == {}   # a primed tick could pass for quiet-live
    t_next = _dt.fromisoformat("2026-11-06T08:30:00+05:30").timestamp()
    assert _closed_engine([t_next]).prime_from_store(tmp_path) == 0          # next morning: yesterday's store is never today's
