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

### 4.5 The 3D edge treatments are plan offsets too

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

Not started, deliberately: FastAPI, React, R3F, job queue, caching. Those wait
until the core relationship is correct and tested, which is what §4.4 and the
test suite establish.

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
    cli.py        traymold build|derive|schema|presets|version
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

### 7.5 Curvature ceilings are validation, not exceptions
Any inward offset or blend must stay below `0.72184 · s`. Beyond it the offset
self-intersects. This is checked arithmetically and by the offset verifier; it is
never a caught exception dressed up as a clamp. Note the G2 ceiling is ~28 %
tighter than the circular one, so switching `corner_style` can invalidate a
working design.

### 7.6 Two reference revisions
Fidelity against the STEP uses `ref-4x7-step` (no features); the featured
`ref-4x7` is checked separately against the STL's feature volumes. Mixing them
produces a 5 cm³ phantom discrepancy.

### 7.7 Build cost
A full reference build is ~40 s, dominated by ~150 2D offset operations. That is
acceptable for a CLI and for tests, and is the first thing to profile before any
interactive preview work begins.

### 7.8 Still open
Draft (`tray.draft_angle`) is implemented as an additional height-dependent plan
offset and builds, but is untested against any reference — the reference has 0°
draft everywhere. Flange relief, plate edge chamfer and the datum switch are in
the schema but not yet in the geometry.
