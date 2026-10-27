"""Long tasks, each in its own process, with a log, a result and cancel.

Builds come first; benchmarks and calibration fits will follow. A job runs one of the
functions in ``JOB_KINDS`` in a fresh process (so a crash or a cancel can't hurt the
caller) and reports log lines and a result over a pipe. Jobs with the same ``key`` don't
run twice at once: asking again while one runs returns the running one, which is how two
runs of the same PROS project share one build.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ACTIVE: tuple[str, ...] = ("queued", "running")


def _build(params: dict, log: Callable[[str], None]) -> dict:
    from vexsim.bridge.build import build_project

    result = build_project(params["project"], log=log)
    return {
        "executable": str(result.executable),
        "linked": result.linked,
        "compiled": result.compiled,
        "total": result.total,
        "seconds": round(result.seconds, 3),
    }


def _echo(params: dict, log: Callable[[str], None]) -> dict:
    """For tests: log lines, optionally wait or fail."""
    for line in params.get("lines", []):
        log(line)
    time.sleep(params.get("sleep_s", 0.0))
    if params.get("fail"):
        raise RuntimeError(params["fail"])
    return {"echo": params.get("result")}


JOB_KINDS: dict[str, Callable[[dict, Callable[[str], None]], dict]] = {
    "build": _build,
    "echo": _echo,
}


def run_job(conn, kind: str, params: dict) -> None:
    """The job's process: run it, sending ("log", line)s, then ("result" | "error", ...)."""

    def log(line: str) -> None:
        conn.send(("log", str(line)))

    try:
        conn.send(("result", JOB_KINDS[kind](params, log)))
    except BaseException as exc:  # report everything, even KeyboardInterrupt
        conn.send(("error", str(exc) or type(exc).__name__))


@dataclass
class Job:
    id: str
    kind: str
    title: str
    params: dict
    key: str
    state: JobState = "queued"
    log: list[str] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    _done: threading.Event = field(default_factory=threading.Event, repr=False)
    _process: Any = field(default=None, repr=False)
    _cancelled: bool = field(default=False, repr=False)

    @property
    def active(self) -> bool:
        return self.state in ACTIVE

    def to_dict(self, since: int = 0) -> dict:
        """The job as the UI shows it: its log from line ``since`` on."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state,
            "log": self.log[since:],
            "log_size": len(self.log),
            "result": self.result,
            "error": self.error,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
        }


# A listener hears every change to a job: ("state", job), or ("log", job) with a new line.
Listener = Callable[[str, Job, str | None], None]


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._listeners: list[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self, event: str, job: Job, line: str | None = None) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, job, line)
            except Exception:  # a listener's failure is its own
                pass

    def submit(self, kind: str, params: dict, *, title: str = "", key: str | None = None) -> Job:
        """Start a job, or return the active job with the same ``key``."""
        if kind not in JOB_KINDS:
            raise ValueError(f"unknown job kind: {kind}")
        with self._lock:
            if key is not None:
                for job in self._jobs.values():
                    if job.key == key and job.active:
                        return job
            job_id = f"job{next(self._ids)}"
            job = Job(job_id, kind, title or kind, dict(params), key or job_id)
            self._jobs[job_id] = job
        thread = threading.Thread(target=self._run, args=(job,), name=f"vexsim-{job_id}")
        thread.daemon = True
        thread.start()
        return job

    def _run(self, job: Job) -> None:
        from vexsim.app.child import ChildError, ChildProcess

        with self._lock:
            cancelled = job._cancelled
            if not cancelled:
                job.state, job.started = "running", time.time()
        if cancelled:
            with self._lock:
                self._finish(job, "cancelled")
            self._notify("state", job)
            return
        self._notify("state", job)

        def output(line: str) -> None:  # anything the job's process prints
            job.log.append(line)
            self._notify("log", job, line)

        outcome: JobState | None = None
        try:
            arguments = {"kind": job.kind, "params": job.params}
            child = ChildProcess("vexsim.app.jobs:run_job", arguments, on_output=output)
        except (ChildError, OSError) as exc:
            job.error, outcome = str(exc), "failed"
            child = None
        if child is not None:
            with self._lock:
                job._process = child
                if job._cancelled:
                    child.terminate()
            while True:
                try:
                    kind, value = child.recv()
                except (EOFError, OSError):
                    break
                if kind == "log":
                    output(value)
                elif kind == "result":
                    job.result, outcome = value, "succeeded"
                elif kind == "error":
                    job.error, outcome = value, "failed"
            child.close()
            if job._cancelled:
                outcome = "cancelled"
            elif outcome is None:
                job.error = f"the job's process stopped (exit code {child.process.returncode})"
                outcome = "failed"
        with self._lock:
            self._finish(job, outcome or "failed")
        self._notify("state", job)

    def _finish(self, job: Job, state: JobState) -> None:
        """Record the end of a job (with the lock held; the caller notifies)."""
        job.state, job.finished = state, time.time()
        job._process = None
        job._done.set()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(self._jobs.values())

    def wait(self, job: Job, timeout: float | None = None) -> bool:
        """Wait for a job to end; False on timeout."""
        return job._done.wait(timeout)

    def cancel(self, job: Job) -> None:
        with self._lock:
            if not job.active:
                return
            job._cancelled = True
            process = job._process
        if process is not None:
            process.terminate()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cancel every active job and wait for them to end."""
        jobs = [j for j in self.list() if j.active]
        for job in jobs:
            self.cancel(job)
        deadline = time.monotonic() + timeout
        for job in jobs:
            self.wait(job, max(0.0, deadline - time.monotonic()))
