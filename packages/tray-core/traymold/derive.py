"""Derived quantities.  Nothing here is user input; everything is computed."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .blends import min_curvature_radius_factor


def forming_gap(params) -> float:
    """The single forming gap between the male and female base profiles, mm.

    This is concept 2 of the three (profile / gap / edge treatments).  It is the
    only quantity permitted to relate the male base profile to the female one.
    """
    if params.fit.gap_override is not None:
        return float(params.fit.gap_override)
    thickness = params.leather.thickness * (1.0 - params.leather.compression)
    return float(params.fit.clearance + thickness)


def corner_radius_min(params) -> float:
    """Tightest radius of curvature anywhere on the base profile, mm."""
    p = params.tray.profile
    return min_curvature_radius_factor(p.corner_style) * p.corner_setback


def plate_size(params) -> tuple[float, float]:
    p = params.tray.profile
    return (p.length + 2 * params.mold.flange_width, p.width + 2 * params.mold.flange_width)


@dataclass(frozen=True)
class Derived:
    forming_gap: float
    corner_setback: float
    corner_style: str
    corner_radius_min: float
    plate_length: float
    plate_width: float
    female_flange_width: float
    closed_height: float
    vertical_wall_height: float
    draft_offset_at_depth: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def derive(params) -> Derived:
    gap = forming_gap(params)
    pl, pw = plate_size(params)
    m = params.mold
    return Derived(
        forming_gap=gap,
        corner_setback=params.tray.profile.corner_setback,
        corner_style=params.tray.profile.corner_style,
        corner_radius_min=corner_radius_min(params),
        plate_length=pl,
        plate_width=pw,
        female_flange_width=m.flange_width - gap,
        closed_height=m.base_plate_thickness + m.cavity_plate_thickness,
        vertical_wall_height=params.tray.depth
        - m.male_root_blend.size
        - m.male_floor_blend.size,
        draft_offset_at_depth=params.tray.depth * math.tan(math.radians(params.tray.draft_angle)),
    )
