"""Regression test for the 25 Oct 2026 14:40-14:48 ui-api hang: monitor WebSocket churn must never block the
event loop.

What happened: about 50 /api/monitor/ws/monitor sockets were opened and closed in bursts through a QA relay.
The round-1 handler called pubsub.unsubscribe() ON THE EVENT LOOP while that socket's reader thread was inside
listen() on the same redis-py connection; unsubscribe() reconnected and waited in a blocking recv() for a reply
the reader thread had taken, and on a quiet channel (Sunday, no ticks) nothing else ever arrived. Every HTTP
request, /health included, hung until the restart. See routers/monitor.py (_QuotesHub) for the fix.

This test runs the real monitor router under a real uvicorn server (same loop implementation as production) in
a thread, against an in-process Redis stand-in speaking RESP over TCP, so redis-py does real socket I/O. The
channel is quiet: no quote is published during the churn. 60 sockets are opened and closed the ways a relay and
browser close them (straight away without a close frame, TCP reset, after a ping, after a subscribe), 16 at a
time, while /health is polled every 20 ms. /health must answer every probe in under 100 ms. Afterwards no
socket, subscriber or Redis connection is left behind and a new socket still receives quotes.

Negative control: with the round-1 routers/monitor.py swapped in, the probes time out (the loop is stuck in
recv) and this test fails.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import http.client
import json
import os
import random
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import monitor as mon

WS_PATH = "/api/monitor/ws/monitor"
CHANNEL = f"test.quiet.{os.getpid()}"
HEALTH_BUDGET_S = 0.100


# ── a minimal Redis (RESP2) on 127.0.0.1: enough for redis-py's connect, PING, SUBSCRIBE and PUBLISH ─────────

def _bulk(b: bytes | None) -> bytes:
    return b"$-1\r\n" if b is None else b"$%d\r\n%s\r\n" % (len(b), b)


class FakeRedisServer:
    """Runs its own asyncio loop in a thread. Answers like Redis for the commands redis-py sends here; counts the
    open client connections so the test can prove none leak."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.subscribers: dict[bytes, set[asyncio.StreamWriter]] = {}
        self.open_connections = 0
        self.total_connections = 0
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="fake-redis")
        self.port = 0

    def start(self) -> FakeRedisServer:
        self._thread.start()
        assert self._ready.wait(5), "fake redis did not start"
        return self

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        server = self.loop.run_until_complete(asyncio.start_server(self._client, "127.0.0.1", 0))
        self.port = server.sockets[0].getsockname()[1]
        self._ready.set()
        self.loop.run_forever()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.open_connections += 1
        self.total_connections += 1
        mine: set[bytes] = set()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                if not line.startswith(b"*"):
                    continue                                   # inline commands are not used by redis-py
                args = []
                for _ in range(int(line[1:])):
                    size = int((await reader.readline())[1:])
                    args.append((await reader.readexactly(size + 2))[:-2])
                writer.write(self._reply(args, writer, mine))
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            return
        finally:
            for ch in mine:
                self.subscribers.get(ch, set()).discard(writer)
            self.open_connections -= 1
            with contextlib.suppress(Exception):
                writer.close()

    def _reply(self, args: list[bytes], writer: asyncio.StreamWriter, mine: set[bytes]) -> bytes:
        cmd = args[0].upper()
        if cmd == b"PING":
            return b"+PONG\r\n"
        if cmd == b"HELLO":
            return b"-ERR unknown command 'HELLO'\r\n"
        if cmd == b"SUBSCRIBE":
            out = b""
            for ch in args[1:]:
                mine.add(ch)
                self.subscribers.setdefault(ch, set()).add(writer)
                out += b"*3\r\n" + _bulk(b"subscribe") + _bulk(ch) + b":%d\r\n" % len(mine)
            return out
        if cmd == b"UNSUBSCRIBE":
            chans = args[1:] or sorted(mine) or [None]
            out = b""
            for ch in chans:
                if ch is not None:
                    mine.discard(ch)
                    self.subscribers.get(ch, set()).discard(writer)
                out += b"*3\r\n" + _bulk(b"unsubscribe") + _bulk(ch) + b":%d\r\n" % len(mine)
            return out
        if cmd == b"PUBLISH":
            ch, data = args[1], args[2]
            targets = list(self.subscribers.get(ch, ()))
            for w in targets:
                w.write(b"*3\r\n" + _bulk(b"message") + _bulk(ch) + _bulk(data))
            return b":%d\r\n" % len(targets)
        return b"+OK\r\n"                                    # CLIENT SETINFO, SELECT, ...

    def publish(self, channel: str, data: bytes) -> int:
        """PUBLISH from the test thread; returns the number of subscribers it reached."""
        async def _pub() -> int:
            reply = self._reply([b"PUBLISH", channel.encode(), data], None, set())  # type: ignore[arg-type]
            return int(reply[1:-2])
        return asyncio.run_coroutine_threadsafe(_pub(), self.loop).result(5)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


# ── the server under test: the real router + an async /health on uvicorn, in a thread ────────────────────────

class ServerThread:
    def __init__(self) -> None:
        app = FastAPI()
        app.include_router(mon.router, prefix="/api/monitor")

        @app.get("/health")
        async def health() -> dict[str, Any]:            # async on purpose: it answers only if the loop is free
            return {"ok": True}

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        config = uvicorn.Config(app, lifespan="off", log_level="warning", loop="auto", ws="auto")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True,
                                       name="uvicorn-under-test")

    def start(self) -> ServerThread:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert time.monotonic() < deadline, "uvicorn did not start"
            time.sleep(0.01)
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(5)                              # a hung loop never exits; the thread is a daemon


# ── a raw WebSocket client: full control over how the socket goes away ────────────────────────────────────────

def _ws_open(port: int) -> socket.socket:
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {WS_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = s.recv(4096)
        if not chunk:
            raise ConnectionError("closed during handshake")
        head += chunk
    if not head.startswith(b"HTTP/1.1 101"):
        raise ConnectionError(head.split(b"\r\n", 1)[0].decode())
    return s


def _ws_send(s: socket.socket, payload: dict[str, Any] | None, opcode: int = 0x1) -> None:
    data = b"" if payload is None else json.dumps(payload).encode()
    mask = os.urandom(4)
    header = bytes([0x80 | opcode]) + (bytes([0x80 | len(data)]) if len(data) < 126
                                       else bytes([0x80 | 126]) + struct.pack("!H", len(data)))
    s.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def _ws_recv(s: socket.socket) -> dict[str, Any]:
    def exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf
    b0, b1 = exact(2)
    size = b1 & 0x7F
    if size == 126:
        size = struct.unpack("!H", exact(2))[0]
    elif size == 127:
        size = struct.unpack("!Q", exact(8))[0]
    data = exact(size)
    if b0 & 0x0F != 0x1:
        raise ConnectionError(f"opcode {b0 & 0x0F}")
    return json.loads(data)


def _reset(s: socket.socket) -> None:
    """Close with a TCP reset (no close frame, no FIN): what a killed tab or relay does."""
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()


def _one_cycle(port: int, i: int) -> str:
    s = _ws_open(port)
    mode = i % 4
    try:
        if mode == 0:
            s.close()                                    # gone straight after the handshake, before any message
        elif mode == 1:
            _reset(s)
        elif mode == 2:
            _ws_send(s, {"action": "ping"})
            assert _ws_recv(s) == {"pong": True}
            _ws_send(s, None, opcode=0x8)                # a proper close frame
            s.close()
        else:
            _ws_send(s, {"action": "subscribe", "symbols": ["NIFTY"]})
            assert _ws_recv(s)["subscribed"] == ["NIFTY"]
            time.sleep(random.uniform(0.02, 0.15))
            _reset(s)
        return "ok"
    finally:
        with contextlib.suppress(OSError):
            s.close()


class HealthProbe(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True, name="health-probe")
        self.port = port
        self.latencies: list[float] = []
        self.errors: list[str] = []
        self.done = threading.Event()

    def run(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        while not self.done.is_set():
            t0 = time.perf_counter()
            try:
                conn.request("GET", "/health")
                resp = conn.getresponse()
                resp.read()
                assert resp.status == 200
                self.latencies.append(time.perf_counter() - t0)
            except Exception as exc:  # noqa: BLE001 — every failure is a finding
                self.errors.append(f"{type(exc).__name__} after {time.perf_counter() - t0:.2f}s")
                conn.close()
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
                if len(self.errors) >= 3:
                    return                               # the loop is stuck: no point waiting longer
            time.sleep(0.02)
        conn.close()


def _wait(cond, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


@pytest.fixture
def fake_redis() -> FakeRedisServer:
    srv = FakeRedisServer().start()
    yield srv
    srv.stop()


@pytest.mark.parametrize("linger_s", [0.0, 15.0], ids=["subscription-per-burst", "production-linger"])
def test_monitor_socket_churn_on_a_quiet_channel_keeps_health_fast(
        fake_redis: FakeRedisServer, monkeypatch: pytest.MonkeyPatch, linger_s: float) -> None:
    monkeypatch.setattr(mon, "REDIS_URL", f"redis://127.0.0.1:{fake_redis.port}/0")
    monkeypatch.setattr(mon, "QUOTES_CHANNEL", CHANNEL, raising=False)
    monkeypatch.setattr(mon, "LINGER_S", linger_s, raising=False)
    monkeypatch.setattr(mon, "_ws_active", 0)
    mon.manager.active.clear()

    srv = ServerThread().start()
    probe = HealthProbe(srv.port)
    probe.start()
    try:
        time.sleep(0.2)                                  # a few probes before the churn
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda i: _safe_cycle(srv.port, i), range(60)))
        time.sleep(0.3)                                  # and a few after it
        probe.done.set()
        probe.join(5)

        assert probe.errors == [], f"/health failed during the churn (event loop blocked?): {probe.errors[:3]}"
        assert len(probe.latencies) >= 15, len(probe.latencies)
        worst = max(probe.latencies)
        assert worst < HEALTH_BUDGET_S, f"/health took {worst * 1000:.0f} ms during the churn"
        assert results.count("ok") == 60, results

        assert _wait(lambda: mon._ws_active == 0 and mon.manager.active == []), (mon._ws_active, mon.manager.active)
        if linger_s == 0.0:                              # every subscription closed with its last socket
            assert _wait(lambda: fake_redis.open_connections == 0), fake_redis.open_connections
        else:                                            # one subscription served the whole churn
            # 2 = the short-timeout PING probe (closed at once, RAPI-01) + the one subscription
            assert fake_redis.open_connections <= 1 and fake_redis.total_connections == 2, \
                (fake_redis.open_connections, fake_redis.total_connections)

        s = _ws_open(srv.port)                           # the feed still works after the churn
        try:
            _ws_send(s, {"action": "subscribe", "symbols": ["RELIANCE"]})
            assert _ws_recv(s)["subscribed"] == ["RELIANCE"]
            quote = {"symbol": "RELIANCE", "ts": 1, "payload": {"ltp": 2950.5}}
            assert _wait(lambda: fake_redis.publish(CHANNEL, json.dumps(quote).encode()) >= 1)
            assert _ws_recv(s) == quote
        finally:
            _reset(s)
    finally:
        probe.done.set()
        srv.stop()
        _wait(lambda: not [t for t in threading.enumerate() if t.name == "redis-quotes-hub"])   # tidy for others


def _safe_cycle(port: int, i: int) -> str:
    try:
        return _one_cycle(port, i)
    except Exception as exc:  # noqa: BLE001 — reported through the results list
        return f"{type(exc).__name__}: {exc}"
