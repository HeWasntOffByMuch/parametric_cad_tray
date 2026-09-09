"""Fidelity against the original Onshape STEP files.

Volume from `BRepGProp` is NOT used as the primary metric.  The imported STEP's
own faces are internally inconsistent: the male's top face reports an area of
14167.56 mm2 while the area enclosed by its own boundary wire is 14245.16 mm2,
and the solid's reported volume disagrees with the volume implied by its own
cross-sections by 0.25 cm3.  Section geometry is the sound metric, so that is
what these tests assert on.
"""

import numpy as np
import pytest

import reference as R
import traymold
from traymold.presets import REF_4X7, REF_4X7_STEP

pytestmark = pytest.mark.slow

#: fidelity budget, mm.  The reference's own internal accuracy is ~2.4 um
#: (Onshape's offset approximation), so this is close to the achievable floor.
TOL = 0.010


@pytest.fixture(scope="module")
def built():
    return traymold.build(REF_4X7_STEP)


@pytest.fixture(scope="module")
def male_ref():
    return R.load_reference("male_tray_mold.step")


@pytest.fixture(scope="module")
def female_ref():
    return R.load_reference("female_tray_mold.step")


def test_male_bounding_box(built):
    bb = built.male.BoundingBox()
    # OCC pads BoundingBox by Precision::Confusion
    assert (bb.xlen, bb.ylen, bb.zlen) == pytest.approx((235.0, 165.0, 40.0), abs=1e-6)


def test_female_bounding_box(built):
    bb = built.female.BoundingBox()
    assert (bb.xlen, bb.ylen, bb.zlen) == pytest.approx((235.0, 165.0, 25.0), abs=1e-6)


@pytest.mark.parametrize("z", [0.5, 1.0, 2.0, 5.0, 12.5, 19.0, 20.0, 21.0, 22.5, 24.0, 24.5])
def test_male_forming_profile_matches_step(built, male_ref, z):
    dev = R.compare_forming_profiles(built.male, male_ref, z)
    assert dev["max"] <= TOL, f"z={z}: max deviation {dev['max'] * 1e3:.2f} um"


@pytest.mark.parametrize("z", [0.5, 5.0, 12.5, 20.0, 22.0, 23.0, 24.0, 24.5, 24.9])
def test_female_cavity_profile_matches_step(built, female_ref, z):
    dev = R.compare_forming_profiles(built.female, female_ref, z)
    assert dev["max"] <= TOL, f"z={z}: max deviation {dev['max'] * 1e3:.2f} um"


def test_male_base_plate_volume_is_exact(built):
    import cadquery as cq

    below = cq.Workplane(obj=built.male).cut(
        cq.Workplane("XY").box(600, 600, 600, centered=(True, True, False))
    ).val()
    assert R.volume_cm3(below) == pytest.approx(235.0 * 165.0 * 15.0 / 1000.0, abs=1e-6)


def _integrated_plug_volume(solid, z0: float, z1: float, n: int = 41) -> float:
    zs = np.linspace(z0, z1, n)
    areas = []
    for z in zs:
        pts = R.forming_loop(solid, z, per_edge=200)
        c = pts.mean(0)
        s = pts[np.argsort(np.arctan2(*(pts - c).T[::-1]))]
        areas.append(abs(0.5 * np.sum(s[:, 0] * np.roll(s[:, 1], -1) - np.roll(s[:, 0], -1) * s[:, 1])))
    return float(np.trapezoid(areas, zs) / 1000.0)


def test_plug_volume_by_section_integration(built, male_ref):
    """Section-integrated volume agrees far better than BRepGProp does on the
    STEP import, which is the point of measuring it this way."""
    mine = _integrated_plug_volume(built.male, 1e-4, 25.0 - 1e-4)
    theirs = _integrated_plug_volume(male_ref, 25.0 + 1e-4, 50.0 - 1e-4)
    assert mine == pytest.approx(theirs, rel=2e-4)


def test_realised_forming_gap_matches_the_reference(built):
    from traymold.profiles import measure_offset_distance

    realised = measure_offset_distance(built.female_profile, built.male_profile)
    assert realised["min"] == pytest.approx(3.0, abs=0.01)
    assert realised["max"] == pytest.approx(3.0, abs=0.01)


def test_featured_preset_adds_the_stl_revision_features():
    """The STL revision has 2 chamfered holes and 2 corner notches that the STEP
    revision does not.  Cutting them from the STEP female gives 512.68 cm3."""
    plain = traymold.build(REF_4X7_STEP)
    featured = traymold.build(REF_4X7)
    removed = R.volume_cm3(plain.female) - R.volume_cm3(featured.female)
    expected = 2 * (np.pi * 3.0**2 * 25.0) + 2 * (15.0 * 15.0 * 8.0) + 2 * 46.08
    assert removed * 1000.0 == pytest.approx(expected, rel=0.02)
    assert R.volume_cm3(featured.male) == pytest.approx(R.volume_cm3(plain.male), abs=1e-9)


def analytic_male_volume(params) -> float:
    """Volume implied by the construction, from the profile's area and perimeter
    and each treatment's offset law.  Steiner: offsetting a convex closed curve
    by d changes its enclosed area by P*d + pi*d**2."""
    import numpy as np

    from traymold.blends import compile_treatment
    from traymold.profiles import make_base_profile, sample_wire

    pts = sample_wire(make_base_profile(params.tray.profile), 4000)
    centre = pts.mean(0)
    s = pts[np.argsort(np.arctan2(*(pts - centre).T[::-1]))]
    area = abs(0.5 * np.sum(s[:, 0] * np.roll(s[:, 1], -1) - np.roll(s[:, 0], -1) * s[:, 1]))
    perim = float(np.sum(np.linalg.norm(np.diff(np.vstack([s, s[:1]]), axis=0), axis=1)))

    def moments(treatment):
        law = compile_treatment(treatment)
        if not treatment.active:
            return 0.0, 0.0
        h = np.linspace(0.0, law.size, 200001)
        lat = law.lateral(h)
        return float(np.trapezoid(lat, h)), float(np.trapezoid(lat**2, h))

    d = derive_params(params)
    plate = d["plate_length"] * d["plate_width"] * params.mold.base_plate_thickness
    plug = area * params.tray.depth
    i1r, i2r = moments(params.mold.male_root_blend)
    i1f, i2f = moments(params.mold.male_floor_blend)
    added = perim * i1r + np.pi * i2r
    removed = perim * i1f - np.pi * i2f
    return float(plate + plug + added - removed) / 1000.0


def derive_params(params) -> dict:
    from traymold.derive import derive

    return derive(params).as_dict()


def test_male_volume_matches_the_analytic_construction(built):
    """A blunt whole-solid invariant.  Section comparisons at sampled heights
    cannot see a boolean that silently ate the plug; this can.  A regression in
    loft section spacing once cost the male 394 cm3 while every sampled section
    still matched."""
    expected = analytic_male_volume(REF_4X7_STEP)
    assert R.volume_cm3(built.male) == pytest.approx(expected, rel=5e-4)


def test_female_volume_matches_the_analytic_construction(built):
    import numpy as np

    from traymold.blends import compile_treatment
    from traymold.profiles import sample_wire

    pts = sample_wire(built.female_profile, 4000)
    centre = pts.mean(0)
    s = pts[np.argsort(np.arctan2(*(pts - centre).T[::-1]))]
    area = abs(0.5 * np.sum(s[:, 0] * np.roll(s[:, 1], -1) - np.roll(s[:, 0], -1) * s[:, 1]))
    perim = float(np.sum(np.linalg.norm(np.diff(np.vstack([s, s[:1]]), axis=0), axis=1)))
    d = derive_params(REF_4X7_STEP)
    t = REF_4X7_STEP.mold.cavity_plate_thickness
    law = compile_treatment(REF_4X7_STEP.mold.female_entry_blend_top)
    h = np.linspace(0.0, law.size, 200001)
    lat = law.lateral(h)
    entry = perim * float(np.trapezoid(lat, h)) + np.pi * float(np.trapezoid(lat**2, h))
    expected = (d["plate_length"] * d["plate_width"] * t - area * t - entry) / 1000.0
    assert R.volume_cm3(built.female) == pytest.approx(expected, rel=5e-4)
