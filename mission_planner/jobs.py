"""Background jobs for slow work (plugin propagators, long simulations).

`start(fn)` runs `fn()` on a daemon thread and returns a job id; `poll(id)`
reports {"status": "running"|"done"|"error", "elapsed_s", ...} and, once
done, merges in `fn`'s dict result (the envelope keys win, so a result can't
mask its own status).  Finished jobs are kept for a while so a late poller
still finds them; running jobs are never evicted.  Used by the core's
/api/plan_job and available to plugins through the module-level `start` /
`poll`, which share one process-wide `JobStore`.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable


class JobStore:
    def __init__(self, keep: int = 8):
        self.keep = keep  # finished jobs retained (the most recent ones)
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, fn: Callable[[], dict]) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            done = [k for k, j in self._jobs.items() if j["status"] != "running"]
            for old in sorted(done, key=lambda k: self._jobs[k]["started"])[: -self.keep or None]:
                del self._jobs[old]
            self._jobs[job_id] = {"status": "running", "started": time.time()}

        def work():
            try:
                result = fn()
                if not isinstance(result, dict):
                    raise TypeError(f"job returned {type(result).__name__}, not a dict")
                update = {"status": "done", "result": result}
            except Exception as e:  # surface any failure to the poller
                traceback.print_exc()
                update = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            with self._lock:
                self._jobs[job_id].update(update, finished=time.time())

        threading.Thread(target=work, daemon=True).start()
        return job_id

    def poll(self, job_id: str) -> dict | None:
        """The job's result (once done) under an envelope that always wins:
        status (running | done | error), elapsed_s (its run time so far, or
        in all once it has finished) and, on error, error."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            out = {}
            if job["status"] == "done":
                out.update(job["result"])
            out["status"] = job["status"]
            out["elapsed_s"] = round(job.get("finished", time.time()) - job["started"], 1)
            if job["status"] == "error":
                out["error"] = job["error"]
        return out


_STORE = JobStore()


def start(fn: Callable[[], dict]) -> str:
    return _STORE.start(fn)


def poll(job_id: str) -> dict | None:
    return _STORE.poll(job_id)
