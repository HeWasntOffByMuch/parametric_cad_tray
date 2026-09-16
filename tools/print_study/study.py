"""Every number in docs/material-optimisation.md.

    python3 tools/print_study/study.py            all of it, ~3 min
    python3 tools/print_study/study.py baseline   one section

Sections: baseline, sections, levers, outline, regions, ledger, bug.

E-MOLD-040 refuses a cavity plate thinner than the draw depth.  Whether that
rule should hold is one of the questions this study exists to answer, so §levers
stands it down for the duration - deliberately, in one place, and nowhere else.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cadquery as cq  # noqa: E402

from material import (  # noqa: E402
    DENSITY, PLANS, area, face_breakdown, pair, printed, section_stiffness, volume,
)
from traymold.derive import derive, forming_gap  # noqa: E402
from traymold.exporters import print_oriented  # noqa: E402
from traymold.mold import (  # noqa: E402
    ProfileFamily, _BaseCache, _at_z, _loft, build, make_base_profile,
)
from traymold.presets import REF_4X7  # noqa: E402


def stand_down_e_mold_040() -> None:
    """Let the study build a female thinner than the draw depth."""
    import traymold.validate  # noqa: F401  (imported for the side effect below)

    sys.modules["traymold.validate"].raise_on_errors = lambda params: None


def mold(**kw):
    """REF_4X7 with `mold.*` overridden, at export quality."""
    return REF_4X7.model_copy(
        update={"mold": REF_4X7.mold.model_copy(update=kw)}
    ).with_quality("export")


def prism(params, d: float, z0: float, z1: float, base_offset: float):
    base = make_base_profile(params)
    family = ProfileFamily(base, base_offset, _BaseCache(base))
    return _loft([_at_z(family.at(d), z0), _at_z(family.at(d), z1)])


def band(params, d0: float, d1: float, z0: float, z1: float, base_offset: float):
    """The closed ring between two offsets of the base profile."""
    return prism(params, d1, z0, z1, base_offset).cut(prism(params, d0, z0, z1, base_offset))


# --------------------------------------------------------------------------
def baseline() -> None:
    print("\n== baseline: ref-4x7 as it ships, at 6 walls / 30 % ==\n")
    r = build(REF_4X7.with_quality("export"))
    total = 0.0
    for half in ("male", "female"):
        s = getattr(r, half)
        p = printed(s, PLANS["6w/30%"])
        total += p["total_cm3"]
        f = face_breakdown(s)
        print(f"  {half:<8} solid {p['solid_cm3']:7.1f} cm3   surface {area(s)/100:7.1f} cm2"
              f"   ({f['horizontal_mm2']/100:.0f} flat / {f['vertical_mm2']/100:.0f} upright)")
        print(f"  {'':<8} shell {p['shell_cm3']:7.1f}      core {p['core_cm3']:7.1f}"
              f"      PRINTED {p['total_cm3']:7.1f} cm3  = {p['grams']:5.0f} g")
    print(f"\n  both halves   {total:7.1f} cm3   {total * DENSITY:5.0f} g")


def sections() -> None:
    print("\n== a printed plate is a sandwich: what a gram of it buys ==\n")
    print(f"  {'section':<38}{'I mm4/mm':>10}{'g/dm2':>9}{'I per gram':>12}")
    rows = [
        (25, 1.0, 0.30, "female 25 mm, 5 skins, 30 %   (now)"),
        (25, 1.0, 0.10, "female 25 mm, 5 skins, 10 %"),
        (25, 1.6, 0.08, "female 25 mm, 8 skins,  8 %"),
        (12, 1.0, 0.30, "female 12 mm, 5 skins, 30 %"),
        (12, 6.0, 1.00, "female 12 mm, SOLID"),
        (15, 1.0, 0.30, "male plate 15 mm, 5 skins, 30 % (now)"),
        (15, 1.0, 0.10, "male plate 15 mm, 5 skins, 10 %"),
        (15, 1.6, 0.08, "male plate 15 mm, 8 skins,  8 %"),
        (10, 1.0, 0.30, "male plate 10 mm, 5 skins, 30 %"),
    ]
    for t, skin, rho, label in rows:
        s = section_stiffness(t, skin, rho)
        print(f"  {label:<38}{s['I_mm4_per_mm']:>10.1f}{s['grams_per_dm2']:>9.1f}"
              f"{s['I_per_gram']:>12.2f}")


def levers() -> None:
    stand_down_e_mold_040()
    print("\n== geometry levers x settings plans, cm3 for both halves ==\n")
    print(f"  {'geometry':<26}" + "".join(f"{k:>12}" for k in PLANS))
    cases = [
        ("baseline  f25 b15 fl30", mold()),
        ("female 12 mm", mold(cavity_plate_thickness=12.0)),
        ("female  8 mm", mold(cavity_plate_thickness=8.0)),
        ("base plate 10 mm", mold(base_plate_thickness=10.0)),
        ("flange 28 mm", mold(flange_width=28.0)),
        ("flange 26 mm", mold(flange_width=26.0)),
        ("flange 24 mm", mold(flange_width=24.0)),
        ("flange 26 + f12 + b10",
         mold(flange_width=26.0, cavity_plate_thickness=12.0, base_plate_thickness=10.0)),
    ]
    for label, params in cases:
        r = build(params)
        print(f"  {label:<26}" + "".join(f"{pair(r, pl):>12.1f}" for pl in PLANS.values()))


def outline() -> None:
    print("\n== plate outline: rectangle vs a curve that follows the profile ==\n")
    import traymold.mold as M
    original = M._plate

    def following(params, z0, z1):
        base = make_base_profile(params)
        family = ProfileFamily(base, 0.0, _BaseCache(base))
        w = family.at(params.mold.flange_width)
        body = _loft([_at_z(w, z0), _at_z(w, z1)])
        ch, d = params.features.clamp_holes, derive(params)
        if not ch.enabled:
            return body
        x, y = d.plate_length / 2 - ch.inset, d.plate_width / 2 - ch.inset
        pts = [(-x, y), (x, -y)] if ch.diagonal == "nw_se" else [(x, y), (-x, -y)]
        ears = None
        for cx, cy in pts:                      # the clamp holes fall outside the curve
            ear = (cq.Workplane("XY").workplane(offset=z0).center(cx, cy)
                   .circle(ch.diameter / 2 + ch.top_chamfer + 6.0).extrude(z1 - z0).val())
            ears = ear if ears is None else ears.fuse(ear)
        return cq.Solid(body.fuse(ears).wrapped)

    try:
        for label, plate in (("rectangle (now)", original), ("profile-following + ears", following)):
            M._plate = plate
            r = build(mold())
            solid = sum(volume(getattr(r, h)) / 1000 for h in ("male", "female"))
            print(f"  {label:<28}solid {solid:7.1f} cm3"
                  + "".join(f"   {k} {pair(r, pl):6.1f}" for k, pl in PLANS.items()
                            if k in ("6w/30%", "3w/10%")))
    finally:
        M._plate = original


def regions() -> None:
    print("\n== a CAD pocket competes with infill for the same core ==\n")
    p = mold()
    t = p.mold.cavity_plate_thickness
    female = build(p).female
    tool = band(p, 0.0, 8.0, 10.0, t + 1.0, forming_gap(p))   # relief above a 10 mm land
    relieved = female.cut(tool)
    for plan_name in ("6w/30%", "3w/10%"):
        before = printed(female, PLANS[plan_name])
        after = printed(relieved, PLANS[plan_name])
        if plan_name == "6w/30%":
            print("  counterbore relief, 10 mm forming land, 8 mm wide above it")
            print(f"    solid  {before['solid_cm3']:7.1f} -> {after['solid_cm3']:7.1f} cm3"
                  f"   ({after['solid_cm3'] - before['solid_cm3']:+.1f})")
            print(f"    shell  {before['shell_cm3']:7.1f} -> {after['shell_cm3']:7.1f} cm3"
                  f"   ({after['shell_cm3'] - before['shell_cm3']:+.1f}, the wall moved rather than appeared)")
        print(f"    printed at {plan_name:<7} {before['total_cm3']:7.1f} -> {after['total_cm3']:7.1f} cm3"
              f"   ({after['total_cm3'] - before['total_cm3']:+.1f})")


def ledger() -> None:
    print("\n== the region ledger: what reinforcing the plan costs back ==\n")
    t, bp, depth = (REF_4X7.mold.cavity_plate_thickness,
                    REF_4X7.mold.base_plate_thickness, REF_4X7.tray.depth)
    gap, cd = forming_gap(REF_4X7), REF_4X7.features.clamp_holes.diameter

    def up_facing(params):
        r = build(params)
        up = sum(area(f)
                 for half in ("male", "female")
                 for f in cq.Solid(print_oriented(getattr(r, half), half).wrapped).Faces()
                 if (lambda n: n is not None and n.z > 0.9)(f.normalAt()))
        return r, up

    p = mold()                                   # the ledger is quoted on the baseline
    r, up = up_facing(p)
    rows = [
        ("6th top solid layer, both parts", up * 0.2 / 1000, 0.0, 1.0),
        ("clamp columns, female  d18 x %g" % t,
         2 * math.pi * (1.5 * cd) ** 2 * t / 1000, 0.10, 0.70),
        ("clamp columns, male    d18 x %g" % bp,
         2 * math.pi * (1.5 * cd) ** 2 * bp / 1000, 0.10, 0.70),
        ("plug core, under the top band",
         volume(prism(p, -6.0, 0.0, depth - 5.0, 0.0)) / 1000, 0.10, 0.07),
        ("5 mm band under the forming face",
         volume(prism(p, 0.0, depth - 5.0, depth, 0.0)) / 1000, 0.10, 0.35),
    ]
    net = 0.0
    for label, vol, was, now in rows:
        delta = vol * (now - was)
        net += delta
        change = "5 -> 6 layers" if was == 0.0 else f"{was:>4.0%} -> {now:<4.0%}"
        print(f"  {label:<36}{vol:8.1f} cm3   {change:<14}{delta:+8.1f}")
    print(f"  {'considered and rejected:':<36}")
    for label, vol_cm3 in (
        ("female cavity-wall backing, 6 mm", volume(band(p, 0.0, 6.0, 0.0, t, gap)) / 1000),
        ("male plug-wall backing, 6 mm", volume(band(p, -6.0, 0.0, 0.0, depth, 0.0)) / 1000),
    ):
        print(f"    {label:<34}{vol_cm3:8.1f} cm3   10 % -> 40 % would cost {vol_cm3 * 0.30:+7.1f}")
    print(f"\n  {'NET over a uniform 10 % plan':<36}{'':>8}       {'':>13}{net:+8.1f} cm3")
    for label, params in (("flange 30 (baseline)", p), ("flange 26", mold(flange_width=26.0))):
        rr, uu = (r, up) if params is p else up_facing(params)
        ledger_here = net - (up - uu) * 0.2 / 1000        # only the top layer moves with the plate
        total = pair(rr, PLANS["3w/10%"]) + ledger_here
        print(f"  uniform 3w/10 % at {label:<20}{pair(rr, PLANS['3w/10%']):7.1f} cm3"
              f"   ->  with the ledger {total:7.1f} cm3 = {total * DENSITY:4.0f} g")


def bug() -> None:
    """Why the clamp-hole rule has to be geometric, and what it catches.

    The obvious rule - compare the hole against the cavity's bounding box - is
    wrong in both directions, and this is the evidence for both. On a rounded
    profile the box is far too pessimistic, because the corner has curved away
    from where the hole sits. On a profile with a small corner setback the hole
    really does open into the forming wall, and the result is still one closed
    shell, so `mold._checked` passes it and the volume bounds pass it too.
    """
    import json

    from traymold.params import CircularRectProfile, G2QuinticRectProfile
    from traymold.validate import _clearance, _polyline_for, validate

    gap = forming_gap(REF_4X7)
    ch = REF_4X7.features.clamp_holes

    def measure(params):
        d = derive(params)
        x, y = d.plate_length / 2 - ch.inset, d.plate_width / 2 - ch.inset
        poly = _polyline_for(json.dumps(params.tray.profile.model_dump(mode="json"), sort_keys=True))
        true_land = _clearance(poly, -x, y, forming_gap(params)) - ch.diameter / 2
        bbox_land = params.mold.flange_width - ch.inset - ch.diameter / 2 - forming_gap(params)
        # does the bore actually meet the cavity?
        overlap = volume(
            prism(params, 0.0, -1.0, params.mold.cavity_plate_thickness + 1.0,
                  forming_gap(params)).intersect(
                cq.Workplane("XY").workplane(offset=-1.0).center(-x, y)
                  .circle(ch.diameter / 2).extrude(params.mold.cavity_plate_thickness + 2.0).val()
            )
        ) / 1000.0
        codes = sorted({d_.code for d_ in validate(params) if d_.severity == "error"})
        return bbox_land, true_land, overlap, codes

    print("\n== the clamp-hole rule: a bounding box is not a plan curve ==\n")
    print(f"  {'profile':<26}{'flange':>7}{'bbox':>8}{'true':>8}{'overlap':>11}   diagnostics")
    cases = [
        ("obround (reference)", mold()),
        ("obround", mold(flange_width=20.0)),
        ("obround", mold(flange_width=12.0)),
        ("circular_rect r=25", mold(flange_width=12.0).model_copy(update={
            "tray": REF_4X7.tray.model_copy(update={
                "profile": CircularRectProfile(length=175.0, width=105.0, corner_radius=25.0)})})),
        ("g2_quintic_rect s=10", mold(flange_width=12.0).model_copy(update={
            "tray": REF_4X7.tray.model_copy(update={
                "profile": G2QuinticRectProfile(length=175.0, width=105.0, corner_setback=10.0)})})),
    ]
    for label, params in cases:
        bbox_land, true_land, overlap, codes = measure(params)
        note = "   <- the bore is in the cavity" if overlap > 1e-6 else ""
        print(f"  {label:<26}{params.mold.flange_width:>7.0f}{bbox_land:>+8.1f}{true_land:>+8.1f}"
              f"{overlap:>8.2f} cm3   {','.join(codes) or 'clean'}{note}")
    print("\n  bbox: flange - inset - radius - gap, the arithmetic rule."
          "\n  true: signed distance to the cavity wall, which is what E-FEAT-050 measures."
          "\n  A shell count cannot see any of this: every row above is one closed solid.")
    _ = gap


SECTIONS = {"baseline": baseline, "sections": sections, "levers": levers,
            "outline": outline, "regions": regions, "ledger": ledger, "bug": bug}


def main(argv=None) -> int:
    names = (argv or sys.argv[1:]) or list(SECTIONS)
    for name in names:
        if name not in SECTIONS:
            print(f"unknown section {name!r}; have {', '.join(SECTIONS)}", file=sys.stderr)
            return 2
        SECTIONS[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
