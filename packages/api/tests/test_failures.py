"""Failure handling.

Every one of these uses `fault_worker`, a worker program that fails on purpose,
so the crash/hang/exception paths are exercised for real rather than mocked.
"""

import time

import pytest
from conftest import poll

from trayapi.errors import GEOMETRY_BUILD_ERROR, TIMEOUT, WORKER_CRASH
from trayapi.worker import WorkerFailure, WorkerPool


TESTS_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)


def fault_pool_factory(size: int = 1) -> WorkerPool:
    return WorkerPool(size=size, module="fault_worker",
                      extra_paths=(TESTS_DIR,), start_timeout=20.0)


@pytest.fixture(scope="module")
def fault_pool():
    pool = fault_pool_factory()
    yield pool
    pool.shutdown()


def payload(name: str) -> dict:
    return {"params": {"name": name}, "quality": "preview", "parts": {}, "formats": [], "outdir": "/tmp"}


def test_a_worker_exception_becomes_a_structured_failure(fault_pool):
    with pytest.raises(WorkerFailure) as exc:
        fault_pool.run(payload("fault-raise"), timeout=30)
    assert exc.value.kind == GEOMETRY_BUILD_ERROR
    assert "OCC" not in exc.value.message and "Traceback" not in exc.value.message


def test_a_worker_crash_becomes_a_structured_failure_and_the_pool_recovers(fault_pool):
    before = fault_pool.spawned
    with pytest.raises(WorkerFailure) as exc:
        fault_pool.run(payload("fault-crash"), timeout=30)
    assert exc.value.kind == WORKER_CRASH
    assert fault_pool.spawned > before, "the pool did not replace the dead worker"
    # and the pool still works afterwards
    assert fault_pool.run(payload("ok"), timeout=30)["quality"] == "preview"


def test_a_hung_worker_times_out_and_is_terminated(fault_pool):
    before = fault_pool.spawned
    started = time.perf_counter()
    with pytest.raises(WorkerFailure) as exc:
        fault_pool.run(payload("fault-hang"), timeout=1.0)
    assert exc.value.kind == TIMEOUT
    assert time.perf_counter() - started < 5.0
    assert fault_pool.spawned > before
    assert fault_pool.run(payload("ok"), timeout=30)["quality"] == "preview"


def test_a_running_job_can_be_cancelled(fault_pool):
    import threading

    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    with pytest.raises(WorkerFailure) as exc:
        fault_pool.run(payload("fault-hang"), timeout=30, cancel=cancel)
    assert exc.value.kind == "cancelled"


def test_worker_recycling_replaces_a_worker_after_its_task_budget():
    pool = WorkerPool(size=1, module="fault_worker", extra_paths=(TESTS_DIR,),
                      start_timeout=20.0, max_tasks=2)
    try:
        before = pool.spawned
        for _ in range(3):
            pool.run(payload("ok"), timeout=30)
        assert pool.spawned == before + 1, "the worker was not recycled at its task budget"
        assert pool.run(payload("ok"), timeout=30)["quality"] == "preview"
    finally:
        pool.shutdown()


@pytest.mark.parametrize("fault,kind", [("fault-raise", GEOMETRY_BUILD_ERROR),
                                        ("fault-crash", WORKER_CRASH)])
def test_failures_surface_through_the_api_as_structured_job_errors(cache, fault, kind, ref_params):
    from fastapi.testclient import TestClient
    from trayapi.jobs import JobManager
    from trayapi.main import create_app

    pool = fault_pool_factory()
    try:
        jobs = JobManager(cache=cache, pool=pool, timeout=20.0)
        with TestClient(create_app(cache=cache, warm=False, jobs=jobs)) as client:
            params = dict(ref_params, name=fault)
            submitted = client.post("/api/preview", json={"params": params})
            assert submitted.status_code == 202
            job = poll(client, submitted.json()["id"], timeout=60)
            assert job["state"] == "failed"
            assert job["error"]["kind"] == kind
            assert job["artifacts"] == {}
            body = str(job["error"])
            assert "Traceback" not in body and "OCP" not in body
    finally:
        pool.shutdown()


def test_a_failed_build_is_not_cached(cache, ref_params):
    from fastapi.testclient import TestClient
    from trayapi.jobs import JobManager
    from trayapi.main import create_app

    pool = fault_pool_factory()
    try:
        jobs = JobManager(cache=cache, pool=pool, timeout=20.0)
        with TestClient(create_app(cache=cache, warm=False, jobs=jobs)) as client:
            params = dict(ref_params, name="fault-raise")
            first = poll(client, client.post("/api/preview", json={"params": params}).json()["id"], 60)
            assert first["state"] == "failed"
            assert cache.get(first["cache_key"]) is None
            second = client.post("/api/preview", json={"params": params}).json()
            assert second["cached"] is False
            poll(client, second["id"], 60)
    finally:
        pool.shutdown()
