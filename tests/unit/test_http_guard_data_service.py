"""data-service (:8001) wiring of the Host/Origin guard (desktop review C2-security-01): a web page can no
longer start the heavy ML build (the 15 Oct EOD OOM job) with a no-body cross-site POST, nor read the API
after DNS rebinding. The module is loaded under a private name; its lifespan never runs (no DuckDB)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "services" / "data-service"
sys.path.insert(0, str(SERVICE))


@pytest.fixture(scope="module")
def ds() -> ModuleType:
    spec = importlib.util.spec_from_file_location("data_service_main_guard_test", SERVICE / "main.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_guard_is_the_outermost_and_only_middleware(ds: ModuleType) -> None:
    from shared.http_guard import HostOriginGuard
    assert [m.cls for m in ds.app.user_middleware] == [HostOriginGuard]


def test_cross_site_post_cannot_start_a_job(ds: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[Any] = []
    monkeypatch.setattr(ds, "_submit", lambda *a, **k: submitted.append(a) or {"job": "fake"})
    c = TestClient(ds.app)
    r = c.post("/jobs/build-ml-dataset", headers={"origin": "https://evil.example", "content-type": "text/plain"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "unauthorized"
    r = c.post("/jobs/build-ml-dataset", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert submitted == []


def test_spoofed_host_is_400_and_loopback_is_served(ds: ModuleType) -> None:
    c = TestClient(ds.app)
    assert c.get("/health", headers={"host": "rebind.attacker.example:8001"}).status_code == 400
    r = c.get("/health", headers={"host": "localhost:8001"})
    assert r.status_code == 200 and r.json()["service"] == "data-service"
