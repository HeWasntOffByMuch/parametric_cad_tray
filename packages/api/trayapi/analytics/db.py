"""Connection handling and deterministic schema migration.

One SQLite file, opened once per thread. FastAPI runs sync endpoints in a
threadpool, so a thread-local connection avoids both a global lock and the
cross-thread sharing sqlite3 refuses by default.

Analytics is secondary to the CAD application throughout: every entry point in
this package swallows its own errors. A locked or missing database must never
be the reason a preview, an export or a download fails.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..settings import SETTINGS
from .schema import MIGRATIONS

log = logging.getLogger("trayapi.analytics")

_local = threading.local()


def utcnow() -> str:
    """UTC, ISO 8601, second resolution. Sorts lexically, reads without a tool."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def database_path() -> str:
    """Where the analytics file lives, empty meaning analytics is off.

    Read from the environment at call time rather than from the settings
    snapshot taken at import. `Settings` is frozen and captured once, which is
    right for a value the process cannot change - but this one is legitimately
    changed by an operator between restarts and by a test between cases, and a
    setting that only responds to the environment on the very first import is a
    setting that lies about being an environment variable.
    """
    return os.environ.get("TRAYMOLD_ANALYTICS_DB", SETTINGS.analytics_db).strip()


def enabled() -> bool:
    return bool(database_path())


def _configure(conn: sqlite3.Connection) -> None:
    # WAL so a reader (the stats endpoint) never blocks a writer (a download),
    # and a busy timeout so a brief overlap waits rather than raising.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=3000")
    # NORMAL rather than FULL: losing the last few events to a power cut is an
    # acceptable trade for not fsyncing on the download path.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row


def migrate(conn: sqlite3.Connection) -> int:
    """Apply outstanding migrations. Idempotent: re-running is a no-op.

    Version is tracked in SQLite's own `user_version`, so there is no bootstrap
    table to create first and no state outside the file.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for index, statements in enumerate(MIGRATIONS, start=1):
        if index <= current:
            continue
        with conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version={index}")
    return len(MIGRATIONS)


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """A migrated connection for this thread, or raise if analytics is off."""
    target = str(path or database_path())
    if not target:
        raise RuntimeError("analytics is disabled")
    existing = getattr(_local, "conn", None)
    if existing is not None and getattr(_local, "path", None) == target:
        return existing
    if existing is not None:
        existing.close()
    Path(target).expanduser().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(Path(target).expanduser()))
    _configure(conn)
    migrate(conn)
    _local.conn = conn
    _local.path = target
    return conn


def reset_thread_state() -> None:
    """Drop this thread's connection. For tests that swap the database path."""
    existing = getattr(_local, "conn", None)
    if existing is not None:
        existing.close()
    _local.conn = None
    _local.path = None


@contextmanager
def session():
    """Yield a connection, or None when analytics is off or unusable.

    Callers write `with session() as conn: if conn is None: return`. Nothing in
    this package raises past this boundary.
    """
    if not enabled():
        yield None
        return
    try:
        conn = connect()
    except Exception:
        log.warning("analytics database unavailable; continuing without it", exc_info=True)
        yield None
        return
    try:
        yield conn
    except Exception:
        log.warning("analytics write failed; continuing", exc_info=True)
