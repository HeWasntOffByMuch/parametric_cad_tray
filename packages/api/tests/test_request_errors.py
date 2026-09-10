"""A body the model rejects must still come back as diagnostics.

The bug this suite exists for: one number outside its bounds took down
`POST /api/validate` in exactly the way it took down `POST /api/preview`, both
with FastAPI's own 422 - a list of pydantic dicts under `detail`. The browser
knows one error envelope and could render none of it, so it showed "request
failed (422)". Worse, validate is the endpoint that explains what is wrong, so
losing it left the form with no diagnostics at all: nothing on the field,
nothing blocking the build, and a stored document that did it again on reload.

Every test here is about a *client's* ability to act: the right envelope, the
field path the form uses, and a sentence with the bound in it.
"""

import copy

import pytest

from trayapi.request_errors import field_path, variant_tags
from traymold.api import json_schema

TAGS = variant_tags(json_schema())


def error(response) -> dict:
    assert response.status_code == 422, response.text
    return response.json()["detail"]["error"]


# --------------------------------------------------------------------------
# the path a diagnostic names
# --------------------------------------------------------------------------
def test_no_variant_tag_is_also_a_field_name():
    """What lets tags be dropped by name rather than by walking the model.

    A discriminated union puts its tag in pydantic's path
    (`tray.profile.g2_quintic_obround.length`); the form shows one variant at a
    time and addresses the same input as `tray.profile.length`. Dropping the tag
    is only safe while no field is called one - so this asserts it, and fails
    the day someone adds a field that is.
    """
    names: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            names.update(node.get("properties") or {})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json_schema())
    assert names, "walked the schema and found no properties at all"
    assert TAGS & names == set()


@pytest.mark.parametrize("loc,expected", [
    (["body", "params", "tray", "depth"], "tray.depth"),
    (["params", "tray", "depth"], "tray.depth"),
    # the variant tag pydantic adds, which the form's path does not have
    (["body", "params", "tray", "profile", "g2_quintic_obround", "length"], "tray.profile.length"),
    (["body", "params", "mold", "male_root_blend", "circular_fillet", "radius"],
     "mold.male_root_blend.radius"),
    (["body", "params", "features", "clamp_holes", "diameter"], "features.clamp_holes.diameter"),
])
def test_field_path_matches_what_the_form_calls_that_input(loc, expected):
    assert field_path(loc, TAGS) == expected


# --------------------------------------------------------------------------
# what a client receives
# --------------------------------------------------------------------------
@pytest.mark.parametrize("endpoint", ["/api/validate", "/api/preview", "/api/export"])
def test_every_endpoint_answers_a_bad_body_in_the_one_envelope(client, ref_params, endpoint):
    params = copy.deepcopy(ref_params)
    params["tray"]["profile"]["length"] = 0
    body = error(client.post(endpoint, json={"params": params}))
    assert body["kind"] == "validation_error"
    assert [d["field"] for d in body["diagnostics"]] == ["tray.profile.length"]
    assert body["diagnostics"][0]["code"] == "E-RANGE"


def test_validate_does_not_lose_its_voice_on_a_value_it_cannot_parse(client, ref_params):
    """The one that made the app unusable: the endpoint whose job is to say what
    is wrong used to fail in the same breath as the build."""
    params = copy.deepcopy(ref_params)
    params["tray"]["profile"]["length"] = 0
    diagnostics = error(client.post("/api/validate", json={"params": params}))["diagnostics"]
    assert diagnostics, "validate must always come back with something to show"
    assert all(d["severity"] == "error" for d in diagnostics)


def test_the_message_carries_the_bound_and_the_value(client, ref_params):
    params = copy.deepcopy(ref_params)
    params["mold"]["flange_width"] = 9999
    (diagnostic,) = error(client.post("/api/validate", json={"params": params}))["diagnostics"]
    assert diagnostic["field"] == "mold.flange_width"
    assert diagnostic["message"] == "must be at most 200 (this is 9999)"


def test_the_summary_leads_with_the_field(client, ref_params):
    """`ApiError.message` is what a caller shows when it has nowhere to put a
    per-field diagnostic, so it has to stand on its own."""
    params = copy.deepcopy(ref_params)
    params["tray"]["depth"] = -5
    assert error(client.post("/api/validate", json={"params": params}))["message"] == (
        "tray.depth must be greater than 0 (this is -5)"
    )


def test_several_bad_fields_are_all_reported(client, ref_params):
    params = copy.deepcopy(ref_params)
    params["tray"]["profile"]["length"] = 0
    params["mold"]["flange_width"] = 9999
    diagnostics = error(client.post("/api/validate", json={"params": params}))["diagnostics"]
    assert {d["field"] for d in diagnostics} == {"tray.profile.length", "mold.flange_width"}


@pytest.mark.parametrize("mutate,code,field", [
    (lambda p: p["tray"].update(depth="abc"), "E-INVALID", "tray.depth"),
    (lambda p: p["tray"]["profile"].update(kind="nonsense"), "E-VARIANT", "tray.profile"),
])
def test_other_ways_a_body_can_be_wrong(client, ref_params, mutate, code, field):
    params = copy.deepcopy(ref_params)
    mutate(params)
    (diagnostic,) = error(client.post("/api/validate", json={"params": params}))["diagnostics"]
    assert (diagnostic["code"], diagnostic["field"]) == (code, field)
    assert diagnostic["message"]


def test_a_request_with_no_parameters_at_all(client):
    """Every field of the document has a default, so nothing inside `params` can
    be missing - but `params` itself can be, and that is a client bug worth
    naming rather than a bare 422."""
    (diagnostic,) = error(client.post("/api/validate", json={}))["diagnostics"]
    assert (diagnostic["code"], diagnostic["field"]) == ("E-REQUIRED", "")
    assert diagnostic["message"] == "is required"


def test_a_valid_body_is_untouched(client, ref_params):
    """The handler must not be reachable from a document that parses."""
    response = client.post("/api/validate", json={"params": ref_params})
    assert response.status_code == 200
    assert response.json()["valid"] is True
