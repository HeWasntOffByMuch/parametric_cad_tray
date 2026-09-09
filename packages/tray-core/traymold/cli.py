"""Command line entry point: build, inspect and export a mold from parameters."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .derive import derive
from .exporters import export_all
from .mold import build
from .params import Params
from .presets import PRESETS
from .version import MODEL_VERSION, SCHEMA_VERSION, kernel_versions


def _load(args) -> Params:
    if args.preset:
        if args.preset not in PRESETS:
            raise SystemExit(f"unknown preset {args.preset!r}; have {sorted(PRESETS)}")
        return PRESETS[args.preset]
    if args.params:
        return Params.model_validate(json.loads(Path(args.params).read_text()))
    return Params()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="traymold")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("build", "derive"):
        p = sub.add_parser(name)
        p.add_argument("--preset")
        p.add_argument("--params")
        if name == "build":
            p.add_argument("-o", "--outdir", default="out")

    sub.add_parser("schema")
    sub.add_parser("presets")
    sub.add_parser("version")

    args = ap.parse_args(argv)
    if args.cmd == "schema":
        print(json.dumps(Params.model_json_schema(), indent=2))
        return 0
    if args.cmd == "presets":
        print("\n".join(sorted(PRESETS)))
        return 0
    if args.cmd == "version":
        print(json.dumps({"schema": SCHEMA_VERSION, "model": MODEL_VERSION, **kernel_versions()}, indent=2))
        return 0

    params = _load(args)
    if args.cmd == "derive":
        print(json.dumps(derive(params).as_dict(), indent=2))
        return 0

    t0 = time.time()
    result = build(params)
    elapsed = time.time() - t0
    written = export_all(result, args.outdir, params)
    print(json.dumps({
        "name": params.name,
        "seconds": round(elapsed, 2),
        "volumes_cm3": {k: round(v, 3) for k, v in result.volumes.items()},
        "derived": result.derived,
        "written": {k: str(v) for k, v in written.items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
