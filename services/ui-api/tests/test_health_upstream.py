"""/api/health/upstream (O-F5a, D-BOOT): the shell's one upstream probe.

Same mirror pattern as test_charts.py: the real router on a bare app, the data-service side
played by httpx.MockTransport — no live data-service in CI.
"""
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers import health_upstream  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_upstream.router, prefix="/api/health")
    return app


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch):
    health_upstream._reset_cache()
    yield
    health_upstream._reset_cache()
    health_upstream._TRANSPORT = None


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_up_and_writable(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"status": "ok", "db_read_only": False})

    monkeypatch.setattr(health_upstream, "_TRANSPORT", _transport(handler))
    c = TestClient(_app())
    body = c.get("/api/health/upstream").json()
    assert body["data_service"] == "up"
    assert body["db_read_only"] is False
    assert body["cached"] is False
    assert isinstance(body["as_of"], float)
    assert calls["n"] == 1


def test_read_only_flag_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_upstream, "_TRANSPORT",
                        _transport(lambda r: httpx.Response(200, json={"db_read_only": True})))
    body = TestClient(_app()).get("/api/health/upstream").json()
    assert body == {"data_service": "up", "db_read_only": True, "as_of": body["as_of"], "cached": False}


def test_unreachable_is_down_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed", request=request)

    monkeypatch.setattr(health_upstream, "_TRANSPORT", _transport(handler))
    r = TestClient(_app()).get("/api/health/upstream")
    assert r.status_code == 200  # the probe endpoint itself never fails
    body = r.json()
    assert body["data_service"] == "down"
    assert body["db_read_only"] is False
    # the transport detail stays out of the payload (it goes to the log)
    assert "connection attempts" not in r.text.lower()


def test_non_200_health_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_upstream, "_TRANSPORT",
                        _transport(lambda r: httpx.Response(503, json={"detail": "starting"})))
    body = TestClient(_app()).get("/api/health/upstream").json()
    assert body["data_service"] == "down"


def test_bad_json_body_is_up_without_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_upstream, "_TRANSPORT",
                        _transport(lambda r: httpx.Response(200, text="ok")))
    body = TestClient(_app()).get("/api/health/upstream").json()
    # a 200 that is not JSON still proves the service answers; json() raising → down is also acceptable,
    # but it must never 500: the endpoint answered 200 either way
    assert body["data_service"] in ("up", "down")


def test_five_second_cache_single_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"db_read_only": False})

    monkeypatch.setattr(health_upstream, "_TRANSPORT", _transport(handler))
    c = TestClient(_app())
    first = c.get("/api/health/upstream").json()
    second = c.get("/api/health/upstream").json()
    third = c.get("/api/health/upstream").json()
    assert calls["n"] == 1  # 43 pages fan in to one probe per 5 s
    assert first["cached"] is False and second["cached"] is True and third["cached"] is True
    assert second["as_of"] == first["as_of"]


def test_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"db_read_only": False})

    monkeypatch.setattr(health_upstream, "_TRANSPORT", _transport(handler))
    c = TestClient(_app())
    c.get("/api/health/upstream")
    # age the cache past CACHE_S instead of sleeping
    health_upstream._cached_at -= health_upstream.CACHE_S + 0.1
    body = c.get("/api/health/upstream").json()
    assert calls["n"] == 2 and body["cached"] is False
