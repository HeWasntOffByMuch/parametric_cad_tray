"""The geometry pipeline.

The dependency order is fixed and is the point of this module:

    base_profile = make_base_profile(params)          # 1. plan geometry only
    male_profile   = base_profile                     #    the male IS the base
    female_profile = offset_profile(base, gap)        # 2. forming gap only

    male   = build_male_from_profile(male_profile)    # 3. raw solids
    male   = apply_male_root_blend(male, ...)         # 4. edge treatments, after
    male   = apply_male_floor_blend(male, ...)
    female = build_female_from_profile(female_profile)
    female = apply_female_entry_blend(female, ...)

The finished male solid is never offset, and no male edge treatment can reach
`female_profile`.  tests/test_dependency_boundary.py enforces this.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cadquery as cq
import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.gp import gp_Trsf, gp_Vec
from OCP.GProp import GProp_GProps

from .blends import BlendLaw
from .derive import derive, forming_gap
from .profiles import (
    MIN_OFFSET,
    OffsetError,
    make_base_profile as _make_base_profile,
    offset_profile,
)

TOL = 1e-9


class BuildError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# step 1 & 2: profiles
# --------------------------------------------------------------------------
def make_base_profile(params) -> cq.Wire:
    """The male forming profile.  Plan geometry only."""
    return _make_base_profile(params.tray.profile)


def make_male_profile(params) -> cq.Wire:
    """The male base profile is the base profile, unmodified."""
    return make_base_profile(params)


def make_female_profile(params) -> cq.Wire:
    """The female cavity base profile: a true 2D offset of the *male base*
    profile by the forming gap.  Male edge treatments are not inputs here."""
    return offset_profile(make_base_profile(params), forming_gap(params))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _at_z(wire: cq.Wire, z: float) -> cq.Wire:
    tr = gp_Trsf()
    tr.SetTranslation(gp_Vec(0.0, 0.0, float(z)))
    return cq.Wire(BRepBuilderAPI_Transform(wire.wrapped, tr, True).Shape())


class ProfileFamily:
    """A base profile plus a fixed offset, from which further offsets are taken.

    Every wire this yields is a *single* offset of the base profile, never an
    offset of an offset: `at(x)` returns `offset(base, base_offset + x)`.  Offsets
    compose exactly, so this is geometrically identical to chaining and markedly
    more robust - OCC degrades quickly when asked to offset its own spline output.

    `base_offset` carries the forming gap for the female family.  It is the only
    thing that distinguishes the female family from the male one, which is the
    dependency boundary this whole module exists to enforce.
    """

    def __init__(self, base: cq.Wire, base_offset: float = 0.0):
        self.base = base
        self.base_offset = float(base_offset)
        self._cache: dict[int, cq.Wire] = {}

    def at(self, extra: float = 0.0) -> cq.Wire:
        d = self.base_offset + float(extra)
        key = int(round(d * 1e7))
        if key not in self._cache:
            self._cache[key] = (
                self.base if abs(d) < MIN_OFFSET else offset_profile(self.base, d)
            )
        return self._cache[key]

    @property
    def wire(self) -> cq.Wire:
        return self.at(0.0)


def _loft(wires: list[cq.Wire], *, solid: bool = True, ruled: bool = False) -> cq.Solid:
    ts = BRepOffsetAPI_ThruSections(solid, ruled, 1e-6)
    for w in wires:
        ts.AddWire(w.wrapped)
    ts.Build()
    if not ts.IsDone():
        raise BuildError("loft through offset sections failed")
    return cq.Solid(ts.Shape())


def _draft_offset(params, z: float) -> float:
    """Inward plan offset from draft at height z above the parting plane."""
    if params.tray.draft_angle <= 0.0:
        return 0.0
    return z * math.tan(math.radians(params.tray.draft_angle))


def _prism(family: ProfileFamily, params, z0: float, z1: float, extra) -> cq.Solid:
    """Loft the base profile between two heights, applying draft plus `extra(z)`."""
    zs = np.asarray(extra["heights"], dtype=float)
    wires = []
    for z in zs:
        d = -_draft_offset(params, z) + float(extra["lateral"](z))
        wires.append(_at_z(family.at(d), z))
    if len(wires) < 2:
        raise BuildError("prism needs at least two sections")
    return _loft(wires)


def _plate(params, z0: float, z1: float) -> cq.Solid:
    d = derive(params)
    return (
        cq.Workplane("XY")
        .workplane(offset=z0)
        .rect(d.plate_length, d.plate_width)
        .extrude(z1 - z0)
        .val()
    )


def _volume(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props)
    return props.Mass()


# --------------------------------------------------------------------------
# step 3: raw solids (no edge treatments)
# --------------------------------------------------------------------------
def build_male_from_profile(family: ProfileFamily, params) -> cq.Solid:
    """Base plate plus the raw forming extrusion.  No blends."""
    depth = params.tray.depth
    n = 2 if params.tray.draft_angle <= 0 else 8
    plug = _prism(
        family,
        params,
        0.0,
        depth,
        {"heights": np.linspace(0.0, depth, n), "lateral": lambda z: 0.0},
    )
    plate = _plate(params, -params.mold.base_plate_thickness, 0.0)
    return cq.Solid(plate.fuse(plug).clean().wrapped)


def build_female_from_profile(family: ProfileFamily, params) -> cq.Solid:
    """Cavity plate with the raw through cavity.  No entry blend."""
    t = params.mold.cavity_plate_thickness
    n = 2 if params.tray.draft_angle <= 0 else 8
    cavity = _prism(
        family,
        params,
        0.0,
        t,
        {"heights": np.linspace(-1.0, t + 1.0, n), "lateral": lambda z: 0.0},
    )
    plate = _plate(params, 0.0, t)
    return cq.Solid(plate.cut(cavity).clean().wrapped)


# --------------------------------------------------------------------------
# step 4: edge treatments, each independent
# --------------------------------------------------------------------------
def apply_male_root_blend(solid: cq.Solid, family: ProfileFamily, params) -> cq.Solid:
    """Concave blend where the plug meets the base plate.  Adds material."""
    t = params.mold.male_root_blend
    if not t.active:
        return solid
    law = BlendLaw(t.style, t.size)
    hs = law.heights(params.export.blend_sections)
    collar = _prism(
        family,
        params,
        0.0,
        t.size,
        {"heights": t.size - hs[::-1], "lateral": lambda z: law.lateral(t.size - z)[0]},
    )
    return cq.Solid(cq.Workplane(obj=solid).union(cq.Workplane(obj=collar)).val().clean().wrapped)


def apply_male_floor_blend(solid: cq.Solid, family: ProfileFamily, params) -> cq.Solid:
    """Convex blend at the top of the plug - the tray's floor radius.  Removes material."""
    t = params.mold.male_floor_blend
    if not t.active:
        return solid
    law = BlendLaw(t.style, t.size)
    depth = params.tray.depth
    z0 = depth - t.size
    hs = law.heights(params.export.blend_sections)
    kept = _prism(
        family,
        params,
        z0,
        depth,
        {"heights": z0 + hs, "lateral": lambda z: -law.lateral(z - z0)[0]},
    )
    band = _prism(
        family,
        params,
        z0,
        depth,
        {"heights": np.array([z0, depth]), "lateral": lambda z: 0.0},
    )
    waste = cq.Workplane(obj=band).cut(cq.Workplane(obj=kept)).val()
    return cq.Solid(cq.Workplane(obj=solid).cut(cq.Workplane(obj=waste)).val().clean().wrapped)


def apply_female_entry_blend(solid: cq.Solid, family: ProfileFamily, params) -> cq.Solid:
    """Entry radius on the cavity mouth.  Removes material.  Independent of the male."""
    out = solid
    t_plate = params.mold.cavity_plate_thickness
    for treatment, at_top in (
        (params.mold.female_entry_blend_top, True),
        (params.mold.female_entry_blend_bottom, False),
    ):
        if not treatment.active:
            continue
        law = BlendLaw(treatment.style, treatment.size)
        hs = law.heights(params.export.blend_sections)
        if at_top:
            z0 = t_plate - treatment.size
            heights = z0 + hs
            lateral = lambda z, z0=z0, law=law: law.lateral(z - z0)[0]
            heights = np.r_[heights, t_plate + 1.0]
            lateral_fn = lambda z, z0=z0, law=law, tp=t_plate: law.lateral(min(z, tp) - z0)[0]
        else:
            z1 = treatment.size
            heights = np.r_[-1.0, z1 - hs[::-1]]
            lateral_fn = lambda z, z1=z1, law=law: law.lateral(z1 - max(z, 0.0))[0]
        tool = _prism(family, params, heights[0], heights[-1],
                      {"heights": heights, "lateral": lateral_fn})
        out = cq.Solid(cq.Workplane(obj=out).cut(cq.Workplane(obj=tool)).val().clean().wrapped)
    return out


# --------------------------------------------------------------------------
# step 5: manufacturing features
# --------------------------------------------------------------------------
def _corner_points(params, inset: float, diagonal: str, pattern: str):
    d = derive(params)
    x, y = d.plate_length / 2.0 - inset, d.plate_width / 2.0 - inset
    if pattern == "four_corners":
        return [(x, y), (-x, y), (-x, -y), (x, -y)]
    return [(-x, y), (x, -y)] if diagonal == "nw_se" else [(x, y), (-x, -y)]


def apply_features(male: cq.Solid, female: cq.Solid, params):
    f = params.features
    t = params.mold.cavity_plate_thickness
    bp = params.mold.base_plate_thickness

    if f.clamp_holes.enabled:
        ch = f.clamp_holes
        pts = _corner_points(params, ch.inset, ch.diagonal, ch.pattern)
        for x, y in pts:
            if ch.in_female:
                cut = cq.Workplane("XY").workplane(offset=-1.0).center(x, y).circle(ch.diameter / 2).extrude(t + 2.0)
                female = cq.Solid(cq.Workplane(obj=female).cut(cut).val().wrapped)
                if ch.top_chamfer > 0:
                    cs = (
                        cq.Workplane("XY").workplane(offset=t - ch.top_chamfer).center(x, y)
                        .circle(ch.diameter / 2)
                        .workplane(offset=ch.top_chamfer)
                        .circle(ch.diameter / 2 + ch.top_chamfer)
                        .loft()
                    )
                    female = cq.Solid(cq.Workplane(obj=female).cut(cs).val().wrapped)
            if ch.in_male:
                cut = cq.Workplane("XY").workplane(offset=-bp - 1.0).center(x, y).circle(ch.diameter / 2).extrude(bp + 2.0)
                male = cq.Solid(cq.Workplane(obj=male).cut(cut).val().wrapped)

    if f.pry_notches.enabled:
        pn = f.pry_notches
        d = derive(params)
        cx, cy = d.plate_length / 2.0, d.plate_width / 2.0
        signs = (
            [(1, 1), (-1, 1), (-1, -1), (1, -1)]
            if pn.pattern == "four_corners"
            else ([(-1, 1), (1, -1)] if pn.diagonal == "nw_se" else [(1, 1), (-1, -1)])
        )
        for sx, sy in signs:
            x = sx * (cx - pn.size_x / 2.0)
            y = sy * (cy - pn.size_y / 2.0)
            cut = (
                cq.Workplane("XY").workplane(offset=t - pn.depth).center(x, y)
                .rect(pn.size_x, pn.size_y).extrude(pn.depth + 1.0)
            )
            female = cq.Solid(cq.Workplane(obj=female).cut(cut).val().wrapped)

    if f.alignment_pins.enabled:
        ap = f.alignment_pins
        clr = params.manufacturing.pin_fit_clearance
        for x, y in _corner_points(params, ap.inset, "nw_se", ap.pattern):
            pin = cq.Workplane("XY").center(x, y).circle(ap.diameter / 2).extrude(ap.height)
            male = cq.Solid(cq.Workplane(obj=male).union(pin).val().wrapped)
            hole = (
                cq.Workplane("XY").workplane(offset=-0.5).center(x, y)
                .circle(ap.diameter / 2 + clr).extrude(ap.height + 0.5 + clr)
            )
            female = cq.Solid(cq.Workplane(obj=female).cut(hole).val().wrapped)
    return male, female


# --------------------------------------------------------------------------
# the whole build
# --------------------------------------------------------------------------
@dataclass
class MoldResult:
    male: cq.Solid
    female: cq.Solid
    base_profile: cq.Wire
    male_profile: cq.Wire
    female_profile: cq.Wire
    derived: dict

    @property
    def volumes(self) -> dict:
        return {"male_cm3": _volume(self.male) / 1000.0, "female_cm3": _volume(self.female) / 1000.0}


def build(params) -> MoldResult:
    base = make_base_profile(params)
    gap = forming_gap(params)

    male_family = ProfileFamily(base, 0.0)          # the male IS the base profile
    female_family = ProfileFamily(base, gap)        # base + forming gap, nothing else

    male = build_male_from_profile(male_family, params)
    male = apply_male_root_blend(male, male_family, params)
    male = apply_male_floor_blend(male, male_family, params)

    female = build_female_from_profile(female_family, params)
    female = apply_female_entry_blend(female, female_family, params)

    male, female = apply_features(male, female, params)
    return MoldResult(
        male, female, base, male_family.wire, female_family.wire, derive(params).as_dict()
    )
