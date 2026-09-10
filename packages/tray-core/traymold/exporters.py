"""Artifact writing.

Kept apart from `mold.build` so one build can serve several formats and so the
worker that owns the OCC solids is the only thing that ever touches them.

Two frames leave here.  The GLB keeps the frame the solids are built in -
assembly orientation - because the viewer has to show the two halves closed.
STEP and STL are print-oriented: `print_oriented` turns the female over so the
face that goes on the bed is the flat one.

Traceability: every format carries the params hash and the versions that produced
it, in whatever channel the format allows - STEP in its header, STL in its 80-byte
binary header, GLB in `asset.extras`.  A printed part can be traced to its inputs.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Sequence

import cadquery as cq

from .quality import Quality, DEFAULTS

PART_COLOURS = {
    "male": (0.36, 0.55, 0.85, 1.0),
    "female": (0.85, 0.62, 0.36, 1.0),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _trace(result) -> dict:
    return {
        "params_hash": result.params_hash,
        "schema_version": result.schema_version,
        "model_version": result.model_version,
        "quality": result.quality,
    }


def export_step(shape, path: Path) -> Path:
    cq.exporters.export(cq.Workplane(obj=shape), str(path), exportType="STEP")
    return path


def export_stl(shape, path: Path, quality: Quality) -> Path:
    cq.exporters.export(
        cq.Workplane(obj=shape), str(path), exportType="STL",
        tolerance=quality.linear_deflection, angularTolerance=quality.angular_deflection,
    )
    return path


def export_glb(result, path: Path, quality: Quality) -> Path:
    """One GLB holding both halves as separate named nodes.

    The assembly root is `tray-mold`; its children are `male` and `female`, each
    with its own mesh, so a viewer can show, hide and transform them
    independently.  Canonical frame: origin at the plan centre on the parting
    plane, +Z the plug direction - the same frame the solids are built in.

    Deliberately *not* print-oriented, unlike the STEP and STL: the viewer's job
    is to show the mold closed, and a female turned over for the bed would not
    meet the male.  See `print_oriented`.
    """
    from cadquery.occ_impl.exporters.assembly import exportGLTF

    assembly = cq.Assembly(name="tray-mold")
    for name in ("male", "female"):
        shape = getattr(result, name)
        if shape is not None:
            assembly.add(shape, name=name, color=cq.Color(*PART_COLOURS[name]))
    exportGLTF(
        assembly, str(path), binary=True,
        tolerance=quality.linear_deflection, angularTolerance=quality.angular_deflection,
    )
    _stamp_glb(path, _trace(result))
    return path


#: glTF defaults metallicFactor to 1.0 when a material omits it, and CadQuery's
#: exporter writes only baseColorFactor.  A fully metallic surface has no diffuse
#: term at all: with no environment map to reflect - and a static page has none -
#: it renders very nearly black, whatever lights are in the scene.  These are
#: printed plastic, so say so, in the artifact rather than in one viewer.
_GLB_MATERIAL = {"metallicFactor": 0.0, "roughnessFactor": 0.55}


def _stamp_glb(path: Path, trace: dict) -> None:
    """Write traceability into the glTF `asset.extras`, rewriting the JSON chunk."""
    raw = path.read_bytes()
    json_len = struct.unpack("<I", raw[12:16])[0]
    doc = json.loads(raw[20 : 20 + json_len])
    doc.setdefault("asset", {}).setdefault("extras", {}).update(trace)
    for material in doc.get("materials", []):
        material.setdefault("pbrMetallicRoughness", {}).update(_GLB_MATERIAL)
    body = raw[20 + json_len :]
    chunk = json.dumps(doc, separators=(",", ":")).encode()
    chunk += b" " * ((4 - len(chunk) % 4) % 4)
    total = 12 + 8 + len(chunk) + len(body)
    path.write_bytes(
        b"glTF" + struct.pack("<II", 2, total)
        + struct.pack("<I", len(chunk)) + b"JSON" + chunk
        + body
    )


def _stamp_stl(path: Path, trace: dict) -> None:
    """Binary STL keeps 80 bytes of free-form header; use them."""
    raw = bytearray(path.read_bytes())
    if len(raw) < 84:
        return
    note = f"traymold {trace['model_version']} {trace['params_hash'][:24]}".encode()[:80]
    raw[0:80] = note.ljust(80, b"\0")
    path.write_bytes(bytes(raw))


def _stamp_step(path: Path, trace: dict) -> None:
    text = path.read_text()
    marker = "FILE_DESCRIPTION("
    note = (
        f"/* traymold params_hash={trace['params_hash']} "
        f"schema={trace['schema_version']} model={trace['model_version']} "
        f"quality={trace['quality']} */\n"
    )
    if marker in text:
        text = text.replace(marker, note + marker, 1)
        path.write_text(text)


#: The solids are built in *assembly* orientation - z=0 is the parting plane and
#: +Z the plug direction - and that frame is what the viewer needs, because the
#: two halves only look like a mold when they are shown closed.  A slicer needs
#: the opposite thing: the face that goes on the bed.
#:
#: For the female those are not the same face.  Everything it carries that is not
#: symmetric in z is on the parting face at z=0 - the entry blend, the pry
#: notches, the clamp chamfers, the blind pin holes - which is precisely the face
#: you cannot print against.  Its outer face at z=`cavity_plate_thickness` is
#: flat: no blend (the top entry blend defaults to none), no notches, no
#: chamfers, no blind holes, only the openings of the clamp holes that pass all
#: the way through.  So the exported female is turned over.
#:
#: The male needs nothing: its base plate is already the lowest face and already
#: flat, with the plug printing upward.
PART_ROTATIONS = {"female": 180.0}


def print_oriented(shape, part: str):
    """Lay a part the way it is printed, not the way it is assembled.

    A **rotation about X**, never a mirror.  A mold half is chiral; mirroring one
    produces a part that cannot close on the other, and the two are easy to
    confuse because turning a real part over does flip its apparent handedness.
    Afterwards the solid is dropped so it rests on z=0.
    """
    angle = PART_ROTATIONS.get(part)
    if not angle:
        return shape
    turned = shape.rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), angle)
    return turned.translate((0.0, 0.0, -turned.BoundingBox().zmin))


def write_artifacts(
    result, outdir: Path, formats: Sequence[str], *, quality: Quality | None = None
) -> list:
    from .api import Artifact

    quality = quality or DEFAULTS["export"]
    outdir.mkdir(parents=True, exist_ok=True)
    trace = _trace(result)
    out: list[Artifact] = []
    # Once, not once per format: turning a solid over copies its whole TShape.
    printed = {
        part: print_oriented(shape, part)
        for part in ("male", "female")
        if (shape := getattr(result, part)) is not None
    }

    for fmt in formats:
        if fmt == "glb":
            # `result`, not `printed`: the viewer needs assembly orientation.
            present = [p for p in ("male", "female") if getattr(result, p) is not None]
            if not present:
                continue
            # A GLB holding one half is named for that half. Two half-builds of
            # the same design are merged into one job by the API, and two files
            # both called preview.glb would collide there - and "assembly" would
            # be a lie about a file with one part in it. Both halves in one file
            # keeps the old name, so a combined build is unchanged.
            part = present[0] if len(present) == 1 else "assembly"
            name = f"{part}.glb" if part != "assembly" else "preview.glb"
            path = outdir / name
            export_glb(result, path, quality)
            out.append(_artifact(name, "glb", part, path))
            continue
        for part, shape in printed.items():
            path = outdir / f"{part}.{fmt}"
            if fmt == "step":
                export_step(shape, path)
                _stamp_step(path, trace)
            elif fmt == "stl":
                export_stl(shape, path, quality)
                _stamp_stl(path, trace)
            else:
                raise ValueError(f"unknown export format {fmt!r}")
            out.append(_artifact(path.name, fmt, part, path))
    return out


def _artifact(name: str, fmt: str, part: str, path: Path):
    from .api import Artifact

    return Artifact(
        name=name, format=fmt, part=part, path=str(path),
        bytes=path.stat().st_size, sha256=_sha256(path),
    )


# --------------------------------------------------------------------------
# kept for the CLI
# --------------------------------------------------------------------------
def export_all(result, outdir: str | Path, params) -> dict[str, Path]:
    from .quality import resolve

    artifacts = write_artifacts(
        result, Path(outdir), ("step", "stl"), quality=resolve(params)
    )
    return {a.name: Path(a.path) for a in artifacts}
