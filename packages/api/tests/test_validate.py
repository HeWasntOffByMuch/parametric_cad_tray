"""Validation: typed, cheap, and provably free of geometry."""

import copy

import pytest


def test_reference_parameters_are_valid(client, ref_params):
    body = client.post("/api/validate", json={"params": ref_params}).json()
    assert body["valid"] is True
    assert body["diagnostics"] == []
    assert body["derived"]["forming_gap"] == 3.0
    assert body["params_hash"]


def test_outer_datum_returns_e_datum_001(client, ref_params):
    params = copy.deepcopy(ref_params)
    params["tray"]["datum"] = "outer"
    body = client.post("/api/validate", json={"params": params}).json()
    assert body["valid"] is False
    codes = [d["code"] for d in body["diagnostics"]]
    assert codes == ["E-DATUM-001"]
    assert "never silently reinterpreted" in body["diagnostics"][0]["message"]


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda p: p["tray"].update(depth=40.0), "E-MOLD-040"),
        (lambda p: p["mold"].update(flange_width=4.0), "E-MOLD-041"),
        (lambda p: p["fit"].update(gap_override=None) or p["leather"].update(thickness=0.4)
         or p["fit"].update(clearance=-0.5), "E-GAP-020"),
    ],
)
def test_invalid_values_return_typed_diagnostics(client, ref_params, mutate, code):
    params = copy.deepcopy(ref_params)
    mutate(params)
    body = client.post("/api/validate", json={"params": params}).json()
    assert body["valid"] is False
    assert code in [d["code"] for d in body["diagnostics"]]
    for diagnostic in body["diagnostics"]:
        assert set(diagnostic) == {"code", "severity", "field", "message"}


def test_schema_violations_are_rejected_before_any_diagnostic(client, ref_params):
    params = copy.deepcopy(ref_params)
    params["tray"]["depth"] = -5.0
    assert client.post("/api/validate", json={"params": params}).status_code == 422


def test_validation_never_builds_geometry(client, ref_params, monkeypatch):
    """The endpoint may build a 2D profile; it must not build a solid, loft or
    boolean.  Poison the three and see that validation still answers."""
    import traymold.mold as mold

    def poison(*args, **kwargs):
        raise AssertionError("validation invoked the geometry kernel")

    monkeypatch.setattr(mold, "_loft", poison)
    monkeypatch.setattr(mold, "build", poison)
    monkeypatch.setattr(mold, "build_male_from_profile", poison)
    monkeypatch.setattr(mold, "build_female_from_profile", poison)

    body = client.post("/api/validate", json={"params": ref_params}).json()
    assert body["valid"] is True


def test_validation_does_not_dispatch_a_worker(client, ref_params):
    import trayapi.worker as worker

    worker.shutdown_pool()
    client.post("/api/validate", json={"params": ref_params})
    assert worker._POOL is None, "validation started a worker pool"


def test_nonzero_draft_is_gated_behind_allow_experimental(client, ref_params):
    import copy

    params = copy.deepcopy(ref_params)
    params["tray"]["draft_angle"] = 3.0

    gated = client.post("/api/validate", json={"params": params}).json()
    assert gated["valid"] is False
    assert [d["code"] for d in gated["diagnostics"]] == ["E-DRAFT-EXPERIMENTAL"]
    assert "cos(draft_angle)" in gated["diagnostics"][0]["message"]

    allowed = client.post(
        "/api/validate", json={"params": params, "allow_experimental": True}
    ).json()
    assert allowed["valid"] is True


def test_quality_and_parts_change_the_hash(client, ref_params):
    base = client.post("/api/validate", json={"params": ref_params}).json()["params_hash"]
    preview = client.post(
        "/api/validate", json={"params": ref_params, "quality": "preview"}
    ).json()["params_hash"]
    male_only = client.post(
        "/api/validate", json={"params": ref_params, "parts": {"male": True, "female": False}}
    ).json()["params_hash"]
    assert len({base, preview, male_only}) == 3


def test_the_design_name_does_not_change_the_hash(client, ref_params):
    import copy

    renamed = copy.deepcopy(ref_params)
    renamed["name"] = "something else entirely"
    a = client.post("/api/validate", json={"params": ref_params}).json()["params_hash"]
    b = client.post("/api/validate", json={"params": renamed}).json()["params_hash"]
    assert a == b
