"""The FastAPI layer.

Thin by construction: it validates transport, hashes, looks in the cache, hands
work to a worker process and serves files.  It contains no CAD logic and never
imports cadquery - the only geometry it touches is through `traymold.api`, whose
cheap half (validate/derive/hash) is pure Python and whose expensive half runs in
a worker.
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncio
import json as _json
import queue as _queue
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from traymold.api import apply_options, environment, json_schema, defaults, validate as core_validate
from traymold.presets import PRESETS
from traymold.version import MODEL_VERSION, SCHEMA_VERSION

from . import analytics
from .cache import ArtifactCache
from .jobs import DEFAULT_FORMATS, Job, JobManager
from .limits import RateLimiter
from .settings import SETTINGS
from .models import (
    AnalyticsEvent,
    ArtifactModel,
    HealthResponse,
    StatsResponse,
    BuildRequest,
    JobResponse,
    PresetSummary,
    SchemaResponse,
    ValidateRequest,
    ValidateResponse,
    VersionResponse,
)
from .policy import policy_diagnostics
from .ui_hints import UI_HINTS
from .version import API_VERSION
from .worker import get_pool, shutdown_pool

log = logging.getLogger("trayapi")

PRESET_TITLES = {
    "ref-4x7": ("Reference 4x7 (STL revision)",
                "The reference pair with the clamp holes and pry notches present in the STL files."),
    "ref-4x7-step": ("Reference 4x7 (STEP revision)",
                     "The reference shape as exported to STEP: no clamp holes, no pry notches."),
}


def create_app(
    cache: ArtifactCache | None = None,
    warm: bool = True,
    jobs: JobManager | None = None,
    limiter: RateLimiter | None = None,
    sweep: bool = True,
) -> FastAPI:
    stop_sweeper = threading.Event()

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        if warm:
            # pre-import the geometry core in the workers: 3.1 s once at startup
            # rather than on the first request, where it would dominate a preview
            get_pool()
        sweeper = None
        if sweep:
            sweeper = threading.Thread(target=_sweep_loop, args=(app_, stop_sweeper), daemon=True)
            sweeper.start()
        yield
        stop_sweeper.set()
        if sweeper is not None:
            sweeper.join(timeout=2.0)
        shutdown_pool()

    app = FastAPI(title="traymold API", version=API_VERSION, lifespan=lifespan)
    app.state.limiter = limiter or RateLimiter()
    app.state.analytics_limiter = RateLimiter(
        requests=SETTINGS.analytics_rate_limit, window_s=SETTINGS.analytics_rate_window_s
    )
    app.state.jobs = jobs or JobManager(cache=cache)

    def _finished(job: Job) -> None:
        if job.client:
            app.state.limiter.release(job.client)
        _record_job_finished(job)

    app.state.jobs.on_finish = _finished
    app.state.started_at = time.time()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(SETTINGS.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
    )

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        """A parameter document is a few kB.  Reject anything absurd before it is
        read, rather than buffering it to find out."""
        declared = request.headers.get("content-length")
        if declared is not None and int(declared) > SETTINGS.max_request_bytes:
            return Response(
                content=_json.dumps({"detail": "request body too large"}),
                status_code=413, media_type="application/json",
            )
        return await call_next(request)

    # -- metadata ----------------------------------------------------------
    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Lightweight: no geometry, no worker round-trip.  Reports whether a
        pool exists and how many workers are idle right now."""
        pool = _peek_pool()
        return HealthResponse(
            status="ok",
            api_version=API_VERSION,
            uptime_s=round(time.time() - app.state.started_at, 1),
            workers={
                "configured": SETTINGS.workers,
                "started": pool.spawned if pool else 0,
                "idle": pool.idle_count if pool else 0,
                "pool_ready": pool is not None,
            },
            cache=app.state.jobs.cache.stats().as_dict(),
            limits=app.state.limiter.snapshot(),
        )

    @app.get("/api/version", response_model=VersionResponse)
    def version() -> VersionResponse:
        env = environment()
        return VersionResponse(api_version=API_VERSION, **env)

    @app.get("/api/schema", response_model=SchemaResponse)
    def schema() -> SchemaResponse:
        return SchemaResponse(
            schema_version=SCHEMA_VERSION,
            model_version=MODEL_VERSION,
            json_schema=json_schema(),
            defaults=defaults(),
            ui_hints=UI_HINTS,
        )

    @app.get("/api/presets", response_model=list[PresetSummary])
    def presets() -> list[PresetSummary]:
        out = []
        for name, params in PRESETS.items():
            title, description = PRESET_TITLES.get(name, (name, ""))
            out.append(PresetSummary(name=name, title=title, description=description,
                                     params=params.model_dump(mode="json")))
        return out

    # -- validation --------------------------------------------------------
    @app.post("/api/validate", response_model=ValidateResponse)
    def validate(request: ValidateRequest) -> ValidateResponse:
        """Cheap and geometry-free: no solid is built, no worker is used."""
        effective = _effective(request)
        result = core_validate(effective)
        diagnostics = result.diagnostics + policy_diagnostics(effective, request.allow_experimental)
        return ValidateResponse(
            valid=not any(d["severity"] == "error" for d in diagnostics),
            diagnostics=diagnostics,
            derived=result.derived,
            params_hash=result.params_hash,
            schema_version=result.schema_version,
            model_version=result.model_version,
        )

    # -- jobs --------------------------------------------------------------
    @app.post("/api/preview", response_model=JobResponse, status_code=202)
    def preview(request: BuildRequest, response: Response, http: Request) -> JobResponse:
        return _submit(app, "preview", request, response, _client(http), request.session_id)

    @app.post("/api/export", response_model=JobResponse, status_code=202)
    def export(request: BuildRequest, response: Response, http: Request) -> JobResponse:
        return _submit(app, "export", request, response, _client(http), request.session_id)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str):
        """Server-sent events for one job.

        The job manager pushes on every state transition, so the browser learns
        that a build finished the instant the worker returns - no polling loop on
        either side.  `GET /api/jobs/{id}` remains the fallback for a dropped
        connection or an API restart.
        """
        found = app.state.jobs.get(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return StreamingResponse(
            _event_stream(app.state.jobs, found),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no",
                     "connection": "keep-alive"},
        )

    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
    def job(job_id: str) -> JobResponse:
        found = app.state.jobs.get(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return _job_response(found)

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel(job_id: str) -> JobResponse:
        found = app.state.jobs.cancel(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return _job_response(found)

    # -- artifacts ---------------------------------------------------------
    @app.get("/api/artifacts/{key}/bundle.zip")
    def bundle(key: str, s: str | None = None, v: str | None = None):
        path = app.state.jobs.cache.bundle(key)
        if path is None:
            raise HTTPException(status_code=404, detail="unknown build")
        # Recorded only once the file exists and is about to be served, so a
        # probe for a key that is not there cannot inflate anything.
        _safe(analytics.record_download, key, "bundle.zip", session_id=s, visitor_id=v)
        return FileResponse(path, media_type="application/zip", filename="tray-mold.zip")

    @app.get("/api/artifacts/{key}/{name}")
    def artifact(key: str, name: str, s: str | None = None, v: str | None = None):
        path = app.state.jobs.cache.artifact_path(key, name)
        if path is None:
            raise HTTPException(status_code=404, detail="unknown artifact")
        _safe(analytics.record_download, key, name, session_id=s, visitor_id=v)
        return FileResponse(path, media_type=_media_type(path), filename=path.name)

    # -- usage analytics ---------------------------------------------------
    @app.get("/api/stats", response_model=StatsResponse)
    def stats() -> StatsResponse:
        """Public counters. Safe to display; nothing here identifies anyone."""
        try:
            return StatsResponse(**analytics.public_stats())
        except Exception:  # pragma: no cover
            log.warning("stats query failed", exc_info=True)
            return StatsResponse(custom_molds_generated=0, unique_designs_downloaded=0,
                                 total_artifact_downloads=0)

    @app.post("/api/analytics/event", status_code=204)
    def analytics_event(event: AnalyticsEvent, http: Request) -> Response:
        """The four events a browser is allowed to report.

        Client telemetry describes the funnel and never the counter: no event
        accepted here can create a qualified usage. The event name is a closed
        enum on the model, so an unknown name is a 422 rather than a new row.
        """
        if not app.state.analytics_limiter.check_rate(_client(http)).allowed:
            # Telemetry is not worth a retry storm; refuse quietly.
            return Response(status_code=204)
        _safe(
            analytics.record_client_event,
            event.event, event.session_id, event.visitor_id,
            source=event.source, medium=event.medium, campaign=event.campaign,
            referrer=event.referrer, landing_path=event.landing_path,
        )
        return Response(status_code=204)

    @app.get("/", include_in_schema=False)
    def harness():
        """A developer harness, not the product UI.  Enough to submit parameters,
        watch a job and look at the GLB while the real front end is built."""
        page = Path(__file__).resolve().parents[1] / "harness" / "dev_harness.html"
        if not page.exists():
            raise HTTPException(status_code=404, detail="harness not installed")
        return FileResponse(page, media_type="text/html")

    return app


# --------------------------------------------------------------------------
def _effective(request: ValidateRequest):
    parts = request.parts.to_selection() if request.parts else None
    return apply_options(request.params, request.quality, parts)


TERMINAL = ("complete", "failed", "cancelled")
HEARTBEAT_S = 15.0


async def _event_stream(jobs: JobManager, job: Job):
    channel = jobs.subscribe(job.id)
    try:
        yield _sse(_job_response(job))
        if job.terminal:
            return
        while True:
            try:
                updated = await asyncio.to_thread(channel.get, True, HEARTBEAT_S)
            except _queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield _sse(_job_response(updated))
            if updated.state in TERMINAL:
                return
    finally:
        jobs.unsubscribe(job.id, channel)


def _sse(payload) -> str:
    body = payload.model_dump_json() if hasattr(payload, "model_dump_json") else _json.dumps(payload)
    state = payload.state if hasattr(payload, "state") else "update"
    return f"event: {state}\ndata: {body}\n\n"


def _safe(call, *args, **kwargs) -> None:
    """Run an analytics call and swallow anything it throws.

    The analytics package already handles its own errors; this is the second
    wall. Serving a file must not depend on a future change over there staying
    well-behaved, and a counter is never worth a 500 on a download.
    """
    try:
        call(*args, **kwargs)
    except Exception:  # pragma: no cover - the point is that nothing escapes
        log.warning("analytics call failed; continuing", exc_info=True)


def _client(http: Request) -> str:
    forwarded = http.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return http.client.host if http.client else "unknown"


def _peek_pool():
    import trayapi.worker as worker_module

    return worker_module._POOL


def _sweep_loop(app: FastAPI, stop: threading.Event) -> None:
    while not stop.wait(SETTINGS.cache_sweep_interval_s):
        try:
            app.state.jobs.cache.sweep()
        except Exception:  # pragma: no cover
            log.exception("cache sweep failed")


def _record_job_finished(job: Job) -> None:
    """A build reaching a terminal state, recorded from the job itself.

    Server-side and after the fact: the duration and the outcome are the job's,
    not something a browser reported about itself.
    """
    if job.state == "cancelled":
        return
    duration = None
    if job.started_at and job.finished_at:
        duration = int((job.finished_at - job.started_at) * 1000)
    _safe(
        analytics.record_build_event,
        f"{job.kind}_{'completed' if job.state == 'complete' else 'failed'}",
        session_id=job.session_id, config_hash=job.params_hash, job_id=job.id,
        duration_ms=duration, error_code=job.error.kind if job.error else None,
    )


def _submit(app: FastAPI, kind: str, request: BuildRequest, response: Response,
            client: str = "unknown", session_id: str | None = None) -> JobResponse:
    effective = _effective(request.model_copy(update={"quality": request.quality or kind}))
    result = core_validate(effective)
    diagnostics = result.diagnostics + policy_diagnostics(effective, request.allow_experimental)
    if any(d["severity"] == "error" for d in diagnostics):
        # invalid parameters never reach a worker
        raise HTTPException(status_code=422, detail={
            "error": {"kind": "validation_error", "message": "the parameters are not valid",
                      "diagnostics": diagnostics}})
    rate = app.state.limiter.check_rate(client)
    if not rate.allowed:
        raise _too_many(rate)

    job = app.state.jobs.submit(kind, effective, request.formats or DEFAULT_FORMATS[kind],
                                client, session_id)
    # The cache key is what an artifact URL carries, so this is the row that
    # lets a later download be attributed without rebuilding any geometry. A
    # split preview has one key per half, and a download names one of those.
    for storage_key in (job.part_keys.values() if job.part_keys else (job.cache_key,)):
        _safe(analytics.record_design, storage_key, job.params_hash, effective,
              effective.quality.mode)
    _safe(
        analytics.record_build_event,
        f"{kind}_requested", session_id=session_id, config_hash=job.params_hash,
        job_id=job.id, params=effective,
    )
    if job.state == "complete":
        # a cache hit costs nothing and occupies no worker
        #
        # It also never reaches on_finish, because nothing ran - so the
        # completion is recorded here instead. Without this the funnel would
        # count the request and lose the success, and since the artifact cache
        # is content-addressed and long-lived that is the common path, not a
        # corner: "successful previews" would read far below the truth and the
        # failure rate far above it.
        _safe(
            analytics.record_build_event,
            f"{kind}_completed", session_id=session_id, config_hash=job.params_hash,
            job_id=job.id, params=effective,
            # No duration: nothing was built, and a 4 ms file read among the
            # build times would make the median a measure of cache hit rate.
            duration_ms=None,
        )
        response.status_code = 200
        return _job_response(job)
    if job.waiters == 1:
        # a genuinely new build; a request that attached to one already running
        # occupies no extra worker and is not counted
        slot = app.state.limiter.try_acquire(client)
        if not slot.allowed:
            app.state.jobs.cancel(job.id)
            raise _too_many(slot)
    return _job_response(job)


def _too_many(decision) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={"error": {"kind": "rate_limited", "message": decision.reason, "diagnostics": []}},
        headers={"retry-after": str(max(1, int(decision.retry_after_s)))},
    )


def _job_response(job: Job) -> JobResponse:
    report = job.report or {}
    artifacts = {}
    for entry in report.get("artifacts", []):
        # A split preview's halves live in two cache directories, so the URL has
        # to name the one this artifact is actually in.
        key = entry.get("cache_key") or job.cache_key
        artifacts[entry["name"]] = ArtifactModel(
            name=entry["name"], format=entry["format"], part=entry["part"],
            bytes=entry["bytes"], sha256=entry["sha256"],
            url=f"/api/artifacts/{key}/{entry['name']}",
        )
    return JobResponse(
        id=job.id,
        state=job.state,
        kind=job.kind,
        progress=job.progress,
        stage=job.stage,
        status=job.status,
        params_hash=job.params_hash,
        cache_key=job.cache_key,
        cached=job.cached,
        artifacts=artifacts,
        # No bundle for a split build: its artifacts are in two directories and
        # there is no single entry to zip. Exports are never split, so the one
        # place a bundle is actually used still has one.
        bundle_url=(f"/api/artifacts/{job.cache_key}/bundle.zip"
                    if artifacts and not job.part_keys else None),
        diagnostics=report.get("diagnostics", []),
        derived=report.get("derived", {}),
        volumes_cm3=report.get("volumes_cm3", {}),
        timings=report.get("timings", {}),
        error=job.error.as_dict() if job.error else None,
    )


def _media_type(path: Path) -> str:
    return {
        ".glb": "model/gltf-binary",
        ".stl": "model/stl",
        ".step": "application/step",
        ".json": "application/json",
        ".zip": "application/zip",
    }.get(path.suffix.lower(), "application/octet-stream")


app = create_app()
