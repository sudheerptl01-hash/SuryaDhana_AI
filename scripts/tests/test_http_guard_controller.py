"""master-controller (:8008) HTTP surface: '*' CORS removed and the Host/Origin guard installed
(desktop review C2-security-07). No lifespan runs, no Telegram call, no ICICI login: every handler that
could reach one is replaced by a recorder before the request."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc

from shared.http_guard import HostOriginGuard

EVIL = "https://evil.example"


@pytest.fixture
def recorders(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    seen: dict[str, list[Any]] = {"alerts": [], "refresh": []}

    async def fake_alert(*a: Any, **k: Any) -> None:
        seen["alerts"].append(a)

    async def fake_refresh(*a: Any, **k: Any) -> None:
        seen["refresh"].append(a)

    monkeypatch.setattr(mc._alerts, "info", fake_alert)              # no Telegram send
    monkeypatch.setattr(mc, "icici_session_refresh", fake_refresh)   # no ICICI login
    monkeypatch.setattr(mc, "_autopilot", mc._AutopilotState())      # isolated in-memory state
    return seen


@pytest.fixture
def client() -> TestClient:
    return TestClient(mc.app)


def test_guard_is_the_only_middleware_and_cors_is_gone() -> None:
    from shared.metrics import ObservabilityMiddleware
    assert [m.cls for m in mc.app.user_middleware] == [HostOriginGuard, ObservabilityMiddleware]
    assert "CORSMiddleware" not in (ROOT / "scripts" / "master_controller.py").read_text()


def test_preflight_from_any_site_gets_no_cors_grant(client: TestClient) -> None:
    r = client.options("/api/scheduler/autopilot", headers={
        "origin": EVIL, "access-control-request-method": "POST", "access-control-request-headers": "content-type"})
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-origin" not in client.get("/health", headers={"origin": EVIL}).headers


def test_cross_site_autopilot_toggle_is_refused(client: TestClient, recorders: dict[str, list[Any]]) -> None:
    before = mc._autopilot.to_dict()["enabled"]
    r = client.post("/api/scheduler/autopilot", content=b'{"enabled": true}',
                    headers={"content-type": "text/plain", "origin": EVIL, "sec-fetch-site": "cross-site"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "unauthorized"
    assert mc._autopilot.to_dict()["enabled"] == before and recorders["alerts"] == []


def test_cross_site_icici_refresh_is_refused(client: TestClient, recorders: dict[str, list[Any]]) -> None:
    r = client.post("/api/scheduler/icici-refresh", headers={"origin": EVIL})
    assert r.status_code == 403 and recorders["refresh"] == []


def test_spoofed_host_is_400(client: TestClient) -> None:
    assert client.get("/health", headers={"host": "rebind.attacker.example:8008"}).status_code == 400
    assert client.get("/api/scheduler/logs", headers={"host": "192.168.31.62:8008"}).status_code == 400
    assert client.get("/health", headers={"host": "localhost:8008"}).status_code == 200


def test_server_side_callers_without_origin_still_work(client: TestClient, recorders: dict[str, list[Any]]) -> None:
    # ui-api's /api/telemetry proxy and scripts call with httpx: no Origin, loopback Host
    r = client.post("/api/scheduler/autopilot", json={"enabled": False}, headers={"host": "localhost:8008"})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert len(recorders["alerts"]) == 1
