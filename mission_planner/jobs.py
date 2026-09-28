"""Background jobs for slow work (plugin propagators, long simulations).

`start(fn)` runs `fn()` on a daemon thread and returns a job id; `poll(id)`
reports {"status": "running"|"done"|"error", "elapsed_s", ...} and, once
done, merges in `fn`'s dict result.  The store keeps the most recent jobs
only.  Used by the core's /api/plan_job and available to plugins.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable

_KEEP = 8
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def start(fn: Callable[[], dict]) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        for old in sorted(_jobs, key=lambda k: _jobs[k]["started"])[: -(_KEEP - 1)]:
            del _jobs[old]
        _jobs[job_id] = {"status": "running", "started": time.time()}

    def work():
        try:
            result = fn()
            with _lock:
                _jobs[job_id].update(status="done", result=result)
        except Exception as e:  # surface any failure to the poller
            with _lock:
                _jobs[job_id].update(status="error", error=str(e))

    threading.Thread(target=work, daemon=True).start()
    return job_id


def poll(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        out = {"status": job["status"], "elapsed_s": round(time.time() - job["started"], 1)}
        if job["status"] == "done":
            out.update(job["result"])
        elif job["status"] == "error":
            out["error"] = job["error"]
    return out
