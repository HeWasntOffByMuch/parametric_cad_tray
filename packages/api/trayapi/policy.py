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


def policy_diagnostics(params, allow_experimental: bool) -> list[dict]:
    out: list[dict] = []
    if params.tray.draft_angle > 0.0 and not allow_experimental:
        out.append(dict(DRAFT_EXPERIMENTAL))
    return out
