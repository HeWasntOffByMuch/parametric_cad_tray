"""The 3MF export, as the API exposes it.

It is experimental and it is offered to everyone. There is no deployment switch
and no browser switch: a format nobody can find is a format nobody reports a
problem with, which is the wrong trade for something new.
"""

from traymold.presets import REF_4X7
from trayapi.cache import cache_key


def test_the_format_is_accepted(client, ref_params):
    """Not refused, and not gated behind anything. A worker-less client cannot
    finish the build, so this asserts only that validation lets it through."""
    response = client.post("/api/export", json={"params": ref_params, "formats": ["3mf"]})
    assert response.status_code != 422, response.text


def test_an_unknown_format_is_still_refused(client, ref_params):
    response = client.post("/api/export", json={"params": ref_params, "formats": ["obj"]})
    assert response.status_code == 422


def test_the_print_settings_are_offered_in_the_form(client):
    hints = client.get("/api/schema").json()["ui_hints"]
    group = next(g for g in hints["groups"] if g["id"] == "print")
    assert "print.profile" in group["fields"]
    assert "experimental" in group["description"].lower()
    assert "print.profile" not in hints["hidden"]


def test_the_print_plan_is_in_the_key_of_a_file_that_carries_it_and_no_other():
    """Choosing an infill option must not rebuild geometry that cannot show it,
    and must still give a 3MF of its own."""
    lean = REF_4X7.model_copy(update={
        "print": REF_4X7.print.model_copy(update={"profile": "lean"})})
    assert cache_key(REF_4X7, ("step", "stl")) == cache_key(lean, ("step", "stl"))
    assert cache_key(REF_4X7, ("glb",)) == cache_key(lean, ("glb",))
    assert cache_key(REF_4X7, ("3mf",)) != cache_key(lean, ("3mf",))
