"""Job lifecycle, cache lookup and concurrent deduplication.

    queued -> running -> complete
                      -> failed
    queued -> cancelled           (always)
    running -> cancelled          (the worker running it is terminated)

Two requests that hash to the same cache key never start two builds: the second
either reads the cache or attaches to the in-flight job.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Literal

from .cache import ArtifactCache, cache_key
from .errors import CANCELLED, PUBLIC_MESSAGE, VALIDATION_ERROR, JobError
from .settings import SETTINGS
from .worker import WorkerFailure, get_pool

log = logging.getLogger("trayapi.jobs")

State = Literal["queued", "running", "complete", "failed", "cancelled"]
DEFAULT_FORMATS = {"preview": ("glb",), "export": ("step", "stl")}


@dataclass
class Job:
    id: str
    kind: str
    cache_key: str
    params_hash: str
    state: State = "queued"
    status: str | None = "queued"
    #: 0.0-1.0 while running, reported by the worker as each stage finishes.
    #: None until the first stage lands, and on a cache hit, where there is no
    #: build to be partway through.
    progress: float | None = None
    #: The stage id behind the current fraction, for anyone who wants to render
    #: something other than the label.
    stage: str | None = None
    cached: bool = False
    report: dict | None = None
    error: JobError | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    waiters: int = 1
    client: str | None = None
    #: Anonymous browser session, carried only so a completed or failed build
    #: can be attributed to the funnel. Never used for rate limiting or identity.
    session_id: str | None = None
    listeners: list = field(default_factory=list)

    @property
    def terminal(self) -> bool:
        return self.state in ("complete", "failed", "cancelled")


class JobManager:
    """In-process job registry.  One instance per API process."""

    def __init__(self, cache: ArtifactCache | None = None, pool=None, timeout: float | None = None,
                 on_finish=None):
        self.cache = cache or ArtifactCache()
        self._pool = pool
        self.timeout = timeout
        #: called with the job when it reaches a terminal state; the app uses it
        #: to release the submitting client's in-flight slot
        self.on_finish = on_finish
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._by_key: dict[str, str] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    # -- submission --------------------------------------------------------
    def submit(self, kind: str, effective_params, formats, client: str | None = None,
               session_id: str | None = None) -> Job:
        """Return a job for this request, building only if nothing else will.

        Three outcomes, in order of preference: a cache hit (job is born
        complete), an in-flight job for the same key (deduplicated), or a new
        build.
        """
        from traymold.api import params_hash

        formats = tuple(formats or DEFAULT_FORMATS[kind])
        key = cache_key(effective_params, formats)
        digest = params_hash(effective_params)

        with self._lock:
            cached = self.cache.get(key)
            if cached is not None:
                job = Job(id=_new_id(), kind=kind, cache_key=key, params_hash=digest,
                          state="complete", status="served from cache", cached=True,
                          report=cached, started_at=time.time(), finished_at=time.time(),
                          client=client, session_id=session_id)
                self._register(job)
                return job

            existing_id = self._by_key.get(key)
            if existing_id is not None:
                existing = self._jobs.get(existing_id)
                if existing is not None and not existing.terminal:
                    existing.waiters += 1
                    return existing

            job = Job(id=_new_id(), kind=kind, cache_key=key, params_hash=digest, client=client,
                      session_id=session_id)
            self._register(job)
            self._by_key[key] = job.id
            # an entry a job is about to hand out must survive a cache sweep
            self.cache.pin(key)

        payload = {
            "params": effective_params.model_dump(mode="json"),
            "quality": effective_params.quality.mode,
            "parts": effective_params.mold.parts.model_dump(),
            "formats": list(formats),
            "outdir": str(self.cache.dir_for(key)),
        }
        thread = threading.Thread(target=self._run, args=(job, payload), daemon=True)
        self._threads.append(thread)
        thread.start()
        return job

    def _register(self, job: Job) -> None:
        self._jobs[job.id] = job
        while len(self._jobs) > SETTINGS.job_retention:
            _, old = self._jobs.popitem(last=False)
            if self._by_key.get(old.cache_key) == old.id:
                self._by_key.pop(old.cache_key, None)

    # -- execution ---------------------------------------------------------
    def _run(self, job: Job, payload: dict) -> None:
        if job.cancel.is_set():
            self._finish(job, state="cancelled",
                         error=JobError(CANCELLED, PUBLIC_MESSAGE[CANCELLED]))
            return
        job.state = "running"
        job.status = "building geometry"
        job.started_at = time.time()
        self._emit(job)

        def on_progress(frame: dict) -> None:
            # Monotonic by construction: the worker sends stages in order and
            # never repeats one. Guarded anyway, because a bar that goes
            # backwards reads as a bug in the build rather than in the bar.
            fraction = frame.get("fraction")
            if isinstance(fraction, (int, float)):
                if job.progress is None or fraction > job.progress:
                    job.progress = float(min(1.0, max(0.0, fraction)))
            job.stage = frame.get("stage")
            job.status = frame.get("label") or job.status
            self._emit(job)

        try:
            pool = self._pool or get_pool()
            dispatched = time.perf_counter()
            report = pool.run(payload, cancel=job.cancel, timeout=self.timeout,
                              on_progress=on_progress)
            report.setdefault("timings", {})["worker_roundtrip_s"] = round(
                time.perf_counter() - dispatched, 4
            )
        except WorkerFailure as failure:
            state = "cancelled" if failure.kind == CANCELLED else "failed"
            self._finish(job, state=state,
                         error=JobError(failure.kind, failure.message, failure.diagnostics))
            return
        except Exception:  # pragma: no cover - defensive
            log.exception("unexpected job failure")
            self._finish(job, state="failed",
                         error=JobError("geometry_build_error",
                                        "the build failed for an unexpected reason"))
            return
        self.cache.put(job.cache_key, report)
        job.report = report
        self._finish(job, state="complete")

    def _finish(self, job: Job, *, state: State, error: JobError | None = None) -> None:
        job.state = state
        job.error = error
        job.status = {"complete": "done", "failed": "failed", "cancelled": "cancelled"}[state]
        # A finished build is 1.0 whatever the last stage reported; a failed or
        # cancelled one keeps the fraction it got to, which is the useful thing
        # to know about where it stopped.
        if state == "complete":
            job.progress = 1.0
        job.finished_at = time.time()
        with self._lock:
            if self._by_key.get(job.cache_key) == job.id:
                self._by_key.pop(job.cache_key, None)
        self.cache.unpin(job.cache_key)
        if self.on_finish is not None:
            try:
                self.on_finish(job)
            except Exception:  # pragma: no cover
                log.exception("job completion hook failed")
        self._emit(job)

    # -- event streaming ---------------------------------------------------
    def subscribe(self, job_id: str) -> "queue.Queue | None":
        """A queue that receives every subsequent state change of this job.

        Used by the SSE endpoint.  Pushing on transition rather than polling
        means the browser sees `complete` the moment the worker returns.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return None
        channel: queue.Queue = queue.Queue()
        with self._lock:
            job.listeners.append(channel)
        return channel

    def unsubscribe(self, job_id: str, channel) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        with self._lock:
            if channel in job.listeners:
                job.listeners.remove(channel)

    def _emit(self, job: Job) -> None:
        with self._lock:
            listeners = list(job.listeners)
        for channel in listeners:
            try:
                channel.put_nowait(job)
            except Exception:  # pragma: no cover
                pass

    # -- queries -----------------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.terminal:
            return job
        job.cancel.set()
        if job.state == "queued":
            self._finish(job, state="cancelled",
                         error=JobError(CANCELLED, PUBLIC_MESSAGE[CANCELLED]))
        return job

    def wait(self, job_id: str, timeout: float = 60.0) -> Job | None:
        """Block until a job leaves the running states.  Test and CLI helper."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self._jobs.get(job_id)
            if job is None or job.terminal:
                return job
            time.sleep(0.02)
        return self._jobs.get(job_id)

    def join(self, timeout: float = 120.0) -> None:
        for thread in list(self._threads):
            thread.join(timeout=timeout)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def rejected_error(diagnostics: list[dict]) -> JobError:
    return JobError(VALIDATION_ERROR, "the parameters are not valid", diagnostics)
