"""Health, rate limiting, cache eviction and request bounds."""

import time
from pathlib import Path

import pytest
from conftest import poll

from trayapi.cache import ArtifactCache
from trayapi.limits import RateLimiter


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------
def test_health_is_ok_and_runs_no_geometry(client, monkeypatch):
    import traymold.mold as mold

    monkeypatch.setattr(mold, "build", lambda *a, **k: pytest.fail("health built geometry"))
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["workers"]["configured"] >= 1
    assert set(body["cache"]) >= {"entries", "bytes", "last_sweep_at", "max_bytes", "max_age_s"}
    assert body["limits"]["requests_per_window"] >= 1


def test_health_reports_the_pool_when_one_exists(client):
    body = client.get("/api/health").json()
    assert body["workers"]["pool_ready"] in (True, False)  # warm=False in this fixture
    assert body["uptime_s"] >= 0


# --------------------------------------------------------------------------
# rate limiting
# --------------------------------------------------------------------------
def test_the_limiter_allows_then_refuses():
    limiter = RateLimiter(requests=3, window_s=60.0, max_concurrent=99)
    assert all(limiter.check_rate("1.2.3.4").allowed for _ in range(3))
    decision = limiter.check_rate("1.2.3.4")
    assert decision.allowed is False
    assert decision.retry_after_s > 0
    assert limiter.check_rate("5.6.7.8").allowed, "limits must be per client"


def test_the_limiter_caps_concurrent_jobs():
    limiter = RateLimiter(requests=999, window_s=60.0, max_concurrent=2)
    for _ in range(2):
        assert limiter.try_acquire("c").allowed
    refused = limiter.try_acquire("c")
    assert refused.allowed is False
    assert "already running" in refused.reason
    limiter.release("c")
    assert limiter.try_acquire("c").allowed


def test_distinct_concurrent_builds_are_capped(cache, ref_params):
    """Three at once is fine; the fourth distinct build is refused."""
    from fastapi.testclient import TestClient
    from trayapi.main import create_app
    from test_failures import fault_pool_factory

    pool = fault_pool_factory()
    try:
        from trayapi.jobs import JobManager

        limiter = RateLimiter(requests=999, window_s=60.0, max_concurrent=3)
        jobs = JobManager(cache=cache, pool=pool, timeout=30.0)
        with TestClient(create_app(cache=cache, warm=False, jobs=jobs, limiter=limiter,
                                   sweep=False)) as c:
            for i in range(3):
                params = dict(ref_params, name="fault-hang",
                              leather=dict(ref_params["leather"], thickness=3.0 + i * 0.1))
                assert c.post("/api/preview", json={"params": params}).status_code == 202
            fourth = dict(ref_params, name="fault-hang",
                          leather=dict(ref_params["leather"], thickness=9.0))
            refused = c.post("/api/preview", json={"params": fourth})
            assert refused.status_code == 429
            assert "already running" in refused.json()["detail"]["error"]["message"]
    finally:
        pool.shutdown()


def test_expensive_endpoints_are_rate_limited(cache, ref_params):
    from fastapi.testclient import TestClient
    from trayapi.main import create_app

    limiter = RateLimiter(requests=2, window_s=60.0, max_concurrent=99)
    app = create_app(cache=cache, warm=False, limiter=limiter, sweep=False)
    with TestClient(app) as c:
        for i in range(2):
            params = dict(ref_params, leather=dict(ref_params["leather"], thickness=3.0 + i * 0.1))
            assert c.post("/api/preview", json={"params": params}).status_code == 202
        refused = c.post("/api/preview", json={"params": ref_params})
        assert refused.status_code == 429
        assert refused.headers["retry-after"]
        assert refused.json()["detail"]["error"]["kind"] == "rate_limited"


def test_cheap_endpoints_are_not_rate_limited(cache, ref_params):
    """Validation runs on every edit; limiting it would break the product."""
    from fastapi.testclient import TestClient
    from trayapi.main import create_app

    limiter = RateLimiter(requests=1, window_s=60.0)
    with TestClient(create_app(cache=cache, warm=False, limiter=limiter, sweep=False)) as c:
        for _ in range(30):
            assert c.post("/api/validate", json={"params": ref_params}).status_code == 200
        for path in ("/api/schema", "/api/presets", "/api/version", "/api/health"):
            assert c.get(path).status_code == 200


@pytest.mark.slow
def test_a_cache_hit_does_not_consume_a_concurrency_slot(live_client, ref_params):
    poll(live_client, live_client.post("/api/preview", json={"params": ref_params}).json()["id"])
    limiter = live_client.app.state.limiter
    before = limiter.snapshot()["in_flight"]
    for _ in range(5):
        assert live_client.post("/api/preview", json={"params": ref_params}).status_code == 200
    assert limiter.snapshot()["in_flight"] == before


# --------------------------------------------------------------------------
# request bounds
# --------------------------------------------------------------------------
def test_an_oversized_request_body_is_refused(client, ref_params):
    fat = dict(ref_params, name="x" * 400_000)
    assert client.post("/api/validate", json={"params": fat}).status_code == 413


# --------------------------------------------------------------------------
# cache eviction
# --------------------------------------------------------------------------
def _entry(cache: ArtifactCache, key: str, size: int = 4096) -> Path:
    directory = cache.dir_for(key)
    directory.mkdir(parents=True, exist_ok=True)
    blob = directory / "male.stl"
    blob.write_bytes(b"0" * size)
    cache.put(key, {"artifacts": [{"name": "male.stl", "format": "stl", "part": "male",
                                   "path": str(blob), "bytes": size, "sha256": "x"}]})
    return directory


def test_stats_report_size_entries_and_last_sweep(cache):
    _entry(cache, "a")
    _entry(cache, "b")
    stats = cache.stats()
    assert stats.entries == 2
    assert stats.bytes > 8000
    assert stats.last_sweep_at is None

    cache.sweep()
    assert cache.stats().last_sweep_at is not None


def test_eviction_by_age(cache):
    old = _entry(cache, "old")
    _entry(cache, "new")
    import os

    os.utime(old, (time.time() - 10_000, time.time() - 10_000))

    result = cache.sweep(max_age_s=3600, max_bytes=10**9)
    assert result["removed"] == ["old"]
    assert cache.get("old") is None
    assert cache.get("new") is not None


def test_eviction_by_total_size_prefers_the_least_recently_used(cache):
    import os

    for name in ("first", "second", "third"):
        _entry(cache, name, size=4096)
    now = time.time()
    os.utime(cache.dir_for("first"), (now - 300, now - 300))
    os.utime(cache.dir_for("second"), (now - 200, now - 200))
    os.utime(cache.dir_for("third"), (now - 100, now - 100))

    cache.sweep(max_age_s=10**9, max_bytes=9000)
    assert cache.get("first") is None, "the least recently used entry should go first"
    assert cache.get("third") is not None, "the most recently used entry should survive"


def test_a_pinned_entry_survives_eviction(cache):
    import os

    _entry(cache, "active")
    os.utime(cache.dir_for("active"), (0, 0))
    cache.pin("active")
    assert cache.sweep(max_age_s=1, max_bytes=0)["removed"] == []
    cache.unpin("active")
    assert cache.sweep(max_age_s=1, max_bytes=0)["removed"] == ["active"]


@pytest.mark.slow
def test_an_active_job_pins_its_cache_entry(live_client, ref_params):
    submitted = live_client.post("/api/preview", json={"params": ref_params}).json()
    cache = live_client.jobs.cache
    assert submitted["cache_key"] in cache._pinned
    poll(live_client, submitted["id"])
    assert submitted["cache_key"] not in cache._pinned


def test_a_hit_refreshes_recency(cache):
    import os

    _entry(cache, "k")
    os.utime(cache.dir_for("k"), (0, 0))
    assert cache.dir_for("k").stat().st_mtime < 1000
    cache.get("k")
    assert cache.dir_for("k").stat().st_mtime > time.time() - 10
