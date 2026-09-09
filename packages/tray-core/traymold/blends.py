"""Blend primitives.

Two independent concerns live here, and nothing else in the package may conflate
them with the *base profile* (`profiles.py`) or with the *forming gap*
(`derive.py`):

* plan-view corner constructions used to build a base profile, and
* 3D edge treatments applied to an already-built solid.

Both are expressed as a scalar "lateral offset as a function of height", because
that is what the reference geometry actually is: every 3D edge treatment in the
Onshape model is the base profile offset in plan by a height-dependent amount.
See docs/architecture.md 2.2 for the evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# --------------------------------------------------------------------------
# The G2 quintic corner template, recovered verbatim from the Onshape STEP
# (male_tray_mold.step, faces F15-F18 / F19 / F24 and female F12 / F17).
#
# Non-rational degree 5, two quintic Bezier spans joined C3.  Three collinear
# poles at each end give exactly zero endpoint curvature, i.e. a true G2 join to
# the adjoining straight edge.  Expressed in a frame with the sharp corner at the
# origin: the curve runs from (-1, 0) * s to (0, 1) * s.
# --------------------------------------------------------------------------
G2_DEGREE = 5
G2_KNOTS: tuple[float, ...] = (0.0, 0.5, 1.0)
G2_MULTS: tuple[int, ...] = (6, 2, 6)
G2_POLES: tuple[tuple[float, float], ...] = (
    (-1.0, 0.0),
    (-0.85, 0.0),
    (-0.70, 0.0),
    (-1.0 / 3.0, 0.10),
    (-0.10, 1.0 / 3.0),
    (0.0, 0.70),
    (0.0, 0.85),
    (0.0, 1.0),
)

#: minimum radius of curvature of the G2 template, as a multiple of the setback.
#: Measured from the template itself; see tests/test_blend_template.py.
G2_MIN_CURVATURE_RADIUS_FACTOR = 0.72184
#: corner area the G2 template removes from a sharp corner, as a multiple of s**2.
G2_CORNER_AREA_FACTOR = 0.163338

CIRCULAR_MIN_CURVATURE_RADIUS_FACTOR = 1.0
CIRCULAR_CORNER_AREA_FACTOR = 1.0 - math.pi / 4.0


def _bspline_basis(i: int, k: int, t: float, knots: np.ndarray) -> float:
    if k == 0:
        inside = knots[i] <= t < knots[i + 1]
        at_end = t >= knots[-1] and knots[i] < knots[i + 1] == knots[-1]
        return 1.0 if (inside or at_end) else 0.0
    left = right = 0.0
    if knots[i + k] != knots[i]:
        left = (t - knots[i]) / (knots[i + k] - knots[i]) * _bspline_basis(i, k - 1, t, knots)
    if knots[i + k + 1] != knots[i + 1]:
        right = (knots[i + k + 1] - t) / (knots[i + k + 1] - knots[i + 1]) * _bspline_basis(
            i + 1, k - 1, t, knots
        )
    return left + right


def _flat_knots() -> np.ndarray:
    out: list[float] = []
    for knot, mult in zip(G2_KNOTS, G2_MULTS):
        out.extend([knot] * mult)
    return np.asarray(out, dtype=float)


def g2_template_points(n: int = 2001) -> np.ndarray:
    """Sample the normalised template. Returns (n, 2) in the (u, v) corner frame."""
    knots = _flat_knots()
    poles = np.asarray(G2_POLES, dtype=float)
    ts = np.linspace(0.0, 1.0, n)
    out = np.empty((n, 2))
    for j, t in enumerate(ts):
        acc = np.zeros(2)
        for i in range(len(poles)):
            acc += _bspline_basis(i, G2_DEGREE, t, knots) * poles[i]
        out[j] = acc
    return out


# --------------------------------------------------------------------------
# 3D edge treatments, as lateral-offset-vs-height laws.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BlendLaw:
    """A 3D edge treatment expressed as plan offset `lateral(h)` over `size` of height.

    `h` runs 0 at the *tangent* end (where the treatment meets the straight wall)
    to `size` at the *face* end (where it meets the flat face).  `lateral` is the
    in-plane distance the profile moves, always non-negative; the caller decides
    the sign (inward for a convex edge, outward for a concave one).
    """

    style: str
    size: float

    def lateral(self, h: np.ndarray | float) -> np.ndarray:
        h = np.atleast_1d(np.asarray(h, dtype=float))
        if self.size <= 0.0:
            return np.zeros_like(h)
        frac = np.clip(h / self.size, 0.0, 1.0)
        if self.style == "circular":
            # rolling-ball quarter round: lateral = R - sqrt(R^2 - h^2)
            return self.size * (1.0 - np.sqrt(np.clip(1.0 - frac**2, 0.0, 1.0)))
        if self.style == "g2_quintic":
            return self.size * _g2_lateral_fraction(frac)
        if self.style == "chamfer":
            return self.size * frac
        if self.style == "none":
            return np.zeros_like(h)
        raise ValueError(f"unknown blend style {self.style!r}")

    def heights(self, n: int) -> np.ndarray:
        """Height samples clustered where the lateral offset changes fastest."""
        if self.size <= 0.0:
            return np.zeros(1)
        # cosine spacing: dense at both tangent and face ends
        u = np.linspace(0.0, 1.0, n)
        return self.size * (0.5 - 0.5 * np.cos(math.pi * u))


_G2_TABLE: np.ndarray | None = None


def _g2_lateral_fraction(frac: np.ndarray) -> np.ndarray:
    """Normalised lateral offset at a normalised height along the G2 template."""
    global _G2_TABLE
    if _G2_TABLE is None:
        pts = g2_template_points(4001)
        # template u in [-1, 0] is the height fraction, v in [0, 1] the lateral one
        _G2_TABLE = np.column_stack([1.0 + pts[:, 0], pts[:, 1]])
    table = _G2_TABLE
    return np.interp(frac, table[:, 0], table[:, 1])


def min_curvature_radius_factor(corner_style: str) -> float:
    """Tightest radius of curvature a corner style produces, per unit of setback."""
    return {
        "g2_quintic": G2_MIN_CURVATURE_RADIUS_FACTOR,
        "circular": CIRCULAR_MIN_CURVATURE_RADIUS_FACTOR,
        # a conic of parameter rho: rho = 0.5 is the parabola, factor 1/sqrt(2)
        "conic": 1.0 / math.sqrt(2.0),
    }[corner_style]
