"""Direction-aware offset validation.

An offset only cusps where it reaches the local radius of curvature on the side
it moves towards.  Those are opposite sides for the two directions, so a convex
profile - which is every profile family in this package - has an unbounded
outward offset and a bounded inward one.  The forming gap is an outward offset,
so it must never be rejected for exceeding the convex minimum radius.
"""

import math

import numpy as np
import pytest

from traymold.derive import forming_gap
from traymold.params import (
    CircularRectProfile,
    EllipseProfile,
    G2QuinticObroundProfile,
    LeatherParams,
)
from traymold.presets import REF_4X7
from traymold.profiles import (
    OffsetError,
    curvature_limits,
    make_base_profile,
    measure_offset_distance,
    offset_profile,
)
from traymold.validate import validate

REF_PROFILE = G2QuinticObroundProfile(length=175.0, width=105.0)


@pytest.fixture(scope="module")
def base():
    return make_base_profile(REF_PROFILE)


def test_curvature_limits_are_direction_aware(base):
    limits = curvature_limits(base)
    assert limits["is_convex"] is True
    assert limits["max_outward"] == math.inf
    assert limits["max_inward"] == pytest.approx(0.72184 * 52.5, rel=2e-4)


@pytest.mark.parametrize(
    "spec,expected_inward",
    [
        (G2QuinticObroundProfile(length=175.0, width=105.0), 0.72184 * 52.5),
        (CircularRectProfile(length=175.0, width=105.0, corner_radius=20.0), 20.0),
        (EllipseProfile(length=175.0, width=105.0), 52.5**2 / 87.5),
    ],
    ids=lambda v: getattr(v, "kind", "r"),
)
def test_inward_limit_matches_the_analytic_minimum_radius(spec, expected_inward):
    limits = curvature_limits(make_base_profile(spec))
    assert limits["max_inward"] == pytest.approx(expected_inward, rel=5e-4)
    assert limits["max_outward"] == math.inf


# --------------------------------------------------------------------------
# a valid large OUTWARD offset succeeds
# --------------------------------------------------------------------------
@pytest.mark.parametrize("d", [3.0, 30.0, 50.0, 80.0])
def test_large_outward_offset_succeeds(base, d):
    """All of these exceed the convex minimum radius of 37.9 mm at d >= 50, and
    must still succeed: an outward offset of a convex curve cannot cusp."""
    result = offset_profile(base, d)
    realised = measure_offset_distance(result, base)
    assert realised["min"] == pytest.approx(d, abs=0.01)
    assert realised["max"] == pytest.approx(d, abs=0.01)
    bb = result.BoundingBox()
    assert bb.xlen == pytest.approx(175.0 + 2 * d, abs=1e-3)


def test_forming_gap_beyond_the_convex_radius_is_not_rejected():
    """A 50 mm gap exceeds the 37.9 mm convex minimum radius.  It is an outward
    offset, so neither validation nor the geometry may refuse it."""
    params = REF_4X7.model_copy(
        update={"fit": REF_4X7.fit.model_copy(update={"gap_override": 50.0})}
    )
    assert forming_gap(params) == 50.0
    codes = {d.code for d in validate(params) if d.severity == "error"}
    assert "E-GAP-025" not in codes
    assert "E-BLEND-011" not in codes


# --------------------------------------------------------------------------
# an invalid INWARD offset is rejected
# --------------------------------------------------------------------------
@pytest.mark.parametrize("d", [-10.0, -25.0, -37.0])
def test_inward_offset_below_the_limit_succeeds(base, d):
    realised = measure_offset_distance(offset_profile(base, d), base)
    assert realised["max"] == pytest.approx(abs(d), abs=0.01)


@pytest.mark.parametrize("d", [-37.9, -38.5, -45.0, -60.0])
def test_inward_offset_at_or_beyond_the_limit_is_rejected(base, d):
    """Both protections are exercised here.  -37.9 mm sits just inside the
    measured limit of 37.9004 mm, so the curvature rule lets it through and the
    realised-distance verifier catches it instead - which is exactly what the
    backstop is for.  Everything past the limit is refused by the rule."""
    with pytest.raises(OffsetError):
        offset_profile(base, d)


@pytest.mark.parametrize("d", [-38.5, -45.0, -60.0])
def test_the_curvature_rule_itself_refuses_a_clearly_invalid_inward_offset(base, d):
    with pytest.raises(OffsetError) as exc:
        offset_profile(base, d)
    assert "inward" in str(exc.value)
    assert "convex curvature limit" in str(exc.value)


def test_the_verifier_is_the_backstop_at_the_boundary(base):
    """Just inside the curvature limit the rule passes but the geometry is
    already degraded; the realised-distance check must refuse it."""
    limits = curvature_limits(base)
    d = -(limits["max_inward"] - 1e-3)
    with pytest.raises(OffsetError) as exc:
        offset_profile(base, d)
    assert "degraded" in str(exc.value)


def test_male_edge_treatment_beyond_the_inward_limit_is_a_diagnostic():
    from traymold.params import G2QuinticBlend

    params = REF_4X7.model_copy(
        update={
            "tray": REF_4X7.tray.model_copy(update={"depth": 120.0}),
            "mold": REF_4X7.mold.model_copy(
                update={"male_floor_blend": G2QuinticBlend(setback=45.0),
                        "cavity_plate_thickness": 120.0}
            ),
        }
    )
    codes = {d.code for d in validate(params) if d.severity == "error"}
    assert "E-BLEND-011" in codes
