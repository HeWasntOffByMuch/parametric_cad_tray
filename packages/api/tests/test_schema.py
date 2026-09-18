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


def test_every_variant_of_every_union_is_reachable_from_the_form():
    """A variant must be constructible from its discriminator alone.

    The form's variant switcher emits the discriminator plus whatever the schema
    gives a default. A required field with no default is therefore emitted as
    undefined, dropped by JSON.stringify, and rejected as missing before the
    user has touched anything - so the variant simply cannot be chosen.

    This happened to the eight profile families once and to the three edge
    treatments again afterwards, because the first fix checked one union rather
    than the rule. This checks the rule: walk the served schema, find every
    discriminated union, and require each variant to validate from its tag.
    """
    from traymold.api import json_schema
    from traymold.params import Params

    schema = json_schema()
    definitions = schema.get("$defs", {})

    def deref(node):
        while "$ref" in node:
            node = definitions[node["$ref"].rsplit("/", 1)[-1]]
        return node

    def unions(node, path="params"):
        """Every (path, discriminator, [variant names]) in the document."""
        node = deref(node)
        found = []
        one_of = node.get("oneOf")
        discriminator = node.get("discriminator")
        if one_of and discriminator:
            found.append((path, discriminator["propertyName"],
                          [deref(o) for o in one_of]))
            for option in one_of:
                found += unions(deref(option), f"{path}.<{discriminator['propertyName']}>")
        for name, child in (node.get("properties") or {}).items():
            found += unions(child, f"{path}.{name}")
        return found

    everything = unions(schema)
    assert everything, "no discriminated unions found - has the schema changed shape?"

    missing = []
    for path, discriminator, variants in everything:
        for variant in variants:
            required = set(variant.get("required", []))
            properties = variant.get("properties", {})
            tag = properties.get(discriminator, {}).get("const")
            for name in sorted(required - {discriminator}):
                if "default" not in properties.get(name, {}):
                    missing.append(f"{path} -> {tag}.{name}")

    assert not missing, (
        "these variant fields are required with no default, so the form cannot "
        "select the variant at all:\n  " + "\n  ".join(missing)
    )


def test_switching_a_variant_by_tag_alone_validates():
    """The same rule, end to end: the tag is all the form is guaranteed to send."""
    import copy

    from traymold.params import Params
    from traymold.presets import REF_4X7_STEP

    document = REF_4X7_STEP.model_dump(mode="json")
    treatments = ("male_root_blend", "male_floor_blend",
                  "female_entry_blend_top", "female_entry_blend_bottom")
    kinds = ("none", "circular_fillet", "g2_quintic_blend", "chamfer")
    for field in treatments:
        for kind in kinds:
            body = copy.deepcopy(document)
            body["mold"][field] = {"kind": kind}
            Params.model_validate(body)   # raises if a field has no default
