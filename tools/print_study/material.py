"""How much filament a solid becomes, under a given set of slicer settings.

A slicer does not fill a solid; it puts a shell on every surface and a lattice
in what is left.  So the material a part costs is

    shell  = sum over faces of  area * shell thickness on that face
    total  = shell + infill_density * (volume - shell)

and the shell thickness is *not* one number: a vertical face gets
`perimeters * extrusion_width`, a horizontal face gets `shell_layers *
layer_height`, and on this geometry those differ by nearly 3x.  Faces are
therefore split by their normal before being multiplied by anything.

Accuracy.  The model ignores shell double-counting where faces meet, the solid
infill a slicer adds under shallow slopes, supports and brim.  Against a real
slicer it is worth about +/-15 % in absolute terms.  Ratios between two plans
are much better than that, because the same approximation is applied to both,
and ratios are what every table in docs/material-optimisation.md is built on.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))

import cadquery as cq  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

#: g/cm3.  PLA; PETG is 1.27, ABS 1.04.  Only the gram columns depend on it.
DENSITY = 1.24

#: Named settings plans.  `walls` and `shells` are counts; the widths are what a
#: 0.4 mm nozzle extrudes at the usual 0.2 mm layer.
PLANS = {
    "6w/30%": dict(walls=6, wall_w=0.45, shells=5, layer_h=0.2, infill=0.30),
    "4w/15%": dict(walls=4, wall_w=0.45, shells=5, layer_h=0.2, infill=0.15),
    "3w/10%": dict(walls=3, wall_w=0.45, shells=5, layer_h=0.2, infill=0.10),
    "3w/8%+8sk": dict(walls=3, wall_w=0.45, shells=8, layer_h=0.2, infill=0.08),
}


def volume(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props)
    return props.Mass()


def area(shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape.wrapped, props)
    return props.Mass()


def face_breakdown(solid) -> dict:
    """Surface area split by how the face lies, because the shell on it differs.

    A face whose normal is within ~25 deg of vertical is treated as horizontal
    and gets the top/bottom shell; within ~6 deg of horizontal, vertical and
    gets the perimeters.  The blends fall in between and are averaged, which is
    what a slicer roughly does to them anyway.
    """
    horizontal = vertical = sloped = 0.0
    for face in cq.Solid(solid.wrapped).Faces():
        a = area(face)
        try:
            nz = abs(face.normalAt().z)
        except Exception:      # a face with no well-defined centre normal
            nz = 0.5
        if nz > 0.9:
            horizontal += a
        elif nz < 0.1:
            vertical += a
        else:
            sloped += a
    return {"horizontal_mm2": horizontal, "vertical_mm2": vertical, "sloped_mm2": sloped}


def material(vol: float, faces: dict, *, walls, wall_w, shells, layer_h, infill) -> dict:
    """mm3 of extruded filament, split into shell and infill."""
    t_vertical = walls * wall_w
    t_horizontal = shells * layer_h
    shell = (
        faces["vertical_mm2"] * t_vertical
        + faces["horizontal_mm2"] * t_horizontal
        + faces["sloped_mm2"] * 0.5 * (t_vertical + t_horizontal)
    )
    shell = min(shell, vol)          # a thin part is all shell
    core = max(vol - shell, 0.0)
    return {"shell_cm3": shell / 1000.0, "core_cm3": core / 1000.0,
            "total_cm3": (shell + infill * core) / 1000.0}


def printed(shape, plan: dict) -> dict:
    """Everything about one solid under one plan."""
    v = volume(shape)
    m = material(v, face_breakdown(shape), **plan)
    return {"solid_cm3": v / 1000.0, **m, "grams": m["total_cm3"] * DENSITY}


def pair(result, plan: dict) -> float:
    """cm3 for both halves of a MoldResult."""
    return sum(printed(getattr(result, h), plan)["total_cm3"]
               for h in ("male", "female") if getattr(result, h) is not None)


def section_stiffness(t: float, skin: float, rho: float) -> dict:
    """A printed plate read as a sandwich: solid skins, lattice core.

    Second moment per mm of width, and the mass of a 100 x 100 mm patch.  The
    core's effective modulus is taken as rho**1.8 - Gibson & Ashby for a
    bending-dominated open cell, which is the conservative end for gyroid.  At
    rho**1.0 (the optimistic end) every conclusion in the doc gets stronger, not
    weaker, so the exponent is not load-bearing.
    """
    core = max(t - 2 * skin, 0.0)
    inertia = (t ** 3 - core ** 3) / 12.0 + (rho ** 1.8) * core ** 3 / 12.0
    grams = (100 * 100 * (t - core) + 100 * 100 * core * rho) / 1000.0 * DENSITY
    return {"I_mm4_per_mm": inertia, "grams_per_dm2": grams, "I_per_gram": inertia / grams}
