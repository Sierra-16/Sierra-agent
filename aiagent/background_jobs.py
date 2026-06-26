from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


JobHandler = Callable[[], Any]


@dataclass
class BackgroundJob:
    """A lightweight record for one best-effort maintenance job."""

    id: str
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    duration_ms: int = 0
    summary: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "summary": dict(self.summary),
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass
class _QueuedJob:
    job: BackgroundJob
    handler: JobHandler | None


class BackgroundJobQueue:
    """Single-worker background queue for post-turn maintenance.

    Jobs are best-effort by design: errors are captured in the job record and do
    not interrupt the foreground conversation.
    """

    def __init__(self, *, enabled: bool = True, max_history: int = 100):
        self.enabled = bool(enabled)
        self.max_history = max(10, int(max_history or 100))
        self._queue: queue.Queue[_QueuedJob] = queue.Queue()
        self._jobs: list[BackgroundJob] = []
        self._lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._closed = False
        self._current_job_id: str | None = None
        self._unfinished_jobs = 0
        self._worker: threading.Thread | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "BackgroundJobQueue":
        config = config if isinstance(config, dict) else {}
        return cls(
            enabled=config.get("enabled", True) is not False,
            max_history=config.get("max_history", 100),
        )

    def submit(
        self,
        name: str,
        handler: JobHandler,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> BackgroundJob:
        job = BackgroundJob(
            id=f"job-{uuid.uuid4().hex[:12]}",
            name=str(name or "background"),
            metadata=dict(metadata or {}),
        )

        with self._lock:
            if not self.enabled or self._closed:
                job.status = "cancelled"
                job.finished_at = time.time()
                self._remember(job)
                return job

            self._remember(job)
            self._ensure_worker_locked()
            self._unfinished_jobs += 1
            self._queue.put(_QueuedJob(job=job, handler=handler))
            self._idle.notify_all()
            return job

    def status(self, limit: int = 20) -> dict[str, Any]:
        with self._lock:
            jobs = [job.to_dict() for job in self._jobs[-max(1, int(limit or 20)):]]
            jobs.reverse()
            pending_count = sum(1 for job in self._jobs if job.status == "pending")
            running_count = sum(1 for job in self._jobs if job.status == "running")
            failed_count = sum(1 for job in self._jobs if job.status == "failed")
            return {
                "enabled": self.enabled,
                "closed": self._closed,
                "pending_count": pending_count,
                "running_count": running_count,
                "failed_count": failed_count,
                "jobs": jobs,
            }

    def wait_idle(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.time() + max(0, timeout)
        with self._idle:
            while self._unfinished_jobs > 0:
                if deadline is None:
                    self._idle.wait()
                    continue
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
            return True

    def close(self, *, wait: bool = False, timeout: float | None = 1.0) -> None:
        with self._lock:
            if self._closed:
                worker = self._worker
            else:
                self._closed = True
                worker = self._worker
                self._cancel_pending_locked()
                if worker is not None:
                    self._queue.put(_QueuedJob(job=BackgroundJob("stop", "stop"), handler=None))
                self._idle.notify_all()

        if wait and worker is not None:
            worker.join(timeout=timeout)

    def _remember(self, job: BackgroundJob) -> None:
        self._jobs.append(job)
        if len(self._jobs) > self.max_history:
            del self._jobs[: len(self._jobs) - self.max_history]

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._run,
            name="sierra-background",
            daemon=True,
        )
        self._worker.start()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item.handler is None:
                    return
                self._execute(item)
            finally:
                self._queue.task_done()
                with self._idle:
                    if item.handler is not None and self._unfinished_jobs > 0:
                        self._unfinished_jobs -= 1
                    self._idle.notify_all()

    def _execute(self, item: _QueuedJob) -> None:
        job = item.job
        with self._lock:
            if self._closed:
                job.status = "cancelled"
                job.finished_at = time.time()
                return
            job.status = "running"
            job.started_at = time.time()
            self._current_job_id = job.id

        try:
            result = item.handler()
            job.summary = _summary_from_result(result)
            job.status = "done"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            finished_at = time.time()
            with self._lock:
                job.finished_at = finished_at
                if job.started_at is not None:
                    job.duration_ms = round((finished_at - job.started_at) * 1000)
                if self._current_job_id == job.id:
                    self._current_job_id = None

    def _cancel_pending_locked(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                if item.handler is not None:
                    item.job.status = "cancelled"
                    item.job.finished_at = time.time()
            finally:
                if item.handler is not None and self._unfinished_jobs > 0:
                    self._unfinished_jobs -= 1
                self._queue.task_done()


def _summary_from_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, dict):
        return dict(result)
    return {"result": str(result)[:500]}
