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
#: on. Both build perfectly well without that one treatment, so this constrains
#: the combination rather than the shape.
#:
#: Each was found by building it: an elliptical plug returns an empty solid from
#: the root-blend fuse, and a superellipse cavity comes back from the entry-blend
#: cut with a stray unclosed shell across the opening. The boolean invariants in
#: `mold._checked` catch both, but only after a worker has spent seconds on a
#: build that was never going to work - and after the user has waited for it.
#:
#: These are written as *constraints*, not as errors: `when` a profile is one of
#: these kinds, `field` is limited to `allowed`, and anything else becomes
#: `fallback`. A UI can read that and never offer the combination in the first
#: place - which is the point. `policy_diagnostics` still raises one as an error,
#: because an API caller that is not the form can post whatever it likes and has
#: to be told; nobody driving the app should ever see it.
#:
#: `allowed` is a whitelist rather than a blacklist of the treatments that fail,
#: so a treatment added later is off until someone has built it on this curve.
UNSUPPORTED_COMBINATIONS = (
    {
        "code": "E-PROFILE-ROOT-BLEND",
        "when": {"field": "tray.profile", "kind_in": ("ellipse",)},
        "field": "mold.male_root_blend",
        "allowed": ("none",),
        "fallback": "none",
        #: Shown on the disabled options, in the UI's voice: by the time anyone
        #: reads it the setting is already off, so it explains rather than asks.
        "reason": "Not available on an ellipse - the plug's root-blend fuse returns "
                  "an empty solid on a curve with no straight runs.",
        "message": (
            "an elliptical plug cannot take a root blend: the fuse returns an empty "
            "solid. Set mold.male_root_blend to none to build this shape, or choose a "
            "rounded-rectangle profile to keep the blend."
        ),
    },
)


def profile_kind(params) -> str | None:
    return getattr(params.tray.profile, "kind", None)


def _value_kind(params, path: str) -> str | None:
    """The discriminator at a dotted path, for a `when` clause."""
    node = params
    for part in path.split("."):
        node = getattr(node, part, None)
        if node is None:
            return None
    return getattr(node, "kind", node if isinstance(node, str) else None)


def constrains(rule: dict, params) -> bool:
    """Is this rule in force for the document as it stands?"""
    when = rule["when"]
    return _value_kind(params, when["field"]) in when["kind_in"]

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

    kind = profile_kind(params)
    parts = params.mold.parts

    stopped = UNSUPPORTED_PROFILES.get(kind)
    if stopped is not None:
        out.append({"code": stopped["code"], "severity": "error",
                    "field": stopped["field"], "message": stopped["message"]})
        return out           # no point also listing which treatment to turn off

    for rule in UNSUPPORTED_COMBINATIONS:
        if not constrains(rule, params):
            continue
        # Only if the half that fails is one the caller actually asked for: a
        # cavity-only build of an ellipse has no plug to blend the root of.
        group, _, name = rule["field"].partition(".")
        half = "female" if name.startswith("female") else "male"
        if not getattr(parts, half):
            continue
        if getattr(getattr(params, group), name).kind not in rule["allowed"]:
            out.append({
                "code": rule["code"], "severity": "error",
                "field": rule["field"], "message": rule["message"],
            })
    return out
