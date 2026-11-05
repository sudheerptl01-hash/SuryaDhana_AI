"""The 'quotes' push channel (routers/live.py, LV-API; R-ARCH fix 7): ONE poll loop per process for the union of every
socket's symbols through the shared hub (one data-service batch per round, never one per socket), a bounded per-socket
outbox that drops the oldest message and counts it (a slow client never holds the others back), changed rows only with
a full snapshot every PUSH_FULL_EVERY_S, and the monitor socket's ``{"action": "subscribe", "channel": "quotes"}``
wiring (the last test runs once the routers/monitor.py patch request is applied; it skips, saying so, before)."""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any

import pytest
import test_live_support as sup
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import live
from routers import monitor as mon


@pytest.fixture
def clock() -> sup.Clock:
    return sup.Clock()


@pytest.fixture
def ds(monkeypatch: pytest.MonkeyPatch, clock: sup.Clock) -> sup.FakeDataService:
    fake = sup.install(monkeypatch, clock=clock)
    fake.rows = {"RELIANCE": sup.row(1311.0), "TCS": sup.row(3050.0, state="delayed", source="nse_api", age_s=49.0),
                 "INFY": sup.row(1490.0)}
    return fake


def _payload(**rows: dict[str, Any]) -> dict[str, Any]:
    return {"as_of": "2026-11-05T11:00:00+05:30", "market": {"state": "open", "session_date": "2026-11-05"},
            "quotes": rows}


def test_a_full_outbox_drops_the_oldest_counts_it_and_resends_everything_next() -> None:
    async def go() -> None:
        c = live.PushClient(queue_max=2)
        for i in range(5):
            c.offer({"n": i})
        assert c.queue.qsize() == 2 and c.dropped == 3
        assert [c.queue.get_nowait()["n"], c.queue.get_nowait()["n"]] == [3, 4]
        c.set_symbols(["A"])
        c.feed(_payload(A={"price": 1.0}), now=100.0)
        c.queue.get_nowait()
        c.feed(_payload(A={"price": 1.0}), now=101.0)            # unchanged inside the full window: nothing
        assert c.queue.empty()
        c.offer({"n": 9})
        c.offer({"n": 10})
        c.offer({"n": 11})                                     # a drop forces the next round to be a full snapshot
        while not c.queue.empty():
            c.queue.get_nowait()
        c.feed(_payload(A={"price": 1.0}), now=102.0)
        msg = c.queue.get_nowait()
        assert msg["full"] is True and msg["dropped"] == 4 and msg["quotes"] == {"A": {"price": 1.0}}
    asyncio.run(go())


def test_changed_rows_only_and_a_full_snapshot_every_n_seconds() -> None:
    async def go() -> list[dict[str, Any]]:
        c = live.PushClient()
        c.set_symbols(["A", "B"])
        c.feed(_payload(A={"price": 1.0}, B={"price": 2.0}), now=0.0)
        c.feed(_payload(A={"price": 1.5}, B={"price": 2.0}), now=2.0)
        c.feed(_payload(A={"price": 1.5}, B={"price": 2.0}), now=4.0)
        c.feed(_payload(A={"price": 1.5}, B={"price": 2.0}), now=10.5)
        return [c.queue.get_nowait() for _ in range(c.queue.qsize())]
    msgs = asyncio.run(go())
    assert [(m["full"], sorted(m["quotes"])) for m in msgs] == [(True, ["A", "B"]), (False, ["A"]), (True, ["A", "B"])]
    assert msgs[1]["type"] == "quotes" and msgs[1]["channel"] == "quotes" and msgs[1]["market"]["state"] == "open"


def test_one_data_service_batch_per_round_for_the_union_of_every_socket(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    def advancing_hub() -> live.LiveQuotesHub:
        clock.t += 2.5                                         # every round is past the 2 s window: a real refresh
        return live.hub()

    async def go() -> tuple[live.PushClient, live.PushClient, live.QuotesPush]:
        push = live.QuotesPush(advancing_hub, interval_s=0.005)
        a, b = live.PushClient(), live.PushClient()
        a.set_symbols(["RELIANCE", "TCS"])
        b.set_symbols(["TCS", "INFY"])
        push.add(a)
        push.add(b)
        for _ in range(200):
            await asyncio.sleep(0.005)
            if push.rounds >= 4:
                break
        push.remove(a)
        push.remove(b)
        await asyncio.sleep(0.02)
        return a, b, push
    a, b, push = asyncio.run(go())
    calls = ds.quote_calls()
    assert push.rounds >= 4 and len(calls) == push.rounds, (len(calls), push.rounds)
    assert all(sorted(c) == ["INFY", "RELIANCE", "TCS"] for c in calls)
    first_a, first_b = a.queue.get_nowait(), b.queue.get_nowait()
    assert sorted(first_a["quotes"]) == ["RELIANCE", "TCS"] and sorted(first_b["quotes"]) == ["INFY", "TCS"]
    assert not push.stats()["running"]                        # the loop ends with the last client


def test_negative_control_one_hub_per_socket_would_double_the_batches(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    async def go() -> None:
        for syms in (["RELIANCE", "TCS"], ["TCS", "INFY"]):          # what per-socket polling would do each round
            clock.t += 2.5
            await live.hub().quotes(syms)
    asyncio.run(go())
    assert len(ds.quote_calls()) == 2                          # vs 1 per round above


def test_the_channel_validates_subscribes_pumps_and_closes(ds: sup.FakeDataService) -> None:
    sent: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def go() -> list[dict[str, Any]]:
        ch = live.QuotesChannel(send, live.QuotesPush(interval_s=0.005))
        replies = [await ch.handle({"action": "subscribe", "channel": "quotes", "symbols": "RELIANCE"}),
                   await ch.handle({"action": "subscribe", "channel": "quotes", "symbols": ["BAD SYM!"]}),
                   await ch.handle({"action": "subscribe", "channel": "quotes", "symbols": ["reliance.ns", "TCS"]})]
        for _ in range(100):
            await asyncio.sleep(0.005)
            if sent:
                break
        replies.append(await ch.handle({"action": "unsubscribe", "channel": "quotes", "symbols": ["TCS"]}))
        replies.append(await ch.handle({"action": "bogus", "channel": "quotes"}))
        replies.append(await ch.handle({"action": "unsubscribe", "channel": "quotes"}))
        await ch.close()
        return replies
    r = asyncio.run(go())
    assert r[0]["error"] == "bad_message" and r[1]["error"] == "bad_message" and "BAD SYM!" in r[1]["detail"]
    assert r[2] == {"ok": True, "channel": "quotes", "subscribed": ["RELIANCE", "TCS"], "interval_s": 0.005}
    assert r[3]["subscribed"] == ["RELIANCE"] and r[4]["error"] == "unknown_action" and r[5]["subscribed"] == []
    assert sent and sent[0]["type"] == "quotes" and sorted(sent[0]["quotes"]) == ["RELIANCE", "TCS"]
    assert sent[0]["quotes"]["RELIANCE"]["source"] == "breeze_ws"


def test_a_slow_socket_never_holds_back_the_others(ds: sup.FakeDataService, clock: sup.Clock) -> None:
    fast: list[dict[str, Any]] = []

    async def go() -> live.QuotesChannel:
        stuck = asyncio.Event()

        async def slow_send(msg: dict[str, Any]) -> None:
            await stuck.wait()                                  # a client that never reads

        async def fast_send(msg: dict[str, Any]) -> None:
            fast.append(msg)

        def advancing_hub() -> live.LiveQuotesHub:
            clock.t += 2.5
            ds.rows["RELIANCE"] = sup.row(1311.0 + clock.t / 1000)     # a new price every round
            return live.hub()
        push = live.QuotesPush(advancing_hub, interval_s=0.002)
        slow, quick = live.QuotesChannel(slow_send, push), live.QuotesChannel(fast_send, push)
        slow.client.queue = asyncio.Queue(maxsize=3)
        await slow.handle({"action": "subscribe", "channel": "quotes", "symbols": ["RELIANCE"]})
        await quick.handle({"action": "subscribe", "channel": "quotes", "symbols": ["RELIANCE"]})
        for _ in range(400):
            await asyncio.sleep(0.002)
            if len(fast) >= 10:
                break
        await quick.close()
        await slow.close()
        return slow
    slow = asyncio.run(go())
    assert len(fast) >= 10
    assert slow.client.queue.qsize() <= 3 and slow.client.dropped >= 5


# ── the monitor socket's wiring (routers/monitor.py patch request, LV-API) ──────────────────────────────────────────

class _QuietPubSub:
    def __init__(self) -> None:
        self.closed = threading.Event()
        self.q: queue.Queue[Any] = queue.Queue()

    def get_message(self, timeout: float = 0.0) -> Any:
        if self.closed.is_set():
            raise ConnectionError("closed")
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.closed.set()


def _next_reply(ws: Any) -> dict[str, Any]:
    """The next non-push message (a push round may land between a request and its reply)."""
    for _ in range(10):
        m = ws.receive_json()
        if m.get("type") != "quotes":
            return m
    raise AssertionError("no reply")


@pytest.mark.skipif(not hasattr(mon, "_live"), reason="routers/monitor.py patch request (LV-API 'quotes' channel) not applied")
def test_the_monitor_socket_carries_the_quotes_channel(ds: sup.FakeDataService, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[_QuietPubSub] = []

    def open_pubsub() -> _QuietPubSub:
        ps = _QuietPubSub()
        opened.append(ps)
        return ps
    monkeypatch.setattr(mon, "_open_quotes_pubsub", open_pubsub)
    monkeypatch.setattr(mon, "_ws_active", 0)
    monkeypatch.setattr(mon, "READ_POLL_S", 0.02)
    monkeypatch.setattr(mon, "LINGER_S", 0.0)
    mon.manager.active.clear()
    app = FastAPI()
    app.include_router(mon.router, prefix="/api/monitor")
    try:
        with TestClient(app) as c, c.websocket_connect("/api/monitor/ws/monitor") as ws:
            ws.send_json({"action": "subscribe", "channel": "quotes", "symbols": ["RELIANCE", "NIFTY 50"]})
            got = [ws.receive_json(), ws.receive_json()]                          # the reply and the first snapshot
            reply = next(m for m in got if "ok" in m)
            msg = next(m for m in got if m.get("type") == "quotes")
            assert reply == {"ok": True, "channel": "quotes", "subscribed": ["RELIANCE", "NIFTY 50"],
                             "interval_s": live.PUSH_INTERVAL_S}
            assert msg["full"] is True and msg["quotes"]["RELIANCE"]["price"] == 1311.0
            assert msg["quotes"]["NIFTY 50"]["state"] == "unavailable"           # the fake has no index row: honest
            ws.send_json({"action": "subscribe", "symbols": ["TCS"]})              # the Redis filter is untouched
            assert _next_reply(ws) == {"ok": True, "subscribed": ["TCS"]}
            ws.send_json({"action": "unsubscribe", "channel": "quotes"})
            assert _next_reply(ws) == {"ok": True, "channel": "quotes", "subscribed": []}
    finally:
        for ps in opened:
            ps.closed.set()
        # the hub's reader thread ends within READ_POLL_S: never leave it to the next module's thread counts
        for t in [t for t in threading.enumerate() if t.name == "redis-quotes-hub"]:
            t.join(timeout=2.0)
