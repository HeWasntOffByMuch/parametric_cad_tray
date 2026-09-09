"""What does the current draft implementation actually hold constant?

The implementation subtracts the same height-dependent plan offset `z*tan(theta)`
from both the male and the female profile families, so the two walls should stay
a constant distance apart *in the profile plane*.  This measures both separations
directly on built solids:

  horizontal - min distance between the two plan sections at the same height
  normal     - true 3D min distance from a point on the plug wall to the cavity

    python3 tools/reference_probe/draft_analysis.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))
sys.path.insert(0, str(ROOT / "packages" / "tray-core" / "tests"))

import cadquery as cq  # noqa: E402
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex  # noqa: E402
from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: E402
from OCP.gp import gp_Pnt  # noqa: E402

import reference as R  # noqa: E402
import traymold  # noqa: E402
from traymold.presets import REF_4X7_STEP as BASE  # noqa: E402
from traymold.profiles import profile_deviation  # noqa: E402

ANGLES = (0.0, 1.0, 3.0, 5.0, 10.0)
Z = 12.5  # mid-wall, clear of every edge treatment


def point_to_shape(p, shape) -> float:
    v = BRepBuilderAPI_MakeVertex(gp_Pnt(float(p[0]), float(p[1]), float(p[2]))).Vertex()
    d = BRepExtrema_DistShapeShape(v, shape.wrapped)
    d.Perform()
    return float(d.Value())


def main() -> int:
    gap = 3.0
    print(f"forming gap = {gap} mm, measured at z = {Z} mm (mid-wall)\n")
    print(f"{'draft':>7} {'horizontal':>12} {'h - gap':>10} {'normal':>12} "
          f"{'n - gap':>10} {'gap*cos(t)':>12} {'n - gap*cos':>12}")
    for angle in ANGLES:
        params = BASE.model_copy(
            update={"tray": BASE.tray.model_copy(update={"draft_angle": angle})}
        ).with_quality("preview")
        result = traymold.build(params)
        male_sec = R.forming_loop(result.male, Z, per_edge=200)
        fem_sec = R.forming_loop(result.female, Z, per_edge=200)
        horizontal = profile_deviation(male_sec, fem_sec)["min"]

        # a handful of points on the plug wall, measured in 3D against the female
        probe = male_sec[:: max(1, len(male_sec) // 8)][:8]
        normal = min(point_to_shape([p[0], p[1], Z], result.female) for p in probe)

        predicted = gap * math.cos(math.radians(angle))
        print(f"{angle:6.1f}° {horizontal:12.6f} {horizontal - gap:+10.6f} {normal:12.6f} "
              f"{normal - gap:+10.6f} {predicted:12.6f} {normal - predicted:+12.6f}")

    print("\nInterpretation")
    print("  horizontal stays at the requested gap for every angle    -> the current")
    print("  implementation preserves a constant PROFILE-PLANE gap.")
    print("  normal follows gap*cos(theta), i.e. the true wall-to-wall")
    print("  separation shrinks with draft. At 10 deg that is -45.6 um on a 3 mm gap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
