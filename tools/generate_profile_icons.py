"""Generate the profile-picker icons from the real plan curves.

    PYTHONPATH=packages/tray-core python3 tools/generate_profile_icons.py

The icons in the shape picker are not drawings of what each profile looks
like - they are each profile, sampled from the same `make_base_profile` the
mold is built from and fitted to a common box. A hand-drawn "rounded rectangle"
would be a guess, and the whole point of the picker is to show the difference
between eight curves that a word cannot distinguish.

Baked to TypeScript at build time rather than computed in the browser: the
front end contains no CAD, and this keeps it that way. Re-run it if a profile
family is added or its shape changes; `profileShapes.test.ts` fails if a kind
in the schema has no path here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "tray-core"))

from traymold.params import (  # noqa: E402
    CircularObroundProfile, CircularRectProfile, ConicObroundProfile, ConicRectProfile,
    EllipseProfile, G2QuinticObroundProfile, G2QuinticRectProfile, SuperellipseProfile,
)
from traymold.profiles import make_base_profile, sample_wire  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "packages/web/src/form/profileShapes.ts"

#: A square-ish plan, so the families are told apart by their corners rather
#: than by how long the tray happens to be. The reference is 175x105; 150x100
#: keeps the obrounds obviously obround without flattening the rects.
LENGTH, WIDTH = 150.0, 100.0

#: The icon box. 24x16 leaves a hairline of padding for the stroke.
BOX_W, BOX_H = 24.0, 16.0
PAD = 1.0

PROFILES = [
    G2QuinticObroundProfile(length=LENGTH, width=WIDTH),
    G2QuinticRectProfile(length=LENGTH, width=WIDTH),
    ConicObroundProfile(length=LENGTH, width=WIDTH),
    ConicRectProfile(length=LENGTH, width=WIDTH),
    CircularObroundProfile(length=LENGTH, width=WIDTH),
    CircularRectProfile(length=LENGTH, width=WIDTH),
    EllipseProfile(length=LENGTH, width=WIDTH),
    SuperellipseProfile(length=LENGTH, width=WIDTH),
]


def path_for(profile) -> str:
    points = sample_wire(make_base_profile(profile), per_edge=120)
    # One scale for both axes, so the icons keep the tray's real proportion and
    # an ellipse cannot be mistaken for a circle.
    width_mm = float(np.ptp(points[:, 0]))
    height_mm = float(np.ptp(points[:, 1]))
    span = max(width_mm, height_mm * (BOX_W - 2 * PAD) / (BOX_H - 2 * PAD))
    scale = (BOX_W - 2 * PAD) / span
    xy = points * scale
    xy[:, 0] += BOX_W / 2 - (xy[:, 0].min() + xy[:, 0].max()) / 2
    # SVG's y grows downward; the profile's does not.
    xy[:, 1] = BOX_H / 2 - (xy[:, 1] - (points[:, 1].min() + points[:, 1].max()) / 2 * scale)

    # Douglas-Peucker down to something a 24px icon can tell apart, so the file
    # is a few hundred bytes rather than tens of kilobytes.
    kept = simplify(xy, tolerance=0.012)
    parts = [f"M{kept[0][0]:.2f} {kept[0][1]:.2f}"]
    parts += [f"L{x:.2f} {y:.2f}" for x, y in kept[1:]]
    return " ".join(parts) + "Z"


def simplify(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Ramer-Douglas-Peucker, iterative so a 1000-point loop cannot blow the stack."""
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        a, b = points[start], points[end]
        segment = b - a
        length = np.hypot(*segment)
        if length == 0:
            distances = np.hypot(*(points[start + 1:end] - a).T)
        else:
            rel = points[start + 1:end] - a
            # 2D cross product by hand: np.cross deprecated it in NumPy 2.
            distances = np.abs(segment[0] * rel[:, 1] - segment[1] * rel[:, 0]) / length
        index = int(np.argmax(distances))
        if distances[index] > tolerance:
            split = start + 1 + index
            keep[split] = True
            stack += [(start, split), (split, end)]
    return points[keep]


def main() -> int:
    rows = []
    for profile in PROFILES:
        rows.append((profile.kind, path_for(profile)))

    body = "\n".join(f"  {kind!r}: '{path}',".replace("'", "'") for kind, path in rows)
    OUT.write_text(f'''/**
 * The plan curve of every profile family, as an SVG path.
 *
 * GENERATED - do not edit by hand. Regenerate with:
 *
 *     PYTHONPATH=packages/tray-core python3 tools/generate_profile_icons.py
 *
 * Each path is the real curve, sampled from the same `make_base_profile` the
 * mold is built from at {LENGTH:.0f} x {WIDTH:.0f} mm and fitted to a
 * {BOX_W:.0f} x {BOX_H:.0f} box. They are drawn rather than described because
 * the difference between eight of these is not something a word carries: a
 * G2 quintic corner and a circular one have the same "rounded" in prose and
 * visibly different curvature on screen.
 *
 * This is a build-time artifact, not CAD in the browser. The front end still
 * computes no geometry.
 */
export const PROFILE_VIEWBOX = '0 0 {BOX_W:.0f} {BOX_H:.0f}'

export const PROFILE_SHAPES: Record<string, string> = {{
{body}
}}
''')
    print(f"wrote {OUT.relative_to(Path.cwd())}")
    for kind, path in rows:
        print(f"  {kind:26} {len(path):5} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
