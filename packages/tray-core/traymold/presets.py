"""Named starting points."""

from __future__ import annotations

from .params import (
    ClampHoles,
    EdgeTreatment,
    Features,
    FitParams,
    G2QuinticObroundProfile,
    LeatherParams,
    MoldParams,
    Params,
    PryNotches,
    TrayParams,
)

#: Exact reconstruction of the reference pair.  The STEP revision carries the
#: shape; the STL revision adds the clamp holes and pry notches.
REF_4X7 = Params(
    name="ref-4x7-wetmold",
    tray=TrayParams(
        profile=G2QuinticObroundProfile(length=175.0, width=105.0),
        depth=25.0,
        datum="inner",
        draft_angle=0.0,
    ),
    leather=LeatherParams(thickness=3.0, compression=0.0),
    fit=FitParams(clearance=0.0),
    mold=MoldParams(
        flange_width=30.0,
        base_plate_thickness=15.0,
        cavity_plate_thickness=25.0,
        male_root_blend=EdgeTreatment(style="circular", size=1.2),
        male_floor_blend=EdgeTreatment(style="g2_quintic", size=5.0),
        female_entry_blend_top=EdgeTreatment(style="g2_quintic", size=3.0),
        female_entry_blend_bottom=EdgeTreatment(style="none", size=0.0),
    ),
    features=Features(
        clamp_holes=ClampHoles(
            enabled=True, pattern="diagonal_pair", diagonal="nw_se",
            diameter=6.0, inset=15.0, top_chamfer=2.0, in_male=False, in_female=True,
        ),
        pry_notches=PryNotches(
            enabled=True, pattern="diagonal_pair", diagonal="ne_sw",
            size_x=15.0, size_y=15.0, depth=8.0,
        ),
    ),
)

#: The same shape without the STL-revision features - matches the STEP files.
REF_4X7_STEP = REF_4X7.model_copy(update={"name": "ref-4x7-step", "features": Features()})

PRESETS = {"ref-4x7": REF_4X7, "ref-4x7-step": REF_4X7_STEP}
