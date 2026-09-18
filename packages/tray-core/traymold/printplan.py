"""What to print the solids at, and what that costs.

This is the third concept the parameter model keeps apart from geometry, and it
is downstream of everything: `printplan` reads the finished solids and the
derived dimensions, and nothing in `mold`, `profiles` or `derive` reads it back.
A plan cannot move a surface.

The problem it solves is that a slicer fills a part uniformly and the loads on a
mold are not uniform.  Measured on the reference pair (docs/material-optimisation.md):
the shell is 271 cm3 of a 642 cm3 print and the other 371 cm3 is lattice sitting
in the middle of a plate, where it carries almost nothing - a printed plate is a
sandwich and the skins own its bending stiffness.  Three places do need density,
and none of them is the middle of a plate:

    the clamp bearing    a concentrated load through the plate thickness
    the forming face     top solid layers over a sparse lattice dimple
    the alignment pins   a 6 mm column at 10 % infill snaps

So the global plan goes lean and those three are named regions that override it.
The cavity wall and the plug wall are deliberately *not* reinforced: both are
closed loops carrying the forming pressure in hoop compression rather than in
bending, and backing them would cost 44 cm3 for nothing.

Every region is a **primitive** - a cylinder at a clamp point, a prism between
two offsets of the base profile, a box under the forming face - positioned from
values `derive` already computes.  No region is booleaned against the part, so
none of the boolean fragility in docs/architecture.md 7.8a is in reach here: a
mispositioned region is a region the slicer ignores, never a build that fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .derive import derive

#: g/cm3.  PLA.  Only the gram figures in a ledger depend on it.
FILAMENT_DENSITY = 1.24

#: What someone printing this today is assumed to be doing, so a ledger can say
#: what a plan saves rather than only what it costs.  Stated, not measured.
REFERENCE_LABEL = "6 perimeters, 30 % infill"


@dataclass(frozen=True)
class Settings:
    """Slicer-neutral setting names.  `threemf` maps them per slicer flavour.

    `None` means "say nothing about it", which is not the same as a value: an
    omitted key leaves whatever the user's own preset has, and that is the whole
    behaviour of the `slicer` profile.
    """

    fill_density: float | None = None          # 0.0 - 1.0
    fill_pattern: str | None = None
    perimeters: int | None = None
    top_solid_layers: int | None = None
    bottom_solid_layers: int | None = None

    def merged(self, other: "Settings") -> "Settings":
        return Settings(**{
            name: (getattr(other, name) if getattr(other, name) is not None
                   else getattr(self, name))
            for name in ("fill_density", "fill_pattern", "perimeters",
                         "top_solid_layers", "bottom_solid_layers")
        })


#: The infill options.  `slicer` is not a plan, it is the absence of one.
PROFILES: dict[str, Settings] = {
    "slicer": Settings(),
    "balanced": Settings(fill_density=0.15, fill_pattern="gyroid", perimeters=4,
                         top_solid_layers=6, bottom_solid_layers=5),
    "lean": Settings(fill_density=0.10, fill_pattern="gyroid", perimeters=3,
                     top_solid_layers=6, bottom_solid_layers=5),
}

#: The reference row a ledger compares against.
REFERENCE = Settings(fill_density=0.30, perimeters=6,
                     top_solid_layers=5, bottom_solid_layers=5)


@dataclass(frozen=True)
class Region:
    """A volume inside one part that is printed differently from the rest.

    `solid` is in **assembly** orientation, the frame the build runs in.  It is
    turned over with its part on the way to the bed - see
    `exporters.print_oriented`, and the note in `threemf` about why forgetting
    that is the one way to get this silently wrong.
    """

    name: str
    part: str
    solid: Any
    settings: Settings
    why: str


@dataclass
class PartPlan:
    part: str
    base: Settings
    regions: list[Region] = field(default_factory=list)


#: A region states only what it changes.  The object itself carries no settings
#: at all - see the note in `threemf` - so there is no stated baseline for a
#: region to be relative to, and every value here is absolute.
def _only(**kw) -> "Settings":
    return Settings(**kw)


@dataclass
class PrintPlan:
    profile: str
    extrusion_width: float
    layer_height: float
    parts: dict[str, PartPlan] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        """Does this plan say anything a slicer would act on?"""
        return self.profile != "slicer"

    def regions(self) -> list[Region]:
        return [r for plan in self.parts.values() for r in plan.regions]

    def oriented(self, transform) -> "PrintPlan":
        """The same plan with every region moved by `transform(solid, part)`.

        The regions are built in assembly orientation and the parts are turned
        over on the way to the bed, so the two have to move together or the
        modifiers point at nothing.  This is the only supported way to do it,
        and `exporters.write_artifacts` calls it with the same `print_oriented`
        it applies to the halves.
        """
        return PrintPlan(
            profile=self.profile,
            extrusion_width=self.extrusion_width,
            layer_height=self.layer_height,
            parts={
                name: PartPlan(
                    part=part.part, base=part.base,
                    regions=[replace(r, solid=transform(r.solid, r.part))
                             for r in part.regions],
                )
                for name, part in self.parts.items()
            },
        )


# --------------------------------------------------------------------------
# resolving the plan
# --------------------------------------------------------------------------
def extrusion_width(params) -> float:
    """Track width.  A 0.4 mm nozzle lays about 0.45 mm; 1.125x is the usual
    default and is what `manufacturing.nozzle_diameter` is for."""
    if params.print.extrusion_width is not None:
        return float(params.print.extrusion_width)
    return round(params.manufacturing.nozzle_diameter * 1.125, 3)


def layer_height(params) -> float:
    if params.print.layer_height is not None:
        return float(params.print.layer_height)
    return round(params.manufacturing.nozzle_diameter * 0.5, 3)


def _corner_points(params, inset: float, diagonal: str, pattern: str):
    """The same placement `mold.apply_features` uses, read from `derive`."""
    d = derive(params)
    x, y = d.plate_length / 2.0 - inset, d.plate_width / 2.0 - inset
    if pattern == "four_corners":
        return [(x, y), (-x, y), (-x, -y), (x, -y)]
    return [(-x, y), (x, -y)] if diagonal == "nw_se" else [(x, y), (-x, -y)]


#: How far a clamp's bearing spreads into the plate, as a multiple of the bolt
#: diameter.  A washer is what actually spreads it; this is the column of plate
#: under the washer, sized generously because the cost is small - 12.7 cm3 in
#: the female and 7.6 cm3 in the male on the reference - and the failure it
#: prevents is the part denting under the clamp.
CLAMP_BEARING_FACTOR = 3.0

#: Thickness of the dense band under the plug's top forming face.  Enough to
#: carry the top solid layers without dimpling, not enough to matter: 82.9 cm3
#: on the reference, of which the density step costs 20.7.
FORMING_FACE_BAND = 5.0

#: How far the plug's sparse core is held back from its wall, so the wall keeps
#: its own perimeters and the region never fights them.
PLUG_CORE_INSET = 6.0


def _plug_core_density(base: Settings) -> float:
    """Below the forming band the plug carries nothing, but it cannot go to zero:
    the band above it would have nothing to print onto.  70 % of the global
    density is a cell roughly every 9 mm at the lean profile, which bridges."""
    return round((base.fill_density or 0.10) * 0.7, 4)


def resolve(params) -> PrintPlan:
    """params -> the plan.  Builds the region primitives; touches no part."""
    import cadquery as cq

    from .mold import ProfileFamily, _at_z, _loft, make_base_profile

    name = params.print.profile
    base = PROFILES[name]
    plan = PrintPlan(profile=name, extrusion_width=extrusion_width(params),
                     layer_height=layer_height(params))
    for part in ("male", "female"):
        if getattr(params.mold.parts, part):
            plan.parts[part] = PartPlan(part=part, base=base)
    if not plan.active:
        return plan

    depth = params.tray.depth
    bp = params.mold.base_plate_thickness
    t_cav = params.mold.cavity_plate_thickness
    f = params.features

    # One cache for the whole plan, for the same reason `mold.build` keeps one:
    # every offset here comes off the same base wire, so they share its
    # curvature limits and its verification polyline.
    family = ProfileFamily(make_base_profile(params), 0.0, None)

    def prism(d: float, z0: float, z1: float):
        wire = family.at(d)
        return _loft([_at_z(wire, z0), _at_z(wire, z1)])

    def add(part: str, region: Region) -> None:
        if part in plan.parts:
            plan.parts[part].regions.append(region)

    # -- the plug's top forming face, and the empty core under it -------------
    if params.print.support_forming_face and "male" in plan.parts:
        band = min(FORMING_FACE_BAND, depth / 2.0)
        add("male", Region(
            "support: under the forming face", "male", prism(0.0, depth - band, depth),
            _only(fill_density=max(0.35, base.fill_density or 0.0)),
            "top solid layers over a sparse lattice dimple, and this face forms leather",
        ))
        # Only worth naming when there is a plug left under the band to empty.
        if depth - band > 1.0:
            add("male", Region(
                "lighten: plug core", "male", prism(-PLUG_CORE_INSET, 0.0, depth - band),
                _only(fill_density=_plug_core_density(base)),
                "a closed box in compression; its middle carries nothing",
            ))

    # -- where the clamps bear ----------------------------------------------
    if params.print.reinforce_clamps and f.clamp_holes.enabled:
        ch = f.clamp_holes
        radius = CLAMP_BEARING_FACTOR * ch.diameter / 2.0
        dense = _only(fill_density=max(0.70, base.fill_density or 0.0),
                      perimeters=max(4, base.perimeters or 0))
        for index, (x, y) in enumerate(_corner_points(params, ch.inset, ch.diagonal, ch.pattern)):
            # Both halves, whatever `in_male` says: the bolt passes through the
            # female and bears down onto the male's plate either way, so the
            # male's plate takes the same load with or without a bore in it.
            add("female", Region(
                f"reinforce: clamp {index + 1}", "female",
                cq.Workplane("XY").center(x, y).circle(radius).extrude(t_cav).val(),
                dense, "a clamp puts a concentrated load through the plate here",
            ))
            add("male", Region(
                f"reinforce: clamp {index + 1}", "male",
                cq.Workplane("XY").workplane(offset=-bp).center(x, y)
                  .circle(radius).extrude(bp).val(),
                dense, "a clamp puts a concentrated load through the plate here",
            ))

    # -- printed alignment pins ---------------------------------------------
    if f.alignment_pins.enabled:
        ap = f.alignment_pins
        for index, (x, y) in enumerate(_corner_points(params, ap.inset, "nw_se", ap.pattern)):
            add("male", Region(
                f"solid: alignment pin {index + 1}", "male",
                cq.Workplane("XY").center(x, y).circle(ap.diameter / 2.0 + 1.0)
                  .extrude(ap.height).val(),
                _only(fill_density=1.0, perimeters=max(4, base.perimeters or 0)),
                "a slender printed column; sparse infill shears it off",
            ))
    return plan


# --------------------------------------------------------------------------
# the ledger: what a plan costs, and what it saves
# --------------------------------------------------------------------------
#
# A slicer does not fill a solid.  It puts a shell on every surface and a
# lattice in what is left, so
#
#     shell = sum over faces of  area * shell thickness on that face
#     total = shell + density * (volume - shell)
#
# and the shell thickness is not one number: a vertical face gets
# `perimeters * extrusion_width`, a horizontal one `layers * layer_height`, and
# on this geometry those differ by 2.7x.  Faces are split by orientation before
# being multiplied by anything.
#
# Accuracy: this ignores shell double-counting where faces meet, the solid
# infill a slicer adds under shallow slopes, supports (neither half needs any)
# and brim.  Against a real slicer it is worth about +/-15 % in absolute terms.
# Ratios between two plans are far better, because the same approximation
# applies to both - and a ledger is read as a ratio.
def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props)
    return props.Mass()


def _area(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape.wrapped, props)
    return props.Mass()


def face_breakdown(solid) -> dict:
    """Surface area split by how each face lies, because the shell on it differs."""
    import cadquery as cq

    horizontal = vertical = sloped = 0.0
    for face in cq.Solid(solid.wrapped).Faces():
        a = _area(face)
        try:
            nz = abs(face.normalAt().z)
        except Exception:                 # a face with no well-defined centre normal
            nz = 0.5
        if nz > 0.9:
            horizontal += a
        elif nz < 0.1:
            vertical += a
        else:
            sloped += a
    return {"horizontal_mm2": horizontal, "vertical_mm2": vertical, "sloped_mm2": sloped}


def material_mm3(volume: float, faces: dict, settings: Settings,
                 *, extrusion_width: float, layer_height: float) -> dict:
    density = settings.fill_density if settings.fill_density is not None else 0.15
    t_vertical = (settings.perimeters or 3) * extrusion_width
    t_horizontal = ((settings.top_solid_layers or 5) + (settings.bottom_solid_layers or 5)) \
        / 2.0 * layer_height
    shell = (
        faces["vertical_mm2"] * t_vertical
        + faces["horizontal_mm2"] * t_horizontal
        + faces["sloped_mm2"] * 0.5 * (t_vertical + t_horizontal)
    )
    shell = min(shell, volume)            # a thin part is all shell
    core = max(volume - shell, 0.0)
    return {"shell": shell, "core": core, "total": shell + density * core}


def ledger(result, plan: PrintPlan, params) -> dict:
    """What this plan costs, what the alternatives cost, and where it differs.

    `result` carries the built solids; every alternative is evaluated on the
    *same* geometry, which is the point - these options change the print, never
    the part.
    """
    ew, lh = plan.extrusion_width, plan.layer_height
    measured = {}
    for part in ("male", "female"):
        shape = getattr(result, part, None)
        if shape is not None:
            measured[part] = (_volume(shape), face_breakdown(shape))

    def total_for(settings: Settings, regions: list[Region] | None) -> float:
        """mm3 over both halves, with each region's density step applied."""
        out = 0.0
        for part, (volume, faces) in measured.items():
            out += material_mm3(volume, faces, settings,
                                extrusion_width=ew, layer_height=lh)["total"]
        for region in regions or []:
            if region.part not in measured:
                continue
            was = settings.fill_density if settings.fill_density is not None else 0.15
            now = region.settings.fill_density if region.settings.fill_density is not None else was
            out += _volume(region.solid) * (now - was)
        return out

    rows = []
    for name, settings in ((REFERENCE_LABEL, REFERENCE), *PROFILES.items()):
        is_profile = name in PROFILES
        row = {"option": name, "reference": not is_profile,
               "selected": is_profile and name == plan.profile}
        if is_profile and not PROFILES[name].fill_density:
            # `slicer` writes no overrides, so what it costs is whatever preset
            # the user has loaded. Guessing a number here would be inventing one
            # about someone else's printer; say so instead.
            row.update(cm3=None, grams=None,
                       note="whatever your own preset does - this option writes no settings")
            rows.append(row)
            continue
        # Each option is priced with the regions *it* would place, not with the
        # selected option's. Pricing the alternatives bare made the number move
        # when you picked one - lean read 417 g next to a selected `balanced`
        # and 448 g once selected - which is the one thing a comparison table
        # must not do. Resolving a plan is primitives only, ~90 ms, and it runs
        # once per option on an export that takes tens of seconds.
        # The reference row is uniform by definition - it is what someone
        # printing this today does, with no modifiers anywhere.
        if not is_profile:
            regions = []
        elif name == plan.profile:
            regions = plan.regions()
        else:
            regions = resolve(params.model_copy(update={
                "print": params.print.model_copy(update={"profile": name})})).regions()
        mm3 = total_for(settings, regions)
        row.update(cm3=round(mm3 / 1000.0, 1), grams=round(mm3 / 1000.0 * FILAMENT_DENSITY))
        rows.append(row)

    baseline = next(r["cm3"] for r in rows if r["reference"])
    for row in rows:
        row["vs_reference_pct"] = (
            round((row["cm3"] - baseline) / baseline * 100.0)
            if baseline and row["cm3"] is not None else None
        )

    region_rows = []
    for region in plan.regions():
        if region.part not in measured:
            continue
        # Against the density of the part this region sits in, not some global
        # one: the row is only meaningful as the step it represents.
        base = plan.parts[region.part].base.fill_density
        was = base if base is not None else 0.15
        now = region.settings.fill_density if region.settings.fill_density is not None else was
        volume = _volume(region.solid) / 1000.0
        region_rows.append({
            "part": region.part, "name": region.name, "cm3": round(volume, 1),
            "from_density": was, "to_density": now,
            "delta_cm3": round(volume * (now - was), 1), "why": region.why,
        })

    base = next(iter(plan.parts.values())).base if plan.parts else Settings()
    return {
        "profile": plan.profile,
        # The file carries the local reinforcement and nothing else, so these
        # are the reader's to set - and saying so is the difference between a
        # ledger that describes the print and one that describes a wish.
        "global_settings": [
            {"label": label, "value": render(value)}
            for label, value in (
                ("Walls", base.perimeters),
                ("Infill", f"{round((base.fill_density or 0) * 100)}%"
                           f"{' ' + base.fill_pattern if base.fill_pattern else ''}"),
                ("Top / bottom shells", f"{base.top_solid_layers} / {base.bottom_solid_layers}"),
            )
            if (render := str) and value not in (None, "0%")
        ],
        "assumptions": {
            "extrusion_width": ew, "layer_height": lh,
            "filament_density_g_cm3": FILAMENT_DENSITY,
            "reference": REFERENCE_LABEL,
            "accuracy": "shell-plus-infill estimate, about +/-15 % absolute; "
                        "ratios between options are much better than that",
        },
        "options": rows,
        "regions": region_rows,
        "solid_cm3": {part: round(volume / 1000.0, 1)
                      for part, (volume, _) in measured.items()},
    }
