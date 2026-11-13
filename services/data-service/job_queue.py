"""Durable background-job queue for data-service (FINAL round, R2-QUEUE; RATING R9-A2 "a persisted job queue
with leases").

Drop-in successor to ``jobs.JobManager`` with the same interface — ``submit(kind, fn) -> (job, created)``,
``get(job_id)``, ``list()``, ``is_running(kind)`` — plus durability:

- Every job is a row in SQLite (``data/job_queue.sqlite``, env ``JOB_QUEUE_DB``): status ``queued`` / ``running`` /
  ``done`` / ``error`` (``error`` == "failed"; the name is kept because the /jobs API and the master-controller's
  poll loop already contract on it), submitted/started/finished timestamps, progress, result and error text.
- A **lease** on every running row (``lease_expires_at``), extended by a heartbeat thread while the worker thread is
  alive. The lease measures *process* liveness, not job progress: as long as this process runs, the lease is renewed.
  A crash (kill -9, reboot, OOM) stops the heartbeat, so the row's lease expires in place.
- **Resume on start**: construction re-queues every ``running`` row whose lease has expired or whose recorded pid is
  dead (status → ``queued``, ``requeued`` = 1). The queued row is *adopted* by the next ``submit()`` of the same kind
  (same job_id, attempt + 1) — the start-up catch-up in master_controller re-POSTs its jobs, and every ingest job
  already resumes after the last stored date, so the re-run is idempotent. The queue never re-executes a closure on
  its own: the callable is not persisted, and silently re-running half-configured work would change job semantics.

One job per *kind* runs at a time, exactly as before: a second request for a running kind gets the existing job back
instead of starting a competing DuckDB writer.

Reads of running jobs come from the in-memory mirror (fresh progress without a write per progress tick); finished
and queued rows come from SQLite. Progress is flushed to SQLite by the heartbeat (every ``heartbeat_s``) and at
terminal states, so a crash loses at most one heartbeat of progress numbers — never the row.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List  # noqa: UP035 — List: the `list` method shadows the builtin in class scope

from shared.logging import get_logger

logger = get_logger(__name__)

_LIST_LIMIT = 50                  # GET /jobs parity with the old in-memory manager
_RESULT_MAX_CHARS = 400_000       # a result bigger than this is summarised, never dropped

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id            TEXT PRIMARY KEY,
    kind              TEXT NOT NULL,
    status            TEXT NOT NULL,              -- queued | running | done | error
    progress          INTEGER NOT NULL DEFAULT 0,
    total             INTEGER NOT NULL DEFAULT 0,
    attempt           INTEGER NOT NULL DEFAULT 1,
    requeued          INTEGER NOT NULL DEFAULT 0, -- 1 = re-queued after a crash (lease expired)
    pid               INTEGER,
    submitted_at      TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    heartbeat_at      TEXT,
    lease_expires_at  TEXT,
    result            TEXT,                       -- JSON
    error             TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_kind_status ON jobs(kind, status);
CREATE INDEX IF NOT EXISTS idx_jobs_submitted ON jobs(submitted_at);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def default_db_path(data_dir: Path) -> Path:
    """``JOB_QUEUE_DB`` env override, else ``<data_dir>/job_queue.sqlite`` (beside the other SQLite stores)."""
    env = os.getenv("JOB_QUEUE_DB", "").strip()
    return Path(env) if env else data_dir / "job_queue.sqlite"


class DurableJobManager:
    """Persisted job queue with leases. Same call surface as ``jobs.JobManager`` (see module docstring)."""

    def __init__(self, db_path: Path | str, lease_s: float = 120.0, heartbeat_s: float = 15.0,
                 keep: int = 500) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lease_s = float(lease_s)
        self._heartbeat_s = float(heartbeat_s)
        self._keep = int(keep)
        self._lock = threading.Lock()                       # guards the mirrors + serialises writes
        self._running: dict[str, dict[str, Any]] = {}       # job_id -> live job dict (this process)
        self._running_by_kind: dict[str, str] = {}
        self._hb_thread: threading.Thread | None = None
        self._hb_stop = threading.Event()
        with self._connect() as con:
            con.executescript(_SCHEMA)
        self.resume_on_start()

    # ── storage ──────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self._path), timeout=30.0)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    # ── crash recovery ───────────────────────────────────────────────────────

    def resume_on_start(self) -> int:
        """Re-queue orphaned ``running`` rows (expired lease, or a dead/foreign pid). Returns the count."""
        now = _iso(_utcnow())
        me = os.getpid()
        requeued = 0
        with self._lock, self._connect() as con:
            rows = con.execute(
                "SELECT job_id, kind, pid, lease_expires_at FROM jobs WHERE status = 'running'").fetchall()
            for job_id, kind, pid, lease in rows:
                if job_id in self._running:                 # owned by this live process
                    continue
                expired = (lease or "") < now
                if not expired and pid == me:
                    continue
                if not expired and _pid_alive(pid):         # another live process still holds the lease
                    continue
                con.execute(
                    "UPDATE jobs SET status = 'queued', requeued = 1, heartbeat_at = NULL,"
                    " lease_expires_at = NULL, pid = NULL WHERE job_id = ?", (job_id,))
                requeued += 1
                logger.warning("Job re-queued after crash (lease expired)", kind=kind, job_id=job_id)
            con.commit()
        return requeued

    # ── the JobManager surface ───────────────────────────────────────────────

    def submit(self, kind: str, fn: Callable[[Callable[[int, int], None]], dict]) -> tuple[dict, bool]:
        """Start ``fn(progress_cb)`` in a thread, persisting the row first. Returns (job, created).

        A queued row of the same kind (crash re-queue) is adopted: same job_id, attempt + 1."""
        now = _utcnow()
        with self._lock:
            running = self._running_by_kind.get(kind)
            if running:
                return self._public(self._running[running]), False
            with self._connect() as con:
                adopted = con.execute(
                    "SELECT job_id, attempt, submitted_at FROM jobs WHERE kind = ? AND status = 'queued'"
                    " ORDER BY submitted_at DESC LIMIT 1", (kind,)).fetchone()
                if adopted:
                    job_id, attempt, submitted_at = adopted[0], int(adopted[1]) + 1, adopted[2]
                    requeued = 1
                else:
                    job_id, attempt, submitted_at, requeued = uuid.uuid4().hex[:12], 1, _iso(now), 0
                job = {
                    "job_id": job_id, "kind": kind, "status": "running",
                    "progress": 0, "total": 0, "attempt": attempt, "requeued": requeued,
                    "submitted_at": submitted_at, "started_at": _iso(now), "finished_at": None,
                    "result": None, "error": None,
                }
                con.execute(
                    "INSERT INTO jobs (job_id, kind, status, progress, total, attempt, requeued, pid,"
                    " submitted_at, started_at, heartbeat_at, lease_expires_at)"
                    " VALUES (?, ?, 'running', 0, 0, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(job_id) DO UPDATE SET status = 'running', progress = 0, total = 0,"
                    " attempt = excluded.attempt, pid = excluded.pid, started_at = excluded.started_at,"
                    " heartbeat_at = excluded.heartbeat_at, lease_expires_at = excluded.lease_expires_at,"
                    " finished_at = NULL, result = NULL, error = NULL",
                    (job_id, kind, attempt, requeued, os.getpid(), submitted_at, job["started_at"],
                     _iso(now), self._lease_iso(now)))
                self._trim(con)
                con.commit()
            self._running[job_id] = job
            self._running_by_kind[kind] = job_id
            self._ensure_heartbeat()

        def _progress(done: int, total: int) -> None:
            job["progress"], job["total"] = done, total      # flushed by the heartbeat

        def _run() -> None:
            try:
                job["result"] = fn(_progress)
                job["status"] = "done"
            except Exception as exc:  # noqa: BLE001 — the row records any failure
                job["status"] = "error"
                job["error"] = f"{type(exc).__name__}: {exc}"
                logger.error("Job failed", kind=kind, job_id=job_id,
                             error=str(exc), trace=traceback.format_exc()[-1500:])
            finally:
                job["finished_at"] = _iso(_utcnow())
                self._finish(job)
                with self._lock:
                    self._running.pop(job_id, None)
                    if self._running_by_kind.get(kind) == job_id:
                        self._running_by_kind.pop(kind, None)

        threading.Thread(target=_run, name=f"job-{kind}-{job_id}", daemon=True).start()
        logger.info("Job started", kind=kind, job_id=job_id, attempt=attempt)
        return self._public(job), True

    def record_sync(self, kind: str, fn: Callable[[], dict]) -> dict:
        """Run ``fn`` inline (a synchronous /jobs endpoint) and persist a done/error row; the response is
        ``fn()``'s own return value, unchanged. Exceptions re-raise after the error row is written."""
        now = _utcnow()
        job_id = uuid.uuid4().hex[:12]
        try:
            result = fn()
        except Exception as exc:
            self._insert_finished(job_id, kind, "error", now, error=f"{type(exc).__name__}: {exc}")
            raise
        self._insert_finished(job_id, kind, "done", now, result=result)
        return result

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            live = self._running.get(job_id)
            if live:
                return self._public(live)
        with self._connect() as con:
            row = con.execute(f"SELECT {self._COLS} FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self) -> List[dict]:
        """Newest-first jobs (running from memory, the rest from the store), capped like the old manager."""
        with self._lock:
            out = {j["job_id"]: self._public(j) for j in self._running.values()}
        with self._connect() as con:
            rows = con.execute(
                f"SELECT {self._COLS} FROM jobs ORDER BY submitted_at DESC LIMIT ?", (_LIST_LIMIT,)).fetchall()
        for row in rows:
            out.setdefault(row[0], self._from_row(row))
        return sorted(out.values(), key=lambda j: j.get("started_at") or j["submitted_at"], reverse=True)[:_LIST_LIMIT]

    def recent(self, n: int = 50) -> List[dict]:
        """Compact newest-first history for ``GET /jobs/recent`` (no result payloads)."""
        n = max(1, min(int(n), 200))
        with self._connect() as con:
            rows = con.execute(
                "SELECT job_id, kind, status, progress, total, attempt, requeued, submitted_at, started_at,"
                " finished_at, error FROM jobs ORDER BY submitted_at DESC LIMIT ?", (n,)).fetchall()
        out = []
        with self._lock:
            live_by_id = {j["job_id"]: (j["status"], j["progress"], j["total"]) for j in self._running.values()}
        for (job_id, kind, status, progress, total, attempt, requeued, submitted_at, started_at,
             finished_at, error) in rows:
            live = live_by_id.get(job_id)
            if live:                                        # fresh progress for running rows
                status, progress, total = live
            duration_s = None
            if started_at and finished_at:
                try:
                    duration_s = round((datetime.fromisoformat(finished_at)
                                        - datetime.fromisoformat(started_at)).total_seconds(), 3)
                except ValueError:
                    pass
            row = {"job_id": job_id, "kind": kind, "status": status, "progress": progress, "total": total,
                   "attempt": attempt, "requeued": bool(requeued), "submitted_at": submitted_at,
                   "started_at": started_at, "finished_at": finished_at, "duration_s": duration_s}
            if error:
                row["error"] = error
            out.append(row)
        return out

    def is_running(self, kind: str) -> bool:
        with self._lock:
            return kind in self._running_by_kind

    def close(self) -> None:
        """Stop the heartbeat thread (tests; worker threads are daemons and stop with the process)."""
        self._hb_stop.set()
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=2.0)
            self._hb_thread = None

    # ── internals ────────────────────────────────────────────────────────────

    _COLS = ("job_id, kind, status, progress, total, attempt, requeued, submitted_at, started_at,"
             " finished_at, result, error")

    def _lease_iso(self, now: datetime | None = None) -> str:
        from datetime import timedelta
        return _iso((now or _utcnow()) + timedelta(seconds=self._lease_s))

    def _ensure_heartbeat(self) -> None:
        if self._hb_thread is not None and self._hb_thread.is_alive():
            return
        self._hb_stop.clear()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name="job-queue-heartbeat", daemon=True)
        self._hb_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._hb_stop.wait(self._heartbeat_s):
            try:
                self.flush_heartbeat()
            except Exception as exc:  # noqa: BLE001 — a failed flush never kills the heartbeat
                logger.warning("Job heartbeat flush failed", error=str(exc))

    def flush_heartbeat(self) -> int:
        """Extend the lease + flush progress for every running job this process owns. Returns the count."""
        with self._lock:
            snapshot = [(j["progress"], j["total"], j["job_id"]) for j in self._running.values()
                        if j["status"] == "running"]
            if not snapshot:
                return 0
            now = _utcnow()
            with self._connect() as con:
                con.executemany(
                    "UPDATE jobs SET progress = ?, total = ?, heartbeat_at = ?, lease_expires_at = ?"
                    " WHERE job_id = ? AND status = 'running'",
                    [(p, t, _iso(now), self._lease_iso(now), jid) for p, t, jid in snapshot])
                con.commit()
        return len(snapshot)

    def _finish(self, job: dict[str, Any]) -> None:
        try:
            with self._lock, self._connect() as con:
                con.execute(
                    "UPDATE jobs SET status = ?, progress = ?, total = ?, finished_at = ?, result = ?,"
                    " error = ?, lease_expires_at = NULL WHERE job_id = ?",
                    (job["status"], job["progress"], job["total"], job["finished_at"],
                     self._encode_result(job.get("result")), job.get("error"), job["job_id"]))
                con.commit()
        except Exception as exc:  # noqa: BLE001 — the in-memory result is still handed to pollers mid-flight
            logger.error("Job row finish write failed", job_id=job["job_id"], error=str(exc))

    def _insert_finished(self, job_id: str, kind: str, status: str, started: datetime,
                         result: dict | None = None, error: str | None = None) -> None:
        now = _iso(_utcnow())
        try:
            with self._lock, self._connect() as con:
                con.execute(
                    "INSERT INTO jobs (job_id, kind, status, progress, total, attempt, requeued, pid,"
                    " submitted_at, started_at, finished_at, result, error)"
                    " VALUES (?, ?, ?, 0, 0, 1, 0, ?, ?, ?, ?, ?, ?)",
                    (job_id, kind, status, os.getpid(), _iso(started), _iso(started), now,
                     self._encode_result(result), error))
                self._trim(con)
                con.commit()
        except Exception as exc:  # noqa: BLE001 — a sync endpoint's response never fails on bookkeeping
            logger.warning("Sync job row write failed", kind=kind, error=str(exc))

    def _trim(self, con: sqlite3.Connection) -> None:
        con.execute(
            "DELETE FROM jobs WHERE status IN ('done', 'error') AND job_id NOT IN ("
            " SELECT job_id FROM jobs WHERE status IN ('done', 'error')"
            " ORDER BY submitted_at DESC LIMIT ?)", (self._keep,))

    @staticmethod
    def _encode_result(result: Any) -> str | None:
        if result is None:
            return None
        try:
            text = json.dumps(result, default=str)
        except (TypeError, ValueError):
            text = json.dumps({"repr": repr(result)[:2000]})
        if len(text) > _RESULT_MAX_CHARS:
            text = json.dumps({"truncated": True, "note": f"result of {len(text)} chars truncated",
                               "preview": text[:2000]})
        return text

    def _from_row(self, row: tuple) -> dict:
        (job_id, kind, status, progress, total, attempt, requeued, submitted_at, started_at,
         finished_at, result, error) = row
        parsed: Any = None
        if result:
            try:
                parsed = json.loads(result)
            except ValueError:
                parsed = {"raw": result[:2000]}
        return {"job_id": job_id, "kind": kind, "status": status, "progress": progress, "total": total,
                "attempt": attempt, "requeued": bool(requeued), "submitted_at": submitted_at,
                "started_at": started_at, "finished_at": finished_at, "result": parsed, "error": error}

    @staticmethod
    def _public(job: dict) -> dict:
        return dict(job)
