"""G7 — DuckDB read concurrency (Terminal v2 PLAN 1.5, R-ARCH §2.3 / fix 2).

The readers-writer lock (shared reads, exclusive writes, writer preferred, self-deadlock impossible), the
``read()`` / ``reader()`` / ``write()`` / ``writer()`` API on per-call cursors, the legacy ``store._lock`` staying the
exclusive side (negative control), and the §2.3 harness as a perf test: ten concurrent distinct-symbol history
reads must take at most 2× one such read (they took the SUM of ten under the old single ``threading.Lock``).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from storage.duckdb_store import DuckDBStore, _RWLock  # noqa: E402


# ── the lock itself ─────────────────────────────────────────────────────────────────────────────────────────────
def _hold_read(rw: _RWLock, seconds: float, out: list[float]) -> None:
    rw.acquire_read()
    try:
        time.sleep(seconds)
        out.append(time.monotonic())
    finally:
        rw.release_read()


def test_readers_share_and_a_writer_is_exclusive():
    rw = _RWLock()
    out: list[float] = []
    t0 = time.monotonic()
    ths = [threading.Thread(target=_hold_read, args=(rw, 0.1, out)) for _ in range(8)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert time.monotonic() - t0 < 0.45, "eight 100 ms readers must overlap (wall ≈ 0.1 s, not 0.8 s)"
    assert not rw.locked()

    # negative control: while a writer holds the lock a reader waits
    rw.acquire_write()
    entered: list[float] = []
    t = threading.Thread(target=_hold_read, args=(rw, 0.0, entered))
    t.start()
    time.sleep(0.15)
    assert entered == [], "a reader got in while the writer held the lock"
    rw.release_write()
    t.join(2)
    assert len(entered) == 1


def test_waiting_writer_blocks_new_readers_and_gets_in_first():
    rw = _RWLock()
    order: list[str] = []
    rw.acquire_read()                                   # reader A holds

    def writer() -> None:
        rw.acquire_write()
        order.append("writer")
        rw.release_write()

    def late_reader() -> None:
        rw.acquire_read()
        order.append("reader")
        rw.release_read()

    tw = threading.Thread(target=writer)
    tw.start()
    time.sleep(0.05)                                    # writer is now waiting on A
    tr = threading.Thread(target=late_reader)
    tr.start()
    time.sleep(0.05)
    assert order == [], "a late reader must not slip past a waiting writer (writer preference)"
    rw.release_read()
    tw.join(2)
    tr.join(2)
    assert order == ["writer", "reader"]


def test_reentrancy_rules_never_deadlock():
    rw = _RWLock()
    rw.acquire_write()
    rw.acquire_read()                                   # read inside own write: no-op
    rw.release_read()
    rw.acquire_write()                                  # nested write: depth 2
    rw.release_write()
    assert rw.locked()
    rw.release_write()
    assert not rw.locked()

    rw.acquire_read()
    with pytest.raises(RuntimeError, match="upgrade"):  # read → write would deadlock: refused instead
        rw.acquire_write()
    rw.release_read()
    with pytest.raises(RuntimeError):
        rw.release_read()                               # release without acquire
    with pytest.raises(RuntimeError):
        rw.release_write()


def test_lock_wait_is_reported_to_the_observer():
    waits: list[tuple[str, float]] = []
    rw = _RWLock(on_wait=lambda mode, s: waits.append((mode, s)))
    rw.acquire_write()
    t = threading.Thread(target=_hold_read, args=(rw, 0.0, []))
    t.start()
    time.sleep(0.12)
    rw.release_write()
    t.join(2)
    assert waits[0][0] == "write" and waits[0][1] < 0.05
    assert waits[1][0] == "read" and waits[1][1] >= 0.1, waits


# ── the store API ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def store(tmp_path: Path) -> DuckDBStore:
    st = DuckDBStore(str(tmp_path / "m.duckdb"))
    yield st
    st.close()


def test_read_write_api_with_frames(store: DuckDBStore):
    df = pd.DataFrame({"symbol": ["AAA", "BBB"], "series": ["EQ", "EQ"], "date": pd.to_datetime(["2026-11-03", "2026-11-03"]),
                       "close": [10.0, 20.0]})
    n = store.write("INSERT INTO nse_bhavcopy (symbol, series, date, close) SELECT symbol, series, date::DATE, close FROM f",
                    frames={"f": df})
    assert n == 2
    assert store.read_one("SELECT COUNT(*) FROM nse_bhavcopy")[0] == 2
    rows = store.read_rows("SELECT symbol FROM nse_bhavcopy WHERE close > ? ORDER BY symbol", [15.0])
    assert rows == [("BBB",)]
    out = store.read("SELECT symbol, close FROM nse_bhavcopy ORDER BY symbol")
    assert out["close"].tolist() == [10.0, 20.0]
    # a frame registered for one call is not visible to the next (per-call cursor, unregistered on write)
    with pytest.raises(Exception, match="(?i)catalog|does not exist|table"):
        store.read("SELECT * FROM f")
    with store.writer() as con:
        con.execute("DELETE FROM nse_bhavcopy WHERE symbol = 'AAA'")
    with store.reader() as con:
        assert con.execute("SELECT COUNT(*) FROM nse_bhavcopy").fetchone()[0] == 1
    assert store.read_one("SELECT symbol FROM nse_bhavcopy WHERE symbol = 'ZZZ'") is None


def test_legacy_store_lock_is_the_exclusive_side(store: DuckDBStore):
    """``with store._lock:`` (the remaining bypass call sites) still excludes every reader — negative control."""
    got: list[int] = []

    def reader() -> None:
        got.append(store.read_one("SELECT 1")[0])

    with store._lock:
        assert store._lock.locked()
        t = threading.Thread(target=reader)
        t.start()
        time.sleep(0.15)
        assert got == [], "a read() slipped past a held store._lock"
    t.join(2)
    assert got == [1]
    assert not store._lock.locked()


def test_reads_run_concurrently_while_a_write_waits(store: DuckDBStore):
    ins = "INSERT INTO instruments (ticker, instrument_type, ml_eligible, classified_by) VALUES "
    store.write(ins + "('A', 'EQUITY', true, 'test'), ('B', 'EQUITY', true, 'test')")
    timeline: list[tuple[str, float]] = []
    t0 = time.monotonic()

    def slow_read() -> None:
        with store.reader() as con:
            con.execute("SELECT COUNT(*) FROM instruments").fetchone()
            time.sleep(0.2)
            timeline.append(("read_done", time.monotonic() - t0))

    def write() -> None:
        store.write(ins + "('C', 'EQUITY', true, 'test')")
        timeline.append(("write_done", time.monotonic() - t0))

    rs = [threading.Thread(target=slow_read) for _ in range(4)]
    for r in rs:
        r.start()
    time.sleep(0.05)
    w = threading.Thread(target=write)
    w.start()
    for r in rs:
        r.join(3)
    w.join(3)
    reads = [t for k, t in timeline if k == "read_done"]
    write_at = next(t for k, t in timeline if k == "write_done")
    assert max(reads) < 0.4, "the four readers must overlap"
    assert write_at >= max(reads), "the write waited for every in-flight reader"
    assert store.read_one("SELECT COUNT(*) FROM instruments")[0] == 3


def test_closed_store_refuses_reads(store: DuckDBStore):
    store.close()
    with pytest.raises(RuntimeError, match="closed"):
        store.read("SELECT 1")


# ── the R-ARCH §2.3 harness as a perf test ──────────────────────────────────────────────────────────────────────
HISTORY_SQL = """
    SELECT date, close, AVG(close) OVER (ORDER BY date ROWS 19 PRECEDING) AS sma20,
           MAX(high) OVER (ORDER BY date ROWS 59 PRECEDING) AS hi60
    FROM nse_bhavcopy WHERE symbol = ? AND series = 'EQ' ORDER BY date DESC LIMIT 3700
"""


@pytest.fixture(scope="module")
def big_store(tmp_path_factory: pytest.TempPathFactory) -> DuckDBStore:
    """≈ 1.5 M bhavcopy rows (300 symbols × 5,000 sessions) so one history read costs tens of milliseconds."""
    st = DuckDBStore(str(tmp_path_factory.mktemp("big") / "big.duckdb"))
    st.write("""
        INSERT INTO nse_bhavcopy (symbol, series, date, open, high, low, close, volume)
        SELECT 'S' || (i % 300)::VARCHAR, 'EQ', DATE '2006-01-01' + (i // 300)::INT,
               100 + random() * 10, 110 + random() * 10, 90 + random() * 10, 100 + random() * 10, (random() * 1e6)::BIGINT
        FROM range(1500000) r(i)
    """)
    yield st
    st.close()


def _history(st: DuckDBStore, sym: str) -> float:
    t = time.perf_counter()
    st.read(HISTORY_SQL, [sym])
    return time.perf_counter() - t


def _burst(big_store: DuckDBStore, syms: list[str], exclusive: bool) -> float:
    """Wall time of ten concurrent history reads: through the shared lock (``read``), or — the negative control
    that reproduces the old single ``threading.Lock`` — through the exclusive ``store._lock``."""
    def one(sym: str) -> None:
        if exclusive:
            with big_store._lock:
                big_store._conn.execute(HISTORY_SQL, [sym]).df()
        else:
            big_store.read(HISTORY_SQL, [sym])

    ths = [threading.Thread(target=one, args=(s,)) for s in syms]
    t0 = time.perf_counter()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    return time.perf_counter() - t0


def test_ten_concurrent_history_reads_take_at_most_twice_one(big_store: DuckDBStore):
    """R-ARCH §2.3: ten concurrent distinct-symbol reads cost 1,243 ms vs 134–165 ms single (≈ the sum of ten) under
    the global lock. Gate G7: wall ≤ 2 × one read. The exclusive-lock run of the same burst is the negative control:
    it must behave like the old code (≈ the sequential sum), proving the harness measures the lock, not the query."""
    syms = [f"S{i}" for i in range(10, 40)]
    for s in syms[:3]:
        _history(big_store, s)                                           # warm the buffer pool
    singles = sorted(_history(big_store, s) for s in syms[3:13])
    single = singles[len(singles) // 2]                                  # median single read
    seq_sum = sum(singles)
    shared_wall = min(_burst(big_store, syms[13:23], exclusive=False), _burst(big_store, syms[23:33], exclusive=False))
    locked_wall = _burst(big_store, syms[13:23], exclusive=True)
    msg = (f"single {single * 1000:.0f} ms · seq sum {seq_sum * 1000:.0f} ms · shared {shared_wall * 1000:.0f} ms · "
           f"locked {locked_wall * 1000:.0f} ms")
    assert shared_wall < 0.6 * seq_sum, "shared reads must not serialise: " + msg
    assert locked_wall > 0.6 * seq_sum, "negative control: the exclusive lock must serialise the burst: " + msg
    if os.cpu_count() and os.cpu_count() >= 4:                           # the 2× gate needs cores to run on
        assert shared_wall <= 2.0 * max(single, 0.01), "G7: 10 concurrent reads wall must be ≤ 2 × one read: " + msg
    assert shared_wall < locked_wall / 2, "the shared lock must at least halve the exclusive wall: " + msg


def test_health_style_probe_is_fast_during_the_burst(big_store: DuckDBStore):
    """`/health` never touches the lock; a tiny read_one must also not queue behind a burst of heavy reads."""
    stop = threading.Event()

    def hammer() -> None:
        i = 0
        while not stop.is_set():
            _history(big_store, f"S{30 + i % 10}")
            i += 1

    ths = [threading.Thread(target=hammer) for _ in range(6)]
    for t in ths:
        t.start()
    time.sleep(0.05)
    t = time.perf_counter()
    assert big_store.read_one("SELECT 1")[0] == 1
    probe = time.perf_counter() - t
    stop.set()
    for th in ths:
        th.join()
    assert probe < 0.25, f"a trivial read waited {probe * 1000:.0f} ms behind the burst"
