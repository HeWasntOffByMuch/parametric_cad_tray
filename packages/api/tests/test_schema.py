"""The schema endpoint, and the claim that there is exactly one schema."""

from traymold.params import Params
from traymold.version import MODEL_VERSION, SCHEMA_VERSION
from trayapi.version import API_VERSION


def test_schema_is_served(client):
    response = client.get("/api/schema")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"schema_version", "model_version", "json_schema", "defaults", "ui_hints"}


def test_schema_is_generated_from_the_core_models_not_restated(client):
    """One authoritative schema.  The API must return exactly what Pydantic
    generates from `traymold.params.Params` - not a hand-maintained copy."""
    served = client.get("/api/schema").json()["json_schema"]
    assert served == Params.model_json_schema()


def test_defaults_round_trip_through_the_core_model(client):
    defaults = client.get("/api/schema").json()["defaults"]
    assert Params.model_validate(defaults) == Params()


def test_versions_are_reported(client):
    body = client.get("/api/schema").json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["model_version"] == MODEL_VERSION

    version = client.get("/api/version").json()
    assert version["api_version"] == API_VERSION
    assert version["schema_version"] == SCHEMA_VERSION
    assert version["model_version"] == MODEL_VERSION
    assert version["cadquery"] and version["cadquery"] != "unknown"
    assert version["OCP"] and version["OCP"] != "unknown"


def test_ui_hints_do_not_leak_into_the_schema(client):
    body = client.get("/api/schema").json()
    assert "ui_hints" not in body["json_schema"]
    assert body["ui_hints"]["fields"]["tray.draft_angle"]["experimental"] is True


def test_presets_include_both_reference_revisions(client):
    presets = client.get("/api/presets").json()
    names = {p["name"] for p in presets}
    assert {"ref-4x7", "ref-4x7-step"} <= names
    by_name = {p["name"]: p for p in presets}
    assert "STL" in by_name["ref-4x7"]["title"]
    assert "STEP" in by_name["ref-4x7-step"]["title"]
    # the STEP revision has no manufacturing features; the STL revision does
    assert by_name["ref-4x7-step"]["params"]["features"]["clamp_holes"]["enabled"] is False
    assert by_name["ref-4x7"]["params"]["features"]["clamp_holes"]["enabled"] is True
    for preset in presets:
        Params.model_validate(preset["params"])
