"""What makes a configuration "custom", and which of its numbers are worth
keeping.

The public counter turns on this definition, so it is deliberately one function
with one rule, and it reads the backend's canonical parameters rather than
anything the browser claims.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

#: Excluded from the comparison because changing one of these does not change
#: the mold: a name is presentation, quality is preview fidelity, and parts is
#: which halves this particular export asked for.
NON_GEOMETRIC = ("name", "schema_version", "quality")
NON_GEOMETRIC_NESTED = (("mold", "parts"),)


def _strip(data: dict) -> dict:
    out = {k: v for k, v in data.items() if k not in NON_GEOMETRIC}
    for parent, child in NON_GEOMETRIC_NESTED:
        if isinstance(out.get(parent), dict):
            out[parent] = {k: v for k, v in out[parent].items() if k != child}
    return out


@lru_cache(maxsize=1)
def _baselines() -> tuple[str, ...]:
    """Every configuration a user can arrive at without deciding anything.

    That is the schema's own defaults plus each shipped preset - the landing
    state is a preset, so a download of an untouched preset is not a custom
    mold, however many parameters it happens to differ from `Params()` by.
    """
    from traymold.api import canonical_json
    from traymold.params import Params
    from traymold.presets import PRESETS

    seen = [Params().model_dump(mode="json")]
    for preset in PRESETS.values():
        seen.append(preset.model_dump(mode="json"))
    return tuple(canonical_json(_strip(d)) for d in seen)


def is_custom_configuration(params: Any) -> bool:
    """True when the design differs from every baseline in some geometry field.

    `params` may be a `Params` model or an already-dumped dict; the API has one
    and workers hand back the other.
    """
    from traymold.api import canonical_json

    data = params if isinstance(params, dict) else params.model_dump(mode="json")
    return canonical_json(_strip(data)) not in _baselines()


def preset_name(params: Any) -> str | None:
    """The shipped preset this configuration matches exactly, if any."""
    from traymold.api import canonical_json
    from traymold.presets import PRESETS

    data = params if isinstance(params, dict) else params.model_dump(mode="json")
    target = canonical_json(_strip(data))
    for name, preset in PRESETS.items():
        if canonical_json(_strip(preset.model_dump(mode="json"))) == target:
            return name
    return None


def dimensions(params: Any) -> dict:
    """The handful of inputs worth analysing, pulled out as columns.

    Deliberately not every geometry field: these are the ones a product question
    is actually asked about - what size do people make, how thick is their
    leather, how much gap do they leave.
    """
    data = params if isinstance(params, dict) else params.model_dump(mode="json")
    tray = data.get("tray") or {}
    profile = tray.get("profile") or {}
    leather = data.get("leather") or {}
    fit = data.get("fit") or {}

    thickness = _num(leather.get("thickness"))
    compression = _num(leather.get("compression")) or 0.0
    clearance = _num(fit.get("clearance")) or 0.0
    override = _num(fit.get("gap_override"))
    # The same formula the core derives the gap from; recomputed here only so a
    # download row can be read without joining to a build report.
    gap = override if override is not None else (
        None if thickness is None else thickness * (1.0 - compression) + clearance
    )

    return {
        "profile_kind": profile.get("kind"),
        "tray_length_mm": _num(profile.get("length")),
        "tray_width_mm": _num(profile.get("width")),
        "tray_depth_mm": _num(tray.get("depth")),
        "leather_thickness_mm": thickness,
        "leather_compression": compression,
        "forming_gap_mm": None if gap is None else round(gap, 4),
    }


def _num(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
