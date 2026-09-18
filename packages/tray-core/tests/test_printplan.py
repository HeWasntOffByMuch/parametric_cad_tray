"""The print plan: what it places, what it costs, and what it must never touch.

The plan is the third concept, downstream of everything.  The tests that matter
most here are the negative ones: a print setting cannot move a surface, and a
region that does not actually sit inside its part is a region the slicer
silently ignores.
"""

import cadquery as cq
import pytest

from traymold.api import build, canonical_params, params_hash
from traymold.mold import _volume
from traymold.presets import REF_4X7
from traymold.printplan import (
    PROFILES,
    Settings,
    extrusion_width,
    layer_height,
    ledger,
    material_mm3,
    resolve,
)


def with_print(**kw):
    return REF_4X7.model_copy(update={"print": REF_4X7.print.model_copy(update=kw)})


@pytest.fixture(scope="module")
def built():
    return build(REF_4X7.with_quality("preview"))


# --------------------------------------------------------------------------
# the boundary: a print setting is not geometry
# --------------------------------------------------------------------------
@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_the_print_plan_is_outside_the_design_identity(profile):
    """Every print setting is excluded from the params hash, so choosing one
    cannot invalidate a preview that could not show it anyway."""
    assert params_hash(with_print(profile=profile)) == params_hash(REF_4X7)
    assert "print" not in canonical_params(with_print(profile=profile))


@pytest.mark.slow
def test_no_print_setting_changes_the_solids(built):
    for profile in sorted(PROFILES):
        other = build(with_print(profile=profile, reinforce_clamps=False,
                                 support_forming_face=False).with_quality("preview"))
        for half in ("male", "female"):
            assert _volume(getattr(other, half)) == pytest.approx(
                _volume(getattr(built, half)), rel=1e-12
            ), f"{profile} moved the {half}"


# --------------------------------------------------------------------------
# resolving
# --------------------------------------------------------------------------
def test_the_slicer_profile_says_nothing_at_all():
    """`slicer` is the absence of a plan: no overrides, and so no regions to
    override.  Anything else would be writing settings for someone else's
    printer."""
    plan = resolve(with_print(profile="slicer"))
    assert not plan.active
    assert plan.regions() == []
    assert plan.parts["male"].base == Settings()


def test_widths_come_from_the_nozzle_when_they_are_not_given():
    params = REF_4X7.model_copy(update={
        "manufacturing": REF_4X7.manufacturing.model_copy(update={"nozzle_diameter": 0.6})})
    assert extrusion_width(params) == pytest.approx(0.675)
    assert layer_height(params) == pytest.approx(0.3)
    override = params.model_copy(update={
        "print": params.print.model_copy(update={"extrusion_width": 0.5, "layer_height": 0.15})})
    assert extrusion_width(override) == 0.5
    assert layer_height(override) == 0.15


def test_the_regions_a_lean_plan_places():
    names = {(r.part, r.name) for r in resolve(with_print(profile="lean")).regions()}
    assert ("male", "support: under the forming face") in names
    assert ("male", "lighten: plug core") in names
    # Both halves are reinforced at the clamp, whatever `in_male` says: the bolt
    # passes through the female and bears down onto the male's plate either way.
    assert ("female", "reinforce: clamp 1") in names
    assert ("male", "reinforce: clamp 1") in names


def test_the_toggles_remove_exactly_their_own_regions():
    without_clamps = {r.name for r in resolve(with_print(reinforce_clamps=False)).regions()}
    assert not any(n.startswith("reinforce: clamp") for n in without_clamps)
    assert "support: under the forming face" in without_clamps

    without_face = {r.name for r in resolve(with_print(support_forming_face=False)).regions()}
    assert "support: under the forming face" not in without_face
    assert "lighten: plug core" not in without_face      # it exists only to sit under the band
    assert any(n.startswith("reinforce: clamp") for n in without_face)


def test_a_plan_places_nothing_for_a_half_that_is_not_being_built():
    female_only = REF_4X7.model_copy(update={
        "mold": REF_4X7.mold.model_copy(update={
            "parts": REF_4X7.mold.parts.model_copy(update={"male": False})})})
    plan = resolve(female_only)
    assert set(plan.parts) == {"female"}
    assert all(r.part == "female" for r in plan.regions())


def test_the_plug_core_is_never_empty_enough_to_leave_the_band_unsupported():
    """0 % under a 5 mm solid band is 25 layers bridging over nothing."""
    for name in ("balanced", "lean"):
        core = next(r for r in resolve(with_print(profile=name)).regions()
                    if r.name == "lighten: plug core")
        assert core.settings.fill_density > 0.0


# --------------------------------------------------------------------------
# the regions have to be where they claim to be
# --------------------------------------------------------------------------
@pytest.mark.slow
def test_every_region_actually_intersects_its_part(built):
    """A modifier only acts where it overlaps the part.  One placed from the
    wrong dimension is not an error anywhere - it is simply ignored - so the
    overlap is asserted rather than assumed."""
    plan = resolve(REF_4X7)
    assert plan.regions(), "the reference should place regions"
    for region in plan.regions():
        part = getattr(built, region.part)
        overlap = _volume(cq.Solid(part.wrapped).intersect(region.solid))
        assert overlap > 0.0, f"{region.part}/{region.name} misses its part entirely"
        # and it must be a real share of itself, not a grazing contact
        assert overlap > 0.25 * _volume(region.solid), (
            f"{region.part}/{region.name} is mostly outside the part"
        )


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------
def test_material_is_shell_plus_infill_and_never_more_than_solid():
    faces = {"horizontal_mm2": 1000.0, "vertical_mm2": 500.0, "sloped_mm2": 0.0}
    dense = material_mm3(50_000.0, faces, Settings(fill_density=1.0, perimeters=3,
                                                   top_solid_layers=5, bottom_solid_layers=5),
                         extrusion_width=0.45, layer_height=0.2)
    sparse = material_mm3(50_000.0, faces, Settings(fill_density=0.05, perimeters=3,
                                                    top_solid_layers=5, bottom_solid_layers=5),
                          extrusion_width=0.45, layer_height=0.2)
    assert dense["total"] == pytest.approx(50_000.0)
    assert sparse["total"] < dense["total"]
    assert sparse["total"] > sparse["shell"]

    # a part thinner than its own shell is all shell, never more
    thin = material_mm3(100.0, faces, Settings(fill_density=1.0, perimeters=6,
                                               top_solid_layers=5, bottom_solid_layers=5),
                        extrusion_width=0.45, layer_height=0.2)
    assert thin["total"] == pytest.approx(100.0)
    assert thin["core"] == 0.0


@pytest.mark.slow
def test_the_ledger_prices_every_option_on_the_same_geometry(built):
    report = ledger(built, resolve(with_print(profile="lean")), with_print(profile="lean"))
    options = {row["option"]: row for row in report["options"]}

    assert sum(row["selected"] for row in report["options"]) == 1
    assert options["lean"]["selected"]
    # `slicer` writes no settings, so it has no number - and must not invent one.
    assert options["slicer"]["cm3"] is None
    assert options["slicer"]["note"]

    reference = next(row for row in report["options"] if row["reference"])
    assert reference["vs_reference_pct"] == 0
    assert options["lean"]["cm3"] < options["balanced"]["cm3"] < reference["cm3"]
    assert options["lean"]["vs_reference_pct"] < -30

    # every priced option is a real fraction of the solid, never more than it
    solid = sum(report["solid_cm3"].values())
    for row in report["options"]:
        if row["cm3"] is not None:
            assert 0.0 < row["cm3"] < solid


@pytest.mark.slow
def test_an_option_costs_the_same_whether_or_not_it_is_the_one_selected(built):
    """The one thing a comparison table must not do is move when you pick a row.

    Each option is priced with the regions *it* would place, so `lean` reads the
    same next to a selected `balanced` as it does once selected. Pricing the
    alternatives bare had it read 417 g and then 448 g.
    """
    quoted = {}
    for selected in sorted(PROFILES):
        params = with_print(profile=selected)
        report = ledger(built, resolve(params), params)
        quoted[selected] = {row["option"]: row["grams"] for row in report["options"]}
    first = quoted[sorted(PROFILES)[0]]
    for selected, rows in quoted.items():
        assert rows == first, f"the table moved when {selected} was selected"


@pytest.mark.slow
def test_the_ledger_shows_where_density_goes_back_in(built):
    report = ledger(built, resolve(with_print(profile="lean")), with_print(profile="lean"))
    rows = {(r["part"], r["name"]): r for r in report["regions"]}
    clamp = rows[("female", "reinforce: clamp 1")]
    assert clamp["to_density"] > clamp["from_density"] and clamp["delta_cm3"] > 0
    core = rows[("male", "lighten: plug core")]
    assert core["to_density"] < core["from_density"] and core["delta_cm3"] < 0
    assert all(r["why"] for r in report["regions"])
