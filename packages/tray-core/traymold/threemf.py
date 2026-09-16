"""3MF, with the print plan inside it.

Two things leave here in one file: the mesh, and what to print it at.

The mesh half is plain core 3MF - a zip holding `3D/3dmodel.model`.  The
settings half is `Metadata/Slic3r_PE_model.config`, the sidecar PrusaSlicer,
SuperSlicer and Orca all read.  That file is how the format carries a modifier:
every volume of an object concatenates into the object's single mesh, and the
config names each volume by its **triangle range** plus a `volume_type` of
`ModelPart` or `ParameterModifier`, with its own settings.

What is deliberately NOT written is `Metadata/Slic3r_PE.config`, the global
print profile.  A full profile is hundreds of keys, differs by slicer version
and by printer, and loading one would replace whatever preset the user has
tuned.  Per-object and per-volume overrides *merge onto* their own preset
instead, which is both far less code and the behaviour someone wants.  It is
also what makes this export version-tolerant: nothing here names a printer.

CadQuery 2.8 ships `ExportTypes.THREEMF`.  It is not used: its writer emits mesh
only - no `Metadata/` at all, every shape collapsed into one `<components>`
object - so it cannot carry a modifier, and one object per half is what a slicer
needs in order to let you select a half and change it.

Frame: whatever the caller hands over, with no build transform - in practice
print orientation, the same frame the STL goes out in.  The parts and the plan
must already be in the *same* frame: `exporters.print_oriented` turns the female
over, and `PrintPlan.oriented` turns its regions over with it.  A rotation about
X maps (x, y, z) -> (x, -y, -z), so a clamp region left in assembly coordinates
lands on the opposite diagonal and reinforces solid plastic while the real bore
sits in sparse lattice.  That is the one way to get this silently wrong, and
`test_threemf.py` reads it off the geometry rather than off the transform.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .printplan import PrintPlan, Region, Settings

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" TargetMode="Internal"/>'
    "</Relationships>"
)
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    '<Default Extension="config" ContentType="application/octet-stream"/>'
    "</Types>"
)

#: Neutral setting name -> the key PrusaSlicer, SuperSlicer and Orca read from a
#: model config, and how to render its value.  A `None` value is never written:
#: an absent key leaves the user's own preset alone, which is the whole point.
_PRUSA_KEYS: dict[str, tuple[str, callable]] = {
    "fill_density": ("fill_density", lambda v: f"{round(v * 100)}%"),
    "fill_pattern": ("fill_pattern", str),
    "perimeters": ("perimeters", lambda v: str(int(v))),
    "top_solid_layers": ("top_solid_layers", lambda v: str(int(v))),
    "bottom_solid_layers": ("bottom_solid_layers", lambda v: str(int(v))),
}


def settings_items(settings: Settings, against: Settings | None = None) -> list[tuple[str, str]]:
    """The (key, value) pairs a slicer config should carry for these settings.

    With `against`, only what actually differs from it is emitted.  A modifier
    that restates its object's own infill pattern and perimeter count is noise
    at best; at worst it reads as a deliberate override of something nobody
    meant to override.  A modifier should say only what it changes.
    """
    out = []
    for name, (key, render) in _PRUSA_KEYS.items():
        value = getattr(settings, name)
        if value is None or (against is not None and getattr(against, name) == value):
            continue
        out.append((key, render(value)))
    return out


# --------------------------------------------------------------------------
def _mesh_xml(verts, tris) -> str:
    """The `<mesh>` element.

    Built as text rather than as ElementTree nodes on purpose: the reference
    male is 209k triangles, and one XML element per triangle costs seconds of
    tree construction and hundreds of megabytes to hold.
    """
    parts = ["<mesh><vertices>"]
    parts.extend(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
    parts.append("</vertices><triangles>")
    parts.extend(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    parts.append("</triangles></mesh>")
    return "".join(parts)


def _tessellate(shape, quality):
    vs, ts = shape.tessellate(quality.linear_deflection, quality.angular_deflection)
    return [(v.x, v.y, v.z) for v in vs], [tuple(t) for t in ts]


def _volumes_for(part: str, shape, regions: list[Region], quality):
    """One part and its regions, tessellated.  Both are already in one frame."""
    out = [(part, "ModelPart", Settings(), _tessellate(shape, quality))]
    for region in regions:
        out.append((region.name, "ParameterModifier", region.settings,
                    _tessellate(region.solid, quality)))
    return out


def write(path: Path, parts: dict, plan: PrintPlan, quality,
          trace: dict | None = None) -> Path:
    """Write a project 3MF.

    `parts` maps "male"/"female" to a solid, and `plan` carries the regions for
    those same parts **in the same frame**.  See the note on frames above.
    """
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    note = "traymold wet-mold pair"
    if trace:
        note = (f"traymold model={trace.get('model_version')} "
                f"schema={trace.get('schema_version')} "
                f"quality={trace.get('quality')} print={plan.profile} "
                f"params_hash={trace.get('params_hash')}")

    model = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}">',
        '<metadata name="Application">traymold</metadata>',
        '<metadata name="Title">tray-mold</metadata>',
        f"<metadata name=\"Description\">{escape(note)}</metadata>",
        f'<metadata name="CreationDate">{created}</metadata>',
        "<resources>",
    ]
    build = ["<build>"]
    config = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]

    object_id = 0
    for part in ("male", "female"):
        shape = parts.get(part)
        if shape is None:
            continue
        object_id += 1
        part_plan = plan.parts.get(part)
        regions = part_plan.regions if part_plan is not None else []
        volumes = _volumes_for(part, shape, regions, quality)

        verts: list = []
        tris: list = []
        spans = []
        for name, kind, settings, (v, t) in volumes:
            base, first = len(verts), len(tris)
            verts.extend(v)
            tris.extend((a + base, b + base, c + base) for a, b, c in t)
            spans.append((name, kind, settings, first, len(tris) - 1))

        model.append(f'<object id="{object_id}" type="model" name={quoteattr(part)}>')
        model.append(_mesh_xml(verts, tris))
        model.append("</object>")
        build.append(f'<item objectid="{object_id}"/>')

        config.append(f'<object id="{object_id}">')
        config.append(f'<metadata type="object" key="name" value={quoteattr(part)}/>')
        if part_plan is not None:
            for key, value in settings_items(part_plan.base):
                config.append(
                    f'<metadata type="object" key={quoteattr(key)} value={quoteattr(value)}/>')
        for name, kind, settings, first, last in spans:
            config.append(f'<volume firstid="{first}" lastid="{last}">')
            config.append(f'<metadata type="volume" key="name" value={quoteattr(name)}/>')
            config.append(f'<metadata type="volume" key="volume_type" value="{kind}"/>')
            base = part_plan.base if part_plan is not None else None
            for key, value in settings_items(settings, against=base):
                config.append(
                    f'<metadata type="volume" key={quoteattr(key)} value={quoteattr(value)}/>')
            config.append("<mesh/>")
            config.append("</volume>")
        config.append("</object>")

    if object_id == 0:
        raise ValueError("a 3MF needs at least one part")

    model.append("</resources>")
    build.append("</build>")
    model.extend(build)
    model.append("</model>")
    config.append("</config>")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", "".join(model))
        zf.writestr("Metadata/Slic3r_PE_model.config", "".join(config))
    return path
