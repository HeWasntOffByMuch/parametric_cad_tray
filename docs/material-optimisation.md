# Printing the mold with less material

Every number here is produced by [`tools/print_study`](../tools/print_study/),
on the `ref-4x7` preset at export quality, and can be reproduced with
`python3 tools/print_study/study.py`.

---

## The short answer

The thickness is not where the material goes. **The core density is.**

At 6 walls and 30 % infill the pair costs about **796 g** of PLA. Changing
nothing but the slicer settings — 3 walls, 10 % gyroid — takes it to **404 g**,
and adding back the density and the top layer that are actually load-bearing
costs **35.6 cm³** of that saving. So:

| | cm³ | g | vs now |
|---|---:|---:|---:|
| as printed today, 6 walls / 30 % | 641.6 | 796 | — |
| 4 walls / 15 %, no geometry change | 412.9 | 512 | −36 % |
| **3 walls / 10 % + reinforcement regions, no geometry change** | **361** | **448** | **−44 %** |
| the same, with `flange_width` 30 → 26 | 335 | 415 | −48 % |

Making the female thinner — the change the brief starts from — is the one lever
that **costs more than it saves**, and §2 is the arithmetic for why.

---

## 1. Where the 796 g goes

```
male     solid  994.2 cm3   surface 1004.3 cm2   (746 flat / 211 upright)
         shell  140.3       core  854.0       PRINTED 396.4 cm3 = 492 g
female   solid  512.4 cm3   surface  742.0 cm2   (397 flat / 319 upright)
         shell  130.6       core  381.7       PRINTED 245.1 cm3 = 304 g
```

The shell — perimeters plus top and bottom solid layers — is only 271 cm³ of the
642. **The other 371 cm³ is infill**, and it is the largest single line item in
the print by a wide margin. Nearly 60 % of the plastic in these parts is lattice
sitting in the middle of a plate, and 30 % is a lot of lattice.

Neither half needs support, which is why those figures are the whole material
story rather than most of it. `print_oriented` already puts each part's flat
face on the bed and every one-sided feature pointing up: the female's entry
blend, pry notches and clamp chamfers all open upward after the flip, and the
male's plug, root fillet and floor round-over are all self-supporting from a
base plate that is already the lowest face. See `architecture.md` §7.10.

The estimator behind those numbers is a shell-plus-infill model, not a slicer:
faces are split by orientation (a vertical face gets `perimeters × width`
≈ 2.7 mm, a horizontal one gets `layers × height` ≈ 1.0 mm — they differ by 2.7×
on this geometry), the shell is integrated over them, and the remainder is
multiplied by the infill density. It is worth about ±15 % in absolute terms.
Ratios between two plans are far better than that, because the same
approximation applies to both, and every conclusion below is a ratio.

---

## 2. The female is thick, and that is the cheap part

A printed plate is a sandwich panel: two solid skins with a lattice between
them. Bending stiffness goes as the *cube* of the section depth and the skins own
almost all of it, because they sit furthest from the neutral axis — on the 25 mm
female the core is 29 % of the section at 30 % infill and 5 % at 10 %. Mass goes
as the *first power* of depth for the skins, and linearly in density for the
core, which is nearly all of the volume. Those two facts point in opposite
directions, and the table settles it — second moment per mm of width, against
the mass of a 100 × 100 mm patch:

| section | I mm⁴/mm | g/dm² | I per gram |
|---|---:|---:|---:|
| female 25 mm, 5 skins, 30 % — **now** | 404.3 | 110.4 | 3.66 |
| female 25 mm, 5 skins, 10 % | 304.2 | 53.3 | 5.71 |
| **female 25 mm, 8 skins, 8 %** | **447.9** | **61.3** | **7.31** |
| female 12 mm, 5 skins, 30 % | 70.2 | 62.0 | 1.13 |
| female 12 mm, **solid** | 144.0 | 148.8 | 0.97 |
| male plate 15 mm, 5 skins, 30 % — now | 119.1 | 73.2 | 1.63 |
| male plate 15 mm, 5 skins, 10 % | 101.1 | 40.9 | 2.47 |
| **male plate 15 mm, 8 skins, 8 %** | **145.8** | **51.4** | **2.84** |
| male plate 10 mm, 5 skins, 30 % | 45.6 | 54.6 | 0.83 |

(Core modulus taken as ρ^1.8, Gibson & Ashby for a bending-dominated open cell —
the conservative end for gyroid. At ρ^1.0 every row below the first gets
*better*, so the exponent is not load-bearing.)

Read the three female rows together:

* **25 mm at 8 skins / 8 % is stiffer than 25 mm at 5 skins / 30 %** — 448
  against 404 — **at 56 % of the mass.** Thickening the skins and emptying the
  core is a free upgrade in both directions at once.
* **A 12 mm female, printed solid, is less than half as stiff as the sparse
  25 mm one and weighs 2.8× as much.** There is no density at 12 mm that
  recovers the section: solid is its ceiling, 144 against 304 for 25 mm at
  10 % — and against 448 for 25 mm at 8 skins and 8 %.

So the intuition in the brief — the female is as thick as the plug is tall, and
only its bottom corner forms leather — is **right about forming and wrong about
material**. The 25 mm is not there to form leather. It is the cheapest bending
stiffness available, because on an FDM part height costs skins once and core
density costs material everywhere. Halving the height throws away 5.8× the
stiffness (404 → 70 at unchanged settings) to recover material that dropping the
infill gives up for free.

The measured cross-table says the same thing in grams (cm³, both halves):

| geometry | 6w/30 % | 4w/15 % | 3w/10 % | 3w/8 % + 8 skins |
|---|---:|---:|---:|---:|
| baseline f25 b15 fl30 | 641.6 | 412.9 | **325.7** | 364.6 |
| female 12 mm | 528.1 | 346.0 | 277.7 | 321.5 |
| female 8 mm | 492.5 | 324.6 | 262.1 | 306.9 |
| base plate 10 mm | 575.9 | 377.7 | 301.4 | 344.1 |
| flange 28 mm | 616.9 | 397.0 | 312.8 | 349.4 |
| flange 26 mm | 592.7 | 381.5 | 300.3 | 334.5 |
| flange 24 mm | 569.0 | 366.2 | 287.9 | 319.9 |
| flange 26 + f12 + b10 | 431.6 | 288.7 | 234.4 | 276.1 |

Note how the columns compress. Thinning the female saves 114 cm³ at 30 % infill
and only 48 cm³ at 10 %, because **geometry savings and infill savings compete
for the same core material**. Once the core is nearly empty, removing core
volume is worth only a tenth of itself. Take the infill saving first; most of
the geometry levers stop being worth their risk afterwards.

### 2a. What `E-MOLD-040` is really protecting

```
cavity_plate_thickness < tray.depth  ->  "the plug would protrude"
```

The rule blocks the whole question, and the reason it gives is an assembly
observation, not a failure: the plug sticking out of the top of the female harms
nothing — the cavity is a through hole, the clamp bores sit 9 mm clear of it,
and the female's bed face is the flat one either way. The part builds cleanly at
12 mm and at 8 mm (both rows above are real builds, with the rule stood down in
one named function of `study.py`).

There is a genuine forming question underneath it, which is how much of the draw
the cavity wall has to guide before the leather is free to buckle outward at the
corners — and a real structural one, which §2 has just answered against
thinning. The recommendation is therefore **not** to relax the rule for material
reasons. If it is relaxed later it should be for forming reasons, phrased as the
engagement depth it actually is:

```
mold.cavity_engagement_depth: float | None = None      # None -> tray.depth
E-MOLD-040:  cavity_plate_thickness < engagement_depth(params)
```

That reproduces today's rule exactly while `None` is the default, and turns a
shorter female from something the schema forbids into something someone has to
ask for by name. It is a parameter-model change, not a geometry one — the cavity
is already lofted from z = −1 to z = t + 1 and does not care how tall the plug
is.

---

## 3. Where the uniform infill is provably not needed

Three things load these parts, and none of them is uniform.

**Bending of the plates.** Settled in §2: the skins carry nearly all of it.
10 % everywhere, and spend the difference on top and bottom layers.

**Compression under the clamps.** This is the one place where infill density
*is* the strength, and the brief is right to single it out. An M6 at a firm
2 N·m is roughly 1.7 kN of preload; through a Ø18 washer that is 226 mm² of
bearing and about **7.4 MPa**.

How much a lattice takes is a sizing estimate rather than a measurement here.
Solid PLA is 60–70 MPa in compression; a lattice falls between the conservative
open-cell relation (≈ 0.3 ρ^1.5 σ) and a linear upper bound (ρ σ), and printed
gyroid sits well inside that band rather than at either end:

| infill | plausible range | vs 7.4 MPa |
|---|---|---|
| 10 % | 0.6 – 6 MPa | under the demand even at the optimistic end |
| 30 % | 3 – 18 MPa | straddles it |
| 70 % | 10 – 42 MPa | clears it at the conservative end |

The band is wide, but it only has to answer one question and the answer is not
close: 10 % is not a clamping surface and 70 % is. The demand is also the
cheapest thing on the page to cut — a Ø25 washer instead of Ø18 halves it to
3.7 MPa on its own — so do both.

Reinforcing is cheap: a Ø18 column through the full plate at each clamp is
**12.7 cm³ in the female and 7.6 cm³ in the male**, and taking those from 10 %
to 70 % costs **12.2 cm³**, under 4 % of the print. Worth a coupon test before
anyone trusts a number in that table, and worth doing regardless of how the
coupon lands.

**Pressure on the forming faces.** These need backing least of all, which is
counter-intuitive enough to be worth stating: both forming walls are *closed
loops*. The cavity wall is a ring in hoop compression and the plug wall a closed
box; neither is in bending, and a membrane-loaded closed section is stiff out of
all proportion to its thickness. Three perimeters is 1.35 mm of solid PLA backed
by a ring — that is not the weak part of this mold. A 6 mm backing band behind
both walls would cost **44.2 cm³** at 40 %, which buys nothing structural.
Reject it. (If infill ghosting shows on the forming surface, the fix is more
perimeters on that wall, not denser infill behind it — cheaper and it addresses
the actual cause.)

The one horizontal forming surface *does* need support: the plug's top face
spans 165 × 95 mm, and top solid layers over a 10 % lattice will dimple. A 5 mm
band under it at 35 % is the cost of a good forming face.

### The region ledger

Global plan: **3 perimeters, 10 % gyroid, 5 bottom / 6 top solid layers.**

| region | volume | change | Δ |
|---|---:|---|---:|
| 6th top solid layer, both parts | 549 cm² up-facing | 5 → 6 layers | +11.0 |
| clamp columns, female — Ø18 × 25 | 12.7 cm³ | 10 % → 70 % | +7.6 |
| clamp columns, male — Ø18 × 15 | 7.6 cm³ | 10 % → 70 % | +4.6 |
| plug core, under the top band | 276.0 cm³ | 10 % → 7 % | −8.3 |
| 5 mm band under the forming face | 82.9 cm³ | 10 % → 35 % | +20.7 |
| *rejected: cavity-wall backing, 6 mm* | *77.9 cm³* | *10 % → 40 %* | *+23.4* |
| *rejected: plug-wall backing, 6 mm* | *69.4 cm³* | *10 % → 40 %* | *+20.8* |
| **net** | | | **+35.6** |

**325.7 + 35.6 = 361.3 cm³ ≈ 448 g**, against 796 g today, with more compressive
strength at the clamps than the current uniform 30 % provides and a better
forming face than it gives.

The plug core cannot go to 0 %: the 5 mm band above it would have nothing to
print on. 7 % gyroid is a cell roughly every 9 mm, which the band bridges
comfortably.

---

## 4. Skeletonizing: what pays, and what does not

It mostly does not, and the reason is specific to FDM.

**A CAD pocket and low infill are the same saving, claimed twice.** A relief
counterbore in the female — a 10 mm forming land, then an 8 mm wide relief above
it — removes 63.1 cm³ of solid:

| | 6 walls / 30 % | 3 walls / 10 % |
|---|---:|---:|
| printed, before | 245.1 | 128.5 |
| printed, after | 227.6 | 123.1 |
| **saving** | **−17.5** | **−5.4** |

63 cm³ of geometry buys 17.5 cm³ of filament at today's settings and **5.4 cm³
once the infill is already low**. The core it removes was only 30 % full, then
only 10 % full. Meanwhile it is real B-rep work on a boolean pipeline that
`docs/architecture.md` §7.8a documents as fragile, and it adds a slicer-visible
ledge. Not worth it.

(One thing this case does *not* show, which is worth recording because the naive
estimate gets it backwards: the counterbore costs almost nothing in extra shell —
+2.0 cm³. It **moves** the cavity wall outward rather than adding a wall. A
pocket that opens a *new* enclosed void is the expensive kind, because a slicer
puts full solid layers on every face of an internal void; a modifier region does
not, which is the whole structural argument for §5.)

**Ribs are worse than infill, not better.** A rib grid modelled in CAD gets its
own perimeters on both faces and its own top surface to bridge. Gyroid infill is
already a rib grid that the slicer draws for free, with no skins. The only thing
CAD ribs add over infill is directionality, and nothing here is loaded
directionally enough to pay for it.

**Shrinking the envelope does pay**, because it removes skin as well as core:

| | solid | 6w/30 % | 3w/10 % |
|---|---:|---:|---:|
| rectangular plate — now | 1506.6 | 641.6 | 325.7 |
| outline follows the profile, + clamp ears | 1342.8 | 578.5 | 292.8 |

A plate whose outline is `offset(profile, flange_width)` with a circular ear at
each clamp saves **11 % of the solid and 10 % of the print, and it holds up at
low infill** (−33 cm³ at 10 %, against −5 for the counterbore) — exactly because
it deletes skin, not just core. It also makes the mold look like the tray. It is
the only skeletonizing idea on this list worth building, and it is still second
priority behind the settings.

`flange_width` 30 → 26 is the same lever without any new geometry: −49 cm³ at
today's settings and −25 at 10 % — again, it holds up at low infill because a
smaller plate is less skin as well as less core. It changes the finished tray's
flange, so it is a design decision rather than a free one, and see §6 before
going below 26.

---

## 5. 3MF with print settings: what it would take

**Effort: roughly 3 days, ~800 lines with tests, and it touches nothing that
builds geometry.** `docs/api.md` already calls 3MF "a self-contained addition to
`exporters.write_artifacts`", and that is accurate.
[`tools/print_study/threemf_prototype.py`](../tools/print_study/threemf_prototype.py)
is a working one — 90 lines of writer and a 60-line sketch of the solver — and
it writes the reference pair with modifiers today:

```
3D/3dmodel.model                  24,552,072 ->  4,310,758
Metadata/Slic3r_PE_model.config        1,953 ->        360
TOTAL                                             4,311,500 bytes
object male:   male (ModelPart, 208,880 tri), forming-face-backing (ParameterModifier, 12 tri)
object female: female (ModelPart, 137,102 tri), clamp-a, clamp-b (ParameterModifier, 1,004 tri each)
```

Note the size: **4.1 MB against 16.5 MB for the STL pair**, a 4× reduction, from
the zip alone. That is worth having even with no settings in it — it is
bandwidth off every export and off the artifact cache.

### What makes it tractable

The format carries a modifier as a *volume* inside an object: all volumes'
triangles concatenate into one mesh, and `Metadata/Slic3r_PE_model.config` names
each volume by its triangle range plus a `volume_type` of `ModelPart` or
`ParameterModifier`, with its own settings. That is it. No lib3mf, no trimesh —
`zipfile` and `xml.etree`, both stdlib, over `Shape.tessellate`, which the STL
exporter already calls.

**Emit per-object and per-volume overrides only; never a global profile.**
`Metadata/Slic3r_PE.config` — the full print profile — is hundreds of keys,
differs by slicer version and printer, and would stamp on whatever preset the
user has tuned. Overrides merge onto their own preset instead. This is both far
less code and the behaviour someone actually wants, and it is what makes the
export version-tolerant. PrusaSlicer, SuperSlicer and Orca all read this layout;
Bambu Studio's native flavour (`Metadata/model_settings.config`, per-object mesh
files) would be a second emitter of maybe 150 lines if it is ever wanted.

Key names differ between families — `fill_density` / `perimeters` /
`top_solid_layers` in PrusaSlicer against `sparse_infill_density` / `wall_loops`
/ `top_shell_layers` in Orca. That is a dictionary, not a research project.

### Shape of the work

| | |
|---|---|
| `traymold/threemf.py` | the writer: objects, volumes, triangle spans, the two config flavours. ~200 lines |
| `traymold/printplan.py` | **the solver**: `params -> [Region(solid, settings)]`. ~250 lines |
| `exporters.write_artifacts` | a `"3mf"` branch beside `"stl"`. ~30 lines |
| `api.Format`, `models.BuildRequest.formats`, `ExportPanel` | add `"3mf"` to three literals and one checkbox list |
| tests | zip structure, triangle spans consistent with the mesh, each region non-empty after intersection with its part, and every region inside the part's bounding box |

The solver is the interesting part and it is also the safe part. Every region is
a **primitive** — a cylinder at a clamp point, a prism between two offsets of the
base profile, a box under the forming face — positioned from values `derive()`
already computes. It runs no booleans against the part, so none of the
fragility in `architecture.md` §7.8a is in reach: a bad region is a region that
does nothing, not a build that fails. `manufacturing.nozzle_diameter` is
already in the schema and read by nothing at all — extrusion width is the one
thing a print solver cannot do without, so this is the job it was waiting for.

### The one trap

`print_oriented` turns the female over on the way to the bed, and a rotation
about X maps (x, y, z) → (x, −y, −z). A modifier built in assembly coordinates
is **not** turned over with it:

```
clamp-NW modifier centre   assembly (-102.5, +67.5)   after print_oriented (-102.5, -67.5)
```

Build a clamp column at the assembly-frame bore and it lands on the opposite
diagonal of the printed part, reinforcing solid plastic while the real bore sits
in 10 % lattice. This is the same chirality that `architecture.md` §7.10 warns
about for features, and it wants the same treatment: every region goes through
`print_oriented` with the part it belongs to, and a test that reads the diagonal
off the geometry rather than off the transform.

---

## 6. A bug found on the way

There is no rule relating `features.clamp_holes` to the flange it has to sit in.
The hole is placed at `plate/2 − inset` and the cavity ends at
`profile/2 + forming_gap`; nothing checks that the first clears the second.

```
flange  hole x  cavity x    land      female  shells
    30   102.5      90.5     +9.0    512.4 cm3   1/1
    26    98.5      90.5     +5.0    434.0 cm3   1/1
    24    96.5      90.5     +3.0    396.0 cm3   1/1
    20    92.5      90.5     -1.0    322.4 cm3   1/1   <- bore opens into the cavity
```

At `flange_width` 20 with the default inset and Ø6 the bore breaks through into
the cavity. The result is still a single closed shell, so `_checked` passes it,
the volume bound passes it, and the user gets a mold with a slot in the forming
wall and no diagnostic. It wants a rule in the same family as `E-MOLD-041`:

```
E-FEAT-0xx  plate_length/2 - inset - diameter/2 - (length/2 + gap) < min_wall
```

checked on both axes, for clamp holes and alignment pins alike. This matters
more once `flange_width` becomes a material lever (§4).

---

## 7. Recommended order

1. **Change the slicer settings. Nothing else.** 3 perimeters, 10 % gyroid,
   5 bottom / 6 top. 796 g → 418 g, today, with no code and no rebuild. Then
   clamp through a wide washer, or hand-place two high-density modifiers, until
   (2) lands and places them for you.
2. **The 3MF export with a print solver.** ~3 days, additive, no B-rep risk,
   and it turns (1) into something the app ships rather than something a user
   has to know. Ships the −44 % as a default, plus 4× smaller artifacts.
3. **The clamp-hole clearance rule.** Half a day. Independent of everything
   else, and a prerequisite for letting anyone pull `flange_width` down.
4. **The profile-following plate outline.** A further −10 %, holds up at low
   infill, and improves how the mold looks. Real geometry work on the fragile
   path — schedule it on its own.
5. **Leave `cavity_plate_thickness` alone**, and re-open it as
   `cavity_engagement_depth` only if forming trials show the cavity wall does
   not need to guide the full draw. That is a forming question; on material it
   loses either way, and §2 is why.

Not recommended: relief counterbores, CAD rib grids, and any pocket whose
purpose is to remove core that 10 % infill has already removed.
