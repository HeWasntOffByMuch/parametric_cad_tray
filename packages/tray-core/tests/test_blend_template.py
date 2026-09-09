"""The G2 quintic template is the model's single blend primitive.  Its poles,
knot vector and derived constants are recovered from the Onshape STEP, so they
are facts about the reference, not tuning knobs."""

import math

import numpy as np
import pytest

from traymold.blends import (
    G2_CORNER_AREA_FACTOR,
    G2_DEGREE,
    G2_KNOTS,
    G2_MIN_CURVATURE_RADIUS_FACTOR,
    G2_MULTS,
    G2_POLES,
    BlendLaw,
    g2_template_points,
)


def test_knot_vector_is_two_quintic_bezier_spans():
    assert G2_DEGREE == 5
    assert G2_KNOTS == (0.0, 0.5, 1.0)
    assert G2_MULTS == (6, 2, 6)
    assert sum(G2_MULTS) == len(G2_POLES) + G2_DEGREE + 1


def test_poles_are_symmetric_about_the_diagonal():
    poles = np.asarray(G2_POLES)
    mirrored = np.column_stack([-poles[::-1, 1], -poles[::-1, 0]])
    assert np.allclose(poles, mirrored, atol=1e-12)


def test_three_collinear_poles_at_each_end_give_zero_endpoint_curvature():
    poles = np.asarray(G2_POLES)
    assert np.allclose(poles[:3, 1], 0.0)
    assert np.allclose(poles[-3:, 0], 0.0)
    pts = g2_template_points(200001)
    h = 1e-6
    for idx in (0, -1):
        i = 1 if idx == 0 else -2
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        d1, d2 = (c - a) / 2.0, c - 2 * b + a
        kappa = abs(d1[0] * d2[1] - d1[1] * d2[0]) / max((d1 @ d1) ** 1.5, 1e-30)
        assert kappa < 2e-3, f"endpoint curvature {kappa} is not zero"


def test_minimum_radius_of_curvature_factor():
    pts = g2_template_points(40001)
    d1 = np.gradient(pts, axis=0)
    d2 = np.gradient(d1, axis=0)
    kappa = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(
        (d1**2).sum(1) ** 1.5, 1e-30
    )
    inner = kappa[200:-200]
    assert 1.0 / inner.max() == pytest.approx(G2_MIN_CURVATURE_RADIUS_FACTOR, abs=2e-4)
    # tighter than a circular fillet of the same setback, and looser than a parabola
    assert G2_MIN_CURVATURE_RADIUS_FACTOR < 1.0
    assert G2_MIN_CURVATURE_RADIUS_FACTOR > 1.0 / math.sqrt(2.0)


def test_corner_area_removed_factor():
    pts = g2_template_points(40001)
    poly = np.vstack([pts, [[0.0, 0.0]]])
    x, y = poly[:, 0], poly[:, 1]
    area = abs(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    assert area == pytest.approx(G2_CORNER_AREA_FACTOR, abs=1e-5)
    assert area < 1.0 - math.pi / 4.0          # bulges past a circular arc
    assert area < 1.0 / 6.0                    # and past a parabola, slightly


def test_blend_law_endpoints():
    law = BlendLaw("g2_quintic", 5.0)
    assert float(law.lateral(0.0)[0]) == pytest.approx(0.0, abs=1e-9)
    assert float(law.lateral(5.0)[0]) == pytest.approx(5.0, abs=1e-6)
    circ = BlendLaw("circular", 1.2)
    assert float(circ.lateral(1.2)[0]) == pytest.approx(1.2, abs=1e-9)
    assert float(circ.lateral(0.6)[0]) == pytest.approx(1.2 - math.sqrt(1.2**2 - 0.6**2), abs=1e-9)
    assert float(BlendLaw("none", 5.0).lateral(3.0)[0]) == 0.0
