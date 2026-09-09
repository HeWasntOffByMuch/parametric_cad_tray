"""Base 2D profiles and the true geometric 2D offset.

This module knows about **plan geometry only**.  It has no knowledge of the
forming gap's meaning, of plate thicknesses, or of 3D edge treatments.  The one
rule it enforces is the dependency boundary:

    female_base_profile = offset_profile(male_base_profile, forming_gap)

so a change to any male 3D edge treatment cannot reach the female cavity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.GCPnts import GCPnts_QuasiUniformAbscissa
from OCP.Geom import Geom_BezierCurve, Geom_BSplineCurve
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_C2
from OCP.GeomAPI import GeomAPI_PointsToBSpline
from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

from .blends import G2_DEGREE, G2_KNOTS, G2_MULTS, G2_POLES

TOL = 1e-9
#: Offsets below this are treated as zero.  OCC's 2D offset refuses sub-micron
#: distances on spline input, and 0.1 um is two orders below the 10 um tolerance
#: the offset result is verified against, so the quantisation is immaterial.
MIN_OFFSET = 1e-4


class ProfileError(ValueError):
    """The requested plan geometry cannot be built."""


class OffsetError(RuntimeError):
    """The 2D offset failed, or produced a curve that is not at the requested distance."""


# --------------------------------------------------------------------------
# edge constructors, one per corner construction
# --------------------------------------------------------------------------
def _pnt(p) -> gp_Pnt:
    return gp_Pnt(float(p[0]), float(p[1]), 0.0)


def line_edge(p0, p1) -> cq.Edge:
    return cq.Edge(BRepBuilderAPI_MakeEdge(_pnt(p0), _pnt(p1)).Edge())


def g2_quintic_corner(corner, e_in, e_out, s: float) -> cq.Edge:
    """The reference's corner: non-rational quintic, zero curvature at both ends.

    `e_in` / `e_out` are unit vectors pointing away from `corner` along the two
    adjoining edges; the curve runs `corner + s*e_in` -> `corner + s*e_out`.
    """
    c, a, b = np.asarray(corner, float), np.asarray(e_in, float), np.asarray(e_out, float)
    poles = np.array([c + s * (-u) * a + s * v * b for u, v in G2_POLES])
    arr = TColgp_Array1OfPnt(1, len(poles))
    for i, p in enumerate(poles, 1):
        arr.SetValue(i, _pnt(p))
    knots = TColStd_Array1OfReal(1, len(G2_KNOTS))
    mults = TColStd_Array1OfInteger(1, len(G2_MULTS))
    for i, (k, m) in enumerate(zip(G2_KNOTS, G2_MULTS), 1):
        knots.SetValue(i, k)
        mults.SetValue(i, m)
    curve = Geom_BSplineCurve(arr, knots, mults, G2_DEGREE)
    return cq.Edge(BRepBuilderAPI_MakeEdge(curve).Edge())


def conic_corner(corner, e_in, e_out, s: float, rho: float) -> cq.Edge:
    """Rational quadratic (conic) corner. rho = 0.5 is the parabola."""
    if not 0.0 < rho < 1.0:
        raise ProfileError(f"conic rho must be in (0, 1), got {rho}")
    c, a, b = np.asarray(corner, float), np.asarray(e_in, float), np.asarray(e_out, float)
    weight = rho / (1.0 - rho)
    arr = TColgp_Array1OfPnt(1, 3)
    arr.SetValue(1, _pnt(c + s * a))
    arr.SetValue(2, _pnt(c))
    arr.SetValue(3, _pnt(c + s * b))
    curve = Geom_BezierCurve(arr)
    curve.SetWeight(2, weight)
    return cq.Edge(BRepBuilderAPI_MakeEdge(curve).Edge())


def circular_corner(corner, e_in, e_out, s: float) -> cq.Edge:
    """Conventional constant-radius fillet; the radius equals the setback."""
    c, a, b = np.asarray(corner, float), np.asarray(e_in, float), np.asarray(e_out, float)
    centre = c + s * a + s * b
    # the arc runs centre->(-b) to centre->(-a); take the short way round
    sense = float(b[0] * a[1] - b[1] * a[0])
    axis = gp_Ax2(_pnt(centre), gp_Dir(0.0, 0.0, 1.0 if sense > 0 else -1.0))
    circ = gp_Circ(axis, s)
    return cq.Edge(BRepBuilderAPI_MakeEdge(circ, _pnt(c + s * a), _pnt(c + s * b)).Edge())


CORNER_BUILDERS = {
    "g2_quintic": lambda c, i, o, s, spec: g2_quintic_corner(c, i, o, s),
    "conic": lambda c, i, o, s, spec: conic_corner(c, i, o, s, spec.rho),
    "circular": lambda c, i, o, s, spec: circular_corner(c, i, o, s),
}


# --------------------------------------------------------------------------
# profile assembly
# --------------------------------------------------------------------------
_RECT_CORNERS = (
    ((1, 1), (-1, 0), (0, -1)),
    ((1, -1), (0, 1), (-1, 0)),
    ((-1, -1), (1, 0), (0, 1)),
    ((-1, 1), (0, -1), (1, 0)),
)


def blended_rect_wire(length: float, width: float, setback: float, style: str, spec) -> cq.Wire:
    """Rectangle `length` x `width` with a corner blend of the given construction.

    `setback` is the distance from the sharp corner along each edge to the blend's
    tangent point.  `setback == width / 2` removes the straight run on the short
    ends entirely, which is the obround / stadium case.
    """
    if length <= 0 or width <= 0:
        raise ProfileError("length and width must be positive")
    if setback < 0:
        raise ProfileError("corner setback must be non-negative")
    if setback > min(length, width) / 2 + TOL:
        raise ProfileError(
            f"corner setback {setback} exceeds half the smaller side "
            f"({min(length, width) / 2})"
        )
    a, b = length / 2.0, width / 2.0
    tangents = []
    for (sx, sy), ei, eo in _RECT_CORNERS:
        c = np.array([sx * a, sy * b], float)
        tangents.append((c, np.asarray(ei, float), np.asarray(eo, float)))

    edges: list[cq.Edge] = []
    for i, (c, ei, eo) in enumerate(tangents):
        prev_c, _, prev_eo = tangents[i - 1]
        prev_end = prev_c + setback * prev_eo
        start = c + setback * ei
        if np.linalg.norm(start - prev_end) > 1e-7:
            edges.append(line_edge(prev_end, start))
        if setback > TOL:
            edges.append(CORNER_BUILDERS[style](c, ei, eo, setback, spec))
    if not edges:
        raise ProfileError("degenerate profile")
    return _wire_from_edges(edges)


def ellipse_wire(length: float, width: float) -> cq.Wire:
    from OCP.gp import gp_Elips

    axis = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
    major, minor = max(length, width) / 2.0, min(length, width) / 2.0
    if length < width:  # major axis must be X for gp_Elips; rotate the frame
        axis = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1), gp_Dir(0, 1, 0))
    elips = gp_Elips(axis, major, minor)
    return _wire_from_edges([cq.Edge(BRepBuilderAPI_MakeEdge(elips).Edge())])


def superellipse_wire(length: float, width: float, exponent: float, samples: int = 1441) -> cq.Wire:
    if exponent <= 0:
        raise ProfileError("superellipse exponent must be positive")
    t = np.linspace(0.0, 2.0 * math.pi, samples)
    ct, st = np.cos(t), np.sin(t)
    x = (length / 2.0) * np.sign(ct) * np.abs(ct) ** (2.0 / exponent)
    y = (width / 2.0) * np.sign(st) * np.abs(st) ** (2.0 / exponent)
    pts = np.column_stack([x, y])[:-1]
    arr = TColgp_Array1OfPnt(1, len(pts) + 1)
    for i, p in enumerate(pts, 1):
        arr.SetValue(i, _pnt(p))
    arr.SetValue(len(pts) + 1, _pnt(pts[0]))
    # a fitted profile, unlike the analytic families: tolerance is explicit
    curve = GeomAPI_PointsToBSpline(arr, 3, 8, GeomAbs_C2, 1e-6).Curve()
    return _wire_from_edges([cq.Edge(BRepBuilderAPI_MakeEdge(curve).Edge())])


def _wire_from_edges(edges: list[cq.Edge]) -> cq.Wire:
    mk = BRepBuilderAPI_MakeWire()
    for e in edges:
        mk.Add(e.wrapped)
    if not mk.IsDone():
        raise ProfileError("could not assemble a closed profile wire")
    return cq.Wire(mk.Wire())


def make_base_profile(spec) -> cq.Wire:
    """Build the base plan profile.  This is step 1 of the pipeline.

    The result is the *male forming profile*.  No blend, fillet, plate or gap has
    been applied and none may be, here or by any caller.
    """
    kind = spec.kind
    if kind in ("g2_quintic_rect", "g2_quintic_obround"):
        return blended_rect_wire(spec.length, spec.width, spec.corner_setback, "g2_quintic", spec)
    if kind in ("conic_rect", "conic_obround"):
        return blended_rect_wire(spec.length, spec.width, spec.corner_setback, "conic", spec)
    if kind in ("circular_rect", "circular_obround"):
        return blended_rect_wire(spec.length, spec.width, spec.corner_setback, "circular", spec)
    if kind == "ellipse":
        return ellipse_wire(spec.length, spec.width)
    if kind == "superellipse":
        return superellipse_wire(spec.length, spec.width, spec.exponent)
    raise ProfileError(f"unknown profile kind {kind!r}")


# --------------------------------------------------------------------------
# the true 2D offset
# --------------------------------------------------------------------------
def offset_profile(wire: cq.Wire, distance: float, *, verify_tol: float = 1e-2) -> cq.Wire:
    """True geometric 2D offset of a closed planar wire.

    Positive grows the profile outward.  This is the *only* sanctioned way to
    derive the female cavity profile from the male base profile.

    The result is verified: the realised distance from the offset curve back to
    the source is measured and must match `distance` within `verify_tol` (mm).
    OCC's 2D offset degrades silently on spline input, so this check is not
    optional - see docs/architecture.md 7.1.
    """
    if abs(distance) < MIN_OFFSET:
        return wire
    mk = BRepOffsetAPI_MakeOffset()
    mk.Init(GeomAbs_Arc, False)
    mk.AddWire(wire.wrapped)
    try:
        mk.Perform(float(distance), 0.0)
        shape = cq.Shape.cast(mk.Shape())
    except Exception as exc:  # OCC raises bare StdFail_NotDone / ValueError
        raise OffsetError(f"2D offset by {distance} mm failed: {type(exc).__name__}: {exc}") from exc
    wires = shape.Wires() if hasattr(shape, "Wires") else []
    if not wires:
        raise OffsetError(f"2D offset by {distance} mm produced no wire")
    result = max(wires, key=lambda w: w.BoundingBox().xlen * w.BoundingBox().ylen)
    realised = measure_offset_distance(result, wire)
    if abs(realised["min"] - abs(distance)) > verify_tol or abs(
        realised["max"] - abs(distance)
    ) > verify_tol:
        raise OffsetError(
            f"2D offset by {distance} mm degraded: realised distance "
            f"{realised['min']:.6f}..{realised['max']:.6f} mm"
        )
    return cq.Wire(result.wrapped)


def sample_wire(wire: cq.Wire, per_edge: int = 400) -> np.ndarray:
    """Sample a planar wire to an (n, 2) point array."""
    pts: list[list[float]] = []
    for edge in wire.Edges():
        adaptor = BRepAdaptor_Curve(edge.wrapped)
        disc = GCPnts_QuasiUniformAbscissa(adaptor, per_edge)
        for i in range(1, disc.NbPoints() + 1):
            p = adaptor.Value(disc.Parameter(i))
            pts.append([p.X(), p.Y()])
    return np.asarray(pts)


def _polyline_distance(points: np.ndarray, poly: np.ndarray) -> np.ndarray:
    a = poly
    b = np.roll(poly, -1, axis=0)
    ab = b - a
    denom = np.maximum((ab**2).sum(1), 1e-30)
    out = np.empty(len(points))
    for i, p in enumerate(points):
        t = np.clip(((p - a) * ab).sum(1) / denom, 0.0, 1.0)
        out[i] = np.min(np.linalg.norm(a + t[:, None] * ab - p, axis=1))
    return out


def measure_offset_distance(offset: cq.Wire, source: cq.Wire, samples: int = 600) -> dict:
    """Realised min/max/rms distance from `offset` back to `source`, in mm."""
    src = _resample_closed(sample_wire(source, 600), 6000)
    pts = sample_wire(offset, max(60, samples // max(1, len(offset.Edges()))))
    d = _polyline_distance(pts, src)
    return {"min": float(d.min()), "max": float(d.max()), "rms": float(np.sqrt((d**2).mean()))}


def profile_deviation(a: np.ndarray, b: np.ndarray, resample: int = 8000) -> dict:
    """Deviation of point set `a` from closed profile `b` (mm)."""
    d = _polyline_distance(a, _resample_closed(b, resample))
    return {"min": float(d.min()), "max": float(d.max()), "rms": float(np.sqrt((d**2).mean()))}


def _resample_closed(pts: np.ndarray, n: int) -> np.ndarray:
    """Order a convex point cloud by angle and resample uniformly by arclength."""
    centre = pts.mean(axis=0)
    ordered = pts[np.argsort(np.arctan2(*(pts - centre).T[::-1]))]
    loop = np.vstack([ordered, ordered[:1]])
    s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(loop, axis=0), axis=1))]
    t = np.linspace(0.0, s[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, s, loop[:, 0]), np.interp(t, s, loop[:, 1])])
