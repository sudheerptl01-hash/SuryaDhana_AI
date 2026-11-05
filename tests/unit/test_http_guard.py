"""shared/http_guard.py: the Host + Origin guard of ui-api, data-service and master-controller
(desktop review C2-security-01/-02/-07/-13).

Pure parsing/decision tests, raw-ASGI middleware tests (HTTP, WebSocket, lifespan pass-through, an SSE
body that must not be buffered) and a Starlette TestClient round trip. No service is imported here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import http_guard as hg
from shared.http_guard import (
    GuardPolicy,
    HostOriginGuard,
    canonical_origin,
    evaluate,
    parse_host,
)

POLICY = GuardPolicy.from_env({})


def _h(**kw: str | list[str]) -> dict[str, list[str]]:
    """Header map as evaluate() takes it: lower-case names, every value."""
    out: dict[str, list[str]] = {}
    for k, v in kw.items():
        out[k.replace("_", "-").lower()] = v if isinstance(v, list) else [v]
    return out


def _decide(method: str = "POST", kind: str = "http", client: Any = ("127.0.0.1", 50000),
            policy: GuardPolicy = POLICY, test_mode: bool = False, **headers: str | list[str]) -> hg.Decision:
    headers.setdefault("host", "127.0.0.1:8010")
    return evaluate(policy, scope_type=kind, method=method, headers=_h(**headers), client=client,
                    test_mode=test_mode)


# ── parsing ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("127.0.0.1:8010", ("127.0.0.1", 8010)),
    ("LocalHost", ("localhost", None)),
    ("  localhost:3000 ", ("localhost", 3000)),
    ("[::1]:8010", ("[::1]", 8010)),
    ("[::1]", ("[::1]", None)),
    ("data-service:8001", ("data-service", 8001)),
    ("mac.tailnet-x.ts.net", ("mac.tailnet-x.ts.net", None)),
])
def test_parse_host_accepts(raw: str, expected: tuple[str, int | None]) -> None:
    assert parse_host(raw) == expected


@pytest.mark.parametrize("raw", [
    "", " ", "::1", "[::1", "[nothost]:80", "localhost:", "localhost:0", "localhost:65536", "localhost:80x",
    "user@localhost", "local host", "localhost/x", "evil.example\r\nX: y", "[::1]x",
])
def test_parse_host_rejects(raw: str) -> None:
    assert parse_host(raw) is None


@pytest.mark.parametrize("raw, expected", [
    ("http://127.0.0.1:8010", "http://127.0.0.1:8010"),
    ("HTTP://LOCALHOST:8010/", "http://localhost:8010"),
    ("http://localhost:80", "http://localhost"),
    ("https://mac.ts.net:443", "https://mac.ts.net"),
    ("http://[::1]:8010", "http://[::1]:8010"),
])
def test_canonical_origin(raw: str, expected: str) -> None:
    assert canonical_origin(raw) == expected


@pytest.mark.parametrize("raw", [
    "null", "NULL", "", "file://", "ftp://localhost", "http://", "http://u:p@localhost:8010",
    "http://localhost:8010/path", "http://localhost:8010?q=1", "http://localhost:99999", "tauri://localhost",
])
def test_canonical_origin_rejects(raw: str) -> None:
    assert canonical_origin(raw) is None


def test_policy_defaults_and_env() -> None:
    assert POLICY.host_allowed(("127.0.0.1", 8010)) and POLICY.host_allowed(("localhost", 3000))
    assert POLICY.host_allowed(("[::1]", None))
    assert not POLICY.host_allowed(("testserver", None))        # TestClient's host: test mode only (below)
    assert not POLICY.host_allowed(("data-service", 8001))
    assert POLICY.origins == frozenset(hg.DEFAULT_ALLOWED_ORIGINS)
    assert POLICY.remote_writes is False
    p = GuardPolicy.from_env({hg.ENV_ALLOWED_HOSTS: "data-service, mac.ts.net:8010,,bad host",
                              hg.ENV_ALLOWED_ORIGINS: "https://mac.ts.net, null",
                              hg.ENV_REMOTE_WRITES: "1"})
    assert p.host_allowed(("data-service", 1234))                      # no port in the entry: any port
    assert p.host_allowed(("mac.ts.net", 8010)) and not p.host_allowed(("mac.ts.net", 8001))
    assert "https://mac.ts.net" in p.origins
    assert p.remote_writes is True
    assert p.ignored == (f"{hg.ENV_ALLOWED_HOSTS} entry 3", f"{hg.ENV_ALLOWED_ORIGINS} entry 2")


def test_remote_writes_needs_exactly_one() -> None:
    for v in ("", "0", "true", "yes", " 2 "):
        assert GuardPolicy.from_env({hg.ENV_REMOTE_WRITES: v}).remote_writes is False


# ── decisions: Host ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1:8010", "localhost:8010", "[::1]:8010", "LOCALHOST:8001"])
def test_loopback_hosts_allowed_for_every_method(host: str) -> None:
    for method in ("GET", "HEAD", "POST", "DELETE"):
        assert _decide(method, host=host).allowed


@pytest.mark.parametrize("host", ["rebind.attacker.example", "rebind.attacker.example:8010", "192.168.31.62:8010",
                                  "localhost.:8010", "127.0.0.2:8010", "data-service:8001", "", "a b"])
def test_foreign_host_is_400_even_for_get(host: str) -> None:
    d = _decide("GET", host=host)
    assert (d.allowed, d.status, d.reason) == (False, 400, "bad_host")


def test_missing_or_duplicate_host_is_400() -> None:
    assert evaluate(POLICY, scope_type="http", method="GET", headers={}).status == 400
    d = _decide("GET", host=["127.0.0.1:8010", "evil.example"])
    assert (d.status, d.reason) == (400, "bad_host")


def test_forwarded_host_is_checked_like_host() -> None:
    # Next's /api rewrite: Host becomes the backend's, X-Forwarded-Host carries the browser's Host.
    assert _decide("GET", host="localhost:8010", x_forwarded_host="127.0.0.1:3000").allowed
    assert _decide("GET", host="localhost:8010", x_forwarded_host="localhost:3000, 127.0.0.1:8010").allowed
    d = _decide("GET", host="localhost:8010", x_forwarded_host="rebind.attacker.example:3000")
    assert (d.status, d.reason) == (400, "bad_forwarded_host")
    d = _decide("GET", host="localhost:8010", x_forwarded_host="localhost:3000, evil.example")
    assert d.reason == "bad_forwarded_host"


def test_extra_hosts_from_env() -> None:
    p = GuardPolicy.from_env({hg.ENV_ALLOWED_HOSTS: "data-service,ui-api"})
    assert _decide("GET", policy=p, host="data-service:8001").allowed
    assert not _decide("GET", policy=p, host="master-controller:8008").allowed


# ── decisions: Origin / Sec-Fetch-Site (unsafe methods + WebSocket) ─────────────────────────────

@pytest.mark.parametrize("origin", list(hg.DEFAULT_ALLOWED_ORIGINS))
def test_allowed_origins_may_write(origin: str) -> None:
    assert _decide("POST", origin=origin, sec_fetch_site="same-origin").allowed


@pytest.mark.parametrize("origin", list(hg.PROXIED_UI_ORIGINS))
def test_next_ui_origin_is_admitted_only_through_its_own_proxy(origin: str) -> None:
    page_host = origin.split("://", 1)[1]
    # the :3000 server's /api rewrite: Host = backend, X-Forwarded-Host = the page's host, Origin forwarded
    assert _decide("POST", host="localhost:8010", origin=origin, x_forwarded_host=page_host,
                   sec_fetch_site="same-origin").allowed
    assert _decide("GET", kind="websocket", host="localhost:8010", origin=origin, x_forwarded_host=page_host).allowed
    # another project's page on :3000 posting straight to :8010 (no proxy header) is refused
    d = _decide("POST", host="localhost:8010", origin=origin)
    assert (d.status, d.reason) == (403, "origin_not_allowed")
    # a proxy that forwards some other host does not vouch for this origin
    assert not _decide("POST", host="localhost:8010", origin=origin, x_forwarded_host="localhost:3001").allowed


def test_no_origin_and_no_fetch_metadata_is_a_non_browser_client() -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert _decide(method).allowed                        # curl, httpx, scripts, the Telegram bot path


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:3001", "http://127.0.0.1:5173",
                                    "http://192.168.31.62:8010", "http://localhost:8010/x", "garbage"])
def test_foreign_origin_cannot_write(origin: str) -> None:
    d = _decide("POST", origin=origin)
    assert (d.allowed, d.status, d.reason) == (False, 403, "origin_not_allowed")


def test_null_origin_is_refused() -> None:
    d = _decide("POST", origin="null")
    assert (d.status, d.reason) == (403, "null_origin")


def test_duplicate_origin_is_refused() -> None:
    assert _decide("POST", origin=["http://127.0.0.1:8010", "https://evil.example"]).status == 403


def test_cross_site_fetch_metadata_is_refused_without_origin() -> None:
    d = _decide("POST", sec_fetch_site="cross-site")
    assert (d.status, d.reason) == (403, "cross_site")
    assert _decide("POST", sec_fetch_site="same-origin").allowed
    assert _decide("POST", sec_fetch_site="none").allowed


def test_cross_site_is_refused_even_with_an_allowed_origin() -> None:
    assert _decide("POST", origin="http://127.0.0.1:8010", sec_fetch_site="cross-site").reason == "cross_site"


def test_same_origin_as_the_allowed_host_may_write() -> None:
    # a service's own page (e.g. data-service /docs on :8001) is same-origin by definition
    assert _decide("POST", host="localhost:8001", origin="http://localhost:8001").allowed
    assert _decide("POST", host="testserver", origin="http://testserver", test_mode=True).allowed
    assert not _decide("POST", host="localhost:8001", origin="http://localhost:8002").allowed
    assert not _decide("POST", host="localhost:8001", origin="http://127.0.0.1:8001").allowed
    assert _decide("POST", host="localhost", origin="https://localhost").allowed   # behind a TLS proxy: 443 both
    assert not _decide("POST", host="localhost", origin="http://localhost:8001").allowed     # 80 != 8001


def test_safe_methods_ignore_origin() -> None:
    for method in ("GET", "HEAD", "OPTIONS"):
        assert _decide(method, origin="https://evil.example", sec_fetch_site="cross-site").allowed


def test_websocket_handshake_checks_origin() -> None:
    assert _decide("GET", kind="websocket", origin="http://127.0.0.1:8010").allowed
    assert _decide("GET", kind="websocket").allowed                          # CLI ws client, no Origin
    d = _decide("GET", kind="websocket", origin="https://evil.example")
    assert (d.allowed, d.status) == (False, 403)
    assert _decide("GET", kind="websocket", host="evil.example").status == 400


def test_extra_origins_from_env() -> None:
    # remote writes on: a tailnet Host is remote since RAPI-03, so the origin rule is only reached when they may write
    p = GuardPolicy.from_env({hg.ENV_ALLOWED_ORIGINS: "https://mac.ts.net", hg.ENV_ALLOWED_HOSTS: "mac.ts.net",
                              hg.ENV_REMOTE_WRITES: "1"})
    assert _decide("POST", policy=p, host="mac.ts.net", origin="https://mac.ts.net").allowed
    assert not _decide("POST", policy=p, host="mac.ts.net", origin="https://other.ts.net").allowed


# ── RAPI-03: a non-loopback Host (or X-Forwarded-Host) is a remote client even without X-Forwarded-For ─────

TAILNET = GuardPolicy.from_env({hg.ENV_ALLOWED_HOSTS: "mac.tailnet-x.ts.net"})


@pytest.mark.parametrize("host, origin", [
    ("mac.tailnet-x.ts.net", "https://mac.tailnet-x.ts.net"),        # tailscale serve --tcp / ssh -R: no XFF
    ("mac.tailnet-x.ts.net:8010", "http://mac.tailnet-x.ts.net:8010"),
    ("mac.tailnet-x.ts.net", None),                                   # a non-browser client
])
def test_a_tailnet_host_without_x_forwarded_for_cannot_write(host: str, origin: str | None) -> None:
    hdrs = {"host": host, **({"origin": origin} if origin else {})}
    d = _decide("POST", policy=TAILNET, client=("127.0.0.1", 50000), **hdrs)
    assert (d.status, d.reason) == (403, "remote_write")
    assert _decide("GET", policy=TAILNET, client=("127.0.0.1", 50000), **hdrs).allowed      # reads stay open
    rw = GuardPolicy.from_env({hg.ENV_ALLOWED_HOSTS: "mac.tailnet-x.ts.net", hg.ENV_REMOTE_WRITES: "1"})
    assert _decide("POST", policy=rw, client=("127.0.0.1", 50000), **hdrs).allowed


def test_the_same_write_with_x_forwarded_for_was_already_refused() -> None:
    """Control: the pre-RAPI-03 rule caught this only because Serve adds X-Forwarded-For."""
    d = _decide("POST", policy=TAILNET, host="mac.tailnet-x.ts.net", origin="https://mac.tailnet-x.ts.net",
                x_forwarded_for="100.101.102.103")
    assert d.reason == "remote_write"


def test_a_tailnet_forwarded_host_is_remote_too() -> None:
    d = _decide("POST", policy=TAILNET, host="127.0.0.1:8010", x_forwarded_host="mac.tailnet-x.ts.net",
                origin="https://mac.tailnet-x.ts.net")
    assert (d.status, d.reason) == (403, "remote_write")


@pytest.mark.parametrize("host, xfh, origin", [
    ("127.0.0.1:8010", None, "http://127.0.0.1:8010"),               # the terminal / desktop app
    ("localhost:8010", None, None),                                  # scripts, the shell's poller
    ("[::1]:8010", None, None),
    ("127.0.0.1:8010", "localhost:3000", "http://localhost:3000"),   # the optional Next :3000 rewrite
    ("localhost:8010", "127.0.0.1:8092", "http://127.0.0.1:8092"),   # a QA scratch proxy
])
def test_loopback_names_stay_local(host: str, xfh: str | None, origin: str | None) -> None:
    hdrs = {"host": host, **({"x_forwarded_host": xfh} if xfh else {}), **({"origin": origin} if origin else {})}
    assert _decide("POST", **hdrs).allowed


def test_test_mode_needs_the_pytest_module_too() -> None:
    """RAPI-11: a process that only inherited PYTEST_CURRENT_TEST (a service started from a test with env=None)
    never imports pytest, so it stays in production mode."""
    marker = {hg.ENV_TEST_MARKER: "tests/x.py::t (call)"}
    assert hg.in_test_mode(marker, modules={"pytest": object()}) is True
    assert hg.in_test_mode(marker, modules={}) is False
    assert hg.in_test_mode({}, modules={"pytest": object()}) is False


def test_the_guard_warns_when_it_starts_in_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(hg.log, "warning", lambda msg, *a, **k: seen.append(msg))

    async def app(scope: Any, receive: Any, send: Any) -> None:
        return None
    HostOriginGuard(app, service="t", env={})                        # pytest is running: test mode
    assert "http_guard.test_mode_active" in seen
    seen.clear()
    HostOriginGuard(app, service="t", env={}, test_mode=False)
    assert "http_guard.test_mode_active" not in seen


# ── decisions: remote peers are read-only ───────────────────────────────────────────────────────

def test_remote_peer_reads_but_cannot_write() -> None:
    p = GuardPolicy.from_env({hg.ENV_ALLOWED_HOSTS: "192.168.31.62"})
    lan = ("192.168.31.70", 51000)
    assert _decide("GET", policy=p, client=lan, host="192.168.31.62:8010").allowed
    d = _decide("POST", policy=p, client=lan, host="192.168.31.62:8010")
    assert (d.status, d.reason) == (403, "remote_write")
    assert _decide("GET", kind="websocket", policy=p, client=lan, host="192.168.31.62:8010").allowed
    p_rw = GuardPolicy.from_env({hg.ENV_ALLOWED_HOSTS: "192.168.31.62", hg.ENV_REMOTE_WRITES: "1"})
    assert _decide("POST", policy=p_rw, client=lan, host="192.168.31.62:8010").allowed


@pytest.mark.parametrize("client", [("127.0.0.1", 1), ("::1", 1), ("::ffff:127.0.0.1", 1), None])
def test_local_peers(client: Any) -> None:
    assert _decide("POST", client=client).allowed


def test_testclient_peer_is_local_only_in_test_mode() -> None:
    assert _decide("POST", client=("testclient", 50000), test_mode=True).allowed
    d = _decide("POST", client=("testclient", 50000))
    assert (d.status, d.reason) == (403, "remote_write")


# ── 'testserver' (Starlette TestClient) is a test-only Host (fix-round-1 adversarial check) ─────────

def test_testserver_host_is_refused_outside_test_mode() -> None:
    for method in ("GET", "POST"):
        d = _decide(method, host="testserver")
        assert (d.allowed, d.status, d.reason) == (False, 400, "bad_host")
        d = _decide(method, host="testserver:8010", origin="http://testserver:8010")
        assert (d.allowed, d.status) == (False, 400)
    assert _decide("GET", host="testserver", test_mode=True).allowed
    assert _decide("POST", host="testserver", test_mode=True).allowed


def test_rebinding_with_a_forged_testclient_peer_is_still_refused() -> None:
    """The attack the old default allowed: http://testserver:8010 rebound to 127.0.0.1 (single-label DNS on a
    hostile network), plus X-Forwarded-For: testclient:50000, which uvicorn (trusting the header from 127.0.0.1)
    turns into scope client ('testclient', 50000). Outside pytest that is a foreign Host."""
    d = _decide("POST", host="testserver:8010", origin="http://testserver:8010", client=("testclient", 50000),
                x_forwarded_for="testclient:50000")
    assert (d.status, d.reason) == (400, "bad_host")


def test_testserver_is_not_admitted_as_a_forwarded_host() -> None:
    d = _decide("GET", host="localhost:8010", x_forwarded_host="testserver", test_mode=True)
    assert d.reason == "bad_forwarded_host"


def test_in_test_mode_reads_the_pytest_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    assert hg.in_test_mode() is True                               # pytest sets PYTEST_CURRENT_TEST now
    assert hg.in_test_mode({}) is False
    assert hg.in_test_mode({hg.ENV_TEST_MARKER: "tests/x.py::t (call)"}) is True
    monkeypatch.delenv(hg.ENV_TEST_MARKER)
    assert hg.in_test_mode() is False


def test_testclient_round_trip_needs_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    def app_with(test_mode: bool | None) -> FastAPI:
        app = FastAPI()
        hg.install_http_guard(app, service="t", env={}, test_mode=test_mode)

        @app.get("/r")
        async def r() -> dict[str, bool]:
            return {"ok": True}
        return app

    assert TestClient(app_with(None)).get("/r").status_code == 200        # auto: pytest is running
    assert TestClient(app_with(True)).get("/r").status_code == 200
    assert TestClient(app_with(False)).get("/r").status_code == 400       # production behaviour
    assert TestClient(app_with(False)).get("/r", headers={"host": "127.0.0.1:8010"}).status_code == 200
    monkeypatch.delenv(hg.ENV_TEST_MARKER)
    assert TestClient(app_with(None)).get("/r").status_code == 400        # no marker: production
    assert TestClient(app_with(None)).get("/r", headers={"host": "localhost:8010"}).status_code == 200


# ── X-Forwarded-For: clients behind a local reverse proxy (Tailscale Serve) ─────────────────────────

@pytest.mark.parametrize("value, local", [
    ("127.0.0.1", True), ("127.0.0.1:5123", True), ("::1", True), ("[::1]:443", True), ("::ffff:127.0.0.1", True),
    ("100.101.102.103", False), ("fd7a:115c:a1e0::1", False), ("192.168.31.70:51000", False),
    ("testclient", False), ("garbage", False), ("", False),
])
def test_loopback_address_literals(value: str, local: bool) -> None:
    assert hg._is_loopback_address(value) is local


def test_a_forwarded_remote_client_is_read_only() -> None:
    tailnet = {"x_forwarded_for": "100.101.102.103"}
    assert _decide("GET", **tailnet).allowed
    assert _decide("GET", kind="websocket", **tailnet).allowed
    d = _decide("POST", **tailnet)
    assert (d.status, d.reason) == (403, "remote_write")
    d = _decide("POST", x_forwarded_for="127.0.0.1, 100.101.102.103")   # any non-loopback hop counts
    assert d.reason == "remote_write"
    d = _decide("POST", x_forwarded_for=["127.0.0.1", "fd7a:115c:a1e0::5"])
    assert d.reason == "remote_write"
    assert _decide("POST", x_forwarded_for="127.0.0.1").allowed          # a local proxy hop stays local
    assert _decide("POST", x_forwarded_for="::1, 127.0.0.1").allowed
    p_rw = GuardPolicy.from_env({hg.ENV_REMOTE_WRITES: "1"})
    assert _decide("POST", policy=p_rw, **tailnet).allowed


def test_tailscale_serve_request_shape() -> None:
    """tailscale serve --bg 8010: peer 127.0.0.1, Host and X-Forwarded-Host = the ts.net name, X-Forwarded-For =
    the tailnet device, Origin = https://<name>. Needs GUARD_ALLOWED_HOSTS; then reads work and writes need
    GUARD_ALLOW_REMOTE_WRITES=1 (uvicorn's own X-Forwarded-For handling gives the same answer, see the next test)."""
    name = "mac.tailnet-x.ts.net"
    shape = {"host": name, "x_forwarded_host": name, "x_forwarded_for": "100.101.102.103",
             "origin": f"https://{name}", "sec_fetch_site": "same-origin"}
    assert _decide("GET", **shape).reason == "bad_host"                  # not listed: 400 even for reads
    p = GuardPolicy.from_env({hg.ENV_ALLOWED_HOSTS: name})
    assert _decide("GET", policy=p, **shape).allowed
    assert _decide("POST", policy=p, **shape).reason == "remote_write"
    p_rw = GuardPolicy.from_env({hg.ENV_ALLOWED_HOSTS: name, hg.ENV_REMOTE_WRITES: "1"})
    assert _decide("POST", policy=p_rw, **shape).allowed
    assert _decide("POST", policy=p_rw, **{**shape, "origin": "https://evil.example"}).reason == "origin_not_allowed"


def test_uvicorn_rewritten_peer_is_remote_too() -> None:
    # uvicorn trusts X-Forwarded-For from 127.0.0.1 and sets scope["client"] to the forwarded address
    d = _decide("POST", client=("100.101.102.103", 0), x_forwarded_for="100.101.102.103")
    assert d.reason == "remote_write"


# ── the ASGI middleware ─────────────────────────────────────────────────────────────────────────

def _scope(kind: str = "http", method: str = "POST", path: str = "/api/desk/reenable",
           headers: list[tuple[str, str]] | None = None, client: Any = ("127.0.0.1", 50000)) -> dict[str, Any]:
    hdrs = headers if headers is not None else [("host", "127.0.0.1:8010")]
    return {"type": kind, "method": method, "path": path, "client": client,
            "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in hdrs]}


class _Recorder:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.calls += 1
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


async def _run(guard: HostOriginGuard, scope: dict[str, Any],
               incoming: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    queue = list(incoming or [{"type": "http.request", "body": b"", "more_body": False}])

    async def receive() -> dict[str, Any]:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await guard(scope, receive, send)
    return sent


def test_middleware_passes_allowed_requests_through_untouched() -> None:
    app = _Recorder()
    sent = asyncio.run(_run(HostOriginGuard(app, policy=POLICY), _scope()))
    assert app.calls == 1 and sent[0]["status"] == 200


def test_middleware_answers_400_and_403_with_the_error_envelope() -> None:
    app = _Recorder()
    guard = HostOriginGuard(app, policy=POLICY, service="t")
    sent = asyncio.run(_run(guard, _scope(method="GET", headers=[("host", "rebind.attacker.example")])))
    assert sent[0]["status"] == 400
    body = json.loads(sent[1]["body"])
    assert body["detail"] == "Host header not allowed" and body["error"]["code"] == "invalid"
    assert (b"content-type", b"application/json") in sent[0]["headers"]
    sent = asyncio.run(_run(guard, _scope(headers=[("host", "127.0.0.1:8010"), ("origin", "https://evil.example"),
                                                   ("content-type", "text/plain")])))
    assert sent[0]["status"] == 403
    body = json.loads(sent[1]["body"])
    assert isinstance(body["detail"], str) and body["error"]["code"] == "unauthorized" and body["error"]["hint"]
    assert app.calls == 0                                       # the handler never ran


def test_middleware_rejects_websocket_before_accept() -> None:
    app = _Recorder()
    guard = HostOriginGuard(app, policy=POLICY)
    scope = _scope(kind="websocket", method="GET", path="/api/monitor/ws/monitor",
                   headers=[("host", "127.0.0.1:8010"), ("origin", "https://evil.example")])
    sent = asyncio.run(_run(guard, scope, [{"type": "websocket.connect"}]))
    assert sent == [{"type": "websocket.close", "code": 1008, "reason": "origin or host not allowed"}]
    assert app.calls == 0


def test_middleware_ignores_lifespan_scope() -> None:
    seen: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    asyncio.run(_run(HostOriginGuard(app, policy=POLICY), {"type": "lifespan"}))
    assert seen == ["lifespan"]


def test_streaming_response_is_not_buffered() -> None:
    """Each SSE chunk reaches the server's send() before the app produces the next one (a buffering
    middleware would deadlock here: the app waits for the client to see chunk i)."""
    gates = [asyncio.Event() for _ in range(3)]

    async def sse_app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        for i, gate in enumerate(gates):
            await send({"type": "http.response.body", "body": f"data: {i}\n\n".encode(), "more_body": True})
            await gate.wait()
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def main() -> list[bytes]:
        chunks: list[bytes] = []

        async def receive() -> dict[str, Any]:
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                chunks.append(message["body"])
                gates[len(chunks) - 1].set()

        guard = HostOriginGuard(sse_app, policy=POLICY)
        await asyncio.wait_for(guard(_scope(method="GET", path="/api/telemetry/logs/stream"), receive, send), 5)
        return chunks

    assert asyncio.run(main()) == [b"data: 0\n\n", b"data: 1\n\n", b"data: 2\n\n"]


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_rejections_are_logged_once_per_reason_and_path_per_minute_without_values() -> None:
    cap = _Capture()
    hg.log.addHandler(cap)
    try:
        guard = HostOriginGuard(_Recorder(), policy=POLICY, service="ui-api")
        bad = _scope(headers=[("host", "127.0.0.1:8010"), ("origin", "https://evil.example")])
        for _ in range(5):
            asyncio.run(_run(guard, bad))
        asyncio.run(_run(guard, _scope(path="/api/execution/order",
                                       headers=[("host", "127.0.0.1:8010"), ("origin", "https://evil.example")])))
        rejected = [r for r in cap.records if r.getMessage() == "http_guard.rejected"]
        assert [r.fields["path"] for r in rejected] == ["/api/desk/reenable", "/api/execution/order"]  # type: ignore[attr-defined]
        fields = rejected[0].fields  # type: ignore[attr-defined]
        assert fields["reason"] == "origin_not_allowed" and fields["service"] == "ui-api" and fields["peer"] == "loopback"
        text = json.dumps([r.fields for r in rejected])  # type: ignore[attr-defined]
        assert "evil.example" not in text and "127.0.0.1" not in text
        forwarded = _scope(headers=[("host", "127.0.0.1:8010"), ("x-forwarded-for", "100.101.102.103")])
        sent = asyncio.run(_run(guard, forwarded))
        assert sent[0]["status"] == 403
        last = [r for r in cap.records if r.getMessage() == "http_guard.rejected"][-1]
        assert last.fields["reason"] == "remote_write" and last.fields["peer"] == "remote"  # type: ignore[attr-defined]
        assert "100.101" not in json.dumps(last.fields)  # type: ignore[attr-defined]
    finally:
        hg.log.removeHandler(cap)


def test_reject_log_window_and_suppressed_count() -> None:
    rl = hg._RejectLog(window_s=60.0, max_keys=4)
    assert rl.admit("bad_host", "/a", now=0.0) == 0
    assert rl.admit("bad_host", "/a", now=10.0) is None
    assert rl.admit("bad_host", "/a", now=20.0) is None
    assert rl.admit("bad_host", "/a", now=61.0) == 2
    for i in range(10):                                         # a path scan: bounded memory
        rl.admit("bad_host", f"/scan/{i}", now=62.0)
    assert len(rl._seen) <= 5


def test_install_makes_the_guard_the_outermost_middleware() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.middleware.gzip import GZipMiddleware

    app = FastAPI()
    app.add_middleware(GZipMiddleware)
    hg.install_http_guard(app, service="t", env={})

    @app.post("/w")
    async def w() -> dict[str, bool]:
        return {"ok": True}

    assert app.user_middleware[0].cls is HostOriginGuard
    c = TestClient(app)
    assert c.post("/w").json() == {"ok": True}
    assert c.post("/w", headers={"origin": "http://127.0.0.1:8010"}).status_code == 200
    assert c.post("/w", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.get("/w", headers={"host": "evil.example"}).status_code == 400
