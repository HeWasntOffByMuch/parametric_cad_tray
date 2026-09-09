"""Shared STEP probing helpers."""
import numpy as np, cadquery as cq
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.gp import gp_Pnt, gp_Pln, gp_Dir
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.GCPnts import GCPnts_QuasiUniformAbscissa
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.TopTools import TopTools_HSequenceOfShape

REF='/home/user/parametric_cad_tray/reference/'
def load_solids(path):
    r=STEPControl_Reader(); assert r.ReadFile(path)==IFSelect_RetDone
    r.TransferRoots(); out=[]
    for i in range(1, r.NbShapes()+1):
        ex=TopExp_Explorer(r.Shape(i), TopAbs_SOLID)
        while ex.More(): out.append(cq.Shape.cast(ex.Current())); ex.Next()
    return out
MALE = lambda: load_solids(REF+'male_tray_mold.step')[0]
FEMALE = lambda: load_solids(REF+'female_tray_mold.step')[0]

def section_loops(solid, z, per_edge=900):
    face=BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0,0,z), gp_Dir(0,0,1))).Face()
    s=BRepAlgoAPI_Section(solid.wrapped, face); s.Approximation(False); s.Build()
    sh=cq.Shape.cast(s.Shape())
    seq=TopTools_HSequenceOfShape()
    for e in sh.Edges(): seq.Append(e.wrapped)
    wires=TopTools_HSequenceOfShape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(seq,1e-7,False,wires)
    out=[]
    for i in range(1,wires.Length()+1):
        w=cq.Shape.cast(wires.Value(i)); pts=[]
        for e in w.Edges():
            a=BRepAdaptor_Curve(e.wrapped); g=GCPnts_QuasiUniformAbscissa(a, per_edge)
            for k in range(1,g.NbPoints()+1):
                p=a.Value(g.Parameter(k)); pts.append([p.X(),p.Y()])
        out.append(np.array(pts))
    return out
def inner_loop(solid, z, maxw=200):
    L=section_loops(solid,z)
    c=[p for p in L if (p.max(0)-p.min(0))[0] < maxw]
    return max(c, key=lambda p:(p.max(0)-p.min(0)).prod())
def resample_polyline(P, n):
    """order by angle (profiles here are convex) and resample by arclength"""
    c=P.mean(0); Q=P-c; S=P[np.argsort(np.arctan2(Q[:,1],Q[:,0]))]
    S=np.vstack([S,S[:1]])
    d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(S,axis=0),axis=1))]
    t=np.linspace(0,d[-1],n,endpoint=False)
    return np.c_[np.interp(t,d,S[:,0]), np.interp(t,d,S[:,1])]
def dist_to_polyline(pts, poly):
    """exact point->segment distances (poly assumed closed)"""
    A=poly; B=np.roll(poly,-1,axis=0); AB=B-A; L2=(AB**2).sum(1)
    d=np.empty(len(pts))
    for i,p in enumerate(pts):
        t=np.clip(((p-A)*AB).sum(1)/np.maximum(L2,1e-30),0,1)
        proj=A+t[:,None]*AB
        d[i]=np.min(np.linalg.norm(proj-p,axis=1))
    return d
def stats(d):
    return dict(min=float(d.min()), max=float(d.max()), rms=float(np.sqrt((d**2).mean())), mean=float(d.mean()))
