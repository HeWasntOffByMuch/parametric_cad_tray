# Parametric Leather-Tray Wet-Mold Generator — Architecture

Status: **design proposal, nothing implemented yet.**
Scope: turn the `4x7` wet-mold pair in `reference/` into a parametric CAD
application (CadQuery core → FastAPI → React/R3F UI).

Companion document: [`parameter-model.md`](./parameter-model.md) — the parameter
schema, dependencies and validation rules in detail.

> **Revision note.** An earlier draft of this document reconstructed the geometry
> from the STL meshes alone and concluded the corner blends were conic (ρ = 0.5)
> and that the forming gap varied between 3.00 and 3.18 mm. The STEP files
> supersede that. Both conclusions were wrong; §2.2 and §2.5 now carry the exact
> B-rep answers, and §7 changes accordingly.

---

## 1. What is in the repository

```
reference/
  male_tray_mold.step         AP242, 25 faces  — authoritative
  female_tray_mold.step       AP242, 18 faces  — authoritative
  4x7-male-wetmold.stl        binary STL, 26 738 tris
  4x7-female-wetmold.stl      binary STL, 37 626 tris
  reference_render_preview.webp   slicer screenshot
  reference_real_picture.webp     photo of the printed parts
```

The STEP files are AP242 exports from **Onshape** (`ONSHAPE BY PTC INC, 1.220`,
via ST-DEVELOPER v20, source document "Part Studio 2"), in **metres**. They carry
exact NURBS geometry, so §2 below is measured, not inferred.

**The STEP pair is an earlier revision than the STL pair.** The STEP female has
**no clamp holes and no pry notches**; its plate side faces are full area
(5875 = 235 × 25 and 4125 = 165 × 25). Cutting the STL's two chamfered Ø6 holes
and two 15 × 15 × 8 notches out of the STEP female gives 512.684 cm³ against the
STL's 512.392 cm³ — a 0.06 % residual, i.e. meshing noise. The two males are the
same part (993.796 cm³ exact vs 994.155 cm³ faceted).

So: **take the shape from the STEP, take the manufacturing features from the
STL.** Neither file alone is the whole design.

The text visible on the male plate in the render is a **slicer object-label
overlay, not geometry** — neither the mesh nor the B-rep has any engraving.

---

## 2. How the existing mold is constructed

### 2.1 Shared coordinate system

Both files are in **assembly position**, not print position:

| | Z range | thickness |
|---|---|---|
| male base plate | 10 → 25 | 15 mm |
| male plug | 25 → 50 | 25 mm |
| female plate | 25 → 50 | 25 mm |

Parting plane `z = 25`; the plug top and the female top are coplanar at `z = 50`;
closed stack height 40 mm. Both plates share an identical 235 × 165 mm outline.

Canonical frame for the new model: origin at the plan centre **on the parting
plane**, `+Z` = plug direction (`z_new = z_ref − 25`).

### 2.2 The corner blend — one G2 quintic, used everywhere

This is the central finding, and it is exactly recoverable.

The plug's plan profile is a 175 × 105 rectangle with a 70 mm straight run on each
long side and no straight run at all on the short ends — the blend consumes the
entire half-width (setback `s` = 52.5 = W/2). The blend faces are
`B_SPLINE_SURFACE deg=(5,1)`, 8 × 2 poles, **non-rational** — a degree-5
polynomial curve extruded linearly. Non-rational rules out conics entirely.

Reading the control points straight out of the STEP and normalising them (corner
at the origin, start at `(−1,0)·s`, end at `(0,1)·s`):

```
degree 5, non-rational
knots  [0,0,0,0,0,0, ½,½, 1,1,1,1,1,1]      → two quintic Bézier spans, C3 at the join
poles  (−1,   0   )
       (−0.85,0   )
       (−0.70,0   )
       (−1/3, 0.10)
       (−0.10,1/3 )
       ( 0,   0.70)
       ( 0,   0.85)
       ( 0,   1   )
```

The polygon is symmetric under `(a,b) → (−b,−a)`, and the three collinear poles at
each end make the **curvature exactly zero at both tangent points** — a true G2
join to the straight edges, not the G1 join a circular fillet gives.

| property | this blend | circular arc r=s | parabola (conic ρ=0.5) |
|---|---|---|---|
| radius of curvature at the tangent points | **∞** | `s` | `2s` |
| minimum radius of curvature (at mid-blend) | **0.72184 · s** | `s` | `s/√2` |
| corner area removed | **0.163338 · s²** | 0.214602 · s² | 0.166667 · s² |

Verification at `s = 52.5`:

| | plan area at z = 35 |
|---|---|
| sharp 175 × 105 rectangle | 18 375.00 mm² |
| circular-arc obround, same bbox | 16 009.01 mm² |
| parabola | 16 537.50 mm² |
| **analytic template** | **16 574.20 mm²** |
| **exact, sectioned from the STEP** | **16 574.19 mm²** |
| measured from the STL | 16 573.16 mm² |

Minimum radius of curvature at `s = 52.5` is **37.90 mm**, against a constant
52.50 mm for a circular fillet.

**The same normalised template is used for the vertical edge blends**, verified
pole-by-pole:

| blend | face | setback | poles match template |
|---|---|---|---|
| plug plan corner | male F15–F18, deg (5,1) | 52.5 | yes — 11 µm max over a sectioned check |
| plug top edge (tray floor) | male F19/F24, deg (5,1) | 5.0 | yes — exact to 4 dp |
| cavity top rim | female F12/F17, deg (5,1) | 3.0 | yes — exact to 4 dp |

One blend primitive, three setbacks. That is the design language of the whole
model, and it means the geometry is **reproducible exactly**, not approximately.

Why the earlier mesh-only reading said "parabola": the template sits within
0.00434 · s of a quadratic Bézier — 0.23 mm at s = 52.5, which is the residual the
STL fit showed. Positionally almost the same curve; in curvature terms a
completely different one (∞ vs 2s at the tangent points). Fitting positions to a
mesh cannot distinguish them. **Curvature is what the leather feels**, so this
distinction is the whole point of the blend.

### 2.3 Male half — exact B-rep

```
25 faces: 9 PLANE, 2 CYLINDER, 14 B_SPLINE_SURFACE
54 edges: 16 LINE, 6 CIRCLE, 32 B_SPLINE
volume 993.796 cm³

base plate   235 × 165 × 15 (z 10→25), all planar, sharp, NO holes, NO notches
plug         plan profile per §2.2, 175 × 105, z 25 → 50
draft        0.000° exactly — the straight walls are PLANE faces at y = ±52.5,
             x ∈ [−35,35], z ∈ [26.2, 45.0]  (area 1316 = 70 × 18.8)
root fillet  TRUE CIRCULAR R1.2 rolling-ball fillet:
               CYLINDER faces d = 2.4 on the two straight runs
               (axis ±X, at y = ±53.7, z = 26.2)
               rational-quadratic (= exact circular section) sweeps at the corners
top edge     G2 template, setback 5.0, z 45 → 50
top face     PLANE at z = 50, 165 × 95 bbox, area 14 167.56 mm²
```

Note the deliberate mixed vocabulary: the **root fillet is a genuine constant-radius
circular fillet**, while every other blend is the G2 quintic. Both must be
expressible.

### 2.4 Female half — exact B-rep

```
18 faces: 8 PLANE, 10 B_SPLINE_SURFACE  (no cylinders → no holes in this revision)
42 edges: 14 LINE, 28 B_SPLINE
volume 517.830 cm³ as exported

plate        235 × 165 × 25 (z 25→50), sharp; side faces full area
cavity       THROUGH opening, 181.0032 × 111.0032, plan area 18 046.91 mm²
draft        0.000° — straight walls are PLANE at y = ±55.5, z ∈ [25,47]
                        (area 1540 = 70 × 22)
top rim      G2 template, setback 3.0, z 47 → 50
bottom edge  SHARP at z = 25
```

Features present in the **STL revision only** (add these back):

```
clamp holes  2 × Ø6.000 through, at (−102.5, +67.5) and (+102.5, −67.5)
             → 15 mm in from both edges, one diagonal
             2 mm × 45° chamfer on the top face (Ø6 at z=48 → Ø10 at z=50)
pry notches  2 × 15 × 15 mm corner rebates at (+117.5,+82.5) and (−117.5,−82.5)
             → the OTHER diagonal, cut 8 mm down from the top (z 42 → 50)
```

The featured part has **C2 rotational symmetry, not mirror symmetry**.

### 2.5 The relationships that actually matter

| relationship | value | why it matters |
|---|---|---|
| **cavity ↔ plug distance** | **exactly 3.000 mm** (measured min 2.998 / max 3.003 over 3600 sampled points — sampling noise) | the cavity is a **true geometric offset** of the plug, not a re-parameterised profile |
| cavity plan bbox | 181.0032 × 111.0032, not 181 × 111 | the offset was approximated to ~1.6 µm; an exact offset of a quintic is not a quintic |
| cavity corner vs the template at s = 55.5 | differs by up to **182 µm** | confirms offset, not re-parameterisation |
| cavity wall surface type | deg (3,3), 13 × 4 poles | an *approximated* surface, unlike the plug's exact deg (5,1) extrusion |
| plug height == female plate thickness | 25 mm == 25 mm | the flush top is deliberate |
| male flange 30 mm, female flange 27 mm | 30 − 3 = 27 | one flange parameter; the difference is just the gap |
| plate outline | identical 235 × 165 for both halves | derived: `tray + 2 × flange` |
| nominal "4 × 7" | 105 × 175 mm = 4.13″ × 6.89″, depth 25 mm ≈ 1″ | the name refers to the *inner* tray size |

**Dimensional datum.** The plug is the tray's **inner** surface; the cavity is the
tray's **outer** surface. `length / width / depth` in the reference are therefore
inner dimensions. The UI must say so and should offer an `inner | outer` switch —
"a 7-inch tray" is ambiguous by ±2 × leather thickness.

**Registration is loose.** The two Ø6 holes exist only in the female (and only in
the later revision); the male plate is a plain slab in both files. Nothing locates
the halves but the plug inside the cavity, which has 3 mm of slop until leather
fills it. The requested alignment-pin feature is a genuine improvement.

**No leather relief at the flange or the floor.** Closed, the female's bottom face
lands directly on the male's plate top and the plug tip reaches the female's bottom
plane — both with zero allowance for the leather that has to be there. In practice
the wet flange is crushed and trimmed. Make this explicit and optional
(`flange_relief`, `stop_offset`) rather than inheriting it silently.

**Usage orientation is ambiguous from geometry alone.** The blended rim (3 mm) is
on the female's *top* face, together with the notches and hole chamfers. Two
readings fit the solid: (a) the female is flipped so its blended edge faces the male
plate and acts as the draw-die entry radius; (b) the female sits blend-up and the
male is pressed down into it. Parameterise the entry radius on *both* faces rather
than hard-coding one.

---

## 3. What should become a parameter

Summarised here; specified in [`parameter-model.md`](./parameter-model.md).

| group | reference value | parameter |
|---|---|---|
| shape family | obround | `tray.profile` (discriminated union) |
| plan size | 175 × 105 | `tray.length`, `tray.width` |
| draw depth | 25 | `tray.depth` |
| corner blend | setback 52.5 = W/2, **G2 quintic template** | `tray.corner_radius`, `corner_style` |
| tray floor blend | G2 quintic, setback 5 | `tray.floor_radius` (+ style) |
| tray rim blend | G2 quintic, setback 3 | `mold.cavity_entry_radius_top` (+ style) |
| forming gap | 3.0 mm, **true offset** | derived from `leather.thickness`, `leather.compression`, `fit.clearance` |
| draft | 0° | `tray.draft_angle` |
| plug root fillet | **circular** R1.2 | `mold.plug_root_fillet` |
| flange | 30 mm (male datum) | `mold.flange_width` |
| plate thicknesses | 15 / 25 | `mold.base_plate_thickness`, `mold.cavity_plate_thickness` |
| clamp holes | 2 × Ø6, inset 15, 2×45° csk, female only | `features.clamp_holes.*` |
| pry notches | 2 × 15 × 15 × 8 deep | `features.pry_notches.*` |
| alignment pins | *absent* | `features.alignment_pins.*` (new) |
| vents / drains | *absent* | `features.vents.*` (new) |
| label engraving | *absent* | `features.label.*` (new) |

Explicitly **not** parameters: anything derivable (cavity dimensions, plate
outline, closed height, volumes) — see
[`parameter-model.md` §4](./parameter-model.md#4-derived-quantities).

---

## 4. Architecture

### 4.1 The one rule

> **All geometry is produced by one deterministic function
> `build(params: MoldParams) -> MoldResult` inside a pure Python package.
> Nothing else in the system knows what a fillet is.**

The API is a transport for that function; the UI is a form and a mesh viewer; the
CLI is the same function with a different front door.

### 4.2 Layout

```
packages/
  tray-core/                      pure Python. No web dependencies.
    traymold/
      params.py       Pydantic v2 models — the single schema definition
      blends.py       the G2 quintic template (§2.2) + circular blend helpers
      profiles.py     2D plan profiles (obround / rounded-rect / ellipse /
                      superellipse) built from blends.py
      sections.py     z → profile rules (root fillet, floor blend, rim blend, draft)
      mold.py         build_male(), build_female(), build_assembly()
      validate.py     cross-field rules → list[Diagnostic] (codes, not prose)
      derive.py       derived quantities
      tessellate.py   OCC mesh → indexed triangles, fixed tolerances
      exporters.py    STL / 3MF / STEP / GLB
      presets.py      named starting points, incl. `ref-4x7`
      version.py      MODEL_VERSION — participates in every cache key
      cli.py          traymold build|validate|schema
    tests/
      test_reference_fidelity.py  rebuild ref-4x7, compare to the STEP B-rep
      test_blend_template.py      poles/curvature/area of the G2 template
      test_validation.py          one test per diagnostic code
      test_determinism.py         same params twice → identical bytes
  api/                            FastAPI. Thin.
    app/{main,routes,jobs,cache,schema_export}.py
  web/                            React + TS + R3F. No CAD logic.
    src/schema/generated.ts       generated from the Pydantic JSON Schema
tools/
  reference_probe/                STEP/STL analysis used for §2
docs/
```

### 4.3 Schema flows one way

`params.py` (Pydantic v2) → JSON Schema → `web/src/schema/generated.ts`.
Generated types are committed; CI fails if regeneration produces a diff. The UI
form is driven by the JSON Schema plus a small `ui_hints` sidecar, so adding a
parameter is a core-only change.

Client-side validation is limited to what JSON Schema expresses (types, ranges,
enums). **Every cross-field rule lives in `validate.py`** and is reachable via
`POST /validate`, so the UI cannot disagree with the kernel.

### 4.4 API surface

| endpoint | purpose |
|---|---|
| `GET  /api/schema` | JSON Schema + `ui_hints` + defaults |
| `GET  /api/presets` | named starting points |
| `POST /api/validate` | `{diagnostics[], derived{}}` — cheap, no geometry |
| `POST /api/preview` | → job; GLB at preview tolerance |
| `POST /api/export` | → job; STL / 3MF / STEP, one part or a zip |
| `GET  /api/jobs/{id}` | status / result links |
| `GET  /api/version` | `MODEL_VERSION` + pinned kernel versions |

`/validate` must be geometry-free so the UI can call it on every keystroke;
`/preview` is debounced and cancellable.

### 4.5 Execution model

OCC is not thread-safe, leaks, and can hard-crash the process on a bad boolean or
offset. Therefore builds run in a **process pool**, one build per worker, workers
recycled after N jobs and killed on timeout; a crashed worker becomes a
diagnostic, never a 500. Never call CadQuery on the event loop.

### 4.6 Determinism and caching

`params_hash = sha256(canonical_json(params) || MODEL_VERSION || KERNEL_VERSIONS)`
keys a content-addressed artifact store. Same params → byte-identical STL.
Requires canonical JSON, pinned `cadquery`/`OCP`, fixed tessellation tolerances,
and no dependence on time, randomness or dict order. `test_determinism.py`
enforces it. It also gives a free permalink: the URL carries base64 params.

### 4.7 Preview is the same geometry

The GLB the viewer renders comes from the **same `build()` call** as the export,
tessellated coarser. Two presets only: `preview` (≈0.25 mm) and `export`
(≈0.05 mm). Viewer duties (R3F): male/female/assembly toggle, exploded and
closing animation, section plane, dimension overlay, printability box. All read
core-computed values; none recompute geometry.

---

## 5. Staged implementation plan

**Stage 0 — reverse-engineering harness.** Commit `tools/reference_probe/` (the
STEP/STL analysis behind §2) and `reference/measured.json` holding every number in
§2.2–2.5. This is the oracle for Stage 2.

**Stage 1 — simplest working parametric mold, CLI only.**
`length, width, depth, corner_radius, gap, flange_width, plate thicknesses`.
Circular corners, zero draft, no blends, no features. STL out. Test bounding boxes
and cross-section areas against the circular-corner error budget. No API, no UI.

**Stage 2 — fidelity.** The G2 quintic template, root fillet, floor blend, rim
blend, and the cavity as a **true offset**. Target: rebuild `ref-4x7` to within
0.05 mm of the STEP B-rep (not the STL — we have exact geometry, so hold the
tolerance an order of magnitude tighter than the earlier plan assumed). Add
`test_blend_template.py` asserting endpoint curvature = 0, min radius = 0.72184·s
and removed area = 0.163338·s².

**Stage 3 — validation and derived values.** `validate.py` with the full rule
table, one unit test per code; `derive.py` with volumes, closed height, minimum
wall, filament estimate, bed fit. Still CLI-only.

**Stage 4 — draft and manufacturing features.** Draft, alignment pins/holes, clamp
holes, pry notches, vents, label engraving, flange relief. This is where the
STL-only features come back in.

**Stage 5 — FastAPI.** Process pool, jobs, cache, schema export, STL/3MF/STEP.
Contract tests: schema snapshot, determinism, worker-crash handling.

**Stage 6 — UI shell.** Schema-driven form + R3F preview + downloads. Debounce,
cancellation, diagnostics rendered against the offending field.

**Stage 7 — polish.** Presets, mm/inch display toggle (core stays mm), leather
weight → thickness helper, printability warnings, exploded/closing animation,
permalinks.

**Stage 8 — optional breadth.** More profile families, multi-cavity plates, keyed
registration ribs, ribbed/hollowed plates to cut the ~1 kg of filament the
993.8 cm³ male implies.

The user-visible feature list is complete at the end of Stage 6.

---

## 6. Testing strategy

- **Golden fidelity**: rebuild `ref-4x7` and compare against the **STEP solids**
  with `BRepExtrema_DistShapeShape`, not against the meshes. Target 0.05 mm.
- **Blend template unit tests**: poles, knot vector, zero endpoint curvature,
  `min radius = 0.72184 s`, `removed area = 0.163338 s²`.
- **Gap property test**: for any valid params, the minimum plug↔cavity distance
  equals `gap` within 0.01 mm — the reference achieves 3.000 ± 0.003, so this is a
  real, tight invariant, not a loose one.
- **Invariants over snapshots** for parametric sweeps: closed, manifold,
  positive volume, no self-intersection.
- **One test per diagnostic code.**
- **Determinism**: build twice in separate processes, compare hashes.

---

## 7. Fragile / hard-to-reproduce areas

Ranked by risk. This section changed substantially once the STEP files arrived —
the blend problem got much easier, the offset problem got harder.

### 7.1 The cavity must be a true offset (new #1 risk)
The measured gap is exactly 3.000 mm, so the cavity is a genuine geometric offset
of the plug, and the STEP shows Onshape approximating it (deg (3,3), 13 × 4 poles,
~1.6 µm tolerance, cavity bbox 181.0032 rather than 181). Reproducing that means
`offset2D` — or 3D offset — **on a quintic spline profile**, which is exactly where
OCC is least reliable: it can fail outright, self-intersect at tight corners, or
return a wildly over-refined spline.

Mitigations, in order:
1. Offset the *profile* in 2D once, then extrude/loft — never offset the solid.
2. Validate the result: check the offset curve's min distance to the source equals
   the gap within tolerance, and reject if not. This is cheap and catches OCC's
   silent failures.
3. Fallback: re-parameterise the template at `s + gap`. That is **not** what the
   original does and is wrong by up to 0.18 mm at the corners, so it must be a
   labelled degraded mode, never a silent substitution.
4. Hard-validate `gap < min_radius_of_curvature` (`0.72184 · s`); a larger offset
   on a concave side self-intersects.

### 7.2 The corner blend is exactly reproducible — but only if built deliberately
Good news that replaces the earlier "no native operation" worry: the blend is an
8-pole non-rational quintic B-spline with a fixed normalised control polygon
(§2.2), constructible with `Edge.makeBezier`/`makeSpline` from poles and an
explicit knot vector. No fitting, no approximation, no conic support needed.

What is *not* free: everything downstream. OCC's `fillet()`, `extrude(taper=)`
and 2D offset are all markedly less robust on spline edges than on lines and arcs.
The mitigation is to express the plug and cavity as a **stack of z-parameterised
2D profiles** and `loft` — draft, root fillet and floor/rim blends all reduce to
"what is the profile at height z". That is deterministic and never throws. Cost:
lofted surfaces are spline approximations rather than exact extrusions, and the
profile count becomes a quality knob. Decide this in Stage 2 and hold to it.

Offer `corner_style = circular` as an alternative and state the cost plainly: a
circular-corner rebuild differs from the reference by up to **3.2 mm** at
mid-blend and **3.5 %** in plan area, and it is G1 rather than G2 — visible in the
formed leather, not a rounding error.

### 7.3 Blend-on-blend corner patches
Where the vertical blend wraps the plan corner, Onshape produced large approximated
NURBS patches: male deg (3,3) with **30 × 29** poles, female deg (3,3) with
**24 × 44**. These are the expensive, failure-prone surfaces. If the loft approach
of §7.2 is used they come out as part of the loft and the problem disappears; if
3D `fillet()` is used, expect this to be where it breaks.

### 7.4 Blend radius vs local curvature
Any 3D blend must satisfy `radius < 0.72184 · s` (37.90 mm at the reference's
s = 52.5). Exceeding it gives an OCC failure or a self-intersecting face, not a
clamped result — so it is a validation rule, not a caught exception. Note this
ceiling is *tighter* than the circular-corner intuition would suggest (`s`), which
is a trap when switching `corner_style`.

### 7.5 Two different blend vocabularies, deliberately
The root fillet is a true circular R1.2 rolling-ball fillet (cylindrical faces on
the straights, rational-quadratic sweeps at the corners); every other blend is the
G2 quintic. A parametric model that forces one style everywhere will not reproduce
the reference. Keep the style selectable per blend.

### 7.6 The two reference revisions disagree
The STEP has the shape but not the clamp holes or pry notches; the STL has both.
`reference/measured.json` must record which file each number came from, and the
Stage 2 fidelity test must compare against the STEP *without* features while the
Stage 4 test compares against the STL *with* them. Mixing them up will produce a
5 cm³ "mystery" discrepancy.

### 7.7 Mesh export determinism
`BRepMesh_IncrementalMesh` output depends on the OCC version and tolerance. Pin
exact versions, record them in export metadata, and ship **3MF alongside STL** —
STL is unitless. STEP export is native to CadQuery; 3MF is not and needs `lib3mf`
or `trimesh` on the tessellated result. Treat that as a real dependency decision.

### 7.8 Print cost explodes quietly
The reference male is **993.8 cm³** solid. "300 × 200 × 60" more than triples it.
Surface a filament/volume/print-envelope estimate next to the preview from Stage 3.

### 7.9 Closed-position semantics
§2.5 — no flange relief, no floor stop, ambiguous usage orientation. Do not
silently inherit that. Model the closed stack explicitly, default to the
reference's behaviour, and document what each knob does.

### 7.10 Two clearances that look alike
The leather gap (3 mm, a *forming* quantity) and the alignment-pin fit clearance
(0.15–0.3 mm, a *printer* quantity) are different in kind. Separate namespaces
(`leather`/`fit` vs `manufacturing`) so tuning a printer never moves a tray
dimension.
