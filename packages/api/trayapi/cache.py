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
import os
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

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


@dataclass
class CacheStats:
    entries: int
    bytes: int
    last_sweep_at: float | None
    last_sweep_removed: int
    max_bytes: int
    max_age_s: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class ArtifactCache:
    """Content-addressed store with bounded growth.

    Eviction is age-then-LRU: anything past `cache_max_age_s` goes, then the
    least recently *read* entries go until the store is under `cache_max_bytes`.
    Recency is the directory's mtime, touched on every hit, so a design someone
    keeps coming back to survives a design built once and forgotten.

    An entry belonging to an active job is never removed, however old: the job
    is about to hand out its URLs.
    """

    def __init__(self, root: Path | None = None):
        self.root = Path(root or SETTINGS.cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_sweep_at: float | None = None
        self._last_sweep_removed = 0
        self._pinned: set[str] = set()

    def dir_for(self, key: str) -> Path:
        return self.root / key

    def get(self, key: str) -> dict | None:
        directory = self.dir_for(key)
        path = directory / RESULT_FILE
        if not path.exists():
            return None
        try:
            report = json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
        for artifact in report.get("artifacts", []):
            if not Path(artifact["path"]).exists():
                return None
        self._touch(directory)
        return report

    def _touch(self, directory: Path) -> None:
        """Mark an entry as recently used.  Eviction reads this."""
        try:
            now = time.time()
            os.utime(directory, (now, now))
        except OSError:  # pragma: no cover
            pass

    # -- pinning -----------------------------------------------------------
    def pin(self, key: str) -> None:
        """Protect an entry from eviction while a job owns it."""
        with self._lock:
            self._pinned.add(key)

    def unpin(self, key: str) -> None:
        with self._lock:
            self._pinned.discard(key)

    # -- eviction ----------------------------------------------------------
    def _entries(self) -> list[tuple[Path, float, int]]:
        out = []
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            size = sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
            out.append((directory, directory.stat().st_mtime, size))
        return out

    def stats(self) -> CacheStats:
        entries = self._entries()
        return CacheStats(
            entries=len(entries),
            bytes=sum(e[2] for e in entries),
            last_sweep_at=self._last_sweep_at,
            last_sweep_removed=self._last_sweep_removed,
            max_bytes=SETTINGS.cache_max_bytes,
            max_age_s=SETTINGS.cache_max_age_s,
        )

    def sweep(self, *, max_bytes: int | None = None, max_age_s: float | None = None) -> dict:
        max_bytes = SETTINGS.cache_max_bytes if max_bytes is None else max_bytes
        max_age_s = SETTINGS.cache_max_age_s if max_age_s is None else max_age_s
        with self._lock:
            pinned = set(self._pinned)
        entries = [e for e in self._entries() if e[0].name not in pinned]
        now = time.time()
        removed: list[str] = []

        for directory, mtime, _size in list(entries):
            if now - mtime > max_age_s:
                shutil.rmtree(directory, ignore_errors=True)
                removed.append(directory.name)
                entries.remove((directory, mtime, _size))

        total = sum(e[2] for e in entries)
        for directory, mtime, size in sorted(entries, key=lambda e: e[1]):
            if total <= max_bytes:
                break
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(directory.name)
            total -= size

        self._last_sweep_at = now
        self._last_sweep_removed = len(removed)
        return {"removed": removed, "remaining_bytes": total}

    def put(self, key: str, report: dict) -> dict:
        directory = self.dir_for(key)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / RESULT_FILE).write_text(json.dumps(report, indent=2, sort_keys=True))
        self._touch(directory)
        return report

    def artifact_path(self, key: str, name: str) -> Path | None:
        if "/" in name or "\\" in name or name.startswith("."):
            return None
        directory = self.dir_for(key)
        path = directory / name
        if not (path.exists() and path.is_file()):
            return None
        self._touch(directory)
        return path

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
