"""The frozen application-facing interface.

Everything an application needs from this package goes through here.  Callers do
not touch `mold`, `profiles` or `blends`, and above all they do not touch
CadQuery or OCC.

Three operations, deliberately separate:

    validate(params)            -> ValidationResult   cheap, no geometry
    build(params, ...)          -> BuildResult        owns the OCC solids
    emit(result, outdir, ...)   -> dict[str, Artifact] turns solids into files

`BuildResult` carries live OCC objects, so it never leaves the process that made
it.  `emit` is separate so a worker can build once and write several formats, and
so tests can build without touching the filesystem.  Anything that must cross a
process boundary is `BuildReport` (below): plain data plus artifact paths.

Pickling a `cq.Solid` was measured and *does* work - 128 KB, exact volume
roundtrip - so passing solids between processes is safe.  It is not useful: the
caller only ever wants artifacts, and receiving a solid would force the parent
process to import cadquery (3.1 s) and hold OCC objects in its event loop.  The
worker that owns the solids writes the files.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

from .derive import derive
from .mold import MoldResult, build as _build
from .params import Params, PartSelection
from .quality import Quality, resolve as _resolve_quality
from .validate import Diagnostic, validate as _validate
from .version import MODEL_VERSION, SCHEMA_VERSION, kernel_versions

Quality_ = Literal["preview", "export"]
Format = Literal["glb", "step", "stl"]

#: Fields that name or describe a design without changing its geometry.  Excluded
#: from the hash so two users who type different names share one build.
NON_GEOMETRIC_FIELDS = ("name",)


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    diagnostics: list[dict]
    derived: dict
    params_hash: str
    schema_version: str
    model_version: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Artifact:
    name: str
    format: str
    part: str  # "male" | "female" | "assembly"
    path: str
    bytes: int
    sha256: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class BuildResult:
    """Carries live OCC solids.  Never cross a process boundary with this."""

    params_hash: str
    schema_version: str
    model_version: str
    quality: str
    parts: dict
    diagnostics: list[dict]
    derived: dict
    stats: dict
    male: Any = None
    female: Any = None

    def metadata(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("male", "female")}
        d["volumes_cm3"] = self.volumes
        return d

    @property
    def volumes(self) -> dict:
        from .mold import _volume

        return {
            f"{name}_cm3": _volume(shape) / 1000.0
            for name, shape in (("male", self.male), ("female", self.female))
            if shape is not None
        }


@dataclass
class BuildReport:
    """The serializable result of build + emit.  This is what crosses processes."""

    params_hash: str
    schema_version: str
    model_version: str
    quality: str
    parts: dict
    diagnostics: list[dict]
    derived: dict
    stats: dict
    volumes_cm3: dict
    artifacts: list[dict] = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# canonical hashing
# --------------------------------------------------------------------------
def canonical_params(params: Params) -> dict:
    """Parameters reduced to the values that determine geometry."""
    data = params.model_dump(mode="json")
    for key in NON_GEOMETRIC_FIELDS:
        data.pop(key, None)
    return data


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def environment() -> dict:
    """Versions that change geometry for unchanged parameters.

    Read from the module rather than captured at import time, so a deliberate
    bump - or a test that simulates one - invalidates every cache key.
    """
    from . import version as _version

    return {
        "schema_version": _version.SCHEMA_VERSION,
        "model_version": _version.MODEL_VERSION,
        **_version.kernel_versions(),
    }


def params_hash(params: Params, **extra) -> str:
    """Content address of a design.  Includes the versions that change geometry."""
    payload = {"params": canonical_params(params), "env": environment(), **extra}
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------
def apply_options(
    params: Params,
    quality: Quality_ | None = None,
    parts: PartSelection | dict | None = None,
) -> Params:
    """Fold caller-supplied quality/parts into the parameter document.

    This is what makes `build(params, quality="preview")` and
    `params.with_quality("preview")` hash identically: there is one effective
    parameter document, and the cache key is taken from it.
    """
    out = params
    if quality is not None:
        out = out.with_quality(quality)
    if parts is not None:
        selection = parts if isinstance(parts, PartSelection) else PartSelection(**parts)
        out = out.model_copy(update={"mold": out.mold.model_copy(update={"parts": selection})})
    return out


def validate(params: Params, quality: Quality_ | None = None, parts=None) -> ValidationResult:
    """Cheap check.  Builds a 2D profile at most; never a solid."""
    effective = apply_options(params, quality, parts)
    diagnostics = _validate(effective)
    return ValidationResult(
        valid=not any(d.severity == "error" for d in diagnostics),
        diagnostics=[asdict(d) for d in diagnostics],
        derived=derive(effective).as_dict(),
        params_hash=params_hash(effective),
        schema_version=SCHEMA_VERSION,
        model_version=MODEL_VERSION,
    )


def build(params: Params, quality: Quality_ | None = None, parts=None) -> BuildResult:
    """Build the solids.  Raises `ValidationError` if the parameters are invalid."""
    effective = apply_options(params, quality, parts)
    result: MoldResult = _build(effective)
    return BuildResult(
        params_hash=params_hash(effective),
        schema_version=SCHEMA_VERSION,
        model_version=MODEL_VERSION,
        quality=effective.quality.mode,
        parts=effective.mold.parts.model_dump(),
        diagnostics=[asdict(d) for d in _validate(effective)],
        derived=result.derived,
        stats=result.stats or {},
        male=result.male,
        female=result.female,
    )


def emit(
    result: BuildResult,
    outdir: str | Path,
    formats: Sequence[Format] = ("glb",),
    *,
    quality: Quality | None = None,
) -> list[Artifact]:
    """Write artifacts for an already-built result.  Separate from `build` on
    purpose: one build can serve several formats, and a build with no filesystem
    is a useful thing for tests."""
    from .exporters import write_artifacts

    return write_artifacts(result, Path(outdir), formats, quality=quality)


def build_and_emit(
    params: Params,
    quality: Quality_,
    parts,
    formats: Sequence[Format],
    outdir: str | Path,
) -> BuildReport:
    """build + emit in one call, returning only serializable data.

    This is the unit of work a worker process performs.  The OCC solids are
    created, used and released inside the caller's process; only the report and
    the files on disk leave it.
    """
    import time

    effective = apply_options(params, quality, parts)
    t0 = time.perf_counter()
    result = build(effective)
    t_build = time.perf_counter() - t0
    t0 = time.perf_counter()
    artifacts = emit(result, outdir, formats, quality=_resolve_quality(effective))
    t_emit = time.perf_counter() - t0
    return BuildReport(
        params_hash=result.params_hash,
        schema_version=result.schema_version,
        model_version=result.model_version,
        quality=result.quality,
        parts=result.parts,
        diagnostics=result.diagnostics,
        derived=result.derived,
        stats=result.stats,
        volumes_cm3=result.volumes,
        artifacts=[a.as_dict() for a in artifacts],
        timings={"build_s": round(t_build, 4), "emit_s": round(t_emit, 4)},
    )


def json_schema() -> dict:
    return Params.model_json_schema()


def defaults() -> dict:
    return Params().model_dump(mode="json")
