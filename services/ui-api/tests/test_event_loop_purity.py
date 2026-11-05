"""Event-loop purity (F2.2, design review A3): heavy routes must not freeze the API.

While a heavy endpoint is mid-flight, 20 concurrent `GET /health` calls must keep
p95 < 100 ms. The real routers are mounted on a bare app (main.py's lifespan warms
Breeze/network — same mirror pattern as test_errors_contract.py); the app runs on ONE
shared event loop via `with TestClient(...)`, so a blocking handler stalls /health.
A deliberately-blocking control route proves the harness detects exactly that.
"""
import asyncio
import inspect
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import icici_admin
from routers import dashboard, pipeline, positions, stocks


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/block")
    async def block():  # negative control: blocks the loop on purpose
        time.sleep(0.6)
        return {"blocked": True}

    app.include_router(dashboard.router, prefix="/api/dashboard")
    app.include_router(stocks.router, prefix="/api/stocks")
    app.include_router(pipeline.router, prefix="/api/pipeline")
    app.include_router(positions.router, prefix="/api/positions")

    @app.post("/inline-breeze-check")
    async def inline_breeze_check():  # negative control: the pre-P2 route body ran this on the loop
        return positions._runtime_status()

    return app


def _health_latencies_while(client: TestClient, heavy_path: str, n: int = 20, json: dict | None = None,
                            replies: list | None = None) -> list[float]:
    """Fire `heavy_path` in a thread (a POST when `json` is given), then time n /health calls on the shared loop."""
    done = threading.Event()

    def _heavy():
        try:
            r = client.get(heavy_path) if json is None else client.post(heavy_path, json=json)
            if replies is not None:
                replies.append(r)
        finally:
            done.set()

    t = threading.Thread(target=_heavy, daemon=True)
    t.start()
    time.sleep(0.05)  # let the heavy request enter its handler
    lat = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = client.get("/health")
        lat.append(time.perf_counter() - t0)
        assert r.status_code == 200
    done.wait(timeout=10)
    t.join(timeout=10)
    return sorted(lat)


def _p95(lat: list[float]) -> float:
    return lat[max(0, int(round(0.95 * len(lat))) - 1)]


def test_harness_detects_a_blocking_route():
    """Control: time.sleep inside an async handler MUST stall /health, else every
    other assertion in this file would pass vacuously."""
    with TestClient(_make_app()) as client:
        lat = _health_latencies_while(client, "/block")
    assert max(lat) > 0.25, f"harness failed to detect loop blocking: max={max(lat):.3f}s"


def test_universe_status_runs_off_the_loop(monkeypatch):
    """dashboard.universe-status is a sync-def route → FastAPI threadpool; a 0.5 s
    DuckDB stall must not delay /health."""
    class _SlowConn:
        def execute(self, sql):
            time.sleep(0.5)
            return self

        def fetchone(self):
            return [0]

    @contextmanager
    def _slow_get_conn():
        yield _SlowConn()

    monkeypatch.setattr(dashboard, "get_conn", _slow_get_conn)
    with TestClient(_make_app()) as client:
        lat = _health_latencies_while(client, "/api/dashboard/universe-status")
    assert _p95(lat) < 0.1, f"/health p95={_p95(lat):.3f}s while universe-status ran"


def test_data_quality_parquet_fallback_runs_off_the_loop(monkeypatch):
    """pipeline.data-quality's parquet fallback (352 MB file in prod) goes through
    asyncio.to_thread; a 0.5 s read must not delay /health."""
    import pandas as pd

    class _Resp:
        status_code = 200

        def json(self):
            return {}

    class _FakeClient:  # data-service "up" but empty → forces the parquet fallback
        def __init__(self, *a, **k): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    class _Exists:
        def exists(self):
            return True

        def __str__(self):
            return "features.parquet"

    class _Missing:
        def exists(self):
            return False

    def _slow_read_parquet(path, columns=None, **k):
        time.sleep(0.5)
        return pd.DataFrame({"ticker": ["AAA", "BBB"]})

    monkeypatch.setattr(pipeline.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(pipeline, "FEATURES_PARQUET", _Exists())
    monkeypatch.setattr(pipeline, "LABELS_PARQUET", _Missing())
    monkeypatch.setattr(pd, "read_parquet", _slow_read_parquet)
    with TestClient(_make_app()) as client:
        lat = _health_latencies_while(client, "/api/pipeline/data-quality")
    assert _p95(lat) < 0.1, f"/health p95={_p95(lat):.3f}s while data-quality ran"


def test_screener_duckdb_block_is_extracted_and_threaded():
    """A3: screener stays async (it awaits httpx); its legacy DuckDB block lives in a
    sync module function called only via asyncio.to_thread — never inline in the body."""
    assert asyncio.iscoroutinefunction(stocks.screener)
    assert not asyncio.iscoroutinefunction(stocks._screener_legacy_duckdb)
    body = inspect.getsource(stocks.screener)
    assert "await asyncio.to_thread(" in body and "_screener_legacy_duckdb" in body
    assert "get_conn" not in body, "raw DuckDB access crept back into the async screener body"


# ── P2: saving an ICICI token or credentials runs the 10-40 s Breeze check off the loop ───────────────────────

SLOW_PROBE_S = 0.6


@pytest.fixture
def slow_breeze(tmp_path, monkeypatch):
    """A Breeze check that takes SLOW_PROBE_S (the real one: 10-40 s), a scratch .env, no network."""
    env = tmp_path / ".env"
    env.write_text("ICICI_API_KEY=k\nICICI_API_SECRET=s\nICICI_SESSION_TOKEN=11111111\n")
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: env)
    for key, value in (("ICICI_API_KEY", "k"), ("ICICI_API_SECRET", "s"), ("ICICI_SESSION_TOKEN", "11111111")):
        monkeypatch.setenv(key, value)
    calls: list[str] = []

    def probe(api_key, api_secret, token):
        calls.append(token)
        time.sleep(SLOW_PROBE_S)
        return {"connected": True, "account_name": "TEST", "customer_id": "AD000001", "attempts": 1}

    async def no_backend(**kwargs):
        return {}

    async def no_status():
        return {}

    monkeypatch.setattr(positions, "probe_breeze_connection", probe)
    monkeypatch.setattr(positions, "propagate_runtime_config", no_backend)
    monkeypatch.setattr(positions, "collect_backend_status", no_status)
    positions._invalidate_breeze_state()
    yield {"env": env, "calls": calls}
    positions._invalidate_breeze_state()


def test_harness_detects_an_inline_breeze_check(slow_breeze):
    """Control: the same slow check called inline in an async route (what /session-token and /credentials did)
    MUST stall /health."""
    with TestClient(_make_app()) as client:
        lat = _health_latencies_while(client, "/inline-breeze-check", json={})
    assert max(lat) > 0.25, f"harness failed to detect the inline check: max={max(lat):.3f}s"


def test_session_token_save_keeps_the_api_responsive(slow_breeze):
    replies: list = []
    with TestClient(_make_app()) as client:
        t0 = time.perf_counter()
        lat = _health_latencies_while(client, "/api/positions/session-token", json={"token": "22222222"}, replies=replies)
        took = time.perf_counter() - t0
    # max, not p95: /health calls are sequential, so a blocked loop delays only the one call waiting on it
    assert max(lat) < 0.25 and _p95(lat) < 0.1, f"/health max={max(lat):.3f}s while the token was checked"
    assert replies and replies[0].status_code == 200 and replies[0].json()["connected"] is True
    assert slow_breeze["calls"] == ["22222222"] and took >= SLOW_PROBE_S          # the check really ran meanwhile
    assert "ICICI_SESSION_TOKEN=22222222" in slow_breeze["env"].read_text().splitlines()


def test_credentials_save_keeps_the_api_responsive(slow_breeze):
    replies: list = []
    with TestClient(_make_app()) as client:
        lat = _health_latencies_while(client, "/api/positions/credentials",
                                      json={"api_key": "k2", "api_secret": "s2"}, replies=replies)
    assert max(lat) < 0.25 and _p95(lat) < 0.1, f"/health max={max(lat):.3f}s while the credentials were checked"
    assert replies and replies[0].status_code == 200 and replies[0].json()["status"]["connected"] is True
    assert slow_breeze["calls"] == ["11111111"]
    assert "ICICI_API_KEY=k2" in slow_breeze["env"].read_text().splitlines()


@pytest.mark.parametrize("route", ["update_session_token", "save_credentials"])
def test_token_routes_call_the_breeze_check_only_through_a_thread(route):
    """Structural guard: the async bodies hand the blocking part to asyncio.to_thread and never call
    _runtime_status / persist_env_updates / _invalidate_breeze_state inline."""
    fn = getattr(positions, route)
    assert asyncio.iscoroutinefunction(fn)
    body = inspect.getsource(fn)
    assert "await asyncio.to_thread(" in body
    for blocking in ("_runtime_status(", "persist_env_updates(", "_invalidate_breeze_state(", "probe_breeze_connection("):
        assert blocking not in body, f"{blocking} crept back into the async body of {route}"
