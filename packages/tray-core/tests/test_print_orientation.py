"""The exported female lies on the bed flat-side-down.

The solids are built in *assembly* orientation: z=0 is the parting face, and the
female carries every one of its asymmetric features there - entry blend, pry
notches, clamp chamfers, blind pin holes.  That is the face you cannot print
against.  Export therefore turns the female over.

Two things have to hold, and neither is obvious from reading the code:

* it is a **rotation**, not a mirror.  A mold half is chiral, and the two are
  easy to confuse because turning a real part over does flip its apparent
  handedness.  A mirrored female would not close on the male, and would look
  perfectly fine in a viewer.
* the face that ends up on the bed is the **featureless** one.

Everything here is measured on the solid or on the written file, never asserted
from the transform.
"""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.TopAbs import TopAbs_IN, TopAbs_ON
from OCP.gp import gp_Pnt

import reference as R
import traymold
from traymold import api
from traymold.derive import derive
from traymold.exporters import print_oriented, write_artifacts
from traymold.params import AlignmentPins
from traymold.presets import REF_4X7

#: The reference shape with every asymmetric feature switched on at once, each
#: on a diagonal of its own so a flip cannot be confused with a relabelling.
PARAMS = REF_4X7.model_copy(update={
    "features": REF_4X7.features.model_copy(update={
        "alignment_pins": AlignmentPins(
            enabled=True, pattern="diagonal_pair", diameter=6.0, height=8.0, inset=30.0,
        ),
    }),
}).with_quality("preview")

T = PARAMS.mold.cavity_plate_thickness


@pytest.fixture(scope="module")
def halves():
    #: `api.build` rather than `traymold.build`: `write_artifacts` stamps
    #: traceability, which only the API-level result carries.
    result = api.build(PARAMS)
    return result.female, print_oriented(result.female, "female"), result


def _solid_at(shape, x, y, z, tol=1e-6) -> bool:
    classifier = BRepClass3d_SolidClassifier(shape.wrapped)
    classifier.Perform(gp_Pnt(float(x), float(y), float(z)), tol)
    return classifier.State() in (TopAbs_IN, TopAbs_ON)


def _diagonals(inset_x: float, inset_y: float) -> dict[str, list[tuple[float, float]]]:
    d = derive(PARAMS)
    x, y = d.plate_length / 2 - inset_x, d.plate_width / 2 - inset_y
    return {"nw_se": [(-x, y), (x, -y)], "ne_sw": [(x, y), (-x, -y)]}


def _which_diagonal(shape, z, corners, void_at) -> str:
    hit = [name for name, pts in corners.items() if all(void_at(shape, x, y, z) for x, y in pts)]
    return "+".join(hit) or "neither"


#: Each asymmetric feature: how to recognise its void, and the diagonal it is
#: specified on.  A pry notch and a blind pin hole are void at their centre; a
#: clamp bore is void at its centre at *both* ends because it goes through, so
#: the chamfer is recognised by the bore being wider than nominal.
def _void(shape, x, y, z):
    return not _solid_at(shape, x, y, z)


def _widened_bore(shape, x, y, z):
    ch = PARAMS.features.clamp_holes
    return not _solid_at(shape, x + ch.diameter / 2 + ch.top_chamfer * 0.4, y, z)


FEATURES = [
    # name, (inset_x, inset_y), spec diagonal, probe, depth into the part
    ("pry notch", (PARAMS.features.pry_notches.size_x / 2, PARAMS.features.pry_notches.size_y / 2),
     PARAMS.features.pry_notches.diagonal, _void, 0.5),
    ("pin hole", (30.0, 30.0), "nw_se", _void, 0.5),
    ("clamp chamfer", (PARAMS.features.clamp_holes.inset, PARAMS.features.clamp_holes.inset),
     PARAMS.features.clamp_holes.diagonal, _widened_bore, 0.4),
]

OPPOSITE = {"nw_se": "ne_sw", "ne_sw": "nw_se"}


# --------------------------------------------------------------------------
# the transform itself
# --------------------------------------------------------------------------
def test_turning_the_female_over_is_a_rigid_motion(halves):
    built, printed, _ = halves
    assert printed.Volume() == pytest.approx(built.Volume(), rel=1e-9)
    a, b = built.BoundingBox(), printed.BoundingBox()
    for got, want in ((b.xmin, a.xmin), (b.xmax, a.xmax), (b.ymin, a.ymin), (b.ymax, a.ymax)):
        assert got == pytest.approx(want, abs=1e-6)


def test_the_printed_female_rests_on_z_zero(halves):
    _, printed, _ = halves
    box = printed.BoundingBox()
    assert box.zmin == pytest.approx(0.0, abs=1e-6)
    assert box.zmax == pytest.approx(T, abs=1e-6)


@pytest.mark.parametrize("name,insets,diagonal,probe,depth", FEATURES,
                         ids=[f[0] for f in FEATURES])
def test_the_female_is_turned_over_not_mirrored(halves, name, insets, diagonal, probe, depth):
    """A rotation about X maps (x, y, z) -> (x, -y, -z), so every one-ended
    feature changes diagonal.  A mirror in z would leave all three where they
    are - which is the whole point of checking three of them.
    """
    built, printed, _ = halves
    corners = _diagonals(*insets)
    assert _which_diagonal(built, depth, corners, probe) == diagonal
    assert _which_diagonal(printed, T - depth, corners, probe) == OPPOSITE[diagonal]


@pytest.mark.parametrize("name,insets,diagonal,probe,depth", FEATURES,
                         ids=[f[0] for f in FEATURES])
def test_no_asymmetric_feature_reaches_the_bed_face(halves, name, insets, diagonal, probe, depth):
    _, printed, _ = halves
    for x, y in _diagonals(*insets)[OPPOSITE[diagonal]]:
        assert probe(printed, x, y, T - depth), f"{name} should be at the top of the printed part"
        assert not probe(printed, x, y, depth), f"{name} must not reach the bed"


def test_the_cavity_mouth_on_the_bed_is_the_unblended_one(halves):
    """The default female is blended at the parting face and sharp at the other.

    After the flip the sharp mouth is the one on the bed, so the first layer is
    the full plate section rather than a knife edge of blend.
    """
    _, printed, _ = halves
    assert PARAMS.mold.female_entry_blend_bottom.active
    assert not PARAMS.mold.female_entry_blend_top.active
    setback = PARAMS.mold.female_entry_blend_bottom.size

    bed = R.forming_loop(printed, 0.25, per_edge=120)
    top = R.forming_loop(printed, T - 0.25, per_edge=120)
    widening = (top.max(0) - top.min(0)) - (bed.max(0) - bed.min(0))
    assert widening.min() > 0.5 * setback, "the blended mouth should be the printed-up one"


def test_the_male_is_left_where_it_was_built(halves):
    """Its base plate is already flat and already the lowest face."""
    _, _, result = halves
    assert print_oriented(result.male, "male") is result.male


# --------------------------------------------------------------------------
# what actually reaches the files
# --------------------------------------------------------------------------
def _stl_vertices(path) -> np.ndarray:
    raw = path.read_bytes()
    count = struct.unpack("<I", raw[80:84])[0]
    data = np.frombuffer(raw[84:], dtype=np.uint8).reshape(count, 50)
    return data[:, 12:48].copy().view("<f4").reshape(count * 3, 3).astype(float)


def _glb_vertices(path, node_name: str) -> np.ndarray:
    """Positions of one named node, in the CAD frame.

    The Z-up to Y-up turn lives on the glTF root node, so the accessor values
    themselves are still the millimetres the solid was built in.
    """
    raw = path.read_bytes()
    json_len = struct.unpack("<I", raw[12:16])[0]
    doc = json.loads(raw[20:20 + json_len])
    body = raw[20 + json_len + 8:]
    node = next(n for n in doc["nodes"] if n.get("name") == node_name)
    out = []
    for prim in doc["meshes"][node["mesh"]]["primitives"]:
        acc = doc["accessors"][prim["attributes"]["POSITION"]]
        view = doc["bufferViews"][acc["bufferView"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        chunk = body[start:start + acc["count"] * 12]
        out.append(np.frombuffer(chunk, dtype="<f4").reshape(-1, 3).astype(float))
    return np.vstack(out)


def _pry_notch_floor_height(vertices: np.ndarray) -> float:
    """The one height that tells the two orientations apart.

    A pry notch is a rebate in a plate corner, so its floor is a horizontal face
    inside that corner, at the notch depth from whichever end the notch opens.
    The plate's own corner contributes vertices only at z=0 and z=T, so any other
    height in that window is the floor - except that the clamp bore of the other
    diagonal reaches into the same window, and its chamfer would read as a second
    floor.  Excluding the bore leaves exactly one, whichever way round the part
    is, which is what makes this readable off a mesh.
    """
    d, pn, ch = derive(PARAMS), PARAMS.features.pry_notches, PARAMS.features.clamp_holes
    ax, ay, z = np.abs(vertices[:, 0]), np.abs(vertices[:, 1]), vertices[:, 2]
    in_corner = (ax >= d.plate_length / 2 - pn.size_x) & (ay >= d.plate_width / 2 - pn.size_y)
    bore_x, bore_y = d.plate_length / 2 - ch.inset, d.plate_width / 2 - ch.inset
    clear = (ax - bore_x) ** 2 + (ay - bore_y) ** 2 > (ch.diameter / 2 + ch.top_chamfer + 1.0) ** 2
    heights = z[in_corner & clear & (z > 1e-3) & (z < T - 1e-3)]
    assert len(heights) >= 3, "no notch floor found in the corner window"
    assert np.ptp(heights) < 0.05, f"the window sees more than one face: {np.unique(heights)}"
    return float(np.median(heights))


def test_step_is_written_print_oriented(tmp_path, halves):
    """The strongest of these: the STEP is read back as a solid and probed
    exactly, with no tessellation in between."""
    import cadquery as cq

    _, _, result = halves
    write_artifacts(result, tmp_path, ("step",))
    shape = cq.importers.importStep(str(tmp_path / "female.step")).val()

    for name, insets, diagonal, probe, depth in FEATURES:
        for x, y in _diagonals(*insets)[OPPOSITE[diagonal]]:
            assert probe(shape, x, y, T - depth), f"{name} is not on the printed-up face"
            assert not probe(shape, x, y, depth), f"{name} reaches the bed"


def test_stl_is_written_print_oriented(tmp_path, halves):
    _, _, result = halves
    write_artifacts(result, tmp_path, ("stl",))
    depth = PARAMS.features.pry_notches.depth
    floor = _pry_notch_floor_height(_stl_vertices(tmp_path / "female.stl"))
    assert floor == pytest.approx(T - depth, abs=0.05), (
        f"the notch floor is at {floor:.2f}; print orientation puts it at {T - depth:.2f}, "
        f"assembly orientation at {depth:.2f}"
    )


def test_the_glb_stays_in_assembly_orientation(tmp_path, halves):
    """The viewer has to show the halves closed, and a turned-over female would
    not meet the male.  This is the one artifact the flip must not touch."""
    _, _, result = halves
    write_artifacts(result, tmp_path, ("glb",))
    floor = _pry_notch_floor_height(_glb_vertices(tmp_path / "preview.glb", "female"))
    assert floor == pytest.approx(PARAMS.features.pry_notches.depth, abs=0.05)


def test_the_two_artifacts_disagree_on_purpose(tmp_path, halves):
    """Guards the pair above against both drifting the same way at once."""
    _, _, result = halves
    write_artifacts(result, tmp_path, ("stl", "glb"))
    stl = _pry_notch_floor_height(_stl_vertices(tmp_path / "female.stl"))
    glb = _pry_notch_floor_height(_glb_vertices(tmp_path / "preview.glb", "female"))
    assert stl - glb == pytest.approx(T - 2 * PARAMS.features.pry_notches.depth, abs=0.1)
