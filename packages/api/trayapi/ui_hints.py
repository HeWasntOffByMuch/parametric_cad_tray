"""Presentation hints for the parameter form.

These live beside the schema, not inside it: the served JSON Schema is exactly
what Pydantic generates, and this is the only place the backend is allowed to
know anything about a UI.  Nothing here reaches the geometry core.

The frontend renders groups in this order and puts anything unlisted into
"Advanced", so adding a parameter to the core surfaces it in the UI without a
frontend change.
"""

from . import policy as _POLICY

UI_HINTS = {
    "groups": [
        {
            "id": "shape",
            "title": "Shape",
            "fields": ["tray.profile"],
            "description": "The plan curve the tray is formed around.",
        },
        {
            "id": "dimensions",
            "title": "Dimensions",
            "fields": ["tray.profile.length", "tray.profile.width", "tray.depth"],
            "description": "Inside dimensions of the finished tray, in millimetres.",
        },
        {
            "id": "leather",
            "title": "Leather & fit",
            "fields": ["leather.thickness", "leather.compression",
                       "fit.clearance", "fit.gap_override"],
            "description": "Together these set the forming gap between the two halves.",
        },
        {
            "id": "mold",
            "title": "Mold",
            "fields": ["mold.flange_width", "mold.base_plate_thickness",
                       "mold.cavity_plate_thickness", "mold.male_root_blend",
                       "mold.male_floor_blend", "mold.female_entry_blend_top",
                       "mold.female_entry_blend_bottom", "mold.plate_edge_chamfer",
                       "mold.flange_relief_depth", "mold.parts"],
        },
        {
            "id": "features",
            "title": "Features",
            "fields": ["features.clamp_holes", "features.pry_notches",
                       "features.alignment_pins"],
        },
        {
            "id": "manufacturing",
            "title": "Manufacturing",
            "fields": ["manufacturing.pin_fit_clearance", "manufacturing.min_wall",
                       "manufacturing.nozzle_diameter"],
        },
        {
            "id": "advanced",
            "title": "Advanced",
            "fields": ["tray.draft_angle", "tray.draft_mode", "tray.datum", "quality"],
            "collapsed": True,
        },
    ],
    "hidden": ["schema_version", "name"],
    "fields": {
        "tray.profile": {
            # Offered in the picker but not selectable, with the reason shown in
            # place of the usual one-line description. Both were found by
            # building them; see trayapi.policy.UNSUPPORTED_COMBINATIONS and
            # docs/architecture.md 7.9.
            "disabled_values": {
                "superellipse": {
                    "code": "E-PROFILE-ENTRY-BLEND",
                    "reason": "Not available yet — the cavity's entry blend and the "
                              "plug's floor blend both fail on this curve.",
                },
            }
        },
        "tray.profile.length": {"unit": "mm", "step": 1, "slider": [40, 400]},
        "tray.profile.width": {"unit": "mm", "step": 1, "slider": [40, 300]},
        "tray.profile.corner_setback": {"unit": "mm", "step": 1},
        "tray.profile.corner_radius": {"unit": "mm", "step": 1},
        "tray.profile.rho": {"step": 0.05},
        "tray.profile.exponent": {"step": 0.25},
        "tray.depth": {"unit": "mm", "step": 0.5, "slider": [5, 120]},
        "tray.datum": {
            "disabled_values": {
                "outer": {
                    "code": "E-DATUM-001",
                    "reason": "Outer-dimension input is planned but not implemented. "
                              "The canonical datum is the inner (male) forming profile.",
                }
            }
        },
        "tray.draft_angle": {
            "unit": "deg",
            "step": 0.5,
            "experimental": True,
            "requires": "allow_experimental",
            "note": "Draft is experimental. The current build holds a constant "
                    "profile-plane gap, so the normal forming gap is "
                    "nominal x cos(draft angle) - 45.6 um smaller at 10 deg on a 3 mm gap. "
                    "The semantic contract is not decided.",
        },
        "tray.draft_mode": {"experimental": True, "requires": "allow_experimental"},
        "leather.thickness": {"unit": "mm", "step": 0.1, "slider": [0.5, 8]},
        "leather.compression": {"step": 0.01, "slider": [0, 0.4],
                                "help": "Fraction the wet leather is deliberately squeezed."},
        "fit.clearance": {"unit": "mm", "step": 0.05, "slider": [-0.5, 2]},
        "fit.gap_override": {"unit": "mm", "step": 0.1,
                             "help": "Set the forming gap directly, ignoring the formula."},
        "mold.flange_width": {"unit": "mm", "step": 1, "slider": [8, 80]},
        "mold.base_plate_thickness": {"unit": "mm", "step": 1, "slider": [3, 40]},
        "mold.cavity_plate_thickness": {"unit": "mm", "step": 1, "slider": [3, 80]},
        "mold.plate_edge_chamfer": {"unit": "mm", "step": 0.5, "unimplemented": True},
        "mold.flange_relief_depth": {"unit": "mm", "step": 0.5, "unimplemented": True},
        "manufacturing.pin_fit_clearance": {"unit": "mm", "step": 0.05},
        "manufacturing.min_wall": {"unit": "mm", "step": 0.5},
        "manufacturing.nozzle_diameter": {"unit": "mm", "step": 0.1},
    },
    "derived": [
        {"key": "forming_gap", "label": "Forming gap", "unit": "mm", "precision": 3},
        {"key": "plate_length", "label": "Plate length", "unit": "mm", "precision": 1},
        {"key": "plate_width", "label": "Plate width", "unit": "mm", "precision": 1},
        {"key": "closed_height", "label": "Closed height", "unit": "mm", "precision": 1},
        {"key": "female_flange_width", "label": "Female flange", "unit": "mm", "precision": 1},
        {"key": "corner_setback", "label": "Corner setback", "unit": "mm", "precision": 1},
        {"key": "corner_radius_min", "label": "Tightest radius", "unit": "mm", "precision": 2},
        {"key": "vertical_wall_height", "label": "Vertical wall", "unit": "mm", "precision": 1},
        {"key": "max_inward_offset", "label": "Max inward offset", "unit": "mm", "precision": 2},
    ],
}

#: Combinations the kernel cannot build, served so the form can stop offering
#: them instead of letting someone assemble one and then explaining the refusal.
#: The rules live in `policy` with the diagnostics they also produce for API
#: callers that are not this form; here they are only reshaped for the wire
#: (tuples to lists, and without the long `message`, which is written for
#: someone reading an API response rather than someone using the app).
UI_HINTS["conflicts"] = [
    {
        "code": rule["code"],
        "when": {"field": rule["when"]["field"], "kind_in": list(rule["when"]["kind_in"])},
        "field": rule["field"],
        "allowed": list(rule["allowed"]),
        "fallback": rule["fallback"],
        "reason": rule["reason"],
    }
    for rule in _POLICY.UNSUPPORTED_COMBINATIONS
]
