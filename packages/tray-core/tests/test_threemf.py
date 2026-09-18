"""The 3MF export: the file a slicer opens, where it puts things, and which
dialect it speaks.

Three things have to hold and none of them is visible in the geometry:

  * a modifier has to be *marked* as one. A reader that does not recognise it
    prints it as solid plastic - the clamp reinforcement becomes a column.
  * the two halves have to be somewhere. Both are built around the origin, so
    without a layout they arrive on top of each other, and the male is built
    with its plate below z=0, so it arrives sunk through the bed.
  * every region has to follow its part through both moves - the turn-over and
    the plate offset - or it reinforces empty space.
"""

import zipfile
from xml.etree import ElementTree as ET

import cadquery as cq
import pytest

from traymold.api import build, emit
from traymold.exporters import print_oriented
from traymold.mold import _volume
from traymold.presets import REF_4X7
from traymold.printplan import Settings, resolve
from traymold.quality import DEFAULTS
from traymold.threemf import (
    CORE_NS,
    ORCA,
    PLATE_STRIDE,
    PRUSA,
    lay_out,
    plate_origins,
    settings_items,
    write,
)

NS = {"c": CORE_NS}


def with_print(**kw):
    return REF_4X7.model_copy(update={"print": REF_4X7.print.model_copy(update=kw)})


@pytest.fixture(scope="module")
def built():
    # preview quality: this module is about the container, the layout and the
    # frame, and a coarser mesh says the same things about all three.
    return build(REF_4X7.with_quality("preview"))


def written(tmp_path, built, params, parts=None):
    plan = resolve(params).oriented(print_oriented)
    shapes = parts if parts is not None else {
        part: print_oriented(getattr(built, part), part) for part in ("male", "female")
    }
    path = write(tmp_path / "out.3mf", shapes, plan, DEFAULTS["preview"],
                 flavour=params.print.flavour)
    return zipfile.ZipFile(path)


def model_of(zf):
    return ET.fromstring(zf.read("3D/3dmodel.model"))


def meshes(zf):
    """Object id -> (name, vertices) for every object that carries a mesh."""
    out = {}
    for obj in model_of(zf).findall(".//c:object", NS):
        vertices = obj.findall(".//c:vertex", NS)
        if vertices:
            out[obj.get("id")] = (obj.get("name"),
                                  [(float(v.get("x")), float(v.get("y")), float(v.get("z")))
                                   for v in vertices])
    return out


# --------------------------------------------------------------------------
# where things go
# --------------------------------------------------------------------------
def test_the_plate_grid_is_square_ish_and_runs_rows_towards_minus_y():
    assert plate_origins(1) == [(0.0, 0.0)]
    assert plate_origins(2) == [(0.0, 0.0), (PLATE_STRIDE, 0.0)]
    # four goes two by two, second row at -Y
    assert plate_origins(4)[2] == (0.0, -PLATE_STRIDE)


@pytest.mark.parametrize("flavour", ["orca", "prusa"])
def test_each_half_gets_its_own_plate_and_stands_on_the_bed(tmp_path, built, flavour):
    zf = written(tmp_path, built, with_print(flavour=flavour))
    by_name = {}
    for name, vertices in meshes(zf).values():
        if name in ("male", "female"):
            by_name[name] = vertices

    for name, vertices in by_name.items():
        zs = [v[2] for v in vertices]
        assert min(zs) == pytest.approx(0.0, abs=1e-6), f"{name} is not resting on the bed"

    centres = {}
    for name, vertices in by_name.items():
        xs, ys = [v[0] for v in vertices], [v[1] for v in vertices]
        centres[name] = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    assert centres["male"] == pytest.approx((0.0, 0.0), abs=1e-6)
    assert centres["female"] == pytest.approx((PLATE_STRIDE, 0.0), abs=1e-6)


def test_the_halves_do_not_overlap(tmp_path, built):
    """Both are modelled around the origin, which is the whole reason a layout
    is needed: unlaid out they are exactly on top of each other."""
    zf = written(tmp_path, built, with_print(flavour="orca"))
    spans = {}
    for name, vertices in meshes(zf).values():
        if name in ("male", "female"):
            xs = [v[0] for v in vertices]
            spans[name] = (min(xs), max(xs))
    assert spans["male"][1] < spans["female"][0], "the two halves share bed space"


def test_the_plate_mapping_names_every_printed_object_once(tmp_path, built):
    zf = written(tmp_path, built, with_print(flavour="orca"))
    config = ET.fromstring(zf.read(ORCA.config))
    printed = {obj.get("id") for obj in config.findall("object")}
    plated = []
    for index, plate in enumerate(config.findall("plate"), start=1):
        assert plate.find("./metadata[@key='plater_id']").get("value") == str(index)
        instance = plate.find("model_instance")
        plated.append(instance.find("./metadata[@key='object_id']").get("value"))
    assert sorted(plated) == sorted(printed)
    assert len(plated) == 2, "two halves, two plates"


# --------------------------------------------------------------------------
# the container, per dialect
# --------------------------------------------------------------------------
@pytest.mark.parametrize("flavour,expected", [("orca", ORCA), ("prusa", PRUSA)])
def test_only_that_readers_config_is_written(tmp_path, built, flavour, expected):
    zf = written(tmp_path, built, with_print(flavour=flavour))
    assert expected.config in zf.namelist()
    other = PRUSA if expected is ORCA else ORCA
    assert other.config not in zf.namelist(), "two dialects in one file contradict each other"
    # Never the global print profile: loading one replaces the reader's preset.
    assert not any(n.endswith(("project_settings.config", "Slic3r_PE.config"))
                   for n in zf.namelist())
    assert model_of(zf).get("unit") == "millimeter"


def test_orca_gathers_the_parts_of_a_half_under_one_printed_object(tmp_path, built):
    zf = written(tmp_path, built, with_print(flavour="orca", profile="lean"))
    model = model_of(zf)
    components = {obj.get("name"): [c.get("objectid") for c in obj.findall(".//c:component", NS)]
                  for obj in model.findall(".//c:object", NS)
                  if obj.find(".//c:component", NS) is not None}
    assert set(components) == {"male", "female"}
    built_items = {i.get("objectid") for i in model.findall(".//c:item", NS)}
    assembled = {obj.get("id") for obj in model.findall(".//c:object", NS)
                 if obj.find(".//c:component", NS) is not None}
    assert built_items == assembled, "the bed should hold the assembled halves, not their parts"

    config = ET.fromstring(zf.read(ORCA.config))
    for obj in config.findall("object"):
        kinds = [p.get("subtype") for p in obj.findall("part")]
        assert kinds[0] == ORCA.part_kind
        assert set(kinds[1:]) <= {ORCA.modifier_kind}
        # every part must resolve to a component of that object
        ids = {p.get("id") for p in obj.findall("part")}
        assert ids == set(components[obj.find("./metadata[@key='name']").get("value")])


def test_prusa_names_its_parts_by_triangle_range(tmp_path, built):
    zf = written(tmp_path, built, with_print(flavour="prusa", profile="lean"))
    model, config = model_of(zf), ET.fromstring(zf.read(PRUSA.config))
    for obj in model.findall(".//c:object", NS):
        triangles = obj.findall(".//c:triangle", NS)
        spans = [(int(v.get("firstid")), int(v.get("lastid")))
                 for v in config.find(f"./object[@id='{obj.get('id')}']").findall("volume")]
        assert spans[0][0] == 0
        assert spans[-1][1] == len(triangles) - 1
        for (_, previous), (following, _) in zip(spans, spans[1:]):
            assert following == previous + 1, "the spans have a gap or an overlap"
    kinds = [v.find("./metadata[@key='volume_type']").get("value")
             for v in config.find("./object[@id='2']").findall("volume")]
    assert kinds[0] == PRUSA.part_kind
    assert set(kinds[1:]) <= {PRUSA.modifier_kind}


# --------------------------------------------------------------------------
# what it says about settings
# --------------------------------------------------------------------------
def test_each_dialect_uses_its_own_names_for_the_same_setting():
    lean = Settings(fill_density=0.10, fill_pattern="gyroid", perimeters=3,
                    top_solid_layers=6, bottom_solid_layers=5)
    assert dict(settings_items(lean, ORCA)) == {
        "sparse_infill_density": "10%", "sparse_infill_pattern": "gyroid",
        "wall_loops": "3", "top_shell_layers": "6", "bottom_shell_layers": "5",
    }
    assert dict(settings_items(lean, PRUSA)) == {
        "fill_density": "10%", "fill_pattern": "gyroid",
        "perimeters": "3", "top_solid_layers": "6", "bottom_solid_layers": "5",
    }


@pytest.mark.parametrize("flavour", [ORCA, PRUSA])
def test_a_modifier_says_only_what_it_changes(flavour):
    base = Settings(fill_density=0.10, fill_pattern="gyroid", perimeters=3,
                    top_solid_layers=6, bottom_solid_layers=5)
    dense = Settings(fill_density=0.70, fill_pattern="gyroid", perimeters=3,
                     top_solid_layers=6, bottom_solid_layers=5)
    assert len(settings_items(dense, flavour, against=base)) == 1
    assert settings_items(Settings(), flavour) == []


def test_the_slicer_profile_writes_a_mesh_and_no_modifiers(tmp_path, built):
    zf = written(tmp_path, built, with_print(flavour="orca", profile="slicer"))
    config = ET.fromstring(zf.read(ORCA.config))
    for obj in config.findall("object"):
        assert len(obj.findall("part")) == 1
    assert model_of(zf).findall(".//c:triangle", NS)


@pytest.mark.parametrize("flavour,dialect", [("orca", ORCA), ("prusa", PRUSA)])
def test_the_body_is_left_to_the_readers_own_profile(tmp_path, built, flavour, dialect):
    """Nothing is written against the object itself, only against the regions.

    An object-level override is not a suggestion - it wins over the reader's own
    controls, so a wall-loops slider stops doing anything and the file looks
    broken. The regions are local and additive and do not have that problem, so
    the plan reinforces where it must and leaves the body alone.
    """
    zf = written(tmp_path, built, with_print(flavour=flavour, profile="lean"))
    config = ET.fromstring(zf.read(dialect.config))
    setting_keys = set(dialect.keys[name][0] for name in dialect.keys)
    for obj in config.findall("object"):
        on_object = {m.get("key") for m in obj.findall("./metadata")}
        assert not (on_object & setting_keys), (
            f"{on_object & setting_keys} on the object would override the reader's own settings"
        )
    # the regions still carry theirs
    written_values = {m.get("key") for m in config.iter("metadata")}
    assert written_values & setting_keys


def test_provenance_records_the_plan_and_the_dialect(tmp_path, built):
    """The params hash deliberately excludes the print plan, so the file has to
    name it - and now the dialect too, since the same design writes two files."""
    zf = written(tmp_path, built, with_print(flavour="orca", profile="lean"))
    path = tmp_path / "t.3mf"
    plan = resolve(with_print(profile="lean")).oriented(print_oriented)
    write(path, {"female": print_oriented(built.female, "female")}, plan, DEFAULTS["preview"],
          {"params_hash": "abc123", "schema_version": "2.3.0",
           "model_version": "0.5.0", "quality": "preview"}, "orca")
    description = ET.fromstring(zipfile.ZipFile(path).read("3D/3dmodel.model")).find(
        "./c:metadata[@name='Description']", NS).text
    assert "print=lean" in description
    assert "flavour=orca" in description
    assert "params_hash=abc123" in description


# --------------------------------------------------------------------------
# the frame, which is the one way to get this silently wrong
# --------------------------------------------------------------------------
@pytest.mark.slow
def test_a_clamp_region_still_lands_on_its_bore_after_being_laid_out(built):
    """Two translations now compose: `print_oriented` turns the female over, and
    `lay_out` moves it to its plate and drops it to the bed. A region that
    follows only one of them reinforces plate where a bore should be.

    Read off the geometry: a clamp region sits over a through bore, so a slim
    column down its axis is empty over the whole plate.
    """
    printed = {part: print_oriented(getattr(built, part), part) for part in ("male", "female")}
    plan = resolve(REF_4X7).oriented(print_oriented)
    placed, moved = lay_out(printed, plan)

    female = cq.Solid(placed["female"].wrapped)
    thickness = REF_4X7.mold.cavity_plate_thickness
    region = next(r for r in moved.regions()
                  if r.part == "female" and r.name == "reinforce: clamp 1")
    box = region.solid.BoundingBox()
    probe = (cq.Workplane("XY").workplane(offset=-1.0)
             .center(box.center.x, box.center.y).circle(2.0).extrude(thickness + 2.0).val())
    assert _volume(female.intersect(probe)) == pytest.approx(0.0, abs=1.0), (
        "the laid-out region is not over the bore it reinforces"
    )
    # and it is on the female's plate, not still at the origin
    assert box.center.x > PLATE_STRIDE / 2


@pytest.mark.slow
@pytest.mark.parametrize("flavour", ["orca", "prusa"])
def test_write_artifacts_lays_the_pair_out(tmp_path, flavour):
    params = with_print(flavour=flavour).with_quality("preview")
    artifacts = emit(build(params), tmp_path, ("3mf",), quality=DEFAULTS["preview"], params=params)
    assert [a.name for a in artifacts] == ["tray-mold.3mf"]
    assert artifacts[0].part == "assembly"
    zf = zipfile.ZipFile(artifacts[0].path)
    halves = {name: v for name, v in meshes(zf).values() if name in ("male", "female")}
    assert set(halves) == {"male", "female"}
    for name, vertices in halves.items():
        assert min(v[2] for v in vertices) == pytest.approx(0.0, abs=1e-6)


def test_a_single_half_takes_the_only_plate(tmp_path):
    params = REF_4X7.model_copy(update={
        "mold": REF_4X7.mold.model_copy(update={
            "parts": REF_4X7.mold.parts.model_copy(update={"male": False})})}).with_quality("preview")
    artifacts = emit(build(params), tmp_path, ("3mf",), quality=DEFAULTS["preview"], params=params)
    assert [(a.name, a.part) for a in artifacts] == [("female.3mf", "female")]
    config = ET.fromstring(zipfile.ZipFile(artifacts[0].path).read(ORCA.config))
    assert len(config.findall("plate")) == 1


def test_the_writer_refuses_a_parameter_document_it_was_not_given(tmp_path):
    params = REF_4X7.with_quality("preview")
    with pytest.raises(ValueError, match="parameter document"):
        emit(build(params), tmp_path, ("3mf",), quality=DEFAULTS["preview"])
