"""Host + Origin guard for the local SuryaDhana HTTP services (desktop review C2-security-01/-02/-07/-13).

ui-api (:8010), data-service (:8001) and master-controller (:8008) have no login: they are meant to be
reached only from this Mac. Two browser attacks reach them anyway, and this pure-ASGI middleware closes
both. It is installed as the OUTERMOST user middleware of each service (``install_http_guard``).

* DNS rebinding: a web page re-points its own hostname at 127.0.0.1 and then talks to the service as a
  same-origin page, reading every GET and sending JSON writes. The browser still sends the attacker's
  hostname in ``Host``, so every request (HTTP and WebSocket, any method) must carry an allowed ``Host``:
  ``127.0.0.1``, ``localhost`` or ``[::1]`` on any port, plus the names in ``GUARD_ALLOWED_HOSTS``.
  Starlette's TestClient host ``testserver`` is accepted only while pytest is running a test in this very
  process (the ``PYTEST_CURRENT_TEST`` variable pytest sets for every test is in the environment AND the
  ``pytest`` module is loaded, so a child process that merely inherited the variable does not qualify),
  never in a service started by uvicorn/launchd: on a network whose DNS search domain an attacker controls,
  ``http://testserver:8010`` could otherwise be rebound to 127.0.0.1 and pass both checks below. Another
  harness lists it in ``GUARD_ALLOWED_HOSTS`` explicitly. Each ``X-Forwarded-Host`` entry must pass the
  same check: Next's
  ``/api`` rewrite proxy (the optional :3000 UI) replaces ``Host`` with the backend's and forwards the
  browser's original ``Host`` there, so without this a rebinding page could read the API through :3000.
  Anything else gets 400.
* Cross-site requests (CSRF): a page on another site auto-submits a form or a ``text/plain`` fetch, which
  needs no CORS preflight. For unsafe methods (anything but GET/HEAD/OPTIONS) and WebSocket handshakes,
  an ``Origin`` header, when present, must be one of:

  - the terminal's origins ``http://127.0.0.1:8010`` / ``http://localhost:8010`` or a name in
    ``GUARD_ALLOWED_ORIGINS``;
  - the request's own origin: ``Origin`` equals ``Host`` (already allowlisted), so a service's own
    ``/docs`` page keeps working;
  - the origin of a loopback proxy in front: ``Origin`` equals an ``X-Forwarded-Host`` entry (also
    allowlisted). This is how the optional Next UI on :3000 is admitted: its ``/api`` rewrite forwards
    ``Origin: http://localhost:3000`` with ``X-Forwarded-Host: localhost:3000``. A page of ANOTHER project
    served on localhost:3000 that posts straight to :8010 carries no such header (a browser cannot add
    it to a simple request) and is refused, which is why the :3000 origins are not listed outright.

  ``Origin: null`` is refused; ``Sec-Fetch-Site: cross-site`` is refused. A request with neither header
  is not from a browser page (curl, httpx between services, scripts/*, the Telegram bot path,
  scripts/daily_session_refresh.py, the desktop shell's health poller) and is allowed. Rejections get 403.
* Remote clients are read-only (backend side of C2-security-02). Every service binds 127.0.0.1 only (the
  old ``UI_API_HOST=0.0.0.0`` LAN opt-in is gone), so another machine can reach one only through a reverse
  proxy running on this Mac: Tailscale Serve for the phone/iPad (docs/RUNBOOK_RESTORE.md section 7). A
  client counts as REMOTE when its socket peer is not loopback, when any ``X-Forwarded-For`` entry is not a
  loopback address, or when its ``Host`` or any ``X-Forwarded-Host`` entry is not a loopback name
  (``127.0.0.1``/``127.x``, ``localhost``, ``[::1]``; desktop review RAPI-03). Tailscale Serve sets
  ``X-Forwarded-For`` to the tailnet device's address (and uvicorn, which trusts that header from 127.0.0.1
  by default, reports the same client); the Host rule also catches a forwarder that adds no
  ``X-Forwarded-For`` (``tailscale serve --tcp``, ``ssh -R``, another local proxy), because the browser's
  ``Host`` is then the tailnet or forwarded name. Remote clients may read (GET, HEAD, OPTIONS and
  WebSocket); their unsafe requests (prefs writes, compute POSTs, paper orders) get 403 unless
  ``GUARD_ALLOW_REMOTE_WRITES=1``. Local callers send no ``X-Forwarded-For`` and use loopback names: the
  terminal, the desktop shell, scripts, and Next :3000 (its ``/api`` rewrite sets only
  ``X-Forwarded-Host: localhost:3000``), so they stay local. A local page that sends a forged
  ``X-Forwarded-For`` only makes itself read-only. (The legacy Docker stack, whose containers call each other
  by service name, sets ``GUARD_ALLOW_REMOTE_WRITES=1``.)

Configuration (environment, read when the middleware is built, i.e. at service start):

``GUARD_ALLOWED_HOSTS``
    Comma list of extra Host names, each optionally with a port (``name`` = any port, ``name:8010`` = that
    port only; IPv6 in brackets). Examples: the Tailscale Serve name (``mac.tailnet-x.ts.net``: Serve
    keeps the browser's Host), and for the legacy Docker stack the service DNS names the containers use
    for each other: ``data-service,ui-api,master-controller``.
``GUARD_ALLOWED_ORIGINS``
    Comma list of extra browser origins allowed to write. Rarely needed: an origin equal to an allowed
    Host is already admitted (``https://mac.tailnet-x.ts.net`` with that Host listed above).
``GUARD_ALLOW_REMOTE_WRITES``
    ``1`` lets remote clients (above) use unsafe methods, e.g. a tailnet iPad that should save settings
    and send compute requests. Off by default; only devices that can reach the proxy are affected.

Responses use the ui-api error envelope (``{"detail": str, "error": {"code", "message", "hint"}}``, see
services/ui-api/errors.py); ``detail`` stays a plain string, so FastAPI-default clients read it as before.
A refused WebSocket handshake is closed with 1008 before accept (servers answer the handshake with 403).
Allowed requests pass straight through with the original ``receive``/``send``: nothing is buffered, so
SSE and streaming responses are untouched.

Logging: one structured JSON line per (reason, path) per minute (``http_guard.rejected``) with the
service, reason, method, path and a suppressed count. Header values and client addresses are never
logged (the peer is reported only as ``loopback`` or ``remote``).

Stdlib only (no Starlette import), so every service can install it and it is unit-testable as raw ASGI.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

__all__ = [
    "DEFAULT_ALLOWED_HOSTS",
    "DEFAULT_ALLOWED_ORIGINS",
    "ENV_ALLOWED_HOSTS",
    "ENV_ALLOWED_ORIGINS",
    "ENV_REMOTE_WRITES",
    "ENV_TEST_MARKER",
    "PROXIED_UI_ORIGINS",
    "TEST_CLIENT_HOST",
    "Decision",
    "GuardPolicy",
    "HostOriginGuard",
    "canonical_origin",
    "evaluate",
    "in_test_mode",
    "install_http_guard",
    "parse_host",
]

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

ENV_ALLOWED_HOSTS = "GUARD_ALLOWED_HOSTS"
ENV_ALLOWED_ORIGINS = "GUARD_ALLOWED_ORIGINS"
ENV_REMOTE_WRITES = "GUARD_ALLOW_REMOTE_WRITES"

DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]")
# Starlette's TestClient: its Host and its scope["client"] host. Accepted only in test mode (see the docstring).
TEST_CLIENT_HOST = "testserver"
ENV_TEST_MARKER = "PYTEST_CURRENT_TEST"
DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = ("http://127.0.0.1:8010", "http://localhost:8010")
# Admitted only through their own server's /api proxy (Origin == X-Forwarded-Host), see the module docstring.
PROXIED_UI_ORIGINS: tuple[str, ...] = ("http://127.0.0.1:3000", "http://localhost:3000")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")
_TESTCLIENT_PEER = "testclient"  # Starlette TestClient's scope["client"] host (local only in test mode)

HostEntry = tuple[str, int | None]


# ── parsing (pure) ───────────────────────────────────────────────────────────────────────────────

def parse_host(value: str) -> HostEntry | None:
    """``'LocalHost:8010'`` → ``('localhost', 8010)``; ``'[::1]'`` → ``('[::1]', None)``; None if malformed.

    Accepts a DNS name or IPv4 literal (letters, digits, ``.-_``) or a bracketed IPv6 literal, with an
    optional port 1-65535. Userinfo, paths, spaces and bare (unbracketed) IPv6 are malformed."""
    v = value.strip().lower()
    if not v or len(v) > 255:
        return None
    port_s: str | None = None
    if v.startswith("["):
        end = v.find("]")
        if end <= 1:
            return None
        host, rest = v[: end + 1], v[end + 1:]
        try:
            ip_address(host[1:-1])
        except ValueError:
            return None
        if rest:
            if not rest.startswith(":"):
                return None
            port_s = rest[1:]
    else:
        host, sep, tail = v.partition(":")
        if sep:
            port_s = tail
        if not host or not set(host) <= _HOST_CHARS:
            return None
    if port_s is None:
        return host, None
    if not port_s.isdigit() or len(port_s) > 5 or not 0 < int(port_s) <= 65535:
        return None
    return host, int(port_s)


def canonical_origin(value: str) -> str | None:
    """Serialized origin (``scheme://host[:port]``, lower case, default port dropped); None if invalid.

    ``'null'`` and anything with a path, query, fragment or userinfo is invalid."""
    v = value.strip()
    if not v or v.lower() == "null":
        return None
    try:
        parts = urlsplit(v)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname or parts.username is not None or parts.password is not None:
        return None
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if parse_host(host) is None:
        return None
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _split_list(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def _is_loopback_address(value: str) -> bool:
    """A loopback IP literal (IPv4, IPv6 incl. IPv4-mapped, optionally bracketed or with a port)."""
    v = value.strip()
    if v.startswith("["):
        v = v[1:].split("]", 1)[0]
    elif v.count(":") == 1:                       # IPv4 with a port; bare IPv6 has several colons
        v = v.split(":", 1)[0]
    try:
        ip = ip_address(v)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(ip.is_loopback or (mapped is not None and mapped.is_loopback))


def _is_local_peer(client: Any, test_mode: bool = False) -> bool:
    """The socket peer is loopback (incl. IPv4-mapped IPv6) or a Unix socket (no address). The TestClient
    sentinel ``testclient`` counts as local only in test mode."""
    if not client:
        return True
    host = str(client[0]) if isinstance(client, (tuple, list)) and client else str(client)
    if host == _TESTCLIENT_PEER:
        return test_mode
    return _is_loopback_address(host)


def _forwarded_for_is_local(headers: Mapping[str, list[str]]) -> bool:
    """False when any X-Forwarded-For entry is not a loopback address (a client on another machine behind
    a local reverse proxy such as Tailscale Serve). No header: True."""
    for value in headers.get("x-forwarded-for", []):
        for item in value.split(","):
            if item.strip() and not _is_loopback_address(item):
                return False
    return True


def _client_is_local(client: Any, headers: Mapping[str, list[str]], test_mode: bool = False) -> bool:
    return _is_local_peer(client, test_mode) and _forwarded_for_is_local(headers)


def _is_loopback_name(entry: HostEntry, test_mode: bool = False) -> bool:
    """``localhost``, a loopback IP literal (``127.x``, ``[::1]``) or, in test mode, the TestClient Host."""
    name = entry[0]
    return name == "localhost" or _is_loopback_address(name) or (test_mode and name == TEST_CLIENT_HOST)


# ── policy + decision (pure) ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GuardPolicy:
    """What the guard admits. Build with ``from_env``; the defaults are loopback-only."""

    hosts: frozenset[HostEntry]
    origins: frozenset[str]
    remote_writes: bool = False
    ignored: tuple[str, ...] = ()  # malformed config entries (logged once at start, never applied)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, extra_hosts: Iterable[str] = (),
                 extra_origins: Iterable[str] = ()) -> GuardPolicy:
        e = os.environ if env is None else env
        hosts: set[HostEntry] = set()
        origins: set[str] = set()
        ignored: list[str] = []
        host_sources = [("default", list(DEFAULT_ALLOWED_HOSTS)), ("extra_hosts", list(extra_hosts)),
                        (ENV_ALLOWED_HOSTS, _split_list(e.get(ENV_ALLOWED_HOSTS)))]
        for source, items in host_sources:
            for i, raw in enumerate(items, 1):
                entry = parse_host(raw)
                if entry is None:
                    ignored.append(f"{source} entry {i}")
                else:
                    hosts.add(entry)
        origin_sources = [("default", list(DEFAULT_ALLOWED_ORIGINS)), ("extra_origins", list(extra_origins)),
                          (ENV_ALLOWED_ORIGINS, _split_list(e.get(ENV_ALLOWED_ORIGINS)))]
        for source, items in origin_sources:
            for i, raw in enumerate(items, 1):
                origin = canonical_origin(raw)
                if origin is None:
                    ignored.append(f"{source} entry {i}")
                else:
                    origins.add(origin)
        remote = (e.get(ENV_REMOTE_WRITES) or "").strip() == "1"
        return cls(frozenset(hosts), frozenset(origins), remote, tuple(ignored))

    def host_allowed(self, entry: HostEntry) -> bool:
        host, port = entry
        return (host, None) in self.hosts or (port is not None and (host, port) in self.hosts)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    status: int = 200
    reason: str = ""   # slug: bad_host · bad_forwarded_host · null_origin · origin_not_allowed · cross_site · remote_write
    message: str = ""
    hint: str = ""


_ALLOW = Decision(True)


def _deny_host(reason: str, message: str) -> Decision:
    return Decision(False, 400, reason, message,
                    f"this service answers on 127.0.0.1 / localhost only; list other names in {ENV_ALLOWED_HOSTS}")


def _deny_origin(reason: str, message: str) -> Decision:
    return Decision(False, 403, reason, message,
                    "state-changing requests are accepted only from the SuryaDhana terminal's own origin")


def _same_origin(origin: str, host: HostEntry) -> bool:
    scheme, _, rest = origin.partition("://")
    o_entry = parse_host(rest)
    if o_entry is None:
        return False
    o_host, o_port = o_entry
    h_host, h_port = host
    default = _DEFAULT_PORTS.get(scheme)
    return o_host == h_host and (o_port or default) == (h_port or default)


def evaluate(policy: GuardPolicy, *, scope_type: str, method: str, headers: Mapping[str, list[str]],
             client: Any = None, test_mode: bool = False) -> Decision:
    """Pure decision for one request. ``headers`` maps lower-case names to every value received.
    ``test_mode`` (pytest running a test) admits Starlette TestClient's ``testserver`` Host and peer."""
    hosts = headers.get("host", [])
    host = parse_host(hosts[0]) if len(hosts) == 1 else None
    if host is None or not (policy.host_allowed(host) or (test_mode and host[0] == TEST_CLIENT_HOST)):
        return _deny_host("bad_host", "Host header not allowed")
    forwarded: list[HostEntry] = []
    for value in headers.get("x-forwarded-host", []):
        for item in value.split(","):
            fwd = parse_host(item)
            if fwd is None or not policy.host_allowed(fwd):
                return _deny_host("bad_forwarded_host", "X-Forwarded-Host not allowed")
            forwarded.append(fwd)
    if scope_type == "http" and method.upper() in SAFE_METHODS:
        return _ALLOW
    origins = headers.get("origin", [])
    if len(origins) > 1:
        return _deny_origin("origin_not_allowed", "more than one Origin header")
    if origins:
        raw = origins[0].strip()
        if raw.lower() == "null":
            return _deny_origin("null_origin", "requests from an opaque (null) origin are refused")
        origin = canonical_origin(raw)
        if origin is None or not (origin in policy.origins
                                  or any(_same_origin(origin, target) for target in (host, *forwarded))):
            return _deny_origin("origin_not_allowed", "cross-origin request refused")
    if any(v.strip().lower() == "cross-site" for v in headers.get("sec-fetch-site", [])):
        return _deny_origin("cross_site", "cross-site request refused")
    if scope_type == "http" and not policy.remote_writes and not (
            _client_is_local(client, headers, test_mode)
            and all(_is_loopback_name(entry, test_mode) for entry in (host, *forwarded))):
        return Decision(False, 403, "remote_write", "clients on other machines are read-only",
                        f"set {ENV_REMOTE_WRITES}=1 to allow writes from the network (not recommended)")
    return _ALLOW


# ── logging ──────────────────────────────────────────────────────────────────────────────────────

class _JsonLineFormatter(logging.Formatter):
    """One JSON object per line (same shape as static_ui.py / shared/logging.py)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "component": "http_guard",
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, default=str, ensure_ascii=False)


log = logging.getLogger("suryadhana.http_guard")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(_JsonLineFormatter())
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class _RejectLog:
    """Rate limiter: at most one line per (reason, path) per ``window_s``; bounded key count."""

    def __init__(self, window_s: float = 60.0, max_keys: int = 256) -> None:
        self.window_s = window_s
        self.max_keys = max_keys
        self._seen: dict[tuple[str, str], list[float | int]] = {}  # key -> [last_logged_at, suppressed]
        self._lock = threading.Lock()

    def admit(self, reason: str, path: str, now: float | None = None) -> int | None:
        """None = suppress; otherwise the number of identical rejections suppressed since the last line."""
        t = time.monotonic() if now is None else now
        with self._lock:
            if len(self._seen) >= self.max_keys and (reason, path) not in self._seen:
                cutoff = t - self.window_s
                self._seen = {k: v for k, v in self._seen.items() if v[0] >= cutoff}
                if len(self._seen) >= self.max_keys:
                    path = "*"  # many distinct paths (a scan): one shared bucket per reason
            entry = self._seen.get((reason, path))
            if entry is not None and t - float(entry[0]) < self.window_s:
                entry[1] = int(entry[1]) + 1
                return None
            suppressed = int(entry[1]) if entry is not None else 0
            self._seen[(reason, path)] = [t, 0]
            return suppressed


def _safe_path(path: Any) -> str:
    s = "".join(ch for ch in str(path or "")[:200] if 0x20 <= ord(ch) < 0x7F)
    return s or "/"


# ── the middleware ───────────────────────────────────────────────────────────────────────────────

def _headers(scope: Scope) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, value in scope.get("headers") or ():
        try:
            key = bytes(name).decode("latin-1").lower()
            out.setdefault(key, []).append(bytes(value).decode("latin-1"))
        except (TypeError, ValueError):
            continue
    return out


def in_test_mode(environ: Mapping[str, str] | None = None, modules: Mapping[str, Any] | None = None) -> bool:
    """True while pytest runs a test in this process: it sets PYTEST_CURRENT_TEST for each one, and the
    ``pytest`` module is loaded. A uvicorn- or launchd-started service never imports pytest, so a process
    that only inherited the variable from a test (subprocess with env=None) stays in production mode."""
    env = os.environ if environ is None else environ
    return bool(env.get(ENV_TEST_MARKER)) and "pytest" in (sys.modules if modules is None else modules)


class HostOriginGuard:
    """Pure ASGI middleware (see the module docstring). ``service`` names the service in log lines.

    ``test_mode``: None (default) = decided per request by ``in_test_mode()``; True/False forces it
    (tests that check the production behaviour pass False)."""

    def __init__(self, app: ASGIApp, *, service: str = "service", policy: GuardPolicy | None = None,
                 env: Mapping[str, str] | None = None, test_mode: bool | None = None) -> None:
        self.app = app
        self.service = service
        self.policy = policy if policy is not None else GuardPolicy.from_env(env)
        self.test_mode = test_mode
        self._rejects = _RejectLog()
        log.info("http_guard.installed", extra={"fields": {
            "service": service,
            "extra_hosts": len(self.policy.hosts) - len(DEFAULT_ALLOWED_HOSTS),
            "extra_origins": len(self.policy.origins) - len(DEFAULT_ALLOWED_ORIGINS),
            "remote_writes": self.policy.remote_writes,
        }})
        for item in self.policy.ignored:
            log.warning("http_guard.config_ignored", extra={"fields": {"service": service, "entry": item}})
        if test_mode is True or (test_mode is None and in_test_mode()):
            log.warning("http_guard.test_mode_active", extra={"fields": {
                "service": service, "note": "Host 'testserver' and the TestClient peer are accepted (pytest only)"}})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or ("GET" if kind == "websocket" else ""))
        headers = _headers(scope)
        test_mode = in_test_mode() if self.test_mode is None else self.test_mode
        decision = evaluate(self.policy, scope_type=kind, method=method, headers=headers,
                            client=scope.get("client"), test_mode=test_mode)
        if decision.allowed:
            await self.app(scope, receive, send)
            return
        self._note(decision, scope, kind, method, headers, test_mode)
        if kind == "http":
            await self._reject_http(send, decision)
        else:
            await self._reject_websocket(receive, send)

    def _note(self, decision: Decision, scope: Scope, kind: str, method: str,
              headers: Mapping[str, list[str]], test_mode: bool) -> None:
        path = _safe_path(scope.get("path"))
        suppressed = self._rejects.admit(decision.reason, path)
        if suppressed is None:
            return
        log.warning("http_guard.rejected", extra={"fields": {
            "service": self.service, "reason": decision.reason, "status": decision.status,
            "type": kind, "method": method[:16], "path": path,
            "peer": "loopback" if _client_is_local(scope.get("client"), headers, test_mode) else "remote",
            "suppressed_since_last": suppressed,
        }})

    @staticmethod
    async def _reject_http(send: Send, decision: Decision) -> None:
        code = "invalid" if decision.status == 400 else "unauthorized"
        error = {"code": code, "message": decision.message, **({"hint": decision.hint} if decision.hint else {})}
        body = json.dumps({"detail": decision.message, "error": error}).encode()
        await send({"type": "http.response.start", "status": decision.status, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
        ]})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _reject_websocket(receive: Receive, send: Send) -> None:
        message = await receive()
        if message.get("type") == "websocket.connect":
            await send({"type": "websocket.close", "code": 1008, "reason": "origin or host not allowed"})


def install_http_guard(app: Any, *, service: str, env: Mapping[str, str] | None = None,
                       test_mode: bool | None = None) -> None:
    """Add the guard to a Starlette/FastAPI ``app``. Call it AFTER every other ``add_middleware``: the
    middleware added last is the outermost, and the guard must see each request first."""
    app.add_middleware(HostOriginGuard, service=service, env=env, test_mode=test_mode)
