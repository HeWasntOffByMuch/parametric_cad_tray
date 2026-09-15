"""A project 3MF with modifier volumes, in one file, to size the real thing.

    python3 tools/print_study/threemf_prototype.py [outdir]

This is a *prototype*, kept in tools/ rather than in `traymold.exporters`, and
it exists to answer one question: how much work is a 3MF export that carries
print settings?  It writes what PrusaSlicer, SuperSlicer and Orca all read:

    [Content_Types].xml               boilerplate
    _rels/.rels                       boilerplate
    3D/3dmodel.model                  core 3MF - the mesh
    Metadata/Slic3r_PE_model.config   the per-object and per-volume settings

One ModelObject per half.  Every volume's triangles are concatenated into that
object's single mesh, and the config names each volume by its triangle range -
that is how the format carries a modifier: a modifier is a volume whose type is
`ParameterModifier`, with its own settings, sharing the object's mesh array.

Deliberately NOT written here: `Metadata/Slic3r_PE.config`, the global print
profile.  A full profile is hundreds of keys, is version- and printer-specific,
and would overwrite whatever preset the user has already tuned.  Per-object and
per-volume overrides are merged onto the user's own preset instead, which is
both far less code and the behaviour someone actually wants.

CadQuery 2.8 ships `ExportTypes.THREEMF`, but its writer emits mesh only - no
Metadata/ directory, and all shapes collapsed into one `<components>` object.
It is the right thing for a plain mesh export and cannot carry a modifier, so
the writer below replaces it rather than wrapping it.
"""

from __future__ import annotations

import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxml'
        'formats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" '
        'Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" '
        'TargetMode="Internal"/></Relationships>')
TYPES = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org'
         '/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
         'openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType='
         '"application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')


@dataclass
class Volume:
    """One mesh inside an object: the part itself, or a region that overrides it."""
    name: str
    verts: list
    tris: list
    kind: str = "ModelPart"                    # or "ParameterModifier"
    settings: dict = field(default_factory=dict)


@dataclass
class Obj:
    name: str
    volumes: list
    settings: dict = field(default_factory=dict)


def write(objects, path: Path) -> Path:
    model = ET.Element("model", {"unit": "millimeter", "xml:lang": "en-US", "xmlns": CORE})
    resources = ET.SubElement(model, "resources")
    build = ET.SubElement(model, "build")
    config = ET.Element("config")

    for index, obj in enumerate(objects, start=1):
        verts: list = []
        tris: list = []
        spans = []
        for volume in obj.volumes:
            base, first = len(verts), len(tris)
            verts.extend(volume.verts)
            tris.extend((a + base, b + base, c + base) for a, b, c in volume.tris)
            spans.append((volume, first, len(tris) - 1))

        xml_obj = ET.SubElement(resources, "object", id=str(index), type="model")
        mesh = ET.SubElement(xml_obj, "mesh")
        xml_verts = ET.SubElement(mesh, "vertices")
        for x, y, z in verts:
            ET.SubElement(xml_verts, "vertex", x=f"{x:.5f}", y=f"{y:.5f}", z=f"{z:.5f}")
        xml_tris = ET.SubElement(mesh, "triangles")
        for a, b, c in tris:
            ET.SubElement(xml_tris, "triangle", v1=str(a), v2=str(b), v3=str(c))
        ET.SubElement(build, "item", objectid=str(index))

        cfg_obj = ET.SubElement(config, "object", id=str(index))
        ET.SubElement(cfg_obj, "metadata", type="object", key="name", value=obj.name)
        for key, value in obj.settings.items():
            ET.SubElement(cfg_obj, "metadata", type="object", key=key, value=str(value))
        for volume, first, last in spans:
            cfg_vol = ET.SubElement(cfg_obj, "volume", firstid=str(first), lastid=str(last))
            ET.SubElement(cfg_vol, "metadata", type="volume", key="name", value=volume.name)
            ET.SubElement(cfg_vol, "metadata", type="volume", key="volume_type", value=volume.kind)
            for key, value in volume.settings.items():
                ET.SubElement(cfg_vol, "metadata", type="volume", key=key, value=str(value))
            ET.SubElement(cfg_vol, "mesh")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", TYPES)
        zf.writestr("_rels/.rels", RELS)
        zf.writestr("3D/3dmodel.model", ET.tostring(model, encoding="utf-8", xml_declaration=True))
        zf.writestr("Metadata/Slic3r_PE_model.config",
                    ET.tostring(config, encoding="utf-8", xml_declaration=True))
    return path


# --------------------------------------------------------------------------
# a solver, in miniature: params -> regions
# --------------------------------------------------------------------------
def demo(outdir: Path) -> None:
    import cadquery as cq
    from traymold.derive import derive
    from traymold.exporters import print_oriented
    from traymold.mold import build
    from traymold.presets import REF_4X7
    from traymold.quality import DEFAULTS

    quality = DEFAULTS["export"]

    def tessellate(shape):
        vs, ts = shape.tessellate(quality.linear_deflection, quality.angular_deflection)
        return [(v.x, v.y, v.z) for v in vs], [tuple(t) for t in ts]

    params = REF_4X7.with_quality("export")
    result = build(params)
    d = derive(params)
    depth, t_plate = params.tray.depth, params.mold.cavity_plate_thickness
    ch = params.features.clamp_holes
    x, y = d.plate_length / 2 - ch.inset, d.plate_width / 2 - ch.inset

    objects = []
    for half, regions in (
        ("male", [
            ("forming-face-backing",
             cq.Workplane("XY").workplane(offset=depth - 5.0)
               .rect(d.plate_length, d.plate_width).extrude(5.0).val(),
             {"fill_density": "35%"}),
        ]),
        ("female", [
            (f"clamp-{name}",
             cq.Workplane("XY").center(cx, cy).circle(1.5 * ch.diameter).extrude(t_plate).val(),
             {"fill_density": "70%", "perimeters": 4})
            for name, (cx, cy) in zip(("a", "b"), [(-x, y), (x, -y)])
        ]),
    ):
        shape = getattr(result, half)
        if shape is None:
            continue
        # THE TRAP.  The part is turned over on the way to the bed, and a
        # modifier built in assembly coordinates is not turned over with it: a
        # rotation about X maps (x, y, z) -> (x, -y, -z), so a clamp column
        # lands on the opposite diagonal from the bore it is meant to reinforce.
        # Every region goes through `print_oriented` with the part it belongs to.
        volumes = [Volume(half, *tessellate(print_oriented(shape, half)))]
        for name, region, settings in regions:
            volumes.append(Volume(name, *tessellate(print_oriented(region, half)),
                                  kind="ParameterModifier", settings=settings))
        objects.append(Obj(half, volumes, settings={
            "fill_density": "10%", "fill_pattern": "gyroid",
            "perimeters": 3, "top_solid_layers": 6, "bottom_solid_layers": 5,
        }))

    path = write(objects, outdir / "tray-mold.3mf")
    zf = zipfile.ZipFile(path)
    print(f"wrote {path}")
    for info in zf.infolist():
        print(f"  {info.filename:<34}{info.file_size:>12,} ->{info.compress_size:>10,}")
    print(f"  {'TOTAL':<34}{'':>12} {sum(i.compress_size for i in zf.infolist()):>10,} bytes")
    for obj in objects:
        print(f"  object {obj.name}: " + ", ".join(
            f"{v.name} ({v.kind}, {len(v.tris):,} tri)" for v in obj.volumes))


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    out.mkdir(parents=True, exist_ok=True)
    demo(out)
