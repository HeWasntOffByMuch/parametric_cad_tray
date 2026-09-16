"""Feature flags: what a deployment offers, and what it refuses.

A flag is a product decision about what is *exposed*, so it lives in `policy`
beside the other ones.  Two properties matter and both are asserted here: the
browser is told what is available so it can hide a control, and the server
refuses the format anyway - because this API is public and a caller that is not
the form can ask for whatever it likes.
"""

from dataclasses import replace

import pytest

from trayapi.policy import format_diagnostics
from trayapi.settings import SETTINGS


@pytest.fixture
def with_3mf(monkeypatch):
    """Turn the flag on for one test.

    `SETTINGS` is frozen at import, and `policy.features` reads it through the
    module at call time, so this is the seam - no environment variable, no
    re-import of the app.
    """
    import trayapi.settings

    monkeypatch.setattr(trayapi.settings, "SETTINGS", replace(SETTINGS, enable_3mf=True))


def export(client, params, **kw):
    return client.post("/api/export", json={"params": params, **kw})


def test_the_default_deployment_does_not_offer_3mf(client):
    assert client.get("/api/schema").json()["features"] == {"3mf": False}


def test_the_flag_turns_it_on(client, with_3mf):
    assert client.get("/api/schema").json()["features"] == {"3mf": True}


def test_the_gated_group_is_hidden_rather_than_removed_from_the_schema(client):
    """There is exactly one authoritative schema, so a gated field stays in it
    and the hint layer hides the control - the same thing `hidden` already does
    for `schema_version` and `name`."""
    body = client.get("/api/schema").json()
    assert "print" in body["json_schema"]["properties"]
    assert "print" in body["defaults"]
    assert "print" not in [group["id"] for group in body["ui_hints"]["groups"]]
    assert "print.profile" in body["ui_hints"]["hidden"]


def test_the_group_appears_once_the_flag_is_on(client, with_3mf):
    hints = client.get("/api/schema").json()["ui_hints"]
    assert "print" in [group["id"] for group in hints["groups"]]
    assert "print.profile" not in hints["hidden"]


def test_a_3mf_export_is_refused_while_the_flag_is_off(client, ref_params):
    response = export(client, ref_params, formats=["3mf"])
    assert response.status_code == 422
    diagnostics = response.json()["detail"]["error"]["diagnostics"]
    codes = [d["code"] for d in diagnostics]
    assert "E-FORMAT-3MF-DISABLED" in codes
    assert "TRAYAPI_ENABLE_3MF" in next(
        d["message"] for d in diagnostics if d["code"] == "E-FORMAT-3MF-DISABLED")


def test_the_refusal_names_the_format_field_not_a_parameter(client, ref_params):
    response = export(client, ref_params, formats=["step", "3mf"])
    diagnostic = next(d for d in response.json()["detail"]["error"]["diagnostics"]
                      if d["code"] == "E-FORMAT-3MF-DISABLED")
    assert diagnostic["field"] == "formats"
    assert diagnostic["severity"] == "error"


def test_ungated_formats_are_never_refused(client, ref_params):
    assert format_diagnostics(["glb", "step", "stl"], {"3mf": False}) == []
    assert format_diagnostics(None, {"3mf": False}) == []


def test_the_print_plan_is_not_in_the_key_of_a_file_that_does_not_carry_it():
    """Choosing an infill option must not rebuild geometry that cannot show it,
    and must still give a 3MF of its own."""
    from traymold.presets import REF_4X7
    from trayapi.cache import cache_key

    lean = REF_4X7.model_copy(update={
        "print": REF_4X7.print.model_copy(update={"profile": "lean"})})
    assert cache_key(REF_4X7, ("step", "stl")) == cache_key(lean, ("step", "stl"))
    assert cache_key(REF_4X7, ("glb",)) == cache_key(lean, ("glb",))
    assert cache_key(REF_4X7, ("3mf",)) != cache_key(lean, ("3mf",))
