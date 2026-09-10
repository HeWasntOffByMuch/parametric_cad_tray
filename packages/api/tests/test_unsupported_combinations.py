"""Two plan curves the kernel cannot take one particular edge treatment on.

Both were found by building them, both produce a *plausible* result rather than
an obvious one - an empty solid in one case, a stray face across the cavity in
the other - and both are refused before a worker is asked to spend seconds on a
build that cannot work.

The point of these tests is that the refusal stays honest in both directions: it
must fire for the combination and it must not fire for the shape.
"""

import pytest

from trayapi.policy import UNSUPPORTED_PROFILES, policy_diagnostics


def profile(kind):
    from traymold.params import (EllipseProfile, G2QuinticObroundProfile,
                                 SuperellipseProfile)
    return {
        "ellipse": EllipseProfile(length=175.0, width=105.0),
        "superellipse": SuperellipseProfile(length=175.0, width=105.0),
        "g2_quintic_obround": G2QuinticObroundProfile(length=175.0, width=105.0),
    }[kind]


def params_with(kind, **mold):
    from traymold.presets import REF_4X7_STEP

    p = REF_4X7_STEP
    p = p.model_copy(update={"tray": p.tray.model_copy(update={"profile": profile(kind)})})
    if mold:
        p = p.model_copy(update={"mold": p.mold.model_copy(update=mold)})
    return p


def codes(params, allow_experimental=False):
    return {d["code"] for d in policy_diagnostics(params, allow_experimental)}


def test_a_shipped_shape_is_not_refused():
    assert codes(params_with("g2_quintic_obround")) == set()


def test_an_ellipse_with_a_root_blend_is_refused_before_the_build():
    found = policy_diagnostics(params_with("ellipse"), False)
    assert [d["code"] for d in found] == ["E-PROFILE-ROOT-BLEND"]
    # The message has to name the one setting to change, because that is the
    # difference between "it doesn't work" and "turn this off and it does".
    assert "male_root_blend" in found[0]["message"]
    assert found[0]["field"] == "mold.male_root_blend"


def test_a_superellipse_is_refused_outright_rather_than_in_combination():
    """It fails in two places, and one of them only at export.

    Turning the entry blend off gets a preview, and then export fails on the
    floor blend's loft - so offering the shape with a workaround would be
    offering a preview of something that cannot be exported.
    """
    found = policy_diagnostics(params_with("superellipse"), False)
    assert [d["code"] for d in found] == ["E-PROFILE-SUPERELLIPSE"]
    assert "entry blend" in found[0]["message"]
    assert "floor blend" in found[0]["message"]


def test_turning_the_entry_blend_off_does_not_unlock_a_superellipse():
    from traymold.params import NoTreatment

    params = params_with("superellipse",
                         female_entry_blend_top=NoTreatment(),
                         female_entry_blend_bottom=NoTreatment())
    assert codes(params) == {"E-PROFILE-SUPERELLIPSE"}, \
        "the export-side floor blend still fails; the shape must stay refused"


def test_the_picker_is_told_which_shapes_it_may_not_offer():
    """The hint the frontend disables an option with, and the policy that
    refuses it, must name the same shapes - otherwise one of them is lying."""
    from trayapi.ui_hints import UI_HINTS

    disabled = set(UI_HINTS["fields"]["tray.profile"]["disabled_values"])
    assert disabled == set(UNSUPPORTED_PROFILES), (disabled, set(UNSUPPORTED_PROFILES))


def test_an_ellipse_is_fine_once_the_root_blend_is_off():
    """Verified by building it: preview and export, both halves."""
    from traymold.params import NoTreatment

    params = params_with("ellipse", male_root_blend=NoTreatment())
    assert codes(params) == set(), "the shape was refused, not the combination"


def test_only_the_half_that_fails_is_refused():
    """A cavity-only build of an ellipse has no plug to blend the root of."""
    params = params_with("ellipse")
    female_only = params.model_copy(update={"mold": params.mold.model_copy(update={
        "parts": params.mold.parts.model_copy(update={"male": False, "female": True})})})
    assert codes(female_only) == set()

    male_only = params.model_copy(update={"mold": params.mold.model_copy(update={
        "parts": params.mold.parts.model_copy(update={"male": True, "female": False})})})
    assert codes(male_only) == {"E-PROFILE-ROOT-BLEND"}


def test_the_api_refuses_the_combination_without_starting_a_build(client, ref_params):
    """422 before the job, not a kernel error minutes later."""
    import copy

    body = copy.deepcopy(ref_params)
    body["tray"]["profile"] = {"kind": "ellipse", "length": 175.0, "width": 105.0}
    response = client.post("/api/preview", json={"params": body})
    assert response.status_code == 422
    detail = response.json()["detail"]["error"]
    assert any(d["code"] == "E-PROFILE-ROOT-BLEND" for d in detail["diagnostics"]), detail


def test_a_build_error_reaches_the_user_with_its_remedy():
    """classify() used to replace every BuildError with one generic sentence.

    The messages exist precisely to say which setting to change; throwing them
    away is why "ellipse doesn't build" was all anyone could see.
    """
    from traymold.mold import BuildError
    from trayapi.errors import GEOMETRY_BUILD_ERROR, classify

    kind, message, _ = classify(BuildError("male root blend produced an empty solid. "
                                           "Set mold.male_root_blend to none"))
    assert kind == GEOMETRY_BUILD_ERROR
    assert "male_root_blend" in message, "the remedy was thrown away"
