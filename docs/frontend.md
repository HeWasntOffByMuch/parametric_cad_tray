# Browser Application

Status: **implemented**. Static frontend, React + TypeScript + Vite + React Three
Fiber, deployable to GitHub Pages against a separately hosted API.

---

## 1. Architecture

```
packages/web/
  src/
    config.ts          where the backend lives, resolved at runtime
    api/
      client.ts        typed fetch wrappers, one error shape
      jobStream.ts     SSE with a polling fallback
      types.ts         transport envelopes only - never the parameter schema
    form/
      schema.ts        JSON Schema -> field tree, grouping, value helpers
      widgets.tsx      number+slider, toggle, select, text
      SchemaForm.tsx   renders groups, objects and discriminated unions
    state/
      useDesign.ts     the preview state machine
      urlState.ts      shareable links and localStorage
    viewer/Viewer.tsx  R3F canvas over the GLB
    panels/            status, derived values, diagnostics, export, controls
    App.tsx
```

No router. The application is one screen and the URL fragment carries design
state, so there is nothing to route and nothing that breaks under a repository
path.

**Backend URL resolution**, most specific first: `?api=…` (also remembered) →
`localStorage` → `window.__TRAYMOLD_API_BASE__` (editable in the deployed
`index.html`) → `VITE_API_BASE_URL` at build time → same origin, which the Vite
dev server proxies. A static build is therefore repointable without rebuilding.

---

## 2. Form strategy

The parameter schema is not restated in TypeScript. `form/schema.ts` walks the
document served by `GET /api/schema` and resolves `$ref`, `anyOf` nullables,
enums, numeric bounds and `oneOf` + `discriminator` unions into a field tree.
`api/types.ts` types only the envelopes; the parameter document itself is JSON.

Grouping comes from `ui_hints`, which lives in the backend beside the schema:
Shape, Dimensions, Leather & fit, Mold, Features, Manufacturing, Advanced.

Two rules make the grouping work in practice:

* **An explicit listing wins over a parent.** Shape holds `tray.profile` for its
  type selector while Dimensions holds `tray.profile.length`; the group that owns
  the parent is told to skip the child rather than render it twice.
* **Unlisted fields are swept in at the leaf.** A parameter added to the core
  appears in Advanced with no frontend change — asserted by a test that injects a
  synthetic field into the schema.

Widgets follow the schema's own metadata. A numeric field gets a text input, and
a slider as well where the hints give a range. **The number input is
authoritative**: it accepts anything the schema allows, while the slider's range
may be narrower. Titles are humanised for containers (Pydantic titles a nested
model with its class name), and every control's accessible name is qualified by
its parent, because three different fields are called "Depth".

---

## 3. Preview state machine

```
empty ──generate──► generating ──ok──► clean ──edit──► dirty ──generate──► generating
                         │                              ▲                      │
                         └──fail──► failed ─────────────┘◄─────────────────────┘
```

`clean` and `dirty` both have geometry on screen. **Editing never blanks the
viewer**; it dims it and marks it out of date, in the status pill and on a badge
over the canvas.

| interaction | validation | geometry |
|---|---|---|
| typing in a number field | immediately, debounced 250 ms | after a 700 ms idle pause |
| dragging a slider | on every value change | never during the drag; on release |
| Update preview | — | immediately |
| choosing a preset | immediately | after the idle pause |

**Staleness is decided by the parameters, not by arrival order and not by the
server hash.** A result may only be displayed if the parameters it was built from
still equal the current ones, compared by a stable fingerprint. Using the server
hash would tie the guard to validation timing — a preview triggered before its
validation returned would look stale when it is not — and arrival order would let
a slow older job overwrite a newer one. A superseded job is also cancelled, so it
stops burning a worker.

Errors block Preview and Export; warnings do not.

### Not building the same thing twice

`generatePreview` is idempotent for the parameters already on screen. Two paths
used to send a request that could not change anything:

- **Clicking Update preview when nothing has changed.** The GLB would come back
  byte-identical, from cache, in milliseconds - which is why it was easy to miss.
  It is still a round trip, a rate-limit slot and a re-fetch of the model. The
  button is now disabled while the state is `clean`, and the call is a no-op if
  it arrives anyway.
- **Clicking Update preview while a field still has focus.** The click blurs the
  input, which commits, which schedules an immediate build; then the button's own
  handler starts a second one, cancelling and replacing the first. Measured
  through the real page: one click, two `POST /api/preview`. A build already in
  flight for the same fingerprint now absorbs the second request.

Measured on the running application, counting every `/api/` call:

| | builds |
|---|---|
| idle, nothing touched, 10 s | 0 |
| change one dimension | 1 |
| click Update preview, nothing changed | 0 (was 2) |
| edit, then click immediately | 1 (was 2) |
| return to a previously built design | 1, served from cache |

---

## 4. SSE

`POST /api/preview` → job id → `EventSource` on `/api/jobs/{id}/events`. The
backend pushes on every state transition (`queued`, `running`, `complete`,
`failed`, `cancelled`) with the full job payload, plus a keep-alive comment every
15 s. `progress` is always `null`; the human-readable `status` drives the spinner.

`followJob` falls back to polling `GET /api/jobs/{id}` when `EventSource` is
absent, when the stream never delivers a frame (a buffering proxy), or when it
drops. That is why the polling endpoint still exists, and it is also the recovery
path after an API restart: query the job, and if it is gone, resubmit — the
artifact cache usually makes that instant.

---

## 5. Viewer

React Three Fiber over the GLB the backend produced. **No mold geometry is
computed in JavaScript**; the GLB's own `male` and `female` nodes are used
directly, so there is no second approximation of the tray in the browser.

Orbit and zoom, reset view, part mode (both / male / female), individual
visibility toggles, and assembled / exploded views. The camera fits itself to the
model's real bounding box, so a 235 mm plate and a 500 mm one frame the same. The
model is authored Z-up in millimetres with its origin on the parting plane; the
scene is rotated so CAD +Z is screen up.

The part rules are pure functions (`partVisibility`, `explodeOffset`) and are
tested without a WebGL context.

### Lighting and the floor

Both were built for one viewpoint and broke as soon as the camera left it.

The rig had every light above the parting plane, and a hemisphere light gives a
downward-facing face its ground colour and nothing else - which was near-black.
Tipping under an exploded mold, exactly what you do to inspect a cavity, showed a
black silhouette. A light now rides the camera, aimed at the origin, so the
guarantee is positional rather than directional: whatever is turned towards you
is lit, from any angle. The fixed key and fill still do the shaping.

The grid is a floor, so it is drawn only from above (`side: FrontSide`) and sits
under the *current* bounding box rather than a fixed fraction of the model
radius. Exploding drops the male half well below where it sits assembled, so a
floor placed once at load time cut straight through it.

---

## 6. Export UX

The same asynchronous job model as preview, and completely independent of it:
requesting an export never regenerates the preview. Parts (both / male / female)
and formats (STEP, STL) are chosen in the panel; download links — plus
`bundle.zip` — appear only once the job completes. A cache hit returns
immediately.

---

## 7. Sharing and persistence

The URL fragment carries a versioned, deterministic encoding of the **parameters**
— never a cache key, so a link still works after the cache is swept and against a
different backend:

```
#d1.<base64url>   deflate-raw compressed JSON, where CompressionStream exists
#j1.<base64url>   plain JSON, the fallback
```

A reader accepts both regardless of which it can write. The most recent design is
also kept in `localStorage`; **the URL takes precedence.** A fragment is never
sent to the server, and requires no server-side routing.

---

## 8. Deployment

`vite.config.ts` sets `base: './'`, so every asset URL is relative and one build
serves both the domain root and `https://user.github.io/parametric_cad_tray/`.
Verified by serving `dist/` under a repository path: index, JS, CSS and a
fragment-carrying deep link all return 200 with relative URLs.

`.github/workflows/pages.yml` builds and deploys on a push to `main`, taking the
API URL from the `TRAYMOLD_API_BASE_URL` repository variable, or from
`https://$TRAYMOLD_API_DOMAIN` when only the domain is configured — the same
variable the API deploy uses, so the host is named once. Set
`TRAYAPI_ALLOWED_ORIGINS` on the backend to the Pages origin: the exact scheme
and host, with no path, so `https://user.github.io` and not
`https://user.github.io/parametric_cad_tray`.

The API half — the image, the compose stack behind Caddy, the VPS prerequisites
and how to rehearse the whole thing locally — is
[`docs/deployment.md`](deployment.md).

---

## 9. Environment

| variable | side | meaning |
|---|---|---|
| `VITE_API_BASE_URL` | build | default backend URL baked into the bundle |
| `window.__TRAYMOLD_API_BASE__` | runtime | editable in the deployed `index.html` |
| `?api=` | runtime | per-visit override, remembered in localStorage |
| `TRAYAPI_ALLOWED_ORIGINS` | API | CORS origins, comma separated; `*` is development only |
| `TRAYAPI_WORKERS` | API | CAD worker processes (default 2) |
| `TRAYAPI_BUILD_TIMEOUT_S` | API | per-build wall clock (default 120) |
| `TRAYAPI_MAX_TASKS_PER_WORKER` | API | recycle threshold (default 24) |
| `TRAYAPI_CACHE_DIR` | API | artifact store |
| `TRAYAPI_CACHE_MAX_BYTES` | API | eviction size ceiling (default 2 GiB) |
| `TRAYAPI_CACHE_MAX_AGE_S` | API | eviction age ceiling (default 7 days) |
| `TRAYAPI_CACHE_SWEEP_INTERVAL_S` | API | background sweep period (default 300) |
| `TRAYAPI_RATE_LIMIT_REQUESTS` / `_WINDOW_S` | API | build requests per client per window (20 / 60 s) |
| `TRAYAPI_MAX_CONCURRENT_JOBS_PER_CLIENT` | API | in-flight builds per client (default 3) |
| `TRAYAPI_MAX_REQUEST_BYTES` | API | request body ceiling (default 256 kB) |

`make dev` starts the API with its worker pool and the Vite dev server together;
`make doctor` prints the resolved configuration and pings health.

---

## 10. Deployment constraint: one API process

Job state is in memory, deliberately — no Redis, no distributed queue. That means
**one API process and its worker pool**. Running several would give each its own
job registry, so a client polling job `X` could hit a process that has never
heard of it.

The artifact cache is on disk and is shared-safe, so recovery is cheap: after a
restart the client's SSE connection fails, `GET /api/jobs/{id}` returns 404, and
resubmitting the same parameters hits the cache and answers immediately. Tested.

Scale out only when the load actually requires it, and add a shared job store at
that point rather than before.
