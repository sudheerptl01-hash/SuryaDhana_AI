"""G7 addition: "``/health`` ≤ 10 ms during the burst" on the REAL data-service app (PLAN 1.7). B7's
``tests/arch/test_duckdb_rw.py`` proves the read lock (10 concurrent history reads wall ≤ 2 × one, with the exclusive-lock
negative control) and that a trivial ``read_one`` does not queue; this drives ``GET /health`` of
``services/data-service/main.py`` (loaded under a private name, lifespan never run, no live DuckDB) while six threads
hammer heavy history reads on a temp store, and requires the median probe ≤ 10 ms. Negative control: the same harness
against a /health that takes the store's exclusive lock (the pre-B7 shape) is measured well above 10 ms."""
from __future__ import annotations

import importlib.util
import statistics
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "services" / "data-service"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVICE))

from storage.duckdb_store import DuckDBStore  # noqa: E402

BUDGET_MS = 10.0
PROBES = 9
HISTORY_SQL = """
    SELECT date, close, AVG(close) OVER (ORDER BY date ROWS 19 PRECEDING) AS sma20,
           MAX(high) OVER (ORDER BY date ROWS 59 PRECEDING) AS hi60
    FROM nse_bhavcopy WHERE symbol = ? AND series = 'EQ' ORDER BY date DESC LIMIT 3700
"""


@pytest.fixture(scope="module")
def ds() -> ModuleType:
    spec = importlib.util.spec_from_file_location("data_service_main_g7_gate", SERVICE / "main.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DuckDBStore]:
    """≈ 900 k bhavcopy rows (150 symbols × 6,000 sessions): one history read costs milliseconds to tens of milliseconds."""
    st = DuckDBStore(str(tmp_path_factory.mktemp("g7") / "g7.duckdb"))
    st.write("""
        INSERT INTO nse_bhavcopy (symbol, series, date, open, high, low, close, volume)
        SELECT 'S' || (i % 150)::VARCHAR, 'EQ', DATE '2003-01-01' + (i // 150)::INT,
               100 + random() * 10, 110 + random() * 10, 90 + random() * 10, 100 + random() * 10, (random() * 1e6)::BIGINT
        FROM range(900000) r(i)
    """)
    yield st
    st.close()


def probe_during_burst(store: DuckDBStore, client: TestClient, path: str, *, exclusive: bool,
                       threads: int = 6) -> list[float]:
    """Probe latencies (ms) of ``GET path`` while ``threads`` threads run heavy history reads (shared or exclusive lock)."""
    stop = threading.Event()

    def hammer(k: int) -> None:
        i = 0
        while not stop.is_set():
            sym = f"S{(k * 17 + i) % 150}"
            if exclusive:                                                # a 40 ms locked read, then 1 ms off the lock
                with store._lock:                                        # (B7's lock is not FIFO: without the gap one
                    store._conn.execute(HISTORY_SQL, [sym]).df()         # hammer re-takes it at once and starves the
                    time.sleep(0.04)                                     # probe forever)
                time.sleep(0.001)
            else:
                store.read(HISTORY_SQL, [sym])
            i += 1

    ths = [threading.Thread(target=hammer, args=(k,), daemon=True) for k in range(threads)]
    for t in ths:
        t.start()
    out: list[float] = []
    try:
        time.sleep(0.1)                                                  # the burst is running
        for _ in range(PROBES):
            t0 = time.perf_counter()
            r = client.get(path, headers={"host": "127.0.0.1:8001"})
            out.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200, r.text
            time.sleep(0.01)
    finally:
        stop.set()
        for t in ths:
            t.join(timeout=30)
    return out


def _warm(client: TestClient, path: str) -> None:
    for _ in range(3):
        client.get(path, headers={"host": "127.0.0.1:8001"})


def test_real_health_stays_under_10ms_during_a_read_burst(ds: ModuleType, store: DuckDBStore):
    client = TestClient(ds.app)
    _warm(client, "/health")
    quiet = [probe_during_burst(store, client, "/health", exclusive=False, threads=0)]
    lat = probe_during_burst(store, client, "/health", exclusive=False)
    med = statistics.median(lat)
    assert med <= BUDGET_MS, f"/health median {med:.1f} ms during the burst (quiet {statistics.median(quiet[0]):.1f} ms): {lat}"


def test_negative_control_a_health_behind_the_exclusive_lock_is_slow(store: DuckDBStore):
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:                                                 # the pre-B7 shape: a probe that queues on the lock
        with store._lock:
            pass
        return {"status": "ok"}

    client = TestClient(app)
    _warm(client, "/health")
    lat = probe_during_burst(store, client, "/health", exclusive=True, threads=2)
    assert statistics.median(lat) > BUDGET_MS, f"the harness must see the queue: {lat}"
