"""3MF, with the print plan inside it.

Three things leave here in one file: the mesh, where each half goes on the bed,
and what to print it at.

The mesh half is core 3MF - a zip holding `3D/3dmodel.model`.  The rest is a
sidecar config, and **there are two mutually exclusive dialects of it**:

| flavour | config | parts | plates |
|---|---|---|---|
| `orca` | `Metadata/model_settings.config` | one `<object>` per part, gathered by the printed object's `<components>` | yes |
| `prusa` | `Metadata/Slic3r_PE_model.config` | one mesh per object, parts named by **triangle range** | no |

They cannot be combined, because they disagree about the mesh itself: Orca wants
a component per part and PrusaSlicer wants one concatenated mesh.  Writing both
into one file would leave one of the two readers treating a modifier as ordinary
geometry - which is not a cosmetic failure, it prints the clamp reinforcement as
a solid column of plastic.  So `params.print.flavour` chooses, and it defaults
to `orca`: plates are a Bambu Studio and Orca idea, PrusaSlicer has no such
thing.

What neither flavour writes is the global print profile -
`Metadata/project_settings.config` for Orca, `Metadata/Slic3r_PE.config` for
PrusaSlicer.  Those are hundreds of keys naming one printer, and loading one
replaces whatever preset the reader has tuned.  Per-object and per-part
overrides merge onto their own preset instead, which is far less code and the
behaviour someone wants.  It is also what keeps this export version-tolerant:
nothing in the file names a printer.

Frame: each half is laid out by `lay_out` - centred on its own plate and resting
on the bed - and the plan's regions are moved with it.  A region left behind
points at nothing, and `print_oriented` has already turned the female over by
then, so the two translations compose.  `test_threemf.py` reads that off the
geometry rather than off the transforms.

CadQuery 2.8 ships `ExportTypes.THREEMF`.  It is not used: its writer emits mesh
only, with no `Metadata/` at all, so it cannot carry a modifier or a plate.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .printplan import PrintPlan, Settings

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

#: Identity, as 3MF writes a transform: the first three columns of a 4x4, row
#: major.  Every component here is already in place in its own vertices.
_IDENTITY = "1 0 0 0 1 0 0 0 1 0 0 0"


@dataclass(frozen=True)
class Flavour:
    """One reader's dialect: where its config goes, and what it calls things."""

    name: str
    config: str
    #: Neutral setting name -> (this reader's key, how to render the value).
    keys: dict
    #: What this reader calls an ordinary part and a settings-only one.
    part_kind: str
    modifier_kind: str
    #: Does it lay objects out across several build plates?
    plates: bool


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _count(value: float) -> str:
    return str(int(value))


ORCA = Flavour(
    name="orca",
    config="Metadata/model_settings.config",
    keys={
        "fill_density": ("sparse_infill_density", _percent),
        "fill_pattern": ("sparse_infill_pattern", str),
        "perimeters": ("wall_loops", _count),
        "top_solid_layers": ("top_shell_layers", _count),
        "bottom_solid_layers": ("bottom_shell_layers", _count),
    },
    part_kind="normal_part",
    modifier_kind="modifier_part",
    plates=True,
)

PRUSA = Flavour(
    name="prusa",
    config="Metadata/Slic3r_PE_model.config",
    keys={
        "fill_density": ("fill_density", _percent),
        "fill_pattern": ("fill_pattern", str),
        "perimeters": ("perimeters", _count),
        "top_solid_layers": ("top_solid_layers", _count),
        "bottom_solid_layers": ("bottom_solid_layers", _count),
    },
    part_kind="ModelPart",
    modifier_kind="ParameterModifier",
    plates=False,
)

FLAVOURS = {f.name: f for f in (ORCA, PRUSA)}


def settings_items(settings: Settings, flavour: Flavour,
                   against: Settings | None = None) -> list[tuple[str, str]]:
    """The (key, value) pairs this reader's config should carry.

    With `against`, only what actually differs from it is emitted.  A modifier
    that restates its object's own infill pattern is noise at best; at worst it
    reads as a deliberate override of something nobody meant to override.
    """
    out = []
    for name, (key, render) in flavour.keys.items():
        value = getattr(settings, name)
        if value is None or (against is not None and getattr(against, name) == value):
            continue
        out.append((key, render(value)))
    return out


# --------------------------------------------------------------------------
# where each half goes
# --------------------------------------------------------------------------
#: Bambu Studio and Orca do not store a plate number against a position - they
#: read the position.  Plates are cells of one very large virtual bed, and an
#: object belongs to the plate whose cell it sits in, so the layout below is not
#: decoration: it is what makes `plater_id` true.
#:
#: The stride is the bed plus a fifth, which is what Bambu's own PartPlate grid
#: uses.  256 mm is the A1 / P1S / X1C bed; a different bed only changes how far
#: apart the plates are, never the parts on them, and a reader lays the plates
#: out on its own bed once it has them.
PLATE_BED = 256.0
PLATE_STRIDE = PLATE_BED * 1.2


def plate_origins(count: int) -> list[tuple[float, float]]:
    """The centre of each plate, in the order the parts are given.

    Bambu's own arrangement: roughly square, filling columns first and running
    rows towards -Y.
    """
    root = count ** 0.5
    nearest = int(root + 0.5)
    columns = nearest + 1 if root > nearest else max(1, nearest)
    out = []
    for index in range(count):
        row, column = divmod(index, columns)
        out.append((column * PLATE_STRIDE, -row * PLATE_STRIDE))
    return out


def lay_out(parts: dict, plan: PrintPlan) -> tuple[dict, PrintPlan]:
    """One half per plate, centred on it and standing on the bed.

    Both halves are built around the origin, so without this they arrive exactly
    on top of each other - and the male is built with its base plate below z=0,
    so it arrives sunk through the bed. A slicer will rescue a loose mesh from
    both of those; a project file is meant to say where things go, so it says.

    The plan is moved with the parts, for the reason `PrintPlan.oriented`
    exists: a region that does not follow its part points at nothing.
    """
    moves: dict[str, tuple[float, float, float]] = {}
    for (name, shape), (x, y) in zip(parts.items(), plate_origins(len(parts))):
        box = shape.BoundingBox()
        moves[name] = (x - box.center.x, y - box.center.y, -box.zmin)
    placed = {name: shape.translate(moves[name]) for name, shape in parts.items()}

    # A plan is resolved from the parameter document and can carry regions for a
    # half this file does not contain - a caller writing one half of a pair that
    # was built as two. Those regions have nowhere to go, so they are dropped
    # here rather than left at the origin, where they would be a modifier
    # floating in the middle of the bed.
    kept = PrintPlan(
        profile=plan.profile,
        extrusion_width=plan.extrusion_width,
        layer_height=plan.layer_height,
        parts={name: part for name, part in plan.parts.items() if name in parts},
    )
    return placed, kept.oriented(lambda solid, part: solid.translate(moves[part]))


# --------------------------------------------------------------------------
# the file
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
    """Triangles for one shape, from the shared mesh.

    `exporters.mesh` is what sets the triangle-size floor; `Shape.tessellate`
    then reuses the triangulation it finds rather than making its own, so the
    3MF and the STL describe the same surface and the shape is meshed once.
    """
    from .exporters import mesh

    mesh(shape, quality)
    vs, ts = shape.tessellate(quality.linear_deflection, quality.angular_deflection)
    return [(v.x, v.y, v.z) for v in vs], [tuple(t) for t in ts]


def _volumes_for(part: str, shape, regions, quality):
    """One half and its regions, tessellated.  All already in one frame."""
    out = [(part, False, Settings(), _tessellate(shape, quality))]
    for region in regions:
        out.append((region.name, True, region.settings, _tessellate(region.solid, quality)))
    return out


def _header(created: str, note: str) -> list[str]:
    return [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}">',
        '<metadata name="Application">traymold</metadata>',
        '<metadata name="Title">tray-mold</metadata>',
        f"<metadata name=\"Description\">{escape(note)}</metadata>",
        f'<metadata name="CreationDate">{created}</metadata>',
        "<resources>",
    ]


def _write_orca(parts: dict, plan: PrintPlan, quality, note: str, created: str):
    """A part per component, a half per plate."""
    model = _header(created, note)
    build = ["<build>"]
    config = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    plates: list[tuple[int, str]] = []
    next_id = 1

    for part, shape in parts.items():
        part_plan = plan.parts.get(part)
        base = part_plan.base if part_plan is not None else None
        volumes = _volumes_for(part, shape, part_plan.regions if part_plan else [], quality)

        # Children first: 3MF requires an object to exist before it is referenced.
        children = []
        for name, is_modifier, settings, (verts, tris) in volumes:
            model.append(f'<object id="{next_id}" type="model" name={quoteattr(name)}>')
            model.append(_mesh_xml(verts, tris))
            model.append("</object>")
            children.append((next_id, name, is_modifier, settings))
            next_id += 1

        printed_id = next_id
        next_id += 1
        model.append(f'<object id="{printed_id}" type="model" name={quoteattr(part)}><components>')
        for child_id, *_ in children:
            model.append(f'<component objectid="{child_id}" transform="{_IDENTITY}"/>')
        model.append("</components></object>")
        build.append(f'<item objectid="{printed_id}" transform="{_IDENTITY}"/>')

        config.append(f'<object id="{printed_id}">')
        config.append(f'<metadata key="name" value={quoteattr(part)}/>')
        config.append('<metadata key="extruder" value="1"/>')
        if base is not None:
            for key, value in settings_items(base, ORCA):
                config.append(f'<metadata key={quoteattr(key)} value={quoteattr(value)}/>')
        for child_id, name, is_modifier, settings in children:
            kind = ORCA.modifier_kind if is_modifier else ORCA.part_kind
            config.append(f'<part id="{child_id}" subtype="{kind}">')
            config.append(f'<metadata key="name" value={quoteattr(name)}/>')
            for key, value in settings_items(settings, ORCA, against=base if is_modifier else None):
                config.append(f'<metadata key={quoteattr(key)} value={quoteattr(value)}/>')
            config.append("</part>")
        config.append("</object>")
        plates.append((printed_id, part))

    for index, (object_id, name) in enumerate(plates, start=1):
        config.append("<plate>")
        config.append(f'<metadata key="plater_id" value="{index}"/>')
        config.append(f'<metadata key="plater_name" value={quoteattr(name)}/>')
        config.append('<metadata key="locked" value="false"/>')
        config.append("<model_instance>")
        config.append(f'<metadata key="object_id" value="{object_id}"/>')
        config.append('<metadata key="instance_id" value="0"/>')
        config.append("</model_instance>")
        config.append("</plate>")

    model.append("</resources>")
    build.append("</build>")
    model.extend(build)
    model.append("</model>")
    config.append("</config>")
    return "".join(model), "".join(config)


def _write_prusa(parts: dict, plan: PrintPlan, quality, note: str, created: str):
    """One mesh per object; parts are triangle ranges within it."""
    model = _header(created, note)
    build = ["<build>"]
    config = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    object_id = 0

    for part, shape in parts.items():
        object_id += 1
        part_plan = plan.parts.get(part)
        base = part_plan.base if part_plan is not None else None
        volumes = _volumes_for(part, shape, part_plan.regions if part_plan else [], quality)

        verts: list = []
        tris: list = []
        spans = []
        for name, is_modifier, settings, (v, t) in volumes:
            offset, first = len(verts), len(tris)
            verts.extend(v)
            tris.extend((a + offset, b + offset, c + offset) for a, b, c in t)
            spans.append((name, is_modifier, settings, first, len(tris) - 1))

        model.append(f'<object id="{object_id}" type="model" name={quoteattr(part)}>')
        model.append(_mesh_xml(verts, tris))
        model.append("</object>")
        build.append(f'<item objectid="{object_id}"/>')

        config.append(f'<object id="{object_id}">')
        config.append(f'<metadata type="object" key="name" value={quoteattr(part)}/>')
        if base is not None:
            for key, value in settings_items(base, PRUSA):
                config.append(
                    f'<metadata type="object" key={quoteattr(key)} value={quoteattr(value)}/>')
        for name, is_modifier, settings, first, last in spans:
            kind = PRUSA.modifier_kind if is_modifier else PRUSA.part_kind
            config.append(f'<volume firstid="{first}" lastid="{last}">')
            config.append(f'<metadata type="volume" key="name" value={quoteattr(name)}/>')
            config.append(f'<metadata type="volume" key="volume_type" value="{kind}"/>')
            for key, value in settings_items(settings, PRUSA, against=base if is_modifier else None):
                config.append(
                    f'<metadata type="volume" key={quoteattr(key)} value={quoteattr(value)}/>')
            config.append("<mesh/>")
            config.append("</volume>")
        config.append("</object>")

    model.append("</resources>")
    build.append("</build>")
    model.extend(build)
    model.append("</model>")
    config.append("</config>")
    return "".join(model), "".join(config)


_WRITERS = {"orca": _write_orca, "prusa": _write_prusa}


def write(path: Path, parts: dict, plan: PrintPlan, quality,
          trace: dict | None = None, flavour: str = "orca") -> Path:
    """Write a project 3MF.

    `parts` maps "male"/"female" to a solid and `plan` carries the regions for
    those same parts, in the same frame.  Both are laid out here, one half per
    plate; see `lay_out`.
    """
    if not parts:
        raise ValueError("a 3MF needs at least one part")
    dialect = FLAVOURS[flavour]
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    note = "traymold wet-mold pair"
    if trace:
        note = (f"traymold model={trace.get('model_version')} "
                f"schema={trace.get('schema_version')} "
                f"quality={trace.get('quality')} print={plan.profile} "
                f"flavour={dialect.name} params_hash={trace.get('params_hash')}")

    placed, moved = lay_out(parts, plan)
    model, config = _WRITERS[dialect.name](placed, moved, quality, note, created)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", model)
        zf.writestr(dialect.config, config)
    return path
