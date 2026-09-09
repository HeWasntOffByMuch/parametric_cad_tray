"""Preview and export describe the same geometry.

They differ only in loft section density and tessellation tolerance.  Every
correctness protection - the curvature rules, the realised-distance verifier,
the dependency boundary - is identical in both.
"""

import pytest

import traymold
from traymold.presets import REF_4X7_STEP
from traymold.profiles import measure_offset_distance, profile_deviation, sample_wire
from traymold.quality import DEFAULTS, resolve

pytestmark = pytest.mark.slow

#: Measured preview budget.  Export holds 4.2 um against the STEP; preview holds
#: 29.9 um (3D surface deviation, worst case at the plug's top tangent).  This is
#: the budget for preview drifting from the *export* result inside the edge
#: treatments.
PREVIEW_TOL = 0.05

#: Outside the edge treatments the two modes build the same prism from the same
#: wire, so they should be identical.  They differ by ~0.17 um: the floor blend's
#: boolean re-approximates the wall faces slightly differently at different
#: section counts.  That is numerical noise, not a semantic difference.
SAME_GEOMETRY_TOL = 1e-3


@pytest.fixture(scope="module")
def export_build():
    return traymold.build(REF_4X7_STEP.with_quality("export"))


@pytest.fixture(scope="module")
def preview_build():
    return traymold.build(REF_4X7_STEP.with_quality("preview"))


def test_quality_modes_are_declared_not_guessed():
    assert set(DEFAULTS) == {"preview", "export"}
    assert DEFAULTS["export"].blend_sections > DEFAULTS["preview"].blend_sections
    assert DEFAULTS["export"].linear_deflection < DEFAULTS["preview"].linear_deflection


def test_overrides_win_over_mode_defaults():
    p = REF_4X7_STEP.with_quality("preview")
    p = p.model_copy(update={"quality": p.quality.model_copy(update={"blend_sections": 99})})
    assert resolve(p).blend_sections == 99
    assert resolve(p).linear_deflection == DEFAULTS["preview"].linear_deflection


def test_base_profiles_are_identical_across_modes(export_build, preview_build):
    """Same semantics: the base profile and the forming gap do not move."""
    for attr in ("base_profile", "male_profile", "female_profile"):
        dev = profile_deviation(
            sample_wire(getattr(export_build, attr), 400),
            sample_wire(getattr(preview_build, attr), 400),
        )
        assert dev["max"] < 1e-4, f"{attr} differs between modes"


def test_forming_gap_is_verified_in_both_modes(export_build, preview_build):
    for build in (export_build, preview_build):
        realised = measure_offset_distance(build.female_profile, build.male_profile)
        assert realised["min"] == pytest.approx(3.0, abs=0.01)
        assert realised["max"] == pytest.approx(3.0, abs=0.01)


@pytest.mark.parametrize("z", [5.0, 10.0, 12.5, 18.0])
def test_preview_matches_export_exactly_outside_the_edge_treatments(export_build, preview_build, z):
    import reference as R

    a = R.forming_loop(export_build.male, z, per_edge=200)
    b = R.forming_loop(preview_build.male, z, per_edge=200)
    assert profile_deviation(a, b)["max"] < SAME_GEOMETRY_TOL


@pytest.mark.parametrize("z", [0.5, 1.0, 21.0, 23.0, 24.0, 24.5])
def test_preview_stays_inside_its_measured_budget_in_the_treatments(export_build, preview_build, z):
    import reference as R

    a = R.forming_loop(export_build.male, z, per_edge=200)
    b = R.forming_loop(preview_build.male, z, per_edge=200)
    assert profile_deviation(a, b)["max"] <= PREVIEW_TOL


def test_preview_is_materially_faster(export_build, preview_build):
    import time

    def timed(mode):
        t0 = time.perf_counter()
        traymold.build(REF_4X7_STEP.with_quality(mode))
        return time.perf_counter() - t0

    assert timed("preview") < timed("export")


# --------------------------------------------------------------------------
# tessellation: what the eye and the slicer actually see
# --------------------------------------------------------------------------
def test_deflections_bound_the_visible_crease_not_just_the_sagitta():
    """A chord error alone does not bound faceting.

    0.05 mm of sagitta on this profile's ~52 mm radius is a 4.6 mm chord, which
    reads as a flat panel however small the sagitta is. Both deflections have to
    come down together, and export has to be the finer of the two.
    """
    export, preview = DEFAULTS["export"], DEFAULTS["preview"]
    assert export.angular_deflection <= 0.05
    assert preview.angular_deflection <= 0.15
    assert export.angular_deflection < preview.angular_deflection
    assert export.linear_deflection < preview.linear_deflection
