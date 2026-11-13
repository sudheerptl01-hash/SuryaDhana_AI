"""FINAL round R2-DRIV (RATING R9-I3): /api/market/index-drivers/intraday — the proxy passes data-service's payload
through one SWR cache, degrades to ok:false + store_errors on a 404 or a dead upstream (never a raw transport error on
the wire), validates the index and the interval, and keeps the empty shape stable for the UI."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _terminal_v2_fixtures as fx  # noqa: E402
import routers.markets as mk  # noqa: E402
from shared import http_client  # noqa: E402

PAYLOAD: dict[str, Any] = {
    "index": "NIFTY 50", "date": "2026-11-13", "interval": "1m", "live": False,
    "minutes": ["14:15", "14:16"], "prev_index_level": 25299.35,
    "actual_pts": [-10.0, -20.0], "explained_pts": [-9.0, -18.0], "residual_pts": [-1.0, -2.0],
    "priced": [48, 48], "others_pts": [0.0, -0.5], "residual_now": -2.0, "index_source": "icici-ws",
    "members": {"add": [{"symbol": "A", "industry": None, "weight_pct": 10.0, "points": 6.0, "ret_pct": 0.2,
                         "source": "icici-ws", "series": [3.0, 6.0]}], "drag": [], "rest": []},
    "coverage": {"members_total": 50, "members_priced": 48,
                 "gaps": [{"symbol": "E", "weight_pct": 1.2, "reason": "no prints on either source"}]},
    "weight_method": "rebuilt_calibrated", "weights_as_of": "2026-11-13",
    "first_minute": "14:15", "last_minute": "15:30", "as_of": "2026-11-13T22:00:00+05:30",
    "badges": {"timeline": "context", "members": "arithmetic", "fit": "arithmetic"},
    "note": "points = previous index close × weight × intraday return … — describes, does not predict",
}


def _install(monkeypatch: pytest.MonkeyPatch, *, status: int = 200, body: Any = None,
             dead: bool = False) -> list[str]:
    """A MockTransport serving only the intraday read (the fixture module's pattern), plus cache resets."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if dead:
            raise httpx.ConnectError("refused")
        if request.url.path == "/db/index-drivers/intraday":
            return httpx.Response(status, json=body if body is not None else {"detail": "Not Found"})
        return httpx.Response(404, json={"detail": f"no fixture for {request.url.path}"})

    clients: dict[int, httpx.AsyncClient] = {}

    def fake_client() -> httpx.AsyncClient:
        import asyncio
        try:
            key = id(asyncio.get_running_loop())
        except RuntimeError:
            key = 0
        c = clients.get(key)
        if c is None or c.is_closed:
            c = clients[key] = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="")
        return c

    monkeypatch.setattr(http_client, "get_async_client", fake_client)
    monkeypatch.setattr(mk, "DATA_SVC", fx.DATA_SVC)
    http_client.reset_state()
    mk._drivers_ttl.clear()
    mk.INTRADAY_STORE.invalidate()
    return seen


def test_intraday_proxies_the_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(monkeypatch, body=PAYLOAD)
    client = TestClient(fx.make_app())
    r = client.get("/api/market/index-drivers/intraday", params={"index": "NIFTY 50"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["store_errors"] == {}
    assert body["minutes"] == ["14:15", "14:16"] and body["residual_now"] == -2.0
    assert body["members"]["add"][0]["series"] == [3.0, 6.0]
    assert body["badges"]["timeline"] == "context"
    assert body["note"].endswith("describes, does not predict")
    assert seen == ["/db/index-drivers/intraday"]
    # the SWR cache serves the repeat without a second upstream call
    r2 = client.get("/api/market/index-drivers/intraday", params={"index": "NIFTY 50"})
    assert r2.status_code == 200 and seen == ["/db/index-drivers/intraday"]


def test_intraday_degrades_on_404_and_dead_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, status=404)
    client = TestClient(fx.make_app())
    r = client.get("/api/market/index-drivers/intraday", params={"index": "NIFTY BANK"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "/db/index-drivers/intraday" in body["store_errors"]
    assert body["minutes"] == [] and body["members"] == {"add": [], "drag": [], "rest": []}
    assert body["index"] == "NIFTY BANK"
    _install(monkeypatch, dead=True)
    r2 = client.get("/api/market/index-drivers/intraday", params={"index": "NIFTY 50"})
    assert r2.status_code == 200 and r2.json()["ok"] is False
    assert r2.json()["store_errors"].get("/db/index-drivers/intraday")   # named, degraded — a 200, not a raw 503


def test_intraday_validates_index_and_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, body=PAYLOAD)
    client = TestClient(fx.make_app())
    assert client.get("/api/market/index-drivers/intraday", params={"index": "SENSEX"}).status_code == 422
    assert client.get("/api/market/index-drivers/intraday", params={"index": "NIFTY 50", "interval": "3m"}).status_code == 422
    assert client.get("/api/market/index-drivers/intraday", params={"index": "NIFTY 50", "top": 99}).status_code == 422
