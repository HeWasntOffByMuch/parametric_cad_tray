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
def offset_profile(
    wire: cq.Wire,
    distance: float,
    *,
    verify_tol: float = 1e-2,
    limits: dict | None = None,
    source_poly: np.ndarray | None = None,
) -> cq.Wire:
    """True geometric 2D offset of a closed planar wire.

    Positive grows the profile outward.  This is the *only* sanctioned way to
    derive the female cavity profile from the male base profile.

    Two protections, in order:

    1. A **direction-aware** curvature check.  An offset only cusps where it
       reaches the local radius of curvature on the side it is moving towards,
       so an outward offset of a convex profile is never rejected however large
       it is - see `curvature_limits`.  Pass `limits` to reuse a computed result.
    2. The realised-distance verifier, which is the final numerical backstop:
       the distance from the offset curve back to the source is measured and
       must match `distance` within `verify_tol` (mm).  OCC's 2D offset degrades
       silently on spline input, so this check is not optional.
    """
    if abs(distance) < MIN_OFFSET:
        return wire
    lim = limits if limits is not None else curvature_limits(wire)
    bound = lim["max_outward"] if distance > 0 else lim["max_inward"]
    if abs(distance) >= bound:
        raise OffsetError(
            f"{'outward' if distance > 0 else 'inward'} offset of {abs(distance):.4f} mm "
            f"reaches the {'concave' if distance > 0 else 'convex'} curvature limit "
            f"of {bound:.4f} mm; the offset would cusp"
        )
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
    realised = measure_offset_distance(result, wire, source_poly=source_poly)
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


#: Points used to represent a curve when measuring distances.  A closed profile of
#: ~500 mm perimeter sampled to 2000 chords has a sagitta of ~0.2 um against the
#: tightest curvature we allow, i.e. 50x below the 10 um verification tolerance.
MEASURE_SAMPLES = 2000
#: coarse stride and candidate count for the two-level nearest-segment search
_STRIDE = 16
_CANDIDATES = 3


def _polyline_distance(points: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Point-to-closed-polyline distances.

    Two-level search: nearest vertex among every `_STRIDE`-th, keep the best
    `_CANDIDATES` of those, then project onto the +/-`_STRIDE` segment window
    around each.  Exhaustive projection over 600 x 2000 costs ~96 ms; this costs
    ~8 ms and agrees with it exactly on every profile pair in the test suite
    (tests/test_profiles.py::test_polyline_distance_matches_brute_force).
    """
    n = len(poly)
    if n <= 4 * _STRIDE:
        return _polyline_distance_exact(points, poly)
    a = poly
    ab = np.roll(poly, -1, axis=0) - a
    denom = np.maximum((ab**2).sum(1), 1e-30)
    coarse_idx = np.arange(0, n, _STRIDE)
    dc = np.linalg.norm(points[:, None, :] - poly[coarse_idx][None], axis=-1)
    keep = np.argsort(dc, axis=1)[:, :_CANDIDATES]
    starts = coarse_idx[keep]                                   # (k, c)
    window = np.arange(-_STRIDE, _STRIDE + 1)
    idx = (starts[:, :, None] + window[None, None, :]) % n       # (k, c, w)
    idx = idx.reshape(len(points), -1)
    A, AB, D = a[idx], ab[idx], denom[idx]
    t = np.clip(((points[:, None, :] - A) * AB).sum(-1) / D, 0.0, 1.0)
    delta = A + t[..., None] * AB - points[:, None, :]
    return np.sqrt((delta**2).sum(-1)).min(1)


def _polyline_distance_exact(points: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Reference implementation: project onto every segment.  Used for short
    polylines and as the oracle the fast path is tested against."""
    a = poly
    ab = np.roll(poly, -1, axis=0) - a
    denom = np.maximum((ab**2).sum(1), 1e-30)
    out = np.empty(len(points))
    for i in range(0, len(points), 512):
        p = points[i : i + 512]
        t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(-1) / denom, 0.0, 1.0)
        delta = a[None] + t[..., None] * ab[None] - p[:, None, :]
        out[i : i + 512] = np.sqrt((delta**2).sum(-1)).min(1)
    return out


def resampled(wire: cq.Wire, n: int = MEASURE_SAMPLES) -> np.ndarray:
    """Arclength-uniform closed polyline for distance measurement."""
    return _resample_closed(sample_wire(wire, 400), n)


def measure_offset_distance(
    offset: cq.Wire, source: cq.Wire, samples: int = 600, source_poly: np.ndarray | None = None
) -> dict:
    """Realised min/max/rms distance from `offset` back to `source`, in mm.

    `source_poly` lets a caller that offsets the same base repeatedly resample it
    once; the result is identical either way.
    """
    src = resampled(source) if source_poly is None else source_poly
    pts = sample_wire(offset, max(40, samples // max(1, len(offset.Edges()))))
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


# --------------------------------------------------------------------------
# direction-aware curvature limits
# --------------------------------------------------------------------------
def curvature_limits(wire: cq.Wire, per_edge: int = 200) -> dict:
    """How far this profile can be offset in each direction before it cusps.

    Offsetting a closed curve fails where the offset distance reaches the local
    radius of curvature **on the side the offset moves towards the centre of
    curvature**.  Those are opposite sides for the two directions:

      * an INWARD offset cusps on CONVEX regions  -> limit = min convex radius
      * an OUTWARD offset cusps on CONCAVE regions -> limit = min concave radius

    A convex profile - which every profile family in this package produces - has
    no concave region at all, so its outward offset is unbounded.  The forming
    gap is an outward offset of the male base profile, so it must never be
    rejected for exceeding the *convex* minimum radius; that number bounds the
    inward direction only.

    Returns `{"max_inward": float, "max_outward": float}` in mm, `inf` when a
    direction is unbounded.

    Curvature is read from OCC's exact second derivatives, not from finite
    differences on a sampled polyline - the latter is dominated by resampling
    noise and understates the radius badly (22.3 mm against the true 37.9 mm on
    the reference profile).
    """
    kappa, points = _signed_curvature(wire, per_edge)
    convex, concave = kappa > _KAPPA_TOL, kappa < -_KAPPA_TOL
    return {
        "max_inward": float(1.0 / kappa[convex].max()) if convex.any() else float("inf"),
        "max_outward": float(1.0 / -kappa[concave].min()) if concave.any() else float("inf"),
        "is_convex": bool(not concave.any()),
    }


#: below this the curve is straight for offsetting purposes (radius > 1e6 mm)
_KAPPA_TOL = 1e-6


def _signed_curvature(wire: cq.Wire, per_edge: int = 200):
    """Signed curvature sampled from exact derivatives.

    Positive means convex - the centre of curvature lies on the interior side -
    independently of how the wire happens to be oriented.
    """
    from OCP.gp import gp_Pnt, gp_Vec

    pts: list[list[float]] = []
    kappa: list[float] = []
    normals: list[list[float]] = []
    for edge in wire.Edges():
        adaptor = BRepAdaptor_Curve(edge.wrapped)
        disc = GCPnts_QuasiUniformAbscissa(adaptor, per_edge)
        for i in range(1, disc.NbPoints() + 1):
            p, v1, v2 = gp_Pnt(), gp_Vec(), gp_Vec()
            adaptor.D2(disc.Parameter(i), p, v1, v2)
            t = np.array([v1.X(), v1.Y()])
            a = np.array([v2.X(), v2.Y()])
            speed = float(np.hypot(*t))
            if speed < 1e-12:
                continue
            cross = t[0] * a[1] - t[1] * a[0]
            k = cross / speed**3
            # curvature vector direction (towards the centre of curvature)
            n = np.array([-t[1], t[0]]) / speed * np.sign(k) if abs(k) > 0 else np.zeros(2)
            pts.append([p.X(), p.Y()])
            kappa.append(abs(k))
            normals.append(n.tolist())
    pts = np.asarray(pts)
    kappa = np.asarray(kappa)
    normals = np.asarray(normals)
    centre = pts.mean(axis=0)
    towards_interior = ((centre - pts) * normals).sum(1)
    signed = np.where(towards_interior >= 0.0, kappa, -kappa)
    return signed, pts


def _signed_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
