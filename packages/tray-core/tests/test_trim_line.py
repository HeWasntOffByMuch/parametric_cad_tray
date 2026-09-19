"""The trim line: a bead that marks a cutting line on the leather.

It is a manufacturing feature, so the things worth asserting are the ones that
are not visible in a volume: that it is on the face the leather touches, that it
stands the right way for both printing and marking, that it follows the cavity
at the distance asked for, and that it cannot reach back into the male.
"""

import cadquery as cq
import pytest

from traymold.api import build
from traymold.derive import forming_gap
from traymold.exporters import print_oriented
from traymold.mold import _volume
from traymold.params import CircularRectProfile
from traymold.presets import REF_4X7
from traymold.validate import validate

REFERENCE = REF_4X7.with_quality("preview")


def with_trim(params=REF_4X7, **kw):
    enabled = {"enabled": True, **kw}
    return params.model_copy(update={"features": params.features.model_copy(
        update={"trim_line": params.features.trim_line.model_copy(update=enabled)})})


@pytest.fixture(scope="module")
def plain():
    return build(REFERENCE)


@pytest.fixture(scope="module")
def marked():
    return build(with_trim().with_quality("preview"))


def bead_of(female, height):
    """Whatever the female has below its parting face is the bead, by definition.

    The plate occupies z = 0 upwards, so nothing else can be down there. Taking
    it this way rather than by subtracting two builds keeps the test honest
    about *where* the bead is rather than only how big it is.
    """
    slab = (cq.Workplane("XY").workplane(offset=-height - 1.0)
            .rect(1000, 1000).extrude(height + 1.0 - 1e-6).val())
    return cq.Solid(female.wrapped).intersect(slab)


# --------------------------------------------------------------------------
# what it does not touch
# --------------------------------------------------------------------------
def test_off_by_default():
    assert REF_4X7.features.trim_line.enabled is False


@pytest.mark.slow
def test_it_leaves_the_male_alone(plain, marked):
    """A manufacturing feature is downstream of everything and an input to
    nothing, and this one is on the female."""
    assert _volume(marked.male) == pytest.approx(_volume(plain.male), rel=1e-12)


@pytest.mark.slow
def test_it_only_adds(plain, marked):
    assert _volume(marked.female) > _volume(plain.female)
    # a bead, not a plate: the section is a 1.0 -> 0.4 mm trapezoid, 0.5 tall
    added = _volume(marked.female) - _volume(plain.female)
    assert 100.0 < added < 400.0, f"{added:.0f} mm3 is not a bead"


# --------------------------------------------------------------------------
# where it is
# --------------------------------------------------------------------------
@pytest.mark.slow
def test_it_stands_proud_of_the_parting_face(marked):
    """The parting face is z=0 and the plate is above it, so a bead that marks
    leather has to be below - towards the male."""
    box = marked.female.BoundingBox()
    assert box.zmin == pytest.approx(-REF_4X7.features.trim_line.height, abs=1e-6)
    assert box.zmax == pytest.approx(REF_4X7.mold.cavity_plate_thickness, abs=1e-6)


@pytest.mark.slow
def test_it_follows_the_cavity_at_the_distance_asked_for(marked):
    """Measured from the edge of the fillet, so it reads as how much flange to
    leave and does not move when the fillet is resized."""
    trim = REF_4X7.features.trim_line
    reach = (forming_gap(REF_4X7) + REF_4X7.mold.female_entry_blend_bottom.size
             + trim.offset + trim.width / 2.0)
    box = bead_of(marked.female, trim.height).BoundingBox()
    assert box.xlen == pytest.approx(REF_4X7.tray.profile.length + 2 * reach, abs=0.05)
    assert box.ylen == pytest.approx(REF_4X7.tray.profile.width + 2 * reach, abs=0.05)


@pytest.mark.slow
def test_the_offset_is_from_the_fillet_not_the_cavity_wall():
    """Halving the fillet moves the bead in by exactly that much."""
    from traymold.params import G2QuinticBlend

    def reach_of(setback):
        params = with_trim(REF_4X7.model_copy(update={
            "mold": REF_4X7.mold.model_copy(update={
                "female_entry_blend_bottom": G2QuinticBlend(setback=setback)})})
        ).with_quality("preview")
        female = build(params).female
        return bead_of(female, params.features.trim_line.height).BoundingBox().xlen

    assert reach_of(3.0) - reach_of(1.5) == pytest.approx(2 * 1.5, abs=0.05)


@pytest.mark.slow
def test_it_is_a_closed_loop_not_an_arc(marked):
    """`_shells` sees one closed solid, and the bead reaches the full plan on
    both axes - which an arc down one side would not."""
    bead = bead_of(marked.female, REF_4X7.features.trim_line.height)
    box = bead.BoundingBox()
    assert box.xlen > REF_4X7.tray.profile.length
    assert box.ylen > REF_4X7.tray.profile.width
    assert box.center.x == pytest.approx(0.0, abs=1e-6)
    assert box.center.y == pytest.approx(0.0, abs=1e-6)


@pytest.mark.slow
def test_it_prints_upward_with_nothing_over_it(marked):
    """`print_oriented` turns the female over, so the face that carries the bead
    is the one facing the nozzle. A bead on the bed face would need support and
    would be crushed by the first layer."""
    printed = print_oriented(marked.female, "female")
    box = printed.BoundingBox()
    assert box.zmin == pytest.approx(0.0, abs=1e-6)
    expected = REF_4X7.mold.cavity_plate_thickness + REF_4X7.features.trim_line.height
    assert box.zmax == pytest.approx(expected, abs=1e-6)


@pytest.mark.slow
def test_a_clamp_bore_cuts_through_it_rather_than_being_filled_by_it():
    """The bead is fused before the holes are cut, so a bore that crosses it
    still goes all the way through."""
    profile = CircularRectProfile(length=175.0, width=105.0, corner_radius=25.0)
    params = with_trim(REF_4X7.model_copy(update={
        "tray": REF_4X7.tray.model_copy(update={"profile": profile}),
        "features": REF_4X7.features.model_copy(update={
            "clamp_holes": REF_4X7.features.clamp_holes.model_copy(update={"inset": 25.0})}),
    }), offset=11.0).with_quality("preview")
    assert "W-FEAT-056" in {d.code for d in validate(params)}, "this design should warn"

    female = build(params).female
    # down the bore's axis, through the bead's depth as well as the plate
    x, y = (175 + 60) / 2 - 25, (105 + 60) / 2 - 25
    probe = (cq.Workplane("XY").workplane(offset=-2.0).center(-x, y)
             .circle(1.5).extrude(REF_4X7.mold.cavity_plate_thickness + 4.0).val())
    assert _volume(cq.Solid(female.wrapped).intersect(probe)) == pytest.approx(0.0, abs=1.0)


# --------------------------------------------------------------------------
# the rules
# --------------------------------------------------------------------------
def codes(params):
    return {d.code for d in validate(params)}


def test_a_bead_that_runs_off_the_plate_is_an_error():
    diagnostic = next(d for d in validate(with_trim(offset=24.0)) if d.code == "E-FEAT-055")
    assert diagnostic.severity == "error"
    assert diagnostic.field == "features.trim_line"
    assert "plate edge" in diagnostic.message
    assert "min_wall" in diagnostic.message


def test_the_reference_offset_is_comfortably_clear():
    assert codes(with_trim()) == set()
    # and there is room to move it a long way before anything complains
    assert codes(with_trim(offset=18.0)) == set()


def test_a_bead_through_a_bore_is_a_warning_not_an_error():
    """The hole is there either way; the mark is just broken into arcs, which is
    worth knowing before printing rather than after."""
    profile = CircularRectProfile(length=175.0, width=105.0, corner_radius=25.0)
    params = with_trim(REF_4X7.model_copy(update={
        "tray": REF_4X7.tray.model_copy(update={"profile": profile}),
        "features": REF_4X7.features.model_copy(update={
            "clamp_holes": REF_4X7.features.clamp_holes.model_copy(update={"inset": 25.0})}),
    }), offset=11.0)
    diagnostic = next(d for d in validate(params) if d.code == "W-FEAT-056")
    assert diagnostic.severity == "warning"
    assert "break the mark" in diagnostic.message
    # clear of the bore on either side
    assert "W-FEAT-056" not in codes(
        params.model_copy(update={"features": params.features.model_copy(
            update={"trim_line": params.features.trim_line.model_copy(update={"offset": 4.0})})}))


def test_a_disabled_bead_is_not_checked():
    reckless = REF_4X7.features.trim_line.model_copy(update={"enabled": False, "offset": 200.0})
    params = REF_4X7.model_copy(update={
        "features": REF_4X7.features.model_copy(update={"trim_line": reckless})})
    assert "E-FEAT-055" not in codes(params)
