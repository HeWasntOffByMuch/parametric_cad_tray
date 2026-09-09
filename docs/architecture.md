# Parametric Leather-Tray Wet-Mold Generator — Architecture

Scope: turn the `4x7` wet-mold pair in `reference/` into a parametric CAD
application. The geometry core is **implemented**; the API and UI are not, and
must not be started until the core relationship below is correct and tested.

Companion: [`parameter-model.md`](./parameter-model.md).

> **Revision history of this document.** v1 reconstructed the geometry from the
> STL meshes and concluded the corners were conic (ρ = 0.5). v2 corrected that
> from the STEP B-rep. v3 (this) corrects the *construction rule*: the female is
> derived from the male **base** profile by a true 2D offset, not by
> re-parameterising a profile at `length + 2·gap`. The bounding-box arithmetic
> still holds as a *derived measurement*; it was never the construction.

---

## 1. The three concepts

These are kept strictly apart everywhere — schema, code and tests:

```
1. tray / profile geometry     the plan curve and the draw depth
2. forming gap                 leather thickness, compression, clearance
3. 3D edge treatments          root blend, floor blend, entry blend
```

They are not interchangeable and must never be mixed. In particular a 3D edge
treatment is **not** a way of changing the forming gap, and the forming gap is
**not** a way of changing the plan profile.

## 2. The dependency tree

```
base tray profile                       (concept 1)
      │
      ├── male forming geometry
      │      └── male root blend        (concept 3, male only)
      │      └── male floor blend       (concept 3, male only)
      │
      └── offset(base male profile, forming_gap)     (concept 2)
             └── female cavity geometry
                    └── female entry blend           (concept 3, female only)
```

The authoritative relationship is:

```
female_base_profile = offset(male_base_profile, forming_gap)
```

where `male_base_profile` is the 2D profile **before** any of the male's 3D edge
treatments. Consequences, all enforced by tests:

* The finished male **solid** is never offset — only the base profile is.
* Male fillets and blends are not inputs to the female offset.
* The female's entry blend is its own operation with its own parameter, applied
  after the cavity exists.
* `cavity_length = length + 2·gap` and `corner_setback + gap` are **derived
  bounding-box measurements**, not construction rules. For the reference they
  happen to be exact; for a general profile they are not (see §4.4).

In code (`traymold/mold.py`, verbatim shape):

```python
base           = make_base_profile(params)
male_family    = ProfileFamily(base, 0.0)               # the male IS the base
female_family  = ProfileFamily(base, forming_gap(params))

male   = build_male_from_profile(male_family, params)
male   = apply_male_root_blend(male, male_family, params)
male   = apply_male_floor_blend(male, male_family, params)

female = build_female_from_profile(female_family, params)
female = apply_female_entry_blend(female, female_family, params)

male, female = apply_features(male, female, params)
```

`ProfileFamily` is a base wire plus one fixed offset; every wire it yields is a
*single* offset of the base, never an offset of an offset. Offsets compose
exactly, so this is geometrically identical to chaining and far more robust —
OCC degrades quickly when asked to offset its own spline output (§7.2).

---

## 3. What is in the repository

```
reference/
  male_tray_mold.step         AP242, 25 faces   — authoritative shape
  female_tray_mold.step       AP242, 18 faces   — authoritative shape
  4x7-male-wetmold.stl        26 738 tris       — later revision
  4x7-female-wetmold.stl      37 626 tris       — later revision, has the features
  reference_render_preview.webp, reference_real_picture.webp
packages/tray-core/           the geometry core (implemented)
tools/reference_probe/        STEP/STL measurement used throughout this document
docs/
```

The STEP files are AP242 exports from **Onshape** (`ONSHAPE BY PTC INC, 1.220`,
via ST-DEVELOPER v20, document "Part Studio 2"), in metres, carrying exact NURBS.

**The STEP pair is an earlier revision than the STL pair.** The STEP female has
no clamp holes and no pry notches. Cutting the STL's two chamfered Ø6 holes and
two 15 × 15 × 8 notches out of the STEP female gives 512.684 cm³ against the
STL's 512.392 cm³ — a 0.06 % meshing residual. Take the **shape** from the STEP
and the **manufacturing features** from the STL; the `ref-4x7-step` and
`ref-4x7` presets are exactly that split.

The text on the male plate in the render is a slicer object-label overlay, not
geometry.

---

## 4. The reference geometry

### 4.1 Coordinate systems

The STEP files are in assembly position with the parting plane at `z = 25`.
`traymold` puts the parting plane at `z = 0` with `+Z` the plug direction, so
`z_reference = z_traymold + 25`.

| | traymold Z | thickness |
|---|---|---|
| male base plate | −15 → 0 | 15 mm |
| male plug | 0 → 25 | 25 mm |
| female plate | 0 → 25 | 25 mm |

Both plates are 235 × 165 mm; the plug top and the female top are coplanar.

### 4.2 The base profile: one G2 quintic, three setbacks

The plug's plan profile is a 175 × 105 rectangle whose corner blend consumes the
entire half-width (setback `s` = 52.5 = W/2), leaving a 70 mm straight run on each
long side and none on the short ends. The blend faces are
`B_SPLINE_SURFACE deg=(5,1)`, 8 × 2 poles, **non-rational** — which rules out
conics, and is why the earlier ρ = 0.5 reading was wrong.

Read directly from the STEP control points and normalised (corner at the origin,
curve from `(−1,0)·s` to `(0,1)·s`):

```
degree 5, non-rational
knots  [0,0,0,0,0,0, ½,½, 1,1,1,1,1,1]     two quintic Bézier spans, C3 at the join
poles  (−1,0) (−0.85,0) (−0.70,0) (−1/3,0.10) (−0.10,1/3) (0,0.70) (0,0.85) (0,1)
```

Symmetric under `(a,b) → (−b,−a)`. Three collinear poles at each end give
**exactly zero endpoint curvature** — a true G2 join to the straight edges, not
the G1 join a circular fillet gives.

| property | this blend | circular arc r=s | parabola (conic ρ=0.5) |
|---|---|---|---|
| radius of curvature at the tangent points | **∞** | `s` | `2s` |
| minimum radius of curvature | **0.72184·s** | `s` | `s/√2` |
| corner area removed | **0.163338·s²** | 0.214602·s² | 0.166667·s² |

At `s = 52.5`: minimum radius **37.90 mm**, and the plan area is 16 574.20 mm²
analytically against 16 574.19 mm² sectioned from the STEP. A circular obround of
the same bounding box gives 16 009.01 mm² — 3.5 % less, and up to 3.2 mm of
positional deviation at mid-blend.

**The same normalised template is used for the 3D edge treatments**, verified
pole-by-pole: male floor blend at setback 5.0 (faces F19/F24), female entry blend
at setback 3.0 (faces F12/F17). One primitive, three setbacks.

### 4.3 The two halves

```
MALE   993.796 cm³ · 25 faces: 9 PLANE, 2 CYLINDER, 14 B_SPLINE_SURFACE
  base plate   235 × 165 × 15, planar, sharp, no holes, no notches
  plug         base profile, 25 mm, draft 0.000° (walls are PLANE faces)
  root blend   TRUE CIRCULAR R1.2 rolling-ball fillet — CYLINDER faces d=2.4 on
               the straight runs, exact circular sweeps at the corners
  floor blend  G2 template, setback 5.0
  top face     PLANE, 165 × 95 bbox

FEMALE 517.830 cm³ · 18 faces: 8 PLANE, 10 B_SPLINE_SURFACE (no cylinders)
  plate        235 × 165 × 25, sharp
  cavity       through, draft 0.000°
  entry blend  G2 template, setback 3.0, on the top face only
  bottom edge  sharp

STL revision only:
  clamp holes  2 × Ø6 through at (∓102.5, ±67.5), 15 mm in from both edges,
               one diagonal, 2 mm × 45° chamfer on the top face
  pry notches  2 × 15 × 15 corner rebates on the *other* diagonal, 8 mm deep
```

The root blend being a genuine circular fillet while every other blend is the G2
quintic is deliberate, and visible in the face types. A model that forces one
style everywhere cannot reproduce the reference.

### 4.4 Evidence that the female is a true offset of the male base profile

Method: build the male base profile analytically from the template above, take a
true geometric 2D offset with `BRepOffsetAPI_MakeOffset`, and compare against the
STEP female's cavity section at a height where both walls are straight
(`z_ref = 35`, i.e. `z_traymold = 10`).

Reproduce with `python3 tools/reference_probe/verify_offset.py`:

| | value |
|---|---|
| requested nominal offset | **3.000000 mm** |
| minimum deviation from the STEP female | **0.000 µm** |
| maximum deviation from the STEP female | **2.406 µm** |
| RMS deviation from the STEP female | **0.855 µm** |

Context for the 2.4 µm:

| | min | max |
|---|---|---|
| realised distance, our offset → our base profile | 3.000000 mm | 3.000070 mm |
| realised distance, STEP female → STEP male | 2.997962 mm | 3.002441 mm |

Our offset is *more* accurate than the one in the file. The 2.4 µm residual is
Onshape's own offset approximation, not ours — the same reason the STEP cavity
measures 181.0032 × 111.0032 where an exact offset gives 181.000 × 111.000.

Supporting checks, all against the STEP:

| check | result |
|---|---|
| analytic base profile vs STEP male section, `z_ref = 35` | max **0.106 µm** |
| STEP female corner vs the template re-parameterised at `s = 55.5` | max **182.3 µm** |
| STEP female cavity wall surface type | deg (3,3), 13 × 4 poles — an *approximated* surface |
| STEP male plug wall surface type | deg (5,1), 8 × 2 poles — an *exact* extrusion |

The last two are the structural tell: the male's wall is an exact extrusion of a
sketched curve, the female's is an approximated offset surface. Together with the
182 µm figure they rule out re-parameterisation and confirm the offset.

**Verdict: encode the offset relationship directly.** Which is what the core does.

### 4.5 The 3D edge treatments are plan offsets too, and are compiled into them

Every edge treatment in the reference is the base profile offset in plan by a
height-dependent amount. Measured against the STEP:

| treatment | model | max deviation |
|---|---|---|
| male root fillet (circular R1.2) | `offset(base, +lat(h))` | 1.00 µm |
| male floor blend (G2, setback 5) | `offset(base, −lat(h))` | 1.69 µm |
| female entry blend (G2, setback 3) | `offset(base, gap + lat(h))` | 1.09 µm |

This is why the core needs no 3D `fillet()` call anywhere: each treatment is a
loft through offset profiles, which is deterministic and cannot fail the way
OCC's blend algorithms do. It also keeps the dependency boundary trivially
enforceable — a treatment is a function of the base profile and its own size, and
of nothing else.

Treatments stay **semantically typed** — a circular fillet has a *radius*, a G2
blend a *setback*, a chamfer a *distance* — and `blends.compile_treatment` is the
single place that meaning becomes geometry:

```
analytic base profile
        +  accumulated plan offset as a function of Z
        →  section profiles           (always offsets of the base, never chained)
        →  loft
```

### 4.6 Relationships that survive as derived values

| derived | reference value |
|---|---|
| cavity bbox | 181 × 111 (exactly, from the offset; the STEP's 181.0032 is its own error) |
| male flange 30, female flange 27 | one flange parameter; the difference is the gap |
| plate outline | `tray + 2 × flange`, shared by both halves |
| plug height == female plate thickness | 25 == 25, the flush top is deliberate |
| nominal "4 × 7" | inner tray 105 × 175 mm = 4.13″ × 6.89″, depth ≈ 1″ |

**Datum.** The plug is the tray's inner surface, the cavity its outer surface, so
`length / width / depth` are inner dimensions. `tray.datum` can switch to `outer`.

**Registration is loose.** The Ø6 holes exist only in the female, and only in the
later revision; nothing locates the halves but the plug in the cavity, with `gap`
of slop until leather fills it. Alignment pins are a real improvement.

**No leather relief** at the flange or the floor in the reference. Modelled
explicitly (`flange_relief_depth`) rather than inherited silently.

---

## 5. Implementation status

Milestone order, as specified:

| # | step | status |
|---|---|---|
| 1 | `make_base_profile(params)` | done — `traymold/profiles.py` |
| 2 | exact reference male base profile | done — 0.053 µm vs STEP |
| 3 | robust 2D offset operation | done — `offset_profile`, self-verifying |
| 4 | female cavity profile from the male base profile | done — `make_female_profile` |
| 5 | male plate + raw forming extrusion | done — `build_male_from_profile` |
| 6 | female plate + raw cavity | done — `build_female_from_profile` |
| 7 | male root treatment | done — `apply_male_root_blend` |
| 8 | male floor/face blend | done — `apply_male_floor_blend` |
| 9 | female face blend | done — `apply_female_entry_blend` |
| 10 | reference holes / chamfers / notches | done — `apply_features` |
| 11 | STEP / STL export | done — `traymold/exporters.py` |
| 12 | fidelity tests against the original STEP | done — `tests/test_reference_fidelity.py` |

**The API layer is now implemented** — see [`api.md`](./api.md). React, R3F and
the production parameter form are still deliberately not started.

### 5.1 Package layout

```
packages/tray-core/
  traymold/
    blends.py     the G2 quintic template + BlendLaw (lateral offset vs height)
    profiles.py   base profiles, the 2D offset, and its verification
    params.py     Pydantic v2 schema — the single definition
    derive.py     forming_gap and other derived values
    mold.py       the pipeline of §2, one function per step
    exporters.py  STEP / STL
    presets.py    ref-4x7 and ref-4x7-step
    api.py        the frozen application-facing interface
    cli.py        traymold build|derive|validate|schema|presets|version
  tests/
    test_blend_template.py       the template's poles, curvature and area
    test_profiles.py             every profile family builds and offsets
    test_dependency_boundary.py  the tree of §2, enforced
    test_reference_fidelity.py   vs the STEP solids
tools/reference_probe/step_probe.py
```

---

## 6. Testing

`test_dependency_boundary.py` is the load-bearing suite. Equivalence is asserted
on three measures, two of them discretisation-free: bounding box (1e-9 mm),
exact enclosed area via `Face.makeFromWires(...).Area()` (1e-12 relative), and
sampled nearest-point deviation (0.1 µm — the sampled floor is ~12 nm from chord
sagitta, so a tighter sampled tolerance would be meaningless).

Must **not** change the female base profile: male root blend, male floor blend,
female entry blend (top and bottom), base plate thickness, cavity plate
thickness, flange width, and every manufacturing feature.

Must change it: tray length, tray width, plan shape family, leather thickness,
compression, clearance, gap override.

**Volume is not a valid fidelity metric against this STEP.** The imported male's
top face reports `Area()` = 14 167.56 mm² while the area enclosed by its own
boundary wire is 14 245.16 mm², and the solid's `BRepGProp` volume disagrees with
the volume implied by its own cross-sections by 0.25 cm³. Section geometry is
sound and is what the fidelity tests assert on; integrated section volume agrees
to ~2 ppm where the reported volumes differ by 0.08 %.

---

## 7. Robustness notes from the implementation

### 7.1 The offset must be verified, never trusted
`offset_profile` measures the realised distance from its result back to the source
and raises `OffsetError` if it is not the requested distance within 10 µm. OCC's
2D offset degrades silently on spline input, and a silently-degraded gap is the
one failure that would reach a printed part unnoticed. The check costs
milliseconds and has already caught two real cases: an inward offset past the
curvature limit, and a wrongly-oriented circular corner arc that produced a
self-intersecting offset with realised distances of 0.001–5.7 mm.

### 7.2 Never offset an offset
Chaining offsets (female profile → entry blend profile) failed outright on OCC:
sub-micron offsets of OCC's own 10-edge offset output return a null shape. The
fix is `ProfileFamily`, which always offsets the *base* by the accumulated
distance in one step. Mathematically identical, empirically robust.

### 7.3 Sub-micron offsets do not exist
OCC refuses distances below roughly 1e-4 mm on spline wires. `MIN_OFFSET = 1e-4`
treats anything smaller as zero — two orders below the verification tolerance, so
immaterial, but it must be explicit rather than a swallowed exception.

### 7.4 Lofting beats filleting
No 3D `fillet()` is used. Each edge treatment is a loft through offset profiles
(`BRepOffsetAPI_ThruSections`, non-ruled, 48 sections by default). This handles
sections with differing edge counts (6 for the base, 10 for an offset) without
complaint, and cannot fail the way blend algorithms on spline-cornered solids do.
The cost is that the lofted surface interpolates between sections; the section
count is exposed as `export.blend_sections`.

### 7.5 Curvature ceilings are direction-aware
An offset cusps only where it reaches the local radius of curvature **on the side
it moves towards**, and those are opposite sides for the two directions:

* an **inward** offset cusps on **convex** regions → limit = min convex radius
* an **outward** offset cusps on **concave** regions → limit = min concave radius

Every profile family here is convex, so its **outward offset is unbounded**. The
forming gap is an outward offset, so it must never be rejected for exceeding the
convex minimum radius — a 60 mm gap on the reference profile (convex minimum
37.90 mm) is valid and builds. Edge treatments offset inward and *are* bounded by
it. `profiles.curvature_limits` returns both, from OCC's exact second derivatives:
finite differences on a resampled polyline understate the radius badly (22.3 mm
against the true 37.9 mm).

Note the G2 ceiling is ~28 % tighter than the circular one, so switching
`corner_style` can invalidate a working design.

### 7.5a The verifier is the backstop, not the rule
The realised-distance check stays in place behind the curvature rules and earns
its keep: at 37.9 mm inward — just inside the measured limit — the rule passes and
the verifier catches the degraded geometry.

### 7.6 Two reference revisions
Fidelity against the STEP uses `ref-4x7-step` (no features); the featured
`ref-4x7` is checked separately against the STL's feature volumes. Mixing them
produces a 5 cm³ phantom discrepancy.

### 7.7 Loft section spacing is load-bearing
Sections are spaced mostly by equal arclength along the treatment's
(height, lateral) cross-section, because these laws move almost all of their
lateral offset in the last few percent of their height. Equal-height spacing costs
271 µm of reference deviation at 10 sections against 49 µm for arclength.

Pure arclength spacing, though, collapses in height wherever the cross-section has
a horizontal tangent: on the 1.2 mm circular root fillet it placed consecutive
sections 1.5 µm apart in z and 60 µm apart in lateral, and the sliver bands made
the following boolean return garbage — **the male silently lost 394 cm³ while
every sampled section profile still matched**. Blending 25 % uniform-height
spacing back in bounds the minimum step and fixes it.

That near-miss is why `test_reference_fidelity.py` now also asserts each half's
volume against an analytic Steiner construction: section sampling cannot see a
boolean that ate the solid.

### 7.8 Section counts come from a tolerance, not a feeling
`Quality.max_section_sagitta` sets a target chord error for the treatment lofts;
`blend_sections` is only a cap. A chord `c` across a cross-section of radius `R`
deviates by `c²/8R`, so the count follows from the cross-section's arclength. At
the export target of 2 µm the reference gets 15 sections on the 1.2 mm root
fillet, 35 on the 5 mm floor blend and 28 on the 3 mm cavity entry — instead of a
flat 48 everywhere, for the same fidelity and 40 % fewer offsets.

### 7.9 Still open
Draft (`tray.draft_angle`) is **experimental**: see §9. Flange relief and plate
edge chamfer are in the schema but not in the geometry. `tray.datum = "outer"` is
explicitly refused (`E-DATUM-001`) rather than silently reinterpreted.

---

## 8. Performance

Reference pair, median of 5 runs, tessellation measured separately from B-rep
construction (`tools/reference_probe/benchmark.py`).

### 8.1 Before

| | |
|---|---|
| full build | **38.6 s** |
| 2D offset operations | 134, all distinct |
| of the 38.6 s | offsets 30.15 s (78 %), lofts 2.86 s (7 %), rest 5.6 s |
| **of the 30.15 s spent "offsetting"** | **29.54 s was the realised-distance verifier** |

The headline assumption — that OCC's offset dominated — was wrong. OCC's raw
offset is **2.0 ms** per call. The verifier's O(n·m) point-to-segment loop was 220
ms per call and accounted for 76 % of the entire build.

### 8.2 What was changed

| change | effect |
|---|---|
| Vectorised the verifier's distance measure, then replaced exhaustive projection with a two-level nearest-segment search (coarse stride 16, best 3 candidates, refine ±16) | 87 ms → 8 ms, bit-identical to brute force (asserted in `test_profiles.py`) |
| Cached the base profile's curvature limits and verification polyline in a `_BaseCache` shared by both `ProfileFamily` instances | 11 ms + 5 ms saved per offset, ×77 |
| Deduplicated offsets at `MIN_OFFSET` across the whole build | male and female families now share one cache |
| Replaced `solid.cut(band.cut(kept))` with `solid.cut(band).fuse(kept)` in the floor blend | 5.43 s → 0.79 s, and lands closer to the analytic volume |
| Sagitta-driven per-treatment section counts (§7.8) | 134 → 77 offsets at equal fidelity |
| Arclength-blended section spacing (§7.7) | fewer sections needed for the same accuracy |
| `clean()` made best-effort | it is cosmetic face merging and must not fail a build |
| Per-part builds (`mold.parts`) | male-only and female-only are real capabilities, not benchmark artifacts |

**Not** changed, deliberately: nothing was traded away from correctness. The
curvature rules and the realised-distance verifier run identically in both quality
modes.

### 8.3 Analytic offsets — investigated, not adopted

OCC's raw 2D offset costs 2.0 ms; 77 calls is 0.15 s, **2.5 %** of an export
build. Replacing it analytically cannot pay for itself:

* the circular families do have a closed form (`offset(rect(L,W,r), d) = rect(L+2d, W+2d, r+d)`), but they are not the reference;
* the G2 quintic family has **no** closed form — the offset of a polynomial curve is not polynomial, and §4.4 already showed that re-parameterising the template at `s + gap` is wrong by 182 µm;
* an analytic path would still need the same verification, which is where the time actually went.

The measurement is recorded here so this is not revisited on intuition.

### 8.4 After

| case | quality | B-rep | tessellation | total | offsets | unique | sections |
|---|---|---|---|---|---|---|---|
| male only | export | 4.07 s | 0.059 s | **4.13 s** | 50 | 50 | 78 |
| female only | export | 1.30 s | 0.039 s | **1.34 s** | 29 | 29 | 78 |
| both | export | 5.33 s | 0.098 s | **5.43 s** | 77 | 77 | 78 |
| both, featured | export | 5.47 s | 0.099 s | **5.57 s** | 77 | 77 | 78 |
| male only | preview | 1.68 s | 0.009 s | **1.69 s** | 12 | 12 | 19 |
| female only | preview | 0.89 s | 0.007 s | **0.89 s** | 8 | 8 | 19 |
| both | preview | 2.50 s | 0.015 s | **2.51 s** | 18 | 18 | 19 |
| both, featured | preview | 2.62 s | 0.016 s | **2.63 s** | 18 | 18 | 19 |

**38.6 s → 5.43 s, a 7.1× speedup**, with fidelity slightly better than before.

Where the remaining export time goes: offsets 1.82 s (30 %), lofts 1.50 s (25 %),
booleans and everything else 2.64 s (44 %). In preview the booleans are 69 % —
they are fixed-cost OCC work on spline solids and do not scale with section count.
The next lever is building each half as a single loft instead of a staged sequence
of booleans, which would trade away the staged API; it has not been taken.

### 8.5 Quality modes

Both modes describe **the same geometry**: identical base profile, identical
forming gap, identical treatment semantics, identical correctness protections.
They differ only in loft section density and tessellation tolerance.

| | export | preview |
|---|---|---|
| `max_section_sagitta` | 0.002 mm | 0.05 mm |
| `blend_sections` cap | 48 | 16 |
| resolved sections (reference) | 15 / 35 / 28 | 4 / 8 / 7 |
| linear / angular deflection | 0.01 mm / 0.05 rad | 0.10 mm / 0.15 rad |
| worst facet crease, reference male | 0.21° | 1.33° |
| triangles / part | 217k | 22k |
| **section deviation vs STEP** | male 4.16 µm, female 3.05 µm | male 4.16 µm, female 24.77 µm |
| **3D surface deviation vs STEP** | male 3.06 µm, female 2.67 µm | male 29.87 µm, female 4.65 µm |
| build (both parts) | 5.43 s | 2.51 s |

Export beats the 10 µm contract by 2.4×, and is close to the reference's own
internal accuracy of 2.4 µm. Preview's measured budget is 30 µm, asserted
separately in `test_quality_modes.py`; it does not affect export.

Two metrics are reported because same-height section comparison is the right
measure on a vertical wall and misleading where the surface turns horizontal: 0.05
mm below the plug top the profile moves ~60 mm laterally per mm of height, so a
1 µm error in the loft's z position reads as 60 µm of "profile deviation" while
the surface is 1 µm out. `tests/reference.py::surface_deviation` measures the
surface.

---

## 9. Draft is experimental

The current implementation subtracts the same height-dependent plan offset
`z·tan(θ)` from **both** profile families. Measured on built solids
(`tools/reference_probe/draft_analysis.py`, gap 3 mm, measured at mid-wall):

| draft | horizontal separation | h − gap | normal separation | n − gap | gap·cos θ | n − gap·cos θ |
|---|---|---|---|---|---|---|
| 0° | 2.999835 | −0.000165 | 3.000000 | +0.000000 | 3.000000 | +0.000000 |
| 1° | 2.999818 | −0.000182 | 2.999511 | −0.000489 | 2.999543 | −0.000032 |
| 3° | 2.999854 | −0.000146 | 2.995870 | −0.004130 | 2.995889 | −0.000018 |
| 5° | 2.999850 | −0.000150 | 2.988571 | −0.011429 | 2.988584 | −0.000013 |
| 10° | 2.999853 | −0.000147 | 2.954415 | −0.045585 | 2.954423 | −0.000008 |

**The current implementation preserves a constant PROFILE-PLANE (horizontal)
gap.** The true wall-to-wall normal separation is `gap·cos θ`, matched to within
0.03 µm at every angle. The horizontal column is flat to 0.18 µm, which is the
discretisation floor of the measurement.

So the semantic contract is unambiguous *as implemented*; what has **not** been
decided is whether it is the right one. For a leather forming gap the normal
separation is arguably what matters — it is the thickness the material is squeezed
to — and at 10° the current behaviour under-delivers it by 45.6 µm on a 3 mm gap
(1.5 %). At 3° the error is 4 µm, below anything the process can resolve.

The result does not clearly favour one interpretation, so no contract is chosen
here. What is recorded: the implementation holds the horizontal gap; the fix, if
normal is chosen, is to scale the offset by `1/cos θ`; and the reference has 0°
draft everywhere, so nothing about the reference depends on this. Until the
contract is decided, draft is **not production-ready** and is documented as such.


---

## 10. Known limits by profile family

Six of the eight plan families build with the default edge treatments. Two fail,
each on exactly one treatment and nowhere else; every other step of the same mold
builds correctly, so the remedy is specific rather than "use something else".

| family | status |
|---|---|
| `g2_quintic_obround`, `g2_quintic_rect` | full |
| `conic_obround`, `conic_rect` | full |
| `circular_obround`, `circular_rect` | full |
| `ellipse` | fails in the **male root blend** fuse. Set `mold.male_root_blend` to `none` and the mold builds. |
| `superellipse` | fails in the **female entry blend** cut. Set `mold.female_entry_blend_top` / `_bottom` to `none` and the mold builds. |

Both are OCC boolean failures against a lofted spline tool that is tangent to the
wall it acts on, not parameter errors: the profile, the offset and every other
boolean succeed. Converting the tangency into a 1 um overlap was tried and only
moves the failure to the next boolean, so the fix is a change to how the blend
solids are constructed, not a tolerance.

They are reported rather than survived. Every boolean in `mold.py` is now bounded
by `_checked`: a fuse may not shrink a solid, a cut may not grow one, and neither
may return nothing. OCC signals these failures by returning a valid but empty or
undersized shape rather than raising, so before this an elliptical male came out
at 70 cm3 instead of 1010 and still exported a printable STL. Silent corruption
in a tool whose output gets printed is worse than a refusal.

### The superellipse fit

A superellipse has no exact NURBS form, so it is sampled and fitted. Sampling
uniformly in `t` is wrong: for exponent > 2 the parameterisation is singular at
the quadrant boundaries - `dy/dt` diverges at `t = 0` - so uniform sampling
crowds points along the flats and starves the corners. The fitter then chased
that noise into 195-819 poles, and the resulting curve, though accurate to a
nanometre, was too tangled to loft through at all.

Sampling is now bisected on chord sagitta, which puts points where the curve
turns: about 50 poles, and 1.4 um from the true curve. The fit is then measured
against the analytic superellipse and refused if it exceeds 10 um, which happens
above roughly exponent 4.6 at 175 x 105 mm and 5.8 on a larger plan. The schema
stops at 6.
