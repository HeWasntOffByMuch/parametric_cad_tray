"""End-to-end API latency, separated from raw geometry time.

    python3 packages/api/bench/benchmark_api.py [runs]

Reports, per operation: total wall time as a client sees it, and the pieces -
request overhead, queue delay, geometry, artifact writing, artifact serving.
Geometry and artifact times come from the worker's own report, so what is left
over is genuinely the API's cost.
"""

from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))
sys.path.insert(0, str(ROOT / "packages" / "api"))

from fastapi.testclient import TestClient  # noqa: E402

from trayapi.cache import ArtifactCache  # noqa: E402
from trayapi.main import create_app  # noqa: E402


def poll(client, job_id, timeout=300.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["state"] in ("complete", "failed", "cancelled"):
            return body
        time.sleep(0.01)
    raise SystemExit(f"job {job_id} timed out")


def run(client, endpoint, params, *, fetch=True):
    t0 = time.perf_counter()
    response = client.post(endpoint, json={"params": params})
    submit = time.perf_counter() - t0
    body = response.json()
    cached = body["cached"]
    if body["state"] == "complete":
        total_job = 0.0
    else:
        t1 = time.perf_counter()
        body = poll(client, body["id"])
        total_job = time.perf_counter() - t1
    fetched = 0.0
    if fetch and body["artifacts"]:
        t2 = time.perf_counter()
        for artifact in body["artifacts"].values():
            client.get(artifact["url"])
        fetched = time.perf_counter() - t2
    timings = {} if cached else body.get("timings", {})
    return {
        "total": submit + total_job + fetched,
        "submit": submit,
        "job": total_job,
        "build": timings.get("build_s", 0.0),
        "emit": timings.get("emit_s", 0.0),
        "roundtrip": timings.get("worker_roundtrip_s", 0.0),
        "fetch": fetched,
        "cached": cached,
        "bytes": sum(a["bytes"] for a in body["artifacts"].values()),
    }


def median_of(samples, key):
    return statistics.median(s[key] for s in samples)


def main(runs: int = 3) -> int:
    cache_dir = Path(tempfile.mkdtemp(prefix="trayapi-bench-"))
    cache = ArtifactCache(cache_dir)
    t0 = time.perf_counter()
    app = create_app(cache=cache, warm=True)
    rows = []
    with TestClient(app) as client:
        startup = time.perf_counter() - t0
        params = next(p for p in client.get("/api/presets").json() if p["name"] == "ref-4x7-step")["params"]

        validate_times = []
        for _ in range(max(runs, 20)):
            t = time.perf_counter()
            client.post("/api/validate", json={"params": params})
            validate_times.append(time.perf_counter() - t)
        rows.append(("validate", {"total": statistics.median(validate_times), "submit": 0.0,
                                  "job": 0.0, "build": 0.0, "emit": 0.0, "roundtrip": 0.0,
                                  "fetch": 0.0, "bytes": 0}))

        for endpoint, label in (("/api/preview", "preview"), ("/api/export", "export")):
            misses, hits = [], []
            for i in range(runs):
                cache.clear()
                tweaked = dict(params, leather=dict(params["leather"], thickness=3.0 + i * 0.01))
                misses.append(run(client, endpoint, tweaked))
                hits.append(run(client, endpoint, tweaked))
            keys = ("total", "submit", "job", "build", "emit", "roundtrip", "fetch", "bytes")
            rows.append((f"{label} cache miss", {k: median_of(misses, k) for k in keys}))
            rows.append((f"{label} cache hit", {k: median_of(hits, k) for k in keys}))

    shutil.rmtree(cache_dir, ignore_errors=True)

    print(f"median of {runs} runs; app startup incl. worker warm-up: {startup:.2f} s\n")
    print(f"{'operation':20} {'total':>9} {'submit':>9} {'geometry':>9} {'artifacts':>10} "
          f"{'ipc':>8} {'download':>9} {'api overhead':>13}")
    for name, row in rows:
        # IPC = worker round-trip minus the work the worker reported doing
        ipc = max(0.0, row["roundtrip"] - row["build"] - row["emit"])
        overhead = row["total"] - row["build"] - row["emit"] - row["fetch"] - ipc
        print(f"{name:20} {row['total']*1000:8.1f}ms {row['submit']*1000:8.1f}ms "
              f"{row['build']*1000:8.1f}ms {row['emit']*1000:9.1f}ms {ipc*1000:7.1f}ms "
              f"{row['fetch']*1000:8.1f}ms {overhead*1000:12.1f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
