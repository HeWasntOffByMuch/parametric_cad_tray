"""The dependency boundary.

    female_base_profile = offset(male_base_profile, forming_gap)

Male 3D edge treatments, plate thicknesses and manufacturing features are
downstream of the base profiles and must not reach back into them.
"""

import cadquery as cq
import numpy as np
import pytest

from traymold import make_base_profile, make_female_profile, offset_profile, sample_wire
from traymold.derive import forming_gap
from traymold.profiles import profile_deviation
from traymold.params import (
    CircularObroundProfile,
    EdgeTreatment,
    G2QuinticObroundProfile,
    Params,
)
from traymold.presets import REF_4X7


#: Deviation floor of the sampled comparison: resampling a curve of ~500 mm
#: perimeter to 8000 chords leaves ~1.2e-5 mm of sagitta, so a sampled test
#: cannot resolve below that.  0.1 um is 24x below the reference's own accuracy.
SAMPLED_TOL = 1e-4


def enclosed_area(wire) -> float:
    """Exact plan area, free of any discretisation error."""
    return cq.Face.makeFromWires(wire).Area()


def assert_profiles_equivalent(a, b, tol: float = SAMPLED_TOL):
    """Equivalence on three independent measures, two of them exact."""
    ba, bb = a.BoundingBox(), b.BoundingBox()
    assert ba.xlen == pytest.approx(bb.xlen, abs=1e-9), "bounding boxes differ"
    assert ba.ylen == pytest.approx(bb.ylen, abs=1e-9), "bounding boxes differ"
    assert enclosed_area(a) == pytest.approx(enclosed_area(b), rel=1e-12), "plan areas differ"
    dev = profile_deviation(sample_wire(a, 400), sample_wire(b, 400))
    assert dev["max"] <= tol, f"profiles differ by {dev['max'] * 1e3:.4f} um (tol {tol * 1e3} um)"


# --------------------------------------------------------------------------
# the relationship itself
# --------------------------------------------------------------------------
def test_female_profile_is_the_offset_of_the_male_base_profile():
    params = REF_4X7
    base = make_base_profile(params)
    female = make_female_profile(params)
    expected = offset_profile(base, forming_gap(params))
    assert_profiles_equivalent(female, expected)


def test_forming_gap_is_realised_exactly():
    from traymold.profiles import measure_offset_distance

    params = REF_4X7
    realised = measure_offset_distance(make_female_profile(params), make_base_profile(params))
    gap = forming_gap(params)
    assert realised["min"] == pytest.approx(gap, abs=0.01)
    assert realised["max"] == pytest.approx(gap, abs=0.01)


# --------------------------------------------------------------------------
# things that must NOT change the female base profile
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param({"male_root_blend": EdgeTreatment(style="circular", size=3.0)}, id="male_root_blend"),
        pytest.param({"male_floor_blend": EdgeTreatment(style="circular", size=9.0)}, id="male_floor_blend"),
        pytest.param({"female_entry_blend_top": EdgeTreatment(style="circular", size=6.0)}, id="female_entry_blend"),
        pytest.param({"female_entry_blend_bottom": EdgeTreatment(style="g2_quintic", size=2.0)}, id="female_entry_blend_bottom"),
        pytest.param({"base_plate_thickness": 40.0}, id="base_plate_thickness"),
        pytest.param({"cavity_plate_thickness": 60.0}, id="cavity_plate_thickness"),
        pytest.param({"flange_width": 55.0}, id="flange_width"),
    ],
)
def test_edge_treatments_and_plates_do_not_change_the_female_profile(mutation):
    a = REF_4X7
    b = a.model_copy(update={"mold": a.mold.model_copy(update=mutation)})
    assert_profiles_equivalent(make_female_profile(a), make_female_profile(b))


def test_manufacturing_features_do_not_change_the_female_profile():
    from traymold.params import ClampHoles, Features, PryNotches

    a = REF_4X7
    b = a.model_copy(
        update={
            "features": Features(
                clamp_holes=ClampHoles(enabled=True, diameter=10.0, inset=25.0),
                pry_notches=PryNotches(enabled=True, size_x=30.0, size_y=30.0, depth=12.0),
            )
        }
    )
    assert_profiles_equivalent(make_female_profile(a), make_female_profile(b))


def test_male_root_fillet_1p2_vs_3p0(): 
    params_a = REF_4X7.model_copy(
        update={"mold": REF_4X7.mold.model_copy(update={"male_root_blend": EdgeTreatment(style="circular", size=1.2)})}
    )
    params_b = REF_4X7.model_copy(
        update={"mold": REF_4X7.mold.model_copy(update={"male_root_blend": EdgeTreatment(style="circular", size=3.0)})}
    )
    assert_profiles_equivalent(make_female_profile(params_a), make_female_profile(params_b))


# --------------------------------------------------------------------------
# things that MUST change the female base profile
# --------------------------------------------------------------------------
def _differs(a, b, minimum: float = 0.05) -> None:
    dev = profile_deviation(
        sample_wire(make_female_profile(a), 400), sample_wire(make_female_profile(b), 400)
    )
    assert dev["max"] > minimum, f"profiles should differ, max deviation only {dev['max']:.6f} mm"


def test_tray_length_changes_the_female_profile():
    a = REF_4X7
    b = a.model_copy(update={"tray": a.tray.model_copy(update={"profile": G2QuinticObroundProfile(length=200.0, width=105.0)})})
    _differs(a, b, minimum=10.0)


def test_tray_width_changes_the_female_profile():
    a = REF_4X7
    b = a.model_copy(update={"tray": a.tray.model_copy(update={"profile": G2QuinticObroundProfile(length=175.0, width=120.0)})})
    _differs(a, b, minimum=5.0)


def test_plan_shape_changes_the_female_profile():
    a = REF_4X7
    b = a.model_copy(update={"tray": a.tray.model_copy(update={"profile": CircularObroundProfile(length=175.0, width=105.0)})})
    _differs(a, b, minimum=1.0)


@pytest.mark.parametrize(
    "group,mutation,expected_gap",
    [
        ("leather", {"thickness": 4.0}, 4.0),
        ("leather", {"compression": 0.25}, 2.25),
        ("fit", {"clearance": 0.5}, 3.5),
        ("fit", {"gap_override": 1.5}, 1.5),
    ],
)
def test_forming_gap_inputs_change_the_female_profile(group, mutation, expected_gap):
    a = REF_4X7
    b = a.model_copy(update={group: getattr(a, group).model_copy(update=mutation)})
    assert forming_gap(b) == pytest.approx(expected_gap)
    _differs(a, b, minimum=0.4)
