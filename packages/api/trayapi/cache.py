"""Content-addressed artifact cache.

The key covers everything that can change the bytes on disk and nothing that
cannot.  Presentation-only fields - the design's `name` - are excluded by the
core's `canonical_params`, so two users who name the same design differently
share one build.

    cache_key = sha256({
        params:   canonical parameters, minus non-geometric fields,
                  with the requested quality and part selection already folded in
        env:      schema version, model version, cadquery and OCP versions
        formats:  the requested artifact formats, sorted
    })

`quality` and `parts` do not appear as separate terms because `apply_options`
folds them into the parameter document first: asking for `params` + quality
`preview` and asking for `params.with_quality("preview")` are the same request
and must hash the same.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Sequence

from .settings import SETTINGS

RESULT_FILE = "result.json"
BUNDLE_NAME = "bundle.zip"


def cache_key(effective_params, formats: Sequence[str]) -> str:
    from traymold.api import canonical_json, canonical_params, environment

    payload = {
        "params": canonical_params(effective_params),
        "env": environment(),
        "formats": sorted(set(formats)),
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


class ArtifactCache:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or SETTINGS.cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def dir_for(self, key: str) -> Path:
        return self.root / key

    def get(self, key: str) -> dict | None:
        path = self.dir_for(key) / RESULT_FILE
        if not path.exists():
            return None
        try:
            report = json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
        for artifact in report.get("artifacts", []):
            if not Path(artifact["path"]).exists():
                return None
        return report

    def put(self, key: str, report: dict) -> dict:
        directory = self.dir_for(key)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / RESULT_FILE).write_text(json.dumps(report, indent=2, sort_keys=True))
        return report

    def artifact_path(self, key: str, name: str) -> Path | None:
        if "/" in name or "\\" in name or name.startswith("."):
            return None
        path = self.dir_for(key) / name
        return path if path.exists() and path.is_file() else None

    def bundle(self, key: str) -> Path | None:
        """Zip every artifact of a build.  Built once, then reused."""
        report = self.get(key)
        if not report:
            return None
        directory = self.dir_for(key)
        bundle = directory / BUNDLE_NAME
        if bundle.exists():
            return bundle
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
            for artifact in report["artifacts"]:
                zf.write(artifact["path"], artifact["name"])
            zf.writestr(RESULT_FILE, json.dumps(report, indent=2, sort_keys=True))
        return bundle

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
