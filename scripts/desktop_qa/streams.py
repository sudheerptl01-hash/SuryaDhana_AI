"""Stream checks through a base URL: SSE flow, the monitor WebSocket, pipeline streams, POST-stream routability.

Every check is read-only against the live stack:

* ``sse_telemetry``   GET /api/telemetry/logs/stream — status 200, ``text/event-stream``, first byte < 2 s, and
                      continued flow: >= 2 frames AND >= 1 frame after the initial burst within ``--sse-window``
                      (master-controller replays the last 50 log lines, then heartbeats every 25 s, so the
                      default 30 s window proves the stream is not buffered by a proxy).
* ``ws_monitor``      WS /api/monitor/ws/monitor — connect, then ``{"action":"ping"}`` → ``{"pong": true}``.
                      The handler only reads Redis pub/sub; ping touches no state.
* ``ml_stream_unknown`` / ``rl_stream_unknown``  GET /api/pipeline/{ml,rl}-stream/<fixed non-existent id>.
                      Today's handler (services/ui-api/routers/pipeline.py) does NOT 404 an unknown id: it
                      registers an in-memory queue for it, sends ``event: status`` (pending) and then a
                      ``: heartbeat`` every 2 s until the client leaves (or 120 idle beats ≈ 4 min). PASS =
                      a clean 404 OR that well-formed pending stream (first frame < 2 s, a heartbeat < 6 s), i.e.
                      no hang. A FIXED id is used so repeated runs reuse one queue entry instead of adding one
                      each run. Informational: whether the front proxy releases its upstream socket to :8010
                      after the client closes (lsof on the proxy's pid; noisy if other clients use the proxy).
Every stream request sends a browser-like ``Accept-Encoding: gzip, deflate`` (``--accept-encoding``; an
EventSource in Chromium/WebKit always advertises gzip) and decodes the body incrementally itself, so a front
server that COMPRESSES an event stream is caught: compressors hold SSE frames in their buffer, which is a
stalled feed to the user. Such a response is reported with ``content_encoding`` and a precise problem line.

* ``post_streams_routable``  /api/ml/train/stream, /api/analytics/backtest/stream, /api/analytics/wfo-backtest/stream
                      are POST-only and start real work, so they are NEVER POSTed. A GET proves the route is
                      wired without running it: Starlette dispatches on method in the router (a path match with
                      the wrong method is answered 405 before dependencies/body/endpoint run), and the Next
                      route handlers export only POST (Next answers 405 itself). PASS = 405 on all three and 404
                      on a non-existent sibling path (negative control). A 404 JSON envelope on the real paths
                      is reported WARN: routable-ness not provable by GET (e.g. a catch-all static mount added
                      after the API routes outranks the 405 partial match) but still cannot start work.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/desktop_qa/streams.py \
        --base http://localhost:3000 --base http://127.0.0.1:8092 --out <dir>
Exit code: 0 = every check PASS/WARN/SKIP on every base, 1 = any FAIL.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

UNKNOWN_JOB_ID = "desktop-qa-nonexistent-job"
POST_ONLY_STREAMS = ("/api/ml/train/stream", "/api/analytics/backtest/stream", "/api/analytics/wfo-backtest/stream")
NEGATIVE_CONTROL = "/api/analytics/backtest/stream-desktop-qa-nonexistent"
UPSTREAM_PORT = 8010
BROWSER_ACCEPT_ENCODING = "gzip, deflate"   # what the harness can decode; browsers add br, zstd


# ── SSE parsing ───────────────────────────────────────────────────────────────────────────────────

class SSEParser:
    """Incremental SSE frame splitter: feed bytes, get complete frames (``\\n\\n``-separated) back."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        self._buf += chunk.replace(b"\r\n", b"\n")
        frames = []
        while b"\n\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n\n", 1)
            if raw.strip():
                frames.append(parse_frame(raw.decode("utf-8", "replace")))
        return frames


def parse_frame(raw: str) -> dict[str, Any]:
    """One SSE frame → {kind: 'comment'|'event', event, data, comment}."""
    event, data, comments = None, [], []
    for line in raw.split("\n"):
        if line.startswith(":"):
            comments.append(line[1:].strip())
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if not data and event is None:
        return {"kind": "comment", "comment": " ".join(comments)}
    return {"kind": "event", "event": event or "message", "data": "\n".join(data)}


class BodyDecoder:
    """Incremental Content-Encoding decoder (identity, gzip/x-gzip, deflate). ``supported`` is False for
    anything else (br, zstd …), in which case ``feed`` returns b"" and the caller reports it."""

    def __init__(self, encoding: str | None) -> None:
        enc = (encoding or "identity").strip().lower()
        self.encoding = enc
        self._z: Any = None
        if enc in ("gzip", "x-gzip"):
            self._z = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif enc == "deflate":
            self._z = zlib.decompressobj()
        self.supported = enc in ("identity", "gzip", "x-gzip", "deflate")

    def feed(self, chunk: bytes) -> bytes:
        if not self.supported:
            return b""
        return self._z.decompress(chunk) if self._z is not None else chunk


def encoding_problem(content_encoding: str | None) -> str | None:
    """Problem line when an event stream is content-encoded (a compressor buffers SSE frames)."""
    if not content_encoding or content_encoding.strip().lower() == "identity":
        return None
    return (f"event stream is content-encoded ({content_encoding}) by the front server: the compressor holds SSE "
            f"frames in its buffer (browsers always send Accept-Encoding: gzip), so the feed stalls")


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────

def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def listener_pid(port: int) -> int | None:
    """PID listening on ``port`` (read-only lsof), or None."""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True,
                             text=True, timeout=10, check=False).stdout.split()
        return int(out[0]) if out else None
    except Exception:
        return None


def upstream_conns(pid: int | None, port: int = UPSTREAM_PORT) -> int | None:
    """ESTABLISHED TCP connections from ``pid`` to ``port`` (read-only lsof); None if unknown."""
    if pid is None:
        return None
    try:
        out = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), f"-iTCP:{port}", "-sTCP:ESTABLISHED"],
                             capture_output=True, text=True, timeout=10, check=False).stdout
        return sum(1 for line in out.splitlines()[1:] if f":{port}" in line.split("->")[-1])
    except Exception:
        return None


async def read_stream(client: httpx.AsyncClient, url: str, *, window_s: float, stop: Any,
                      accept_encoding: str = BROWSER_ACCEPT_ENCODING) -> dict[str, Any]:
    """GET ``url`` as SSE, collect frames with arrival times until ``stop(frames)`` or ``window_s``.

    ``first_byte_ms`` is the first DECODED byte (what an EventSource can act on); ``raw_first_byte_ms`` is
    the first byte on the wire (a gzip header can arrive long before any frame does)."""
    t0 = time.perf_counter()
    res: dict[str, Any] = {"url": url, "http_status": None, "content_type": None, "content_encoding": None,
                           "server": None, "headers_ms": None, "raw_first_byte_ms": None, "first_byte_ms": None,
                           "raw_bytes": 0, "decoded_bytes": 0, "frames": [], "error": None}
    parser = SSEParser()
    try:
        async with asyncio.timeout(window_s):
            async with client.stream("GET", url, headers={"accept": "text/event-stream",
                                                          "accept-encoding": accept_encoding}) as r:
                res.update(http_status=r.status_code, content_type=r.headers.get("content-type"),
                           content_encoding=r.headers.get("content-encoding"), server=r.headers.get("server"),
                           headers_ms=_ms(t0))
                dec = BodyDecoder(res["content_encoding"])
                if not dec.supported:
                    res["error"] = f"undecodable content-encoding {dec.encoding!r}"
                async for chunk in r.aiter_raw():
                    if res["raw_first_byte_ms"] is None and chunk:
                        res["raw_first_byte_ms"] = _ms(t0)
                    res["raw_bytes"] += len(chunk)
                    data = dec.feed(chunk)
                    res["decoded_bytes"] += len(data)
                    if res["first_byte_ms"] is None and data:
                        res["first_byte_ms"] = _ms(t0)
                    for f in parser.feed(data):
                        f["t_ms"] = _ms(t0)
                        res["frames"].append(f)
                    if stop(res["frames"]):
                        break
    except TimeoutError:
        res["timed_out"] = True
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"[:300]
    res["elapsed_ms"] = _ms(t0)
    return res


# ── checks ────────────────────────────────────────────────────────────────────────────────────────

async def check_sse_telemetry(client: httpx.AsyncClient, base: str, window_s: float,
                              accept_encoding: str = BROWSER_ACCEPT_ENCODING) -> dict[str, Any]:
    def stop(frames: list[dict[str, Any]]) -> bool:
        if len(frames) < 2:
            return False
        first = frames[0]["t_ms"]
        return any(f["t_ms"] - first >= 1000 for f in frames)   # a frame after the initial burst

    r = await read_stream(client, f"{base}/api/telemetry/logs/stream", window_s=window_s, stop=stop,
                          accept_encoding=accept_encoding)
    frames = r.pop("frames")
    first = frames[0]["t_ms"] if frames else None
    post = [f for f in frames if first is not None and f["t_ms"] - first >= 1000]
    r.update(frames_total=len(frames), events=sum(f["kind"] == "event" for f in frames),
             heartbeats=sum(f["kind"] == "comment" for f in frames), frames_after_burst=len(post),
             first_post_burst_ms=post[0]["t_ms"] if post else None,
             sample=[(f.get("event") or f.get("comment") or "")[:40] for f in frames[:2]])
    problems = []
    if r["http_status"] != 200:
        problems.append(f"HTTP {r['http_status']}")
    if not (r["content_type"] or "").startswith("text/event-stream"):
        problems.append(f"content-type {r['content_type']}")
    if enc_problem := encoding_problem(r["content_encoding"]):
        problems.append(enc_problem)
    if r["first_byte_ms"] is None or r["first_byte_ms"] >= 2000:
        problems.append(f"first byte {r['first_byte_ms']} ms (budget < 2000)")
    if len(frames) < 2:
        problems.append(f"only {len(frames)} frames in {window_s:g}s")
    if not post:
        problems.append(f"no frame after the initial burst within {window_s:g}s (buffered or stalled)")
    if r.get("error"):
        problems.append(r["error"])
    return {"check": "sse_telemetry", "status": "PASS" if not problems else "FAIL", "problems": problems, **r}


async def check_ws_monitor(base: str, timeout_s: float = 5.0) -> dict[str, Any]:
    import websockets

    parts = urlsplit(base)
    url = f"{'wss' if parts.scheme == 'https' else 'ws'}://{parts.netloc}/api/monitor/ws/monitor"
    t0 = time.perf_counter()
    res: dict[str, Any] = {"check": "ws_monitor", "url": url, "connect_ms": None, "first_message": None,
                           "first_message_ms": None, "pong_ms": None, "messages": 0}
    problems: list[str] = []
    try:
        async with websockets.connect(url, open_timeout=timeout_s, close_timeout=2) as ws:
            res["connect_ms"] = _ms(t0)
            await ws.send(json.dumps({"action": "ping"}))
            async with asyncio.timeout(timeout_s):
                while res["pong_ms"] is None:
                    msg = await ws.recv()
                    res["messages"] += 1
                    if res["first_message"] is None:
                        res["first_message"], res["first_message_ms"] = str(msg)[:200], _ms(t0)
                    try:
                        if json.loads(msg).get("pong") is True:
                            res["pong_ms"] = _ms(t0)
                    except (ValueError, AttributeError):
                        problems.append(f"non-JSON message {str(msg)[:80]}")
    except TimeoutError:
        problems.append(f"no pong within {timeout_s:g}s")
    except Exception as exc:
        problems.append(f"{type(exc).__name__}: {exc}"[:300])
    if res["connect_ms"] is None and not problems:
        problems.append("not connected")
    return {**res, "status": "PASS" if not problems and res["pong_ms"] is not None else "FAIL", "problems": problems}


async def check_unknown_job_stream(client: httpx.AsyncClient, base: str, kind: str,
                                   accept_encoding: str = BROWSER_ACCEPT_ENCODING,
                                   release_wait_s: float = 3.0) -> dict[str, Any]:
    """``kind`` = 'ml' | 'rl'. ``release_wait_s``: pause before re-counting the proxy's upstream sockets."""
    url = f"{base}/api/pipeline/{kind}-stream/{UNKNOWN_JOB_ID}"
    port = urlsplit(base).port
    proxy_pid = listener_pid(port) if port and port != UPSTREAM_PORT else None
    before = upstream_conns(proxy_pid)

    during: dict[str, Any] = {}

    def stop(frames: list[dict[str, Any]]) -> bool:
        if any(f["kind"] == "comment" and "heartbeat" in f.get("comment", "") for f in frames):
            during["conns"] = upstream_conns(proxy_pid)
            return True
        return False

    r = await read_stream(client, url, window_s=8.0, stop=stop, accept_encoding=accept_encoding)
    frames = r.pop("frames")
    await asyncio.sleep(release_wait_s)    # give the proxy time to notice the client went away
    after = upstream_conns(proxy_pid)
    problems: list[str] = []
    outcome = "unknown"
    if r["http_status"] == 404:
        outcome = "clean 404"
    elif r["http_status"] == 200:
        first = frames[0] if frames else None
        status_payload: Any = None
        if first and first["kind"] == "event":
            try:
                status_payload = json.loads(first["data"])
            except ValueError:
                status_payload = first["data"]
        hb = next((f for f in frames if f["kind"] == "comment" and "heartbeat" in f.get("comment", "")), None)
        if enc_problem := encoding_problem(r["content_encoding"]):
            problems.append(enc_problem)
        if r["first_byte_ms"] is None or r["first_byte_ms"] >= 2000:
            problems.append(f"first byte {r['first_byte_ms']} ms (hang?)")
        if not (first and first["kind"] == "event" and first.get("event") == "status"):
            problems.append(f"first frame is not 'event: status': {first}")
        elif not (isinstance(status_payload, dict) and status_payload.get("status") == "pending"):
            problems.append(f"unexpected status payload {status_payload}")
        if hb is None:
            problems.append("no heartbeat within 8 s (stalled)")
        elif hb["t_ms"] > 6000:
            problems.append(f"first heartbeat at {hb['t_ms']} ms (> 6000)")
        outcome = ("pending stream + heartbeats (handler does not 404 unknown ids)" if frames else
                   f"HTTP 200 but no SSE frame decoded within 8 s ({r['raw_bytes']} bytes on the wire)")
        r["first_frame"] = first
        r["first_heartbeat_ms"] = hb["t_ms"] if hb else None
    else:
        problems.append(f"HTTP {r['http_status']} {r.get('error') or ''}".strip())
    lingering = None if before is None or after is None else after > before
    return {"check": f"{kind}_stream_unknown", "status": "PASS" if not problems else "FAIL", "problems": problems,
            "outcome": outcome, "job_id": UNKNOWN_JOB_ID, **r,
            "upstream_release": {"proxy_pid": proxy_pid, "conns_before": before, "conns_during": during.get("conns"),
                                 "conns_3s_after_close": after, "lingering": lingering,
                                 "note": "informational; other clients of the proxy can move these counts"}}


async def check_post_streams(client: httpx.AsyncClient, base: str) -> dict[str, Any]:
    rows, problems, warns = [], [], []
    for path in (*POST_ONLY_STREAMS, NEGATIVE_CONTROL):
        try:
            r = await client.get(f"{base}{path}", timeout=15)
            body = r.text[:300]
            try:
                js = r.json()
            except ValueError:
                js = None
            envelope = isinstance(js, dict) and "error" in js and "detail" in js
            answered_by = "ui-api (error envelope)" if envelope else ("front proxy" if r.status_code == 405 else "other")
            rows.append({"path": path, "status": r.status_code, "allow": r.headers.get("allow"),
                         "answered_by": answered_by, "body": body[:120]})
        except Exception as exc:
            rows.append({"path": path, "status": None, "error": f"{type(exc).__name__}: {exc}"[:200]})
    for row in rows:
        if row["path"] == NEGATIVE_CONTROL:
            if row["status"] != 404:
                problems.append(f"negative control {row['path']} → {row['status']} (expected 404)")
            continue
        if row["status"] == 405:
            if row.get("allow") and "POST" not in row["allow"].upper():
                problems.append(f"{row['path']} 405 but Allow={row['allow']}")
        elif row["status"] == 404 and row.get("answered_by", "").startswith("ui-api"):
            warns.append(f"{row['path']} → 404 envelope: route not provable by GET (catch-all outranks 405?)")
        else:
            problems.append(f"{row['path']} → {row['status']} (expected 405)")
    status = "FAIL" if problems else ("WARN" if warns else "PASS")
    return {"check": "post_streams_routable", "status": status, "problems": problems + warns, "rows": rows,
            "method": "GET only (never POST): method mismatch is rejected by the router before the handler runs"}


async def run_base(base: str, window_s: float, accept_encoding: str = BROWSER_ACCEPT_ENCODING) -> dict[str, Any]:
    base = base.rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=None)) as client:
        checks = [await check_sse_telemetry(client, base, window_s, accept_encoding), await check_ws_monitor(base),
                  await check_unknown_job_stream(client, base, "ml", accept_encoding),
                  await check_unknown_job_stream(client, base, "rl", accept_encoding),
                  await check_post_streams(client, base)]
    return {"base": base, "checks": checks, "ok": all(c["status"] != "FAIL" for c in checks)}


def render_markdown(report: dict[str, Any]) -> str:
    out = [f"# Stream checks — {report['meta']['started_at']}", ""]
    for b in report["bases"]:
        out += [f"## {b['base']}: {'PASS' if b['ok'] else 'FAIL'}", "", "| check | result | key facts | problems |",
                "|---|---|---|---|"]
        for c in b["checks"]:
            facts = _facts(c)
            out.append(f"| {c['check']} | {c['status']} | {facts} | {'; '.join(c['problems'])[:200] or '—'} |")
        out.append("")
    out.append(f"**Overall: {'PASS' if report['ok'] else 'FAIL'}**")
    return "\n".join(out) + "\n"


def _facts(c: dict[str, Any]) -> str:
    k = c["check"]
    enc = f" · content-encoding {c['content_encoding']}" if c.get("content_encoding") else ""
    if k == "sse_telemetry":
        return (f"HTTP {c.get('http_status')}{enc} · first byte {c.get('first_byte_ms')} ms · {c.get('frames_total')} frames "
                f"({c.get('events')} events, {c.get('heartbeats')} heartbeats) · first post-burst frame "
                f"{c.get('first_post_burst_ms')} ms")
    if k == "ws_monitor":
        return f"connect {c.get('connect_ms')} ms · first msg {c.get('first_message')!s:.40} · pong {c.get('pong_ms')} ms"
    if k.endswith("_stream_unknown"):
        u = c.get("upstream_release") or {}
        return (f"{c.get('outcome')}{enc} · first byte {c.get('first_byte_ms')} ms (wire {c.get('raw_first_byte_ms')} ms) "
                f"· heartbeat {c.get('first_heartbeat_ms')} ms"
                f" · upstream conns before/during/after {u.get('conns_before')}/{u.get('conns_during')}/"
                f"{u.get('conns_3s_after_close')}")
    if k == "post_streams_routable":
        return " · ".join(f"{r['path'].rsplit('/api/', 1)[-1]} {r.get('status')}" for r in c["rows"])
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SSE / WS / pipeline-stream / POST-stream checks through a base")
    ap.add_argument("--base", action="append", required=True, help="repeatable, e.g. http://localhost:3000")
    ap.add_argument("--sse-window", type=float, default=30.0, help="seconds to wait for continued SSE flow")
    ap.add_argument("--out", default=None, help="directory for streams.json + streams.md")
    ap.add_argument("--accept-encoding", default=BROWSER_ACCEPT_ENCODING,
                    help="Accept-Encoding for the stream GETs (default browser-like 'gzip, deflate'; 'identity' "
                         "= what curl/httpx-without-compression see)")
    args = ap.parse_args(argv)
    report: dict[str, Any] = {"meta": {"started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                                       "sse_window_s": args.sse_window, "unknown_job_id": UNKNOWN_JOB_ID,
                                       "accept_encoding": args.accept_encoding},
                              "bases": []}
    for base in args.base:   # sequential: one stream at a time against the live ui-api
        res = asyncio.run(run_base(base, args.sse_window, args.accept_encoding))
        report["bases"].append(res)
        for c in res["checks"]:
            print(f"{base:28} {c['check']:22} {c['status']:5} {_facts(c)[:150]} {'; '.join(c['problems'])[:160]}", flush=True)
    report["ok"] = all(b["ok"] for b in report["bases"])
    report["meta"]["finished_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "streams.json").write_text(json.dumps(report, indent=2, default=str))
        (out / "streams.md").write_text(render_markdown(report))
        print(f"report: {out / 'streams.md'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
