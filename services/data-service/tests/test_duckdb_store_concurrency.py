"""R4-CONC (final round, 14 Nov 2026): the store's read side really is parallel.

``DuckDBStore.read()`` / ``reader()`` run each call on a per-call ``self._conn.cursor()`` under the
SHARED side of the readers-writer lock (shipped with Terminal v2 wave 2, commit 0b27dcc). These tests
pin that behaviour so a regression back to "one exclusive lock around every read" can never ship quietly:

- concurrent heavy reads finish in far less than the serialized sum (with ``SET threads=1`` so DuckDB's
  own intra-query parallelism cannot mask a serializing lock);
- a write completes promptly while readers churn (writer preference in ``_RWLock``: no starvation);
- per-call cursors are isolated (two threads registering different frames under the same name never
  cross-talk) and are closed deterministically on exit.

CI-safe bounds: the parallelism assertion uses 4 readers and a generous wall bound that still clearly
separates "parallel" (≈ 1-2x one call on ≥ 2 cores) from "serialized" (≥ 4x one call).
"""
from __future__ import annotations

import os
import threading
import time

import duckdb
import pandas as pd
import pytest

from storage.duckdb_store import DuckDBStore

# One query's DuckDB-native work must dominate Python overhead, so the GIL (released inside
# duckdb's execute) cannot hide a serializing lock. ~30-80 ms per call at threads=1.
HEAVY_SQL = "SELECT sum(sin(x) + cos(x) + sqrt(abs(x))) FROM heavy"
N_READERS = 4


@pytest.fixture()
def store(tmp_path):
    s = DuckDBStore(str(tmp_path / "conc.duckdb"))
    with s.writer() as con:
        # threads=1 is database-wide: each query runs single-threaded, so any speed-up below
        # can only come from cursors executing concurrently, never from intra-query threads.
        con.execute("SET threads=1")
        con.execute("CREATE TABLE heavy AS SELECT (random()*2-1)::DOUBLE AS x FROM range(3000000)")
        con.execute("CREATE TABLE marks (v INTEGER)")
    yield s
    s.close()


def _single_read_seconds(s: DuckDBStore) -> float:
    best = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        s.read_one(HEAVY_SQL)
        best = min(best, time.perf_counter() - t0)
    return best


@pytest.mark.skipif((os.cpu_count() or 1) < 2, reason="needs >= 2 cores to observe read parallelism")
def test_concurrent_reads_are_parallel(store: DuckDBStore) -> None:
    single = _single_read_seconds(store)
    assert single > 0.005, f"heavy query too fast ({single*1000:.1f} ms) to measure parallelism reliably"

    barrier = threading.Barrier(N_READERS)
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            barrier.wait()
            row = store.read_one(HEAVY_SQL)
            assert row is not None and row[0] is not None
        except BaseException as e:  # noqa: BLE001 — surfaced below
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(N_READERS)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    wall = time.perf_counter() - t0

    assert not errors, errors
    # Serialized (the old single exclusive lock) would be ~N_READERS x one call (4x+).
    # Parallel is ~1x on >= 4 cores and ~2x on 2 cores. 2.6x separates the two with CI margin.
    assert wall < 2.6 * single, (
        f"4 concurrent reads took {wall*1000:.0f} ms vs {single*1000:.0f} ms single "
        f"({wall/single:.1f}x): reads look serialized again"
    )


def test_writer_not_starved_while_readers_churn(store: DuckDBStore) -> None:
    stop = threading.Event()
    errors: list[BaseException] = []

    def churn() -> None:
        try:
            while not stop.is_set():
                store.read_one("SELECT sum(x) FROM heavy")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=churn) for _ in range(3)]
    for t in threads:
        t.start()
    try:
        time.sleep(0.2)  # readers established
        t0 = time.perf_counter()
        store.write("INSERT INTO marks VALUES (?)", [1])
        waited = time.perf_counter() - t0
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=30)
    assert not errors, errors
    assert waited < 2.0, f"write waited {waited:.2f}s behind churning readers (writer starvation)"
    assert store.read_one("SELECT COUNT(*) FROM marks")[0] == 1


def test_per_call_cursors_are_isolated_frames(store: DuckDBStore) -> None:
    """Two threads register different frames under the SAME name concurrently: each must see its own."""
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(value: int) -> None:
        frame = pd.DataFrame({"v": [value] * 50})
        try:
            barrier.wait()
            for _ in range(25):
                row = store.read_one("SELECT DISTINCT v FROM f", frames={"f": frame})
                assert row is not None and int(row[0]) == value, f"cross-talk: got {row} wanted {value}"
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(v,)) for v in (7, 42)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors


def test_reader_cursor_is_not_the_primary_and_closes(store: DuckDBStore) -> None:
    with store.reader() as con:
        assert con is not store._conn, "reader() must hand out a per-call cursor, not the write connection"
        assert con.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(duckdb.Error):
        con.execute("SELECT 1")  # the cursor is closed deterministically on exit
