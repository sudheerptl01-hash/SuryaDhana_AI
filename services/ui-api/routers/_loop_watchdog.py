"""Event-loop stall watchdog for ui-api (follow-up to the 25 Oct 2026 14:40-14:48 hang).

During that hang the event loop sat in a blocking recv() for eight minutes: /health stopped answering, and the
only way to see why was a root-only py-spy or a native `sample`, which shows C frames but no Python ones. This
module makes the next stall diagnosable from the log, without root:

* a heartbeat task on the loop stamps the time every BEAT_S;
* a watcher THREAD (a task cannot run while the loop is blocked, so it could only report after the fact) checks
  the stamp; when it is older than the threshold (UI_API_LOOP_STALL_S, default 5 s) it logs one WARNING line
  ``{"event": "loop_stall", "stalled_s": ...}`` and dumps every thread's Python stack with
  faulthandler.dump_traceback(all_threads=True) into the same stream (ui-api's stderr = .logs/ui-api.log).
  "Current thread" in the dump is the watchdog itself; the event loop is the main thread, whose stack ends in
  uvicorn's run / run_until_complete, and the frames above that name the stuck coroutine (``_serve_monitor``
  in the 14:42 case). A stall that lasts gets a fresh dump every REPEAT_S, and the end of a stall logs
  ``{"event": "loop_stall_recovered", "stalled_s": ...}``;
* ``kill -USR1 <ui-api pid>`` dumps all stacks on demand (faulthandler.register), also without root.

A stall can also be seen only AFTER the fact: when the whole process was frozen (SIGSTOP, a debugger, a C
extension holding the GIL), the watcher thread did not run either, so its first check comes when everything
resumes (the 25 Oct 15:40 SIGSTOP drill was first reported 48.5 s in, and its dump blamed whatever frame the loop
happened to be in afterwards). The watcher notices that its own wake-up came more than ``check_s + stall_s`` late
and then logs ``post_hoc: true`` with ``watcher_gap_s``; the stack dump that follows is headed "post-hoc dump"
and describes where the threads are NOW, not what blocked the loop (desktop review RAPI-05).

Off with UI_API_LOOP_WATCHDOG=0. Costs one sleeping thread and a 0.5 s timer; nothing on the request path.
"""
from __future__ import annotations

import asyncio
import contextlib
import faulthandler
import json
import logging
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import IO, Any

BEAT_S = 0.5
CHECK_S = 0.5
REPEAT_S = 60.0
DEFAULT_STALL_S = 5.0


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "component": "loop_watchdog",
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, default=str)


# Own handler (ui-api configures no root logging). stderr, like the faulthandler dump, so the two stay in order.
log = logging.getLogger("suryadhana.loop_watchdog")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(_JsonLineFormatter())
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def _fileno(stream: Any) -> int | None:
    try:
        return stream.fileno()
    except (AttributeError, OSError, ValueError):     # pytest capture, a closed or in-memory stream
        return None


def dump_all_threads(stream: IO[str]) -> None:
    """faulthandler's dump (lock-free, works whatever the stuck thread holds) when the stream is a real file;
    else the same information from sys._current_frames()."""
    with contextlib.suppress(Exception):
        stream.flush()
    if _fileno(stream) is not None:
        faulthandler.dump_traceback(file=stream, all_threads=True)
        return
    names = {t.ident: t.name for t in threading.enumerate()}
    parts = []
    for ident, frame in sys._current_frames().items():
        parts.append(f"Thread 0x{ident:016x} ({names.get(ident, '?')}) (most recent call first):\n"
                     + "".join(reversed(traceback.format_stack(frame))))
    stream.write("\n".join(parts) + "\n")
    with contextlib.suppress(Exception):
        stream.flush()


class LoopStallWatchdog:
    """Heartbeat task on ``loop`` + watcher thread. ``stalls`` counts stall episodes, ``max_stall_s`` the longest."""

    def __init__(self, loop: asyncio.AbstractEventLoop, *, stall_s: float = DEFAULT_STALL_S, beat_s: float = BEAT_S,
                 check_s: float = CHECK_S, repeat_s: float = REPEAT_S, stream: IO[str] | None = None) -> None:
        self.loop = loop
        self.stall_s, self.beat_s, self.check_s, self.repeat_s = stall_s, beat_s, check_s, repeat_s
        self.stream = stream if stream is not None else sys.stderr
        self.last_beat = time.monotonic()
        self.stalls = 0
        self.post_hoc_stalls = 0
        self.max_stall_s = 0.0
        self._stalled_since: float | None = None
        self._last_dump = 0.0
        self._task: asyncio.Task[None] | None = None
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True, name="ui-api-loop-watchdog")

    def start(self) -> LoopStallWatchdog:
        """Call on the loop's thread (the app lifespan)."""
        self.last_beat = time.monotonic()
        self._task = self.loop.create_task(self._heartbeat(), name="ui-api-loop-heartbeat")
        self._thread.start()
        return self

    async def stop(self) -> None:
        self._halt.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await asyncio.to_thread(self._thread.join, 2.0)

    async def _heartbeat(self) -> None:
        while True:
            self.last_beat = time.monotonic()
            await asyncio.sleep(self.beat_s)

    def _watch(self) -> None:
        prev_wake = time.monotonic()
        while not self._halt.wait(self.check_s):
            now = time.monotonic()
            self.tick(now, watcher_gap=now - prev_wake)   # ~check_s normally; far more if the process was frozen
            prev_wake = now

    def tick(self, now: float, *, watcher_gap: float) -> None:
        """One watcher check at monotonic time ``now``; ``watcher_gap`` = time since the previous check."""
        age = now - self.last_beat
        if age > self.stall_s:
            if self._stalled_since is None:
                self._stalled_since = self.last_beat
                self.stalls += 1
            if now - self._last_dump >= self.repeat_s or self._last_dump < self._stalled_since:
                self._last_dump = now
                post_hoc = watcher_gap > self.check_s + self.stall_s
                self._report_stall(age, post_hoc=post_hoc, watcher_gap_s=watcher_gap)
        elif self._stalled_since is not None:
            stalled = self.last_beat - self._stalled_since
            self.max_stall_s = max(self.max_stall_s, stalled)
            self._stalled_since = None
            with contextlib.suppress(Exception):
                log.warning("loop_stall_recovered", extra={"fields": {"stalled_s": round(stalled, 2)}})

    def _report_stall(self, age: float, *, post_hoc: bool = False, watcher_gap_s: float = 0.0) -> None:
        if post_hoc:
            self.post_hoc_stalls += 1
            fields: dict[str, Any] = {
                "stalled_s": round(age, 2), "threshold_s": self.stall_s, "pid": os.getpid(), "post_hoc": True,
                "watcher_gap_s": round(watcher_gap_s, 2),
                "hint": "the watchdog thread itself did not run for watcher_gap_s: the whole process was frozen "
                        "(SIGSTOP, a debugger, the GIL held by native code). The stacks that follow were taken "
                        "after it resumed and do NOT show what blocked the loop"}
        else:
            fields = {"stalled_s": round(age, 2), "threshold_s": self.stall_s, "pid": os.getpid(),
                      "hint": "the event loop has not run for stalled_s; every thread's stack follows (the loop is "
                              "the thread inside run_forever)"}
        with contextlib.suppress(Exception):
            log.warning("loop_stall", extra={"fields": fields})
        with contextlib.suppress(Exception):
            if post_hoc:
                self.stream.write(f"--- loop_watchdog: post-hoc dump (the watcher was frozen {watcher_gap_s:.1f} s "
                                  "with the rest of the process; these stacks are from AFTER the stall) ---\n")
            dump_all_threads(self.stream)


def _stall_s_from_env() -> float:
    try:
        value = float(os.environ.get("UI_API_LOOP_STALL_S", DEFAULT_STALL_S))
    except ValueError:
        return DEFAULT_STALL_S
    return value if value > 0 else DEFAULT_STALL_S


def _register_dump_signal(stream: IO[str]) -> bool:
    """kill -USR1 <pid> -> all thread stacks to ``stream`` (C-level handler: works while the loop is stuck)."""
    sig = getattr(signal, "SIGUSR1", None)
    if sig is None or _fileno(stream) is None:
        return False
    try:
        faulthandler.register(sig, file=stream, all_threads=True, chain=False)
    except (RuntimeError, ValueError, OSError):
        return False
    return True


def start_from_env(loop: asyncio.AbstractEventLoop | None = None) -> LoopStallWatchdog | None:
    """Start the watchdog for the running loop unless UI_API_LOOP_WATCHDOG=0. Never raises."""
    if os.environ.get("UI_API_LOOP_WATCHDOG", "1").strip() == "0":
        return None
    try:
        loop = loop or asyncio.get_running_loop()
        watchdog = LoopStallWatchdog(loop, stall_s=_stall_s_from_env()).start()
        signal_ok = _register_dump_signal(watchdog.stream)
        log.info("loop_watchdog_started", extra={"fields": {
            "threshold_s": watchdog.stall_s, "stack_dump_signal": "SIGUSR1" if signal_ok else None}})
        return watchdog
    except Exception:  # noqa: BLE001 — diagnostics must never stop the service from starting
        return None
