"""ui-api HTTP security on the REAL app (main.app): Host/Origin guard, no CORS, PAPER ONLY execution guard,
prefs Content-Type, monitor WebSocket Origin + cap, /api/health, static-UI security headers.

Desktop review findings C2-security-01/-03/-06/-08/-09/-13 and C3-logic-unchanged-09.

main.py is loaded once per module under a private name with dotenv's loader disabled (so the live .env is
never read into the test process) and UI_DIST_DIR pointing at a throwaway release. The lifespan never
runs (TestClient is used without `with`). Every handler that would touch live state is replaced by a
recorder: the Desk (routers.desk.get_desk), the execution engine (routers.execution.get_engine) and the
Redis pubsub of the monitor socket; PREFS_DB and PAPER_TRADES_DB point at tmp_path (conftest).
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

UI_API_DIR = Path(__file__).resolve().parents[1]
REPO = UI_API_DIR.parents[1]
sys.path.insert(0, str(UI_API_DIR))

EVIL = "https://evil.example"
SAME_ORIGIN = "http://127.0.0.1:8010"


@pytest.fixture(scope="module")
def ui_main(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    release = tmp_path_factory.mktemp("dist") / "release"
    release.mkdir()
    (release / "index.html").write_text("<!doctype html><title>SuryaDhana</title><p>terminal</p>")
    (release / "_next" / "static").mkdir(parents=True)
    (release / "_next" / "static" / "app.js").write_text("console.log(1)")
    mp = pytest.MonkeyPatch()
    mp.setenv("UI_DIST_DIR", str(release))
    import dotenv
    mp.setattr(dotenv, "load_dotenv", lambda *a, **k: False)   # never read the live .env into this process
    try:
        spec = importlib.util.spec_from_file_location("ui_api_main_under_test", UI_API_DIR / "main.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture
def client(ui_main: ModuleType) -> TestClient:
    return TestClient(ui_main.app)


# ── wiring ──────────────────────────────────────────────────────────────────────────────────────

def test_guard_is_the_outermost_middleware_and_cors_is_gone(ui_main: ModuleType) -> None:
    from fastapi.middleware.cors import CORSMiddleware
    from routers._api_gzip import ApiGzipMiddleware

    from shared.http_guard import HostOriginGuard
    classes = [m.cls for m in ui_main.app.user_middleware]
    assert classes == [HostOriginGuard, ApiGzipMiddleware]           # user_middleware[0] is the outermost
    assert CORSMiddleware not in classes


def test_no_cors_headers_for_the_old_dev_origins(client: TestClient) -> None:
    for origin in ("http://localhost:3000", "http://localhost:3001"):
        r = client.get("/health", headers={"origin": origin})
        assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
        r = client.options("/api/desk/status", headers={"origin": origin, "access-control-request-method": "POST",
                                                        "access-control-request-headers": "content-type"})
        assert "access-control-allow-origin" not in r.headers and "access-control-allow-credentials" not in r.headers


# ── Host (DNS rebinding) ────────────────────────────────────────────────────────────────────────

def test_spoofed_host_gets_400_envelope(client: TestClient) -> None:
    r = client.get("/health", headers={"host": "rebind.attacker.example"})
    assert r.status_code == 400
    body = r.json()
    assert body["detail"] == "Host header not allowed" and body["error"]["code"] == "invalid"
    assert client.get("/", headers={"host": "rebind.attacker.example:8010"}).status_code == 400
    assert client.get("/health", headers={"host": "127.0.0.1:8010"}).status_code == 200
    assert client.get("/health", headers={"host": "localhost:8010"}).status_code == 200


def test_rebinding_through_the_next_proxy_is_400(client: TestClient) -> None:
    # Next's rewrite sends Host=<backend> and X-Forwarded-Host=<the browser's Host>
    ok = client.get("/health", headers={"host": "localhost:8010", "x-forwarded-host": "127.0.0.1:3000"})
    assert ok.status_code == 200
    r = client.get("/health", headers={"host": "localhost:8010", "x-forwarded-host": "rebind.attacker.example:3000"})
    assert r.status_code == 400


# ── Origin (CSRF) ───────────────────────────────────────────────────────────────────────────────

class _DeskRecorder:
    def __init__(self) -> None:
        self.reenabled = 0

    def reenable(self) -> dict[str, Any]:
        self.reenabled += 1
        return {"reenabled": True, "fake": True}


@pytest.fixture
def desk(monkeypatch: pytest.MonkeyPatch, ui_main: ModuleType) -> _DeskRecorder:
    rec = _DeskRecorder()
    monkeypatch.setattr(sys.modules["routers.desk"], "get_desk", lambda: rec)
    return rec


def test_cross_site_text_plain_post_to_desk_reenable_is_403(client: TestClient, desk: _DeskRecorder) -> None:
    r = client.post("/api/desk/reenable", content=b"x=1",
                    headers={"content-type": "text/plain", "origin": EVIL, "sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "unauthorized"
    assert desk.reenabled == 0                                     # the HARD stop was NOT cleared


def test_form_post_with_null_origin_is_403(client: TestClient, desk: _DeskRecorder) -> None:
    r = client.post("/api/desk/reenable", content=b"",
                    headers={"content-type": "application/x-www-form-urlencoded", "origin": "null"})
    assert r.status_code == 403 and desk.reenabled == 0


def test_cross_site_without_origin_is_403(client: TestClient, desk: _DeskRecorder) -> None:
    assert client.post("/api/desk/reenable", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert desk.reenabled == 0


def test_same_post_without_origin_reaches_the_handler(client: TestClient, desk: _DeskRecorder) -> None:
    r = client.post("/api/desk/reenable", content=b"x=1", headers={"content-type": "text/plain"})
    assert r.status_code == 200 and r.json() == {"reenabled": True, "fake": True}
    assert desk.reenabled == 1                                     # curl / scripts / Telegram path unchanged


@pytest.mark.parametrize("origin", [SAME_ORIGIN, "http://localhost:8010"])
def test_same_origin_post_works(client: TestClient, desk: _DeskRecorder, origin: str) -> None:
    r = client.post("/api/desk/reenable", headers={"origin": origin, "sec-fetch-site": "same-origin"})
    assert r.status_code == 200 and desk.reenabled == 1


@pytest.mark.parametrize("page", ["localhost:3000", "127.0.0.1:3000"])
def test_post_through_the_next_ui_proxy_works(client: TestClient, desk: _DeskRecorder, page: str) -> None:
    # exactly what Next's /api rewrite sends (verified against ui/node_modules/next proxy-request.js)
    r = client.post("/api/desk/reenable", headers={"host": "localhost:8010", "x-forwarded-host": page,
                                                   "origin": f"http://{page}", "sec-fetch-site": "same-origin"})
    assert r.status_code == 200 and desk.reenabled == 1


def test_another_project_on_port_3000_cannot_post_directly(client: TestClient, desk: _DeskRecorder) -> None:
    # a simple POST from some other dev server's page on localhost:3000 straight to :8010 (C2-security-06)
    r = client.post("/api/desk/reenable", headers={"host": "127.0.0.1:8010", "origin": "http://localhost:3000",
                                                   "sec-fetch-site": "same-site"})
    assert r.status_code == 403 and desk.reenabled == 0


def test_get_from_a_foreign_page_is_still_served(client: TestClient) -> None:
    assert client.get("/health", headers={"origin": EVIL, "sec-fetch-site": "cross-site"}).status_code == 200


# ── 'testserver' only under pytest (W2: fix-round-1 adversarial check) ───────────────────────────

def test_testclient_host_is_refused_without_the_pytest_marker(client: TestClient,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from shared.http_guard import ENV_TEST_MARKER
    assert client.get("/health").status_code == 200                       # Host: testserver, under pytest
    monkeypatch.delenv(ENV_TEST_MARKER)                                     # what a uvicorn-run ui-api sees
    r = client.get("/health")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid"
    assert client.get("/health", headers={"host": "127.0.0.1:8010"}).status_code == 200
    r = client.post("/api/prefs/import", json={"items": {}}, headers={"origin": "http://testserver"})
    assert r.status_code == 400                                             # the rebinding shape is refused


# ── /docs and /redoc off by default (completeness-06) ──────────────────────────────────────────

def test_swagger_and_redoc_are_off_by_default(client: TestClient, ui_main: ModuleType) -> None:
    assert ui_main.DOCS_ENABLED is False
    for path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        r = client.get(path, headers={"accept": "application/json"})
        assert r.status_code == 404 and "swagger" not in r.text.lower() and "redoc.standalone" not in r.text
    r = client.get("/openapi.json")
    assert r.status_code == 200 and "/api/prefs" in r.json()["paths"]       # data only, no third-party script


def test_ui_api_docs_1_turns_them_back_on(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    (release / "index.html").write_text("<!doctype html><title>SuryaDhana</title>")
    mp = pytest.MonkeyPatch()
    mp.setenv("UI_DIST_DIR", str(release))
    mp.setenv("UI_API_DOCS", "1")
    import dotenv
    mp.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    try:
        spec = importlib.util.spec_from_file_location("ui_api_main_docs_on", UI_API_DIR / "main.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    c = TestClient(mod.app)
    assert mod.DOCS_ENABLED is True
    assert c.get("/docs").status_code == 200 and "swagger-ui" in c.get("/docs").text
    assert c.get("/redoc").status_code == 200


# ── /api/health alias ───────────────────────────────────────────────────────────────────────────

def test_api_health_alias_has_the_same_body(client: TestClient) -> None:
    a, b = client.get("/health"), client.get("/api/health")
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() == {"status": "ok", "service": "ui-api"}


# ── static UI security headers through the real app ─────────────────────────────────────────────

def test_csp_and_security_headers_on_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200 and "terminal" in r.text
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-cache"                # caching unchanged
    asset = client.get("/_next/static/app.js")
    assert asset.headers["x-content-type-options"] == "nosniff" and asset.headers["referrer-policy"] == "same-origin"
    assert "content-security-policy" not in asset.headers
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    api = client.get("/health")
    assert "content-security-policy" not in api.headers           # API responses untouched


# ── PAPER ONLY execution guard ──────────────────────────────────────────────────────────────────

class FakeEngine:
    """Stands in for live_execution.ExecutionEngine (never the real paper_trades.db)."""

    def __init__(self, mode: str = "LIVE") -> None:
        self.mode = mode
        self.calls: list[tuple[str, Any]] = []

    def get_status(self) -> dict[str, Any]:
        return {"mode": self.mode, "state": "ACTIVE", "open_positions": 0, "equity": 1.0}

    async def set_mode(self, mode: Any) -> None:
        self.calls.append(("set_mode", mode.value))
        self.mode = mode.value

    async def place_order(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("place_order", kw["symbol"]))
        return {"status": "FILLED", "mode": self.mode}

    async def translate_weights_to_orders(self, **kw: Any) -> list[dict[str, Any]]:
        return [{"symbol": "TCS", "side": "BUY", "quantity": 1, "price": 3000.0}]

    async def execute_kill_switch(self, reason: str) -> dict[str, Any]:
        self.calls.append(("kill_switch", reason))
        return {"halted": True}


@pytest.fixture
def execution(ui_main: ModuleType) -> ModuleType:
    mod = sys.modules["routers.execution"]
    if not mod._engine_available:
        pytest.skip("live_execution not importable here")
    return mod


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, execution: ModuleType) -> FakeEngine:
    fake = FakeEngine("PAPER")
    monkeypatch.setattr(execution, "get_engine", lambda: fake)
    monkeypatch.delenv("EXECUTION_LIVE_ALLOWED", raising=False)
    return fake


def test_live_mode_is_refused_without_the_opt_in(client: TestClient, engine: FakeEngine) -> None:
    r = client.post("/api/execution/mode", json={"mode": "LIVE", "confirm_live": True})
    assert r.status_code == 403
    body = r.json()
    assert "PAPER ONLY" in body["detail"] and "EXECUTION_LIVE_ALLOWED=1" in body["error"]["hint"]
    assert engine.mode == "PAPER" and ("set_mode", "LIVE") not in engine.calls


def test_live_mode_is_allowed_with_the_opt_in(client: TestClient, engine: FakeEngine,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_LIVE_ALLOWED", "1")
    assert client.post("/api/execution/mode", json={"mode": "LIVE"}).status_code == 400   # confirm_live still needed
    r = client.post("/api/execution/mode", json={"mode": "LIVE", "confirm_live": True})
    assert r.status_code == 200 and engine.mode == "LIVE"


def test_paper_mode_switch_is_unchanged(client: TestClient, engine: FakeEngine) -> None:
    r = client.post("/api/execution/mode", json={"mode": "PAPER"})
    assert r.status_code == 200 and r.json()["mode"] == "PAPER"


def test_status_exposes_the_mode_policy(client: TestClient, engine: FakeEngine,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    s = client.get("/api/execution/status").json()
    assert (s["mode"], s["live_allowed"], s["mode_policy"]) == ("PAPER", False, "PAPER_ONLY")
    monkeypatch.setenv("EXECUTION_LIVE_ALLOWED", "1")
    s = client.get("/api/execution/status").json()
    assert (s["live_allowed"], s["mode_policy"]) == (True, "LIVE_ALLOWED")


def test_status_switches_a_live_engine_to_paper(client: TestClient, engine: FakeEngine) -> None:
    engine.mode = "LIVE"
    s = client.get("/api/execution/status").json()
    assert s["mode"] == "PAPER" and engine.calls == [("set_mode", "PAPER")]


ORDER = {"symbol": "TCS", "side": "BUY", "quantity": 1, "price": 3000.0}


@pytest.mark.parametrize("path, payload", [
    ("/api/execution/order", ORDER),
    ("/api/execution/rebalance", {"target_weights": {"TCS": 0.1}, "prices": {"TCS": 3000.0}, "dry_run": False}),
    ("/api/execution/liquidate", {"confirm": True}),
])
def test_order_paths_refuse_a_live_engine_without_the_opt_in(client: TestClient, engine: FakeEngine,
                                                             path: str, payload: dict[str, Any]) -> None:
    engine.mode = "LIVE"
    r = client.post(path, json=payload)
    assert r.status_code == 403 and "nothing was sent to the broker" in r.json()["detail"]
    assert engine.calls == [("set_mode", "PAPER")]                 # switched, and no order / kill switch ran
    assert engine.mode == "PAPER"


def test_paper_order_and_dry_run_rebalance_still_work(client: TestClient, engine: FakeEngine) -> None:
    assert client.post("/api/execution/order", json=ORDER).json() == {"status": "FILLED", "mode": "PAPER"}
    engine.mode = "LIVE"                                           # a dry run is not an order path
    r = client.post("/api/execution/rebalance", json={"target_weights": {"TCS": 0.1}, "prices": {"TCS": 3000.0}})
    assert r.status_code == 200 and r.json()["dry_run"] is True and engine.mode == "PAPER"


def test_live_orders_pass_with_the_opt_in(client: TestClient, engine: FakeEngine,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_LIVE_ALLOWED", "1")
    engine.mode = "LIVE"
    assert client.post("/api/execution/order", json=ORDER).json() == {"status": "FILLED", "mode": "LIVE"}
    assert engine.calls == [("place_order", "TCS")]


def test_unreadable_status_fails_closed(client: TestClient, engine: FakeEngine,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> dict[str, Any]:
        raise RuntimeError("boom")
    monkeypatch.setattr(engine, "get_status", broken)
    assert client.post("/api/execution/order", json=ORDER).status_code == 403
    assert ("place_order", "TCS") not in engine.calls


def test_startup_switches_a_restored_live_mode_to_paper(execution: ModuleType, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """The REAL engine on a scratch SQLite: LIVE persisted, restored by a new engine, switched to PAPER
    through its own set_mode at startup, and the PAPER mode is what the next start restores."""
    from live_execution import ExecutionEngine, ExecutionMode

    db = str(tmp_path / "paper_trades.db")
    first = ExecutionEngine(mode=ExecutionMode.PAPER, db_path=db, price_guard_pct=0)
    asyncio.run(first.set_mode(ExecutionMode.LIVE))
    restored = ExecutionEngine(mode=ExecutionMode.PAPER, db_path=db, price_guard_pct=0)
    assert restored.get_status()["mode"] == "LIVE"                 # the C2-security-03 state
    monkeypatch.setattr(execution, "get_engine", lambda: restored)
    monkeypatch.delenv("EXECUTION_LIVE_ALLOWED", raising=False)
    assert asyncio.run(execution.enforce_paper_only_at_startup()) == "switched"
    assert restored.get_status()["mode"] == "PAPER"
    assert ExecutionEngine(db_path=db, price_guard_pct=0).get_status()["mode"] == "PAPER"


def test_startup_keeps_live_with_the_opt_in_and_never_raises(execution: ModuleType,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeEngine("LIVE")
    monkeypatch.setattr(execution, "get_engine", lambda: fake)
    monkeypatch.setenv("EXECUTION_LIVE_ALLOWED", "1")
    assert asyncio.run(execution.enforce_paper_only_at_startup()) == "live_allowed"
    assert fake.mode == "LIVE" and fake.calls == []
    monkeypatch.delenv("EXECUTION_LIVE_ALLOWED")

    def boom() -> FakeEngine:
        raise OSError("disk")
    monkeypatch.setattr(execution, "get_engine", boom)
    assert asyncio.run(execution.enforce_paper_only_at_startup()) == "error"
    monkeypatch.setattr(execution, "get_engine", lambda: FakeEngine("PAPER"))
    assert asyncio.run(execution.enforce_paper_only_at_startup()) == "paper"


def test_lifespan_calls_the_startup_guard(ui_main: ModuleType, execution: ModuleType,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    import inspect
    src = inspect.getsource(ui_main.lifespan)
    assert "execution.enforce_paper_only_at_startup()" in src


# ── prefs: JSON bodies only ─────────────────────────────────────────────────────────────────────

def test_prefs_import_requires_json_content_type(client: TestClient) -> None:
    body = b'{"items": {"junk.1": "x"}, "origin": "http://evil"}'
    r = client.post("/api/prefs/import", content=body, headers={"content-type": "text/plain"})
    assert r.status_code == 415 and r.json()["error"]["code"] == "invalid"
    r = client.post("/api/prefs/import", content=body)             # no Content-Type at all
    assert r.status_code == 415
    assert client.get("/api/prefs").json()["prefs"] == {}           # nothing was stored
    r = client.post("/api/prefs/import", content=body, headers={"content-type": "application/json; charset=utf-8"})
    assert r.status_code == 200 and r.json()["imported"] == ["junk.1"]


def test_prefs_put_requires_json_content_type(client: TestClient) -> None:
    body = b'{"value": "[]", "updated_at": 1000}'
    assert client.put("/api/prefs/watchlist", content=body, headers={"content-type": "text/plain"}).status_code == 415
    assert client.put("/api/prefs/watchlist", json={"value": "[]", "updated_at": 1000}).status_code == 200


# ── monitor WebSocket: Origin + cap ─────────────────────────────────────────────────────────────

@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch, ui_main: ModuleType) -> ModuleType:
    mod = sys.modules["routers.monitor"]

    def no_redis() -> None:
        raise ConnectionError("redis stubbed out in tests")
    monkeypatch.setattr(mod, "_open_quotes_pubsub", no_redis)
    return mod


WS = "/api/monitor/ws/monitor"


def test_ws_from_a_foreign_origin_is_refused(client: TestClient, monitor: ModuleType) -> None:
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect(WS, headers={"origin": EVIL}):
        pass
    assert exc.value.code == 1008
    assert monitor._ws_active == 0


@pytest.mark.parametrize("headers", [{"origin": SAME_ORIGIN}, {}, {"origin": "http://localhost:3000",
                                                                  "x-forwarded-host": "localhost:3000"}])
def test_ws_from_the_terminal_or_a_cli_works(client: TestClient, monitor: ModuleType,
                                             headers: dict[str, str]) -> None:
    with client.websocket_connect(WS, headers=headers) as ws:
        assert ws.receive_json()["error"] == "redis_unavailable"
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"pong": True}
    assert monitor._ws_active == 0 and monitor.manager.active == []


def test_ws_concurrency_is_capped(client: TestClient, monitor: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "MONITOR_WS_MAX", 2)
    with client.websocket_connect(WS) as a, client.websocket_connect(WS) as b:
        a.receive_json()
        b.receive_json()
        assert monitor._ws_active == 2
        with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect(WS):
            pass
        assert exc.value.code == 1013
    with client.websocket_connect(WS) as c:                         # slots are released on close
        assert c.receive_json()["error"] == "redis_unavailable"
    assert monitor._ws_active == 0
