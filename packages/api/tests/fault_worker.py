"""A worker that fails on purpose, so the failure paths are actually exercised.

Selected with `WorkerPool(module="fault_worker")`.  The fault is chosen by the
`name` field of the parameters it is sent, which keeps the wire protocol
identical to the real worker's.
"""

from __future__ import annotations

import os
import sys
import time


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from multiprocessing.connection import Client

    conn = Client(argv[0], authkey=bytes.fromhex(argv[1]))
    conn.send({"ready": True, "pid": os.getpid()})
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return 0
        if msg is None:
            return 0
        fault = msg.get("params", {}).get("name", "")
        if fault == "fault-raise":
            conn.send({"ok": False, "kind": "geometry_build_error",
                       "message": "the geometry kernel could not build this parameter set",
                       "diagnostics": []})
        elif fault == "fault-crash":
            os._exit(9)
        elif fault == "fault-hang":
            time.sleep(3600)
        else:
            conn.send({"ok": True, "report": {
                "params_hash": "0" * 64, "schema_version": "0", "model_version": "0",
                "quality": msg["quality"], "parts": msg["parts"], "diagnostics": [],
                "derived": {}, "stats": {}, "volumes_cm3": {}, "artifacts": [],
                "timings": {"build_s": 0.0, "emit_s": 0.0},
            }})


if __name__ == "__main__":
    raise SystemExit(main())
