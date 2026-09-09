"""Build-time benchmark.

    python3 tools/reference_probe/benchmark.py [runs]

Reports median wall time per configuration, the number of OCC offset operations
and unique accumulated offsets, the loft section count, and tessellation time
measured separately from B-rep construction.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))

import cadquery as cq  # noqa: E402

import traymold  # noqa: E402
from traymold.params import PartSelection  # noqa: E402
from traymold.presets import REF_4X7, REF_4X7_STEP  # noqa: E402
from traymold.quality import resolve  # noqa: E402

OUT = Path("/tmp/traymold-bench.stl")


def with_parts(params, male: bool, female: bool):
    return params.model_copy(
        update={"mold": params.mold.model_copy(update={"parts": PartSelection(male=male, female=female)})}
    )


def tessellate(result, quality) -> float:
    t0 = time.perf_counter()
    for shape in (result.male, result.female):
        if shape is None:
            continue
        cq.exporters.export(
            cq.Workplane(obj=shape), str(OUT), exportType="STL",
            tolerance=quality.linear_deflection, angularTolerance=quality.angular_deflection,
        )
    return time.perf_counter() - t0


def main(runs: int = 5) -> int:
    cases = [
        ("male only", with_parts(REF_4X7_STEP, True, False), "export"),
        ("female only", with_parts(REF_4X7_STEP, False, True), "export"),
        ("both", REF_4X7_STEP, "export"),
        ("both, featured", REF_4X7, "export"),
        ("male only", with_parts(REF_4X7_STEP, True, False), "preview"),
        ("female only", with_parts(REF_4X7_STEP, False, True), "preview"),
        ("both", REF_4X7_STEP, "preview"),
        ("both, featured", REF_4X7, "preview"),
    ]
    print(f"median of {runs} runs\n")
    print(f"{'case':16} {'quality':8} {'brep s':>8} {'tess s':>8} {'total s':>8} "
          f"{'offsets':>8} {'unique':>7} {'sections':>9}")
    for label, params, mode in cases:
        p = params.with_quality(mode)
        quality = resolve(p)
        brep, tess = [], []
        result = None
        for _ in range(runs):
            t0 = time.perf_counter()
            result = traymold.build(p)
            brep.append(time.perf_counter() - t0)
            tess.append(tessellate(result, quality))
        b, t = statistics.median(brep), statistics.median(tess)
        print(f"{label:16} {mode:8} {b:8.2f} {t:8.3f} {b + t:8.2f} "
              f"{result.stats['offset_calls']:8d} {result.stats['unique_offsets']:7d} "
              f"{result.stats['total_sections']:9d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5))
