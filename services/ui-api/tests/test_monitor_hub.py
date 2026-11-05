"""Monitor WebSocket fan-out (desktop review C2-performance-09) and the redis_unavailable cleanup path (fix
round 1 adversarial check on C2-security-13).

Every socket used to open its own Redis pubsub connection and its own reader thread. Now one subscription and
one reader thread per process feed every socket. These tests run the real router on a small FastAPI app with a
fake pubsub (no Redis) inside ONE TestClient portal, so every socket shares one event loop as under uvicorn.

The fake also enforces the threading rule behind the 25 Oct ui-api hang (see _QuotesHub): after the worker
thread that opens it, a pubsub is touched by its reader thread ONLY, never by the event loop or a second
thread. The end-to-end churn test over real sockets is test_monitor_churn.py.
"""
from __future__ import annotations

import asyncio
import json
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import monitor as mon

WS = "/api/monitor/ws/monitor"


class FakePubSub:
    """get_message(timeout) like redis-py's (None when nothing arrived in time), fed from a thread-safe queue.
    Records every thread that touches it (the round-1 hang was two threads on one connection)."""

    def __init__(self) -> None:
        self.q: queue.Queue[Any] = queue.Queue()
        self.closed = threading.Event()
        self.users: set[str] = set()

    def _touch(self) -> None:
        self.users.add(threading.current_thread().name)

    def publish(self, data: Any) -> None:            # test side: the "Redis server" publishing
        self.q.put({"type": "message", "channel": b"live.quotes", "data": data})

    def drop(self) -> None:
        self.q.put(ConnectionError("connection lost"))

    def get_message(self, timeout: float = 0.0) -> Any:
        self._touch()
        if self.closed.is_set():
            raise ConnectionError("closed")
        try:
            item = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item, BaseException):
            raise item
        return item

    def unsubscribe(self, *args: Any) -> None:       # must never be called: it can reconnect and block
        self._touch()
        raise AssertionError("unsubscribe() called")

    def close(self) -> None:
        self._touch()
        self.closed.set()


class FakeRedis:
    def __init__(self) -> None:
        self.opened: list[FakePubSub] = []
        self.down = False

    def open(self) -> FakePubSub:
        if self.down:
            raise ConnectionError("Error 61 connecting to localhost:6379. Connection refused.")
        ps = FakePubSub()
        self.opened.append(ps)
        return ps


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(mon, "_open_quotes_pubsub", fake.open)
    monkeypatch.setattr(mon, "_ws_active", 0)
    monkeypatch.setattr(mon, "READ_POLL_S", 0.02)            # fast stop for the tests (production: 1 s)
    monkeypatch.setattr(mon, "LINGER_S", 0.0)                # close with the last socket unless a test lingers
    monkeypatch.setattr(mon, "RESTART_BACKOFF_S", (0.05,))
    mon.manager.active.clear()
    yield fake
    for ps in fake.opened:
        ps.closed.set()


def _only_its_reader_touched(ps: FakePubSub) -> None:
    assert ps.users <= {"redis-quotes-hub"}, ps.users


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(mon.router, prefix="/api/monitor")
    with TestClient(app) as c:          # one portal = one event loop for every socket (as under uvicorn)
        yield c


def _quote(symbol: str, price: float) -> bytes:
    return json.dumps({"symbol": symbol, "ts": 1, "payload": {"ltp": price}}).encode()


def _readers() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "redis-quotes-hub" and t.is_alive()]


def _wait(cond, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.01)


def test_sockets_share_one_subscription_and_one_reader_thread(client: TestClient, redis: FakeRedis) -> None:
    with client.websocket_connect(WS) as a, client.websocket_connect(WS) as b, client.websocket_connect(WS) as c:
        for ws in (a, b, c):                                      # wait until each socket is registered
            ws.send_json({"action": "ping"})
            assert ws.receive_json() == {"pong": True}
        assert len(redis.opened) == 1 and len(_readers()) == 1
        redis.opened[0].publish(_quote("RELIANCE", 2950.5))
        for ws in (a, b, c):
            assert ws.receive_json() == {"symbol": "RELIANCE", "ts": 1, "payload": {"ltp": 2950.5}}
    _wait(lambda: redis.opened[0].closed.is_set())                # the last socket closed the subscription
    _wait(lambda: not _readers())
    assert mon.manager.active == [] and mon._ws_active == 0
    _only_its_reader_touched(redis.opened[0])


def test_a_reload_within_the_linger_reuses_the_subscription(
        client: TestClient, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mon, "LINGER_S", 0.3)
    with client.websocket_connect(WS) as ws:
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"pong": True}
    with client.websocket_connect(WS) as ws:                      # the window reloaded
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"pong": True}
        assert len(redis.opened) == 1 and not redis.opened[0].closed.is_set()
    _wait(lambda: redis.opened[0].closed.is_set())                # closed LINGER_S after the last socket
    _wait(lambda: not _readers())
    _only_its_reader_touched(redis.opened[0])


def test_fast_open_close_churn_never_touches_the_pubsub_off_its_reader(client: TestClient, redis: FakeRedis) -> None:
    """The 14:40 trigger: ~50 sockets opened and closed in bursts (some before their first message)."""
    for i in range(60):
        with client.websocket_connect(WS) as ws:
            if i % 3 == 0:
                ws.send_json({"action": "ping"})
                assert ws.receive_json() == {"pong": True}
    _wait(lambda: not _readers())
    assert redis.opened and all(ps.closed.is_set() for ps in redis.opened)
    for ps in redis.opened:
        _only_its_reader_touched(ps)
    assert mon.manager.active == [] and mon._ws_active == 0


def test_symbol_filters_stay_per_socket(client: TestClient, redis: FakeRedis) -> None:
    with client.websocket_connect(WS) as tcs_only, client.websocket_connect(WS) as everything:
        tcs_only.send_json({"action": "subscribe", "symbols": ["tcs"]})
        assert tcs_only.receive_json() == {"ok": True, "subscribed": ["TCS"]}
        everything.send_json({"action": "ping"})
        assert everything.receive_json() == {"pong": True}
        ps = redis.opened[0]
        ps.publish(_quote("RELIANCE", 1.0))
        ps.publish(b"not json")                                    # skipped, as before
        ps.publish(json.dumps({"symbol": 7, "ts": 1}).encode())    # non-text symbol: only unfiltered sockets
        ps.publish(_quote("TCS", 2.0))
        assert everything.receive_json()["symbol"] == "RELIANCE"
        assert everything.receive_json()["symbol"] == 7
        assert everything.receive_json()["symbol"] == "TCS"
        assert tcs_only.receive_json()["symbol"] == "TCS"          # RELIANCE and 7 were filtered out
        tcs_only.send_json({"action": "unsubscribe", "symbols": ["TCS"]})
        assert tcs_only.receive_json() == {"ok": True, "subscribed": []}


def test_a_dropped_connection_reconnects_on_its_own(client: TestClient, redis: FakeRedis) -> None:
    with client.websocket_connect(WS) as first:
        first.send_json({"action": "ping"})
        assert first.receive_json() == {"pong": True}
        redis.opened[0].drop()                                     # Redis went away mid-stream
        _wait(lambda: len(redis.opened) == 2 and len(_readers()) == 1)   # backoff, then a new subscription
        redis.opened[1].publish(_quote("INFY", 1500.0))
        assert first.receive_json()["symbol"] == "INFY"            # the open socket resumes without a reload
        with client.websocket_connect(WS) as second:
            second.send_json({"action": "ping"})
            assert second.receive_json() == {"pong": True}
            assert len(redis.opened) == 2 and len(_readers()) == 1
            redis.opened[1].publish(_quote("TCS", 1.0))
            assert second.receive_json()["symbol"] == "TCS"
            assert first.receive_json()["symbol"] == "TCS"
    _wait(lambda: not _readers())
    for ps in redis.opened:
        _only_its_reader_touched(ps)


def test_sockets_opened_while_redis_was_down_get_quotes_once_it_is_back(client: TestClient, redis: FakeRedis) -> None:
    redis.down = True
    with client.websocket_connect(WS) as ws:
        assert ws.receive_json()["error"] == "redis_unavailable"
        redis.down = False                                         # Redis started
        _wait(lambda: len(redis.opened) == 1 and len(_readers()) == 1)
        redis.opened[0].publish(_quote("SBIN", 800.0))
        assert ws.receive_json()["symbol"] == "SBIN"
    _wait(lambda: not _readers())


def test_redis_down_keeps_the_socket_usable_and_releases_everything(client: TestClient, redis: FakeRedis) -> None:
    redis.down = True
    with client.websocket_connect(WS) as ws:
        msg = ws.receive_json()
        assert msg["error"] == "redis_unavailable" and "Connection refused" in msg["detail"]
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"pong": True}
    _wait(lambda: mon._ws_active == 0)
    assert mon.manager.active == [] and redis.opened == []


class _GoneSocket:
    """A client that left while Redis was being reached: every send raises (Starlette raises after close)."""

    def __init__(self) -> None:
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: Any) -> None:
        raise RuntimeError('Cannot call "send" once a close message has been sent.')

    async def receive_text(self) -> str:
        raise WebSocketDisconnect(1001)


def test_redis_unavailable_send_failure_does_not_leak(redis: FakeRedis) -> None:
    """Fix-round-1 note: the redis_unavailable send sat outside the try/finally, so a client that had already
    left kept its manager entry forever."""
    redis.down = True
    sock = _GoneSocket()

    async def scenario() -> None:
        with pytest.raises(RuntimeError):
            await mon._serve_monitor(sock)                         # type: ignore[arg-type]
        hub = mon._hub()
        assert hub.subscribers == set()
    asyncio.run(scenario())
    assert sock.accepted and mon.manager.active == []


def test_slow_clients_lose_the_oldest_quotes_not_memory() -> None:
    async def scenario() -> None:
        sub = mon._Subscriber()
        for i in range(sub.QUEUE_MAX + 10):
            sub.offer({"symbol": "X", "i": i})
        assert sub.queue.qsize() == sub.QUEUE_MAX and sub.dropped == 10
        assert sub.queue.get_nowait()["i"] == 10                  # the 10 oldest were dropped
    asyncio.run(scenario())
