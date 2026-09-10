# API Layer

Status: **implemented**. The React UI is not, deliberately.

The API is a transport for `traymold.api`. It contains no CAD logic, and the
FastAPI process never imports cadquery — the only geometry it touches is the
cheap half of the core interface (validate, derive, hash), which is pure Python.

```
parameters
    ↓ validate                 geometry-free, ~1.9 ms
    ↓ canonical parameter hash
    ↓ cache?
   yes → artifact              ~5 ms (preview)
   no  → worker process        one build, one process
          ↓ build + emit
          ↓ artifact
```

---

## 1. The frozen core interface

`traymold/api.py` is the only surface an application uses.

```python
validate(params, quality=None, parts=None) -> ValidationResult
build(params, quality=None, parts=None)    -> BuildResult      # owns OCC solids
emit(result, outdir, formats)              -> list[Artifact]   # solids -> files
build_and_emit(params, quality, parts, formats, outdir) -> BuildReport   # worker unit
params_hash(params, **extra) -> str
environment() -> dict
json_schema() / defaults() / apply_options()
```

`build` and `emit` stay separate: one build serves several formats, and a build
with no filesystem is a useful thing for tests. `build_and_emit` is the unit of
work a worker performs, and returns `BuildReport` — plain data plus artifact
paths.

**OCC objects never cross a process boundary.** Pickling a `cq.Solid` was
measured and does work — 128 KB, exact volume roundtrip — so it is *safe*. It is
not *useful*: the caller only ever wants artifacts, and receiving a solid would
force the API process to import cadquery (3.1 s) and hold OCC objects in its
event loop. The worker that owns the solids writes the files.

`apply_options` folds a caller's `quality` and `parts` into the parameter
document before anything is hashed, so `build(params, quality="preview")` and
`params.with_quality("preview")` are the same request and share one cache entry.

---

## 2. API contract

| method | path | success | notes |
|---|---|---|---|
| GET | `/api/schema` | 200 | JSON Schema generated from `Params`, defaults, UI hints, versions |
| GET | `/api/presets` | 200 | `ref-4x7` (STL revision), `ref-4x7-step` (STEP revision) |
| GET | `/api/version` | 200 | api / schema / model / cadquery / OCP |
| POST | `/api/validate` | 200 | `{valid, diagnostics[], derived{}, params_hash, …}` |
| POST | `/api/preview` | **202** job, **200** on a cache hit | preview quality → GLB |
| POST | `/api/export` | **202** job, **200** on a cache hit | export quality → STEP + STL |
| GET | `/api/jobs/{id}` | 200 / 404 | job state, with `progress` and `stage` while running |
| POST | `/api/jobs/{id}/cancel` | 200 / 404 | |
| GET | `/api/artifacts/{key}/{name}` | 200 / 404 | one file; optional `?s=&v=` anonymous ids |
| GET | `/api/artifacts/{key}/bundle.zip` | 200 / 404 | every artifact + `result.json` |
| GET | `/api/jobs/{id}/events` | 200 | server-sent events, one frame per transition |
| GET | `/api/health` | 200 | status, worker pool, cache stats, limits; runs no geometry |
| GET | `/api/stats` | 200 | three public usage counters |
| POST | `/api/analytics/event` | **204** always | four client events; cannot move the counter |
| GET | `/` | 200 | developer harness, not the product UI |

Invalid parameters return **422** with
`{"detail": {"error": {kind, message, diagnostics[]}}}` and **never enqueue a
build**.

The artifact endpoints are additions to the requested list: a job hands back
URLs, so something has to serve them. Both single files and a zip are offered, so
a caller can take one part or the pair.

`/api/stats` and `/api/analytics/event` are the usage-analytics surface. `s` and
`v` on an artifact URL are opaque, client-generated, anonymous ids — a download
is a plain browser navigation and carries no headers of ours, so that is the only
way the server can attribute a file to a session. Both endpoints degrade to
zeros and 204s when analytics is disabled, and nothing on this surface can be
made to fail a build, an export or a download. See
[`analytics.md`](analytics.md).

There is exactly one authoritative schema. `test_schema.py` asserts the served
document is byte-identical to `Params.model_json_schema()`; UI hints live in a
separate `ui_hints` key and never leak into it.

### 3MF
Not shipped. STEP and STL both come free from CadQuery; 3MF needs `lib3mf` or a
`trimesh` round-trip through the tessellation, and the milestone said not to let
it delay the API. It is a self-contained addition to `exporters.write_artifacts`.

---

## 3. Worker architecture

Workers are **subprocesses**, not `multiprocessing.Process` children and not
threads.

Threads are out because OCC can abort the interpreter and is not thread-safe.
`multiprocessing` was tried and abandoned: every start method re-imports the
parent's `__main__` in the child, which is fine under `uvicorn` and fatal under
pytest or any script whose `__main__` is not import-safe — the API must not care
how it was launched. A `subprocess` plus a `multiprocessing.connection` socket
keeps the same pickled duplex channel with none of that coupling, and gives a
real `kill()`.

```
FastAPI process                     worker process (× N, persistent)
  JobManager                          python -m trayapi.worker_main
    thread per job  ──socket──►         imports traymold once (3.1 s)
    poll / timeout  ◄────────           build_and_emit → BuildReport
```

| requirement | how |
|---|---|
| one build per worker process | a worker serves one request at a time; the pool hands out idle workers |
| structured exceptions | the worker classifies and sends `{kind, message, diagnostics}`; the traceback stays in its stderr |
| a crash must not crash FastAPI | the parent watches `Popen.poll()`; a dead worker becomes `worker_crash` and is replaced |
| build timeout | the parent polls with a deadline and `kill()`s the worker; default 120 s |
| worker recycling | replaced after `max_tasks` builds (default 24) — OCC leaks steadily |
| no raw OCC traces in responses | only the mapped kinds below ever leave the process |

Pre-warming matters: importing traymold costs 3.1 s, so cold workers would
dominate a 2.5 s preview. Workers are started and warmed at app startup
(3.45 s total).

### Error mapping

| kind | raised by |
|---|---|
| `validation_error` | `traymold.validate.ValidationError` (also caught before dispatch) |
| `geometry_build_error` | `ProfileError`, and anything else the kernel throws |
| `offset_verification_failure` | `profiles.OffsetError` — the realised gap check |
| `timeout` | the parent's deadline |
| `worker_crash` | the worker process died |
| `export_failure` | `OSError` and friends while writing artifacts |
| `cancelled` | a cancel arrived before or during the build |

### A body the model will not parse

Every endpoint takes the same `params` model, so one number outside its bounds
is refused identically by `/api/validate`, `/api/preview` and `/api/export`.
FastAPI's own answer to that is a 422 whose `detail` is a list of pydantic
dicts, and shipping it had three consequences, each worse than the last:

* the browser knows one error envelope, `detail.error.{kind,message,diagnostics}`,
  and rendered none of that list — it showed `request failed (422)`;
* pydantic locates the error at
  `["body","params","tray","profile","g2_quintic_obround","length"]` while the
  form addresses that input as `tray.profile.length`, so nothing could be
  attached to a field even if it had been readable;
* **validate went down with the build.** The endpoint whose entire job is to
  explain what is wrong failed on exactly the documents that need explaining, so
  the app had no diagnostics at all — nothing inline, nothing blocking the
  build button, and a stored document that reproduced it on reload.

`trayapi.request_errors` answers it in the same envelope as everything else,
with the field named the way the form names it:

```json
{"detail": {"error": {"kind": "validation_error",
  "message": "tray.profile.length must be greater than 0 (this is 0)",
  "diagnostics": [{"code": "E-RANGE", "severity": "error",
                   "field": "tray.profile.length",
                   "message": "must be greater than 0 (this is 0)"}]}}}
```

| code | pydantic types |
|---|---|
| `E-RANGE` | `greater_than`, `greater_than_equal`, `less_than`, `less_than_equal`, `multiple_of` |
| `E-REQUIRED` | `missing` |
| `E-VARIANT` | `union_tag_invalid`, `union_tag_not_found`, `literal_error` |
| `E-INVALID` | everything else, keeping pydantic's own sentence |

The variant tag is dropped from the path because the form shows one variant at
a time and hangs its fields directly off the union field. That is safe only
while no field is named like a tag, so `test_request_errors` asserts it across
the whole schema rather than leaving it as an assumption.

---

## 4. Cache key

```
cache_key = sha256(canonical_json({
    params:  canonical parameters, minus non-geometric fields,
             with the requested quality and part selection already folded in,
    env:     {schema_version, model_version, cadquery, OCP},
    formats: sorted set of requested artifact formats,
}))
```

* `quality` and `parts` are **not** separate terms — `apply_options` folds them
  into the parameter document first, so the two ways of expressing the same
  request hash identically. Tested.
* `name` is excluded (`NON_GEOMETRIC_FIELDS`): two users who label the same
  design differently share one build.
* `environment()` reads the version module at call time, so a `MODEL_VERSION`
  bump or a kernel upgrade invalidates every key. Both tested.

Layout: `CACHE_DIR/<key>/{result.json, preview.glb, male.step, …, bundle.zip}`.
A hit requires `result.json` and every artifact it lists to exist. **Failed
builds are never cached.**

### Per-half keys, for previews

A preview is two builds (§6a), so it uses two entries. `half_key` is the same
address over a *projection* of the parameters:

```
half_key = sha256(canonical_json({
    params:  canonical parameters, minus this half's IGNORED_BY paths
             and minus `mold.parts`,
    part:    "male" | "female",
    env:     …, formats: …,
}))
```

`mold.parts` is dropped and replaced by `part`, so asking for both halves and
asking for one hit the same entry. `IGNORED_BY` is what makes reuse possible and
is proved against geometry in `test_split_keys.py` — see §6a.

Note the quality *defaults* are not in either key: they resolve at build time
rather than living in the parameter document. Changing one therefore requires a
`MODEL_VERSION` bump to invalidate what is already on disk, which is what
0.2.0 → 0.3.0 was for. Anything else that changes the bytes for unchanged
parameters needs the same: 0.3.0 → 0.4.0 covers the female's features moving
onto the parting face and the print-oriented STEP/STL (§7, architecture §7.10).

### Concurrent deduplication
`JobManager` keeps `cache_key → job_id` for in-flight jobs under a lock. A second
request for a key already building attaches to that job rather than starting a
second one. `test_concurrent_identical_requests_deduplicate_to_one_build` fires
four simultaneous requests through a counting pool and asserts exactly one build.

---

## 5. Job lifecycle

```
submit ─┬─ cache hit ──────────────────────────► complete (cached, HTTP 200)
        ├─ in-flight same key ─────────────────► that job's id
        └─ new ─► queued ─► running ─┬────────► complete
                                     ├────────► failed    (structured error)
                                     └────────► cancelled
        queued ─► cancelled  (always)
        running ─► cancelled (the worker is terminated)
```

`progress` is always `null`. The core exposes no meaningful stages, and a
fabricated percentage would be a lie; `status` carries a short message
(`queued`, `building geometry`, `served from cache`, `done`) for a spinner.

Cancellation works in both states: queued work never starts, and a running build
is stopped by killing its worker — practical here precisely because each build
owns a whole process.

---

## 6. Preview artifact

**Two GLBs, one per half** — `male.glb` and `female.glb` — each holding that
half as a node named for it:

```
male.glb    node "male"    → mesh "male"
female.glb  node "female"  → mesh "female"
```

Two files rather than one because a preview is built as two jobs; see §6a. Both
are emitted in assembly position in the core's canonical frame — origin at the
plan centre on the parting plane, +Z the plug direction — so loading both and
adding nothing shows the mold closed, and the viewer shows, hides and explodes
each by moving its named node.

A build that asks for only one half returns only that half's file. A build that
puts both halves in one file still writes `preview.glb` with `part: assembly`
and both nodes inside it, which is what the CLI and any older client get.

---

## 6a. Why a preview is two builds

The plug and the cavity share nothing downstream of the base profile. The male
*is* that profile; the female is the same profile offset by the forming gap; and
`apply_features` guards every branch on which half it was handed. So the halves
can be built separately, and are:

* **A change to one half does not rebuild the other.** Each half is content
  addressed on the parameters that can actually reach it — `cache.half_key`,
  with `IGNORED_BY` naming the exclusions. Changing `leather.thickness` moves
  the forming gap, so the cavity is rebuilt and the plug is served from disk.
* **A change to both is built in parallel.** Two halves go to two workers, so
  the wall clock is the slower half rather than the sum.

`IGNORED_BY` is a claim about geometry, so `test_split_keys.py` proves it: every
excluded field is changed and the half it is excluded from must come out
volumetrically identical. Both halves are built from the *whole* parameter
document — only the key is projected — so validation and the derived values are
exactly what a combined build produces.

Exports are never split: their STEP and STL are per-part already, a bundle
spanning two cache directories has no meaning, and an export happens once.

It comes from the same `build()` as an export, at preview quality. There is no
second, browser-side approximation of the tray. Preview's ≤50 µm contract is
tested in the core suite and unaffected by the API.

`asset.extras` carries `params_hash`, `schema_version`, `model_version` and
`quality`.

---

## 7. Export artifacts

STEP is the CAD reference, STL the slicer export, one file per part.
Traceability goes into whatever channel each format allows:

| format | channel |
|---|---|
| STEP | a comment before `FILE_DESCRIPTION` with `params_hash`, schema, model, quality |
| STL | the 80-byte binary header: `traymold <model_version> <hash[:24]>` |
| GLB | `asset.extras` |

Export geometry is never degraded for latency: export quality is fixed at
`max_section_sagitta = 0.002 mm` regardless of API load.

**STEP and STL come out print-oriented; the GLB does not.** The solids are built
in assembly orientation — z=0 the parting face, +Z the plug direction — which is
what the viewer needs, because the two halves only read as a mold when they are
shown closed. A slicer needs the opposite: the female's parting face carries the
entry blend, the pry notches, the clamp chamfers and the blind pin holes, so the
exported female is turned over (a rotation about X, never a mirror) and dropped
onto z=0, leaving its flat outer face on the bed. The male is already
plate-down and is left where it was built. See architecture §7.10.

---

## 8. Measured latency

`packages/api/bench/benchmark_api.py`, median of 3, geometry and artifact times
taken from the worker's own report so the remainder is genuinely the API's.

| operation | total | submit | geometry | artifacts | IPC | download | **API overhead** |
|---|---|---|---|---|---|---|---|
| validate | **1.9 ms** | — | — | — | — | — | 1.9 ms |
| preview, cache miss | 3413 ms | 3.1 | 3291 | 41.1 | 70.6 | 2.6 | **7.7 ms** |
| preview, cache hit | **4.8 ms** | 2.5 | — | — | — | 2.3 | 2.5 ms |
| export, cache miss | 6044 ms | 3.2 | 5435 | 193.4 | 391.7 | 16.7 | **7.1 ms** |
| export, cache hit | **18.4 ms** | 2.6 | — | — | — | 15.8 | 2.6 ms |

App startup including worker warm-up: 3.45 s.

### The edit loop, after the split

The table above times a build. What a *user* waits for when they change one
setting is smaller, because a preview is two independently cached halves built
in parallel. Measured against a running API on the reference design:

| the edit | wall | what happened |
|---|---|---|
| nothing changed | **0.00 s** | both halves served from cache |
| a cavity setting (`cavity_plate_thickness`) | **1.74 s** | plug reused, cavity rebuilt |
| leather thickness | **1.80 s** | moves the forming gap, so the cavity only |
| a plug setting (`base_plate_thickness`) | **3.20 s** | cavity reused, plug rebuilt |
| tray length | **3.70 s** | both rebuilt, in parallel; ~5.5 s in series |
| a cold build | 4.21 s | both halves, nothing cached |

The plug is the expensive half — its floor blend alone is 41% of a preview — so
a cavity-side edit is roughly a third of a full rebuild.

The API adds ~7 ms to a build — 0.2 % of a preview, 0.1 % of an export. The core
baseline it wraps is 2.5 s / 5.4 s; the extra ~0.9 s and ~0.6 s here are the
benchmark's own polling client competing for the GIL, visible as the IPC column.

`validate` at 1.9 ms is comfortably keystroke-rate. It got there by memoising the
base profile's curvature limits per profile spec — the models are immutable, so
the answer cannot go stale — which took the core call from 12 ms to 0.06 ms.

---

## 9. Public-exposure hardening

Added when the browser application made the API publicly reachable.

**CORS** — `TRAYAPI_ALLOWED_ORIGINS`, comma separated. `*` is the development
default and wrong for anything on the internet.

**Rate limiting**, on `/api/preview` and `/api/export` only. Schema, presets,
version, health, validate and artifact downloads are never limited: validation is
~2 ms and the UI calls it on every edit, so limiting it would break the product to
protect nothing.

Two independent limits:

| limit | default | applies to |
|---|---|---|
| sliding window per client | 20 requests / 60 s | every build request |
| concurrent builds per client | 3 | only requests that **start** a build |

A cache hit, and a request that attaches to an identical build already running,
occupy no worker and so consume no concurrency slot — refusing them would punish
a client for asking for something cheap. Refusals are `429` with `Retry-After`.

**Request bounds** — bodies over `TRAYAPI_MAX_REQUEST_BYTES` (256 kB) are refused
with `413` from the `Content-Length` header, before being buffered. A parameter
document is a few kB.

**Cache eviction** — age first, then LRU by last *read* until the store is under
`TRAYAPI_CACHE_MAX_BYTES` (2 GiB default) and `TRAYAPI_CACHE_MAX_AGE_S` (7 days).
Recency is the entry directory's mtime, touched on every hit, so a design people
keep returning to outlives one built once and forgotten. A background thread
sweeps every `TRAYAPI_CACHE_SWEEP_INTERVAL_S` (300 s). **An entry belonging to an
active job is pinned** and never removed, however old — the job is about to hand
out its URLs. `GET /api/health` reports entries, bytes, the last sweep and what it
removed.

**Health** — `GET /api/health` returns status, uptime, worker pool availability,
cache statistics and the current limits. It runs no geometry and takes no worker
round-trip.

## 10. Deployment constraint: one API process

Job state is in memory, deliberately. That means one API process and its worker
pool; several would each have their own job registry, so a client polling job `X`
could reach a process that never heard of it.

The artifact cache is on disk, so recovery is cheap: after a restart the SSE
connection fails, `GET /api/jobs/{id}` returns 404, and resubmitting the same
parameters hits the cache and answers immediately. Both halves of that path are
tested. Add a shared job store when load actually requires it, not before.

## 11. Server-sent events

`GET /api/jobs/{id}/events` streams one frame per state transition, named for the
state (`queued`, `running`, `complete`, `failed`, `cancelled`) and carrying the
full job payload, plus a keep-alive comment every 15 s. The job manager pushes on
transition rather than the endpoint polling, so a browser sees `complete` the
moment the worker returns.

`progress` is a real fraction, 0 to 1, and `stage` names the build stage behind
it. The core calls back as each stage *finishes*; `traymold.progress.plan()`
turns the stage into a fraction using costs measured on the reference design,
normalised over the stages that particular parameter set will actually run. So
the bar advances in real checkpoints rather than being eased along a timer, and
a build with one half already cached does not stall waiting for work that was
never going to happen.

`progress` is `null` until the first stage lands and on a cache hit, where
nothing was built to be partway through. `status` carries the stage's label
("blending the tray floor").

For a split preview the two halves report independently and the job's fraction
is their weighted mean, weighted by how long each half is expected to take — the
plug is about 2.7x the cavity, so a plain average would run ahead.

`GET /api/jobs/{id}` remains the fallback for a dropped stream, a buffering proxy
or a restarted API.

## 12. Draft stays experimental

Nonzero `tray.draft_angle` is refused with `E-DRAFT-EXPERIMENTAL` unless the
request sets `allow_experimental: true`. The message states what the current
implementation actually holds — a constant profile-plane gap, so the normal gap
is `nominal × cos(draft_angle)` — and that the contract is undecided. The UI hint
for the field carries the same warning.

Nothing was changed in the geometry. If the normal-gap contract is chosen later,
the correction is to scale the offset by `1/cos θ`, which is a new behaviour and
must not silently redefine existing parameters.
