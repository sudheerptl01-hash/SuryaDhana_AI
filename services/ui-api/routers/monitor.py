from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import os
import threading
import time
import weakref
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from routers import live as _live   # the live NSE 'quotes' push channel (LV-API)

router = APIRouter()
log = logging.getLogger("ui-api.monitor")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUOTES_CHANNEL = "live.quotes"          # the Redis pub/sub channel the monitor socket forwards (tests use a quiet one)
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")


def _ws_cap_from_env() -> int:
    try:
        return max(1, int(os.environ.get("MONITOR_WS_MAX", "32")))
    except ValueError:
        return 32


# Concurrent monitor sockets are capped (desktop review C2-security-13; the Origin check itself is
# shared/http_guard.py). Since C2-performance-09 the sockets share ONE Redis subscription and one reader
# thread per process (_QuotesHub below), so a socket costs an asyncio task and a small queue; the cap still
# bounds them. The terminal opens one socket per window, so 32 leaves ample room. Over the cap the handshake
# is closed before accept: an ASGI test client sees close code 1013, a browser sees a refused handshake
# (uvicorn answers HTTP 403, close code 1006). The UI's wsManager reconnects with backoff either way.
MONITOR_WS_MAX = _ws_cap_from_env()
_ws_active = 0          # sockets being served (event-loop confined: only touched from coroutines)
_ws_refused_logged = 0.0


class SubscribeRequest(BaseModel):
    symbol: str


_REDIS_DOWN = ("Redis is not running at {url} — live quote streaming is disabled "
               "(watchlist itself is stored in the browser and is unaffected)")


def _redis_client():
    """Short timeouts so a missing/unreachable Redis fails in ~2 s, never hangs."""
    import redis
    return redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)


def _redis_call(fn):
    import redis
    try:
        return fn(_redis_client())
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=_REDIS_DOWN.format(url=REDIS_URL)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Sync handlers: redis-py is blocking I/O, so FastAPI runs these in its threadpool
# instead of stalling the event loop that serves every other UI request.
@router.post("/subscribe")
def subscribe(req: SubscribeRequest):
    _redis_call(lambda r: r.sadd("monitored.stocks", req.symbol.upper()))
    return {"ok": True, "symbol": req.symbol.upper()}


@router.post("/unsubscribe")
def unsubscribe(req: SubscribeRequest):
    _redis_call(lambda r: r.srem("monitored.stocks", req.symbol.upper()))
    return {"ok": True, "symbol": req.symbol.upper()}


@router.get("/list")
def list_monitored():
    members = _redis_call(lambda r: r.smembers("monitored.stocks")) or set()
    return {"symbols": [m.decode() if isinstance(m, bytes) else m for m in members]}


@router.get("/live/nifty")
async def get_live_nifty():
    """Proxy the latest NIFTY quote from the data-service into the UI API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{DATA_SVC}/live/index/nifty")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Data service request failed: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# Simple WebSocket that forwards Redis 'live.quotes' pubsub messages to connected clients.
# Clients can send a JSON message {"action":"subscribe","symbols":["RELIANCE","TCS"]}
# to limit which symbols they receive.

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        try:
            self.active.remove(ws)
        except ValueError:
            pass

    async def send_json(self, ws: WebSocket, data: Any):
        await ws.send_json(data)

    async def broadcast(self, data: Any):
        for ws in list(self.active):
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws/monitor")
async def ws_monitor(socket: WebSocket):
    global _ws_active, _ws_refused_logged
    if _ws_active >= MONITOR_WS_MAX:
        now = time.monotonic()
        if now - _ws_refused_logged >= 60.0:
            _ws_refused_logged = now
            log.warning(json.dumps({"event": "monitor.ws_refused", "reason": "cap", "cap": MONITOR_WS_MAX}))
        await socket.close(code=1013)
        return
    _ws_active += 1
    try:
        await _serve_monitor(socket)
    finally:
        _ws_active -= 1


class RedisUnavailable(ConnectionError):
    """Redis could not be reached; the message is the connection error's (shown to the socket as ``detail``)."""


def _probe_redis() -> None:
    """Blocking: one PING on a short-lived connection whose socket timeout is HANDSHAKE_TIMEOUT_S. A Redis that
    accepts TCP but never answers (SIGSTOP, swap storm, a long blocking command) then fails in about
    HANDSHAKE_TIMEOUT_S, instead of READ_STALL_S per joining socket (desktop review RAPI-01). The subscription
    itself keeps READ_STALL_S as its stall bound."""
    import redis as _redis
    pool = _redis.ConnectionPool.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=HANDSHAKE_TIMEOUT_S)
    try:
        _redis.Redis(connection_pool=pool).ping()
    finally:
        with contextlib.suppress(Exception):
            pool.disconnect()


def _open_quotes_pubsub():
    """Blocking: connect to Redis (fails fast if unreachable or unresponsive, see _probe_redis) and subscribe to
    QUOTES_CHANNEL. Runs in a worker thread; the returned pubsub then belongs to the hub's reader thread alone
    (see _QuotesHub).

    The pool is created explicitly. With redis.from_url() the client owns its pool (auto_close_connection_pool),
    so when this function returned and the client was garbage-collected, Redis.__del__ -> close() ->
    pool.disconnect() closed the pubsub's socket right after SUBSCRIBE: every round-1 socket started with a
    dead subscription that the first caller had to reconnect (part of the 14:42 hang, see _QuotesHub)."""
    import redis as _redis
    _probe_redis()
    pool = _redis.ConnectionPool.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=READ_STALL_S)
    pubsub = None
    try:
        client = _redis.Redis(connection_pool=pool)
        client.ping()
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(QUOTES_CHANNEL)          # reuses the PING's pooled connection: one connection per hub
    except Exception:
        _close_pubsub(pubsub, pool)
        raise
    return pubsub


def _decode_quote(raw: Any) -> dict[str, Any] | None:
    """A live.quotes payload as the dict the socket forwards (None = skip, exactly as before)."""
    if raw is None:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            decoded = json.loads(raw.decode())
        elif isinstance(raw, str):
            decoded = json.loads(raw)
        else:
            return None
    except (ValueError, RecursionError):        # not JSON / not UTF-8 / absurdly nested
        return None
    return decoded if isinstance(decoded, dict) else None


def _wants(subscribed: set[str], quote: dict[str, Any]) -> bool:
    """The per-socket symbol filter (unchanged): everything until the client subscribes, then its symbols."""
    if not subscribed:
        return True
    symbol = quote.get("symbol")
    try:
        return bool(symbol and symbol.upper() in subscribed)
    except (AttributeError, TypeError):         # a non-text symbol never matches a subscription
        return False


class _Subscriber:
    """One monitor socket's view of the hub: its symbol filter and a bounded outbox."""

    QUEUE_MAX = 256       # quotes waiting for a slow client; the oldest is dropped beyond this

    def __init__(self) -> None:
        self.subscribed: set[str] = set()
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.QUEUE_MAX)
        self.dropped = 0

    def offer(self, quote: dict[str, Any]) -> None:
        if not _wants(self.subscribed, quote):
            return
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(quote)


# Reader timing (see _QuotesHub). The reader waits at most READ_POLL_S for a message, so a stop request is
# honoured within that time; a message that starts arriving but stalls for READ_STALL_S ends the connection.
READ_POLL_S = 1.0
READ_STALL_S = 10.0
HANDSHAKE_TIMEOUT_S = 2.5          # the PING probe before subscribing (RAPI-01)
FAILED_JOIN_MEMORY_S = 2.0         # a failed connect is remembered this long: joins in between fail at once
MAX_SYMBOLS = 500                  # symbols one socket may subscribe to (RAPI-08)
LINGER_S = 15.0                    # keep the subscription this long after the last socket leaves (reloads)
RESTART_BACKOFF_S = (2.0, 5.0, 15.0, 30.0)


class _QuotesHub:
    """ONE Redis subscription to live.quotes and ONE reader thread per event loop, fanned out to every monitor
    socket (desktop review C2-performance-09; it used to be one Redis connection plus one thread per socket).

    Threading rule (root cause of the 25 Oct 14:40-14:48 ui-api hang): a redis-py connection is not thread-safe.
    In round 1 each socket had its own pubsub, opened by a worker thread with redis.from_url(); when that helper
    returned, the client was garbage-collected and Redis.__del__ closed its pool, so the pubsub's socket was
    already closed when the socket's reader thread entered listen(). Both the reader thread and, when the client
    left quickly, the event loop (the handler's finally: pubsub.unsubscribe() ran ON THE LOOP) then reconnected
    the SAME connection object at once. The loop sent the handshake and waited in a blocking recv() (no socket
    timeout) for a reply the reader thread consumed; on a quiet channel (Sunday, no ticks) nothing else ever
    arrived, so the event loop, and every HTTP request with it, hung until the restart. Reproduced in scratch with
    ~50 fast open/close cycles against the real Redis; faulthandler stacks: loop in _serve_monitor ->
    unsubscribe -> connect -> on_connect -> read_response -> recv, reader in listen -> read_response -> recv,
    the same native shape as the live sample. Now:
      * the pool is explicit, so the subscription survives the helper (see _open_quotes_pubsub);
      * no redis-py call ever runs on the event loop (connect and subscribe run in a worker thread);
      * after that, the pubsub belongs to its reader thread ALONE: it reads with get_message(timeout) (bounded,
        never the open-ended listen()), notices a stop request within READ_POLL_S, and closes the connection
        itself;
      * stopping is just setting an Event.

    The reader decodes each message once and hands it to the loop (call_soon_threadsafe); the loop puts it into
    the queue of each subscriber whose filter wants it, and each socket's sender task drains its own queue in
    order. The subscription opens with the first socket and closes LINGER_S after the last one leaves (a window
    reload reuses it). If Redis is down, join() raises and that socket gets {"error": "redis_unavailable"} as
    before. If the connection drops while sockets are open, the hub reconnects on its own with backoff
    (RESTART_BACKOFF_S) and the open sockets resume receiving quotes.

    Connecting is single flight (desktop review RAPI-01): sockets that join while a connect is running wait for
    THAT attempt (one shared task) instead of queueing behind the lock for an attempt each, so with a Redis that
    accepts TCP but never answers they all learn redis_unavailable after one HANDSHAKE_TIMEOUT_S probe instead of
    the k-th waiting k x READ_STALL_S. A failed attempt is remembered for FAILED_JOIN_MEMORY_S: joins in that
    window fail at once (they stay registered, and the reconnect task, which ignores the memory, brings them
    quotes when Redis is back)."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop_ref = weakref.ref(loop)          # weak: _hubs is keyed by the loop
        self.subscribers: set[_Subscriber] = set()
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._lock = asyncio.Lock()
        self._linger: asyncio.TimerHandle | None = None
        self._restart: asyncio.Task[None] | None = None
        self._connecting: asyncio.Task[None] | None = None
        self._failed_at: float | None = None
        self._failed_detail = ""
        self.connects = 0
        self.connect_attempts = 0

    @property
    def running(self) -> bool:
        return (self._thread is not None and self._thread.is_alive()
                and self._stop is not None and not self._stop.is_set())

    async def join(self, sub: _Subscriber) -> None:
        """Register ``sub``; start the subscription if it is not running. Raises if Redis is unreachable
        (``sub`` stays registered, so it receives quotes once the hub reconnects)."""
        self.subscribers.add(sub)
        if self._linger is not None:
            self._linger.cancel()
            self._linger = None
        try:
            await self._ensure_running()
        except Exception:
            self._schedule_reconnect()        # sockets that joined while Redis was down get quotes once it is back
            raise

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop_ref()

    async def _ensure_running(self, *, retry: bool = False) -> None:
        """Make sure the subscription runs; raise when Redis is unreachable. ``retry`` (the reconnect task)
        ignores the memory of a recent failure."""
        if self.running:
            return
        if (not retry and self._failed_at is not None
                and time.monotonic() - self._failed_at < FAILED_JOIN_MEMORY_S):
            raise RedisUnavailable(self._failed_detail)
        attempt = self._connecting
        if attempt is None or attempt.done():
            attempt = self._connecting = asyncio.get_running_loop().create_task(
                self._connect(), name="redis-quotes-hub-connect")
            attempt.add_done_callback(_mark_retrieved)
        # shield: a joiner that gives up (its client left) does not cancel the attempt the others wait for
        await asyncio.shield(attempt)

    async def _connect(self) -> None:
        async with self._lock:
            if self.running:
                return
            self.connect_attempts += 1
            try:
                pubsub = await asyncio.to_thread(_open_quotes_pubsub)
            except Exception as exc:
                self._failed_at, self._failed_detail = time.monotonic(), str(exc)
                raise
            self._failed_at = None
            self.connects += 1
            stop = threading.Event()
            thread = threading.Thread(target=self._read, args=(pubsub, stop), daemon=True, name="redis-quotes-hub")
            self._stop, self._thread = stop, thread
            thread.start()

    async def leave(self, sub: _Subscriber) -> None:
        self.subscribers.discard(sub)
        if self.subscribers:
            return
        if self._restart is not None:                 # nobody left to reconnect for
            self._restart.cancel()
            self._restart = None
        loop = self.loop
        if self._stop is None or loop is None:
            return
        if LINGER_S <= 0:
            self._stop_reader()
        elif self._linger is None:
            self._linger = loop.call_later(LINGER_S, self._linger_expired)

    def _linger_expired(self) -> None:
        self._linger = None
        if not self.subscribers:
            self._stop_reader()

    def _stop_reader(self) -> None:
        if self._stop is not None:
            self._stop.set()                 # the reader closes its own connection within READ_POLL_S
        self._stop = self._thread = None
        if self._restart is not None:
            self._restart.cancel()
            self._restart = None

    def _read(self, pubsub: Any, stop: threading.Event) -> None:
        """Reader thread: the only user of ``pubsub``. Bounded waits, one decode per message, hand-off to the loop."""
        dropped = False
        try:
            while not stop.is_set():
                message = pubsub.get_message(timeout=READ_POLL_S)
                loop = self.loop
                if loop is None or loop.is_closed():       # the server's loop ended (shutdown, test server)
                    break
                if message is None or stop.is_set():
                    continue
                quote = _decode_quote(message.get("data"))
                if quote is not None:
                    loop.call_soon_threadsafe(self._dispatch, quote)
        except Exception:  # noqa: BLE001 — any redis/socket error: the connection dropped
            dropped = not stop.is_set()
        finally:
            stop.set()
            _close_pubsub(pubsub)
            loop = self.loop
            if dropped and loop is not None:
                with contextlib.suppress(RuntimeError):          # the loop is closed at shutdown
                    loop.call_soon_threadsafe(self._reader_dropped, stop)

    def _reader_dropped(self, stop: threading.Event) -> None:
        """On the loop: the current reader lost Redis while sockets are open -> reconnect with backoff."""
        if stop is self._stop:
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        loop = self.loop
        if not self.subscribers or self._restart is not None or loop is None:
            return
        self._restart = loop.create_task(self._reconnect(), name="redis-quotes-hub-reconnect")

    async def _reconnect(self) -> None:
        try:
            for delay in itertools.chain(RESTART_BACKOFF_S, itertools.repeat(RESTART_BACKOFF_S[-1])):
                await asyncio.sleep(delay)
                if not self.subscribers:
                    return
                try:
                    await self._ensure_running(retry=True)
                except Exception as exc:  # noqa: BLE001 — Redis still down: try again after the next delay
                    log.info(json.dumps({"event": "monitor.hub_reconnect_failed", "error": type(exc).__name__,
                                         "retry_in_s": delay}))
                else:
                    log.warning(json.dumps({"event": "monitor.hub_reconnected"}))
                    return
        finally:
            if self._restart is asyncio.current_task():
                self._restart = None

    def _dispatch(self, quote: dict[str, Any]) -> None:
        for sub in list(self.subscribers):
            sub.offer(quote)


def _mark_retrieved(task: asyncio.Task[Any]) -> None:
    """A shared connect attempt's exception counts as retrieved even if every joiner already left."""
    if not task.cancelled():
        task.exception()


def _close_pubsub(pubsub: Any, pool: Any = None) -> None:
    """Close the connection and its pool (no UNSUBSCRIBE: it can reconnect and wait for a reply; Redis drops
    the subscription with the connection anyway). Called only by the pubsub's owner: the reader thread, or the
    worker thread that failed to open it."""
    if pubsub is not None:
        if pool is None:
            pool = getattr(pubsub, "connection_pool", None)
        with contextlib.suppress(Exception):
            pubsub.close()
    if pool is not None:
        with contextlib.suppress(Exception):
            pool.disconnect()


_hubs: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _QuotesHub] = weakref.WeakKeyDictionary()


def _hub() -> _QuotesHub:
    """The hub of the running loop (one in production; ASGI test clients may run one loop per socket)."""
    loop = asyncio.get_running_loop()
    hub = _hubs.get(loop)
    if hub is None:
        hub = _hubs[loop] = _QuotesHub(loop)
    return hub


def _symbols(raw: Any) -> list[str] | None:
    """A subscribe/unsubscribe ``symbols`` value as upper-case symbols: missing/null = none; a list keeps its
    text entries (at most MAX_SYMBOLS); anything else is not a valid request (None)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    return [s.upper() for s in raw[:MAX_SYMBOLS] if isinstance(s, str)]


async def _send_quotes(socket: WebSocket, sub: _Subscriber) -> None:
    """Drain this socket's outbox in order. A failed send (the client is gone) ends the task; the receive loop
    in _serve_monitor ends with the disconnect and cleans up."""
    while True:
        quote = await sub.queue.get()
        try:
            await manager.send_json(socket, quote)
        except Exception:  # noqa: BLE001 — WebSocketDisconnect, ConnectionClosed, RuntimeError after close
            return


async def _serve_monitor(socket: WebSocket):
    await manager.connect(socket)
    sub = _Subscriber()
    hub = _hub()
    sender: asyncio.Task[None] | None = None
    quotes_ch: Any = None          # the live 'quotes' channel (routers/live.py), made on its first subscribe
    # Everything after accept runs inside this try, so every exit path (including a client that left while
    # Redis was being reached, which made the redis_unavailable send raise) releases the socket's entries.
    try:
        try:
            await hub.join(sub)
        except Exception as exc:
            # Redis unavailable — WebSocket still works but no live quotes
            await socket.send_json({"error": "redis_unavailable", "detail": str(exc)})
        sender = asyncio.create_task(_send_quotes(socket, sub), name="monitor-ws-sender")

        while True:
            msg = await socket.receive_text()
            try:
                payload = json.loads(msg)
            except Exception:
                continue
            # RAPI-08: any JSON value can arrive; only an object with a list of text symbols is a request
            if not isinstance(payload, dict):
                await manager.send_json(socket, {"error": "bad_message"})
                continue
            action = payload.get("action")
            if action in ("ping", "heartbeat"):
                await manager.send_json(socket, {"pong": True})
            elif action in ("subscribe", "unsubscribe") and payload.get("channel") == "quotes":
                # live NSE quotes push (routers/live.py, LV-API): one poll loop per process for the union of every
                # socket's symbols, this socket's own bounded outbox (drop-oldest, counted); the Redis filter is untouched
                if quotes_ch is None:
                    quotes_ch = _live.QuotesChannel(lambda msg: manager.send_json(socket, msg))
                await manager.send_json(socket, await quotes_ch.handle(payload))
            elif action in ("subscribe", "unsubscribe"):
                syms = _symbols(payload.get("symbols"))
                if syms is None:
                    await manager.send_json(socket, {"error": "bad_message", "action": action})
                elif action == "subscribe":
                    sub.subscribed = set(syms)
                    await manager.send_json(socket, {"ok": True, "subscribed": list(sub.subscribed)})
                else:
                    sub.subscribed = set(sub.subscribed) - set(syms)
                    await manager.send_json(socket, {"ok": True, "subscribed": list(sub.subscribed)})
            else:
                shown = action if isinstance(action, str) and len(action) <= 64 else None
                await manager.send_json(socket, {"error": "unknown_action", "action": shown})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(socket)
        if quotes_ch is not None:
            await quotes_ch.close()
        if sender is not None:
            sender.cancel()
            with contextlib.suppress(BaseException):
                await sender
        await hub.leave(sub)


# (dead route /embed removed — Bloomberg program F1.5; the UI builds its own TradingView
#  embeds client-side and never called this)
