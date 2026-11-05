"""Scratch "same-origin" server for the parity/streams baseline: a static UI export + a transparent /api proxy.

It reproduces the target topology of reports/desktop_app/PLAN.md §3 (one origin serving the static UI next to
/api, SSE and the WebSocket) *without* touching the live ui-api: the static files come from a scratch export
and everything the UI calls is forwarded to the live backend (default http://127.0.0.1:8010).

* ``/api/*`` (any method): streamed pass-through (SSE/NDJSON flush chunk by chunk, upstream closed when the
  client goes away); hop-by-hop headers dropped, ``content-encoding`` kept with the raw bytes. Like Next's
  ``/api`` rewrite, ``Host`` becomes the backend's and the page's own ``Host`` is sent as ``X-Forwarded-Host``
  (replacing any the client sent), so the backend's Host/Origin guard (shared/http_guard.py) judges a page's
  request exactly as it judges one through Next: a same-origin write is admitted (its ``Origin`` equals the
  forwarded host), a cross-site one is still refused.
* ``/api/*`` WebSocket: bidirectional relay with close propagation (``/api/monitor/ws/monitor`` today).
* ``/health /ready /live /metrics /version``: forwarded too (the shell's poller and D1's /version live there).
* static: ``/`` and ``*.html`` are ``no-cache``; ``/_next/static/*`` is ``immutable``; a ``.gz`` sibling is
  served when the client accepts gzip (mirrors D1's precompressed release); unknown paths get ``404.html``.

Writes and the live stack (R-OPS-08). Because a same-origin write is forwarded exactly like Next forwards it, the
live guard ADMITS it: this server is NOT read-only by construction. So against the live ui-api (``--backend`` on
port 8010 of a loopback host, the default) every non-GET/HEAD/OPTIONS /api call is answered 403 here and never
forwarded, unless ``--allow-mutations`` is given; ``--block-mutations`` forces the same against any backend. A
non-live backend (a scratch ui-api on another port) gets writes relayed by default.

WebSockets and the live stack (R-OPS-09). Relaying the monitor socket to the live ui-api puts QA load on it (the 25 Oct
14:40 wedge happened with ~200 relayed connections), so against the live backend a page's WebSocket is accepted and
closed at once (1008, reason names the flag) unless ``--allow-live-ws``. QA browser contexts mock every WebSocket
anyway (probe.new_qa_context). ``/__qa/health`` reports both decisions.

``--prefs-db <file>`` (optional) serves ``/api/prefs`` *locally* instead of forwarding it: the real ui-api router
(services/ui-api/routers/prefs.py, loaded as a private module copy) runs on that scratch SQLite file, so an E2E can
exercise preference writes (PUT/DELETE/import) without ever touching the live store. Blocking keeps applying to
everything that is still forwarded; the local prefs routes accept writes (they only reach the scratch file). The
live ``data/ui_prefs.sqlite`` is refused as a target.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/desktop_qa/scratch_server.py --ui <export dir> [--port 8092] \
        [--block-mutations | --allow-mutations] [--allow-live-ws] [--prefs-db <scratch dir>/ui_prefs.sqlite]
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import itertools
import mimetypes
import re
import sys
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from types import ModuleType

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "content-length", "host"}
FORWARDED_ROOT_PATHS = ("/health", "/ready", "/live", "/metrics", "/version")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LIVE_UI_API_PORT = 8010
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}   # names compared, never bound
GRACEFUL_SHUTDOWN_S = 3   # seconds open streams get after SIGTERM before uvicorn closes them
REPO = Path(__file__).resolve().parents[2]
UI_API_DIR = REPO / "services" / "ui-api"
LIVE_PREFS_DB = REPO / "data" / "ui_prefs.sqlite"
_prefs_copies = itertools.count()


def _safe_file(root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` inside ``root`` (no traversal, no symlink escape); None if absent."""
    try:
        p = (root / rel.lstrip("/")).resolve()
    except (OSError, ValueError):
        return None
    if root not in p.parents and p != root:
        return None
    return p if p.is_file() else None


def is_live_backend(url: str) -> bool:
    """True for the live ui-api: http(s) on port 8010 of a loopback name (the default ``--backend``)."""
    try:
        u = httpx.URL(url)
        port = u.port or (443 if u.scheme == "https" else 80)
    except (httpx.InvalidURL, TypeError, ValueError):
        return True   # unparseable: treat as live (the safe side)
    host = u.host.strip("[]").lower()
    if not host:
        return True   # no host at all: not a backend this server could name, so the safe side again
    return host in LOOPBACK_HOSTS and port == LIVE_UI_API_PORT


def resolve_policy(backend: str, *, block_mutations: bool = False, allow_mutations: bool = False,
                   allow_live_ws: bool = False) -> tuple[bool, bool]:
    """CLI flags → (block_mutations, relay_ws). Writes are blocked against the live backend unless
    ``allow_mutations``; ``block_mutations`` blocks them against any backend. The WebSocket relay to the live backend
    is off unless ``allow_live_ws``."""
    if block_mutations and allow_mutations:
        raise ValueError("--block-mutations and --allow-mutations contradict each other")
    live = is_live_backend(backend)
    block = block_mutations or (live and not allow_mutations)
    return block, (not live) or allow_live_ws


def forward_headers(items: Iterable[tuple[str, str]], host: str | None) -> dict[str, str]:
    """Request headers for the backend, as Next's ``/api`` rewrite sends them: hop-by-hop headers and ``Host``
    dropped (the client sets the backend's), the page's ``Host`` in ``X-Forwarded-Host`` (any client-sent value
    is replaced, never appended), ``Origin`` and everything else unchanged."""
    out = {k: v for k, v in items if k.lower() not in HOP_BY_HOP and k.lower() != "x-forwarded-host"}
    if host:
        out["x-forwarded-host"] = host
    return out


def parse_inject(specs: list[str]) -> list[tuple[re.Pattern[str], int]]:
    """``['^/api/desk/status$=500']`` → [(regex, status)]; for the harness's negative control only."""
    out = []
    for spec in specs:
        rx, _, status = spec.rpartition("=")
        if not rx or not status.isdigit():
            raise ValueError(f"bad --inject {spec!r} (expected REGEX=STATUS)")
        out.append((re.compile(rx), int(status)))
    return out


def load_prefs_module(db: Path) -> ModuleType:
    """Load ui-api's prefs router as a private module copy whose store is ``db`` (a scratch SQLite file).

    The copy has its own store cache and its ``default_db_path`` is rebound, so neither ``PREFS_DB`` nor the
    live ``data/ui_prefs.sqlite`` is consulted. Refuses the live store as a target."""
    target = Path(db).expanduser().resolve()
    if target == LIVE_PREFS_DB.resolve():
        raise ValueError(f"--prefs-db must be a scratch file, not the live store {LIVE_PREFS_DB}")
    if target.is_dir():
        raise ValueError(f"--prefs-db {target} is a directory (expected a SQLite file path)")
    if str(UI_API_DIR) not in sys.path:
        sys.path.append(str(UI_API_DIR))  # prefs.py does `from errors import ...` (ui-api's error contract)
    name = f"_desktop_qa_prefs_{next(_prefs_copies)}"
    spec = importlib.util.spec_from_file_location(name, UI_API_DIR / "routers" / "prefs.py")
    if spec is None or spec.loader is None:  # pragma: no cover - the file is part of the repo
        raise RuntimeError("cannot load services/ui-api/routers/prefs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    vars(mod)["default_db_path"] = lambda: target  # get_store() resolves the path through this module global
    return mod


def create_app(ui_dir: Path, backend: str = "http://127.0.0.1:8010", *, client: httpx.AsyncClient | None = None,
               ws_backend: str | None = None, block_mutations: bool = False,
               inject: list[tuple[re.Pattern[str], int]] | None = None,
               prefs_db: Path | None = None, relay_ws: bool = True) -> FastAPI:
    """Build the scratch app. ``client`` is injectable (tests use an ``httpx.MockTransport``).

    The flags are taken as given (the CLI derives them with ``resolve_policy``, which blocks writes and the WebSocket
    relay against the live backend). ``inject`` answers matching /api paths with a fixed error status instead of
    forwarding them (fault injection, used to prove the parity/audit harness detects a regression). ``prefs_db``
    mounts ui-api's prefs router locally on that scratch SQLite file instead of forwarding ``/api/prefs`` (see the
    module doc). ``relay_ws=False`` accepts a page's WebSocket and closes it at once (1008) instead of relaying it."""
    root = ui_dir.resolve()
    backend = backend.rstrip("/")
    ws_base = ws_backend or backend.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    owns_client = client is None
    http = client or httpx.AsyncClient(base_url=backend, timeout=httpx.Timeout(60.0, read=None))
    prefs_mod = load_prefs_module(prefs_db) if prefs_db is not None else None

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if prefs_mod is not None:
                prefs_mod.close_all()  # checkpoint + close the scratch SQLite
            if owns_client:
                # close every pooled and streaming upstream connection, so a stopped QA server never keeps
                # sockets open on the backend (the live ui-api) after it is gone
                await http.aclose()

    app = FastAPI(title="desktop-qa scratch server", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)

    @app.get("/__qa/health")
    async def qa_health() -> dict[str, str]:
        prefs = f"local:{prefs_mod.default_db_path()}" if prefs_mod is not None else "forwarded"
        return {"status": "ok", "ui_dir": str(root), "backend": backend, "prefs": prefs,
                "mutations": "blocked" if block_mutations else "forwarded",
                "websockets": "relayed" if relay_ws else "closed"}

    if prefs_mod is not None:
        _mount_local_prefs(app, prefs_mod, inject or [])

    @app.websocket("/api/{path:path}")
    async def ws_proxy(ws: WebSocket, path: str) -> None:
        if not relay_ws:   # accepted then closed: no handshake error in the page's console, no socket on the backend
            await ws.accept()
            await ws.close(code=1008, reason="scratch server: no WebSocket relay to the live ui-api (--allow-live-ws)")
            return
        import websockets  # imported lazily: only needed when a socket is opened

        qs = ws.url.query
        target = f"{ws_base}/api/{path}" + (f"?{qs}" if qs else "")
        try:
            # close_timeout 2 s (default 10): a relay never waits long on a wedged backend's close handshake before
            # it drops the socket (25 Oct: stalled relays held sockets on the live ui-api)
            upstream = await websockets.connect(target, open_timeout=10, close_timeout=2, max_size=None)
        except Exception:  # noqa: BLE001 - any upstream connect failure is relayed to the page as a 1011 close
            await ws.close(code=1011)
            return
        await ws.accept()

        async def down() -> None:
            async for msg in upstream:
                if isinstance(msg, (bytes, bytearray)):
                    await ws.send_bytes(bytes(msg))
                else:
                    await ws.send_text(msg)

        async def up() -> None:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    return
                if m.get("text") is not None:
                    await upstream.send(m["text"])
                elif m.get("bytes") is not None:
                    await upstream.send(m["bytes"])

        tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            with contextlib.suppress(Exception):
                await upstream.close()
            with contextlib.suppress(Exception):
                await ws.close()

    async def forward(request: Request, path: str) -> Response:
        for rx, code in inject or ():
            if rx.search(path):
                return JSONResponse({"detail": "injected by desktop-qa scratch server"}, status_code=code)
        if block_mutations and request.method not in SAFE_METHODS:
            return JSONResponse({"detail": "blocked by desktop-qa scratch server (--block-mutations)"}, status_code=403)
        headers = forward_headers(request.headers.items(), request.headers.get("host"))
        req = http.build_request(request.method, path, params=request.query_params, headers=headers,
                                 content=await request.body())
        try:
            r = await http.send(req, stream=True)
        except httpx.HTTPError as exc:
            return JSONResponse({"detail": f"scratch proxy: backend unreachable ({type(exc).__name__})"}, status_code=502)

        async def body() -> AsyncIterator[bytes]:
            try:
                async for chunk in r.aiter_raw():
                    yield chunk
            finally:
                await r.aclose()

        out_headers = {k: v for k, v in r.headers.items() if k.lower() not in HOP_BY_HOP}
        return StreamingResponse(body(), status_code=r.status_code, headers=out_headers)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def api_proxy(request: Request, path: str) -> Response:
        return await forward(request, f"/api/{path}")

    def _root_forwarder(target: str):  # one async handler per forwarded root path
        async def handler(request: Request) -> Response:
            return await forward(request, target)
        return handler

    for rp in FORWARDED_ROOT_PATHS:
        app.add_api_route(rp, _root_forwarder(rp), methods=["GET", "HEAD"], include_in_schema=False)

    @app.get("/{path:path}")
    async def static(request: Request, path: str) -> Response:
        rel = path or "index.html"
        f = _safe_file(root, rel) or (_safe_file(root, f"{rel}.html") if "." not in rel.rsplit("/", 1)[-1] else None)
        if f is None:
            nf = _safe_file(root, "404.html")
            if nf is None:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(nf, status_code=404, headers={"Cache-Control": "no-cache"})
        headers = {"Cache-Control": "public, max-age=31536000, immutable" if rel.startswith("_next/static/")
                   else "no-cache"}
        media = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        gz = f.with_name(f.name + ".gz")
        if "gzip" in request.headers.get("accept-encoding", "") and gz.is_file():
            headers.update({"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
            return FileResponse(gz, media_type=media, headers=headers)
        return FileResponse(f, media_type=media, headers=headers)

    return app


def _mount_local_prefs(app: FastAPI, prefs_mod: ModuleType, inject: list[tuple[re.Pattern[str], int]]) -> None:
    """Serve /api/prefs from ``prefs_mod`` with ui-api's error envelope (registered before the /api proxy route,
    so it takes precedence). ``--inject`` rules still apply to these paths."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    errors = sys.modules["errors"]  # imported by load_prefs_module (services/ui-api/errors.py)

    async def injected(request: Request) -> None:
        for rx, code in inject:
            if rx.search(request.url.path):
                raise HTTPException(status_code=code, detail="injected by desktop-qa scratch server")

    @app.exception_handler(StarletteHTTPException)
    async def error_contract(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Same shape as ui-api main.py's handler: detail stays a string, error{code,message,hint} beside it.
        d = exc.detail
        if isinstance(d, dict) and "code" in d and "message" in d:
            block, message = errors.error_block(d["code"], str(d["message"]), d.get("hint")), str(d["message"])
        else:
            message = d if isinstance(d, str) else str(d)
            block = errors.error_block(errors.code_for_status(exc.status_code), message)
        return JSONResponse({"detail": message, "error": block}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    app.add_exception_handler(RequestValidationError, errors.validation_error_handler)
    app.include_router(prefs_mod.router, prefix="/api/prefs", dependencies=[Depends(injected)])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="static UI export + /api, SSE, WS forwarding (scratch, read-only use)")
    ap.add_argument("--ui", required=True, help="static export directory (contains index.html)")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"], help="loopback only")
    ap.add_argument("--backend", default="http://127.0.0.1:8010")
    ap.add_argument("--block-mutations", action="store_true",
                    help="answer every forwarded non-GET/HEAD/OPTIONS /api call 403, whatever the backend "
                         "(the default against the live :8010 backend)")
    ap.add_argument("--allow-mutations", action="store_true",
                    help="forward writes to the live :8010 backend too (its guard admits same-origin writes: they "
                         "change the live paper state)")
    ap.add_argument("--allow-live-ws", action="store_true",
                    help="relay page WebSockets to the live :8010 backend (off by default: QA load on the live ui-api)")
    ap.add_argument("--inject", action="append", default=[], metavar="REGEX=STATUS",
                    help="answer matching /api paths with STATUS (negative-control fault injection)")
    ap.add_argument("--prefs-db", type=Path, default=None, metavar="PATH",
                    help="serve /api/prefs locally from this scratch SQLite file (created on demand) instead of "
                         "forwarding it; the live data/ui_prefs.sqlite is refused")
    ap.add_argument("--allow-any-port", action="store_true", help="permit a port outside the QA range 8090-8099")
    ap.add_argument("--log-level", default="warning")
    args = ap.parse_args(argv)
    ui = Path(args.ui)
    if not (ui / "index.html").is_file():
        print(f"{ui} has no index.html (not a static export)", file=sys.stderr)
        return 2
    if not (8090 <= args.port <= 8099) and not args.allow_any_port:
        print("port must be in 8090-8099 (QA scratch range) unless --allow-any-port", file=sys.stderr)
        return 2
    import uvicorn

    try:
        inject = parse_inject(args.inject)
    except (ValueError, re.error) as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        block, relay_ws = resolve_policy(args.backend, block_mutations=args.block_mutations,
                                         allow_mutations=args.allow_mutations, allow_live_ws=args.allow_live_ws)
        app = create_app(ui, args.backend, block_mutations=block, inject=inject, prefs_db=args.prefs_db,
                         relay_ws=relay_ws)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"scratch_server: backend {args.backend}{' (the LIVE ui-api)' if is_live_backend(args.backend) else ''}: "
          f"writes {'blocked (403)' if block else 'FORWARDED'}, WebSockets {'relayed' if relay_ws else 'closed (1008)'}",
          file=sys.stderr)
    # A bounded graceful shutdown: relayed SSE streams and WebSockets never end on their own, and without a cap
    # uvicorn waits for them forever after SIGTERM while the process keeps its upstream connections to the
    # backend open (seen 25 Oct: stopped QA servers holding sockets on the live ui-api).
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level, ws="auto",
                timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
