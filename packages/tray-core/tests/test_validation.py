"""Validation rules, with emphasis on the direction-aware ones."""

import pytest

from traymold.params import (
    CircularFillet,
    G2QuinticBlend,
    G2QuinticObroundProfile,
    LeatherParams,
    NoTreatment,
    Params,
    TrayParams,
)
from traymold.presets import REF_4X7, REF_4X7_STEP
from traymold.validate import ValidationError, raise_on_errors, validate


def codes(params, severity=None):
    return {d.code for d in validate(params) if severity is None or d.severity == severity}


def test_the_reference_presets_validate_clean():
    assert validate(REF_4X7) == []
    assert validate(REF_4X7_STEP) == []


# --------------------------------------------------------------------------
# datum
# --------------------------------------------------------------------------
def test_outer_datum_is_an_explicit_unsupported_diagnostic():
    params = REF_4X7.model_copy(
        update={"tray": REF_4X7.tray.model_copy(update={"datum": "outer"})}
    )
    diags = [d for d in validate(params) if d.code == "E-DATUM-001"]
    assert len(diags) == 1
    assert diags[0].severity == "error"
    assert "not supported" in diags[0].message
    assert "never silently reinterpreted" in diags[0].message


def test_outer_datum_refuses_to_build():
    import traymold

    params = REF_4X7.model_copy(
        update={"tray": REF_4X7.tray.model_copy(update={"datum": "outer"})}
    )
    with pytest.raises(ValidationError) as exc:
        traymold.build(params)
    assert "E-DATUM-001" in str(exc.value)


# --------------------------------------------------------------------------
# direction awareness
# --------------------------------------------------------------------------
@pytest.mark.parametrize("gap", [3.0, 20.0, 45.0, 60.0])
def test_a_large_forming_gap_is_never_rejected_for_convex_curvature(gap):
    """The gap is an OUTWARD offset of a convex profile: unbounded by curvature.
    45 and 60 mm both exceed the profile's 37.9 mm convex minimum radius."""
    params = REF_4X7.model_copy(
        update={"fit": REF_4X7.fit.model_copy(update={"gap_override": gap}),
                "mold": REF_4X7.mold.model_copy(update={"flange_width": gap + 30.0})}
    )
    assert "E-GAP-025" not in codes(params, "error")
    assert "E-BLEND-011" not in codes(params, "error")


def test_a_male_treatment_beyond_the_convex_radius_is_rejected():
    params = REF_4X7.model_copy(
        update={
            "tray": REF_4X7.tray.model_copy(update={"depth": 120.0}),
            "mold": REF_4X7.mold.model_copy(update={
                "male_floor_blend": G2QuinticBlend(setback=45.0),
                "cavity_plate_thickness": 120.0,
            }),
        }
    )
    assert "E-BLEND-011" in codes(params, "error")


def test_derived_reports_both_offset_directions():
    from traymold.derive import derive

    d = derive(REF_4X7)
    assert d.max_inward_offset == pytest.approx(0.72184 * 52.5, rel=1e-3)
    assert d.max_outward_offset == float("inf")


# --------------------------------------------------------------------------
# the rest of the rule table
# --------------------------------------------------------------------------
def test_non_positive_gap_is_an_error():
    from traymold.derive import forming_gap

    params = REF_4X7.model_copy(
        update={"leather": LeatherParams(thickness=0.4, compression=0.0),
                "fit": REF_4X7.fit.model_copy(update={"clearance": -0.5, "gap_override": None})}
    )
    assert forming_gap(params) < 0
    assert "E-GAP-020" in codes(params, "error")


def test_plug_deeper_than_the_cavity_plate_is_an_error():
    params = REF_4X7.model_copy(update={"tray": REF_4X7.tray.model_copy(update={"depth": 40.0})})
    assert "E-MOLD-040" in codes(params, "error")


def test_treatments_that_consume_the_whole_wall_are_an_error():
    params = REF_4X7.model_copy(update={"mold": REF_4X7.mold.model_copy(update={
        "male_root_blend": CircularFillet(radius=13.0),
        "male_floor_blend": G2QuinticBlend(setback=12.4),
    })})
    assert "E-BLEND-015" in codes(params, "error")


def test_flange_thinner_than_min_wall_is_an_error():
    params = REF_4X7.model_copy(update={"mold": REF_4X7.mold.model_copy(update={"flange_width": 4.0})})
    assert "E-MOLD-041" in codes(params, "error")


def test_raise_on_errors_passes_warnings_through():
    params = REF_4X7.model_copy(
        update={"fit": REF_4X7.fit.model_copy(update={"gap_override": 0.3})}
    )
    assert "W-GAP-021" in codes(params, "warning")
    raise_on_errors(params)  # warnings must not block a build


# --------------------------------------------------------------------------
# the shell invariant
# --------------------------------------------------------------------------
def test_a_boolean_that_leaves_a_stray_face_is_refused():
    """A volume bound cannot see a stray face, because a face weighs nothing.

    The superellipse cavity cut came back with the right volume, the right
    silhouette and a spare unclosed shell lying across the opening: it rendered
    as a solid plate with a groove scribed on it, and every volume bound was
    satisfied. BRepCheck_Analyzer calls that shape valid too. The shell count is
    what says no.
    """
    import pytest

    import traymold
    from traymold.mold import BuildError
    from traymold.params import SuperellipseProfile
    from traymold.presets import REF_4X7_STEP

    params = REF_4X7_STEP.model_copy(update={
        "tray": REF_4X7_STEP.tray.model_copy(update={
            "profile": SuperellipseProfile(length=175.0, width=105.0, exponent=4.0)}),
        "mold": REF_4X7_STEP.mold.model_copy(update={
            "parts": REF_4X7_STEP.mold.parts.model_copy(update={
                "male": False, "female": True})}),
    })
    with pytest.raises(BuildError, match="stray face"):
        traymold.build(params.with_quality("preview"))


def test_the_invariant_counts_shells_rather_than_trusting_the_kernel():
    from OCP.BRepCheck import BRepCheck_Analyzer

    import traymold
    from traymold.mold import _shells
    from traymold.presets import REF_4X7_STEP

    result = traymold.build(REF_4X7_STEP.with_quality("preview"))
    for part in ("male", "female"):
        solid = getattr(result, part)
        assert _shells(solid) == (1, 1), f"{part} is not one closed shell"
        assert BRepCheck_Analyzer(solid.wrapped).IsValid()


# --------------------------------------------------------------------------
# corner-feature placement
#
# All three corner features are placed by the same helper, so all three fail the
# same way: the bore or the rebate reaches the cavity, the boolean still returns
# one closed shell, `mold._checked` passes it, and the user gets a mold with a
# slot in the forming wall and no diagnostic at all.
#
# The rule has to be geometric.  A corner feature sits diagonally outboard, where
# a rounded profile has already curved away, so the cavity's bounding box is
# wildly pessimistic there - 25 mm of it on the reference obround.
# --------------------------------------------------------------------------
from traymold.params import (  # noqa: E402
    AlignmentPins,
    CircularRectProfile,
    ClampHoles,
    G2QuinticRectProfile,
    PryNotches,
)
from traymold.validate import _clearance, _polyline_for  # noqa: E402


def with_fields(**kw):
    params = REF_4X7
    for path, value in kw.items():
        head, _, tail = path.partition(".")
        params = params.model_copy(
            update={head: getattr(params, head).model_copy(update={tail: value})}
        )
    return params


def test_the_convex_offset_identity_the_clearance_rule_rests_on():
    """`_clearance` measures to the base profile and subtracts the gap instead of
    offsetting.  That is exact for a convex curve, and every profile family here
    is convex - which is the same fact `derive` records as an infinite
    `max_outward_offset`.  Checked against a real OCC offset."""
    import json

    import numpy as np

    from traymold.profiles import make_base_profile, offset_profile, sample_wire

    for profile in (
        G2QuinticObroundProfile(length=175.0, width=105.0),
        CircularRectProfile(length=175.0, width=105.0, corner_radius=25.0),
        G2QuinticRectProfile(length=175.0, width=105.0, corner_setback=10.0),
    ):
        poly = _polyline_for(json.dumps(profile.model_dump(mode="json"), sort_keys=True))
        cavity = np.asarray(sample_wire(offset_profile(make_base_profile(profile), 3.0), 2048))[:, :2]
        for px, py in ((95.0, 60.0), (100.0, 70.0), (80.0, 45.0), (60.0, 30.0), (0.0, 0.0)):
            exact = float(np.min(np.hypot(cavity[:, 0] - px, cavity[:, 1] - py)))
            approximate = abs(_clearance(poly, px, py, 3.0))
            assert approximate == pytest.approx(exact, abs=0.02), profile.kind


def test_a_rounded_corner_is_not_a_bounding_box():
    """The reference obround at a narrow flange is fine, and an arithmetic rule
    against the cavity's bounding box would reject it.  This is the case that
    decides the rule has to measure against the curve."""
    narrow = with_fields(**{"mold.flange_width": 12.0})
    assert "E-FEAT-050" not in codes(narrow)


def test_a_clamp_bore_that_opens_into_the_cavity_is_an_error():
    params = with_fields(**{
        "tray.profile": G2QuinticRectProfile(length=175.0, width=105.0, corner_setback=10.0),
        "mold.flange_width": 12.0,
    })
    diagnostic = next(d for d in validate(params)
                      if d.code == "E-FEAT-050" and d.field == "features.clamp_holes")
    assert diagnostic.severity == "error"
    assert "opens into the forming wall" in diagnostic.message
    assert "flange_width" in diagnostic.message


def test_a_land_thinner_than_min_wall_is_an_error_before_it_breaks_through():
    """0.11 mm of plastic between a bore and the forming wall is not a mold."""
    params = with_fields(**{
        "tray.profile": CircularRectProfile(length=175.0, width=105.0, corner_radius=25.0),
        "mold.flange_width": 12.0,
    })
    diagnostic = next(d for d in validate(params)
                      if d.code == "E-FEAT-050" and d.field == "features.clamp_holes")
    assert "below min_wall" in diagnostic.message
    assert "opens into" not in diagnostic.message      # it has not broken through yet


def test_a_clamp_bore_that_breaks_out_of_the_plate_edge_is_an_error():
    params = with_fields(**{
        "features.clamp_holes": REF_4X7.features.clamp_holes.model_copy(update={"inset": 2.0}),
    })
    diagnostic = next(d for d in validate(params) if d.code == "E-FEAT-051")
    assert "plate edge" in diagnostic.message
    assert diagnostic.field == "features.clamp_holes"


def test_a_pry_notch_that_reaches_the_cavity_is_an_error():
    params = with_fields(**{
        "features.pry_notches": PryNotches(enabled=True, size_x=60.0, size_y=60.0, depth=8.0),
    })
    diagnostic = next(d for d in validate(params)
                      if d.code == "E-FEAT-050" and d.field == "features.pry_notches")
    assert "opens into the forming wall" in diagnostic.message
    assert "make the notch smaller" in diagnostic.message
    # the reference's own notches are nowhere near it
    assert codes(REF_4X7) == set()


def test_the_notch_probe_covers_the_inner_edges_and_not_only_the_corner():
    """For the convex plan curves here the inner corner is always the nearest
    point, so the edge samples are defensive.  They are still asserted: the rule
    should not quietly become corner-only if a concave profile is ever added."""
    from traymold.validate import _notch_probes

    probes = _notch_probes(100.0, 80.0, 15.0, 15.0, 1, 1)
    assert (85.0, 65.0) in probes                       # the inner corner
    assert any(x > 85.0 and y == 65.0 for x, y in probes)   # along the x edge
    assert any(x == 85.0 and y > 65.0 for x, y in probes)   # along the y edge


def test_an_alignment_pin_is_measured_over_its_own_fit_clearance():
    """The female's hole is bored to the pin plus its clearance, so that - not
    the pin - is the widest thing at the spot."""
    on_the_plug = with_fields(**{
        "features.alignment_pins": AlignmentPins(enabled=True, inset=40.0)})
    assert any(d.code == "E-FEAT-050" and d.field == "features.alignment_pins"
               for d in validate(on_the_plug))
    assert codes(with_fields(**{
        "features.alignment_pins": AlignmentPins(enabled=True)})) == set()


def test_a_disabled_feature_is_not_placed_and_so_is_not_checked():
    reckless = ClampHoles(enabled=False, inset=200.0, diameter=30.0)
    assert "E-FEAT-050" not in codes(with_fields(**{"features.clamp_holes": reckless}))


def test_the_reference_keeps_nine_millimetres_of_land():
    """The number the rule is calibrated against, so a change to either shows up
    here rather than in a mold."""
    import json

    poly = _polyline_for(json.dumps(REF_4X7.tray.profile.model_dump(mode="json"), sort_keys=True))
    clearance = _clearance(poly, -102.5, 67.5, 3.0) - REF_4X7.features.clamp_holes.diameter / 2
    assert clearance == pytest.approx(33.8, abs=0.1)
