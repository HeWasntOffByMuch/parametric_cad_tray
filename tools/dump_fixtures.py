#!/usr/bin/env python3
"""Write the frontend's test fixture from the API itself.

`packages/web/tests/fixtures.json` is what every frontend test believes the
backend serves. Captured by hand it goes quietly stale, and a stale one is worse
than none: the suite keeps passing against a schema the API stopped sending. It
had drifted to the point of still carrying `required` without defaults on every
edge treatment - the exact shape of a bug that had already been fixed and that
the frontend suite therefore could not have caught.

Run `make fixtures` after any change to the parameter model or the UI hints.
`test_fixtures_are_current` fails the API suite when this has not been run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "tray-core"))
sys.path.insert(0, str(ROOT / "packages" / "api"))

FIXTURES = ROOT / "packages" / "web" / "tests" / "fixtures.json"


def fixtures() -> dict:
    """Exactly the bodies of `GET /api/schema` and `GET /api/presets`."""
    from fastapi.testclient import TestClient

    from trayapi.main import create_app

    with TestClient(create_app()) as client:
        return {
            "schema": client.get("/api/schema").json(),
            "presets": client.get("/api/presets").json(),
        }


def serialise(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def main() -> int:
    text = serialise(fixtures())
    if "--check" in sys.argv:
        if FIXTURES.read_text() != text:
            print(f"{FIXTURES} is out of date; run `make fixtures`", file=sys.stderr)
            return 1
        print(f"{FIXTURES} is current")
        return 0
    FIXTURES.write_text(text)
    print(f"wrote {FIXTURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
