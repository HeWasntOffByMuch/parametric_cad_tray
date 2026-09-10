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

from .cache import ArtifactCache, cache_key, half_key
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
    #: For a split preview: part name -> that half's own cache key. Empty for a
    #: single-key build, where `cache_key` is both the identity and the storage.
    part_keys: dict = field(default_factory=dict)
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


def split_for(kind: str, effective_params, formats) -> dict | None:
    """The two half-builds this request decomposes into, or None if it does not.

    The plug and the cavity share nothing downstream of the base profile - the
    male is the base profile, the female is that profile offset by the forming
    gap, and `apply_features` guards every branch on which half it was handed.
    So building them separately gives the same geometry, and gives each half its
    own cache entry: changing a cavity setting then leaves the plug's entry
    untouched, which is most of why an edit is fast.

    Only previews. An export writes STEP and STL per part already and happens
    once, so splitting it buys a bundle spanning two directories and nothing
    else.
    """
    if kind != "preview":
        return None
    parts = effective_params.mold.parts
    if not (parts.male and parts.female):
        return None          # already one half; nothing to split
    out = {}
    for name in ("male", "female"):
        # The half is built from the *whole* parameter document with only the
        # part flags changed, so validation and the derived values are exactly
        # what a combined build would produce. Only the key is projected - see
        # cache.half_key and its proof in test_split_keys.py.
        half = effective_params.model_copy(update={
            "mold": effective_params.mold.model_copy(update={
                "parts": parts.model_copy(update={
                    "male": name == "male", "female": name == "female",
                }),
            }),
        })
        out[name] = (half, half_key(half, formats, name))
    return out


def _half_weight(name: str, payload: dict | None) -> float:
    """How long this half is expected to take, relative to the other.

    Read from the same measured table the progress bar uses, over the stages
    this half will actually run, so a cavity with its entry blend switched off
    is correctly weighted lighter than one with it on.
    """
    try:
        from traymold.params import Params
        from traymold.progress import COST, stages_for

        if payload is None:
            raise ValueError                       # cached half: fall back below
        params = Params.model_validate(payload["params"])
        mode = params.quality.mode if params.quality.mode in COST else "preview"
        return float(sum(COST[mode].get(s, 1.0) for s in stages_for(params))) or 1.0
    except Exception:
        # Measured on the reference: the plug is about 2.7x the cavity. A wrong
        # weight makes the bar uneven, never wrong about being finished.
        return {"male": 3400.0, "female": 1300.0}.get(name, 1000.0)


def merge_reports(reports: dict[str, dict], keys: dict[str, str]) -> dict:
    """One report from two half-builds.

    Each artifact is stamped with the cache key of the half that produced it,
    because they live in different directories and the URL has to say which.
    Everything else is either identical between the halves (the parameters were
    the same but for which half to build) or a union.
    """
    ordered = [reports[n] for n in ("male", "female") if n in reports]
    if not ordered:
        return {}
    merged = dict(ordered[0])
    artifacts, volumes, stats, timings = [], {}, {}, {}
    for name in ("male", "female"):
        report = reports.get(name)
        if report is None:
            continue
        for artifact in report.get("artifacts", []):
            artifacts.append({**artifact, "cache_key": keys[name]})
        volumes.update(report.get("volumes_cm3", {}))
        stats.update(report.get("stats", {}))
        for label, value in (report.get("timings") or {}).items():
            # The halves run at the same time, so the slower one is the wall
            # clock; summing would claim a build took twice as long as it did.
            timings[label] = max(timings.get(label, 0.0), value)
    merged["artifacts"] = artifacts
    merged["volumes_cm3"] = volumes
    merged["stats"] = stats
    merged["timings"] = timings
    # The parts flag on the merged report describes what the caller asked for,
    # not what either half was told to build.
    merged["parts"] = {"male": "male" in reports, "female": "female" in reports}
    return merged


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
        split = split_for(kind, effective_params, formats)
        part_keys = {name: k for name, (_, k) in (split or {}).items()}

        with self._lock:
            # A split build is a hit only when *both* halves are cached; a half
            # that is missing is built while the other is served from disk.
            if split is None:
                cached = self.cache.get(key)
                halves = {}
            else:
                halves = {n: self.cache.get(k) for n, k in part_keys.items()}
                cached = (merge_reports(halves, part_keys)
                          if all(v is not None for v in halves.values()) else None)
            if cached is not None:
                job = Job(id=_new_id(), kind=kind, cache_key=key, params_hash=digest,
                          state="complete", status="served from cache", cached=True,
                          part_keys=part_keys, report=cached,
                          started_at=time.time(), finished_at=time.time(),
                          client=client, session_id=session_id)
                self._register(job)
                return job

            existing_id = self._by_key.get(key)
            if existing_id is not None:
                existing = self._jobs.get(existing_id)
                if existing is not None and not existing.terminal:
                    existing.waiters += 1
                    return existing

            job = Job(id=_new_id(), kind=kind, cache_key=key, params_hash=digest,
                      part_keys=part_keys, client=client, session_id=session_id)
            self._register(job)
            self._by_key[key] = job.id
            # an entry a job is about to hand out must survive a cache sweep
            for pinned in (part_keys.values() if split else (key,)):
                self.cache.pin(pinned)

        def payload_for(params, storage_key):
            return {
                "params": params.model_dump(mode="json"),
                "quality": params.quality.mode,
                "parts": params.mold.parts.model_dump(),
                "formats": list(formats),
                "outdir": str(self.cache.dir_for(storage_key)),
            }

        if split is None:
            args = (job, {None: payload_for(effective_params, key)}, {None: key}, {})
        else:
            # Only the halves that are not already on disk are dispatched; the
            # rest are handed straight to the merge.
            todo = {n: payload_for(params, part_keys[n])
                    for n, (params, _) in split.items() if halves.get(n) is None}
            ready = {n: r for n, r in halves.items() if r is not None}
            args = (job, todo, part_keys, ready)

        thread = threading.Thread(target=self._run, args=args, daemon=True)
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
    def _run(self, job: Job, payloads: dict, keys: dict, ready: dict) -> None:
        """Run every outstanding half, in parallel, and merge what comes back.

        `payloads` is keyed by part name (or the single key None for a build
        that was not split), `ready` holds halves already served from cache.
        """
        if job.cancel.is_set():
            self._finish(job, state="cancelled",
                         error=JobError(CANCELLED, PUBLIC_MESSAGE[CANCELLED]))
            return
        job.state = "running"
        job.status = "building geometry"
        job.started_at = time.time()
        self._emit(job)

        # Each half reports its own 0-1; the job's fraction is their weighted
        # mean, weighted by how long each half is expected to take. A plain
        # average would run ahead, because the plug is roughly three times the
        # cavity. A half already on disk is simply done.
        weights = {name: _half_weight(name, payloads.get(name)) for name in payloads}
        for name in ready:
            weights.setdefault(name, _half_weight(name, None))
        total_weight = sum(weights.values()) or 1.0
        fractions = {name: 1.0 for name in ready}
        lock = threading.Lock()

        def report(name):
            def on_progress(frame: dict) -> None:
                value = frame.get("fraction")
                if not isinstance(value, (int, float)):
                    return
                with lock:
                    fractions[name] = min(1.0, max(0.0, float(value)))
                    combined = sum(fractions.get(n, 0.0) * w
                                   for n, w in weights.items()) / total_weight
                    if job.progress is None or combined > job.progress:
                        job.progress = round(combined, 4)
                    job.stage = frame.get("stage")
                    job.status = frame.get("label") or job.status
                self._emit(job)
            return on_progress

        pool = self._pool or get_pool()
        results: dict = dict(ready)
        failures: list[WorkerFailure] = []
        dispatched = time.perf_counter()

        def run_one(name, payload):
            try:
                results[name] = pool.run(payload, cancel=job.cancel, timeout=self.timeout,
                                         on_progress=report(name))
            except WorkerFailure as failure:
                failures.append(failure)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("unexpected job failure")
                failures.append(WorkerFailure("geometry_build_error",
                                              "the build failed for an unexpected reason"))

        # One half stays on this thread: with a two-worker pool, handing both
        # halves to other threads would leave this one blocked on a join for no
        # reason, and a single-half build would pay a thread for nothing.
        items = list(payloads.items())
        threads = [threading.Thread(target=run_one, args=item, daemon=True)
                   for item in items[1:]]
        for thread in threads:
            thread.start()
        if items:
            run_one(*items[0])
        for thread in threads:
            thread.join()

        if failures:
            # Cancellation is the user's decision and outranks a build error
            # from the other half, which is usually a consequence of it.
            failure = next((f for f in failures if f.kind == CANCELLED), failures[0])
            state = "cancelled" if failure.kind == CANCELLED else "failed"
            self._finish(job, state=state,
                         error=JobError(failure.kind, failure.message, failure.diagnostics))
            return

        if None in results:                       # not split
            report_out = results[None]
            self.cache.put(job.cache_key, report_out)
        else:
            for name, half in results.items():
                if name not in ready:
                    self.cache.put(keys[name], half)
            report_out = merge_reports(results, keys)
        report_out.setdefault("timings", {})["worker_roundtrip_s"] = round(
            time.perf_counter() - dispatched, 4
        )
        job.report = report_out
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
        for pinned in (job.part_keys.values() if job.part_keys else (job.cache_key,)):
            self.cache.unpin(pinned)
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
