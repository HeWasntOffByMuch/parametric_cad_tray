"""Worker entry point: `python -m trayapi.worker_main <address> <authkey-hex>`.

A real program rather than a `multiprocessing.Process` target, because every
`multiprocessing` start method re-imports the parent's `__main__` in the child.
That is fine under `uvicorn` and fatal under pytest, a stdin script, or anything
else whose `__main__` is not import-safe - and the API must not care how it was
launched.  A subprocess plus a `multiprocessing.connection` socket keeps the same
pickled duplex channel with none of that coupling.
"""

from __future__ import annotations

import os
import sys
import traceback


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    address, authkey_hex = argv[0], argv[1]

    from multiprocessing.connection import Client

    conn = Client(address, authkey=bytes.fromhex(authkey_hex))
    try:
        from traymold import api
        from traymold.params import Params
    except Exception:
        conn.send({"ready": False, "detail": traceback.format_exc()})
        return 1
    conn.send({"ready": True, "pid": os.getpid()})

    from trayapi.errors import classify

    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return 0
        if msg is None:
            return 0
        try:
            params = Params.model_validate(msg["params"])
            # The fraction table is computed here, in the process that is about
            # to do the work, so it can never disagree with the stages the build
            # actually runs. The parent is sent numbers, not a vocabulary it
            # would have to keep in step.
            from traymold.api import apply_options
            from traymold.progress import LABELS, plan

            effective = apply_options(params, msg["quality"], msg["parts"])
            table = plan(effective)

            def report_stage(stage: str) -> None:
                # A progress frame is a message on the same pipe as the result,
                # distinguished by its key. It must never raise: a broken pipe
                # here would abandon a build that is otherwise fine, and the
                # parent's own recv loop will notice the worker is gone anyway.
                try:
                    conn.send({"progress": {
                        "stage": stage,
                        "fraction": table.get(stage, 0.0),
                        "label": LABELS.get(stage, stage),
                    }})
                except Exception:
                    pass

            report = api.build_and_emit(
                params,
                msg["quality"],
                msg["parts"],
                tuple(msg["formats"]),
                msg["outdir"],
                on_stage=report_stage,
            )
            conn.send({"ok": True, "report": report.as_dict()})
        except BaseException as exc:  # noqa: BLE001 - catching everything is the point
            kind, message, diagnostics = classify(exc)
            # the traceback stays here, in the worker's stderr, never in a response
            print(f"[worker {os.getpid()}] {kind}\n{traceback.format_exc()}", file=sys.stderr, flush=True)
            conn.send({"ok": False, "kind": kind, "message": message, "diagnostics": diagnostics})


if __name__ == "__main__":
    raise SystemExit(main())
