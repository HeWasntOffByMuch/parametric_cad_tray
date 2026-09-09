"""API request and response models.

These describe the *transport*, not the geometry.  The one authoritative
parameter schema stays in `traymold.params`; `BuildRequest.params` is that model,
imported, not restated.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from traymold.params import Params, PartSelection


class PartsRequest(BaseModel):
    male: bool = True
    female: bool = True

    def to_selection(self) -> PartSelection:
        return PartSelection(male=self.male, female=self.female)


class ValidateRequest(BaseModel):
    params: Params
    quality: Literal["preview", "export"] | None = None
    parts: PartsRequest | None = None
    allow_experimental: bool = Field(
        default=False,
        description="permit parameters marked experimental, currently nonzero draft_angle",
    )


class BuildRequest(ValidateRequest):
    #: Opaque anonymous session id from the browser, used only to attribute this
    #: build to a funnel. Optional, bounded, and never required for a build.
    session_id: str | None = Field(default=None, max_length=64)
    formats: list[Literal["glb", "step", "stl"]] | None = Field(
        default=None, description="defaults per endpoint: preview -> glb, export -> step+stl"
    )


class DiagnosticModel(BaseModel):
    code: str
    severity: str
    field: str
    message: str


class ValidateResponse(BaseModel):
    valid: bool
    diagnostics: list[DiagnosticModel]
    derived: dict[str, Any]
    params_hash: str
    schema_version: str
    model_version: str


class ArtifactModel(BaseModel):
    name: str
    format: str
    part: str
    bytes: int
    sha256: str
    url: str


class JobResponse(BaseModel):
    id: str
    state: Literal["queued", "running", "complete", "failed", "cancelled"]
    kind: Literal["preview", "export"]
    #: 0.0-1.0 as each build stage finishes; null before the first one lands and
    #: on a cache hit, where nothing was built to be partway through.
    progress: float | None = None
    #: The stage id behind that fraction - see traymold.progress.LABELS.
    stage: str | None = None
    status: str | None = None
    params_hash: str | None = None
    cache_key: str | None = None
    cached: bool = False
    artifacts: dict[str, ArtifactModel] = Field(default_factory=dict)
    bundle_url: str | None = None
    diagnostics: list[DiagnosticModel] = Field(default_factory=list)
    derived: dict[str, Any] = Field(default_factory=dict)
    volumes_cm3: dict[str, float] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class AnalyticsEvent(BaseModel):
    """The closed set of events a browser may report.

    `event` is a Literal, so an unrecognised name is rejected by validation
    rather than becoming a row. Every field is length-bounded: this endpoint is
    public and takes no arbitrary JSON.
    """

    event: Literal["app_opened", "config_engaged", "share_link_copied", "makerworld_clicked"]
    session_id: str | None = Field(default=None, max_length=64)
    visitor_id: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=64)
    medium: str | None = Field(default=None, max_length=64)
    campaign: str | None = Field(default=None, max_length=64)
    #: A full URL is accepted but only its hostname is ever stored.
    referrer: str | None = Field(default=None, max_length=512)
    landing_path: str | None = Field(default=None, max_length=128)


class StatsResponse(BaseModel):
    """Public counters. Nothing here is per-visitor or reversible."""

    custom_molds_generated: int
    unique_designs_downloaded: int
    total_artifact_downloads: int


class HealthResponse(BaseModel):
    status: Literal["ok"]
    api_version: str
    uptime_s: float
    workers: dict[str, Any]
    cache: dict[str, Any]
    limits: dict[str, Any]


class VersionResponse(BaseModel):
    api_version: str
    schema_version: str
    model_version: str
    cadquery: str
    OCP: str


class SchemaResponse(BaseModel):
    schema_version: str
    model_version: str
    json_schema: dict[str, Any]
    defaults: dict[str, Any]
    ui_hints: dict[str, Any]


class PresetSummary(BaseModel):
    name: str
    title: str
    description: str
    params: dict[str, Any]
