"""Server-sent events for job state."""

import json

import pytest
from conftest import poll

from test_failures import TESTS_DIR, fault_pool_factory


def parse_sse(text: str) -> list[dict]:
    """Return the payloads of every `data:` frame, ignoring keep-alive comments."""
    events = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line.startswith("data:")]
        if lines:
            events.append(json.loads(lines[0][5:].strip()))
    return events


def event_names(text: str) -> list[str]:
    return [line[7:].strip() for line in text.splitlines() if line.startswith("event:")]


@pytest.mark.slow
def test_sse_streams_states_through_to_complete(live_client, ref_params):
    job_id = live_client.post("/api/preview", json={"params": ref_params}).json()["id"]
    with live_client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        body = "".join(stream.iter_text())

    states = [e["state"] for e in parse_sse(body)]
    assert states[-1] == "complete", states
    assert "running" in states or states[0] == "running"
    assert event_names(body)[-1] == "complete"

    final = parse_sse(body)[-1]
    assert set(final["artifacts"]) == {"male.glb", "female.glb"}
    for artifact in final["artifacts"].values():
        assert artifact["url"].startswith("/api/artifacts/")
    assert final["status"] == "done"
    assert final["progress"] == 1.0


@pytest.mark.slow
def test_sse_reports_real_monotonic_progress(live_client, ref_params):
    """The bar is a promise about time, so this asserts it is kept.

    Progress must come from stages the build actually finished - never
    interpolated, never invented, never backwards - and the last frame must be
    exactly 1.0 rather than something that rounds to it.
    """
    job_id = live_client.post("/api/preview", json={"params": ref_params}).json()["id"]
    with live_client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        body = "".join(stream.iter_text())

    events = parse_sse(body)
    fractions = [e["progress"] for e in events if e.get("progress") is not None]
    assert len(fractions) >= 3, f"expected several stages, got {fractions}"
    assert fractions == sorted(fractions), f"progress went backwards: {fractions}"
    assert all(0.0 <= f <= 1.0 for f in fractions), fractions
    assert fractions[-1] == 1.0

    # A preview builds its two halves at the same time, so the stages of one
    # interleave with the stages of the other and there is no single order to
    # compare against. What must hold is that every stage reported is one of the
    # stages one of the halves was going to run, and that both halves are heard
    # from - a bar driven by only one of two concurrent builds would stall.
    from traymold.api import apply_options
    from traymold.params import Params
    from traymold.progress import plan

    params = Params.model_validate(ref_params)
    halves = {}
    for part in ("male", "female"):
        effective = apply_options(params, "preview", {"male": part == "male",
                                                      "female": part == "female"})
        halves[part] = set(plan(effective))

    reported = {e["stage"] for e in events if e.get("stage")}
    assert reported, "no stage names were reported"
    assert reported <= (halves["male"] | halves["female"]), (reported, halves)

    male_only = halves["male"] - halves["female"]
    female_only = halves["female"] - halves["male"]
    assert reported & male_only, f"nothing was heard from the plug: {reported}"
    assert reported & female_only, f"nothing was heard from the cavity: {reported}"


@pytest.mark.slow
def test_sse_on_an_already_finished_job_emits_once_and_closes(live_client, ref_params):
    job_id = live_client.post("/api/preview", json={"params": ref_params}).json()["id"]
    poll(live_client, job_id)
    with live_client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        body = "".join(stream.iter_text())
    events = parse_sse(body)
    assert len(events) == 1 and events[0]["state"] == "complete"


def test_sse_reports_failure_with_a_structured_error(cache, ref_params):
    from fastapi.testclient import TestClient
    from trayapi.jobs import JobManager
    from trayapi.main import create_app

    pool = fault_pool_factory()
    try:
        jobs = JobManager(cache=cache, pool=pool, timeout=20.0)
        with TestClient(create_app(cache=cache, warm=False, jobs=jobs, sweep=False)) as c:
            job_id = c.post("/api/preview",
                            json={"params": dict(ref_params, name="fault-raise")}).json()["id"]
            with c.stream("GET", f"/api/jobs/{job_id}/events") as stream:
                body = "".join(stream.iter_text())
            final = parse_sse(body)[-1]
            assert final["state"] == "failed"
            assert final["error"]["kind"] == "geometry_build_error"
            assert "Traceback" not in json.dumps(final)
    finally:
        pool.shutdown()


def test_sse_reports_cancellation(cache, ref_params):
    import threading

    from fastapi.testclient import TestClient
    from trayapi.jobs import JobManager
    from trayapi.main import create_app

    pool = fault_pool_factory()
    try:
        jobs = JobManager(cache=cache, pool=pool, timeout=60.0)
        with TestClient(create_app(cache=cache, warm=False, jobs=jobs, sweep=False)) as c:
            job_id = c.post("/api/preview",
                            json={"params": dict(ref_params, name="fault-hang")}).json()["id"]
            threading.Timer(0.4, lambda: c.post(f"/api/jobs/{job_id}/cancel")).start()
            with c.stream("GET", f"/api/jobs/{job_id}/events") as stream:
                body = "".join(stream.iter_text())
            final = parse_sse(body)[-1]
            assert final["state"] == "cancelled"
            assert final["error"]["kind"] == "cancelled"
    finally:
        pool.shutdown()


def test_sse_on_an_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope/events").status_code == 404


@pytest.mark.slow
def test_the_polling_endpoint_remains_the_fallback(live_client, ref_params):
    """A dropped SSE connection must be recoverable without resubmitting."""
    job_id = live_client.post("/api/preview", json={"params": ref_params}).json()["id"]
    with live_client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        next(stream.iter_text())  # read one frame, then abandon the stream
    recovered = poll(live_client, job_id)
    assert recovered["state"] == "complete"
    assert recovered["artifacts"]


@pytest.mark.slow
def test_a_lost_job_id_is_recoverable_by_resubmitting_into_the_cache(live_client, ref_params):
    """The documented recovery path after an API restart: the job record is gone,
    but resubmitting hits the artifact cache and answers immediately."""
    poll(live_client, live_client.post("/api/preview", json={"params": ref_params}).json()["id"])
    live_client.jobs._jobs.clear()  # as if the process had restarted

    assert live_client.get("/api/jobs/anything").status_code == 404
    again = live_client.post("/api/preview", json={"params": ref_params})
    assert again.status_code == 200
    assert again.json()["cached"] is True
