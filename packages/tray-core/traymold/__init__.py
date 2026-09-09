"""traymold - deterministic parametric leather wet-mold geometry.

The public surface deliberately mirrors the dependency order documented in
docs/architecture.md: base profile -> forming gap -> raw solids -> edge
treatments -> manufacturing features.
"""

from .derive import Derived, derive, forming_gap
from .mold import (
    MoldResult,
    apply_female_entry_blend,
    apply_features,
    apply_male_floor_blend,
    apply_male_root_blend,
    build,
    build_female_from_profile,
    build_male_from_profile,
    make_base_profile,
    make_female_profile,
    make_male_profile,
)
from .params import Params
from .presets import PRESETS
from .profiles import (
    OffsetError,
    ProfileError,
    curvature_limits,
    offset_profile,
    sample_wire,
)
from .quality import Quality, resolve as resolve_quality
from .validate import Diagnostic, ValidationError, validate
from .version import MODEL_VERSION, SCHEMA_VERSION

__all__ = [
    "Params", "PRESETS", "build", "MoldResult",
    "make_base_profile", "make_male_profile", "make_female_profile",
    "build_male_from_profile", "build_female_from_profile",
    "apply_male_root_blend", "apply_male_floor_blend", "apply_female_entry_blend",
    "apply_features", "offset_profile", "sample_wire",
    "derive", "Derived", "forming_gap",
    "ProfileError", "OffsetError", "curvature_limits",
    "validate", "Diagnostic", "ValidationError",
    "Quality", "resolve_quality",
    "SCHEMA_VERSION", "MODEL_VERSION",
]
