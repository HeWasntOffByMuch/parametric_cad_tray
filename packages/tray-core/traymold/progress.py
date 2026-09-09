"""Build stages, and what fraction of the wall clock each one is worth.

A progress bar is a promise about time, so the weights here are measured rather
than guessed.  On the reference design, per stage, in milliseconds:

    stage                 preview   export
    base profile                1        1
    male loft                  34       30
    male root blend          1123     2087
    male floor blend         2240     4594
    female loft               194      188
    female entry blend       1130     1855
    features                    0        0     (inactive on the reference)
    write artifacts           631     4803

Two things follow.  The weights differ by mode - writing is 11% of a preview and
34% of an export - so there is a table per mode.  And a plan is built for the
*stages that will actually run*, then normalised: a female-only build must not
stall at 25% waiting for a male half that was never going to be built.

The numbers are an estimate for one design and will be wrong for another; a bar
that is honest about its checkpoints and approximate between them is the trade
this makes.  What is never approximate is the *order*: each fraction is reported
only once the stage behind it has actually finished.
"""

from __future__ import annotations

#: Stage id -> what to tell the user it is doing.
LABELS: dict[str, str] = {
    "profile": "tracing the profile",
    "male_solid": "extruding the plug",
    "male_root_blend": "blending the plug root",
    "male_floor_blend": "blending the tray floor",
    "female_solid": "cutting the cavity",
    "female_entry_blend": "blending the cavity mouth",
    "features": "adding holes and pins",
    "write": "writing the files",
}

#: Relative cost of each stage, measured on the reference design.  Only the
#: ratios matter; `plan` normalises whatever subset actually runs.
COST: dict[str, dict[str, float]] = {
    "preview": {
        "profile": 1, "male_solid": 34, "male_root_blend": 1123,
        "male_floor_blend": 2240, "female_solid": 194,
        "female_entry_blend": 1130, "features": 40, "write": 631,
    },
    "export": {
        "profile": 1, "male_solid": 30, "male_root_blend": 2087,
        "male_floor_blend": 4594, "female_solid": 188,
        "female_entry_blend": 1855, "features": 80, "write": 4803,
    },
}

#: The order stages run in.  `build` emits them in exactly this sequence.
ORDER = ("profile", "male_solid", "male_root_blend", "male_floor_blend",
         "female_solid", "female_entry_blend", "features", "write")


def stages_for(params) -> list[str]:
    """Which stages this parameter set will actually run.

    Reads the same flags `build` branches on, so the plan and the build cannot
    disagree about what is going to happen.
    """
    parts = params.mold.parts
    mold = params.mold
    out = ["profile"]
    if parts.male:
        out.append("male_solid")
        if mold.male_root_blend.active:
            out.append("male_root_blend")
        if mold.male_floor_blend.active:
            out.append("male_floor_blend")
    if parts.female:
        out.append("female_solid")
        if mold.female_entry_blend_top.active or mold.female_entry_blend_bottom.active:
            out.append("female_entry_blend")
    f = params.features
    if f.clamp_holes.enabled or f.pry_notches.enabled or f.alignment_pins.enabled:
        out.append("features")
    out.append("write")
    return out


def plan(params) -> dict[str, float]:
    """Stage id -> the fraction complete once that stage has finished.

    Monotonic, ends at exactly 1.0, and covers only the stages that will run.
    """
    mode = params.quality.mode if params.quality.mode in COST else "preview"
    cost = COST[mode]
    stages = stages_for(params)
    total = sum(cost.get(s, 1.0) for s in stages) or 1.0
    out: dict[str, float] = {}
    running = 0.0
    for stage in stages:
        running += cost.get(stage, 1.0)
        out[stage] = round(running / total, 4)
    # Floating-point addition must not leave the last stage at 0.9999.
    if stages:
        out[stages[-1]] = 1.0
    return out
