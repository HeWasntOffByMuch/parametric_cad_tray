"""Content-addressed caching and concurrent deduplication."""

import copy
import threading

import pytest
from conftest import poll

from trayapi.cache import cache_key
from traymold.api import apply_options
from traymold.params import Params


def key_for(params: dict, quality=None, parts=None, formats=("glb",)) -> str:
    effective = apply_options(Params.model_validate(params), quality, parts)
    return cache_key(effective, formats)


# --------------------------------------------------------------------------
# key definition
# --------------------------------------------------------------------------
def test_identical_requests_produce_identical_keys(ref_params):
    assert key_for(ref_params) == key_for(copy.deepcopy(ref_params))


def test_the_design_name_is_not_part_of_the_key(ref_params):
    renamed = dict(ref_params, name="a different label")
    assert key_for(ref_params) == key_for(renamed)


def test_a_parameter_change_misses(ref_params):
    changed = copy.deepcopy(ref_params)
    changed["leather"]["thickness"] = 3.5
    assert key_for(ref_params) != key_for(changed)


def test_a_quality_change_misses(ref_params):
    assert key_for(ref_params, quality="preview") != key_for(ref_params, quality="export")


def test_quality_as_an_argument_and_quality_in_the_document_agree(ref_params):
    baked = copy.deepcopy(ref_params)
    baked["quality"]["mode"] = "preview"
    assert key_for(baked) == key_for(ref_params, quality="preview")


def test_a_parts_change_misses(ref_params):
    both = key_for(ref_params, parts={"male": True, "female": True})
    male = key_for(ref_params, parts={"male": True, "female": False})
    assert both != male


def test_a_format_change_misses(ref_params):
    assert key_for(ref_params, formats=("glb",)) != key_for(ref_params, formats=("step", "stl"))
    assert key_for(ref_params, formats=("step", "stl")) == key_for(ref_params, formats=("stl", "step"))


def test_a_model_version_bump_invalidates_every_key(ref_params, monkeypatch):
    import traymold.version as version

    before = key_for(ref_params)
    monkeypatch.setattr(version, "MODEL_VERSION", version.MODEL_VERSION + "+test")
    assert key_for(ref_params) != before


def test_a_kernel_version_change_invalidates_every_key(ref_params, monkeypatch):
    import traymold.version as version

    before = key_for(ref_params)
    monkeypatch.setattr(version, "kernel_versions", lambda: {"cadquery": "0.0.0", "OCP": "0.0.0"})
    assert key_for(ref_params) != before


# --------------------------------------------------------------------------
# behaviour
# --------------------------------------------------------------------------
@pytest.mark.slow
def test_a_second_identical_request_does_not_rebuild(live_client, ref_params):
    first = poll(live_client, live_client.post("/api/preview", json={"params": ref_params}).json()["id"])
    assert first["cached"] is False

    response = live_client.post("/api/preview", json={"params": ref_params})
    assert response.status_code == 200, "a cache hit should answer immediately, not 202"
    second = response.json()
    assert second["state"] == "complete"
    assert second["cached"] is True
    assert second["cache_key"] == first["cache_key"]
    assert second["artifacts"] == first["artifacts"]
    assert second["id"] != first["id"], "a cache hit is still its own job record"


@pytest.mark.slow
def test_a_changed_parameter_rebuilds(live_client, ref_params):
    poll(live_client, live_client.post("/api/preview", json={"params": ref_params}).json()["id"])
    changed = copy.deepcopy(ref_params)
    changed["leather"]["thickness"] = 2.5
    response = live_client.post("/api/preview", json={"params": changed})
    assert response.status_code == 202
    assert response.json()["cached"] is False
    assert poll(live_client, response.json()["id"])["state"] == "complete"


@pytest.mark.slow
def test_concurrent_identical_requests_deduplicate_to_one_build(cache, ref_params):
    """Two clients asking for the same geometry must not start two OCC builds."""
    from fastapi.testclient import TestClient
    from trayapi.jobs import JobManager
    from trayapi.main import create_app
    from trayapi.worker import WorkerPool

    class CountingPool(WorkerPool):
        builds = 0

        def run(self, payload, **kwargs):
            type(self).builds += 1
            return super().run(payload, **kwargs)

    pool = CountingPool(size=2)
    try:
        jobs = JobManager(cache=cache, pool=pool)
        # four identical requests attach to one build, so none of them is a
        # second build and none consumes an extra concurrency slot
        with TestClient(create_app(cache=cache, warm=False, jobs=jobs)) as client:
            results: list[dict] = []
            barrier = threading.Barrier(4)

            def submit():
                barrier.wait()
                results.append(client.post("/api/preview", json={"params": ref_params}).json())

            threads = [threading.Thread(target=submit) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=120)

            assert all("id" in r for r in results), f"a request was refused: {results}"
            assert len({r["id"] for r in results}) == 1, "requests did not deduplicate to one job"
            assert poll(client, results[0]["id"])["state"] == "complete"
            # One job, and one build *per half* - a preview is two builds by
            # design. Four requests still cost exactly what one costs: what must
            # never happen is eight.
            assert CountingPool.builds == 2, \
                f"{CountingPool.builds} builds ran, expected 2 (one per half)"
    finally:
        pool.shutdown()
