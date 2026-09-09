"""Job lifecycle over real geometry workers."""

import copy

import pytest
from conftest import poll

pytestmark = pytest.mark.slow


def test_preview_job_completes_and_produces_a_glb(live_client, ref_params):
    submitted = live_client.post("/api/preview", json={"params": ref_params})
    assert submitted.status_code == 202
    assert submitted.json()["state"] in ("queued", "running")

    job = poll(live_client, submitted.json()["id"])
    assert job["state"] == "complete"
    assert job["error"] is None
    assert list(job["artifacts"]) == ["preview.glb"]
    assert job["timings"]["build_s"] > 0
    assert job["volumes_cm3"]["male_cm3"] == pytest.approx(994.2, abs=0.5)

    glb = live_client.get(job["artifacts"]["preview.glb"]["url"])
    assert glb.status_code == 200
    assert glb.headers["content-type"] == "model/gltf-binary"
    assert glb.content[:4] == b"glTF"


def test_export_job_completes_with_step_and_stl_for_both_parts(live_client, ref_params):
    job = poll(live_client, live_client.post("/api/export", json={"params": ref_params}).json()["id"])
    assert job["state"] == "complete"
    assert set(job["artifacts"]) == {"male.step", "female.step", "male.stl", "female.stl"}
    for artifact in job["artifacts"].values():
        assert artifact["bytes"] > 1000
        assert live_client.get(artifact["url"]).status_code == 200
    bundle = live_client.get(job["bundle_url"])
    assert bundle.status_code == 200
    assert bundle.content[:2] == b"PK"


def test_export_can_select_one_part(live_client, ref_params):
    job = poll(live_client, live_client.post(
        "/api/export", json={"params": ref_params, "parts": {"male": True, "female": False}}
    ).json()["id"])
    assert job["state"] == "complete"
    assert set(job["artifacts"]) == {"male.step", "male.stl"}
    assert set(job["volumes_cm3"]) == {"male_cm3"}


def test_an_invalid_request_never_enqueues_a_build(live_client, ref_params):
    params = copy.deepcopy(ref_params)
    params["tray"]["datum"] = "outer"
    before = len(live_client.jobs._jobs)

    response = live_client.post("/api/preview", json={"params": params})
    assert response.status_code == 422
    error = response.json()["detail"]["error"]
    assert error["kind"] == "validation_error"
    assert [d["code"] for d in error["diagnostics"]] == ["E-DATUM-001"]
    assert len(live_client.jobs._jobs) == before, "an invalid request created a job"


def test_job_lookup_and_unknown_job(live_client, ref_params):
    job_id = live_client.post("/api/preview", json={"params": ref_params}).json()["id"]
    assert live_client.get(f"/api/jobs/{job_id}").json()["id"] == job_id
    assert live_client.get("/api/jobs/does-not-exist").status_code == 404
    poll(live_client, job_id)


def test_queued_cancellation_prevents_the_build(live_client, ref_params):
    from trayapi.jobs import JobManager

    jobs: JobManager = live_client.jobs
    submitted = live_client.post("/api/preview", json={"params": ref_params}).json()
    job = jobs.get(submitted["id"])
    job.cancel.set()  # as if cancelled the instant it was queued
    cancelled = poll(live_client, submitted["id"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["error"]["kind"] == "cancelled"
