import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))
sys.path.insert(0, str(ROOT / "packages" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def analytics_off(monkeypatch):
    """Analytics is off for every test that does not ask for it.

    Without this the suite inherits whatever `TRAYMOLD_ANALYTICS_DB` the shell
    has - which for a developer running `make dev` is a real database - and a
    test run would quietly write hundreds of rows into it. Tests that exercise
    analytics set the variable themselves; monkeypatch lets the inner setenv win.
    """
    monkeypatch.setenv("TRAYMOLD_ANALYTICS_DB", "")


@pytest.fixture
def cache_dir():
    path = Path(tempfile.mkdtemp(prefix="trayapi-test-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def cache(cache_dir):
    from trayapi.cache import ArtifactCache

    return ArtifactCache(cache_dir)


@pytest.fixture
def client(cache):
    """An app with no workers: metadata and validation only."""
    from fastapi.testclient import TestClient
    from trayapi.main import create_app

    with TestClient(create_app(cache=cache, warm=False)) as c:
        yield c


@pytest.fixture(scope="session")
def live_pool():
    """One real worker pool for the whole session; spawning costs ~3 s each."""
    from trayapi.worker import WorkerPool

    pool = WorkerPool(size=2)
    yield pool
    pool.shutdown()


@pytest.fixture
def live_client(cache, live_pool):
    """An app wired to real geometry workers."""
    from fastapi.testclient import TestClient
    from trayapi.jobs import JobManager
    from trayapi.main import create_app

    jobs = JobManager(cache=cache, pool=live_pool)
    with TestClient(create_app(cache=cache, warm=False, jobs=jobs)) as c:
        c.jobs = jobs
        yield c


@pytest.fixture
def ref_params():
    from traymold.presets import REF_4X7_STEP

    return REF_4X7_STEP.model_dump(mode="json")


def poll(client, job_id, timeout=240.0):
    import time

    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["state"] in ("complete", "failed", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")
