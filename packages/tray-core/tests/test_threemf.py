"""The 3MF export: the file a slicer reads, and the frame it reads it in."""

import zipfile
from xml.etree import ElementTree as ET

import cadquery as cq
import pytest

from traymold.api import build, emit
from traymold.exporters import print_oriented
from traymold.mold import _volume
from traymold.presets import REF_4X7
from traymold.printplan import resolve
from traymold.quality import DEFAULTS
from traymold.threemf import CORE_NS, settings_items, write
from traymold.printplan import Settings

NS = {"c": CORE_NS}


def with_print(**kw):
    return REF_4X7.model_copy(update={"print": REF_4X7.print.model_copy(update=kw)})


@pytest.fixture(scope="module")
def built():
    # preview quality: this module is about the container and the frame, and a
    # coarser mesh says exactly the same things about both in a fifth the time.
    return build(REF_4X7.with_quality("preview"))


def written(tmp_path, built, params, parts=None):
    plan = resolve(params).oriented(print_oriented)
    shapes = parts if parts is not None else {
        part: print_oriented(getattr(built, part), part) for part in ("male", "female")
    }
    path = write(tmp_path / "out.3mf", shapes, plan, DEFAULTS["preview"])
    return zipfile.ZipFile(path)


def model_of(zf):
    return ET.fromstring(zf.read("3D/3dmodel.model"))


def config_of(zf):
    return ET.fromstring(zf.read("Metadata/Slic3r_PE_model.config"))


# --------------------------------------------------------------------------
# the container
# --------------------------------------------------------------------------
def test_the_package_holds_what_a_slicer_opens(tmp_path, built):
    zf = written(tmp_path, built, REF_4X7)
    assert set(zf.namelist()) == {
        "[Content_Types].xml", "_rels/.rels",
        "3D/3dmodel.model", "Metadata/Slic3r_PE_model.config",
    }
    # Never the global print profile: loading one would replace whatever preset
    # the reader has tuned. See the note at the top of `threemf`.
    assert "Metadata/Slic3r_PE.config" not in zf.namelist()
    assert model_of(zf).get("unit") == "millimeter"


def test_one_object_per_half_named_for_its_half(tmp_path, built):
    zf = written(tmp_path, built, REF_4X7)
    objects = model_of(zf).findall(".//c:object", NS)
    assert [o.get("name") for o in objects] == ["male", "female"]
    items = model_of(zf).findall(".//c:item", NS)
    assert {i.get("objectid") for i in items} == {o.get("id") for o in objects}


def test_every_triangle_belongs_to_exactly_one_named_volume(tmp_path, built):
    """The triangle ranges are the whole mechanism: a modifier is a span of the
    object's own mesh, so a span that is off by one is a modifier pointing at
    someone else's geometry."""
    zf = written(tmp_path, built, REF_4X7)
    model, config = model_of(zf), config_of(zf)
    for obj in model.findall(".//c:object", NS):
        triangles = obj.findall(".//c:triangle", NS)
        vertices = obj.findall(".//c:vertex", NS)
        spans = [(int(v.get("firstid")), int(v.get("lastid")))
                 for v in config.find(f"./object[@id='{obj.get('id')}']").findall("volume")]
        assert spans[0][0] == 0
        assert spans[-1][1] == len(triangles) - 1
        for (_, previous_last), (next_first, _) in zip(spans, spans[1:]):
            assert next_first == previous_last + 1, "the spans have a gap or overlap"
        highest = max(max(int(t.get(k)) for k in ("v1", "v2", "v3")) for t in triangles)
        assert highest == len(vertices) - 1


def test_the_part_is_a_ModelPart_and_the_regions_are_modifiers(tmp_path, built):
    zf = written(tmp_path, built, with_print(profile="lean"))
    female = config_of(zf).find("./object[@id='2']")
    kinds = [v.find("./metadata[@key='volume_type']").get("value")
             for v in female.findall("volume")]
    assert kinds[0] == "ModelPart"
    assert set(kinds[1:]) == {"ParameterModifier"}


# --------------------------------------------------------------------------
# what it says about settings
# --------------------------------------------------------------------------
def test_a_modifier_says_only_what_it_changes():
    base = Settings(fill_density=0.10, fill_pattern="gyroid", perimeters=3,
                    top_solid_layers=6, bottom_solid_layers=5)
    dense = Settings(fill_density=0.70, fill_pattern="gyroid", perimeters=3,
                     top_solid_layers=6, bottom_solid_layers=5)
    assert settings_items(dense, against=base) == [("fill_density", "70%")]
    assert dict(settings_items(base))["fill_density"] == "10%"
    # None is "say nothing", which is not the same as a value
    assert settings_items(Settings()) == []


def test_the_slicer_profile_writes_a_mesh_and_no_settings(tmp_path, built):
    zf = written(tmp_path, built, with_print(profile="slicer"))
    config = config_of(zf)
    for obj in config.findall("object"):
        keys = [m.get("key") for m in obj.findall("./metadata")]
        assert keys == ["name"], "an unplanned export must not touch the reader's preset"
        assert len(obj.findall("volume")) == 1
    assert model_of(zf).findall(".//c:triangle", NS)


def test_the_object_carries_the_plan_and_the_file_carries_its_provenance(tmp_path, built):
    zf = written(tmp_path, built, with_print(profile="lean"))
    male = config_of(zf).find("./object[@id='1']")
    settings = {m.get("key"): m.get("value") for m in male.findall("./metadata")}
    assert settings["fill_density"] == "10%"
    assert settings["fill_pattern"] == "gyroid"
    assert settings["perimeters"] == "3"


def test_provenance_records_the_print_profile_too(tmp_path, built):
    """The params hash deliberately excludes the print plan, so the file has to
    name the plan itself or a printed part cannot be traced back to it."""
    plan = resolve(with_print(profile="lean")).oriented(print_oriented)
    path = write(tmp_path / "t.3mf", {"female": print_oriented(built.female, "female")},
                 plan, DEFAULTS["preview"],
                 {"params_hash": "abc123", "schema_version": "2.1.0",
                  "model_version": "0.4.0", "quality": "preview"})
    description = ET.fromstring(zipfile.ZipFile(path).read("3D/3dmodel.model")).find(
        "./c:metadata[@name='Description']", NS).text
    assert "print=lean" in description
    assert "params_hash=abc123" in description


# --------------------------------------------------------------------------
# the frame, which is the one way to get this silently wrong
# --------------------------------------------------------------------------
@pytest.mark.slow
def test_a_clamp_region_lands_on_the_bore_it_exists_to_reinforce(built):
    """`print_oriented` turns the female over, and a rotation about X maps
    (x, y, z) -> (x, -y, -z) - so a region left in assembly coordinates reaches
    the opposite diagonal, reinforcing solid plastic while the real bore sits in
    sparse lattice.  Read off the geometry, not off the transform: a region that
    covers a bore intersects its part by *less* than its own volume, and one on
    the wrong diagonal intersects by all of it.
    """
    printed = cq.Solid(print_oriented(built.female, "female").wrapped)
    thickness = REF_4X7.mold.cavity_plate_thickness

    def bore_under(region):
        """How much of a slim column down the region's axis is material.

        A clamp region exists to surround a through bore, so the column at its
        centre should be empty over the whole plate. Somewhere with no bore
        under it is solid all the way down - which is the failure, and it is
        read off the part rather than off the transform.
        """
        box = region.solid.BoundingBox()
        probe = (cq.Workplane("XY").workplane(offset=-1.0)
                 .center(box.center.x, box.center.y).circle(2.0)
                 .extrude(thickness + 2.0).val())
        return _volume(printed.intersect(probe))

    turned = next(r for r in resolve(REF_4X7).oriented(print_oriented).regions()
                  if r.part == "female" and r.name == "clamp-bearing-0")
    unturned = next(r for r in resolve(REF_4X7).regions()
                    if r.part == "female" and r.name == "clamp-bearing-0")

    assert bore_under(turned) == pytest.approx(0.0, abs=1.0), (
        "the oriented region should sit on the through bore it reinforces"
    )
    # Not merely "some material": the unturned region reaches the other diagonal,
    # where the plate is unbored, so the column is material over its full depth.
    assert bore_under(unturned) > 0.5 * 4.0 * 3.14159 * thickness, (
        "the unturned region found unbored plate, which is exactly the trap"
    )


@pytest.mark.slow
def test_write_artifacts_hands_the_writer_an_oriented_plan(tmp_path):
    """The end-to-end version of the same thing, through the public path."""
    params = REF_4X7.with_quality("preview")
    result = build(params)
    artifacts = emit(result, tmp_path, ("3mf",), quality=DEFAULTS["preview"], params=params)
    assert [a.name for a in artifacts] == ["tray-mold.3mf"]
    assert artifacts[0].part == "assembly"

    zf = zipfile.ZipFile(artifacts[0].path)
    female = model_of(zf).findall(".//c:object", NS)[1]
    zs = [float(v.get("z")) for v in female.findall(".//c:vertex", NS)]
    assert min(zs) == pytest.approx(0.0, abs=1e-6), "the exported part should rest on the bed"
    assert max(zs) == pytest.approx(REF_4X7.mold.cavity_plate_thickness, abs=1e-3)


def test_a_single_half_is_named_for_that_half(tmp_path):
    params = REF_4X7.model_copy(update={
        "mold": REF_4X7.mold.model_copy(update={
            "parts": REF_4X7.mold.parts.model_copy(update={"male": False})})}).with_quality("preview")
    result = build(params)
    artifacts = emit(result, tmp_path, ("3mf",), quality=DEFAULTS["preview"], params=params)
    assert [(a.name, a.part) for a in artifacts] == [("female.3mf", "female")]


def test_the_writer_refuses_a_parameter_document_it_was_not_given(tmp_path):
    params = REF_4X7.with_quality("preview")
    result = build(params)
    with pytest.raises(ValueError, match="parameter document"):
        emit(result, tmp_path, ("3mf",), quality=DEFAULTS["preview"])
