# Parametric Leather-Tray Wet-Mold Generator — Architecture

Status: **design proposal, nothing implemented yet.**
Scope: turn the single `4x7` wet-mold pair in `reference/` into a parametric CAD
application (CadQuery core → FastAPI → React/R3F UI).

Companion document: [`parameter-model.md`](./parameter-model.md) — the parameter
schema, dependencies and validation rules in detail.

---

## 1. What is in the repository

```
reference/
  4x7-male-wetmold.stl        binary STL, 26 738 tris, 1.34 MB
  4x7-female-wetmold.stl      binary STL, 37 626 tris, 1.88 MB
  reference_render_preview.webp   slicer screenshot of both plates
  reference_real_picture.webp     photo of the printed parts
```

There is **no source CAD** — only meshes. Everything in §2 was recovered by
slicing and curve-fitting the two STLs. Both files carry the same binary header
string `MW 1.0 2178594 US`, which tells us nothing useful about the authoring
tool. All recovered numbers are quoted with the mesh noise floor in mind
(≈ 0.1–0.2 mm); see §7.1.

The text visible on the male plate in the render is a **slicer object label
overlay, not geometry** — the mesh has no engraving (verified: single closed
loop at every Z through the base plate).

---

## 2. How the existing mold is constructed

### 2.1 Shared coordinate system

Both STLs are exported **in assembly position**, not print position:

| | Z range | thickness |
|---|---|---|
| male base plate | 10 → 25 | 15 mm |
| male plug | 25 → 50 | 25 mm |
| female plate | 25 → 50 | 25 mm |

The parting plane is `z = 25`. The plug top and the female top are **coplanar at
`z = 50`**. Closed stack height = 40 mm. Both plates share the identical
235 × 165 mm outline, so they stack flush.

Recommended canonical frame for the new model: origin at the plan centre **on
the parting plane**, `+Z` = plug direction. (`z_new = z_ref − 25`.)

### 2.2 Plan profile — an obround with *parabolic*, not circular, corners

This is the single most important finding.

The plug cross-section is constant `175.000 × 105.000` mm between `z = 26.2` and
`z = 45.0`. It has a **70 mm straight run** on each long side and **no straight
run at all** on the short ends — i.e. the corner blend consumes the entire
half-width (setback = 52.5 mm = width / 2). That is the shape of a stadium /
obround.

But it is *not* a stadium. Measured plan area is **16 573 mm²** against
**16 009 mm²** for a true circular stadium of the same bounding box, and the
measured perimeter (481.5 mm) exceeds the circular one (469.9 mm) — impossible
for a faceted approximation of a circle, which always undershoots.

Fitting curve families to the first-quadrant outline (143 sampled points):

| corner model | RMS deviation | max deviation |
|---|---|---|
| circular arc, R = 52.5 | **2.263 mm** | 3.185 mm |
| cubic Bézier, best `k` = 1.195 | 0.355 mm | 0.650 mm |
| conic, best `w` = 1.010 (ρ = 0.502) | **0.116 mm** | 0.207 mm |
| quadratic Bézier / parabola (w = 1, ρ = 0.5) | 0.127 mm | 0.227 mm |

The corner is a **conic section with ρ = 0.5, i.e. a parabola / quadratic
Bézier**, whose control polygon is the sharp rectangle corner:

```
P0 = (L/2, W/2 − s)     P1 = (L/2, W/2)     P2 = (L/2 − s, W/2)
with s = corner setback = 52.5 mm
```

The residual 0.12 mm rms is mesh tessellation, not model error. The identical
fit holds for the female cavity (`w = 0.990`, rms 0.124 mm).

Consequence: the corner has **continuously varying curvature**, not a constant
radius:

| position on the corner | radius of curvature |
|---|---|
| tangent points (t = 0 and t = 1) | `2s` = 105 mm |
| 45° apex (t = 0.5) | `s/√2` = 37.1 mm |
| equivalent circular arc | 52.5 mm |

This is a G2-continuous blend — genuinely nicer for leather than a circular
fillet, because curvature does not jump at the tangent point where stress
concentrates. It is also the main reproduction hazard (§7.2), and it sets a hard
ceiling on every downstream 3D fillet: **no blend radius may exceed `s/√2`.**

### 2.3 Male half ("plug" / punch)

```
base plate   235 × 165 × 15 mm, sharp corners in plan (r = 0), sharp edges,
             no holes, no notches, no engraving
plug         obround profile 175 × 105, extruded z = 25 → 50 (25 mm)
draft        0.000° — walls exactly vertical, x = ±87.500 over z ∈ [26.2, 45.0]
root fillet  circular R 1.2 mm where the plug meets the plate
             (verified circular to 1e-4: centre (88.700, 26.200))
top edge     PARABOLIC blend, 5 mm setback, z = 45 → 50
             control polygon (87.5,45) → (87.5,50) → (82.5,50);
             predicted midpoint (86.250, 48.750) matches the mesh exactly
top face     flat at z = 50, ≈ 165 × 95 (setback 47.5)
volume       994.2 cm³
```

Note the mixed vocabulary: the **root fillet is a true circular arc**, while the
**top edge blend is parabolic**. Both must be expressible.

### 2.4 Female half (die / cavity plate)

```
plate        235 × 165 × 25 mm, sharp edges
cavity       THROUGH opening, obround 181 × 111, same parabolic corner rule
             (setback 55.5 = width/2, 70 mm straight run)
draft        0.000° — vertical from z = 25 to z = 47
top rim      PARABOLIC blend, 3 mm setback, z = 47 → 50
             predicted midpoint (91.250, 49.250) matches the mesh exactly
bottom edge  SHARP (no break at z = 25)
clamp holes  2 × Ø6.000 through, centres (−102.5, +67.5) and (+102.5, −67.5)
             → 15 mm in from both edges, one diagonal only
             2 mm × 45° chamfer on the top face (Ø6 at z=48 → Ø10 at z=50)
pry notches  2 × 15 × 15 mm corner rebates at (+117.5,+82.5) and (−117.5,−82.5)
             → the *other* diagonal, cut 8 mm down from the top (z = 42 → 50)
volume       512.4 cm³
```

The part has **C2 rotational symmetry, not mirror symmetry**: holes on one
diagonal, notches on the other.

### 2.5 The relationships that actually matter

| relationship | value | why it matters |
|---|---|---|
| cavity − plug, per side | **exactly 3.000 mm** everywhere (181 = 175+6, 111 = 105+6) | this is the leather + clearance gap |
| cavity profile generation | same construction re-run with `L+2g, W+2g, s+g` — **not** a geometric offset | reproduces to ~0.18 mm; a true offset of a parabola is not a parabola |
| plug height == female plate thickness | 25 mm == 25 mm | the flush top is deliberate |
| male flange 30 mm, female flange 27 mm | 30 − 3 = 27 | there is **one** flange parameter; the 3 mm difference is just the gap |
| plate outline | identical 235 × 165 for both halves | derived: `tray + 2 × flange`, shared |
| nominal "4 × 7" | 105 × 175 mm = 4.13″ × 6.89″, depth 25 mm ≈ 1″ | the name refers to the *inner* tray size |

**Dimensional datum.** The plug is the tray's **inner** surface; the cavity is
the tray's **outer** surface. So `length / width / depth` in the reference are
inner dimensions. The UI must state this, and should offer an `inner | outer`
datum switch, because "I want a 7-inch tray" is ambiguous by ±2 × leather.

**Registration is loose.** The two Ø6 holes exist **only in the female** — the
male plate is a plain slab. Nothing locates the halves except the plug inside
the cavity, which has 3 mm of slop until the leather fills it. The user's
requested "alignment pins" feature is a genuine improvement, not decoration.

**There is no leather relief at the flange or the floor.** In the closed
position the female's bottom face lands directly on the male's plate top, and
the plug tip reaches the female's bottom plane — both with zero allowance for
the leather that has to be there. In practice the wet flange is crushed and then
trimmed. The parametric model should make this explicit and optional
(`flange_relief`, `stop_offset`) rather than inheriting it silently.

**Usage orientation is ambiguous from geometry alone.** The blended rim (3 mm) is
on the female's *top* face together with the notches and hole chamfers. Two
readings are consistent with the mesh: (a) the female is flipped so its blended
edge faces the male plate and acts as the draw-die entry radius; (b) the female
sits blend-up on a bench, leather is laid over the opening, and the male is
pressed down into it. Both are supported by the same solid. The new model should
parameterise the entry radius on *both* faces of the cavity rather than
hard-coding one, and document the closed-position stack explicitly.

---

## 3. What should become a parameter

Summarised here; specified in [`parameter-model.md`](./parameter-model.md).

| group | reference value | parameter |
|---|---|---|
| shape family | obround | `tray.profile` (discriminated union) |
| plan size | 175 × 105 | `tray.length`, `tray.width` |
| draw depth | 25 | `tray.depth` |
| corner blend | setback 52.5 = W/2, conic ρ 0.5 | `tray.corner_radius`, `corner_style`, `corner_rho` |
| tray floor blend | 5 mm parabolic (plug top) | `tray.floor_radius` (+ style) |
| tray rim blend | 3 mm parabolic (cavity top) | `tray.rim_radius` (+ style) |
| forming gap | 3.0 mm/side | derived from `leather.thickness`, `leather.compression`, `fit.clearance` |
| draft | 0° | `tray.draft_angle` |
| plug root fillet | circular R1.2 | `mold.plug_root_fillet` |
| flange | 30 mm (male datum) | `mold.flange_width` |
| plate thicknesses | 15 / 25 | `mold.base_plate_thickness`, `mold.cavity_plate_thickness` |
| clamp holes | 2 × Ø6, inset 15, 2×45° csk, female only | `features.clamp_holes.*` |
| pry notches | 2 × 15×15×8 deep | `features.pry_notches.*` |
| alignment pins | *absent* | `features.alignment_pins.*` (new) |
| vents / drains | *absent* | `features.vents.*` (new) |
| label engraving | *absent* | `features.label.*` (new) |

Explicitly **not** parameters: anything the geometry can compute
(cavity dimensions, plate outline, closed height, volumes) — see
[`parameter-model.md` §4](./parameter-model.md#4-derived-quantities).

---

## 4. Architecture

### 4.1 The one rule

> **All geometry is produced by one deterministic function
> `build(params: MoldParams) -> MoldResult` inside a pure Python package.
> Nothing else in the system knows what a fillet is.**

The API is a transport for that function. The UI is a form and a mesh viewer.
The CLI is the same function with a different front door. If a number needs to
be computed from other numbers, it is computed in the core and travels outward.

### 4.2 Layout

```
packages/
  tray-core/                      pure Python. No web dependencies.
    traymold/
      params.py       Pydantic v2 models — the single schema definition
      profiles.py     2D plan profiles (obround / rounded-rect / ellipse /
                      superellipse), circular + conic corner construction
      sections.py     vertical section rules (root fillet, floor blend,
                      rim blend, draft) as z → profile functions
      mold.py         build_male(), build_female(), build_assembly()
      validate.py     cross-field rules → list[Diagnostic] (codes, not prose)
      derive.py       derived quantities (cavity dims, volumes, closed height…)
      tessellate.py   OCC mesh → indexed triangles, fixed tolerances
      exporters.py    STL / 3MF / STEP / GLB
      presets.py      named starting points, incl. `ref-4x7`
      version.py      MODEL_VERSION — participates in every cache key
      cli.py          traymold build|validate|schema
    tests/
      test_reference_fidelity.py  golden: rebuild ref-4x7, compare to the STLs
      test_validation.py          one test per diagnostic code
      test_determinism.py         same params twice → identical bytes
  api/                            FastAPI. Thin.
    app/{main,routes,jobs,cache,schema_export}.py
  web/                            React + TS + R3F. No CAD logic.
    src/schema/generated.ts       generated from the Pydantic JSON Schema
tools/
  reference_probe/                mesh slicer + curve fitter used for §2
docs/
```

### 4.3 Schema flows one way

`params.py` (Pydantic v2) → JSON Schema → `web/src/schema/generated.ts`.

Generated types are **committed** and CI fails if regeneration produces a diff.
The UI form is *driven* by the JSON Schema plus a small `ui_hints` sidecar
(group, order, unit, step, widget), so adding a parameter is a core-only change.
The UI never hand-writes a parameter list.

Client-side validation is limited to what JSON Schema can express (types, ranges,
enums). **Every cross-field rule lives in `validate.py`** and is reachable via
`POST /validate`, so the UI cannot disagree with the kernel.

### 4.4 API surface

| endpoint | purpose |
|---|---|
| `GET  /api/schema` | JSON Schema + `ui_hints` + defaults |
| `GET  /api/presets` | named starting points |
| `POST /api/validate` | `{diagnostics[], derived{}}` — cheap, no geometry |
| `POST /api/preview` | → job; result is a GLB at preview tolerance |
| `POST /api/export` | → job; STL / 3MF / STEP, one part or a zip |
| `GET  /api/jobs/{id}` | status / result links |
| `GET  /api/version` | `MODEL_VERSION` + pinned kernel versions |

`POST /validate` must be fast and geometry-free so the UI can call it on every
keystroke; `preview` is debounced and cancellable.

### 4.5 Execution model

OCC (the kernel under CadQuery) is **not thread-safe**, leaks, and can hard-crash
the process on a bad boolean. Therefore:

- builds run in a **process pool**, one build per worker, workers recycled after
  N jobs and killed on timeout;
- a crashed worker becomes a diagnostic, never a 500 with a stack trace;
- never call CadQuery on the FastAPI event loop.

### 4.6 Determinism and caching

`params_hash = sha256(canonical_json(params) || MODEL_VERSION || KERNEL_VERSIONS)`

keys a content-addressed artifact store. Same params → byte-identical STL.
Requires: canonical JSON (sorted keys, fixed float formatting, no `NaN`), pinned
`cadquery`/`OCP` versions, fixed tessellation tolerances, and no dependence on
time, randomness or dict iteration order. `test_determinism.py` enforces it.

This also gives a free permalink: the URL carries base64 params, so any design a
user shows a colleague rebuilds bit-for-bit.

### 4.7 Preview is the same geometry

The GLB the viewer renders comes from **the same `build()` call** as the export,
tessellated at a coarser tolerance. There is no second, simplified model. Two
presets only: `preview` (≈0.25 mm linear) and `export` (≈0.05 mm linear).

Viewer responsibilities (R3F): male / female / assembly toggle, exploded and
"closing" animation along Z, a section plane, dimension overlay, and a
printability box showing the plates against the configured bed. All of these read
values the core computed; none of them recompute geometry.

---

## 5. Staged implementation plan

Each stage ends with something runnable and tested.

**Stage 0 — reverse-engineering harness.**
Commit `tools/reference_probe/` (the slicer and curve fitter behind §2) and a
`reference/measured.json` fixture holding every number in §2.3–2.5. This becomes
the oracle for Stage 2.

**Stage 1 — simplest working parametric mold, CLI only.**
`length, width, depth, corner_radius, gap, flange_width, plate thicknesses`.
Circular corners, zero draft, no blends, no features. `build_male` / `build_female`,
STL out. Test: bounding boxes and cross-section areas match the reference within
the circular-corner error budget. *No API, no UI.*

**Stage 2 — fidelity.**
Root fillet, floor blend, rim blend, and the conic (ρ) corner style. Target:
rebuild `ref-4x7` to within 0.2 mm of both reference STLs (sampled Hausdorff).
This is the stage that proves the geometry strategy in §7 works.

**Stage 3 — validation and derived values.**
`validate.py` with the full rule table, one unit test per code; `derive.py` with
volumes, closed height, minimum wall, filament estimate, bed fit. Still CLI-only.

**Stage 4 — draft and manufacturing features.**
Draft via profile lofting (§7.3). Alignment pins/holes, clamp holes, pry notches,
vents, label engraving, flange relief. Feature placement diagnostics.

**Stage 5 — FastAPI.**
Process pool, job queue, cache, schema export, STL/3MF/STEP. Contract tests:
schema snapshot, determinism, worker-crash handling.

**Stage 6 — UI shell.**
Schema-driven form + R3F preview + downloads. Debounce, cancellation,
diagnostics rendered inline against the offending field.

**Stage 7 — polish.**
Presets, mm/inch display toggle (core stays mm), leather-weight → thickness
helper (oz → mm), printability warnings, exploded/closing animation, permalinks.

**Stage 8 — optional breadth.**
More profile families (ellipse, superellipse, true rounded-rect with small radii),
multi-cavity plates, keyed registration ribs, ribbed/hollowed plates to cut the
~1 kg of filament the current 994 cm³ male implies.

The user-visible feature list is complete at the end of Stage 6; Stages 7–8 are
quality.

---

## 6. Testing strategy

- **Golden fidelity** (Stage 2 onward): rebuild `ref-4x7`, sample points on the
  generated mesh, assert max distance to the reference STL < 0.2 mm.
- **Invariants, not snapshots**, for parametric sweeps: for random valid params
  assert the solids are closed and manifold, `volume(male) > 0`, the plug fits
  the cavity with the intended gap (measured by slicing, the same probe code as
  Stage 0), and no self-intersection.
- **One test per diagnostic code**, asserting the code fires and that the build
  is refused.
- **Determinism**: build twice in separate processes, compare hashes.
- **Property test on the gap**: for any valid params, the minimum plug↔cavity
  distance over the wall height equals the computed gap ± 0.05 mm.

---

## 7. Fragile / hard-to-reproduce areas

Ranked by risk.

### 7.1 There is no source CAD
Everything is inferred from meshes. Numbers like `1.2 mm` root fillet or `2 mm`
chamfer are measured to ~0.01 mm but the *intent* (1.2 vs 1.25) is unknowable.
Record measured-vs-assumed in `reference/measured.json` and treat the reference
as a target, not a specification.

### 7.2 Parabolic corners have no native CadQuery operation
CadQuery/OCC gives circular `fillet()`. Reproducing §2.2 requires building the
profile from explicit conic/Bézier edges (`Edge.makeBezier`, or
`Workplane.spline` with tangent constraints). That is easy; what is *not* easy is
everything downstream — OCC blend and offset operations are markedly less robust
on B-spline edges than on lines and arcs.

Mitigations, in order of preference:
1. Offer `corner_style = circular` as the **default** and `conic` as
   "reference-accurate"; the circular path stays on OCC's happy path.
2. Never `offset2D` a spline profile — generate the cavity profile
   parametrically (`L+2g, W+2g, s+g`), exactly as the original does. Keep
   `offset2D` as a fallback only.
3. Prefer lofting between analytically-computed z-profiles over 3D `fillet()`
   on spline-cornered solids (§7.3).

Be explicit with users: a circular-corner rebuild of `ref-4x7` differs from the
reference by up to **3.2 mm** at the 45° point and **3.5 %** in plan area. That
is a visible difference, not a rounding error.

### 7.3 Blends, draft and 3D fillets on splined solids
`extrude(taper=)` and `fillet()` are the two operations most likely to fail or
silently produce garbage on a spline-cornered prism. The robust alternative is to
express the plug and the cavity as a **stack of z-parameterised 2D profiles** —
draft, root fillet and floor/rim blend all reduce to "what is the profile offset
at height z" — and `loft` through them. That is deterministic, never throws, and
handles draft + blend + conic corners uniformly. Cost: the lofted surface is a
spline approximation rather than an exact torus, and profile count becomes a
tessellation-quality knob.

Decide this in Stage 2 and stick to it; mixing the two approaches is how these
projects become unmaintainable.

### 7.4 Blend radius vs local curvature
Any 3D blend must satisfy `radius < s/√2` (37.1 mm for the reference). Exceeding
it produces an OCC failure or a self-intersecting face, not a clamped result.
This must be a *validation rule*, not a caught exception.

### 7.5 The gap is not exactly uniform
Because the cavity is generated parametrically rather than offset, the plug↔cavity
distance is 3.000 mm on the straight runs and at the apex, but ≈3.18 mm through
the 45° region — a 6 % variation. Reproduce the behaviour (matching the original)
and report the *actual* min/max gap as a derived value, rather than claiming a
single number.

### 7.6 Mesh export determinism
`BRepMesh_IncrementalMesh` output depends on the OCC version and on tolerance.
Pin exact versions, record them in the export metadata, and ship **3MF alongside
STL** — STL is unitless and slicers have been known to guess wrong on
inch-authored files. STEP is straightforward from CadQuery
(`cq.exporters.export(..., "STEP")`); 3MF is not native and needs `lib3mf` or
`trimesh` on the tessellated result — treat that as a real dependency decision,
not an afterthought.

### 7.7 Print cost explodes quietly
The reference male is **994 cm³** solid. A user typing "300 × 200 × 60" more than
triples that. Surface a filament/volume/print-envelope estimate next to the
preview from Stage 3, before anyone spends a spool.

### 7.8 Closed-position semantics
§2.5 — the reference has no flange relief and no floor stop, and its usage
orientation is ambiguous. Do not silently inherit that. Model the closed stack
explicitly (`flange_relief`, `stop_offset`, entry radius on both cavity faces),
default the values to the reference's behaviour, and document what each does.

### 7.9 Two clearances that look alike
The leather gap (3 mm, a *forming* quantity) and the alignment-pin fit clearance
(0.15–0.3 mm, a *printer* quantity) are different in kind. Keep them in separate
namespaces (`leather`/`fit` vs `manufacturing`) so a user tuning their printer
never perturbs the tray dimensions.
