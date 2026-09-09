# trayapi — HTTP layer over the traymold geometry core

Thin by construction. It validates transport, hashes, looks in the cache, hands
work to a worker process and serves files. It contains no CAD logic and the API
process never imports cadquery.

```
parameters → validate → canonical hash → cache? ─yes→ artifact
                                          └─no→ worker process → artifact
```

## Endpoints

| method | path | notes |
|---|---|---|
| GET | `/api/schema` | JSON Schema generated from `traymold.params.Params`, defaults, UI hints |
| GET | `/api/presets` | `ref-4x7` (STL revision) and `ref-4x7-step` (STEP revision) |
| GET | `/api/version` | api / schema / model / cadquery / OCP versions |
| POST | `/api/validate` | geometry-free; typed diagnostics + derived values |
| POST | `/api/preview` | 202 + job; preview quality, GLB |
| POST | `/api/export` | 202 + job; export quality, STEP + STL |
| GET | `/api/jobs/{id}` | job state |
| POST | `/api/jobs/{id}/cancel` | cancels queued work, terminates a running worker |
| GET | `/api/artifacts/{key}/{name}` | one artifact |
| GET | `/api/artifacts/{key}/bundle.zip` | every artifact of a build plus its report |
| GET | `/` | developer harness, not the product UI |

A cache hit answers `200` with `state: complete` instead of `202`.

## Running

```bash
PYTHONPATH=packages/tray-core:packages/api uvicorn trayapi.main:app --port 8000
```

Configuration is environment-only and never changes geometry: `TRAYAPI_CACHE_DIR`,
`TRAYAPI_WORKERS`, `TRAYAPI_MAX_TASKS_PER_WORKER`, `TRAYAPI_BUILD_TIMEOUT_S`.

## Tests

```bash
python3 -m pytest packages/api/tests -q                 # everything
python3 -m pytest packages/api/tests -q -m "not slow"   # no real geometry
```

## Benchmark

```bash
python3 packages/api/bench/benchmark_api.py 3
```
