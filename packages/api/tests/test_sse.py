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
    assert final["artifacts"]["preview.glb"]["url"].startswith("/api/artifacts/")
    assert final["status"] == "done"
    assert final["progress"] is None, "progress must not be invented"


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
