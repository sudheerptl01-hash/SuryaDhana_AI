"""Gzip for ui-api's JSON API responses (desktop review C2-performance-08).

The old :3000 Next server gzipped /api JSON; since the terminal is served by ui-api on :8010 it went out
uncompressed (GET /api/stocks/list?limit=1500, fetched by every window at boot: 934,658 B instead of about
110 kB). On loopback that costs little, but the phone/iPad path (Tailscale Serve, docs/RUNBOOK_RESTORE.md
section 7) pays it per window open and per poll.

``ApiGzipMiddleware`` compresses a response only when ALL of these hold:
- the request is HTTP (never a WebSocket) and its path starts with ``/api/`` (the static UI under ``/`` has
  its own precompressed .gz files, see static_ui.py, and is never touched);
- the client accepts gzip (``Accept-Encoding``, honouring ``q=0`` and ``*``);
- the response is JSON (``application/json`` or ``+json``), has no ``Content-Encoding`` and no ``ETag``,
  and is not a 1xx/204/304;
- the body arrives in ONE message (``more_body`` false) and is at least ``minimum_size`` (4 KB) long.

Anything streamed (the first body message has ``more_body``: SSE ``text/event-stream``, NDJSON, chunked
exports) is passed through untouched, message by message, so nothing is ever buffered. Eligible responses
get ``Vary: Accept-Encoding`` whether or not this client accepted gzip. Bodies of 256 KB or more are
compressed in a worker thread, so a large payload never stalls the event loop.

Install it with ``app.add_middleware`` BEFORE ``install_http_guard`` (the guard must stay outermost).
"""
from __future__ import annotations

import gzip
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import anyio
from starlette.datastructures import Headers, MutableHeaders

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

MINIMUM_SIZE = 4096
COMPRESS_LEVEL = 5
THREAD_THRESHOLD = 256 * 1024
PATH_PREFIXES: tuple[str, ...] = ("/api/",)


def accepts_gzip(accept_encoding: str) -> bool:
    """RFC 9110 Accept-Encoding: gzip (or x-gzip) with q > 0, or ``*`` with q > 0 when gzip is not listed."""
    gzip_q: float | None = None
    star_q: float | None = None
    for item in accept_encoding.split(","):
        token, _, params = item.strip().partition(";")
        name = token.strip().lower()
        if not name:
            continue
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
        if name in ("gzip", "x-gzip"):
            gzip_q = q if gzip_q is None else max(gzip_q, q)
        elif name == "*":
            star_q = q
    if gzip_q is not None:
        return gzip_q > 0
    return star_q is not None and star_q > 0


def _is_json(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


class ApiGzipMiddleware:
    """Pure ASGI; see the module docstring."""

    def __init__(self, app: ASGIApp, *, minimum_size: int = MINIMUM_SIZE, compresslevel: int = COMPRESS_LEVEL,
                 path_prefixes: tuple[str, ...] = PATH_PREFIXES, thread_threshold: int = THREAD_THRESHOLD) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
        self.path_prefixes = path_prefixes
        self.thread_threshold = thread_threshold

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not str(scope.get("path") or "").startswith(self.path_prefixes):
            await self.app(scope, receive, send)
            return
        accept = accepts_gzip(Headers(scope=scope).get("accept-encoding", ""))
        await _Responder(self, accept, send).run(scope, receive)


class _Responder:
    def __init__(self, mw: ApiGzipMiddleware, accept: bool, send: Send) -> None:
        self.mw = mw
        self.accept = accept
        self.send = send
        self.start: Message | None = None     # held http.response.start (eligible responses only)
        self.passthrough = False

    async def run(self, scope: Scope, receive: Receive) -> None:
        await self.mw.app(scope, receive, self.on_send)

    async def on_send(self, message: Message) -> None:
        kind = message.get("type")
        if self.passthrough:
            await self.send(message)
            return
        if kind == "http.response.start":
            headers = Headers(raw=message.get("headers") or [])
            status = int(message.get("status") or 200)
            eligible = (_is_json(headers.get("content-type", "")) and "content-encoding" not in headers
                        and "etag" not in headers and status >= 200 and status not in (204, 304))
            if not eligible:
                self.passthrough = True
                await self.send(message)
                return
            self.start = message
            return
        if self.start is None:                                    # nothing held (defensive)
            self.passthrough = True
            await self.send(message)
            return
        start, self.start = self.start, None
        self.passthrough = True                                   # every later message goes straight through
        if kind != "http.response.body" or message.get("more_body", False):
            await self.send(start)                                # a streamed body: never buffered
            await self.send(message)
            return
        body: bytes = message.get("body", b"")
        if len(body) < self.mw.minimum_size:
            await self.send(start)
            await self.send(message)
            return
        start["headers"] = list(start.get("headers") or [])     # MutableHeaders edits the raw list in place
        headers = MutableHeaders(raw=start["headers"])
        headers.add_vary_header("Accept-Encoding")
        if not self.accept:
            await self.send(start)
            await self.send(message)
            return
        if len(body) >= self.mw.thread_threshold:
            compressed = await anyio.to_thread.run_sync(self._compress, body)
        else:
            compressed = self._compress(body)
        headers["Content-Encoding"] = "gzip"
        headers["Content-Length"] = str(len(compressed))
        await self.send(start)
        await self.send({**message, "body": compressed})

    def _compress(self, body: bytes) -> bytes:
        return gzip.compress(body, compresslevel=self.mw.compresslevel, mtime=0)
