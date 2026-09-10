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
