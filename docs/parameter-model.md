# Parameter Model

Status: **design proposal, nothing implemented yet.**
Companion to [`architecture.md`](./architecture.md), which contains the
reverse-engineering evidence this schema is derived from.

> **Revision note.** Rebuilt against the STEP B-rep. The earlier draft modelled the
> corner as a conic (ρ = 0.5) and treated the forming gap as approximately uniform.
> Both were wrong: the blend is an exact G2 quintic (§2.2) and the gap is an exact
> geometric offset (§4). `corner_style`, the curvature ceiling in `E-BLEND-011`,
> and the gap tolerance all change as a result.

---

## 1. Principles

1. **Millimetres and degrees, always.** No unit strings in the data model. The UI
   may *display* inches; conversion happens at the edge, never in the core.
2. **Inputs are independent; everything else is derived.** If a value can be
   computed from other values it is not a parameter (§4). The reference's
   235 × 165 plate outline, its 27 mm female flange and its 181 × 111 cavity are
   all consequences, not inputs.
3. **Strongly typed, not stringly typed.** Shape families are a discriminated
   union, so `corner_radius` cannot even be spelled for an obround (where it is
   fixed at `width / 2`) or for an ellipse (where it is meaningless).
4. **Namespaces separate concerns.** Leather and forming quantities
   (`tray`, `leather`) live apart from printer/fit quantities
   (`fit`, `manufacturing`). Tuning a printer must never move a tray dimension.
5. **One schema definition.** `params.py` (Pydantic v2) → JSON Schema →
   generated TypeScript. See [`architecture.md` §4.3](./architecture.md#43-schema-flows-one-way).
6. **Datum is explicit.** `length / width / depth` are the **inner** dimensions of
   the finished tray (the plug surface) by default — this is what the reference's
   "4 × 7" refers to. `tray.datum` can switch to `outer` (the cavity surface).

---

## 2. Parameter groups

### 2.1 `tray` — the shape of the finished leather piece

| field | type | default | range | notes |
|---|---|---|---|---|
| `profile` | `ProfileUnion` | `obround` | — | discriminated on `kind`; carries `corner_style`, §2.2 |
| `datum` | `"inner" \| "outer"` | `inner` | — | which surface `length/width/depth` describe |
| `length` | float mm | 175.0 | 20 … 400 | X |
| `width` | float mm | 105.0 | 20 … 400 | Y |
| `depth` | float mm | 25.0 | 3 … 120 | draw depth, Z |
| `draft_angle` | float deg | 0.0 | 0 … 15 | 0 in the reference |
| `draft_mode` | `"both" \| "plug_only" \| "cavity_only"` | `both` | — | `both` keeps the gap constant with height |
| `floor_radius` | float mm | 5.0 | 0 … — | blend **setback**, tray floor ↔ wall = the plug's top edge |
| `floor_blend_style` | `CornerStyle` | `g2_quintic` | — | the reference uses the same template as the plan corners, setback 5.0 |

### 2.2 `ProfileUnion` — "choose a tray shape"

```python
class ObroundProfile(BaseModel):            # the reference
    kind: Literal["obround"] = "obround"
    corner_style: CornerStyle = "g2_quintic"
    # corner setback is locked to width/2 — deliberately not expressible

class RoundedRectProfile(BaseModel):
    kind: Literal["rounded_rect"]
    corner_radius: float                     # CORNER SETBACK, see the note below
    corner_style: CornerStyle = "g2_quintic"

class EllipseProfile(BaseModel):
    kind: Literal["ellipse"]

class SuperellipseProfile(BaseModel):
    kind: Literal["superellipse"]
    exponent: float = 4.0                    # 2 = ellipse, →∞ = rectangle

CornerStyle = Literal["g2_quintic", "circular"]
```

**`corner_radius` means corner *setback*** — the distance from the sharp rectangle
corner along each edge to the blend's tangent point. For `circular` the setback
equals the arc radius. For `g2_quintic` the curvature varies, and the core reports
the real numbers as derived values.

**`g2_quintic`** is the reference's own blend, recovered exactly from the STEP
control points. It is a fixed, scale-invariant primitive — not a fit, not an
approximation:

```
degree 5, non-rational
knots  [0,0,0,0,0,0, ½,½, 1,1,1,1,1,1]     two quintic Bézier spans, C3 at the join
poles  (−1,0) (−0.85,0) (−0.70,0) (−1/3,0.10) (−0.10,1/3) (0,0.70) (0,0.85) (0,1)
       in a frame with the sharp corner at the origin, scaled by the setback s
```

| quantity | `g2_quintic` | `circular` |
|---|---|---|
| curvature at the tangent points | **0** (true G2 with the straight edge) | `1/s` (G1 only) |
| radius of curvature at the tangent points | ∞ | `s` |
| **minimum** radius of curvature | **`0.72184 · s`** (at mid-blend) | `s` (constant) |
| corner area removed | `0.163338 · s²` | `0.214602 · s²` |
| reference, `s = 52.5` | R: ∞ → **37.90 mm** → ∞ | constant 52.5 mm |

The `0.72184 · s` figure is not cosmetic — it is the ceiling on every downstream 3D
blend radius *and* on the forming gap (§5, `E-BLEND-011`, `E-GAP-025`). It is
**tighter** than the circular intuition, so switching `corner_style` can turn a
valid design invalid; the validator must be re-run on that switch.

Verification at the reference's `s = 52.5`: the analytic template gives a plan area
of 16 574.20 mm²; sectioning the STEP solid gives 16 574.19 mm². A circular-arc
obround of the same bounding box gives 16 009.01 mm² — a 3.5 % difference, and up
to 3.2 mm of positional deviation at mid-blend.

### 2.3 `leather` — the material being formed

| field | type | default | range | notes |
|---|---|---|---|---|
| `thickness` | float mm | 3.0 | 0.4 … 8.0 | the reference's 3 mm gap implies ≈7–8 oz veg-tan |
| `compression` | float fraction | 0.0 | 0.0 … 0.40 | intentional squeeze of the wet leather |

A `weight_oz → thickness_mm` helper (1 oz ≈ 0.4 mm) belongs in the UI, not the
schema.

### 2.4 `fit` — forming clearance

| field | type | default | range | notes |
|---|---|---|---|---|
| `clearance` | float mm | 0.0 | −0.5 … 2.0 | added to the gap; negative = deliberate interference |
| `gap_override` | float mm \| null | `null` | 0.2 … 12 | escape hatch: set the gap directly, bypassing the formula |

```
gap = clearance + thickness × (1 − compression)          # or gap_override
```
Reference: `3.0 = 0.0 + 3.0 × (1 − 0.0)`.

### 2.5 `mold` — how the two plates are built

| field | type | default | range | notes |
|---|---|---|---|---|
| `flange_width` | float mm | 30.0 | 8 … 120 | measured from the **plug**; the female's 27 mm is derived |
| `base_plate_thickness` | float mm | 15.0 | 3 … 60 | male |
| `cavity_plate_thickness` | float mm | 25.0 | 3 … 150 | female; `== depth` in the reference (flush top) |
| `plug_root_fillet` | float mm | 1.2 | 0 … — | **circular** rolling-ball fillet in the reference — cylindrical faces on the straights, exact circular sweeps at the corners. Deliberately a different vocabulary from the other blends. |
| `cavity_entry_radius_top` | float mm | 3.0 | 0 … — | the blended rim in the reference |
| `cavity_entry_radius_bottom` | float mm | 0.0 | 0 … — | **sharp** in the reference; see [`architecture.md` §2.5](./architecture.md#25-the-relationships-that-actually-matter) |
| `entry_blend_style` | `CornerStyle` | `g2_quintic` | — | the reference uses the same template as the plan corners, setback 3.0 |
| `flange_relief_depth` | float mm | 0.0 | 0 … — | recess for the leather flange; the reference has none |
| `plate_edge_chamfer` | float mm | 0.0 | 0 … 5 | print-friendly break; 0 in the reference |
| `parts` | `{male: bool, female: bool}` | both true | — | which halves to build |

Both cavity entry radii are exposed because the reference's usage orientation is
genuinely ambiguous from the geometry — see
[`architecture.md` §2.5](./architecture.md#25-the-relationships-that-actually-matter).

### 2.6 `features` — optional manufacturing features

```python
class AlignmentPins(BaseModel):        # NOT in the reference — a real improvement
    enabled: bool = False
    pattern: Literal["diagonal_pair","four_corners","edge_midpoints"] = "four_corners"
    diameter: float = 6.0
    height: float = 8.0                # protrusion above the male plate
    inset: float = 15.0                # from both plate edges
    integral: bool = True              # printed onto the male vs separate dowels

class ClampHoles(BaseModel):           # the reference's 2 × Ø6
    enabled: bool = True
    pattern: Literal["diagonal_pair","four_corners","perimeter"] = "diagonal_pair"
    diameter: float = 6.0
    inset: float = 15.0
    in_male: bool = False              # reference: female only
    in_female: bool = True
    top_chamfer: float = 2.0           # 2 mm × 45°
    counterbore: float | None = None

class PryNotches(BaseModel):           # the reference's 2 × 15×15×8
    enabled: bool = True
    pattern: Literal["diagonal_pair","four_corners"] = "diagonal_pair"
    size_x: float = 15.0
    size_y: float = 15.0
    depth: float = 8.0                 # down from the female's top face

class Vents(BaseModel):                # NOT in the reference; wet-forming drainage
    enabled: bool = False
    diameter: float = 2.0
    count: int = 4
    location: Literal["plug_top","cavity_floor_corners"] = "plug_top"

class Label(BaseModel):                # NOT in the reference (the render text is
    enabled: bool = False              # a slicer overlay, not geometry)
    text: str = ""
    depth: float = 0.6
    engrave: bool = True               # engrave vs emboss
    face: Literal["male_plate","female_top"] = "male_plate"
```

Reference note: clamp holes sit on **one** diagonal and pry notches on the
**other** — the female has C2 rotational symmetry, not mirror symmetry. The
`diagonal_pair` patterns must encode which diagonal, so the two feature sets do
not collide (`E-FEAT-053`).

### 2.7 `manufacturing` — printer-side reality

| field | type | default | notes |
|---|---|---|---|
| `pin_fit_clearance` | float mm | 0.20 | pin ↔ hole; **not** the leather gap |
| `min_wall` | float mm | 2.0 | validation floor for every feature-to-edge distance |
| `nozzle_diameter` | float mm | 0.4 | |
| `bed_size` | `{x,y,z}` mm | 256/256/256 | printability warnings only |

### 2.8 `export`

| field | type | default | notes |
|---|---|---|---|
| `formats` | `list["stl","3mf","step"]` | all three | STEP is native to CadQuery; 3MF needs `lib3mf`/`trimesh` |
| `linear_deflection` | float mm | 0.05 | `0.25` for the preview tolerance preset |
| `angular_deflection` | float rad | 0.20 | |

---

## 3. Reference expressed as parameters

`presets/ref-4x7.json` — the exact reconstruction target for Stage 2.

```json
{
  "schema_version": "1.0.0",
  "meta": { "name": "ref-4x7-wetmold" },
  "tray": {
    "profile": { "kind": "obround", "corner_style": "g2_quintic" },
    "datum": "inner",
    "length": 175.0, "width": 105.0, "depth": 25.0,
    "draft_angle": 0.0, "draft_mode": "both",
    "floor_radius": 5.0, "floor_blend_style": "g2_quintic"
  },
  "leather": { "thickness": 3.0, "compression": 0.0 },
  "fit": { "clearance": 0.0, "gap_override": null },
  "mold": {
    "flange_width": 30.0,
    "base_plate_thickness": 15.0,
    "cavity_plate_thickness": 25.0,
    "plug_root_fillet": 1.2,
    "cavity_entry_radius_top": 3.0,
    "cavity_entry_radius_bottom": 0.0,
    "entry_blend_style": "g2_quintic",
    "flange_relief_depth": 0.0,
    "plate_edge_chamfer": 0.0,
    "parts": { "male": true, "female": true }
  },
  "features": {
    "alignment_pins": { "enabled": false },
    "clamp_holes": {
      "enabled": true, "pattern": "diagonal_pair", "diameter": 6.0,
      "inset": 15.0, "in_male": false, "in_female": true, "top_chamfer": 2.0
    },
    "pry_notches": {
      "enabled": true, "pattern": "diagonal_pair",
      "size_x": 15.0, "size_y": 15.0, "depth": 8.0
    },
    "vents": { "enabled": false },
    "label": { "enabled": false }
  },
  "manufacturing": { "pin_fit_clearance": 0.20, "min_wall": 2.0,
                     "nozzle_diameter": 0.4, "bed_size": {"x":256,"y":256,"z":256} },
  "export": { "formats": ["stl","3mf","step"],
              "linear_deflection": 0.05, "angular_deflection": 0.20 }
}
```

Note `plug_root_fillet` is a **circular** rolling-ball fillet while the plan
corners, the floor blend and the entry blend all use the **same G2 quintic
template** at three different setbacks (52.5 / 5.0 / 3.0). That asymmetry is not an
accident of export — it is visible in the STEP face types (cylinders and
rational-quadratic sweeps for the root fillet; non-rational deg-5 surfaces
everywhere else) and must survive into the schema.

This preset is the Stage 2 fidelity target and should reproduce
`male_tray_mold.step` and `female_tray_mold.step` to within 0.05 mm. The clamp
holes and pry notches exist only in the STL revision, so with
`features.clamp_holes.enabled = false` and `features.pry_notches.enabled = false`
this preset must instead match the STEP female exactly (517.830 cm³).

---

## 4. Derived quantities

Computed in `derive.py`, returned by `POST /validate`, displayed by the UI,
**never** accepted as input.

| derived | formula | reference |
|---|---|---|
| `gap` | `clearance + thickness × (1 − compression)` | 3.000 |
| `cavity_length` | bbox of the **true 3D offset** of the plan profile by `gap` | 181.0032 |
| `cavity_width` | bbox of the same offset | 111.0032 |
| `cavity_corner_setback` | nominal `corner_setback + gap`; the true offset differs from the template at that setback by up to 0.18 mm | 55.5 (nominal) |
| `plate_length` | `length + 2·flange_width` | 235.0 |
| `plate_width` | `width + 2·flange_width` | 165.0 |
| `female_flange_width` | `flange_width − gap` | 27.0 |
| `closed_height` | `base_plate_thickness + cavity_plate_thickness` | 40.0 |
| `plug_top_length/width` | `length − 2·floor_radius − 2·depth·tan(draft)` | 165 × 95 |
| `corner_radius_min/max` | `g2_quintic`: `0.72184·s`, ∞; `circular`: `s`, `s` | 37.90 / ∞ |
| `gap_actual_min/max` | measured plug↔cavity distance (§6) | 3.000 / 3.000 |
| `volume_male`, `volume_female` | solid volume | 993.80 / 517.83 cm³ (STEP, no features); 512.68 cm³ with features |
| `filament_estimate` | volume × infill model | — |
| `bed_fit` | `plate_* ≤ bed_*` per part | ok |
| `min_wall_actual` | min over all feature-to-edge/cavity distances | — |
| `vertical_wall_height` | `depth − floor_radius − plug_root_fillet` | 18.8 |

`gap_actual_min` and `gap_actual_max` must both equal `gap`: the reference achieves
3.000 mm uniformly (measured 2.998–3.003 over 3600 sampled points, i.e. sampling
noise). The cavity is a **true geometric offset** of the plug, so this is a tight
invariant, not a loose one — see
[`architecture.md` §7.1](./architecture.md#71-the-cavity-must-be-a-true-offset-new-1-risk).
If a build reports a spread wider than 0.01 mm, the offset silently failed.

---

## 5. Dependencies and invalid combinations

### 5.1 Dependency graph

```
leather.thickness ┐
leather.compression├─► gap ─┬─► cavity_length / cavity_width / cavity_corner_setback
fit.clearance     ┘         ├─► female_flange_width ──► feature placement limits
                            └─► draft interaction (E-GAP-024)

tray.length ─┬─► corner_radius ceiling (E-SHAPE-001)
tray.width  ─┤       │
             │       └─► corner_radius_min = 0.72184·s ─► blend + offset ceiling
             │                                             (E-BLEND-011, E-GAP-025)
             ├─► plate_length / plate_width ──► bed_fit, feature inset limits
             └─► plug_top_* (with depth, draft, floor_radius)  (E-DRAFT-031)

tray.depth ─┬─► floor_radius ceiling (E-BLEND-010)
            ├─► cavity_plate_thickness floor (E-MOLD-040)
            └─► draft × depth ──► gap interaction (E-GAP-024)

mold.flange_width ──► every feature inset window (E-FEAT-051/052/056)
features.* ──► mutual collision checks (E-FEAT-053/058)
```

The two clearances that must never be confused: `gap` (forming, ≈3 mm) and
`manufacturing.pin_fit_clearance` (printer, ≈0.2 mm).

### 5.2 Diagnostics

Every rule returns a machine-readable code, a severity, the offending field path
and the numbers involved — so the UI can render it against the right input.
`error` refuses the build; `warning` builds and flags.

| code | sev | condition | why |
|---|---|---|---|
| `E-SHAPE-001` | error | `corner_radius > min(L,W)/2` | setback cannot exceed the half-width |
| `E-SHAPE-004` | error | any of `length,width,depth ≤ 0` | |
| `W-SHAPE-003` | warn | `corner_radius < 3 × leather.thickness` | leather will not take that corner cleanly |
| `W-SHAPE-005` | warn | `corner_radius == 0` | sharp plan corners tear wet leather |
| `E-BLEND-010` | error | `floor_radius > depth / 2` | no room in Z |
| `E-BLEND-011` | error | `floor_radius ≥ corner_radius_min` (`0.72184·s` for `g2_quintic`, `s` for `circular`) | blend exceeds local curvature → OCC failure or self-intersection, **not** a clamped result. The `g2_quintic` ceiling is ~28 % tighter than `circular`, so switching style can invalidate a working design — re-validate on that switch. |
| `E-BLEND-012` | error | `min(L,W) − 2 × floor_radius ≤ 0` | the plug's top face degenerates |
| `E-BLEND-013` | error | `entry_top + entry_bottom > cavity_plate_thickness` | the two rim blends meet |
| `E-BLEND-014` | error | `plug_root_fillet > min(flange_width, base_plate_thickness)` | |
| `E-BLEND-015` | error | `floor_radius + plug_root_fillet ≥ depth` | no vertical wall left on the plug |
| `E-GAP-020` | error | `gap ≤ 0` | plug larger than cavity |
| `W-GAP-021` | warn | `gap < 0.4` | below FDM resolution; the halves will fuse |
| `W-GAP-022` | warn | `gap > 1.5 × leather.thickness` | loose forming, poor definition |
| `E-GAP-023` | error | `gap ≥ min(L,W)/2` | nonsensical |
| `E-GAP-025` | error | `gap ≥ corner_radius_min` | a 2D offset larger than the tightest concave curvature self-intersects |
| `E-GAP-026` | error | the built offset's measured distance to the source deviates from `gap` by > 0.01 mm | OCC offset silently degraded; refuse rather than ship a wrong gap |
| `E-GAP-024` | error | `draft_mode ≠ "both"` and `depth × tan(draft) ≥ gap` | the drafted wall closes the gap before full depth |
| `E-DRAFT-030` | error | `draft_angle` outside `[0, 15]` | |
| `E-DRAFT-031` | error | `min(L,W) − 2·depth·tan(draft) ≤ 2 × floor_radius` | the plug tapers to nothing |
| `W-DRAFT-032` | warn | `draft_angle == 0` | matches the reference, but demolding is harder |
| `E-MOLD-040` | error | `cavity_plate_thickness < depth` unless `allow_protrusion` | the plug would stick out of the die |
| `E-MOLD-041` | error | `female_flange_width < min_wall` | i.e. `flange_width − gap < min_wall` |
| `W-MOLD-043` | warn | `flange_width < 15` | no room for clamps or notches |
| `E-FEAT-050` | error | clamp hole to cavity wall `< d/2 + min_wall` | hole breaks into the cavity |
| `E-FEAT-051` | error | `inset < d/2 + min_wall` | hole breaks the plate edge |
| `E-FEAT-052` | error | `d/2 + top_chamfer > inset − min_wall` | the chamfer breaks out |
| `E-FEAT-053` | error | a pry notch footprint overlaps a clamp hole | reference avoids this by using opposite diagonals |
| `E-FEAT-054` | error | `pry_notch.depth ≥ cavity_plate_thickness` | notch severs the plate |
| `E-FEAT-055` | error | notch footprint reaches the cavity outline | |
| `E-FEAT-056` | error | `pin.diameter + 2 × min_wall > flange_width` | pin does not fit the flange |
| `E-FEAT-057` | error | `pin.height > cavity_plate_thickness` | pin cannot be received by the female |
| `E-FEAT-058` | error | alignment pin and clamp hole footprints overlap | |
| `W-FEAT-059` | warn | `alignment_pins.enabled` and fewer than 2 pins | one pin gives no rotational lock |
| `W-FEAT-061` | warn | no alignment pins and no clamp holes in **both** halves | reproduces the reference's loose registration |
| `E-MFG-073` | error | any computed wall `< 2 × nozzle_diameter` | unprintable |
| `W-MFG-070` | warn | `plate_length > bed.x` or `plate_width > bed.y` | will not fit the configured bed |
| `W-MFG-071` | warn | estimated volume > 1500 cm³ | the reference male alone is 994 cm³ |
| `W-MFG-072` | warn | `pin_fit_clearance < 0.10` | pins will not assemble on FDM |

`W-FEAT-061` deliberately fires on the reference itself: nothing but the plug
locates the two halves, and the plug has `gap` of slop until leather fills it.
That is a faithful reproduction of a real weakness, so it warns rather than
errors.

### 5.3 Rules that must be validated, never caught

`E-BLEND-011`, `E-BLEND-012`, `E-DRAFT-031` and `E-GAP-024` all describe states
where OCC either throws or — worse — returns a self-intersecting solid that
tessellates into a plausible-looking but unprintable mesh. They must be checked
arithmetically *before* the kernel is invoked. A `try/except` around
`fillet()` is not validation.

---

## 6. Verification hooks

The schema is only worth as much as the checks behind it. Two of the derived
values above exist specifically to be tested:

- `gap_actual_min/max` is measured with `BRepExtrema_DistShapeShape` between the
  built plug and cavity walls — the same probe used to reverse-engineer the
  reference. It must equal `gap` within **0.01 mm everywhere**, not just on the
  straight runs; the reference meets that, so anything looser is hiding a bug.
- The `g2_quintic` primitive gets its own unit tests independent of any mold:
  the knot vector and 8 poles, zero curvature at both endpoints, minimum radius
  of curvature `0.72184 · s`, and removed corner area `0.163338 · s²`.
- `min_wall_actual` is measured from the built solid, not from the input
  arithmetic, so a feature-placement bug cannot hide behind a passing rule.

---

## 7. Versioning

- `schema_version` (semver) is stored in every params document.
- `MODEL_VERSION` in `traymold/version.py` changes whenever the *geometry* for
  unchanged parameters changes; it participates in the cache key
  ([`architecture.md` §4.6](./architecture.md#46-determinism-and-caching)).
- Additive fields with defaults → minor bump, no migration.
- Any change to meaning (e.g. redefining `corner_radius` from setback to true
  radius) → major bump plus an explicit migration function; old documents are
  never reinterpreted silently.
- Exported STEP/3MF carry `schema_version`, `MODEL_VERSION`, the kernel versions
  and the `params_hash` in their metadata, so a printed part can be traced back
  to the exact inputs that produced it.
