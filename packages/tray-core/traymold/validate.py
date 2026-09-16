"""Cross-field validation.

Rules are checked arithmetically **before** the kernel is invoked, and each
returns a machine-readable code.  A `try/except` around an OCC call is not
validation; the only exception is the realised-distance verifier in
`profiles.offset_profile`, which is a numerical backstop rather than a rule.

The placement rules are **geometric**, and cannot be arithmetic.  A corner
feature sits diagonally outboard of the plan, where a rounded profile has
already curved away, so the cavity's bounding box says a clamp hole collides
long before the cavity actually reaches it - on the reference obround the box
is 25 mm pessimistic.  The rules below measure against the curve.

The curvature rules here are **direction aware**.  An offset only cusps where it
reaches the local radius of curvature on the side it moves towards, so:

  * the forming gap is an OUTWARD offset of the male base profile, which is
    convex, and is therefore unbounded by curvature - it must never be rejected
    for exceeding the profile's minimum (convex) radius;
  * an edge treatment is an INWARD offset over part of its range, and is bounded
    by that minimum convex radius.
"""

from __future__ import annotations

from dataclasses import dataclass

from functools import lru_cache

import numpy as np

from .derive import derive, forming_gap
from .profiles import curvature_limits, make_base_profile, sample_wire


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str  # "error" | "warning"
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()} {self.code}] {self.field}: {self.message}"


class ValidationError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__("; ".join(str(d) for d in diagnostics))


def validate(params, *, with_geometry: bool = True) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    tray, mold = params.tray, params.mold
    gap = forming_gap(params)

    if tray.datum != "inner":
        out.append(Diagnostic(
            "E-DATUM-001", "error", "tray.datum",
            f"datum {tray.datum!r} is not supported: the canonical datum is the inner "
            "(male) forming profile, and no outer->inner conversion exists yet. "
            "Outer dimensions are never silently reinterpreted as inner ones.",
        ))

    if gap <= 0.0:
        out.append(Diagnostic("E-GAP-020", "error", "leather/fit",
                              f"forming gap must be positive, got {gap:.4f} mm"))
    elif gap < 0.4:
        out.append(Diagnostic("W-GAP-021", "warning", "leather/fit",
                              f"forming gap {gap:.3f} mm is below FDM resolution; the halves may fuse"))

    treatments = {
        "mold.male_root_blend": mold.male_root_blend,
        "mold.male_floor_blend": mold.male_floor_blend,
        "mold.female_entry_blend_top": mold.female_entry_blend_top,
        "mold.female_entry_blend_bottom": mold.female_entry_blend_bottom,
    }
    floor, root = mold.male_floor_blend, mold.male_root_blend
    if floor.active and floor.size > tray.depth / 2.0:
        out.append(Diagnostic("E-BLEND-010", "error", "mold.male_floor_blend",
                              f"setback {floor.size} mm exceeds half the draw depth ({tray.depth / 2} mm)"))
    if floor.active and root.active and floor.size + root.size >= tray.depth:
        out.append(Diagnostic("E-BLEND-015", "error", "mold.male_floor_blend",
                              "root and floor treatments leave no vertical wall on the plug"))
    entry_total = mold.female_entry_blend_top.size + mold.female_entry_blend_bottom.size
    if entry_total > mold.cavity_plate_thickness:
        out.append(Diagnostic("E-BLEND-013", "error", "mold.female_entry_blend_top",
                              "the two cavity entry treatments meet inside the plate"))
    if mold.cavity_plate_thickness < tray.depth:
        out.append(Diagnostic("E-MOLD-040", "error", "mold.cavity_plate_thickness",
                              f"{mold.cavity_plate_thickness} mm is less than the draw depth "
                              f"({tray.depth} mm); the plug would protrude"))
    if mold.flange_width - gap < params.manufacturing.min_wall:
        out.append(Diagnostic("E-MOLD-041", "error", "mold.flange_width",
                              f"female flange would be {mold.flange_width - gap:.2f} mm, "
                              f"below min_wall {params.manufacturing.min_wall} mm"))

    if with_geometry:
        out.extend(_geometric_diagnostics(params, treatments, gap))
    return out


@lru_cache(maxsize=256)
def _limits_for(profile_json: str) -> dict | str:
    """Curvature limits for a profile spec.

    Memoised on the spec's canonical JSON: profile models are immutable, so the
    answer cannot go stale, and validation is called on every keystroke while
    building the 2D profile and reading its curvature costs ~12 ms.
    """
    import json

    from .params import ProfileSpec  # noqa: F401
    from pydantic import TypeAdapter

    spec = TypeAdapter(ProfileSpec).validate_python(json.loads(profile_json))
    try:
        return curvature_limits(make_base_profile(spec))
    except ValueError as exc:
        return str(exc)


@lru_cache(maxsize=256)
def _polyline_for(profile_json: str):
    """The base profile as a closed polyline, for clearance tests.

    Memoised on the spec's canonical JSON for the same reason `_limits_for` is:
    profile models are immutable, and validation runs on every keystroke.
    """
    import json

    from .params import ProfileSpec  # noqa: F401
    from pydantic import TypeAdapter

    spec = TypeAdapter(ProfileSpec).validate_python(json.loads(profile_json))
    try:
        return np.asarray(sample_wire(make_base_profile(spec), 2048))[:, :2]
    except ValueError:
        return None


def _clearance(poly, px: float, py: float, gap: float) -> float:
    """Distance from a point to the **cavity wall**: positive outside, negative in.

    The cavity is `offset(base, gap)`, and every profile family in this schema is
    convex - which is exactly why `max_outward_offset` is infinite.  For a convex
    curve an outward offset moves every boundary point by `gap` along its own
    normal, so the distance to the offset curve is the distance to the base curve
    minus the gap, identically.  `test_validation.py` checks that against a real
    OCC offset on four profile families.

    That identity is the whole reason this rule is affordable: it needs no offset
    at all, so it costs a distance transform over a cached polyline rather than a
    kernel call on every keystroke.
    """
    x, y = poly[:, 0], poly[:, 1]
    distance = float(np.min(np.hypot(x - px, y - py)))
    # even-odd ray cast, to give the distance a sign
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    dy = np.where(y2 == y, np.inf, y2 - y)
    crossings = ((y > py) != (y2 > py)) & (px < (x2 - x) * (py - y) / dy + x)
    inside = bool(int(crossings.sum()) % 2)
    return (-distance if inside else distance) - gap


def _notch_probes(cx: float, cy: float, sx: float, sy: float, sign_x: int, sign_y: int):
    """The inner boundary of a corner rebate, sampled.

    A notch is open to two plate edges, so only its inner L can approach the
    cavity.  For the convex plan curves this schema has, the inner corner is
    always the nearest point of that L, so sampling the edges as well is
    defensive rather than load-bearing - it costs a few dozen distance
    evaluations and it does not depend on every future profile staying convex.
    """
    ix, iy = sign_x * (cx - sx), sign_y * (cy - sy)
    ts = np.linspace(0.0, 1.0, 17)
    along_x = [(sign_x * (cx - sx + sx * t), iy) for t in ts]
    along_y = [(ix, sign_y * (cy - sy + sy * t)) for t in ts]
    return along_x + along_y


#: Corner features, and what to call each one.  All three are placed by the same
#: `mold._corner_points`, so all three fail the same way - which is why the code
#: names the *condition* and the diagnostic's field names the feature.
_CORNER_FEATURES = (
    ("clamp_holes", "features.clamp_holes", "clamp hole"),
    ("alignment_pins", "features.alignment_pins", "alignment pin"),
    ("pry_notches", "features.pry_notches", "pry notch"),
)

#: Too close to, or inside, the forming wall.
_TOO_CLOSE_TO_CAVITY = "E-FEAT-050"
#: Too close to, or through, the outside of the plate.
_TOO_CLOSE_TO_EDGE = "E-FEAT-051"


def _corner_points(params, inset: float, diagonal: str, pattern: str):
    d = derive(params)
    x, y = d.plate_length / 2.0 - inset, d.plate_width / 2.0 - inset
    if pattern == "four_corners":
        return [(x, y), (-x, y), (-x, -y), (x, -y)]
    return [(-x, y), (x, -y)] if diagonal == "nw_se" else [(x, y), (-x, -y)]


def _placement_diagnostics(params, poly, gap) -> list[Diagnostic]:
    """Every corner feature must keep `min_wall` from the cavity and from the
    plate edge.  Nothing downstream notices when one does not: a bore sunk into
    the cavity still leaves a single closed shell, so `mold._checked` passes it
    and the user gets a mold with a slot in the forming wall."""
    out: list[Diagnostic] = []
    min_wall = params.manufacturing.min_wall
    d = derive(params)
    f = params.features

    for name, field, label in _CORNER_FEATURES:
        feature = getattr(f, name)
        if not feature.enabled:
            continue
        if name == "pry_notches":
            probes, radius, edge = [], 0.0, None
            signs = (
                [(1, 1), (-1, 1), (-1, -1), (1, -1)] if feature.pattern == "four_corners"
                else ([(-1, 1), (1, -1)] if feature.diagonal == "nw_se" else [(1, 1), (-1, -1)])
            )
            for sx, sy in signs:
                probes += _notch_probes(d.plate_length / 2.0, d.plate_width / 2.0,
                                        feature.size_x, feature.size_y, sx, sy)
        else:
            # A pin's hole in the female is bored to the pin plus its fit
            # clearance, so that - not the pin - is the widest thing at the spot.
            radius = feature.diameter / 2.0 + (
                params.manufacturing.pin_fit_clearance if name == "alignment_pins" else 0.0
            )
            diagonal = getattr(feature, "diagonal", "nw_se")
            probes = _corner_points(params, feature.inset, diagonal, feature.pattern)
            edge = feature.inset - radius

        worst = min(_clearance(poly, px, py, gap) for px, py in probes) - radius
        if worst < min_wall:
            breach = " - it opens into the forming wall" if worst < 0 else ""
            remedy = ("make the notch smaller" if name == "pry_notches"
                      else "move the feature inboard with a smaller inset")
            out.append(Diagnostic(
                _TOO_CLOSE_TO_CAVITY, "error", field,
                f"the {label} leaves {worst:+.2f} mm of wall to the cavity, below min_wall "
                f"{min_wall} mm{breach}. Widen mold.flange_width, or {remedy}.",
            ))
        elif edge is not None and edge < min_wall:
            breach = " - it breaks out of the plate" if edge < 0 else ""
            out.append(Diagnostic(
                _TOO_CLOSE_TO_EDGE, "error", field,
                f"the {label} leaves {edge:+.2f} mm of wall to the plate edge, below min_wall "
                f"{min_wall} mm{breach}. Increase the inset, or use a smaller diameter.",
            ))
    return out


def _geometric_diagnostics(params, treatments, gap) -> list[Diagnostic]:
    """Rules that need the base profile's actual curvature."""
    import json

    out: list[Diagnostic] = []
    limits = _limits_for(json.dumps(params.tray.profile.model_dump(mode="json"), sort_keys=True))
    if isinstance(limits, str):
        return [Diagnostic("E-SHAPE-001", "error", "tray.profile", limits)]

    # E-GAP-025: the forming gap is an OUTWARD offset.  For a convex profile the
    # outward limit is infinite, so this fires only for a profile with a concave
    # region - never merely because the gap exceeds the convex minimum radius.
    if gap >= limits["max_outward"]:
        out.append(Diagnostic("E-GAP-025", "error", "leather/fit",
                              f"forming gap {gap:.3f} mm reaches the concave curvature limit "
                              f"{limits['max_outward']:.3f} mm; the outward offset would cusp"))

    # E-BLEND-011: edge treatments offset INWARD, so the convex limit applies.
    for field, treatment in treatments.items():
        if not treatment.active:
            continue
        inward = treatment is params.mold.female_entry_blend_top or (
            treatment is params.mold.female_entry_blend_bottom
        )
        # cavity treatments grow the opening outward; male treatments cut inward
        if inward:
            continue
        if treatment.size >= limits["max_inward"]:
            out.append(Diagnostic("E-BLEND-011", "error", field,
                                  f"{treatment.size} mm reaches the convex curvature limit "
                                  f"{limits['max_inward']:.3f} mm; the inward offset would cusp"))
    floor = params.mold.male_floor_blend
    if floor.active and min(params.tray.profile.length, params.tray.profile.width) - 2 * floor.size <= 0:
        out.append(Diagnostic("E-BLEND-012", "error", "mold.male_floor_blend",
                              "the plug's top face degenerates"))

    poly = _polyline_for(json.dumps(params.tray.profile.model_dump(mode="json"), sort_keys=True))
    if poly is not None:
        out.extend(_placement_diagnostics(params, poly, gap))
    return out


def raise_on_errors(params) -> None:
    diagnostics = validate(params)
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        raise ValidationError(errors)
