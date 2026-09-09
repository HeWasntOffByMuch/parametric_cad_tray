"""Reproduce the offset evidence in docs/architecture.md 4.4.

    python3 tools/reference_probe/verify_offset.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))
sys.path.insert(0, str(ROOT / "packages" / "tray-core" / "tests"))

import reference as R  # noqa: E402
from traymold.profiles import (  # noqa: E402
    make_base_profile,
    measure_offset_distance,
    offset_profile,
    profile_deviation,
    sample_wire,
)
from traymold.presets import REF_4X7_STEP as P  # noqa: E402

Z_REF = 35.0          # a height where both walls are straight
NOMINAL = 3.0


def main() -> int:
    base = make_base_profile(P.tray.profile)
    male_ref = R.load_reference("male_tray_mold.step")
    female_ref = R.load_reference("female_tray_mold.step")

    m = profile_deviation(sample_wire(base, 400), R.forming_loop(male_ref, Z_REF))
    print("1. male base profile (analytic) vs STEP male section")
    print(f"   min/max/rms = {m['min']*1e3:8.3f} / {m['max']*1e3:8.3f} / {m['rms']*1e3:8.3f} um")

    offset = offset_profile(base, NOMINAL)
    f = profile_deviation(sample_wire(offset, 400), R.forming_loop(female_ref, Z_REF))
    print(f"\n2. offset(male base, {NOMINAL:.6f}) vs STEP female cavity section")
    print(f"   requested nominal offset : {NOMINAL:.6f} mm")
    print(f"   minimum deviation        : {f['min']*1e3:8.3f} um")
    print(f"   maximum deviation        : {f['max']*1e3:8.3f} um")
    print(f"   RMS deviation            : {f['rms']*1e3:8.3f} um")

    ours = measure_offset_distance(offset, base)
    print("\n3. realised offset distances")
    print(f"   ours  (offset -> base)      : {ours['min']:.6f} .. {ours['max']:.6f} mm")
    ref_pts = R.forming_loop(female_ref, Z_REF, per_edge=300)
    theirs = profile_deviation(ref_pts, R.forming_loop(male_ref, Z_REF))
    print(f"   Onshape (STEP fem -> male)  : {theirs['min']:.6f} .. {theirs['max']:.6f} mm")

    print("\n4. re-parameterisation hypothesis (same template at s = 55.5)")
    from traymold.params import G2QuinticObroundProfile

    reparam = make_base_profile(G2QuinticObroundProfile(length=181.0, width=111.0))
    d = profile_deviation(sample_wire(reparam, 400), ref_pts)
    print(f"   template(s=55.5) vs STEP female: max {d['max']*1e3:8.2f} um  <- ruled out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
