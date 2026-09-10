"""API-level policy.

Rules that are about *what we expose*, not about what the geometry can do.  The
core stays free of product decisions; this is where a parameter is gated.
"""

from __future__ import annotations

DRAFT_EXPERIMENTAL = {
    "code": "E-DRAFT-EXPERIMENTAL",
    "severity": "error",
    "field": "tray.draft_angle",
    "message": (
        "nonzero draft is experimental and not exposed by default. The current "
        "implementation holds a constant profile-plane gap, so the normal forming gap "
        "is nominal * cos(draft_angle) - -45.6 um at 10 deg on a 3 mm gap. The semantic "
        "contract is undecided. Set allow_experimental to build with it anyway."
    ),
}


#: Plan curves the kernel cannot currently take one particular edge treatment
#: on. Both build perfectly well without that one treatment, so this refuses the
#: combination rather than the shape - and says which half of it to change.
#:
#: Each was found by building it: an elliptical plug returns an empty solid from
#: the root-blend fuse, and a superellipse cavity comes back from the entry-blend
#: cut with a stray unclosed shell across the opening. The boolean invariants in
#: `mold._checked` catch both, but only after a worker has spent seconds on a
#: build that was never going to work - and after the user has waited for it.
UNSUPPORTED_COMBINATIONS = (
    {
        "kinds": ("ellipse",),
        "treatments": ("male_root_blend",),
        "code": "E-PROFILE-ROOT-BLEND",
        "field": "mold.male_root_blend",
        "message": (
            "an elliptical plug cannot take a root blend: the fuse returns an empty "
            "solid. Set mold.male_root_blend to none to build this shape, or choose a "
            "rounded-rectangle profile to keep the blend."
        ),
    },
)

#: Plan curves that cannot currently produce an exportable mold at all, whatever
#: else is turned off. Refused outright rather than as a combination, because
#: offering a preview of something that cannot be exported is a trap.
UNSUPPORTED_PROFILES = {
    "superellipse": {
        "code": "E-PROFILE-SUPERELLIPSE",
        "field": "tray.profile.kind",
        "message": (
            "a superellipse cannot currently be built into a mold. Two separate steps "
            "fail on this curve: the cavity's entry blend cut leaves a stray face "
            "across the opening, and the plug's floor blend cannot be lofted above 8 "
            "sections - export uses 35, so it fails there even with the entry blend "
            "off. Choose a rounded-rectangle or obround profile; both take every "
            "treatment."
        ),
    },
}


def policy_diagnostics(params, allow_experimental: bool) -> list[dict]:
    out: list[dict] = []
    if params.tray.draft_angle > 0.0 and not allow_experimental:
        out.append(dict(DRAFT_EXPERIMENTAL))

    kind = getattr(params.tray.profile, "kind", None)
    parts = params.mold.parts

    stopped = UNSUPPORTED_PROFILES.get(kind)
    if stopped is not None:
        out.append({"code": stopped["code"], "severity": "error",
                    "field": stopped["field"], "message": stopped["message"]})
        return out           # no point also listing which treatment to turn off

    for rule in UNSUPPORTED_COMBINATIONS:
        if kind not in rule["kinds"]:
            continue
        # Only if the half that fails is one the caller actually asked for: a
        # cavity-only build of an ellipse has no plug to blend the root of.
        half = "female" if "female" in rule["treatments"][0] else "male"
        if not getattr(parts, half):
            continue
        if any(getattr(params.mold, name).active for name in rule["treatments"]):
            out.append({
                "code": rule["code"], "severity": "error",
                "field": rule["field"], "message": rule["message"],
            })
    return out
