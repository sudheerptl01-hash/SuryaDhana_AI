"""Observability contract for the three services (Terminal v2 PLAN 1.5; R-ARCH fix 5).

One call per service, above the Host/Origin guard line (the guard must stay the outermost middleware)::

    from shared.metrics import install_observability
    install_observability(app, service="ui-api")        # then install_http_guard(app, ...)

It installs

* ``GET /metrics`` — Prometheus text format: request count and latency histograms by route family
  (``sd_http_*``), in-flight requests, DuckDB lock wait (``sd_duckdb_lock_wait_seconds``, fed by
  ``DuckDBStore``), job durations (``sd_job_seconds``), cache events (``sd_cache_events_total``), the Breeze
  budget (``sd_breeze_budget_used``), upstream calls and circuit-breaker state (``sd_upstream_*``, fed by
  ``shared.http_client``) and feed lag (``sd_feed_lag_seconds``);
* a request-id middleware: an incoming ``X-Request-ID`` (sanitised) or a fresh id is bound as the structured
  logger's correlation id for the request and echoed back in the ``X-Request-ID`` response header;
* a JSON access log through the structured logger (``event="http.access"``) with ``/health``, ``/api/health``,
  ``/live``, ``/`` and ``/metrics`` excluded (the desktop shell polls the first four ≈ 26×/min); an excluded
  path is still logged when it crashes (status 500; a 503 "not ready" from /live during boot stays quiet).
  uvicorn's plain access log is silenced so every access
  line is JSON (keep it with ``SD_ACCESS_LOG=uvicorn``);
* the anyio worker-thread limit raised to ``SD_THREAD_LIMIT`` (default 64, up from FastAPI's 40) on the first
  request, so the per-call DuckDB cursors can actually run side by side.

Route labels use the matched route template (``/api/stocks/{symbol}/history``), never the raw path, so the
cardinality is the number of routes. Metric objects are created once per process; re-importing under pytest
reuses the registered collectors instead of raising.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from shared.logging import bind_correlation_id, configure_logging, get_logger, is_logging_configured, unbind_correlation_id

try:  # prometheus_client is pinned in requirements*.txt; the helpers degrade to no-ops without it
    from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Gauge, Histogram, generate_latest
    HAVE_PROMETHEUS = True
except ImportError:  # pragma: no cover
    HAVE_PROMETHEUS = False

EXCLUDED_ACCESS_PATHS: frozenset[str] = frozenset({"/health", "/api/health", "/live", "/", "/metrics"})
DEFAULT_THREAD_LIMIT = 64
_REQUEST_ID_RE = re.compile(r"[^A-Za-z0-9._\-]")
_REQUEST_ID_MAX = 64
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

_SERVICE: dict[str, str] = {"name": "unknown"}


def service_name() -> str:
    return _SERVICE["name"]


# ── metric objects (idempotent per process) ────────────────────────────────────────────────────────────────────
def _metric(cls: Any, name: str, doc: str, labels: Iterable[str], **kw: Any) -> Any:
    if not HAVE_PROMETHEUS:
        return _NoopMetric()
    existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
    if existing is not None:
        return existing
    return cls(name, doc, list(labels), **kw)


class _NoopMetric:
    """Stand-in when prometheus_client is absent: every call is a no-op with the same surface."""

    def labels(self, *a: Any, **k: Any) -> _NoopMetric:
        return self

    def inc(self, *a: Any, **k: Any) -> None: ...
    def dec(self, *a: Any, **k: Any) -> None: ...
    def set(self, *a: Any, **k: Any) -> None: ...
    def observe(self, *a: Any, **k: Any) -> None: ...


HTTP_REQUESTS = _metric(Counter, "sd_http_requests_total", "HTTP requests by service, method, route and status class",
                        ["service", "method", "route", "status"])
HTTP_LATENCY = _metric(Histogram, "sd_http_request_seconds", "HTTP request latency by service, method and route",
                       ["service", "method", "route"], buckets=_LATENCY_BUCKETS)
HTTP_INFLIGHT = _metric(Gauge, "sd_http_inflight", "HTTP requests in flight", ["service"])
DUCKDB_LOCK_WAIT = _metric(Histogram, "sd_duckdb_lock_wait_seconds", "Seconds waited for the DuckDB RW lock",
                           ["service", "mode"], buckets=(0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0))
JOB_DURATION = _metric(Histogram, "sd_job_seconds", "Job durations by service, job and status", ["service", "job", "status"],
                       buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600))
CACHE_EVENTS = _metric(Counter, "sd_cache_events_total", "Cache events (hit / miss / stale / refresh / error)",
                       ["service", "cache", "event"])
BREEZE_BUDGET_USED = _metric(Gauge, "sd_breeze_budget_used", "Breeze calls used in the window (minute / day)", ["window"])
UPSTREAM_REQUESTS = _metric(Counter, "sd_upstream_requests_total", "Upstream HTTP calls by upstream, route and outcome",
                            ["service", "upstream", "route", "outcome"])
BREAKER_OPEN = _metric(Gauge, "sd_upstream_breaker_open", "1 while the upstream circuit breaker is open", ["service", "upstream"])
FEED_LAG = _metric(Gauge, "sd_feed_lag_seconds", "Age of the newest stored tick / chain snapshot", ["service", "feed"])


# ── helpers other modules call ──────────────────────────────────────────────────────────────────────────────────
def observe_duckdb_lock_wait(mode: str, seconds: float) -> None:
    DUCKDB_LOCK_WAIT.labels(service_name(), mode).observe(seconds)


def observe_job(job: str, seconds: float, status: str = "ok") -> None:
    JOB_DURATION.labels(service_name(), job, status).observe(seconds)


def count_cache_event(cache: str, event: str) -> None:
    CACHE_EVENTS.labels(service_name(), cache, event).inc()


def set_breeze_budget(window: str, used: float) -> None:
    BREEZE_BUDGET_USED.labels(window).set(used)


def count_upstream(upstream: str, route: str, outcome: str) -> None:
    UPSTREAM_REQUESTS.labels(service_name(), upstream, route, outcome).inc()


def set_breaker_open(upstream: str, is_open: bool) -> None:
    BREAKER_OPEN.labels(service_name(), upstream).set(1 if is_open else 0)


def set_feed_lag(feed: str, seconds: float) -> None:
    FEED_LAG.labels(service_name(), feed).set(seconds)


def render_metrics() -> tuple[bytes, str]:
    """(body, content-type) for ``GET /metrics``."""
    if not HAVE_PROMETHEUS:
        return b"# prometheus_client not installed\n", "text/plain; version=0.0.4; charset=utf-8"
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def route_family(path: str) -> str:
    """Fallback label for an unmatched path (static UI, 404s): the first segment plus ``/*``. ``/_next/static/x.js``
    → ``/_next/*``; ``/api/stocks/TCS`` → ``/api/*`` (matched routes use their template instead)."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "/"
    return f"/{parts[0]}" + ("/*" if len(parts) > 1 else "")


def sanitize_request_id(raw: str | None) -> str:
    """An incoming X-Request-ID kept only when it is a plain token (≤ 64 of [A-Za-z0-9._-]); else a fresh id."""
    if raw and len(raw) <= _REQUEST_ID_MAX and not _REQUEST_ID_RE.search(raw):
        return raw
    return uuid.uuid4().hex


def _status_class(status: int) -> str:
    return f"{status // 100}xx" if 100 <= status < 600 else "0xx"


def raise_thread_limit(total: int) -> int | None:
    """Raise anyio's default worker-thread limiter (sync endpoints run there). Must run inside the event loop."""
    try:
        import anyio
        limiter = anyio.to_thread.current_default_thread_limiter()
    except Exception:  # noqa: BLE001 — outside a loop, or anyio missing: nothing to raise
        return None
    limiter.total_tokens = max(limiter.total_tokens, total)
    return int(limiter.total_tokens)


class _DropAll(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


def silence_uvicorn_access_log() -> None:
    """The JSON access line replaces uvicorn's plain one (R-ARCH §2.4: 19,992 of 20,000 lines were plain access
    lines, 26/min of them health polls). Disabled flag + a drop-all filter, so uvicorn's own dictConfig (which runs
    before the app module is imported) cannot re-enable it."""
    lg = logging.getLogger("uvicorn.access")
    lg.disabled = True
    if not any(isinstance(f, _DropAll) for f in lg.filters):
        lg.addFilter(_DropAll())


class ObservabilityMiddleware:
    """Pure-ASGI: request id + correlation id, Prometheus request metrics, JSON access log, thread-limit raise."""

    def __init__(self, app: Any, *, service: str, exclude: Iterable[str] = EXCLUDED_ACCESS_PATHS,
                 thread_limit: int | None = DEFAULT_THREAD_LIMIT, clock: Callable[[], float] = time.perf_counter,
                 access_log: bool = True) -> None:
        self.app = app
        self.service = service
        self.exclude = frozenset(exclude)
        self.thread_limit = thread_limit
        self.clock = clock
        self.access_log = access_log
        self._limiter_logged = False
        self._log = get_logger("access")

    def _ensure_thread_limit(self) -> None:
        """Cheap per-request check (one RunVar lookup): the limiter belongs to the event loop, so raising it once
        per process is only right when the loop never changes — true under uvicorn, not under a test portal."""
        if not self.thread_limit:
            return
        got = raise_thread_limit(self.thread_limit)
        if got is not None and not self._limiter_logged:
            self._limiter_logged = True
            self._log.info("thread_limit", service=self.service, total_tokens=got)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        self._ensure_thread_limit()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        rid = sanitize_request_id(headers.get("x-request-id"))
        token = bind_correlation_id(rid)
        if scope["type"] == "websocket":
            try:
                await self.app(scope, receive, send)
            finally:
                unbind_correlation_id(token)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        status = {"code": 0, "bytes": 0}
        t0 = self.clock()
        HTTP_INFLIGHT.labels(self.service).inc()

        async def send_wrapped(message: Any) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message.get("status", 0))
                raw = list(message.get("headers") or [])
                raw.append((b"x-request-id", rid.encode("latin-1")))
                message = {**message, "headers": raw}
            elif message["type"] == "http.response.body":
                status["bytes"] += len(message.get("body") or b"")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapped)
        except BaseException:
            if status["code"] == 0:
                status["code"] = 500
            raise
        finally:
            elapsed = self.clock() - t0
            HTTP_INFLIGHT.labels(self.service).dec()
            route = scope.get("route")
            label = getattr(route, "path", None) or route_family(path)
            code = status["code"] or 500
            HTTP_REQUESTS.labels(self.service, method, label, _status_class(code)).inc()
            HTTP_LATENCY.labels(self.service, method, label).observe(elapsed)
            if self.access_log and (path not in self.exclude or code == 500):
                client = scope.get("client") or (None, None)
                query = scope.get("query_string", b"").decode("latin-1", "replace")[:200]
                self._log.info("http.access", method=method, path=path, route=label, status=code,
                               ms=round(elapsed * 1000, 1), bytes=status["bytes"], client=client[0],
                               query=query or None, ua=(headers.get("user-agent") or "")[:80] or None)
            unbind_correlation_id(token)


def install_observability(app: Any, *, service: str, thread_limit: int | None = None, metrics_path: str = "/metrics",
                          access_log: bool | None = None, env: dict[str, str] | None = None) -> None:
    """Wire /metrics, the request-id middleware and the JSON access log into a FastAPI app.

    Call it BEFORE ``install_http_guard`` (the guard must stay outermost). ``thread_limit`` defaults to
    ``SD_THREAD_LIMIT`` (64). ``SD_ACCESS_LOG=uvicorn`` keeps uvicorn's plain access log and skips the JSON one.
    """
    environ = os.environ if env is None else env
    _SERVICE["name"] = service
    if not is_logging_configured():
        configure_logging(service, environ.get("LOG_LEVEL", "INFO"))
    if thread_limit is None:
        try:
            thread_limit = int(environ.get("SD_THREAD_LIMIT", str(DEFAULT_THREAD_LIMIT)))
        except ValueError:
            thread_limit = DEFAULT_THREAD_LIMIT
    keep_uvicorn = environ.get("SD_ACCESS_LOG", "").strip().lower() == "uvicorn"
    if access_log is None:
        access_log = not keep_uvicorn
    if access_log:
        silence_uvicorn_access_log()

    from fastapi import Response

    async def metrics() -> Response:
        body, ctype = render_metrics()
        return Response(content=body, media_type=ctype)

    app.add_api_route(metrics_path, metrics, methods=["GET"], include_in_schema=False, name="metrics")
    app.add_middleware(ObservabilityMiddleware, service=service, thread_limit=thread_limit, access_log=access_log)
