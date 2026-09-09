# Parametric leather-tray wet mold

A parametric CAD application: one deterministic geometry model in Python and
CadQuery, a thin HTTP layer over it, and a browser front end that never contains
CAD logic.

```
packages/tray-core   the geometry. CadQuery + Pydantic. The source of truth.
packages/api         FastAPI over the core, with process-isolated CAD workers.
packages/web         React + TypeScript + Vite + React Three Fiber.
deploy/              the image, the compose stack and the smoke script.
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

## Or run the deployment, locally

The same image, compose file and Caddyfile the VPS runs, with TLS off and on
unprivileged ports.

```bash
make deploy-local      # build and start the containerised stack on :8080
make deploy-smoke      # 19 checks: TLS, CORS, SSE buffering, cache, exports
make deploy-local-web  # the GitHub Pages build, pointed at that stack
make deploy-down
```

## Documentation

| | |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | the geometry core: what the reference is, how it is rebuilt, why |
| [`docs/parameter-model.md`](docs/parameter-model.md) | the parameter schema, dependencies and diagnostics |
| [`docs/api.md`](docs/api.md) | the HTTP contract, workers, caching, job lifecycle |
| [`docs/frontend.md`](docs/frontend.md) | the browser application, its state machine and viewer |
| [`docs/deployment.md`](docs/deployment.md) | GitHub Pages, the VPS, and rehearsing both locally |

## The rule the whole project is built around

```
female_base_profile = offset(male_base_profile, forming_gap)
```

The female cavity is a true 2D offset of the male's **base** profile — the plan
curve before any 3D edge treatment. Verified against the original Onshape STEP to
2.4 um, and enforced by tests that assert no male fillet, plate dimension or
manufacturing feature can reach it.
