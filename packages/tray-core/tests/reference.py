"""Helpers for comparing built geometry against the original Onshape STEP files.

The STEP pair is in assembly coordinates with the parting plane at z = 25;
traymold puts the parting plane at z = 0.  `Z_SHIFT` bridges the two.
"""

from __future__ import annotations

from pathlib import Path

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepGProp import BRepGProp
from OCP.GCPnts import GCPnts_QuasiUniformAbscissa
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
from OCP.IFSelect import IFSelect_RetDone
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopTools import TopTools_HSequenceOfShape

REFERENCE_DIR = Path(__file__).resolve().parents[3] / "reference"
Z_SHIFT = 25.0  # reference z = traymold z + 25


def load_reference(name: str) -> cq.Solid:
    path = REFERENCE_DIR / name
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise RuntimeError(f"cannot read {path}")
    reader.TransferRoots()
    for i in range(1, reader.NbShapes() + 1):
        explorer = TopExp_Explorer(reader.Shape(i), TopAbs_SOLID)
        while explorer.More():
            return cq.Shape.cast(explorer.Current())
    raise RuntimeError(f"no solid in {path}")


def volume_cm3(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props)
    return props.Mass() / 1000.0


def section_loops(solid, z: float, per_edge: int = 400) -> list[np.ndarray]:
    face = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1))).Face()
    sec = BRepAlgoAPI_Section(solid.wrapped, face)
    sec.Approximation(False)
    sec.Build()
    shape = cq.Shape.cast(sec.Shape())
    seq = TopTools_HSequenceOfShape()
    for edge in shape.Edges():
        seq.Append(edge.wrapped)
    wires = TopTools_HSequenceOfShape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(seq, 1e-7, False, wires)
    out = []
    for i in range(1, wires.Length() + 1):
        wire = cq.Shape.cast(wires.Value(i))
        pts = []
        for edge in wire.Edges():
            adaptor = BRepAdaptor_Curve(edge.wrapped)
            disc = GCPnts_QuasiUniformAbscissa(adaptor, per_edge)
            for k in range(1, disc.NbPoints() + 1):
                p = adaptor.Value(disc.Parameter(k))
                pts.append([p.X(), p.Y()])
        out.append(np.asarray(pts))
    return out


def forming_loop(solid, z: float, max_width: float = 200.0, per_edge: int = 400) -> np.ndarray:
    """The plug outline (male) or cavity outline (female) at height z."""
    loops = [p for p in section_loops(solid, z, per_edge) if (p.max(0) - p.min(0))[0] < max_width]
    if not loops:
        raise RuntimeError(f"no forming loop at z={z}")
    return max(loops, key=lambda p: (p.max(0) - p.min(0)).prod())


def _resample(pts: np.ndarray, n: int) -> np.ndarray:
    centre = pts.mean(axis=0)
    ordered = pts[np.argsort(np.arctan2(*(pts - centre).T[::-1]))]
    loop = np.vstack([ordered, ordered[:1]])
    s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(loop, axis=0), axis=1))]
    t = np.linspace(0.0, s[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, s, loop[:, 0]), np.interp(t, s, loop[:, 1])])


def deviation(a: np.ndarray, b: np.ndarray, resample: int = 8000) -> dict:
    poly = _resample(b, resample)
    p0, p1 = poly, np.roll(poly, -1, axis=0)
    seg = p1 - p0
    denom = np.maximum((seg**2).sum(1), 1e-30)
    d = np.empty(len(a))
    for i, p in enumerate(a):
        t = np.clip(((p - p0) * seg).sum(1) / denom, 0.0, 1.0)
        d[i] = np.min(np.linalg.norm(p0 + t[:, None] * seg - p, axis=1))
    return {"min": float(d.min()), "max": float(d.max()), "rms": float(np.sqrt((d**2).mean()))}


def compare_forming_profiles(built, reference, z_built: float, per_edge: int = 300) -> dict:
    a = forming_loop(built, z_built, per_edge=per_edge)
    b = forming_loop(reference, z_built + Z_SHIFT, per_edge=per_edge)
    return deviation(a, b)
