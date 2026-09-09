"""Base profiles and the 2D offset."""

import numpy as np
import pytest

from traymold.blends import G2_CORNER_AREA_FACTOR
from traymold.params import (
    CircularObroundProfile,
    CircularRectProfile,
    ConicObroundProfile,
    EllipseProfile,
    G2QuinticObroundProfile,
    G2QuinticRectProfile,
    Params,
    SuperellipseProfile,
    TrayParams,
)
from traymold.profiles import (
    OffsetError,
    ProfileError,
    make_base_profile,
    measure_offset_distance,
    offset_profile,
    sample_wire,
)

ALL_PROFILES = [
    G2QuinticObroundProfile(length=175.0, width=105.0),
    G2QuinticRectProfile(length=175.0, width=105.0, corner_setback=25.0),
    ConicObroundProfile(length=175.0, width=105.0, rho=0.5),
    CircularObroundProfile(length=175.0, width=105.0),
    CircularRectProfile(length=175.0, width=105.0, corner_radius=20.0),
    EllipseProfile(length=175.0, width=105.0),
    SuperellipseProfile(length=175.0, width=105.0, exponent=4.0),
]


def plan_area(pts: np.ndarray) -> float:
    centre = pts.mean(axis=0)
    s = pts[np.argsort(np.arctan2(*(pts - centre).T[::-1]))]
    return abs(0.5 * np.sum(s[:, 0] * np.roll(s[:, 1], -1) - np.roll(s[:, 0], -1) * s[:, 1]))


@pytest.mark.parametrize("spec", ALL_PROFILES, ids=lambda s: s.kind)
def test_every_profile_builds_a_closed_wire_of_the_right_size(spec):
    wire = make_base_profile(spec)
    assert wire.IsClosed()
    bb = wire.BoundingBox()
    # superellipse is the one fitted family; the rest are analytic
    tol = 1e-3 if spec.kind == "superellipse" else 1e-6
    assert bb.xlen == pytest.approx(spec.length, abs=tol)
    assert bb.ylen == pytest.approx(spec.width, abs=tol)


@pytest.mark.parametrize("spec", ALL_PROFILES, ids=lambda s: s.kind)
def test_every_profile_offsets_to_the_requested_distance(spec):
    wire = make_base_profile(spec)
    for d in (0.5, 3.0):
        realised = measure_offset_distance(offset_profile(wire, d), wire)
        assert realised["min"] == pytest.approx(d, abs=0.01)
        assert realised["max"] == pytest.approx(d, abs=0.01)


def test_reference_profile_plan_area_matches_the_analytic_template():
    """175 x 105 with G2 corners at setback 52.5.  The STEP section measures
    16574.19 mm2; the analytic template predicts 16574.20."""
    spec = G2QuinticObroundProfile(length=175.0, width=105.0)
    area = plan_area(sample_wire(make_base_profile(spec), 2000))
    predicted = 175.0 * 105.0 - 4.0 * G2_CORNER_AREA_FACTOR * 52.5**2
    assert area == pytest.approx(predicted, abs=0.05)
    assert area == pytest.approx(16574.19, abs=0.1)


def test_circular_obround_is_a_true_stadium():
    import math

    spec = CircularObroundProfile(length=175.0, width=105.0)
    area = plan_area(sample_wire(make_base_profile(spec), 2000))
    expected = 70.0 * 105.0 + math.pi * 52.5**2
    assert area == pytest.approx(expected, abs=0.5)


def test_g2_and_circular_obrounds_differ_materially():
    from traymold.profiles import profile_deviation

    a = sample_wire(make_base_profile(G2QuinticObroundProfile(length=175.0, width=105.0)), 800)
    b = sample_wire(make_base_profile(CircularObroundProfile(length=175.0, width=105.0)), 800)
    dev = profile_deviation(a, b)
    assert dev["max"] > 3.0, "a circular obround should differ from the reference by >3 mm"


def test_setback_beyond_half_width_is_rejected():
    with pytest.raises(ValueError):
        Params(tray=TrayParams(profile=G2QuinticRectProfile(length=175.0, width=105.0, corner_setback=60.0)))
    with pytest.raises(ProfileError):
        make_base_profile(G2QuinticRectProfile.model_construct(
            kind="g2_quintic_rect", length=175.0, width=105.0, corner_setback=60.0))


def test_offset_that_self_intersects_is_refused_not_silently_wrong():
    """Inward offsets beyond the tightest curvature must fail loudly."""
    spec = G2QuinticObroundProfile(length=175.0, width=105.0)
    wire = make_base_profile(spec)
    with pytest.raises(OffsetError):
        offset_profile(wire, -60.0)
