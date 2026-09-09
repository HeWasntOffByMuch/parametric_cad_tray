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

from .blends import compile_treatment
from .derive import derive, forming_gap
from .profiles import (
    MIN_OFFSET,
    OffsetError,
    curvature_limits,
    make_base_profile as _make_base_profile,
    offset_profile,
    resampled,
)
from .quality import resolve as resolve_quality

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

    Two measurements of the base are computed once and shared by every offset it
    yields: the direction-aware curvature limits, and the arclength-uniform
    polyline the realised-distance verifier measures against.  Recomputing those
    per offset cost 11 ms and 5 ms respectively, on 134 offsets per build.

    Offsets are deduplicated at `MIN_OFFSET` (0.1 um) - the resolution below
    which an offset is treated as zero anyway - so numerically equivalent
    requests share one wire.
    """

    _QUANTUM = MIN_OFFSET

    def __init__(self, base: cq.Wire, base_offset: float = 0.0, shared: "_BaseCache | None" = None):
        self.base = base
        self.base_offset = float(base_offset)
        self._shared = shared if shared is not None else _BaseCache(base)

    def at(self, extra: float = 0.0) -> cq.Wire:
        return self._shared.offset(self.base_offset + float(extra))

    @property
    def stats(self) -> dict:
        return self._shared.stats

    @property
    def wire(self) -> cq.Wire:
        return self.at(0.0)


class _BaseCache:
    """One base profile, its measurements, and every offset taken from it."""

    def __init__(self, base: cq.Wire):
        self.base = base
        self._limits: dict | None = None
        self._poly = None
        self._wires: dict[int, cq.Wire] = {}
        self.calls = 0

    @property
    def limits(self) -> dict:
        if self._limits is None:
            self._limits = curvature_limits(self.base)
        return self._limits

    @property
    def poly(self):
        if self._poly is None:
            self._poly = resampled(self.base)
        return self._poly

    def offset(self, d: float) -> cq.Wire:
        key = int(round(d / ProfileFamily._QUANTUM))
        wire = self._wires.get(key)
        if wire is None:
            self.calls += 1
            wire = (
                self.base
                if abs(d) < MIN_OFFSET
                else offset_profile(self.base, d, limits=self.limits, source_poly=self.poly)
            )
            self._wires[key] = wire
        return wire

    @property
    def stats(self) -> dict:
        return {"offset_calls": self.calls, "unique_offsets": len(self._wires)}


def _clean(shape):
    """Best-effort face merging.  `clean()` runs ShapeUpgrade_UnifySameDomain,
    which can fail on lofted spline geometry ("Courbes non jointives") at low
    section counts.  It is cosmetic - it merges coplanar faces - so a failure
    must not fail the build."""
    try:
        return shape.clean()
    except Exception:
        return shape


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
    wires: list[cq.Wire] = []
    seen: list[tuple[int, int]] = []
    for z in zs:
        d = -_draft_offset(params, z) + float(extra["lateral"](z))
        key = (int(round(z / MIN_OFFSET)), int(round(d / MIN_OFFSET)))
        if seen and key == seen[-1]:
            continue  # a repeated section makes the loft degenerate
        seen.append(key)
        wires.append(_at_z(family.at(d), z))
    if len(wires) < 2:
        raise BuildError("prism needs at least two distinct sections")
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
    return cq.Solid(_clean(plate.fuse(plug)).wrapped)


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
    return cq.Solid(_clean(plate.cut(cavity)).wrapped)


# --------------------------------------------------------------------------
# step 4: edge treatments, each independent
# --------------------------------------------------------------------------
def apply_male_root_blend(solid: cq.Solid, family: ProfileFamily, params) -> cq.Solid:
    """Concave blend where the plug meets the base plate.  Adds material."""
    t = params.mold.male_root_blend
    if not t.active:
        return solid
    law = compile_treatment(t)
    hs = law.heights(resolve_quality(params).sections(law))
    collar = _prism(
        family,
        params,
        0.0,
        t.size,
        {"heights": t.size - hs[::-1], "lateral": lambda z: law.lateral(t.size - z)[0]},
    )
    return cq.Solid(_clean(solid.fuse(collar)).wrapped)


def apply_male_floor_blend(solid: cq.Solid, family: ProfileFamily, params) -> cq.Solid:
    """Convex blend at the top of the plug - the tray's floor radius.  Removes material."""
    t = params.mold.male_floor_blend
    if not t.active:
        return solid
    law = compile_treatment(t)
    depth = params.tray.depth
    z0 = depth - t.size
    hs = law.heights(resolve_quality(params).sections(law))
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
    # Remove the whole top band, then add the blended cap back.  Cutting the
    # ring (band - kept) out of the solid instead is 6.9x slower (5.43 s vs
    # 0.79 s) and lands further from the analytic volume, because the ring is a
    # thin spline shell and OCC struggles with it.
    return cq.Solid(_clean(solid.cut(band).fuse(kept)).wrapped)


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
        law = compile_treatment(treatment)
        hs = law.heights(resolve_quality(params).sections(law))
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
        out = cq.Solid(_clean(out.cut(tool)).wrapped)
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


def apply_features(male, female, params):
    """Manufacturing features.  Downstream of everything; inputs to nothing."""
    f = params.features
    t = params.mold.cavity_plate_thickness
    bp = params.mold.base_plate_thickness

    if f.clamp_holes.enabled:
        ch = f.clamp_holes
        pts = _corner_points(params, ch.inset, ch.diagonal, ch.pattern)
        for x, y in pts:
            if ch.in_female and female is not None:
                cut = cq.Workplane("XY").workplane(offset=-1.0).center(x, y).circle(ch.diameter / 2).extrude(t + 2.0)
                female = cq.Solid(female.cut(cut.val()).wrapped)
                if ch.top_chamfer > 0:
                    cs = (
                        cq.Workplane("XY").workplane(offset=t - ch.top_chamfer).center(x, y)
                        .circle(ch.diameter / 2)
                        .workplane(offset=ch.top_chamfer)
                        .circle(ch.diameter / 2 + ch.top_chamfer)
                        .loft()
                    )
                    female = cq.Solid(female.cut(cs.val()).wrapped)
            if ch.in_male and male is not None:
                cut = cq.Workplane("XY").workplane(offset=-bp - 1.0).center(x, y).circle(ch.diameter / 2).extrude(bp + 2.0)
                male = cq.Solid(male.cut(cut.val()).wrapped)

    if f.pry_notches.enabled:
        pn = f.pry_notches
        d = derive(params)
        cx, cy = d.plate_length / 2.0, d.plate_width / 2.0
        signs = (
            [(1, 1), (-1, 1), (-1, -1), (1, -1)]
            if pn.pattern == "four_corners"
            else ([(-1, 1), (1, -1)] if pn.diagonal == "nw_se" else [(1, 1), (-1, -1)])
        )
        for sx, sy in signs if female is not None else []:
            x = sx * (cx - pn.size_x / 2.0)
            y = sy * (cy - pn.size_y / 2.0)
            cut = (
                cq.Workplane("XY").workplane(offset=t - pn.depth).center(x, y)
                .rect(pn.size_x, pn.size_y).extrude(pn.depth + 1.0)
            )
            female = cq.Solid(female.cut(cut.val()).wrapped)

    if f.alignment_pins.enabled:
        ap = f.alignment_pins
        clr = params.manufacturing.pin_fit_clearance
        for x, y in _corner_points(params, ap.inset, "nw_se", ap.pattern):
            if male is not None:
                pin = cq.Workplane("XY").center(x, y).circle(ap.diameter / 2).extrude(ap.height)
                male = cq.Solid(male.fuse(pin.val()).wrapped)
            if female is not None:
                hole = (
                    cq.Workplane("XY").workplane(offset=-0.5).center(x, y)
                    .circle(ap.diameter / 2 + clr).extrude(ap.height + 0.5 + clr)
                )
                female = cq.Solid(female.cut(hole.val()).wrapped)
    return male, female


# --------------------------------------------------------------------------
# the whole build
# --------------------------------------------------------------------------
def _section_stats(params) -> dict:
    q = resolve_quality(params)
    m = params.mold
    counts = {
        name: q.sections(compile_treatment(t))
        for name, t in (
            ("male_root_blend", m.male_root_blend),
            ("male_floor_blend", m.male_floor_blend),
            ("female_entry_blend_top", m.female_entry_blend_top),
            ("female_entry_blend_bottom", m.female_entry_blend_bottom),
        )
        if t.active
    }
    return {"blend_sections_cap": q.blend_sections, "sections": counts,
            "total_sections": sum(counts.values())}


@dataclass
class MoldResult:
    male: cq.Solid | None
    female: cq.Solid | None
    base_profile: cq.Wire
    male_profile: cq.Wire
    female_profile: cq.Wire
    derived: dict
    stats: dict = None

    @property
    def volumes(self) -> dict:
        return {
            f"{name}_cm3": _volume(shape) / 1000.0
            for name, shape in (("male", self.male), ("female", self.female))
            if shape is not None
        }


def build(params) -> MoldResult:
    from .validate import raise_on_errors

    raise_on_errors(params)
    base = make_base_profile(params)
    gap = forming_gap(params)

    # one cache for the whole build: both families offset the SAME base wire, so
    # they share its curvature limits, its verification polyline and its offsets
    shared = _BaseCache(base)
    male_family = ProfileFamily(base, 0.0, shared)      # the male IS the base profile
    female_family = ProfileFamily(base, gap, shared)    # base + forming gap, nothing else

    parts = params.mold.parts
    male = female = None
    if parts.male:
        male = build_male_from_profile(male_family, params)
        male = apply_male_root_blend(male, male_family, params)
        male = apply_male_floor_blend(male, male_family, params)
    if parts.female:
        female = build_female_from_profile(female_family, params)
        female = apply_female_entry_blend(female, female_family, params)

    male, female = apply_features(male, female, params)
    return MoldResult(
        male,
        female,
        base,
        male_family.wire,
        female_family.wire,
        derive(params).as_dict(),
        shared.stats | _section_stats(params),
    )
