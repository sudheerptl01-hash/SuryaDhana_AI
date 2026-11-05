"""
Read snapshot of the live DuckDB file for analytics.

data-service holds the only read-write connection to market.duckdb, and DuckDB
rejects a second process opening it, so ui-api analytics read a private copy.
Copying the ~4 GB file takes ~40 s, which is longer than the Next.js proxy waits
(30 s), so the copy must almost never happen inside a user request:

* Change detection, not age: a copy is reused for as long as the source file and
  its WAL are unchanged (size + mtime), across ui-api restarts (pointer file).
* Interactive reads (``fresh=False``) get the current copy immediately; once the
  source has changed AND the copy is older than ``ttl`` a background refresh starts
  (stale-while-revalidate). Staleness is bounded by ttl + one copy duration.
* Correctness reads (``fresh=True``: the Decision Desk cycle, backtests) rebuild
  synchronously whenever the source changed, so they never trade on old data.
* Every build writes a new versioned file and swaps a pointer, so a reader never
  opens a half-replaced main/WAL pair. Superseded versions are deleted after a
  grace period (open handles keep working after unlink on POSIX).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

Signature = tuple  # ((main size, main mtime_ns), (wal size, wal mtime_ns) | None)


def _stat_sig(path: str) -> Optional[tuple[int, int]]:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns)


def source_signature(src: str) -> Signature:
    return (_stat_sig(src), _stat_sig(f"{src}.wal"))


@dataclass(frozen=True)
class SnapshotState:
    path: str
    sig: Signature
    copied_at: float


class ReadSnapshot:
    def __init__(self, source: Callable[[], str], directory: str = "/tmp", name: str = "bt_snapshot",
                 ttl: float = 600.0, grace: float = 120.0, clock: Callable[[], float] = time.time):
        self._source = source            # callable so tests / config changes resolve lazily
        self._dir = directory
        self._name = name
        self._ttl = ttl
        self._grace = grace
        self._clock = clock
        self._pointer = os.path.join(directory, f"{name}.json")
        self._build_lock = threading.Lock()   # single-flight: one 4 GB copy at a time
        self._state: Optional[SnapshotState] = None
        self._refresher: Optional[threading.Thread] = None
        self.builds = 0                  # observability + tests

    # ── public ──────────────────────────────────────────────────────────────────
    def get(self, fresh: bool = False) -> str:
        """Path of a readable snapshot. Blocks only when none exists yet, or when
        ``fresh`` is requested and the source changed since the current copy."""
        state = self._current()
        if state is None:
            return self._build_blocking(require_current=True).path
        if state.sig == source_signature(self._source()):
            return state.path
        if fresh:
            return self._build_blocking(require_current=True).path
        if self._clock() - state.copied_at >= self._ttl:
            self._refresh_in_background()
        return state.path

    def invalidate(self, path: str) -> None:
        """Forget a snapshot that failed to open (e.g. torn copy) so the next get rebuilds."""
        with self._build_lock:
            if self._state is not None and self._state.path == path:
                self._state = None
                try:
                    os.remove(self._pointer)
                except OSError:
                    pass
            self._remove_files(path)

    def wait_for_refresh(self, timeout: Optional[float] = None) -> None:
        t = self._refresher
        if t is not None:
            t.join(timeout)

    # ── internals ───────────────────────────────────────────────────────────────
    def _current(self) -> Optional[SnapshotState]:
        if self._state is not None and os.path.exists(self._state.path):
            return self._state
        self._state = self._load_pointer()
        return self._state

    def _load_pointer(self) -> Optional[SnapshotState]:
        try:
            with open(self._pointer) as fh:
                raw = json.load(fh)
            sig = tuple(tuple(x) if x is not None else None for x in raw["sig"])
            state = SnapshotState(raw["path"], sig, float(raw["copied_at"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return state if os.path.exists(state.path) else None

    def _build_blocking(self, require_current: bool) -> SnapshotState:
        with self._build_lock:
            # another thread may have finished a build while we waited for the lock
            state = self._current()
            if state is not None and (not require_current or state.sig == source_signature(self._source())):
                return state
            return self._build_locked()

    def _refresh_in_background(self) -> None:
        if self._refresher is not None and self._refresher.is_alive():
            return

        def run() -> None:
            try:
                self._build_blocking(require_current=True)
            except Exception as exc:  # the old copy keeps serving; next request retries
                print(f"[snapshot] background refresh failed: {exc}")

        self._refresher = threading.Thread(target=run, name="snapshot-refresh", daemon=True)
        self._refresher.start()

    def _build_locked(self) -> SnapshotState:
        src = self._source()
        os.makedirs(self._dir, exist_ok=True)
        path = os.path.join(self._dir, f"{self._name}.{time.time_ns()}.duckdb")
        tmp = f"{path}.tmp"
        for attempt in range(2):
            sig = source_signature(src)
            if sig[0] is None:
                raise FileNotFoundError(src)
            shutil.copyfile(src, tmp)
            has_wal = sig[1] is not None and os.path.exists(f"{src}.wal")
            if has_wal:
                shutil.copyfile(f"{src}.wal", f"{tmp}.wal")
            # A checkpoint during the copy rewrites the main file: the copy may be torn.
            if source_signature(src)[0] == sig[0] or attempt == 1:
                break
            self._remove_files(tmp)
        if has_wal:
            os.replace(f"{tmp}.wal", f"{path}.wal")
        os.replace(tmp, path)

        state = SnapshotState(path, sig, self._clock())
        ptmp = f"{self._pointer}.tmp"
        with open(ptmp, "w") as fh:
            json.dump({"path": path, "sig": sig, "copied_at": state.copied_at}, fh)
        os.replace(ptmp, self._pointer)

        old = [p for p in glob.glob(os.path.join(self._dir, f"{self._name}.*.duckdb")) if p != path]
        legacy = os.path.join(self._dir, f"{self._name}.duckdb")   # pre-versioning layout
        if os.path.exists(legacy):
            old.append(legacy)
        self._state = state
        self.builds += 1
        if old:
            timer = threading.Timer(self._grace, lambda: [self._remove_files(p) for p in old])
            timer.daemon = True
            timer.start()
        return state

    @staticmethod
    def _remove_files(path: str) -> None:
        for p in (path, f"{path}.wal"):
            try:
                os.remove(p)
            except OSError:
                pass
