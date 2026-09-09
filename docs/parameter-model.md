# Parameter Model

Companion to [`architecture.md`](./architecture.md). The schema below is
implemented in `packages/tray-core/traymold/params.py`; Pydantic v2 is the single
definition and everything else (JSON Schema, generated TypeScript, the CLI) is
derived from it.

> **Revision history.** v1 modelled the corner as a conic. v2 corrected it to the
> G2 quintic. v3 (this) separates the three concepts properly and removes
> `length + 2·gap` / `corner_setback + gap` as construction rules — they are
> derived measurements only. Profile types are now named for the curve
> construction they actually use.

---

## 1. Principles

1. **Three concepts, never mixed** — plan/profile geometry, forming gap, 3D edge
   treatments. Each has its own namespace; a change in one cannot be expressed as
   a change in another.
2. **The dependency boundary is a schema property, not a convention.**
   `female_base_profile = offset(male_base_profile, forming_gap)`; nothing else
   may reach the female cavity profile.
   `tests/test_dependency_boundary.py` enforces it in both directions.
3. **Millimetres and degrees, always.** No unit strings in the data model; the UI
   may display inches, converting at the edge.
4. **Inputs are independent; everything else is derived** (§4).
5. **Strongly typed, not stringly typed.** Profile families are a discriminated
   union named for their curve construction, so an obround cannot carry a corner
   setback and an ellipse cannot carry a `rho`.
6. **Datum is explicit and `outer` is refused.** `length / width / depth` are the
   finished tray's **inner** dimensions — the male forming profile, which is what
   the reference's "4 × 7" means. `tray.datum = "outer"` is accepted by the schema
   so the intent is expressible, but `validate` returns `E-DATUM-001` and `build`
   raises. Outer dimensions are never silently reinterpreted as inner ones. The
   rule goes away when a real outer→inner conversion exists.

7. **Draft is experimental.** The current implementation preserves a constant
   **profile-plane (horizontal)** gap; the true normal separation is `gap·cos θ`
   (−45.6 µm at 10° on a 3 mm gap). Measured in
   [`architecture.md` §9](./architecture.md#9-draft-is-experimental). No semantic
   contract has been chosen, so draft is not production-ready.

---

## 2. Parameter groups

### 2.1 Concept 1 — `tray`: profile geometry

| field | type | default | notes |
|---|---|---|---|
| `profile` | `ProfileSpec` | `G2QuinticObroundProfile(175, 105)` | discriminated union, §2.2; carries `length` and `width` |
| `depth` | float mm | 25.0 | draw depth, Z |
| `datum` | `"inner" \| "outer"` | `inner` | which surface the dimensions describe |
| `draft_angle` | float deg | 0.0 | **experimental**, see below; 0 in the reference |
| `draft_mode` | `"both" \| "plug_only" \| "cavity_only"` | `both` | |

### 2.2 `ProfileSpec` — named for the curve construction

```python
class G2QuinticObroundProfile:    kind, length, width                    # THE REFERENCE
class G2QuinticRectProfile:       kind, length, width, corner_setback
class ConicObroundProfile:        kind, length, width, rho = 0.5
class ConicRectProfile:           kind, length, width, corner_setback, rho = 0.5
class CircularObroundProfile:     kind, length, width                    # conventional stadium
class CircularRectProfile:        kind, length, width, corner_radius     # conventional rounded rect
class EllipseProfile:             kind, length, width
class SuperellipseProfile:        kind, length, width, exponent = 4.0
```

Every member exposes `corner_setback` and `corner_style` as computed properties.
The `*Obround*` members lock the setback to `width / 2` — the degenerate maximum
where the short ends lose their straight run entirely — so it is not expressible
and cannot be set wrong.

**The reference is `G2QuinticObroundProfile`, not a conic.** The blend surfaces in
the STEP are non-rational, which rules conics out by definition; the exact poles
are in [`architecture.md` §4.2](./architecture.md#42-the-base-profile-one-g2-quintic-three-setbacks).
`ConicObroundProfile` / `ConicRectProfile` remain as their own families because a
conic is a perfectly reasonable thing to want — they are simply not what the
reference is. A conventional circular stadium is likewise its own family.

| | `g2_quintic` | `conic` (ρ) | `circular` |
|---|---|---|---|
| rational | no | yes | yes |
| curvature at the tangent points | **0** (true G2) | `1/2s` | `1/s` (G1 only) |
| minimum radius of curvature | **0.72184·s** | `s/√2` at ρ=0.5 | `s` |
| corner area removed | 0.163338·s² | 0.166667·s² at ρ=0.5 | 0.214602·s² |
| reference `s = 52.5` | ∞ → **37.90 mm** → ∞ | ∞ is not attainable | constant 52.5 |

`corner_setback` always means **setback** — the distance from the sharp corner
along each edge to the tangent point. For `circular` that equals the arc radius,
which is why that family names the field `corner_radius`.

The `0.72184·s` minimum is the ceiling on every inward offset and every 3D blend
(§5). It is ~28 % tighter than the circular intuition, so switching families can
invalidate a working design; re-validate on that switch.

### 2.3 Concept 2 — `leather` and `fit`: the forming gap

| group | field | default | notes |
|---|---|---|---|
| `leather` | `thickness` | 3.0 | mm |
| `leather` | `compression` | 0.0 | fraction, 0 … 0.4 |
| `fit` | `clearance` | 0.0 | mm, −0.5 … 2.0; negative = interference |
| `fit` | `gap_override` | `null` | set the gap directly, bypassing the formula |

```
forming_gap = clearance + thickness × (1 − compression)        # or gap_override
```

Reference: `3.0 = 0.0 + 3.0 × (1 − 0.0)`.

This is the **only** quantity permitted to relate the male base profile to the
female one. It is not a plate dimension, not a blend, and not a printer fit —
those live in `mold`, `mold.*_blend` and `manufacturing` respectively.

### 2.4 Concept 3 — `mold.*_blend`: 3D edge treatments

Each treatment is an independent, **semantically typed** value, applied to a solid
*after* the base profiles exist. The type carries the design meaning and names its
own parameter accordingly:

```python
class CircularFillet:     kind="circular_fillet";   radius: float
class G2QuinticBlend:     kind="g2_quintic_blend";  setback: float
class ChamferTreatment:   kind="chamfer";           distance: float
class NoTreatment:        kind="none"
```

`blends.compile_treatment` is the one place that meaning becomes geometry: every
treatment compiles to a height-dependent plan offset of the base profile, and the
solid is lofted through those offsets. **No OCC 3D fillet is used**, because the
profile-offset loft reproduces the reference more robustly and to ~1 µm
([`architecture.md` §4.5](./architecture.md#45-the-3d-edge-treatments-are-plan-offsets-too-and-are-compiled-into-them)).
The semantic type survives that compilation — it is what the schema, the UI and
the diagnostics speak in.

| field | reference | applies to |
|---|---|---|
| `male_root_blend` | `CircularFillet(radius=1.2)` | plug ↔ base plate junction (adds material) |
| `male_floor_blend` | `G2QuinticBlend(setback=5.0)` | plug top edge = the tray's floor radius |
| `female_entry_blend_top` | `G2QuinticBlend(setback=3.0)` | cavity mouth, top face |
| `female_entry_blend_bottom` | `NoTreatment()` | cavity mouth, bottom face (sharp in the reference) |

The reference deliberately mixes vocabularies — a true circular rolling-ball
fillet at the root, the G2 quintic everywhere else — so the style is per
treatment, never global. Both cavity faces are exposed because the reference's
usage orientation is ambiguous from the geometry
([`architecture.md` §4.6](./architecture.md#46-relationships-that-survive-as-derived-values)).

**No edge treatment is an input to the forming gap or to either base profile.**

### 2.5 `mold`: plate construction

| field | default | notes |
|---|---|---|
| `flange_width` | 30.0 | measured from the **plug**; the female's 27 mm is derived |
| `base_plate_thickness` | 15.0 | male |
| `cavity_plate_thickness` | 25.0 | female; `== depth` in the reference (flush top) |
| `plate_edge_chamfer` | 0.0 | *schema only, not yet in the geometry* |
| `flange_relief_depth` | 0.0 | recess for the leather flange; the reference has none. *schema only* |

### 2.6 `features`: manufacturing features

`clamp_holes` (pattern, diagonal, diameter, inset, top_chamfer, in_male,
in_female), `pry_notches` (pattern, diagonal, size_x, size_y, depth),
`alignment_pins` (pattern, diameter, height, inset). All default to disabled;
the `ref-4x7` preset enables the first two to match the STL revision.

Reference note: clamp holes sit on one diagonal and pry notches on the other, so
`diagonal` is part of the schema — the female has C2 rotational symmetry, not
mirror symmetry.

### 2.7 `manufacturing` and `quality`

`manufacturing`: `pin_fit_clearance` (0.20), `min_wall` (2.0),
`nozzle_diameter` (0.4). These are printer quantities and must never be confused
with the forming gap.

`quality`: `mode` (`preview` | `export`) plus optional overrides for
`blend_sections`, `max_section_sagitta`, `linear_deflection` and
`angular_deflection`. Leave the overrides at `None` to take the mode's measured
defaults.

**Both modes describe the same geometry** — identical base profile, identical
forming gap, identical treatment semantics, identical correctness protections.
They differ only in loft section density and tessellation tolerance.

| | export | preview |
|---|---|---|
| `max_section_sagitta` | 0.002 mm | 0.05 mm |
| `blend_sections` (a **cap**, not a count) | 48 | 16 |
| resolved sections on the reference | 15 / 35 / 28 | 4 / 8 / 7 |
| `linear_deflection` / `angular_deflection` | 0.05 mm / 0.20 rad | 0.25 mm / 0.50 rad |
| measured deviation vs STEP | ≤ 4.2 µm | ≤ 29.9 µm |
| build time, both parts | 5.43 s | 2.51 s |

Section counts are derived from `max_section_sagitta`, not set directly: a chord
`c` across a cross-section of radius `R` deviates by `c²/8R`, so the count follows
from the treatment's own size. `blend_sections` only caps it.

`mold.parts` selects which halves to build (`male`, `female`); an unselected half
is `None` in the result.

---

## 3. The reference as parameters

`traymold.presets.REF_4X7_STEP` reproduces the STEP pair; `REF_4X7` adds the
STL revision's features. The split matters: mixing them produces a 5 cm³ phantom
discrepancy.

```python
Params(
    name="ref-4x7-wetmold",
    tray=TrayParams(
        profile=G2QuinticObroundProfile(length=175.0, width=105.0),
        depth=25.0, datum="inner", draft_angle=0.0,
    ),
    leather=LeatherParams(thickness=3.0, compression=0.0),
    fit=FitParams(clearance=0.0),
    mold=MoldParams(
        flange_width=30.0,
        base_plate_thickness=15.0,
        cavity_plate_thickness=25.0,
        male_root_blend=CircularFillet(radius=1.2),
        male_floor_blend=G2QuinticBlend(setback=5.0),
        female_entry_blend_top=G2QuinticBlend(setback=3.0),
        female_entry_blend_bottom=NoTreatment(),
    ),
    features=Features(
        clamp_holes=ClampHoles(enabled=True, pattern="diagonal_pair", diagonal="nw_se",
                               diameter=6.0, inset=15.0, top_chamfer=2.0,
                               in_male=False, in_female=True),
        pry_notches=PryNotches(enabled=True, pattern="diagonal_pair", diagonal="ne_sw",
                               size_x=15.0, size_y=15.0, depth=8.0),
    ),
)
```

---

## 4. Derived quantities

Computed in `derive.py`; never accepted as input.

| derived | how | reference |
|---|---|---|
| `forming_gap` | `clearance + thickness × (1 − compression)` | 3.000 |
| `corner_setback` | from the profile family | 52.5 |
| `corner_radius_min` | `factor(corner_style) × corner_setback`; bounds INWARD offsets only | 37.90 |
| `max_inward_offset` | same as `corner_radius_min` — the convex minimum radius | 37.90 |
| `max_outward_offset` | min concave radius; `inf` for a convex profile | `inf` |
| `plate_length` / `plate_width` | `length/width + 2 × flange_width` | 235.0 / 165.0 |
| `female_flange_width` | `flange_width − forming_gap` | 27.0 |
| `closed_height` | `base_plate_thickness + cavity_plate_thickness` | 40.0 |
| `vertical_wall_height` | `depth − root_blend.size − floor_blend.size` | 18.8 |
| `draft_offset_at_depth` | `depth × tan(draft_angle)` | 0.0 |

**Cavity bounding box is a measurement, not a parameter.** For the reference the
offset happens to give exactly 181 × 111, so `length + 2·gap` is numerically
right — but it is an *observation about this profile*, not the construction. For a
profile whose corner setback is below the maximum, or for an ellipse or
superellipse, the offset's bounding box is still `length + 2·gap` while its
*corner geometry* is not the same family re-parameterised: the STEP female's own
corner differs from the template at `s = 55.5` by up to 182 µm. Never generate a
cavity that way.

---

## 5. Dependencies and validation

### 5.1 Dependency graph

```
profile.length ─┐
profile.width  ─┼─► base profile ─┬─► male forming geometry
plan-shape args ┘                 │      └─► male root blend      (male only)
                                  │      └─► male floor blend     (male only)
                                  │
leather.thickness ┐               └─► offset(base, forming_gap)
leather.compression├─► forming_gap ────────┘   └─► female cavity
fit.clearance     ┤                                   └─► female entry blend
fit.gap_override  ┘

profile.corner_setback ─► corner_radius_min = factor × setback
                            └─► ceiling on forming_gap, every inward offset,
                                and every blend size
mold.flange_width ─► plate size ─► feature inset windows
```

Edge treatments, plate thicknesses and features are leaves. Nothing flows back up.

### 5.2 Direction-aware curvature

An offset cusps only where it reaches the local radius of curvature **on the side
it moves towards**, and those are opposite sides for the two directions:

| offset direction | cusps on | limit |
|---|---|---|
| inward (male edge treatments) | convex regions | `max_inward_offset` = 37.90 mm on the reference |
| outward (**the forming gap**) | concave regions | `max_outward_offset` = `inf`, every family here is convex |

So a 60 mm forming gap on the reference profile is valid and builds, even though
it is 1.6× the convex minimum radius. Tested both ways in
`tests/test_offset_direction.py`. The realised-distance verifier stays behind the
rules as the numerical backstop, and earns it: at 37.9 mm inward — just inside the
measured limit — the rule passes and the verifier catches the degraded geometry.

### 5.3 The boundary, as tested

| changing this | must change the female base profile |
|---|---|
| `tray.profile.length` | yes |
| `tray.profile.width` | yes |
| `tray.profile` family / plan-shape args | yes |
| `leather.thickness`, `leather.compression` | yes |
| `fit.clearance`, `fit.gap_override` | yes |
| `mold.male_root_blend` | **no** |
| `mold.male_floor_blend` | **no** |
| `mold.female_entry_blend_top` / `_bottom` | **no** |
| `mold.base_plate_thickness`, `cavity_plate_thickness`, `flange_width` | **no** |
| any `features.*` | **no** |

Equivalence is asserted on three measures, two discretisation-free: bounding box
(1e-9 mm), exact enclosed area via `Face.makeFromWires(...).Area()` (1e-12
relative), and sampled deviation (0.1 µm; the sampled floor is ~12 nm of chord
sagitta).

### 5.4 Diagnostics

`error` refuses the build; `warning` builds and flags. Codes marked ✓ are
implemented; the rest are specified for the validation milestone.

| code | sev | condition | why |
|---|---|---|---|
| `E-SHAPE-001` ✓ | error | `corner_setback > min(L,W)/2` | setback cannot exceed the half-width |
| `E-SHAPE-004` ✓ | error | any of `length,width,depth ≤ 0` | |
| `W-SHAPE-003` | warn | `corner_setback < 3 × leather.thickness` | leather will not take that corner |
| `E-BLEND-010` ✓ | error | `floor_blend.size > depth / 2` | no room in Z |
| `E-BLEND-011` ✓ | error | a **male** treatment's size ≥ `max_inward_offset` | male treatments offset inward, so the convex minimum radius bounds them |
| `E-BLEND-012` | error | `min(L,W) − 2 × floor_blend.size ≤ 0` | the plug's top face degenerates |
| `E-BLEND-013` ✓ | error | `entry_top.size + entry_bottom.size > cavity_plate_thickness` | the rim blends meet |
| `E-BLEND-015` ✓ | error | `root_blend.size + floor_blend.size ≥ depth` | no vertical wall left |
| `E-GAP-020` ✓ | error | `forming_gap ≤ 0` | plug larger than cavity |
| `E-GAP-025` ✓ | error | `forming_gap ≥ max_outward_offset` (the **concave** minimum radius) | the outward offset would cusp. For a convex profile this is `inf`, so a gap larger than the convex minimum radius is **valid** and must not be refused |
| `E-GAP-026` ✓ | error | realised offset distance ≠ requested within 10 µm | OCC degraded silently — refuse, never ship |
| `E-DATUM-001` ✓ | error | `tray.datum != "inner"` | no outer→inner conversion exists; never reinterpret silently |
| `W-GAP-021` ✓ | warn | `forming_gap < 0.4` | below FDM resolution; the halves fuse |
| `E-MOLD-040` ✓ | error | `cavity_plate_thickness < depth` | the plug protrudes |
| `E-MOLD-041` ✓ | error | `female_flange_width < min_wall` | i.e. `flange_width − gap < min_wall` |
| `E-FEAT-050` | error | clamp hole to cavity wall `< d/2 + min_wall` | hole breaks into the cavity |
| `E-FEAT-051` | error | `inset < d/2 + min_wall` | hole breaks the plate edge |
| `E-FEAT-053` | error | a pry notch overlaps a clamp hole | the reference avoids this via opposite diagonals |
| `W-FEAT-061` | warn | no pins and no holes in both halves | reproduces the reference's loose registration |
| `W-MFG-071` | warn | estimated volume > 1500 cm³ | the reference male alone is 993.8 cm³ |

`E-BLEND-011`, `E-BLEND-012` and `E-GAP-025` describe states where OCC either
throws or returns a self-intersecting solid that tessellates into a
plausible-looking but unprintable mesh. They must be checked arithmetically
before the kernel is invoked. `E-GAP-026` is the backstop and is already live in
`offset_profile`.

---

## 6. Versioning

`schema_version` (2.0.0) is stored in every params document. `MODEL_VERSION`
changes whenever the geometry for unchanged parameters changes, and participates
in cache keys. Redefining a field's meaning is a major bump plus an explicit
migration; old documents are never silently reinterpreted.
