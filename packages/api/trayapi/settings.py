"""Runtime configuration.  Everything here is an operational knob; nothing here
changes geometry."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    cache_dir: Path = Path(os.environ.get("TRAYAPI_CACHE_DIR", "/tmp/trayapi-cache"))
    workers: int = _int("TRAYAPI_WORKERS", 2)
    #: A worker is recycled after this many builds.  OCC leaks steadily.
    max_tasks_per_worker: int = _int("TRAYAPI_MAX_TASKS_PER_WORKER", 24)
    #: Wall-clock budget for one build.  Export of the reference is ~5.5 s.
    build_timeout_s: float = _float("TRAYAPI_BUILD_TIMEOUT_S", 120.0)
    #: How long a worker may take to import traymold on startup.
    worker_start_timeout_s: float = _float("TRAYAPI_WORKER_START_TIMEOUT_S", 60.0)
    job_retention: int = _int("TRAYAPI_JOB_RETENTION", 500)

    # -- public exposure ---------------------------------------------------
    #: Origins allowed to call the API.  "*" is fine for local development and
    #: wrong for anything reachable from the internet.
    allowed_origins: tuple[str, ...] = tuple(
        o.strip() for o in os.environ.get("TRAYAPI_ALLOWED_ORIGINS", "*").split(",") if o.strip()
    )
    #: Token bucket for the endpoints that cost CPU: N requests per window.
    rate_limit_requests: int = _int("TRAYAPI_RATE_LIMIT_REQUESTS", 20)
    rate_limit_window_s: float = _float("TRAYAPI_RATE_LIMIT_WINDOW_S", 60.0)
    #: Expensive jobs one client may have in flight at once.
    max_concurrent_jobs_per_client: int = _int("TRAYAPI_MAX_CONCURRENT_JOBS_PER_CLIENT", 3)
    #: Parameter documents are a few kB; anything larger is not a design.
    max_request_bytes: int = _int("TRAYAPI_MAX_REQUEST_BYTES", 256 * 1024)

    # -- cache eviction ----------------------------------------------------
    cache_max_bytes: int = _int("TRAYAPI_CACHE_MAX_BYTES", 2 * 1024 * 1024 * 1024)
    cache_max_age_s: float = _float("TRAYAPI_CACHE_MAX_AGE_S", 7 * 24 * 3600)
    cache_sweep_interval_s: float = _float("TRAYAPI_CACHE_SWEEP_INTERVAL_S", 300.0)

    # -- usage analytics ---------------------------------------------------
    #: SQLite file for product analytics. Empty disables analytics entirely,
    #: which is the default: nothing should start writing a database into
    #: whatever directory a developer happened to run the server from. It also
    #: must not live beside the artifact cache - that directory is swept.
    #: Production: TRAYMOLD_ANALYTICS_DB=/var/lib/traymold/analytics/analytics.sqlite3
    analytics_db: str = os.environ.get("TRAYMOLD_ANALYTICS_DB", "").strip()
    #: Client events are cheap but a browser can loop; this is its own budget,
    #: separate from the build limiter, so telemetry can never starve a build.
    analytics_rate_limit: int = _int("TRAYAPI_ANALYTICS_RATE_LIMIT", 60)
    analytics_rate_window_s: float = _float("TRAYAPI_ANALYTICS_RATE_WINDOW_S", 60.0)


SETTINGS = Settings()
