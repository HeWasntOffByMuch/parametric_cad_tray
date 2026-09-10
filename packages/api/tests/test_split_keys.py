"""The claim that makes the split worth anything, proved rather than asserted.

A preview is built as two halves so that changing one does not rebuild the
other. That only works if each half's cache key ignores the parameters that
cannot reach it - and if the key ignores something that *can*, two different
designs share an entry and the viewer shows the wrong solid.

So every field in `IGNORED_BY` is changed here, and the half it is supposed to
be invisible to must come out identical. These run at preview quality on the
reference design; that is enough to catch a field that moves geometry, because
a field that moves geometry moves it at any tessellation.
"""

import copy

import pytest

from trayapi.cache import IGNORED_BY, half_key

PARTS = ("male", "female")


def _params(overrides: dict | None = None):
    from traymold.api import apply_options
    from traymold.presets import REF_4X7_STEP

    params = REF_4X7_STEP
    if overrides:
        data = params.model_dump(mode="json")
        _apply(data, overrides)
        from traymold.params import Params

        params = Params.model_validate(data)
    return apply_options(params, "preview", None)


def _apply(data: dict, overrides: dict) -> None:
    for path, value in overrides.items():
        node = data
        steps = path.split(".")
        for step in steps[:-1]:
            node = node[step]
        node[steps[-1]] = value


def _solid(params, part: str):
    """Build one half and return something comparable."""
    from traymold.mold import build

    half = params.model_copy(update={
        "mold": params.mold.model_copy(update={
            "parts": params.mold.parts.model_copy(update={
                "male": part == "male", "female": part == "female",
            }),
        }),
    })
    result = build(half)
    return result.volumes


#: One concrete change per ignored path, chosen to be geometrically loud.
CHANGES: dict[str, dict] = {
    "leather": {"leather.thickness": 5.5},
    "fit": {"fit.clearance": 1.25},
    "mold.cavity_plate_thickness": {"mold.cavity_plate_thickness": 40.0},
    "mold.female_entry_blend_top": {"mold.female_entry_blend_top": {"kind": "none"}},
    "mold.female_entry_blend_bottom": {
        "mold.female_entry_blend_bottom": {"kind": "circular_fillet", "radius": 2.0}
    },
    "features.pry_notches": {
        "features.pry_notches": {"enabled": True, "pattern": "diagonal_pair",
                                 "diagonal": "ne_sw", "size_x": 15.0, "size_y": 15.0,
                                 "depth": 8.0}
    },
    "manufacturing.pin_fit_clearance": {"manufacturing.pin_fit_clearance": 0.9},
    "mold.base_plate_thickness": {"mold.base_plate_thickness": 30.0},
    "mold.male_root_blend": {"mold.male_root_blend": {"kind": "none"}},
    "mold.male_floor_blend": {
        "mold.male_floor_blend": {"kind": "circular_fillet", "radius": 2.0}
    },
}


def test_every_ignored_path_has_a_change_to_test_it_with():
    """A field added to IGNORED_BY without a case here would be untested."""
    declared = {".".join(path) for paths in IGNORED_BY.values() for path in paths}
    assert declared == set(CHANGES), declared.symmetric_difference(set(CHANGES))


@pytest.mark.slow
@pytest.mark.parametrize("part", PARTS)
def test_an_ignored_field_changes_neither_the_key_nor_the_solid(part):
    base = _params()
    baseline_key = half_key(base, ("glb",), part)
    baseline = _solid(base, part)

    for path in IGNORED_BY[part]:
        name = ".".join(path)
        changed = _params(CHANGES[name])
        assert half_key(changed, ("glb",), part) == baseline_key, \
            f"{name} is in {part}'s key, so the split rebuilds for nothing"
        # The key claims this cannot reach the half. If it can, the cache would
        # hand back the wrong solid - so the claim is checked against geometry.
        assert _solid(changed, part) == pytest.approx(baseline, rel=1e-9), \
            f"{name} DOES change the {part}: it must not be ignored by its key"


@pytest.mark.parametrize("part", PARTS)
def test_a_field_that_does_reach_the_half_is_in_its_key(part):
    """The other direction: the shared parameters must still separate entries."""
    base = _params()
    baseline = half_key(base, ("glb",), part)
    for path, value in (("tray.depth", 22.0), ("tray.profile.length", 190.0)):
        changed = _params({path: value})
        assert half_key(changed, ("glb",), part) != baseline, \
            f"{path} reaches both halves and must be in {part}'s key"


def test_the_two_halves_never_share_a_key():
    base = _params()
    assert half_key(base, ("glb",), "male") != half_key(base, ("glb",), "female")


def test_the_key_does_not_depend_on_how_the_parts_were_requested():
    """Asking for both halves and asking for one must hit the same entry."""
    both = _params()
    only_male = both.model_copy(update={
        "mold": both.mold.model_copy(update={
            "parts": both.mold.parts.model_copy(update={"male": True, "female": False}),
        }),
    })
    assert half_key(both, ("glb",), "male") == half_key(only_male, ("glb",), "male")
