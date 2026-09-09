"""Cross-field validation.

Rules are checked arithmetically **before** the kernel is invoked, and each
returns a machine-readable code.  A `try/except` around an OCC call is not
validation; the only exception is the realised-distance verifier in
`profiles.offset_profile`, which is a numerical backstop rather than a rule.

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

from .derive import forming_gap
from .profiles import curvature_limits, make_base_profile


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


def _geometric_diagnostics(params, treatments, gap) -> list[Diagnostic]:
    """Rules that need the base profile's actual curvature."""
    out: list[Diagnostic] = []
    try:
        base = make_base_profile(params.tray.profile)
    except ValueError as exc:
        return [Diagnostic("E-SHAPE-001", "error", "tray.profile", str(exc))]
    limits = curvature_limits(base)

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
    return out


def raise_on_errors(params) -> None:
    diagnostics = validate(params)
    errors = [d for d in diagnostics if d.severity == "error"]
    if errors:
        raise ValidationError(errors)
