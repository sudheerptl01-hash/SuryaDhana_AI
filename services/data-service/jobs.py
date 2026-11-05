"""
In-process background jobs for long data operations (universe refresh, ML dataset
build). HTTP handlers return a job id immediately; callers poll ``GET /jobs/{id}``.

One job per *kind* runs at a time — a second request for a running kind gets the
existing job back instead of starting a competing writer.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from shared.logging import get_logger

logger = get_logger(__name__)

_MAX_HISTORY = 50


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._running_by_kind: dict[str, str] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[Callable[[int, int], None]], dict]) -> tuple[dict, bool]:
        """Start ``fn(progress_cb)`` in a thread. Returns (job, created)."""
        with self._lock:
            running = self._running_by_kind.get(kind)
            if running:
                return self._public(self._jobs[running]), False
            job_id = uuid.uuid4().hex[:12]
            job = {
                "job_id": job_id,
                "kind": kind,
                "status": "running",
                "progress": 0,
                "total": 0,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "result": None,
                "error": None,
            }
            self._jobs[job_id] = job
            self._running_by_kind[kind] = job_id
            self._trim()

        def _progress(done: int, total: int) -> None:
            job["progress"], job["total"] = done, total

        def _run() -> None:
            try:
                job["result"] = fn(_progress)
                job["status"] = "done"
            except Exception as exc:
                job["status"] = "error"
                job["error"] = f"{type(exc).__name__}: {exc}"
                logger.error("Job failed", kind=kind, job_id=job_id,
                             error=str(exc), trace=traceback.format_exc()[-1500:])
            finally:
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                with self._lock:
                    self._running_by_kind.pop(kind, None)

        threading.Thread(target=_run, name=f"job-{kind}-{job_id}", daemon=True).start()
        logger.info("Job started", kind=kind, job_id=job_id)
        return self._public(job), True

    def get(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return self._public(job) if job else None

    def list(self) -> list[dict]:
        return [self._public(j) for j in sorted(self._jobs.values(),
                                                 key=lambda j: j["started_at"], reverse=True)]

    def is_running(self, kind: str) -> bool:
        return kind in self._running_by_kind

    def _trim(self) -> None:
        if len(self._jobs) <= _MAX_HISTORY:
            return
        finished = sorted((j for j in self._jobs.values() if j["status"] != "running"),
                          key=lambda j: j["started_at"])
        for j in finished[: len(self._jobs) - _MAX_HISTORY]:
            self._jobs.pop(j["job_id"], None)

    @staticmethod
    def _public(job: dict) -> dict:
        return dict(job)
