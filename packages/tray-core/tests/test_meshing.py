"""Tessellation: the mesh has to describe the solid, not the noise in it.

A B-rep can be correct and its mesh absurd, and nothing else in this suite can
see the difference. The case that motivated these tests: a conic-obround female
whose entry-blend cut left eight sliver faces of 0.43 cm2 - the first 0.08 mm of
a 3 mm blend, duplicated over the blend proper. The solid was one closed shell
with the right volume, so `mold._checked` passed it and the volume bounds passed
it; OCC then meshed each sliver to 125 000 triangles and the STL came out at
54.6 MB for a part whose honest mesh is 12 MB.

The sliver faces are still there - that is a boolean defect, recorded in
docs/architecture.md 7.9 - but they no longer cost anything, because meshing now
carries a floor on how small a triangle may be.
"""

import cadquery as cq
import pytest
from OCP.BRep import BRep_Tool
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopLoc import TopLoc_Location

from traymold.api import build
from traymold.exporters import mesh
from traymold.params import (
    CircularObroundProfile,
    CircularRectProfile,
    ConicObroundProfile,
    G2QuinticObroundProfile,
    G2QuinticRectProfile,
    LeatherParams,
    MoldParams,
    Params,
    TrayParams,
)
from traymold.quality import DEFAULTS, MIN_MESH_SIZE

EXPORT = DEFAULTS["export"]

#: What one face may spend, as `FIXED + PER_CM2 * area`.
#:
#: A density bound alone is the wrong shape: a genuine 0.002 cm2 fillet corner
#: needs its hundred triangles and reads as 240 000 per cm2 for doing so. So a
#: face gets a flat allowance plus a density.  Measured across six profile
#: families, both halves, at export quality:
#:
#:     healthy worst   13 153 tri on 0.43 cm2   = 47 % of its allowance
#:     the fault      125 342 tri on 0.43 cm2   = 4.5x its allowance
#:
#: An order of magnitude of clearance on each side of the line.
FIXED_ALLOWANCE = 2_000
PER_CM2_ALLOWANCE = 60_000


def _area(shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape.wrapped, props)
    return props.Mass()


def face_budget(solid):
    """Every face, its area in cm2 and the triangles it was given."""
    mesh(solid, EXPORT)
    out = []
    for face in cq.Solid(solid.wrapped).Faces():
        triangulation = BRep_Tool.Triangulation_s(face.wrapped, TopLoc_Location())
        if triangulation is None:
            continue
        out.append((triangulation.NbTriangles(), _area(face) / 100.0))
    return out


def design(profile, **kw):
    return Params(
        tray=TrayParams(profile=profile, depth=25.0),
        mold=MoldParams(flange_width=30.0, base_plate_thickness=15.0,
                        cavity_plate_thickness=25.0),
        **kw,
    ).with_quality("export")


#: The design a user reported, and the one the bound is calibrated against.
REPORTED = design(ConicObroundProfile(length=175.0, width=175.0, rho=0.5),
                  leather=LeatherParams(thickness=3.0, compression=0.14))

PROFILES = {
    "conic_obround square": REPORTED,
    "conic_obround": design(ConicObroundProfile(length=175.0, width=105.0, rho=0.5)),
    "g2_quintic_obround": design(G2QuinticObroundProfile(length=175.0, width=105.0)),
    "circular_obround": design(CircularObroundProfile(length=175.0, width=105.0)),
    "g2_quintic_rect": design(G2QuinticRectProfile(length=175.0, width=105.0, corner_setback=25.0)),
    "circular_rect": design(CircularRectProfile(length=175.0, width=105.0, corner_radius=25.0)),
}


def test_the_floor_is_below_anything_a_printer_could_resolve():
    """The constant is physical, not numerical: a quarter of a 0.2 mm layer and
    a ninth of a 0.45 mm extrusion, so it cannot remove printable detail."""
    assert MIN_MESH_SIZE < 0.2 / 2
    assert EXPORT.min_mesh_size == MIN_MESH_SIZE
    assert DEFAULTS["preview"].min_mesh_size == MIN_MESH_SIZE


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(PROFILES))
def test_no_face_is_meshed_out_of_all_proportion_to_its_area(name):
    """The guard that would have caught the 54.6 MB female.

    Not a bound on the total - a bigger part earns a bigger mesh - but on what
    any single face may spend. A face over this is not describing the part.
    """
    result = build(PROFILES[name])
    for half in ("male", "female"):
        for triangles, area in face_budget(getattr(result, half)):
            allowance = FIXED_ALLOWANCE + PER_CM2_ALLOWANCE * area
            assert triangles <= allowance, (
                f"{name}/{half}: a {area:.2f} cm2 face was given {triangles:,} triangles, "
                f"{triangles / allowance:.1f}x its allowance of {allowance:,.0f}"
            )


@pytest.mark.slow
def test_the_reported_design_meshes_to_a_sane_size(tmp_path):
    """The regression proper, in the units the report was made in.

    Before the floor this female exported at 54.6 MB against the male's 14.1 -
    four times the mesh for half the volume, which is what made it visible.
    """
    from traymold.exporters import write_artifacts

    result = build(REPORTED)
    sizes = {a.part: a.bytes for a in write_artifacts(
        result, tmp_path, ("stl",), quality=EXPORT, params=REPORTED)}

    assert sizes["female"] < 20_000_000, "the female is back to meshing its slivers"
    # The female has roughly half the male's volume, so it has no business
    # carrying a larger mesh than the male does.
    assert sizes["female"] <= sizes["male"]


@pytest.mark.slow
def test_the_sliver_faces_are_still_there_and_still_cost_nothing():
    """The underlying boolean defect is recorded, not fixed.

    If the entry-blend cut is ever made to stop leaving slivers, this test fails
    and the note in architecture.md 7.9 should go with it.
    """
    female = build(REPORTED).female
    blend_top = REPORTED.mold.female_entry_blend_bottom.size
    slivers = [
        face for face in cq.Solid(female.wrapped).Faces()
        if (bb := face.BoundingBox()).zlen < blend_top / 10 and bb.zmin < 0.1 and _area(face) > 1.0
    ]
    assert slivers, "no slivers - has the entry-blend cut been fixed?"
    for triangles, area in face_budget(female):
        assert triangles < 40_000, "a sliver is being meshed to death again"
