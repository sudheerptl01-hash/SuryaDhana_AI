"""Static terminal UI served by ui-api (desktop program Layer 1: Node out of production).

`scripts/build_ui.sh` builds the Next.js terminal as a static export into atomic releases
(`ui/dist/releases/<id>/`, with `ui/dist/current` a symlink to the live one). This module serves that
release from ui-api on the same origin as `/api`, SSE and the monitor WebSocket.

How it attaches: `mount_static_ui(app)` installs the UI as the router's *not-found fallback*
(`app.router.default`), not as a route or a `Mount("/")`. A request reaches it only when NO route
matches, not even partially. That gives every guarantee by construction, whatever the call order:

* `/api/*`, `/health`, `/docs`, `/openapi.json`, `/redoc`, `/version`, `/ready`, `/live`, `/metrics` and
  every route added later are never shadowed. A method mismatch on an API route still returns 405, and
  `redirect_slashes` still works. A `Mount("/")` would full-match first and break all of these.
* Unknown paths under those reserved roots, non-GET/HEAD requests and WebSocket scopes go to the
  ORIGINAL fallback, so they keep today's behaviour: the JSON error-envelope 404 from main.py's
  `StarletteHTTPException` handler, or a WebSocket close.
* No routes are added, so the OpenAPI schema is unchanged.

Serving rules:

=======================  ===========================================  ================================
path                     file                                         Cache-Control
=======================  ===========================================  ================================
``/`` (any query)        index.html                                   no-cache (revalidate: ETag/304)
``/_next/static/**``     content-hashed chunks                        public, max-age=31536000, immutable
``/build-info.json``     the release's build identity                 no-store
*.html, *.txt, *.json    pages, RSC payloads, data                    no-cache
anything else            icons, fonts, ...                            public, max-age=300
=======================  ===========================================  ================================

* A precompressed ``<file>.gz`` (written by build_ui.sh) is served when ``Accept-Encoding`` allows gzip
  (q-values honoured, ``gzip;q=0`` refuses it), with the ORIGINAL file's Content-Type,
  ``Content-Encoding: gzip`` and the .gz file's own Content-Length and ETag. Compressible types always
  carry ``Vary: Accept-Encoding``.
* Strong ETag + Last-Modified on every file; ``If-None-Match`` (weak comparison, ``*``) and then
  ``If-Modified-Since`` answer 304. HEAD sends the GET headers without a body.
* Path safety: NUL, backslash, ``.``/``..`` segments and dotfiles are refused, and the final
  ``realpath`` must stay inside the release root, which also defeats symlink escapes and encoded
  ``%2e%2e%2f`` (ASGI paths arrive percent-decoded).
* ``dist_dir`` (normally the ``current`` symlink) is resolved on every request, so a release swap or
  rollback is live on the next request without a restart. A missing or broken build makes ``/`` (and
  any other HTML navigation) a clear 503 page that says how to run ``scripts/build_ui.sh`` and refreshes
  itself. The API keeps working.
* Security headers (desktop review C2-security-09): every static response carries
  ``X-Content-Type-Options: nosniff`` and ``Referrer-Policy: same-origin``; HTML (pages, the export's
  404.html, the missing-build 503 page) also carries ``Content-Security-Policy: frame-ancestors 'none';
  object-src 'none'; base-uri 'self'`` and ``X-Frame-Options: DENY``. The CSP deliberately leaves
  script/style/connect/frame/img sources open: the export's bootstrap scripts and the terminal's styles
  are inline and the news chart embeds TradingView's iframe. 304s carry only the caching headers, as
  before (a browser keeps the stored response's other headers).
* Event loop: path resolution and file reads run in worker threads under a DEDICATED limiter. ui-api
  has many sync routes (DuckDB) that can fill AnyIO's default 40-thread limiter, and asset loads must
  not queue behind them. Files are immutable per release, so bodies up to 4 MB are kept in a bounded LRU
  (64 MB) keyed by (path, inode, size, mtime). Larger files stream in 256 KB chunks.

Also here: `version_router`, which adds ``GET /version`` (service, api_version, ui_build = build-info or
null), ``GET /ready`` and ``GET /live``. main.py had only ``/health``.

Logging: JSON lines on stdout (the ui-api log), one event per state change (mounted, release changed,
build missing/restored) plus rate-limited warnings for refused paths. Requests are not logged here
(uvicorn's access log covers that). No secrets pass through this module.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal

import anyio
from anyio import CapacityLimiter
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.responses import Response, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

__all__ = [
    "DEFAULT_DIST_DIR",
    "StaticUI",
    "accepts_gzip",
    "cache_control_for",
    "mount_static_ui",
    "read_build_info",
    "resolve_dist_dir",
    "version_router",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIST_DIR = REPO_ROOT / "ui" / "dist" / "current"
ENV_DIST_DIR = "UI_DIST_DIR"

# Paths the UI must never answer for; a request under one of these that reached the fallback (no
# route matched) gets the ORIGINAL not-found behaviour (the JSON envelope 404).
RESERVED_ROOTS: tuple[str, ...] = (
    "/api", "/health", "/ready", "/live", "/metrics", "/version", "/docs", "/openapi.json", "/redoc",
)

CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CACHE_REVALIDATE = "no-cache"
CACHE_NO_STORE = "no-store"
CACHE_SHORT = "public, max-age=300"

COMPRESSIBLE_EXT = frozenset({
    ".html", ".js", ".mjs", ".css", ".txt", ".json", ".svg", ".xml", ".map", ".webmanifest", ".ttf", ".otf", ".csv",
})
_REVALIDATE_EXT = frozenset({".html", ".txt", ".json", ".webmanifest"})

# Explicit types for what a Next export contains; mimetypes' answer can vary with the host's
# mime.types files. `.txt` MUST be text/plain: Next's client accepts RSC payloads of a static export
# only as text/plain.
_MEDIA_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".xml": "application/xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".wasm": "application/wasm",
    ".pdf": "application/pdf",
}

# Security headers (module docstring). Applied to static responses only; API responses are untouched.
CSP_HTML = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
_STATIC_SECURITY_HEADERS: dict[str, str] = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
}
_HTML_SECURITY_HEADERS: dict[str, str] = {
    **_STATIC_SECURITY_HEADERS,
    "content-security-policy": CSP_HTML,
    "x-frame-options": "DENY",
}

_MAX_CACHED_FILE = 4 * 1024 * 1024
_MAX_CACHE_BYTES = 64 * 1024 * 1024
_STREAM_CHUNK = 256 * 1024
_LIMITER_TOKENS = 16


# ── logging ─────────────────────────────────────────────────────────────────────────────────────

class _JsonLineFormatter(logging.Formatter):
    """One JSON object per line, in the same shape as shared/logging.py (ts, level, service, event, ...)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": "ui-api",
            "component": "static_ui",
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, default=str, ensure_ascii=False)


log = logging.getLogger("suryadhana.ui_api.static_ui")
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(_JsonLineFormatter())
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


def _event(level: int, event: str, **fields: Any) -> None:
    log.log(level, event, extra={"fields": fields})


# ── pure helpers (unit-tested) ──────────────────────────────────────────────────────────────────

def resolve_dist_dir(dist_dir: str | os.PathLike[str] | None = None) -> Path:
    """The configured dist dir (argument > $UI_DIST_DIR > <repo>/ui/dist/current). Not resolved:
    a symlink stays a symlink so it is followed afresh on every request."""
    raw = dist_dir if dist_dir is not None else os.environ.get(ENV_DIST_DIR) or DEFAULT_DIST_DIR
    return Path(raw).expanduser().absolute()


def accepts_gzip(accept_encoding: str | None) -> bool:
    """True if an Accept-Encoding header admits gzip (RFC 9110 §12.5.3). An explicit gzip/x-gzip
    q-value wins, then `*`. No header, `identity` only, `gzip;q=0` or a malformed q all mean no."""
    if not accept_encoding:
        return False
    gzip_q: float | None = None
    star_q: float | None = None
    for part in accept_encoding.split(","):
        token, _, params = part.strip().partition(";")
        token = token.strip().lower()
        if not token:
            continue
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
                if not 0.0 <= q <= 1.0:
                    q = 0.0
        if token in ("gzip", "x-gzip"):
            gzip_q = q if gzip_q is None else max(gzip_q, q)
        elif token == "*":
            star_q = q
    if gzip_q is not None:
        return gzip_q > 0.0
    return star_q is not None and star_q > 0.0


def cache_control_for(rel_path: str) -> str:
    """Cache-Control for a release-relative POSIX path (see the module docstring table)."""
    if rel_path.startswith("_next/static/"):
        return CACHE_IMMUTABLE
    if rel_path == "build-info.json":
        return CACHE_NO_STORE
    if os.path.splitext(rel_path)[1].lower() in _REVALIDATE_EXT:
        return CACHE_REVALIDATE
    return CACHE_SHORT


def media_type_for(rel_path: str) -> str:
    ext = os.path.splitext(rel_path)[1].lower()
    if ext in _MEDIA_TYPES:
        return _MEDIA_TYPES[ext]
    import mimetypes

    guessed = mimetypes.guess_type(rel_path)[0] or "application/octet-stream"
    return f"{guessed}; charset=utf-8" if guessed.startswith("text/") else guessed


def is_reserved(path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in RESERVED_ROOTS)


def candidate_paths(url_path: str) -> list[str] | None:
    """Release-relative files a URL path may map to, in order; None if the path is refused.

    `/` → index.html · `/x` → x, x.html, x/index.html · `/x/` → x/index.html, x.html.
    Refused: NUL or backslash anywhere, `.`/`..` segments, dotfile segments, over-long paths, and
    direct requests for the internal `.gz` siblings (they are only served via content negotiation).
    """
    if len(url_path) > 1024 or "\x00" in url_path or "\\" in url_path or not url_path.startswith("/"):
        return None
    trailing = url_path.endswith("/")
    segments = [s for s in url_path.split("/") if s]
    for s in segments:
        if s in (".", "..") or s.startswith("."):
            return None
    if not segments:
        return ["index.html"]
    if segments[-1].lower().endswith(".gz"):
        return None
    rel = "/".join(segments)
    if trailing:
        return [f"{rel}/index.html", f"{rel}.html"]
    return [rel, f"{rel}.html", f"{rel}/index.html"]


def etag_for(st: os.stat_result, encoding: str | None) -> str:
    """Strong ETag from (mtime_ns, size, inode) plus the content-coding, so the gzip and identity
    representations never share a tag. Carried-forward chunk copies keep the mtime, so their size
    and mtime match the original; the inode differs, which only costs one extra 200."""
    tag = f"{st.st_mtime_ns:x}-{st.st_size:x}-{st.st_ino:x}"
    return f'"{tag}-gz"' if encoding == "gzip" else f'"{tag}"'


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """Weak comparison (RFC 9110 §13.1.2) of If-None-Match against our ETag."""
    value = if_none_match.strip()
    if value == "*":
        return True
    ours = etag.removeprefix("W/")
    for candidate in value.split(","):
        c = candidate.strip()
        c = c.removeprefix("W/")
        if c == ours:
            return True
    return False


def is_not_modified(request_headers: Headers, etag: str, mtime: float) -> bool:
    inm = request_headers.get("if-none-match")
    if inm is not None:
        return _etag_matches(inm, etag)
    ims = request_headers.get("if-modified-since")
    if ims:
        try:
            since = parsedate_to_datetime(ims)
        except (TypeError, ValueError, IndexError):
            return False
        if since is None:
            return False
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        return int(mtime) <= int(since.timestamp())
    return False


def read_build_info(root: Path | str) -> dict[str, Any] | None:
    """Parse <release root>/build-info.json; None if absent, unreadable or not a JSON object."""
    try:
        with open(os.path.join(root, "build-info.json"), "rb") as fh:
            data = json.loads(fh.read(64 * 1024))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ── resolution (runs in a worker thread) ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Lookup:
    status: Literal["ok", "not_found", "build_missing"]
    root: str | None = None          # realpath of the release root (None when the build is missing)
    rel: str | None = None           # release-relative path of the ORIGINAL file
    path: str | None = None          # file actually served (the .gz sibling when gzip is used)
    st: os.stat_result | None = None
    encoding: str | None = None
    has_gzip_sibling: bool = False
    reason: str | None = None


def _is_inside(child: str, root: str) -> bool:
    return child == root or child.startswith(root.rstrip(os.sep) + os.sep)


def _regular_file(path: str) -> os.stat_result | None:
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return st if stat.S_ISREG(st.st_mode) else None


def lookup(dist_dir: Path, candidates: list[str], want_gzip: bool) -> Lookup:
    """Resolve the dist symlink NOW and find the first candidate inside the release root."""
    try:
        root = os.path.realpath(dist_dir, strict=True)
    except (OSError, ValueError):
        return Lookup("build_missing", reason=f"{dist_dir} does not exist (or is a dangling link)")
    if not os.path.isdir(root):
        return Lookup("build_missing", reason=f"{dist_dir} is not a directory")
    if _regular_file(os.path.join(root, "index.html")) is None:
        return Lookup("build_missing", root=root, reason="index.html missing in the release")
    for rel in candidates:
        full = os.path.realpath(os.path.join(root, rel))
        if not _is_inside(full, root):
            return Lookup("not_found", root=root, rel=rel, reason="escapes the release root")
        st = _regular_file(full)
        if st is None:
            continue
        ext = os.path.splitext(rel)[1].lower()
        gz_st = None
        gz_real = ""
        if ext in COMPRESSIBLE_EXT:
            gz_real = os.path.realpath(full + ".gz")
            if _is_inside(gz_real, root):
                gz_st = _regular_file(gz_real)
        if want_gzip and gz_st is not None:
            return Lookup("ok", root=root, rel=rel, path=gz_real, st=gz_st, encoding="gzip", has_gzip_sibling=True)
        return Lookup("ok", root=root, rel=rel, path=full, st=st, has_gzip_sibling=gz_st is not None)
    return Lookup("not_found", root=root)


def _read_whole(path: str, size: int) -> bytes:
    with open(path, "rb") as fh:
        data = fh.read(size + 1)
    if len(data) != size:
        raise OSError(f"{path} changed size while being read")
    return data


class _BodyCache:
    """Bounded LRU of file bodies keyed by (path, inode, size, mtime_ns); thread-safe."""

    def __init__(self, max_bytes: int = _MAX_CACHE_BYTES) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[tuple[str, int, int, int], bytes] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    @staticmethod
    def key(path: str, st: os.stat_result) -> tuple[str, int, int, int]:
        return (path, st.st_ino, st.st_size, st.st_mtime_ns)

    def get(self, key: tuple[str, int, int, int]) -> bytes | None:
        with self._lock:
            data = self._items.get(key)
            if data is not None:
                self._items.move_to_end(key)
            return data

    def put(self, key: tuple[str, int, int, int], data: bytes) -> None:
        if len(data) > self.max_bytes:
            return
        with self._lock:
            if key in self._items:
                return
            self._items[key] = data
            self._bytes += len(data)
            while self._bytes > self.max_bytes and self._items:
                _, old = self._items.popitem(last=False)
                self._bytes -= len(old)

    @property
    def size_bytes(self) -> int:
        return self._bytes


# ── the ASGI fallback ─────────────────────────────────────────────────────────────────────────────

_MISSING_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10"><title>SuryaDhana: UI build missing</title>
<style>
 :root{color-scheme:dark}
 body{margin:0;background:#000;color:#d7dde4;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
 main{max-width:720px;margin:12vh auto;padding:0 24px}
 h1{font-size:15px;letter-spacing:.08em;color:#ffb000;margin:0 0 16px}
 code,pre{background:#0d1117;border:1px solid #30363d;border-radius:3px;color:#7ee787}
 pre{padding:10px 12px;overflow-x:auto} code{padding:1px 5px} .dim{color:#8b949e}
</style></head>
<body><main>
<h1>SURYADHANA &middot; TERMINAL UI BUILD NOT FOUND</h1>
<p>ui-api is running and the API works, but there is no usable UI release to serve
(<span class="dim">__REASON__</span>).</p>
<p>Build and publish one from the repository root:</p>
<pre>scripts/build_ui.sh</pre>
<p>Or bring back the previous release: <code>scripts/build_ui.sh --rollback</code>.
The new build is served on the next request, with no ui-api restart. This page checks again every 10 s.</p>
<p class="dim">API: <a style="color:#58a6ff" href="/health">/health</a> &middot;
<a style="color:#58a6ff" href="/version">/version</a> &middot; dist: __DIST__</p>
</main></body></html>
"""


class StaticUI:
    """ASGI app installed as the FastAPI router's not-found fallback (see module docstring)."""

    def __init__(self, dist_dir: Path, fallback: ASGIApp) -> None:
        self.dist_dir = dist_dir
        self.fallback = fallback
        self.limiter = CapacityLimiter(_LIMITER_TOKENS)
        self.cache = _BodyCache()
        self._state_lock = threading.Lock()
        self._last_root: str | None = None
        self._last_status: str | None = None
        self._refused_at = 0.0
        self._refused_suppressed = 0

    # state-change logging -------------------------------------------------------------------
    def _note(self, result: Lookup) -> None:
        status = "missing" if result.status == "build_missing" else "ok"
        with self._state_lock:
            prev_status, prev_root = self._last_status, self._last_root
            self._last_status = status
            if status == "ok":
                self._last_root = result.root
        if status == "missing" and prev_status != "missing":
            _event(logging.WARNING, "static_ui.build_missing", dist=str(self.dist_dir), reason=result.reason)
        elif status == "ok" and prev_status == "missing":
            _event(logging.INFO, "static_ui.build_restored", release=_release_id(result.root))
        if status == "ok" and prev_root is not None and result.root != prev_root:
            _event(logging.INFO, "static_ui.release_changed",
                   from_release=_release_id(prev_root), to_release=_release_id(result.root))

    def _note_refused(self, path: str) -> None:
        now = time.monotonic()
        with self._state_lock:
            if now - self._refused_at < 10.0:
                self._refused_suppressed += 1
                return
            suppressed, self._refused_suppressed, self._refused_at = self._refused_suppressed, 0, now
        _event(logging.WARNING, "static_ui.path_refused", path=path[:200], suppressed_since_last=suppressed)

    # ASGI --------------------------------------------------------------------------------------
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.fallback(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        path: str = scope.get("path", "/")
        if method not in ("GET", "HEAD") or is_reserved(path):
            await self.fallback(scope, receive, send)
            return
        candidates = candidate_paths(path)
        if candidates is None:
            self._note_refused(path)
            await self.fallback(scope, receive, send)
            return
        headers = Headers(scope=scope)
        result = await anyio.to_thread.run_sync(
            lookup, self.dist_dir, candidates, accepts_gzip(headers.get("accept-encoding")), limiter=self.limiter
        )
        self._note(result)
        if result.status == "build_missing":
            await self._missing(scope, receive, send, headers, method, result.reason or "unknown")
            return
        if result.status == "not_found":
            if result.reason:
                self._note_refused(path)
            await self._not_found(scope, receive, send, headers, method)
            return
        await self._serve(scope, receive, send, headers, method, result)

    async def _serve(self, scope: Scope, receive: Receive, send: Send, headers: Headers, method: str,
                     result: Lookup) -> None:
        assert result.st is not None and result.path is not None and result.rel is not None
        st = result.st
        rel = result.rel
        ext = os.path.splitext(rel)[1].lower()
        etag = etag_for(st, result.encoding)
        out: dict[str, str] = {
            "cache-control": cache_control_for(rel),
            "etag": etag,
            "last-modified": formatdate(st.st_mtime, usegmt=True),
            **(_HTML_SECURITY_HEADERS if ext == ".html" else _STATIC_SECURITY_HEADERS),
        }
        if ext in COMPRESSIBLE_EXT:
            out["vary"] = "Accept-Encoding"
        if is_not_modified(headers, etag, st.st_mtime):
            not_modified = {k: v for k, v in out.items() if k in ("cache-control", "etag", "last-modified", "vary")}
            await Response(status_code=304, headers=not_modified)(scope, receive, send)
            return
        if result.encoding:
            out["content-encoding"] = result.encoding
        out["content-length"] = str(st.st_size)
        media_type = media_type_for(rel)
        if method == "HEAD":
            await Response(content=b"", headers=out, media_type=media_type)(scope, receive, send)
            return
        if st.st_size <= _MAX_CACHED_FILE:
            key = _BodyCache.key(result.path, st)
            body = self.cache.get(key)
            if body is None:
                body = await anyio.to_thread.run_sync(_read_whole, result.path, st.st_size, limiter=self.limiter)
                self.cache.put(key, body)
            await Response(content=body, headers=out, media_type=media_type)(scope, receive, send)
            return
        await StreamingResponse(self._stream(result.path, st.st_size), headers=out, media_type=media_type)(
            scope, receive, send)

    async def _stream(self, path: str, size: int):
        fh = await anyio.to_thread.run_sync(open, path, "rb", limiter=self.limiter)
        try:
            remaining = size
            while remaining > 0:
                chunk = await anyio.to_thread.run_sync(fh.read, min(_STREAM_CHUNK, remaining), limiter=self.limiter)
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            fh.close()  # never awaits: must also run when the client disconnected (cancelled scope)

    async def _not_found(self, scope: Scope, receive: Receive, send: Send, headers: Headers, method: str) -> None:
        """A browser navigation gets the export's 404.html; everything else the JSON envelope 404."""
        if "text/html" in (headers.get("accept") or ""):
            result = await anyio.to_thread.run_sync(lookup, self.dist_dir, ["404.html"], False, limiter=self.limiter)
            if result.status == "ok" and result.path and result.st:
                body = await anyio.to_thread.run_sync(_read_whole, result.path, result.st.st_size, limiter=self.limiter)
                out = {"cache-control": CACHE_REVALIDATE, **_HTML_SECURITY_HEADERS,
                       "content-length": str(len(body))}
                await Response(content=b"" if method == "HEAD" else body, status_code=404, headers=out,
                               media_type=_MEDIA_TYPES[".html"])(scope, receive, send)
                return
        await self.fallback(scope, receive, send)

    async def _missing(self, scope: Scope, receive: Receive, send: Send, headers: Headers, method: str,
                       reason: str) -> None:
        out = {"cache-control": CACHE_NO_STORE, "retry-after": "10", **_STATIC_SECURITY_HEADERS}
        if scope.get("path") == "/" or "text/html" in (headers.get("accept") or ""):
            body = (_MISSING_PAGE.replace("__REASON__", _html_escape(reason))
                    .replace("__DIST__", _html_escape(_display_path(self.dist_dir)))).encode()
            media_type = _MEDIA_TYPES[".html"]
            out.update(_HTML_SECURITY_HEADERS)
        else:
            body = b"SuryaDhana UI build not found; run scripts/build_ui.sh\n"
            media_type = _MEDIA_TYPES[".txt"]
        out["content-length"] = str(len(body))
        await Response(content=b"" if method == "HEAD" else body, status_code=503, headers=out,
                       media_type=media_type)(scope, receive, send)

    # introspection -----------------------------------------------------------------------------
    async def current_build(self) -> tuple[str, dict[str, Any] | None]:
        """('ok', build-info|None) for a usable release, ('missing', None) otherwise."""
        def _probe() -> tuple[str, dict[str, Any] | None]:
            result = lookup(self.dist_dir, [], False)
            if result.status == "build_missing" or result.root is None:
                return "missing", None
            return "ok", read_build_info(result.root)

        return await anyio.to_thread.run_sync(_probe, limiter=self.limiter)


def _release_id(root: str | None) -> str | None:
    return os.path.basename(root) if root else None


def _display_path(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ── public API ────────────────────────────────────────────────────────────────────────────────────

def mount_static_ui(app: FastAPI, dist_dir: str | os.PathLike[str] | None = None) -> StaticUI:
    """Serve the static terminal UI from `dist_dir` (default $UI_DIST_DIR, else <repo>/ui/dist/current)
    as `app`'s not-found fallback. Idempotent: calling again re-points the existing handler.
    Never raises for a missing build (the UI answers 503 until a release exists)."""
    dist = resolve_dist_dir(dist_dir)
    current = app.router.default
    if isinstance(current, StaticUI):
        current.dist_dir = dist
        handler = current
    else:
        handler = StaticUI(dist, fallback=current)
        app.router.default = handler
    app.state.static_ui = handler
    probe = lookup(dist, [], False)  # once, at startup; the request path always runs in a thread
    _event(logging.INFO if probe.status != "build_missing" else logging.WARNING, "static_ui.mounted",
           dist=str(dist), release=_release_id(probe.root) if probe.status != "build_missing" else None,
           status="ok" if probe.status != "build_missing" else "missing", reason=probe.reason)
    return handler


version_router = APIRouter(tags=["meta"])
_NO_STORE = {"Cache-Control": CACHE_NO_STORE}


def _static_ui_of(request: Request) -> StaticUI | None:
    handler = getattr(request.app.state, "static_ui", None)
    return handler if isinstance(handler, StaticUI) else None


async def _ui_state(request: Request) -> tuple[str, dict[str, Any] | None]:
    handler = _static_ui_of(request)
    if handler is not None:
        return await handler.current_build()

    def _probe() -> tuple[str, dict[str, Any] | None]:
        result = lookup(resolve_dist_dir(), [], False)
        if result.status == "build_missing" or result.root is None:
            return "missing", None
        return "ok", read_build_info(result.root)

    return await anyio.to_thread.run_sync(_probe)


@version_router.get("/version")
async def version(request: Request) -> JSONResponse:
    """Service identity + the UI release being served (the build-info.json object, or null)."""
    ui_status, info = await _ui_state(request)
    return JSONResponse({"service": "ui-api", "api_version": request.app.version,
                         "ui_build": info, "ui_status": ui_status}, headers=_NO_STORE)


@version_router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness of the API (always 200 while it answers); `ui` reports the static UI separately
    so a missing UI build never makes health checkers treat the API as down."""
    ui_status, info = await _ui_state(request)
    return JSONResponse({"status": "ready", "service": "ui-api", "ui": ui_status,
                         "ui_build_id": (info or {}).get("id")}, headers=_NO_STORE)


@version_router.get("/live")
async def live() -> JSONResponse:
    """Liveness: the process and its event loop answer."""
    return JSONResponse({"status": "alive", "service": "ui-api"}, headers=_NO_STORE)
