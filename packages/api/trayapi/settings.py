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


SETTINGS = Settings()
