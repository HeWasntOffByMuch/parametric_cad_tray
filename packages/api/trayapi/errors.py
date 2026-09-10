"""Internal error taxonomy.

Every failure a client can see is one of these kinds.  Raw OCC messages and
tracebacks are logged server-side and never returned: they leak implementation
detail and are meaningless to a caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field

VALIDATION_ERROR = "validation_error"
GEOMETRY_BUILD_ERROR = "geometry_build_error"
OFFSET_VERIFICATION_FAILURE = "offset_verification_failure"
TIMEOUT = "timeout"
WORKER_CRASH = "worker_crash"
EXPORT_FAILURE = "export_failure"
CANCELLED = "cancelled"

KINDS = (
    VALIDATION_ERROR,
    GEOMETRY_BUILD_ERROR,
    OFFSET_VERIFICATION_FAILURE,
    TIMEOUT,
    WORKER_CRASH,
    EXPORT_FAILURE,
    CANCELLED,
)

#: Messages a client may see, per kind.  Deliberately free of OCC vocabulary.
PUBLIC_MESSAGE = {
    GEOMETRY_BUILD_ERROR: "the geometry kernel could not build this parameter set",
    OFFSET_VERIFICATION_FAILURE: "the forming-gap offset did not come out at the requested distance",
    TIMEOUT: "the build exceeded its time budget",
    WORKER_CRASH: "the build worker terminated unexpectedly",
    EXPORT_FAILURE: "the geometry built but an artifact could not be written",
    CANCELLED: "the job was cancelled",
}


@dataclass(frozen=True)
class JobError:
    kind: str
    message: str
    diagnostics: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "diagnostics": list(self.diagnostics)}


def classify(exc: BaseException) -> tuple[str, str, list[dict]]:
    """Map an exception raised inside a worker to (kind, public message, diagnostics).

    Runs in the worker, where traymold is imported.  The caller sends only the
    tuple back; the traceback stays in the worker's log.
    """
    from dataclasses import asdict

    from traymold.mold import BuildError
    from traymold.profiles import OffsetError, ProfileError
    from traymold.validate import ValidationError

    if isinstance(exc, ValidationError):
        return VALIDATION_ERROR, str(exc), [asdict(d) for d in exc.diagnostics]
    if isinstance(exc, OffsetError):
        return OFFSET_VERIFICATION_FAILURE, PUBLIC_MESSAGE[OFFSET_VERIFICATION_FAILURE], []
    if isinstance(exc, ProfileError):
        return GEOMETRY_BUILD_ERROR, str(exc), []
    # A BuildError is a boolean invariant refusing a result, and its message
    # names the step that failed and the one setting to change. Falling through
    # to the generic sentence below threw all of that away: someone who picked
    # an ellipse was told "the geometry kernel could not build this parameter
    # set" when the code knew, and had written down, that the root blend was the
    # problem and that turning it off builds the mold.
    if isinstance(exc, BuildError):
        return GEOMETRY_BUILD_ERROR, str(exc), []
    name = type(exc).__name__
    if "Export" in name or "IOError" in name or isinstance(exc, OSError):
        return EXPORT_FAILURE, PUBLIC_MESSAGE[EXPORT_FAILURE], []
    return GEOMETRY_BUILD_ERROR, PUBLIC_MESSAGE[GEOMETRY_BUILD_ERROR], []
