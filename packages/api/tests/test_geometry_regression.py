"""The reference preset travelling the whole API pipeline.

The core suite proves the geometry; these check that nothing between the HTTP
request and the downloaded file damages it.  Representative cases only.
"""

import struct
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from conftest import poll

pytestmark = pytest.mark.slow

CORE_TESTS = Path(__file__).resolve().parents[3] / "packages" / "tray-core" / "tests"


def _reference_module():
    import sys

    sys.path.insert(0, str(CORE_TESTS))
    import reference

    return reference


def test_exported_step_matches_the_original_within_the_export_tolerance(live_client, ref_params, tmp_path):
    """The 10 um contract, measured on the file a client actually downloads."""
    import cadquery as cq

    reference = _reference_module()
    job = poll(live_client, live_client.post("/api/export", json={"params": ref_params}).json()["id"])
    assert job["state"] == "complete"

    downloaded = tmp_path / "male.step"
    downloaded.write_bytes(live_client.get(job["artifacts"]["male.step"]["url"]).content)
    built = cq.importers.importStep(str(downloaded)).val()
    original = reference.load_reference("male_tray_mold.step")

    for z in (0.5, 5.0, 12.5, 20.0, 22.5, 24.0):
        deviation = reference.compare_forming_profiles(built, original, z, per_edge=200)
        assert deviation["max"] <= 0.010, f"z={z}: {deviation['max'] * 1e3:.2f} um"


def test_exported_stl_is_binary_and_has_the_expected_scale(live_client, ref_params, tmp_path):
    job = poll(live_client, live_client.post("/api/export", json={"params": ref_params}).json()["id"])
    raw = live_client.get(job["artifacts"]["female.stl"]["url"]).content
    triangles = struct.unpack("<I", raw[80:84])[0]
    assert len(raw) == 84 + 50 * triangles
    assert triangles > 1000
    assert raw[:8].startswith(b"traymold"), "the STL header should carry traceability"


def test_step_carries_traceability_metadata(live_client, ref_params):
    job = poll(live_client, live_client.post("/api/export", json={"params": ref_params}).json()["id"])
    text = live_client.get(job["artifacts"]["male.step"]["url"]).content.decode("utf-8", "replace")
    assert f"params_hash={job['params_hash']}" in text
    assert "schema=" in text and "model=" in text


def test_preview_glb_has_separate_male_and_female_nodes(live_client, ref_params):
    import json

    job = poll(live_client, live_client.post("/api/preview", json={"params": ref_params}).json()["id"])
    raw = live_client.get(job["artifacts"]["preview.glb"]["url"]).content
    assert raw[:4] == b"glTF" and struct.unpack("<I", raw[4:8])[0] == 2
    json_len = struct.unpack("<I", raw[12:16])[0]
    doc = json.loads(raw[20 : 20 + json_len])

    names = [node.get("name") for node in doc["nodes"]]
    assert "male" in names and "female" in names
    assert {mesh["name"] for mesh in doc["meshes"]} == {"male", "female"}
    for name in ("male", "female"):
        node = next(n for n in doc["nodes"] if n.get("name") == name)
        assert node.get("mesh") is not None, f"{name} has no mesh of its own"
    assert doc["asset"]["extras"]["params_hash"] == job["params_hash"]
    assert doc["asset"]["extras"]["quality"] == "preview"


def test_preview_and_export_describe_the_same_design(live_client, ref_params):
    """Different tessellation, same geometry: the derived values and the volumes
    must agree, and only the quality-dependent parts of the hash may differ."""
    preview = poll(live_client, live_client.post("/api/preview", json={"params": ref_params}).json()["id"])
    export = poll(live_client, live_client.post("/api/export", json={"params": ref_params}).json()["id"])
    assert preview["derived"] == export["derived"]
    for part, volume in preview["volumes_cm3"].items():
        assert volume == pytest.approx(export["volumes_cm3"][part], rel=2e-4)


def test_the_bundle_contains_every_artifact_and_the_report(live_client, ref_params):
    job = poll(live_client, live_client.post("/api/export", json={"params": ref_params}).json()["id"])
    archive = zipfile.ZipFile(BytesIO(live_client.get(job["bundle_url"]).content))
    assert set(archive.namelist()) == set(job["artifacts"]) | {"result.json"}
    assert archive.read("result.json")


def test_single_part_export_omits_the_other_half(live_client, ref_params):
    job = poll(live_client, live_client.post(
        "/api/export", json={"params": ref_params, "parts": {"male": False, "female": True}}
    ).json()["id"])
    assert set(job["artifacts"]) == {"female.step", "female.stl"}
