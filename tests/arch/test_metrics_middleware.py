"""G8 — the observability contract (Terminal v2 PLAN 1.5; shared/metrics.py): ``/metrics`` with the named series,
``X-Request-ID`` in and out bound as the correlation id, the JSON access log excluding ``/health`` ``/live`` ``/``
(but never a failure), route labels from the template, uvicorn's access log silenced, the anyio thread limit raised,
and the Host/Origin guard still outermost. Negative controls: an unsafe request id is replaced; an excluded path
IS logged when it fails; a kept-uvicorn configuration logs nothing."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import anyio
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared import metrics as m  # noqa: E402
from shared.http_guard import HostOriginGuard, install_http_guard  # noqa: E402
from shared.logging import get_correlation_id  # noqa: E402


def make_app(**kw) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/stocks/{sym}/history")
    def history(sym: str):                       # sync: runs on the anyio worker pool
        return {"sym": sym, "cid": get_correlation_id(),
                "tokens": None}

    @app.get("/api/tokens")
    async def tokens():
        return {"tokens": anyio.to_thread.current_default_thread_limiter().total_tokens}

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("boom")

    @app.get("/live")
    async def live():
        raise HTTPException(status_code=503, detail="down")

    m.install_observability(app, service="test-svc", **kw)
    install_http_guard(app, service="test-svc")
    return app


@pytest.fixture
def app() -> FastAPI:
    return make_app(thread_limit=70)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _access_lines(capsys) -> list[dict]:
    out = capsys.readouterr().out
    lines = []
    for ln in out.splitlines():
        if ln.startswith("{"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("event") == "http.access":
                lines.append(d)
    return lines


def test_guard_stays_outermost(app: FastAPI):
    assert app.user_middleware[0].cls is HostOriginGuard
    assert m.ObservabilityMiddleware in [mw.cls for mw in app.user_middleware]


def test_metrics_endpoint_has_the_named_series(client: TestClient):
    client.get("/api/stocks/TCS/history")
    client.get("/api/stocks/INFY/history")
    r = client.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    for name in ("sd_http_requests_total", "sd_http_request_seconds", "sd_http_inflight", "sd_duckdb_lock_wait_seconds",
                 "sd_job_seconds", "sd_cache_events_total", "sd_breeze_budget_used", "sd_upstream_requests_total",
                 "sd_upstream_breaker_open", "sd_feed_lag_seconds"):
        assert name in body, name
    # the route label is the template, never the raw path (cardinality = number of routes)
    assert 'route="/api/stocks/{sym}/history"' in body
    assert "TCS" not in body and "INFY" not in body
    assert 'sd_http_requests_total{method="GET",route="/api/stocks/{sym}/history",service="test-svc",status="2xx"}' in body


def test_request_id_is_echoed_and_bound_as_correlation_id(client: TestClient):
    r = client.get("/api/stocks/TCS/history", headers={"x-request-id": "abc-123.x"})
    assert r.headers["x-request-id"] == "abc-123.x"
    assert r.json()["cid"] == "abc-123.x"                     # visible inside a sync handler on the worker pool
    r2 = client.get("/api/stocks/TCS/history")
    assert len(r2.headers["x-request-id"]) == 32 and r2.json()["cid"] == r2.headers["x-request-id"]
    # negative control: an id with spaces / control characters is replaced, never echoed verbatim
    r3 = client.get("/api/stocks/TCS/history", headers={"x-request-id": "evil id\r\nX: y"})
    assert "evil" not in r3.headers["x-request-id"] and len(r3.headers["x-request-id"]) == 32


def test_correlation_id_does_not_leak_between_requests(client: TestClient):
    client.get("/api/stocks/TCS/history", headers={"x-request-id": "first"})
    assert get_correlation_id() == "no-correlation-id"


def test_access_log_excludes_health_root_live_but_logs_failures(client: TestClient, capsys):
    client.get("/health")
    client.get("/api/stocks/TCS/history", headers={"x-request-id": "rid-1"})
    client.get("/metrics")
    client.get("/live")                                       # excluded path, but it FAILS (503)
    lines = _access_lines(capsys)
    paths = [d["path"] for d in lines]
    assert "/health" not in paths and "/metrics" not in paths
    assert "/api/stocks/TCS/history" in paths
    hit = next(d for d in lines if d["path"] == "/api/stocks/TCS/history")
    assert hit["status"] == 200 and hit["correlation_id"] == "rid-1" and hit["route"] == "/api/stocks/{sym}/history"
    assert hit["service"] == "test-svc" and "ms" in hit
    assert "/live" not in paths, "a 503 is an upstream refusal, not a crash: stays excluded"
    r = client.get("/api/boom")
    assert r.status_code == 500
    assert next(d for d in _access_lines(capsys) if d["path"] == "/api/boom")["status"] == 500


def test_an_excluded_path_that_crashes_is_logged(capsys):
    app = FastAPI()

    @app.get("/health")
    async def health():
        raise RuntimeError("db gone")

    m.install_observability(app, service="crash-svc", thread_limit=None)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/health").status_code == 500
    assert [d["status"] for d in _access_lines(capsys) if d["path"] == "/health"] == [500]


def test_uvicorn_access_logger_is_silenced_unless_kept():
    make_app()
    lg = logging.getLogger("uvicorn.access")
    assert lg.disabled and any(isinstance(f, m._DropAll) for f in lg.filters)
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "GET /health 200", None, None)
    assert all(not f.filter(rec) for f in lg.filters)
    lg.disabled = False
    lg.filters.clear()
    app = make_app(env={"SD_ACCESS_LOG": "uvicorn"})      # escape hatch: keep uvicorn's lines, no JSON lines
    assert not logging.getLogger("uvicorn.access").disabled
    mw = next(mw for mw in app.user_middleware if mw.cls is m.ObservabilityMiddleware)
    assert mw.kwargs["access_log"] is False


def test_thread_limit_is_raised_on_first_request(client: TestClient):
    client.get("/health")
    assert client.get("/api/tokens").json()["tokens"] >= 70


def test_thread_limit_default_and_env(monkeypatch):
    app = make_app(env={"SD_THREAD_LIMIT": "90"})
    mw = next(mw for mw in app.user_middleware if mw.cls is m.ObservabilityMiddleware)
    assert mw.kwargs["thread_limit"] == 90
    app = make_app(env={"SD_THREAD_LIMIT": "nonsense"})
    mw = next(mw for mw in app.user_middleware if mw.cls is m.ObservabilityMiddleware)
    assert mw.kwargs["thread_limit"] == m.DEFAULT_THREAD_LIMIT == 64


def test_route_family_fallback_for_unmatched_paths():
    assert m.route_family("/_next/static/chunks/app.js") == "/_next/*"
    assert m.route_family("/api/nope/x") == "/api/*"
    assert m.route_family("/") == "/"
    assert m.route_family("/favicon.ico") == "/favicon.ico"


def test_sanitize_request_id():
    assert m.sanitize_request_id("ok-1.2_3") == "ok-1.2_3"
    assert len(m.sanitize_request_id("")) == 32
    assert len(m.sanitize_request_id("x" * 100)) == 32           # too long → fresh id (never a truncated foreign id)
    assert m.sanitize_request_id("x" * 64) == "x" * 64
    assert len(m.sanitize_request_id("has space")) == 32


def test_helper_metrics_record_without_error():
    m.observe_duckdb_lock_wait("read", 0.001)
    m.observe_job("iv_eod", 3.2, "ok")
    m.count_cache_event("monitor", "hit")
    m.set_breeze_budget("minute", 12)
    m.count_upstream("data-service", "live", "ok")
    m.set_breaker_open("data-service", True)
    m.set_feed_lag("ticks", 4.0)
    body, _ctype = m.render_metrics()
    text = body.decode()
    assert "sd_duckdb_lock_wait_seconds_count" in text
    assert 'sd_upstream_breaker_open{service="test-svc",upstream="data-service"} 1.0' in text


def test_metrics_module_reimport_reuses_collectors():
    """Re-importing (pytest loads services' main.py under private names) must not raise 'Duplicated timeseries'."""
    import importlib
    before = m.HTTP_REQUESTS
    m2 = importlib.reload(m)
    assert m2.HTTP_REQUESTS is before
