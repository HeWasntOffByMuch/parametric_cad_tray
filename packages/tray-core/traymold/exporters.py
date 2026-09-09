"""Export.  Tessellation tolerances are explicit so exports are reproducible."""

from __future__ import annotations

from pathlib import Path

import cadquery as cq


def export_step(shape, path: str | Path) -> Path:
    path = Path(path)
    cq.exporters.export(cq.Workplane(obj=shape), str(path), exportType="STEP")
    return path


def export_stl(shape, path: str | Path, *, linear: float = 0.05, angular: float = 0.20) -> Path:
    path = Path(path)
    cq.exporters.export(
        cq.Workplane(obj=shape), str(path), exportType="STL",
        tolerance=linear, angularTolerance=angular,
    )
    return path


def export_all(result, outdir: str | Path, params) -> dict[str, Path]:
    from .quality import resolve

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    q = resolve(params)
    lin, ang = q.linear_deflection, q.angular_deflection
    written: dict[str, Path] = {}
    for name, shape in (("male", result.male), ("female", result.female)):
        if shape is None:
            continue
        written[f"{name}.step"] = export_step(shape, outdir / f"{params.name}-{name}.step")
        written[f"{name}.stl"] = export_stl(shape, outdir / f"{params.name}-{name}.stl",
                                            linear=lin, angular=ang)
    return written
