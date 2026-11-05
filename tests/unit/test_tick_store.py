"""services/data-service/tick_store.py (W6 TICKS): bounded buffer + drop counter, lazy flusher,
atomic numbered parquet parts, crash-safe reads, OHLCV bars + VWAP (cumulative-ttq diff vs
per-tick qty), frozen W1 bars contract, store-status — and the live_ticks.py hook patch applied
to a COPY of the real source (anchors must stay unique; live_ticks.py itself is never edited).

All ticks are SYNTHETIC — no Breeze, no network, no data/market.duckdb.
"""
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/data-service"))

import tick_store  # noqa: E402
from tick_store import TickStore  # noqa: E402

IST = tick_store.IST
DAY = "2026-10-14"                 # fixed past date: never collides with today's live buffer


# ── the exact patch blocks handed to the PM (report build_w6.md copies these verbatim) ──────────
# Applied here to a COPY of live_ticks.py: the test fails if any anchor drifts or duplicates.

LIVE_TICKS_PATCHES = [
    (
        "from shared.breeze_cache import patch_socketio_wait\n"
        "from shared.logging import get_logger\n",
        "from shared.breeze_cache import patch_socketio_wait\n"
        "from shared.logging import get_logger\n"
        "\n"
        "import tick_store  # W6: tick persistence — lazy, kill-switched; see the _on_tick hook\n",
    ),
    (
        "        self._last_sync = 0.0\n"
        "        self._first_tick_logged = False\n",
        "        self._last_sync = 0.0\n"
        "        self._first_tick_logged = False\n"
        "        self._store: Any = None            # W6: lazy TickStore; False = persistence decided OFF\n",
    ),
    (
        "            self.last_tick_at = now\n"
        "            if self.state == DEGRADED:\n"
        "                self._set_state(LIVE, None)                              # minor 15: flip back on next tick\n",
        "            self.last_tick_at = now\n"
        "            if self.state == DEGRADED:\n"
        "                self._set_state(LIVE, None)                              # minor 15: flip back on next tick\n"
        "            # W6 TICKS: persist to parquet via tick_store — constructed lazily ONLY when a tick\n"
        "            # actually flows (zero cost while LIVE_TICKS=0). TICK_PERSIST kill switch, default ON\n"
        "            # whenever ticks flow; read once per worker life. append() never raises (strike\n"
        "            # counter in store stats) and this guard covers construction too: persistence can\n"
        "            # NEVER break the feed.\n"
        "            try:\n"
        "                if self._store is None:\n"
        "                    self._store = tick_store.get_store() if tick_store.persist_enabled() else False\n"
        "                if self._store:\n"
        "                    self._store.append(sym, tick)\n"
        "            except Exception:  # noqa: BLE001 — persistence must never break the stream\n"
        "                pass\n",
    ),
]

MAIN_PY_ANCHORS = [  # context lines the main.py patch block hangs off — must exist, once each
    "import live_ticks as live_ticks_mod\n",
    "app = FastAPI(\n    title=\"SuryaDhana — Data Service\",\n    version=\"1.0.0\",\n    lifespan=lifespan,\n)\n",
    "    try:\n        live_ticks_mod.shutdown_instance()\n    except Exception:\n        pass\n",
]

LIVE_TICKS_PATH = _ROOT / "services/data-service/live_ticks.py"
MAIN_PY_PATH = _ROOT / "services/data-service/main.py"


def iso(h: int, m: int, s: int, day: str = DAY) -> str:
    naive = datetime.strptime(f"{day} {h:02d}:{m:02d}:{s:02d}", "%Y-%m-%d %H:%M:%S")
    return IST.localize(naive).isoformat(timespec="seconds")


def tick(price, ttq=None, qty=None, bid=None, ask=None, prev_close=None, as_of=None) -> dict:
    return {"price": price, "ttq": ttq, "qty": qty, "bid": bid, "ask": ask,
            "prev_close": prev_close, "as_of": as_of or iso(9, 15, 0)}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Manual-flush store in a tmp dir, installed as the module singleton; routes read tmp too."""
    st = TickStore(base_dir=tmp_path / "ticks", flush_s=None)
    monkeypatch.setattr(tick_store, "_instance", st)
    monkeypatch.setenv("TICKS_DIR", str(tmp_path / "ticks"))
    return st


@pytest.fixture()
def client(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(tick_store.router)
    return TestClient(app)


# ── buffer bounds + append hygiene ──────────────────────────────────────────────────────────────

def test_default_cap_and_flush_cadence_match_spec():
    assert tick_store.BUFFER_CAP == 50_000 and tick_store.FLUSH_S == 30.0
    st = TickStore(base_dir="/tmp/unused-w6", flush_s=None)
    assert st._buf.maxlen == 50_000


def test_buffer_cap_drops_oldest_and_counts(tmp_path):
    st = TickStore(base_dir=tmp_path, flush_s=None, buffer_cap=1_000)
    for i in range(1_500):
        assert st.append("TCS", tick(float(i))) is True
    s = st.stats()
    assert s["buffer_rows"] == 1_000 and s["dropped"] == 500 and s["appended_total"] == 1_500
    assert st._buf[0]["price"] == 500.0            # oldest 500 evicted, newest kept


def test_append_strikes_never_raise(tmp_path):
    st = TickStore(base_dir=tmp_path, flush_s=None)
    assert st.append("TCS", {"price": "abc"}) is False        # unparseable price
    assert st.append("", {"price": 1.0}) is False             # empty symbol
    assert st.append("TCS", {}) is False                      # no price at all
    assert st.append("tcs.ns", tick(10.0)) is True            # normalized to TCS
    s = st.stats()
    assert s["append_strikes"] == 3 and s["buffer_rows"] == 1
    assert st._buf[0]["symbol"] == "TCS"


def test_junk_as_of_never_poisons_the_day_dir(tmp_path):
    st = TickStore(base_dir=tmp_path, flush_s=None)
    st.append("TCS", {"price": 10.0, "as_of": "../evil"})
    st.flush()
    dirs = [p.name for p in tmp_path.iterdir() if p.is_dir()]
    assert len(dirs) == 1 and tick_store._DATE_RE.match(dirs[0])   # today-IST, valid name


# ── flush: numbered parts, one file per day for all symbols, restart numbering, atomicity ──────

def test_flush_writes_one_part_per_day_all_symbols_and_restart_continues(tmp_path):
    st = TickStore(base_dir=tmp_path, flush_s=None)
    st.append("TCS", tick(100.0, ttq=10))
    st.append("INFY", tick(200.0, ttq=20))
    assert st.flush() == 2
    day_dir = tmp_path / DAY
    assert [p.name for p in sorted(day_dir.glob("part-*.parquet"))] == ["part-0000.parquet"]
    st.append("TCS", tick(101.0, ttq=30, as_of=iso(9, 16, 0)))
    st.flush()
    assert sorted(p.name for p in day_dir.glob("part-*.parquet")) == ["part-0000.parquet",
                                                                      "part-0001.parquet"]
    st2 = TickStore(base_dir=tmp_path, flush_s=None)       # "restart": fresh store, same dir
    st2.append("TCS", tick(102.0, ttq=40, as_of=iso(9, 17, 0)))
    st2.flush()
    assert (day_dir / "part-0002.parquet").exists()        # numbering continues, nothing overwritten
    import pyarrow.parquet as pq
    total = sum(pq.read_table(p).num_rows for p in day_dir.glob("part-*.parquet"))
    assert total == 4
    s = st.stats()
    assert s["rows_flushed_total"] == 3 and s["parts_written"] == 2 and s["last_flush_rows"] == 1
    assert s["flush_errors"] == 0 and s["last_flush_at"]


def test_corrupt_part_and_stale_tmp_never_hide_good_parts(store, client):
    store.append("TCS", tick(100.0, ttq=100, as_of=iso(9, 15, 5)))
    store.append("TCS", tick(101.0, ttq=250, as_of=iso(9, 15, 40)))
    store.flush()
    day_dir = Path(store._base) / DAY
    (day_dir / "part-0099.parquet").write_bytes(b"not a parquet file at all")   # crashed/garbage
    (day_dir / ".part-0100.parquet.tmp-999").write_bytes(b"half-written temp")  # never globbed
    body = client.get(f"/ticks/bars?symbol=TCS&date={DAY}&interval=1m").json()
    assert len(body["bars"]) == 1 and body["bars"][0]["o"] == 100.0
    assert "skipped 1 unreadable part file(s)" in body["note"]


# ── bars + VWAP: hand-checked micro fixture (cumulative ttq) ───────────────────────────────────

def _micro_fixture(store):
    rows = [  # (h, m, s, price, ttq) — deltas: n/a→0, 150, 150, 300, 200, 100
        (9, 15, 5, 100.00, 100),
        (9, 15, 40, 101.00, 250),
        (9, 16, 10, 100.50, 400),
        (9, 20, 30, 102.00, 700),
        (9, 20, 45, 101.50, 900),
        (9, 34, 10, 103.00, 1000),
    ]
    for h, m, s, p, q in rows:
        store.append("TCS", tick(p, ttq=q, as_of=iso(h, m, s)))
    store.flush()


def test_bars_5m_ohlcv_and_vwap_hand_checked(store, client):
    _micro_fixture(store)
    body = client.get(f"/ticks/bars?symbol=TCS&date={DAY}&interval=5m").json()
    assert body["symbol"] == "TCS" and body["date"] == DAY and body["interval"] == "5m"
    assert body["source"] == "icici-ws"
    assert body["bars"] == [
        {"t": "09:15", "o": 100.00, "h": 101.00, "l": 100.00, "c": 100.50, "v": 300},
        {"t": "09:20", "o": 102.00, "h": 102.00, "l": 101.50, "c": 101.50, "v": 500},
        {"t": "09:30", "o": 103.00, "h": 103.00, "l": 103.00, "c": 103.00, "v": 100},
    ]
    # VWAP by hand: (101·150 + 100.5·150 + 102·300 + 101.5·200 + 103·100) / 900 = 91425/900
    assert body["vwap"] == round(91425 / 900, 4) == 101.5833


def test_bars_1m_and_15m_rollups(store, client):
    _micro_fixture(store)
    b1 = client.get(f"/ticks/bars?symbol=TCS&date={DAY}&interval=1m").json()["bars"]
    assert b1[0] == {"t": "09:15", "o": 100.00, "h": 101.00, "l": 100.00, "c": 101.00, "v": 150}
    assert [b["t"] for b in b1] == ["09:15", "09:16", "09:20", "09:34"]
    b15 = client.get(f"/ticks/bars?symbol=TCS&date={DAY}&interval=15m").json()["bars"]
    assert b15 == [
        {"t": "09:15", "o": 100.00, "h": 102.00, "l": 100.00, "c": 101.50, "v": 800},
        {"t": "09:30", "o": 103.00, "h": 103.00, "l": 103.00, "c": 103.00, "v": 100},
    ]


def test_vwap_endpoint_running_vwap_and_total_volume(store, client):
    _micro_fixture(store)
    body = client.get(f"/ticks/vwap?symbol=TCS&date={DAY}").json()
    assert body["vwap"] == 101.5833 and body["volume"] == 900          # = last ttq − first ttq
    assert body["ticks"] == 6 and body["volume_mode"] == "cumulative-ttq"
    assert body["last_price"] == 103.0 and body["source"] == "icici-ws"


# ── volume semantics: 10k synthetic ticks, cumulative ttq, independent recompute ───────────────

def test_10k_ticks_cumulative_ttq_bars_match_independent_recompute(store, client):
    n = 10_000
    secs, prices, ttqs = [], [], []
    for i in range(n):
        secs.append(9 * 3600 + 15 * 60 + int(i * 0.27))                # 09:15:00 → 09:59:59
        prices.append(round(100 + ((i * 7) % 50) / 20, 2))             # 2-dp grid, deterministic
        ttqs.append(10.0 * (i + 1))                                    # cumulative, +10 per tick
    for i in range(n):
        store.append("TCS", tick(prices[i], ttq=ttqs[i],
                                 as_of=iso(secs[i] // 3600, (secs[i] % 3600) // 60, secs[i] % 60)))
    # interleave a second symbol to prove per-symbol separation
    store.append("INFY", tick(55.0, ttq=1.0, as_of=iso(9, 30, 0)))
    assert store.flush() == n + 1
    # independent pure-python recompute of 5m OHLCV + VWAP
    exp: dict[int, dict] = {}
    spv = svol = 0.0
    for i in range(n):
        b = (secs[i] // 300) * 300
        e = exp.setdefault(b, {"o": prices[i], "h": prices[i], "l": prices[i], "c": prices[i], "v": 0.0})
        e["h"], e["l"], e["c"] = max(e["h"], prices[i]), min(e["l"], prices[i]), prices[i]
        dv = 0.0 if i == 0 else ttqs[i] - ttqs[i - 1]                  # first obs unattributable
        e["v"] += dv
        spv += prices[i] * dv
        svol += dv
    body = client.get(f"/ticks/bars?symbol=TCS&date={DAY}&interval=5m").json()
    assert len(body["bars"]) == len(exp) == 9
    for bar in body["bars"]:
        hh, mm = map(int, bar["t"].split(":"))
        e = exp[hh * 3600 + mm * 60]
        assert (bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]) == \
               (round(e["o"], 2), round(e["h"], 2), round(e["l"], 2), round(e["c"], 2), int(e["v"]))
    assert body["vwap"] == round(spv / svol, 4)
    assert svol == 10.0 * (n - 1)                                      # sanity on the recompute itself
    infy = client.get(f"/ticks/bars?symbol=INFY&date={DAY}&interval=5m").json()
    assert len(infy["bars"]) == 1 and infy["bars"][0]["o"] == 55.0     # no cross-symbol bleed


def test_per_tick_qty_mode_when_no_ttq(store, client):
    for i in range(50):
        store.append("INFY", tick(150.0, qty=5, as_of=iso(9, 15 + i // 25, i % 25)))
    store.flush()
    body = client.get(f"/ticks/vwap?symbol=INFY&date={DAY}").json()
    assert body["volume_mode"] == "per-tick-qty" and body["volume"] == 250 and body["vwap"] == 150.0
    bars = client.get(f"/ticks/bars?symbol=INFY&date={DAY}&interval=1m").json()["bars"]
    assert [b["v"] for b in bars] == [125, 125]


def test_non_monotone_ttq_falls_back_to_qty_then_none(store, client):
    bouncing = [500, 200, 900, 100, 700, 50]                           # clearly NOT cumulative
    for i, tq in enumerate(bouncing):
        store.append("WIPRO", tick(400.0 + i, ttq=tq, qty=7, as_of=iso(9, 15, i)))
    for i, tq in enumerate(bouncing):                                  # same shape, no qty at all
        store.append("LT", tick(300.0 + i, ttq=tq, as_of=iso(9, 15, i)))
    store.flush()
    w = client.get(f"/ticks/vwap?symbol=WIPRO&date={DAY}").json()
    assert w["volume_mode"] == "per-tick-qty" and w["volume"] == 42
    lt_ = client.get(f"/ticks/vwap?symbol=LT&date={DAY}").json()
    assert lt_["volume_mode"] == "none" and lt_["vwap"] is None and lt_["volume"] == 0
    lt_bars = client.get(f"/ticks/bars?symbol=LT&date={DAY}&interval=1m").json()
    assert lt_bars["vwap"] is None and lt_bars["bars"][0]["v"] == 0    # bars still form, honest v=0
    assert "vwap unavailable" in lt_bars["note"]


def test_single_feed_reset_tolerated_as_cumulative(store, client):
    for i in range(200):
        tq = 10.0 * (i + 1) if i != 100 else 5.0                       # one reset among 199 steps
        store.append("SBIN", tick(100.0, ttq=tq, as_of=iso(9, 15 + i // 60, i % 60)))
    store.flush()
    body = client.get(f"/ticks/vwap?symbol=SBIN&date={DAY}").json()
    assert body["volume_mode"] == "cumulative-ttq"                     # ≥99 % steps non-negative
    # 197 normal +10 steps; the reset's −995 delta clips to 0; recovery step i=101 is 1020−5=+1015
    assert body["volume"] == 197 * 10 + 1015 == 2985


# ── W1 contract: empty day/symbol, key names, validation, live buffer ──────────────────────────

def test_missing_day_and_symbol_return_200_empty_bars_with_note(client):
    r = client.get("/ticks/bars?symbol=TCS&date=2026-01-02&interval=5m")
    assert r.status_code == 200
    body = r.json()
    assert body == {"symbol": "TCS", "date": "2026-01-02", "interval": "5m", "bars": [],
                    "vwap": None, "source": "icici-ws", "note": "no tick data for TCS on 2026-01-02"}
    v = client.get("/ticks/vwap?symbol=TCS&date=2026-01-02").json()
    assert v["vwap"] is None and v["volume"] == 0 and v["ticks"] == 0


def test_contract_key_names_are_frozen(store, client):
    _micro_fixture(store)
    body = client.get(f"/ticks/bars?symbol=TCS.NS&date={DAY}&interval=5m").json()   # .NS normalized
    assert {"symbol", "date", "interval", "bars", "vwap", "source"} <= set(body)
    assert all(set(b) == {"t", "o", "h", "l", "c", "v"} for b in body["bars"])
    assert body["symbol"] == "TCS" and isinstance(body["vwap"], float)


def test_query_validation_422(client):
    assert client.get(f"/ticks/bars?symbol=TCS&date={DAY}&interval=3m").status_code == 422
    assert client.get("/ticks/bars?symbol=TCS&date=14-10-2026").status_code == 422
    assert client.get("/ticks/bars").status_code == 422                # symbol required
    assert client.get(f"/ticks/bars?symbol=TCS&date={DAY}").status_code == 200   # interval defaults 1m


def test_unflushed_buffer_rows_are_visible_in_bars(store, client):
    store.append("TCS", tick(100.0, ttq=100, as_of=iso(9, 15, 5)))     # NOT flushed
    body = client.get(f"/ticks/bars?symbol=TCS&date={DAY}&interval=1m").json()
    assert len(body["bars"]) == 1 and body["bars"][0]["c"] == 100.0
    assert store.stats()["rows_flushed_total"] == 0                    # really came from the buffer


def test_store_status_route(store, client):
    store.append("TCS", tick(100.0, ttq=10))
    body = client.get("/ticks/store-status").json()
    assert body["started"] is True and body["persist_enabled"] is True
    assert body["buffer_rows"] == 1 and body["buffer_cap"] == 50_000
    assert {"rows_flushed_today", "last_flush_at", "dropped", "append_strikes",
            "flush_errors", "dir"} <= set(body)


# ── flusher thread lifecycle ───────────────────────────────────────────────────────────────────

def test_flusher_thread_lazy_start_periodic_flush_and_final_drain_on_stop(tmp_path):
    import time as _time
    st = TickStore(base_dir=tmp_path, flush_s=0.05)
    assert st._thread is None                                          # lazy: nothing before a tick
    st.append("TCS", tick(100.0, ttq=10, as_of=iso(9, 15, 0)))
    deadline = _time.time() + 3.0
    while _time.time() < deadline and not list((tmp_path / DAY).glob("part-*.parquet")):
        _time.sleep(0.02)
    assert list((tmp_path / DAY).glob("part-*.parquet")), "periodic flush never happened"
    assert st.stats()["flusher_alive"] is True
    st.append("TCS", tick(101.0, ttq=20, as_of=iso(9, 15, 1)))         # raced row → final drain
    st.stop()
    assert st.stats()["flusher_alive"] is False
    import pyarrow.parquet as pq
    total = sum(pq.read_table(p).num_rows for p in (tmp_path / DAY).glob("part-*.parquet"))
    assert total == 2 and st.stats()["buffer_rows"] == 0
    st.stop()                                                          # idempotent


def test_flush_error_drops_rows_and_counts_instead_of_requeueing(tmp_path, monkeypatch):
    st = TickStore(base_dir=tmp_path, flush_s=None)
    st.append("TCS", tick(100.0))
    monkeypatch.setattr(st, "_write_part", lambda day, rows: (_ for _ in ()).throw(OSError("disk full")))
    assert st.flush() == 0
    s = st.stats()
    assert s["flush_errors"] == 1 and s["rows_lost_on_flush_error"] == 1
    assert "disk full" in s["last_error"] and s["buffer_rows"] == 0    # bounded: never re-queued


def test_shutdown_store_flushes_and_clears_singleton(tmp_path, monkeypatch):
    st = TickStore(base_dir=tmp_path, flush_s=None)
    monkeypatch.setattr(tick_store, "_instance", st)
    st.append("TCS", tick(100.0, as_of=iso(9, 15, 0)))
    tick_store.shutdown_store()
    assert list((tmp_path / DAY).glob("part-*.parquet")) and tick_store.instance() is None


# ── the live_ticks hook: patch a COPY of the real source and drive it ──────────────────────────

def _load_patched_live_ticks(tmp_path):
    src = LIVE_TICKS_PATH.read_text()
    if "W6 TICKS" not in src:                          # pre-integration: apply the patch blocks
        for old, new in LIVE_TICKS_PATCHES:
            assert src.count(old) == 1, f"live_ticks.py anchor drifted/duplicated: {old[:60]!r}"
            src = src.replace(old, new)
    target = tmp_path / "live_ticks_patched.py"
    target.write_text(src)
    spec = importlib.util.spec_from_file_location("live_ticks_patched", target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_ticks_patched"] = mod
    spec.loader.exec_module(mod)
    return mod


def _mk_lt(mod):
    obj = mod.LiveTicks(lambda: None, clock=lambda: 1000.0)
    obj._isec_to_sym["TATCON"] = "TCS"
    return obj


PAYLOAD = {"stock_code": "TATCON", "last": 2100.0, "close": 2080.0, "ttq": 500,
           "bPrice": 2099.5, "sPrice": 2100.5}


def test_hook_persists_ticks_and_is_lazy(tmp_path, monkeypatch):
    monkeypatch.delenv("TICK_PERSIST", raising=False)                  # default ON
    monkeypatch.setenv("TICKS_DIR", str(tmp_path / "hook-ticks"))
    monkeypatch.setattr(tick_store, "_instance", None)
    mod = _load_patched_live_ticks(tmp_path)
    obj = _mk_lt(mod)
    assert tick_store.instance() is None                               # zero cost before any tick
    obj._on_tick(PAYLOAD)
    st = tick_store.instance()
    assert st is not None and str(st._base).startswith(str(tmp_path))  # constructed on first tick
    assert obj._ticks["TCS"]["price"] == 2100.0                        # feed bookkeeping intact
    row = st._buf[-1]
    assert (row["symbol"], row["price"], row["ttq"], row["bid"], row["ask"], row["prev_close"]) == \
           ("TCS", 2100.0, 500.0, 2099.5, 2100.5, 2080.0)
    st.stop()


def test_hook_kill_switch_tick_persist_0(tmp_path, monkeypatch):
    monkeypatch.setenv("TICK_PERSIST", "0")
    monkeypatch.setattr(tick_store, "_instance", None)
    mod = _load_patched_live_ticks(tmp_path)
    obj = _mk_lt(mod)
    obj._on_tick(PAYLOAD)
    assert obj._ticks["TCS"]["price"] == 2100.0                        # feed unaffected
    assert tick_store.instance() is None and obj._store is False       # decided OFF, cached


def test_hook_store_failure_never_breaks_the_feed(tmp_path, monkeypatch):
    monkeypatch.delenv("TICK_PERSIST", raising=False)
    st = TickStore(base_dir=tmp_path / "t", flush_s=None)
    monkeypatch.setattr(st, "append", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(tick_store, "_instance", st)
    mod = _load_patched_live_ticks(tmp_path)
    obj = _mk_lt(mod)
    obj._on_tick(PAYLOAD)                                              # must not raise
    obj._on_tick({**PAYLOAD, "last": 2101.0})                          # and must keep flowing
    assert obj._ticks["TCS"]["price"] == 2101.0


def test_hook_does_not_regress_existing_live_ticks_behaviour(tmp_path, monkeypatch):
    """The patched module still passes the A5 preference/clamp semantics around the hook site."""
    monkeypatch.setenv("TICK_PERSIST", "0")                            # isolate: no persistence
    mod = _load_patched_live_ticks(tmp_path)
    obj = _mk_lt(mod)
    obj._on_tick(PAYLOAD)
    snap = obj.snapshot(["TCS"])["TCS"]
    assert snap["prev_close"] == 2080.0 and abs(snap["chg_pct"] - (2100 / 2080 - 1) * 100) < 1e-3
    obj.state = mod.DEGRADED
    obj._on_tick({**PAYLOAD, "last": 2102.0})
    assert obj.state == mod.LIVE                                       # minor-15 flip still works


def test_main_py_patch_anchors_exist():
    """The PM's main.py patch block hangs off these exact context lines (skip once applied)."""
    src = MAIN_PY_PATH.read_text()
    if "tick_store_mod" in src:
        return                                                         # already integrated
    for anchor in MAIN_PY_ANCHORS:
        assert src.count(anchor) == 1, f"main.py anchor drifted/duplicated: {anchor[:60]!r}"


def test_overlapping_flushes_never_reuse_a_part_index(store, monkeypatch):
    """19 Oct resilience review: stop()'s final flush can overlap a slow in-flight flush (10 s join
    timeout). Without the write lock both picked the same part index and the second os.replace
    overwrote the first part — silently losing ticks. Both batches must survive as distinct parts."""
    import threading
    import time as _t

    import pyarrow.parquet as pq

    real = store._write_part

    def slow_write(day, rows):
        _t.sleep(0.3)                                    # widen the race window
        return real(day, rows)
    monkeypatch.setattr(store, "_write_part", slow_write)

    for i in range(50):
        store.append("TCS", tick(100 + i, ttq=1000 + i))
    t1 = threading.Thread(target=store.flush)
    t1.start()
    _t.sleep(0.05)                                       # first flush has drained and is writing
    for i in range(30):
        store.append("INFY", tick(200 + i, ttq=2000 + i))
    store.flush()                                        # the overlapping "shutdown" flush
    t1.join()

    parts = sorted(store._base.glob("*/part-*.parquet"))
    assert len(parts) == 2 and len({p.name for p in parts}) == 2
    assert sum(pq.read_table(p).num_rows for p in parts) == 80   # nothing overwritten
