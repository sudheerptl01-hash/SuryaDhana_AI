"""Loop-stall watchdog (routers/_loop_watchdog.py), the diagnosability follow-up to the 25 Oct 14:40 hang: a
blocked event loop gets a WARNING line and every thread's Python stack in the log, without root."""
from __future__ import annotations

import asyncio
import json
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import _loop_watchdog as wd


@pytest.fixture
def records(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """The watchdog's structured lines, as dicts (its logger does not propagate to pytest's caplog)."""
    out: list[dict] = []

    class _Capture:
        def handle(self, record) -> None:
            out.append({"event": record.getMessage(), "level": record.levelname, **getattr(record, "fields", {})})

    monkeypatch.setattr(wd.log, "handle", _Capture().handle)
    return out


def _block_the_loop_like_a_sync_recv(seconds: float) -> None:
    time.sleep(seconds)               # a blocking call on the event loop thread (the 14:42 recv() in miniature)


def test_a_stalled_loop_is_reported_with_every_threads_stack(records: list[dict]) -> None:
    with tempfile.TemporaryFile("w+") as stream:          # a real file: faulthandler writes to its fd
        async def scenario() -> wd.LoopStallWatchdog:
            dog = wd.LoopStallWatchdog(asyncio.get_running_loop(), stall_s=0.3, beat_s=0.05, check_s=0.05,
                                       stream=stream).start()
            await asyncio.sleep(0.2)
            _block_the_loop_like_a_sync_recv(1.0)
            await asyncio.sleep(0.3)                       # running again: the recovery is noticed
            await dog.stop()
            return dog

        dog = asyncio.run(scenario())
        stream.seek(0)
        dump = stream.read()

    assert dog.stalls == 1 and 0.7 < dog.max_stall_s < 2.5, (dog.stalls, dog.max_stall_s)
    events = [r["event"] for r in records]
    assert events == ["loop_stall", "loop_stall_recovered"], events
    stall = records[0]
    # >= : the report fires once the loop has been silent for the threshold, and stalled_s is rounded, so under load it
    # can equal it exactly (seen at 0.3 in a parallel gate run)
    assert stall["level"] == "WARNING" and stall["stalled_s"] >= 0.3 and stall["threshold_s"] == 0.3
    assert records[1]["level"] == "WARNING" and records[1]["stalled_s"] > 0.7
    # faulthandler's all-threads dump, naming the blocking frame on the loop thread and the coroutine above it
    assert "Current thread" in dump and dump.count("Thread 0x") >= 1
    assert "_block_the_loop_like_a_sync_recv" in dump and "scenario" in dump


def test_a_long_stall_is_dumped_again_every_repeat_interval(records: list[dict]) -> None:
    with tempfile.TemporaryFile("w+") as stream:
        async def scenario() -> wd.LoopStallWatchdog:
            dog = wd.LoopStallWatchdog(asyncio.get_running_loop(), stall_s=0.2, beat_s=0.05, check_s=0.05,
                                       repeat_s=0.4, stream=stream).start()
            await asyncio.sleep(0.1)
            _block_the_loop_like_a_sync_recv(1.2)
            await asyncio.sleep(0.2)
            await dog.stop()
            return dog

        dog = asyncio.run(scenario())
        stream.seek(0)
        dump = stream.read()
    assert dog.stalls == 1
    stalls = [r for r in records if r["event"] == "loop_stall"]
    assert 2 <= len(stalls) <= 4, len(stalls)             # one stall episode, re-dumped while it lasts
    assert dump.count("_block_the_loop_like_a_sync_recv") == len(stalls)


def test_a_busy_but_healthy_loop_is_not_reported(records: list[dict]) -> None:
    with tempfile.TemporaryFile("w+") as stream:
        async def scenario() -> wd.LoopStallWatchdog:
            dog = wd.LoopStallWatchdog(asyncio.get_running_loop(), stall_s=0.3, beat_s=0.05, check_s=0.05,
                                       stream=stream).start()
            for _ in range(40):                            # lots of short work, never 0.3 s without yielding
                time.sleep(0.01)                           # noqa: ASYNC251 — deliberate short blocking work
                await asyncio.sleep(0)
            await asyncio.sleep(0.4)
            await dog.stop()
            return dog

        dog = asyncio.run(scenario())
        stream.seek(0)
        assert stream.read() == ""
    assert dog.stalls == 0 and records == []


def test_stack_dump_without_a_file_descriptor_still_works() -> None:
    class _NoFd:
        def __init__(self) -> None:
            self.text = ""

        def write(self, s: str) -> int:
            self.text += s
            return len(s)

        def flush(self) -> None:
            pass

    out = _NoFd()
    wd.dump_all_threads(out)                               # type: ignore[arg-type]
    assert "MainThread" in out.text and "test_stack_dump_without_a_file_descriptor_still_works" in out.text


def test_env_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_API_LOOP_WATCHDOG", "0")
    assert asyncio.run(_start_and_stop()) is None
    monkeypatch.setenv("UI_API_LOOP_WATCHDOG", "1")
    for raw, want in (("2.5", 2.5), ("junk", wd.DEFAULT_STALL_S), ("-1", wd.DEFAULT_STALL_S), ("", wd.DEFAULT_STALL_S)):
        monkeypatch.setenv("UI_API_LOOP_STALL_S", raw)
        assert wd._stall_s_from_env() == want, raw
    monkeypatch.delenv("UI_API_LOOP_STALL_S")
    assert asyncio.run(_start_and_stop()) == wd.DEFAULT_STALL_S


async def _start_and_stop() -> float | None:
    dog = wd.start_from_env()
    if dog is None:
        return None
    alive = dog._thread.is_alive()
    await dog.stop()
    assert alive and not dog._thread.is_alive()
    return dog.stall_s


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="no SIGUSR1 on this platform")
def test_sigusr1_dumps_stacks_on_demand() -> None:
    with tempfile.TemporaryFile("w+") as stream:
        assert wd._register_dump_signal(stream)
        try:
            signal.raise_signal(signal.SIGUSR1)
            stream.seek(0)
            text = stream.read()
        finally:
            import faulthandler
            faulthandler.unregister(signal.SIGUSR1)
    assert "Current thread" in text and "test_sigusr1_dumps_stacks_on_demand" in text


def test_main_lifespan_runs_the_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real ui-api lifespan starts it and stops it (warmers stubbed: no Breeze, no DuckDB, no Yahoo)."""
    import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main.positions, "warm_breeze_probe", lambda: None)
    monkeypatch.setattr(main.analytics, "warm_snapshot", lambda: None)
    monkeypatch.setattr(main.gold_preopen, "warm", lambda: None)

    async def _no_paper_check() -> None:
        return None
    monkeypatch.setattr(main.execution, "enforce_paper_only_at_startup", _no_paper_check)

    def dogs() -> list[threading.Thread]:
        return [t for t in threading.enumerate() if t.name == "ui-api-loop-watchdog" and t.is_alive()]

    before = len(dogs())
    with TestClient(main.app, base_url="http://127.0.0.1:8010") as client:
        assert client.get("/health").json()["status"] == "ok"
        assert len(dogs()) == before + 1
    deadline = time.monotonic() + 3
    while len(dogs()) > before and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(dogs()) == before


def test_log_line_is_one_json_object() -> None:
    import logging
    rec = logging.LogRecord("suryadhana.loop_watchdog", logging.WARNING, __file__, 1, "loop_stall", None, None)
    rec.fields = {"stalled_s": 6.1, "threshold_s": 5.0}
    line = wd._JsonLineFormatter().format(rec)
    obj = json.loads(line)
    assert obj["event"] == "loop_stall" and obj["level"] == "warning" and obj["stalled_s"] == 6.1
    assert obj["component"] == "loop_watchdog" and "\n" not in line
