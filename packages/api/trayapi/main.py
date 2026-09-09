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

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse

from traymold.api import apply_options, environment, json_schema, defaults, validate as core_validate
from traymold.presets import PRESETS
from traymold.version import MODEL_VERSION, SCHEMA_VERSION

from .cache import ArtifactCache
from .jobs import DEFAULT_FORMATS, Job, JobManager
from .models import (
    ArtifactModel,
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


def create_app(cache: ArtifactCache | None = None, warm: bool = True, jobs: JobManager | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if warm:
            # pre-import the geometry core in the workers: 3.1 s once at startup
            # rather than on the first request, where it would dominate a preview
            get_pool()
        yield
        shutdown_pool()

    app = FastAPI(title="traymold API", version=API_VERSION, lifespan=lifespan)
    app.state.jobs = jobs or JobManager(cache=cache)

    # -- metadata ----------------------------------------------------------
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
    def preview(request: BuildRequest, response: Response) -> JobResponse:
        return _submit(app, "preview", request, response)

    @app.post("/api/export", response_model=JobResponse, status_code=202)
    def export(request: BuildRequest, response: Response) -> JobResponse:
        return _submit(app, "export", request, response)

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
    def bundle(key: str):
        path = app.state.jobs.cache.bundle(key)
        if path is None:
            raise HTTPException(status_code=404, detail="unknown build")
        return FileResponse(path, media_type="application/zip", filename="tray-mold.zip")

    @app.get("/api/artifacts/{key}/{name}")
    def artifact(key: str, name: str):
        path = app.state.jobs.cache.artifact_path(key, name)
        if path is None:
            raise HTTPException(status_code=404, detail="unknown artifact")
        return FileResponse(path, media_type=_media_type(path), filename=path.name)

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


def _submit(app: FastAPI, kind: str, request: BuildRequest, response: Response) -> JobResponse:
    effective = _effective(request.model_copy(update={"quality": request.quality or kind}))
    result = core_validate(effective)
    diagnostics = result.diagnostics + policy_diagnostics(effective, request.allow_experimental)
    if any(d["severity"] == "error" for d in diagnostics):
        # invalid parameters never reach a worker
        raise HTTPException(status_code=422, detail={
            "error": {"kind": "validation_error", "message": "the parameters are not valid",
                      "diagnostics": diagnostics}})
    job = app.state.jobs.submit(kind, effective, request.formats or DEFAULT_FORMATS[kind])
    if job.state == "complete":
        response.status_code = 200
    return _job_response(job)


def _job_response(job: Job) -> JobResponse:
    report = job.report or {}
    artifacts = {}
    for entry in report.get("artifacts", []):
        artifacts[entry["name"]] = ArtifactModel(
            name=entry["name"], format=entry["format"], part=entry["part"],
            bytes=entry["bytes"], sha256=entry["sha256"],
            url=f"/api/artifacts/{job.cache_key}/{entry['name']}",
        )
    return JobResponse(
        id=job.id,
        state=job.state,
        kind=job.kind,
        status=job.status,
        params_hash=job.params_hash,
        cache_key=job.cache_key,
        cached=job.cached,
        artifacts=artifacts,
        bundle_url=f"/api/artifacts/{job.cache_key}/bundle.zip" if artifacts else None,
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
