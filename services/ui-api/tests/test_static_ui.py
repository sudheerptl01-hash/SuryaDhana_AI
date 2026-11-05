"""static_ui.py: ui-api serving the static terminal UI (desktop program Layer 1, AC-2).

Every test builds a throwaway release tree under tmp_path (never ui/dist). The app under test is a
bare FastAPI with main.py's REAL StarletteHTTPException handler (extracted from main.py's source with
`ast` and executed on its own: importing main would load .env into the test process and pull in
every router), plus a few API, SSE and WS routes standing in for ui-api's.

Covers: cache headers per class, gzip negotiation incl. q=0, HEAD, 304, path traversal (raw ASGI
paths, encoded `..`, symlink escapes), the missing-build 503, a live release swap without restart,
the API 404 envelope and 405/redirect semantics left intact, SSE unbuffered through a real uvicorn
server, the WS route not shadowed, a dedicated thread limiter, /version, /ready and /live.
"""
from __future__ import annotations

import ast
import asyncio
import gzip
import json
import logging
import os
import socket
import sys
import threading
import time
from email.utils import formatdate
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.websockets import WebSocket, WebSocketDisconnect

UI_API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI_API_DIR))
import static_ui
from static_ui import (
    CACHE_IMMUTABLE,
    CACHE_NO_STORE,
    CACHE_REVALIDATE,
    CACHE_SHORT,
    accepts_gzip,
    cache_control_for,
    candidate_paths,
    mount_static_ui,
    read_build_info,
    version_router,
)

# ── fixtures ────────────────────────────────────────────────────────────────────────────────────

CHUNK = "_next/static/chunks/app-3f2a9c.js"
CSS = "_next/static/css/main-77aa01.css"


def _write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


def _gz_sibling(path: Path) -> None:
    raw = path.read_bytes()
    gz = path.with_name(path.name + ".gz")
    gz.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    st = path.stat()
    os.utime(gz, ns=(st.st_atime_ns, st.st_mtime_ns))


def make_release(dist: Path, rid: str, marker: str, *, gzip_assets: bool = True) -> Path:
    """A minimal static export like build_ui.sh produces (index/404/RSC/chunks/icon/build-info)."""
    root = dist / "releases" / rid
    pad = "<!-- " + ("x" * 3000) + " -->"  # > 1 KB so it gets a .gz sibling
    _write(root / "index.html",
           f'<!doctype html><html><head><script src="/{CHUNK}"></script></head>'
           f"<body>{marker}{pad}</body></html>")
    _write(root / "404.html", f"<!doctype html><title>404</title><p>not found {marker}</p>{pad}")
    _write(root / "index.txt", f"0:RSC payload {marker} " + "y" * 2000)
    _write(root / CHUNK, f"/* {marker} */ console.log('chunk');" + "z" * 4000)
    _write(root / CSS, "body{background:#000}" + " " * 2000)
    _write(root / "_next/static/chunks/tiny.js", "x=1")  # < 1 KB: no .gz sibling
    _write(root / "icon.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")
    _write(root / "fonts/mono.woff2", b"wOF2" + os.urandom(64))
    _write(root / "metrics", "must never be served")   # reserved names inside a release
    _write(root / "version", "must never be served")
    _write(root / "build-info.json", json.dumps({"id": rid, "git_sha": rid[-7:], "built_at": "2026-10-24T05:50:07Z",
                                                 "files": 9, "bytes": 12345, "next_version": "15.5.18"}))
    if gzip_assets:
        for rel in ("index.html", "404.html", "index.txt", CHUNK, CSS):
            _gz_sibling(root / rel)
    return root


def point(dist: Path, name: str, rid: str) -> None:
    """Atomic symlink swap, exactly like ui/scripts/release.mjs (temp link + rename(2))."""
    tmp = dist / f".{name}.tmp-{os.getpid()}"
    if tmp.is_symlink():
        tmp.unlink()
    os.symlink(f"releases/{rid}", tmp)
    os.replace(tmp, dist / name)


RID_A = "20261024-101500-aaaaaaa"
RID_B = "20261024-111500-bbbbbbb"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    make_release(d, RID_A, "RELEASE-A")
    make_release(d, RID_B, "RELEASE-B")
    point(d, "current", RID_A)
    return d


def _real_error_handler():
    """main.py's `_error_contract_handler`, compiled from main.py's own source (not a copy)."""
    tree = ast.parse((UI_API_DIR / "main.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_error_contract_handler")
    decorators = [ast.unparse(d) for d in fn.decorator_list]
    assert decorators == ["app.exception_handler(StarletteHTTPException)"], decorators
    fn.decorator_list = []
    module = ast.Module(body=[fn], type_ignores=[])
    ns: dict[str, Any] = {"Request": Request, "JSONResponse": JSONResponse,
                          "StarletteHTTPException": StarletteHTTPException}
    exec(compile(module, str(UI_API_DIR / "main.py"), "exec"), ns)  # noqa: S102 - our own source
    return ns["_error_contract_handler"]


def make_app(dist_dir: Path | None, *, mount: bool = True) -> FastAPI:
    app = FastAPI(title="static-ui-test", version="1.0.0")
    app.add_exception_handler(StarletteHTTPException, _real_error_handler())

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "ui-api"}

    @app.get("/api/thing")
    async def thing():
        return {"ok": True}

    @app.post("/api/only-post")
    async def only_post():
        return {"posted": True}

    @app.get("/api/sync-block")
    def sync_block(seconds: float = 1.0):  # sync route: runs in AnyIO's DEFAULT thread limiter
        time.sleep(seconds)
        return {"slept": seconds}

    @app.post("/api/_limit-default-threads")
    async def limit_default_threads(tokens: int = 1):
        anyio.to_thread.current_default_thread_limiter().total_tokens = tokens
        return {"tokens": tokens}

    @app.get("/api/sse")
    async def sse(gap: float = 1.5):
        async def gen():
            yield b"data: first\n\n"
            await asyncio.sleep(gap)
            yield b"data: second\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.websocket("/api/monitor/ws/monitor")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        msg = await websocket.receive_text()
        await websocket.send_text(f"echo:{msg}")
        await websocket.close()

    app.include_router(version_router)
    if mount:
        mount_static_ui(app, dist_dir)
    return app


@pytest.fixture
def client(dist: Path) -> TestClient:
    return TestClient(make_app(dist / "current"))


def asgi_request(app: FastAPI, path: str, *, method: str = "GET",
                 headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    """Drive the ASGI app with an exact, already-decoded path, as uvicorn passes it (no client-side
    URL normalisation, which httpx applies to `..`)."""
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode("utf-8", "surrogateescape"),
             "root_path": "", "query_string": b"", "headers": hdrs, "client": ("127.0.0.1", 5555),
             "server": ("127.0.0.1", 8010)}
    out: dict[str, Any] = {"status": 0, "headers": {}, "body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"")

    anyio.run(app, scope, receive, send)
    return out["status"], out["headers"], out["body"]


# ── pure helpers ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("header,expected", [
    (None, False), ("", False), ("identity", False), ("br", False),
    ("gzip", True), ("GZIP", True), ("x-gzip", True), ("gzip, deflate, br", True),
    ("gzip;q=0", False), ("gzip; q=0.0", False), ("gzip;q=0.001", True), ("br;q=1, gzip;q=0", False),
    ("*", True), ("*;q=0", False), ("*;q=0, gzip", True), ("gzip;q=0, *", False),
    ("gzip;q=abc", False), ("gzip;q=2", False), (" , gzip", True),
])
def test_accepts_gzip(header, expected):
    assert accepts_gzip(header) is expected


@pytest.mark.parametrize("rel,expected", [
    ("index.html", CACHE_REVALIDATE), ("404.html", CACHE_REVALIDATE), ("index.txt", CACHE_REVALIDATE),
    (CHUNK, CACHE_IMMUTABLE), ("_next/static/abc123/_buildManifest.js", CACHE_IMMUTABLE),
    ("build-info.json", CACHE_NO_STORE), ("icon.svg", CACHE_SHORT), ("fonts/mono.woff2", CACHE_SHORT),
    ("data/x.json", CACHE_REVALIDATE),
])
def test_cache_control_classes(rel, expected):
    assert cache_control_for(rel) == expected


@pytest.mark.parametrize("path,expected", [
    ("/", ["index.html"]),
    ("/icon.svg", ["icon.svg", "icon.svg.html", "icon.svg/index.html"]),
    ("/x/", ["x/index.html", "x.html"]),
    ("//icon.svg", ["icon.svg", "icon.svg.html", "icon.svg/index.html"]),
    ("/../etc/passwd", None), ("/a/../../b", None), ("/./index.html", None), ("/.env", None),
    ("/_next/.git/config", None), ("/a\\..\\b", None), ("/a\x00b", None), ("/index.html.gz", None),
    ("relative", None), ("/" + "a" * 2000, None),
])
def test_candidate_paths(path, expected):
    assert candidate_paths(path) == expected


def test_read_build_info_tolerates_garbage(tmp_path):
    assert read_build_info(tmp_path) is None
    (tmp_path / "build-info.json").write_text("{not json")
    assert read_build_info(tmp_path) is None
    (tmp_path / "build-info.json").write_text("[1, 2]")
    assert read_build_info(tmp_path) is None
    (tmp_path / "build-info.json").write_text('{"id": "x"}')
    assert read_build_info(tmp_path) == {"id": "x"}


def test_dist_dir_resolution_order(tmp_path, monkeypatch):
    monkeypatch.delenv("UI_DIST_DIR", raising=False)
    assert static_ui.resolve_dist_dir() == static_ui.DEFAULT_DIST_DIR
    assert static_ui.DEFAULT_DIST_DIR == UI_API_DIR.parents[1] / "ui" / "dist" / "current"
    monkeypatch.setenv("UI_DIST_DIR", str(tmp_path / "env"))
    assert static_ui.resolve_dist_dir() == tmp_path / "env"
    assert static_ui.resolve_dist_dir(tmp_path / "arg") == tmp_path / "arg"


# ── serving + headers per class ─────────────────────────────────────────────────────────────────

def test_root_serves_index_no_cache(client):
    r = client.get("/", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert "RELEASE-A" in r.text
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["etag"].startswith('"') and r.headers["last-modified"].endswith("GMT")
    assert r.headers["vary"] == "Accept-Encoding"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-encoding" not in r.headers
    assert int(r.headers["content-length"]) == len(r.content)


def test_query_string_still_serves_index(client):
    r = client.get("/?tab=desk")
    assert r.status_code == 200 and "RELEASE-A" in r.text


def test_hashed_assets_are_immutable(client):
    r = client.get(f"/{CHUNK}", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.headers["content-type"] == "text/javascript; charset=utf-8"
    css = client.get(f"/{CSS}", headers={"Accept-Encoding": "identity"})
    assert css.headers["content-type"] == "text/css; charset=utf-8"
    assert css.headers["cache-control"] == CACHE_IMMUTABLE


def test_build_info_is_no_store(client):
    r = client.get("/build-info.json")
    assert r.status_code == 200 and r.json()["id"] == RID_A
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"] == "application/json"


def test_other_files_short_cache_and_types(client):
    svg = client.get("/icon.svg")
    assert svg.headers["cache-control"] == CACHE_SHORT and svg.headers["content-type"] == "image/svg+xml"
    font = client.get("/fonts/mono.woff2")
    assert font.headers["content-type"] == "font/woff2" and font.headers["cache-control"] == CACHE_SHORT
    assert "vary" not in font.headers  # never compressible, so the response does not vary
    rsc = client.get("/index.txt", headers={"Accept-Encoding": "identity"})
    assert rsc.headers["content-type"] == "text/plain; charset=utf-8"  # Next's export RSC check
    assert rsc.headers["cache-control"] == CACHE_REVALIDATE


# ── gzip negotiation ────────────────────────────────────────────────────────────────────────────

def _raw(client: TestClient, path: str, accept_encoding: str | None) -> tuple[httpx.Response, bytes]:
    headers = {"Accept-Encoding": accept_encoding} if accept_encoding is not None else {}
    with client.stream("GET", path, headers=headers) as r:
        raw = b"".join(r.iter_raw())
    return r, raw


def test_gzip_served_when_accepted(client, dist):
    original = (dist / "releases" / RID_A / CHUNK).read_bytes()
    gz_file = (dist / "releases" / RID_A / (CHUNK + ".gz")).read_bytes()
    r, raw = _raw(client, f"/{CHUNK}", "gzip, deflate, br")
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["content-type"] == "text/javascript; charset=utf-8"   # the ORIGINAL file's type
    assert r.headers["vary"] == "Accept-Encoding"
    assert int(r.headers["content-length"]) == len(gz_file) == len(raw)
    assert raw == gz_file and gzip.decompress(raw) == original
    assert r.headers["etag"].endswith('-gz"')


@pytest.mark.parametrize("ae", ["gzip;q=0", "identity", "br", "*;q=0", None])
def test_identity_when_gzip_not_acceptable(client, dist, ae):
    original = (dist / "releases" / RID_A / CHUNK).read_bytes()
    r, raw = _raw(client, f"/{CHUNK}", ae if ae is not None else "")
    assert r.status_code == 200
    assert "content-encoding" not in r.headers
    assert raw == original and int(r.headers["content-length"]) == len(original)
    assert r.headers["vary"] == "Accept-Encoding"


def test_star_accepts_gzip(client):
    r, _ = _raw(client, "/", "*")
    assert r.headers["content-encoding"] == "gzip"


def test_small_file_without_sibling_is_identity_even_if_gzip_accepted(client):
    r, raw = _raw(client, "/_next/static/chunks/tiny.js", "gzip")
    assert "content-encoding" not in r.headers and raw == b"x=1"


def test_gzip_and_identity_have_distinct_etags(client):
    a = client.get("/", headers={"Accept-Encoding": "gzip"}).headers["etag"]
    b = client.get("/", headers={"Accept-Encoding": "identity"}).headers["etag"]
    assert a != b


def test_direct_request_for_gz_sibling_is_refused(client):
    r = client.get("/index.html.gz")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ── HEAD and conditional requests ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ae", ["gzip", "identity"])
def test_head_matches_get_without_body(client, ae):
    g = client.get(f"/{CHUNK}", headers={"Accept-Encoding": ae})
    h = client.head(f"/{CHUNK}", headers={"Accept-Encoding": ae})
    assert h.status_code == 200 and h.content == b""
    for k in ("content-type", "content-length", "etag", "last-modified", "cache-control", "vary"):
        assert h.headers[k] == g.headers[k], k
    assert h.headers.get("content-encoding") == g.headers.get("content-encoding")


def test_etag_revalidation_304(client):
    first = client.get("/", headers={"Accept-Encoding": "identity"})
    etag = first.headers["etag"]
    for inm in (etag, f"W/{etag}", f'"nope", {etag}', "*"):
        r = client.get("/", headers={"If-None-Match": inm, "Accept-Encoding": "identity"})
        assert r.status_code == 304, inm
        assert r.content == b""
        assert r.headers["etag"] == etag and r.headers["cache-control"] == "no-cache"
        assert r.headers["vary"] == "Accept-Encoding"
    miss = client.get("/", headers={"If-None-Match": '"other"', "Accept-Encoding": "identity"})
    assert miss.status_code == 200


def test_if_modified_since(client, dist):
    mtime = (dist / "releases" / RID_A / "index.html").stat().st_mtime
    later = formatdate(mtime + 60, usegmt=True)
    earlier = formatdate(mtime - 3600, usegmt=True)
    assert client.get("/", headers={"If-Modified-Since": later}).status_code == 304
    assert client.get("/", headers={"If-Modified-Since": earlier}).status_code == 200
    assert client.get("/", headers={"If-Modified-Since": "garbage"}).status_code == 200
    # If-None-Match takes precedence over If-Modified-Since (RFC 9110 §13.2.2)
    r = client.get("/", headers={"If-None-Match": '"other"', "If-Modified-Since": later})
    assert r.status_code == 200


def test_head_304(client):
    etag = client.get("/icon.svg").headers["etag"]
    r = client.head("/icon.svg", headers={"If-None-Match": etag})
    assert r.status_code == 304


# ── path traversal ──────────────────────────────────────────────────────────────────────────────

SECRET = "TOP-SECRET-OUTSIDE-THE-RELEASE"


@pytest.fixture
def escape_dist(dist: Path, tmp_path: Path) -> Path:
    outside = _write(tmp_path / "outside" / "secret.txt", SECRET)
    root = dist / "releases" / RID_A
    os.symlink(outside, root / "leak.txt")                      # file symlink escaping the release
    os.symlink(outside.parent, root / "leakdir")                # dir symlink escaping the release
    os.symlink(outside, root / "evil.js.gz")
    _write(root / "evil.js", "console.log('fine')" + "q" * 2000)  # its .gz sibling escapes
    return dist


@pytest.mark.parametrize("path", [
    "/../outside/secret.txt", "/../../outside/secret.txt", "/_next/../../outside/secret.txt",
    "/leak.txt", "/leakdir/secret.txt", "/.././.././etc/passwd", "/..", "/%2e%2e/outside/secret.txt",
    "/a\\..\\..\\outside\\secret.txt", "/.git/config", "/index.html\x00.png",
])
def test_traversal_attempts_never_leak(escape_dist, path):
    app = make_app(escape_dist / "current")
    status, headers, body = asgi_request(app, path)
    assert status == 404, (path, status)
    assert SECRET.encode() not in body
    assert headers["content-type"] == "application/json"  # the envelope, not a file


def test_encoded_traversal_through_real_http(escape_dist):
    """httpx would normalise `..`, so send the percent-encoded form; Starlette decodes it into the
    path the handler sees. Either way the secret must never come back."""
    client = TestClient(make_app(escape_dist / "current"))
    for url in ("/%2e%2e/outside/secret.txt", "/_next/%2e%2e%2f%2e%2e%2foutside%2fsecret.txt",
                "/%2e%2e%2f%2e%2e%2fetc%2fpasswd", "/leakdir%2fsecret.txt"):
        r = client.get(url)
        assert r.status_code == 404, url
        assert SECRET not in r.text


def test_gz_sibling_escaping_the_release_is_ignored(escape_dist):
    client = TestClient(make_app(escape_dist / "current"))
    r = client.get("/evil.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and "content-encoding" not in r.headers
    assert SECRET not in r.text


def test_reserved_names_inside_a_release_are_never_served(client):
    for path in ("/metrics", "/version"):
        r = client.get(path)
        assert "must never be served" not in r.text, path
    assert client.get("/metrics").status_code == 404
    assert client.get("/version").json()["service"] == "ui-api"


# ── API contract left intact (real main.py handler) ─────────────────────────────────────────────

def test_unknown_api_path_keeps_json_envelope(client):
    for method in ("GET", "POST", "PUT", "DELETE", "HEAD"):
        r = client.request(method, "/api/does-not-exist")
        assert r.status_code == 404, method
        if method != "HEAD":
            assert r.json() == {"detail": "Not Found", "error": {"code": "not_found", "message": "Not Found"}}
            assert r.headers["content-type"] == "application/json"


def test_reserved_roots_are_not_shadowed(client):
    assert client.get("/health").json() == {"status": "ok", "service": "ui-api"}
    assert client.get("/api/thing").json() == {"ok": True}
    assert client.get("/docs").status_code == 200 and "swagger" in client.get("/docs").text.lower()
    assert client.get("/redoc").status_code == 200
    spec = client.get("/openapi.json").json()
    assert set(spec["paths"]) >= {"/health", "/api/thing", "/version", "/ready", "/live"}
    assert not any(p in spec["paths"] for p in ("/", "/{path}", "/{path:path}"))  # no static routes in the schema
    for path in ("/api", "/api/", "/health/x", "/docs/x", "/metrics", "/ready/x", "/live/x", "/version/x"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (404, 307), path
        if r.status_code == 404:
            assert r.json()["error"]["code"] == "not_found", path


def test_method_mismatch_and_slash_redirect_unchanged(client):
    # a Mount("/") would full-match these and turn 405 into 404 / break the redirect
    assert client.post("/health").status_code == 405
    assert client.get("/api/only-post").status_code == 405
    r = client.get("/health/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].endswith("/health")


def test_non_get_on_ui_paths_is_the_envelope_404(client):
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        r = client.request(method, "/")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", method


def test_missing_static_file(client):
    js = client.get("/_next/static/chunks/gone-123.js")
    assert js.status_code == 404 and js.json()["error"]["code"] == "not_found"
    page = client.get("/no-such-page", headers={"Accept": "text/html,application/xhtml+xml"})
    assert page.status_code == 404 and "not found RELEASE-A" in page.text
    assert page.headers["content-type"] == "text/html; charset=utf-8"


def test_mount_without_ui_leaves_404_behaviour_identical(dist):
    plain = TestClient(make_app(None, mount=False))
    mounted = TestClient(make_app(dist / "current"))
    for path in ("/api/x", "/health/nope", "/metrics"):
        a, b = plain.get(path), mounted.get(path)
        assert (a.status_code, a.json()) == (b.status_code, b.json()), path


# ── security headers (desktop review C2-security-09) ────────────────────────────────────────────

CSP = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"


def _assert_html_security(headers) -> None:
    assert headers["content-security-policy"] == CSP
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "same-origin"
    assert headers["x-content-type-options"] == "nosniff"


def test_html_pages_carry_the_security_headers(client):
    _assert_html_security(client.get("/").headers)
    _assert_html_security(client.get("/", headers={"Accept-Encoding": "gzip"}).headers)   # the .gz representation
    _assert_html_security(client.head("/").headers)
    page = client.get("/no-such-page", headers={"Accept": "text/html"})                 # the export's 404.html
    assert page.status_code == 404
    _assert_html_security(page.headers)


def test_csp_leaves_script_style_connect_and_frame_sources_open(client):
    csp = client.get("/").headers["content-security-policy"]
    for directive in ("default-src", "script-src", "style-src", "connect-src", "frame-src", "img-src"):
        assert directive not in csp     # inline bootstrap/styles and the TradingView iframe keep working


@pytest.mark.parametrize("path", [f"/{CHUNK}", f"/{CSS}", "/icon.svg", "/fonts/mono.woff2", "/index.txt",
                                  "/build-info.json"])
def test_non_html_static_files_get_nosniff_and_referrer_policy_only(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "same-origin"
    assert "content-security-policy" not in r.headers and "x-frame-options" not in r.headers


def test_security_headers_leave_caching_and_304_unchanged(client):
    r = client.get("/")
    assert r.headers["cache-control"] == CACHE_REVALIDATE
    again = client.get("/", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    assert set(again.headers) <= {"cache-control", "etag", "last-modified", "vary", "date", "server"}
    assert client.get(f"/{CHUNK}").headers["cache-control"] == CACHE_IMMUTABLE


def test_api_and_envelope_404_responses_get_no_static_headers(client):
    for path in ("/health", "/api/does-not-exist", "/_next/static/chunks/gone.js"):
        r = client.get(path)
        assert "content-security-policy" not in r.headers and "referrer-policy" not in r.headers, path


def test_missing_build_page_carries_the_security_headers(tmp_path):
    client = TestClient(make_app(tmp_path / "nothing-here"))
    page = client.get("/")
    assert page.status_code == 503
    _assert_html_security(page.headers)
    asset = client.get(f"/{CHUNK}")
    assert asset.status_code == 503 and asset.headers["x-content-type-options"] == "nosniff"
    assert asset.headers["referrer-policy"] == "same-origin" and "content-security-policy" not in asset.headers


# ── missing / broken build ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["absent", "dangling", "no_index", "file"])
def test_missing_build_is_a_clear_503_and_api_still_works(tmp_path, kind):
    dist = tmp_path / "dist"
    dist.mkdir()
    target = dist / "current"
    if kind == "dangling":
        os.symlink("releases/gone", target)
    elif kind == "no_index":
        _write(dist / "releases" / RID_A / "icon.svg", "<svg/>")
        point(dist, "current", RID_A)
    elif kind == "file":
        target.write_text("not a dir")
    client = TestClient(make_app(target))
    r = client.get("/")
    assert r.status_code == 503
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.headers["cache-control"] == "no-store" and r.headers["retry-after"] == "10"
    assert "scripts/build_ui.sh" in r.text and "--rollback" in r.text
    assert 'http-equiv="refresh"' in r.text
    asset = client.get(f"/{CHUNK}")
    assert asset.status_code == 503 and asset.headers["content-type"].startswith("text/plain")
    assert client.head("/").status_code == 503 and client.head("/").content == b""
    assert client.get("/health").status_code == 200
    assert client.get("/api/does-not-exist").json()["error"]["code"] == "not_found"
    v = client.get("/version").json()
    assert v["ui_build"] is None and v["ui_status"] == "missing"


def test_build_appearing_later_is_served_without_restart(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    client = TestClient(make_app(dist / "current"))
    assert client.get("/").status_code == 503
    make_release(dist, RID_A, "LATE-RELEASE")
    point(dist, "current", RID_A)
    r = client.get("/")
    assert r.status_code == 200 and "LATE-RELEASE" in r.text


# ── live release swap ───────────────────────────────────────────────────────────────────────────

def test_release_swap_is_live_without_restart(client, dist):
    assert "RELEASE-A" in client.get("/").text
    a_etag = client.get("/").headers["etag"]
    old_chunk = client.get(f"/{CHUNK}")
    assert "RELEASE-A" in old_chunk.text
    point(dist, "current", RID_B)
    r = client.get("/")
    assert "RELEASE-B" in r.text and r.headers["etag"] != a_etag
    # a window still holding A's ETag revalidates and gets B, not a stale 304
    assert client.get("/", headers={"If-None-Match": a_etag}).status_code == 200
    assert client.get("/build-info.json").json()["id"] == RID_B
    assert client.get("/version").json()["ui_build"]["id"] == RID_B
    point(dist, "current", RID_A)  # rollback is just as live
    assert "RELEASE-A" in client.get("/").text


def test_release_change_is_logged_once(client, dist):
    records: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = Grab()
    static_ui.log.addHandler(handler)
    try:
        client.get("/")
        point(dist, "current", RID_B)
        client.get("/")
        client.get("/")
    finally:
        static_ui.log.removeHandler(handler)
    changes = [r for r in records if r.getMessage() == "static_ui.release_changed"]
    assert len(changes) == 1
    assert changes[0].fields == {"from_release": RID_A, "to_release": RID_B}
    line = static_ui._JsonLineFormatter().format(changes[0])
    assert json.loads(line)["service"] == "ui-api" and json.loads(line)["event"] == "static_ui.release_changed"


def test_body_cache_reuses_reads_and_sees_new_content(client, dist, monkeypatch):
    calls: list[str] = []
    real = static_ui._read_whole

    def counting(path, size):
        calls.append(path)
        return real(path, size)

    monkeypatch.setattr(static_ui, "_read_whole", counting)
    for _ in range(3):
        assert client.get("/icon.svg").status_code == 200
    assert len(calls) == 1
    icon = dist / "releases" / RID_A / "icon.svg"
    icon.write_text("<svg xmlns='http://www.w3.org/2000/svg'><g/></svg>")
    os.utime(icon, ns=(icon.stat().st_atime_ns, icon.stat().st_mtime_ns + 5_000_000_000))
    assert client.get("/icon.svg").text.endswith("<g/></svg>")
    assert len(calls) == 2


def test_large_file_streams_with_exact_length(client, dist):
    blob = os.urandom(5 * 1024 * 1024 + 123)
    _write(dist / "releases" / RID_A / "big.bin", blob)
    r = client.get("/big.bin")
    assert r.status_code == 200 and r.content == blob
    assert int(r.headers["content-length"]) == len(blob)
    assert r.headers["content-type"] == "application/octet-stream"


def test_mount_is_idempotent(dist, tmp_path):
    app = make_app(dist / "current")
    first = app.router.default
    second = mount_static_ui(app, tmp_path / "elsewhere")
    assert second is first and app.router.default is first
    assert not isinstance(first.fallback, static_ui.StaticUI)
    assert TestClient(app).get("/").status_code == 503  # re-pointed at an empty location


# ── /version, /ready, /live ─────────────────────────────────────────────────────────────────────

def test_version_ready_live(client):
    v = client.get("/version")
    assert v.status_code == 200 and v.headers["cache-control"] == "no-store"
    body = v.json()
    assert body["service"] == "ui-api" and body["api_version"] == "1.0.0" and body["ui_status"] == "ok"
    assert body["ui_build"]["id"] == RID_A and body["ui_build"]["next_version"] == "15.5.18"
    rd = client.get("/ready").json()
    assert rd == {"status": "ready", "service": "ui-api", "ui": "ok", "ui_build_id": RID_A}
    assert client.get("/live").json() == {"status": "alive", "service": "ui-api"}


def test_version_without_mount_uses_default_dist(monkeypatch, tmp_path):
    monkeypatch.setenv("UI_DIST_DIR", str(tmp_path / "nothing"))
    c = TestClient(make_app(None, mount=False))
    assert c.get("/version").json()["ui_build"] is None
    assert c.get("/ready").json()["ui"] == "missing"


# ── event loop / thread pool ────────────────────────────────────────────────────────────────────

def test_static_lookups_do_not_queue_behind_the_default_thread_pool(dist):
    """ui-api's sync routes share AnyIO's default limiter. Shrink it to ONE token, hold that token
    with a blocking sync route, and the UI must still be served promptly (dedicated limiter)."""
    with TestClient(make_app(dist / "current")) as c:
        assert c.post("/api/_limit-default-threads?tokens=1").status_code == 200
        t = threading.Thread(target=lambda: c.get("/api/sync-block?seconds=1.5"), daemon=True)
        t.start()
        time.sleep(0.2)
        t0 = time.perf_counter()
        r1 = c.get("/", headers={"Accept-Encoding": "identity"})
        r2 = c.get(f"/{CHUNK}", headers={"Accept-Encoding": "gzip"})
        elapsed = time.perf_counter() - t0
        t.join(timeout=5)
        c.post("/api/_limit-default-threads?tokens=40")
    assert r1.status_code == 200 and r2.status_code == 200
    assert elapsed < 0.75, f"static serving waited on the default thread limiter ({elapsed:.2f}s)"


# ── SSE unbuffered + WS through a REAL server ───────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(dist):
    import uvicorn

    port = _free_port()
    config = uvicorn.Config(make_app(dist / "current"), host="127.0.0.1", port=port, log_level="warning",
                            lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_sse_streams_unbuffered_through_the_mounted_app(live_server):
    t0 = time.perf_counter()
    with httpx.Client(base_url=live_server, timeout=10) as c, \
            c.stream("GET", "/api/sse?gap=1.5", headers={"Accept": "text/event-stream"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert "content-encoding" not in r.headers and "content-length" not in r.headers
        chunks = r.iter_raw()
        first = next(chunks)
        first_at = time.perf_counter() - t0
        rest = b"".join(chunks)
        total = time.perf_counter() - t0
    assert first.startswith(b"data: first")
    assert b"data: second" in first + rest
    assert first_at < 0.75, f"first SSE byte took {first_at:.2f}s (buffered?)"
    assert total >= 1.4  # the generator really was still running when the first chunk arrived


def test_static_ui_over_real_http(live_server):
    with httpx.Client(base_url=live_server, timeout=10) as c:
        r = c.get("/", headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200 and r.headers["content-encoding"] == "gzip" and "RELEASE-A" in r.text
        h = c.head(f"/{CHUNK}", headers={"Accept-Encoding": "identity"})
        assert h.status_code == 200 and h.headers["content-length"] != "0" and h.content == b""
        raw = c.get("/%2e%2e/%2e%2e/etc/passwd")
        assert raw.status_code == 404 and "root:" not in raw.text


def test_websocket_route_not_shadowed(client):
    with client.websocket_connect("/api/monitor/ws/monitor") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "echo:ping"


def test_websocket_to_unknown_path_is_closed_not_served(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/") as ws:
        ws.receive_text()


# ── main.py wiring (active once the PM applies reports/desktop_app/patches/D1.md) ──────────────────

def test_main_py_wiring_when_applied():
    src = (UI_API_DIR / "main.py").read_text()
    if "static_ui" not in src:
        pytest.skip("D1 patch not applied to main.py yet")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    def lineno_of(name: str) -> list[int]:
        out = []
        for n in calls:
            f = n.func
            if (isinstance(f, ast.Attribute) and f.attr == name) or (isinstance(f, ast.Name) and f.id == name):
                out.append(n.lineno)
        return out

    mounts = lineno_of("mount_static_ui")
    includes = lineno_of("include_router")
    assert len(mounts) == 1, "mount_static_ui must be called exactly once"
    assert mounts[0] > max(includes), "mount_static_ui must come after every include_router"
    assert "version_router" in src
    assert "@app.get(\"/version\")" not in src and "@app.get('/version')" not in src
