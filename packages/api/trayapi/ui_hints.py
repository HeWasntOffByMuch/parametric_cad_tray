"""Presentation hints for the future parameter form.

These live beside the schema, not inside it: they are the only place the API is
allowed to know anything about a UI, and nothing here reaches the geometry core.
"""

UI_HINTS = {
    "groups": [
        {"id": "tray", "title": "Tray", "fields": ["tray.profile", "tray.depth", "tray.datum"]},
        {"id": "leather", "title": "Leather & fit",
         "fields": ["leather.thickness", "leather.compression", "fit.clearance", "fit.gap_override"]},
        {"id": "blends", "title": "Edge treatments",
         "fields": ["mold.male_root_blend", "mold.male_floor_blend",
                    "mold.female_entry_blend_top", "mold.female_entry_blend_bottom"]},
        {"id": "mold", "title": "Mold construction",
         "fields": ["mold.flange_width", "mold.base_plate_thickness", "mold.cavity_plate_thickness"]},
        {"id": "features", "title": "Manufacturing features", "fields": ["features"]},
        {"id": "advanced", "title": "Advanced", "fields": ["tray.draft_angle", "manufacturing", "quality"]},
    ],
    "fields": {
        "tray.depth": {"unit": "mm", "step": 0.5},
        "tray.draft_angle": {
            "unit": "deg", "step": 0.5, "experimental": True,
            "note": "The gap semantics under draft are undecided: the current build holds a "
                    "constant profile-plane gap, so the normal gap is nominal * cos(draft). "
                    "Requires allow_experimental.",
        },
        "leather.thickness": {"unit": "mm", "step": 0.1},
        "leather.compression": {"unit": "fraction", "step": 0.01},
        "fit.clearance": {"unit": "mm", "step": 0.05},
        "mold.flange_width": {"unit": "mm", "step": 1.0},
        "mold.base_plate_thickness": {"unit": "mm", "step": 1.0},
        "mold.cavity_plate_thickness": {"unit": "mm", "step": 1.0},
        "tray.datum": {"unsupported_values": {"outer": "E-DATUM-001"}},
    },
}
