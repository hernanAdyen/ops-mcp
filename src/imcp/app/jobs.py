"""Slow work (our model reading merchant material) as jobs on the app server.

Starting a job returns at once, or as soon as the job finishes if that's within `wait` seconds.
The client asks again with the job ID until it is done. The job lives here, not in the MCP
server, so it survives the IM's Claude restarting. Results stay in memory only (they hold the
answers found, which are never stored) and are dropped after KEEP_SECONDS.
"""

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError

MAX_WAIT = 50  # a bridge may give up at 60 s
KEEP_SECONDS = 1800


class JobStore:
    def __init__(self, workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="imcp-job")
        self._jobs: dict[str, tuple[Future, float]] = {}
        self._lock = threading.Lock()

    def submit(self, fn) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._prune()
            self._jobs[job_id] = (self._pool.submit(fn), time.monotonic())
        return job_id

    def get(self, job_id: str) -> Future | None:
        with self._lock:
            entry = self._jobs.get(job_id)
        return entry[0] if entry else None

    def wait(self, job_id: str, seconds: float):
        """('done', result) | ('pending', None) | ('unknown', None). A job that failed re-raises its error."""
        future = self.get(job_id)
        if future is None:
            return "unknown", None
        try:
            return "done", future.result(timeout=max(0.0, min(seconds, MAX_WAIT)))
        except TimeoutError:
            return "pending", None

    def _prune(self) -> None:
        cutoff = time.monotonic() - KEEP_SECONDS
        for job_id in [j for j, (f, t) in self._jobs.items() if f.done() and t < cutoff]:
            del self._jobs[job_id]
