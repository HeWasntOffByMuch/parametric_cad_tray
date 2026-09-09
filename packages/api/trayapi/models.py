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
    progress: None = None
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
