# Parametric leather-tray wet mold

A parametric CAD application: one deterministic geometry model in Python and
CadQuery, a thin HTTP layer over it, and a browser front end that never contains
CAD logic.

```
packages/tray-core   the geometry. CadQuery + Pydantic. The source of truth.
packages/api         FastAPI over the core, with process-isolated CAD workers.
packages/web         React + TypeScript + Vite + React Three Fiber.
tools/reference_probe  measurement scripts behind every number in the docs.
reference/           the original STEP and STL pair this was reverse-engineered from.
```

## Run it

```bash
make install
make dev        # API + worker pool + Vite
make test       # core, API and frontend suites
make doctor     # resolved configuration, and ping the API
```

## Documentation

| | |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | the geometry core: what the reference is, how it is rebuilt, why |
| [`docs/parameter-model.md`](docs/parameter-model.md) | the parameter schema, dependencies and diagnostics |
| [`docs/api.md`](docs/api.md) | the HTTP contract, workers, caching, job lifecycle |
| [`docs/frontend.md`](docs/frontend.md) | the browser application and its deployment |

## The rule the whole project is built around

```
female_base_profile = offset(male_base_profile, forming_gap)
```

The female cavity is a true 2D offset of the male's **base** profile — the plan
curve before any 3D edge treatment. Verified against the original Onshape STEP to
2.4 um, and enforced by tests that assert no male fillet, plate dimension or
manufacturing feature can reach it.
