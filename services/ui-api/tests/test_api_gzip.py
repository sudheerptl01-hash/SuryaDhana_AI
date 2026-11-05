"""Gzip of /api JSON (desktop review C2-performance-08): compressed when it pays (JSON, >= 4 KB, one body
message, client accepts gzip), never for streams (SSE must stay unbuffered), WebSockets, the static UI,
already-encoded or ETag'd responses. Unit tests on raw ASGI plus the REAL main.app stack (guard + gzip)."""
from __future__ import annotations

import asyncio
import gzip
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

UI_API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI_API_DIR))

from routers import _api_gzip as gz

BIG = json.dumps({"rows": [{"symbol": f"SYM{i}", "ltp": i * 1.5, "name": "Company Limited"} for i in range(400)]}).encode()


@pytest.mark.parametrize("header, ok", [
    ("gzip", True), ("gzip, deflate, br", True), ("br;q=1.0, gzip;q=0.8", True), ("GZIP", True), ("x-gzip", True),
    ("identity", False), ("", False), ("gzip;q=0", False), ("gzip;q=0.0, *;q=1", False), ("*", True),
    ("*;q=0", False), ("br", False), ("gzip;q=bogus", False), ("deflate, *;q=0.1", True),
])
def test_accept_encoding_parsing(header: str, ok: bool) -> None:
    assert gz.accepts_gzip(header) is ok


def _scope(path: str = "/api/stocks/list", accept: str | None = "gzip, deflate", kind: str = "http") -> dict[str, Any]:
    headers = [(b"host", b"127.0.0.1:8010")]
    if accept is not None:
        headers.append((b"accept-encoding", accept.encode()))
    return {"type": kind, "method": "GET", "path": path, "headers": headers, "query_string": b""}


def _json_app(body: bytes, *, ctype: bytes = b"application/json", status: int = 200,
              extra: list[tuple[bytes, bytes]] | None = None):
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", ctype), (b"content-length", str(len(body)).encode()), *(extra or [])]})
        await send({"type": "http.response.body", "body": body})
    return app


async def _call(app: Any, scope: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await gz.ApiGzipMiddleware(app)(scope, receive, send)
    return sent


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {k.decode().lower(): v.decode() for k, v in message["headers"]}


def test_large_json_is_gzipped_with_correct_headers() -> None:
    start, body = asyncio.run(_call(_json_app(BIG), _scope()))
    h = _headers(start)
    assert h["content-encoding"] == "gzip" and h["vary"] == "Accept-Encoding"
    assert int(h["content-length"]) == len(body["body"]) < len(BIG) // 3
    assert gzip.decompress(body["body"]) == BIG


def test_small_json_and_clients_without_gzip_get_the_identity_body() -> None:
    small = b'{"ok": true}'
    start, body = asyncio.run(_call(_json_app(small), _scope()))
    assert "content-encoding" not in _headers(start) and body["body"] == small
    start, body = asyncio.run(_call(_json_app(BIG), _scope(accept=None)))
    h = _headers(start)
    assert "content-encoding" not in h and h["vary"] == "Accept-Encoding" and body["body"] == BIG
    start, body = asyncio.run(_call(_json_app(BIG), _scope(accept="gzip;q=0")))
    assert "content-encoding" not in _headers(start) and body["body"] == BIG


@pytest.mark.parametrize("kw", [
    {"ctype": b"text/csv"}, {"ctype": b"text/html; charset=utf-8"}, {"ctype": b"application/octet-stream"},
    {"extra": [(b"content-encoding", b"br")]}, {"extra": [(b"etag", b'"abc"')]}, {"status": 304}, {"status": 204},
])
def test_ineligible_responses_pass_through_untouched(kw: dict[str, Any]) -> None:
    start, body = asyncio.run(_call(_json_app(BIG, **kw), _scope()))
    assert "vary" not in _headers(start) and body["body"] == BIG
    assert _headers(start).get("content-encoding") in (None, "br")


def test_problem_json_is_eligible() -> None:
    start, _ = asyncio.run(_call(_json_app(BIG, ctype=b"application/problem+json"), _scope()))
    assert _headers(start)["content-encoding"] == "gzip"


def test_static_ui_paths_and_websockets_are_never_touched() -> None:
    for path in ("/", "/_next/static/chunks/app.js", "/build-info.json", "/version", "/apix"):
        start, body = asyncio.run(_call(_json_app(BIG), _scope(path=path)))
        assert "content-encoding" not in _headers(start) and body["body"] == BIG
    seen: list[str] = []

    async def ws_app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])
    asyncio.run(_call(ws_app, _scope(kind="websocket")))
    assert seen == ["websocket"]


def _gated_stream_app(ctype: bytes, gates: list[asyncio.Event]):
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", ctype)]})
        for i, gate in enumerate(gates):
            await send({"type": "http.response.body", "body": f"data: {i}\n\n".encode() * 500, "more_body": True})
            await gate.wait()                                    # the next chunk only after the client saw this one
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    return app


@pytest.mark.parametrize("ctype", [b"text/event-stream", b"application/json", b"application/x-ndjson"])
def test_streams_are_never_buffered_or_compressed(ctype: bytes) -> None:
    """A buffering middleware deadlocks here: each chunk must reach the server before the app sends the next."""
    async def main() -> tuple[dict[str, str], list[bytes]]:
        gates = [asyncio.Event() for _ in range(3)]
        chunks: list[bytes] = []
        start: dict[str, str] = {}

        async def receive() -> dict[str, Any]:
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                start.update(_headers(message))
            elif message.get("body"):
                chunks.append(message["body"])
                gates[len(chunks) - 1].set()

        mw = gz.ApiGzipMiddleware(_gated_stream_app(ctype, gates))
        await asyncio.wait_for(mw(_scope(path="/api/pipeline/rl-stream/x"), receive, send), 5)
        return start, chunks

    start, chunks = asyncio.run(main())
    assert "content-encoding" not in start and len(chunks) == 3
    assert chunks[0].startswith(b"data: 0\n\n")


def test_big_bodies_are_compressed_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = gz.anyio.to_thread.run_sync

    async def spy(fn: Any, *args: Any, **kw: Any) -> Any:
        calls.append(len(args[0]))
        return await real(fn, *args, **kw)
    monkeypatch.setattr(gz.anyio.to_thread, "run_sync", spy)
    huge = json.dumps({"x": "y" * (gz.THREAD_THRESHOLD + 10)}).encode()
    _start, body = asyncio.run(_call(_json_app(huge), _scope()))
    assert calls == [len(huge)] and gzip.decompress(body["body"]) == huge
    calls.clear()
    asyncio.run(_call(_json_app(BIG), _scope()))
    assert calls == []                                            # small bodies stay inline (cheap)


# ── the real app: guard outermost, gzip inside it ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def ui_main(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    release = tmp_path_factory.mktemp("dist") / "release"
    (release / "_next" / "static").mkdir(parents=True)
    (release / "index.html").write_text("<!doctype html><title>SuryaDhana</title>" + "<p>x</p>" * 2000)
    (release / "_next" / "static" / "app.js").write_text("console.log(1);" * 2000)
    mp = pytest.MonkeyPatch()
    mp.setenv("UI_DIST_DIR", str(release))
    import dotenv
    mp.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    try:
        spec = importlib.util.spec_from_file_location("ui_api_main_gzip", UI_API_DIR / "main.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


def test_real_app_gzips_a_large_api_json_response(ui_main: ModuleType) -> None:
    c = TestClient(ui_main.app)
    for i in range(40):                                           # fill the (tmp) prefs store past 4 KB
        assert c.put(f"/api/prefs/k{i}", json={"value": "v" * 200, "updated_at": 1000 + i}).status_code == 200
    r = c.get("/api/prefs", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip" and len(r.json()["prefs"]) == 40
    assert "accept-encoding" in r.headers["vary"].lower()
    r = c.get("/api/prefs", headers={"accept-encoding": "identity"})
    assert "content-encoding" not in r.headers and len(r.json()["prefs"]) == 40
    r = c.get("/api/prefs", headers={"accept-encoding": "gzip", "host": "rebind.attacker.example"})
    assert r.status_code == 400                                   # the guard still runs first


def test_real_app_static_ui_is_left_to_static_ui(ui_main: ModuleType) -> None:
    c = TestClient(ui_main.app)
    for path in ("/", "/_next/static/app.js"):
        r = c.get(path, headers={"accept-encoding": "gzip"})
        assert r.status_code == 200
        assert r.headers.get("content-encoding") in (None, "gzip")   # static_ui's own precompressed .gz only
    r = c.get("/_next/static/app.js", headers={"accept-encoding": "gzip"})
    assert "content-encoding" not in r.headers                   # no .gz next to it: identity, not re-gzipped


def test_real_app_sse_stream_is_not_buffered(ui_main: ModuleType) -> None:
    """/api/pipeline/rl-stream through the whole stack (guard, gzip, router) with Accept-Encoding: gzip: each
    event reaches the client while the stream is still open."""
    pipeline = sys.modules["routers.pipeline"]
    job = "w2-api-sse-test"
    pipeline._jobs[job] = {"status": "running", "progress": 0}

    async def main() -> tuple[dict[str, str], list[bytes]]:
        start: dict[str, str] = {}
        chunks: list[bytes] = []
        got = asyncio.Event()

        async def receive() -> dict[str, Any]:
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                start.update(_headers(message))
            elif message.get("body"):
                chunks.append(message["body"])
                got.set()

        scope = {"type": "http", "method": "GET", "path": f"/api/pipeline/rl-stream/{job}", "raw_path": b"",
                 "query_string": b"", "root_path": "", "scheme": "http", "http_version": "1.1",
                 "server": ("127.0.0.1", 8010), "client": ("127.0.0.1", 50000),
                 "headers": [(b"host", b"127.0.0.1:8010"), (b"accept-encoding", b"gzip")]}
        task = asyncio.create_task(ui_main.app(scope, receive, send))
        await asyncio.wait_for(got.wait(), 5)                     # the status event, before anything else happens
        assert b"event: status" in chunks[0]
        got.clear()
        pipeline._emit(job, "hello")
        await asyncio.wait_for(got.wait(), 5)                     # a live event while the stream is open
        assert b"hello" in chunks[-1] and not task.done()
        pipeline._jobs[job]["status"] = "done"
        pipeline._emit(job, "bye")
        await asyncio.wait_for(task, 10)
        return start, chunks

    try:
        start, chunks = asyncio.run(main())
    finally:
        pipeline._jobs.pop(job, None)
        pipeline._train_log_queues.pop(job, None)
    assert start["content-type"].startswith("text/event-stream") and "content-encoding" not in start
    assert b"event: done" in chunks[-1]
