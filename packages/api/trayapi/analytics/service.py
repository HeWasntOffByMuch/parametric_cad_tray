"""Recording and querying. Every public function here is failure-safe.

The rule the whole module exists to serve:

    A *qualified custom usage* is one (session, config_hash) pair for which a
    genuinely custom configuration was built successfully and at least one of
    its exportable artifacts was actually served.

Deduplication is the UNIQUE(session_id, config_hash) constraint, not a check in
Python - two downloads arriving on different threads at the same instant must
not be able to both decide they are the first.
"""

from __future__ import annotations

import json
import logging
import threading
import time

from .custom import dimensions, is_custom_configuration, preset_name
from .db import session, utcnow
from .sources import clean, normalize_source, referrer_host

log = logging.getLogger("trayapi.analytics")

#: The only events a browser may report. Anything else is dropped: the public
#: counter must not be reachable from client-submitted data.
CLIENT_EVENTS = ("app_opened", "config_engaged", "share_link_copied", "makerworld_clicked")

#: Server-recorded events.
SERVER_EVENTS = (
    "preview_requested", "preview_completed", "preview_failed",
    "export_requested", "export_completed", "export_failed",
    "artifact_downloaded",
)

#: Formats whose download means someone took the mold away. A GLB is the preview
#: the viewer renders - fetching it is not a download in any sense a counter
#: should care about.
QUALIFYING_FORMATS = ("step", "stl", "zip")

_ID_MAX = 64


def _id(value: str | None) -> str | None:
    """Accept an opaque client id, bounded. Never derived, never inspected."""
    if not value:
        return None
    text = str(value).strip()
    return text[:_ID_MAX] or None


def parse_artifact(name: str) -> tuple[str | None, str | None]:
    """`male.stl` -> ("stl", "male"); `bundle.zip` -> ("zip", "assembly")."""
    if "." not in name:
        return None, None
    stem, _, extension = name.rpartition(".")
    fmt = extension.lower() or None
    if stem == "bundle":
        return fmt, "assembly"
    if stem in ("male", "female"):
        return fmt, stem
    return fmt, "assembly"


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------
def ensure_session(conn, session_id: str, visitor_id: str | None = None, *,
                   source: str | None = None, medium: str | None = None,
                   campaign: str | None = None, referrer: str | None = None,
                   landing_path: str | None = None) -> None:
    """Create the session on first sight; afterwards only touch `last_seen_at`.

    First-touch attribution is the point: navigating around inside the app must
    not rewrite where the visit came from.
    """
    now = utcnow()
    host = referrer_host(referrer)
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO sessions
               (session_id, visitor_id, first_seen_at, last_seen_at,
                source, medium, campaign, referrer_host, landing_path)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (session_id, _id(visitor_id) or "unknown", now, now,
             normalize_source(source, host), clean(medium), clean(campaign),
             host, clean(landing_path, 128)),
        )
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE session_id=?", (now, session_id))


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------
def record_client_event(event_type: str, session_id: str | None, visitor_id: str | None = None,
                        *, source=None, medium=None, campaign=None, referrer=None,
                        landing_path=None, metadata: dict | None = None) -> None:
    if event_type not in CLIENT_EVENTS:
        return
    sid = _id(session_id)
    with session() as conn:
        if conn is None or sid is None:
            return
        ensure_session(conn, sid, visitor_id, source=source, medium=medium, campaign=campaign,
                       referrer=referrer, landing_path=landing_path)
        with conn:
            conn.execute(
                "INSERT INTO analytics_events (event_type, session_id, created_at, metadata)"
                " VALUES (?,?,?,?)",
                (event_type, sid, utcnow(), json.dumps(metadata)[:512] if metadata else None),
            )


def record_design(cache_key: str, config_hash: str, params, quality: str | None = None) -> None:
    """Remember what a cache key was built from.

    The artifact route is handed a key and nothing else. Without this row a
    download could only be attributed by rebuilding the geometry, which is not a
    thing analytics gets to do.
    """
    with session() as conn:
        if conn is None:
            return
        data = params if isinstance(params, dict) else params.model_dump(mode="json")
        dims = dimensions(data)
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO designs
                   (cache_key, config_hash, is_custom, quality, preset, profile_kind,
                    tray_length_mm, tray_width_mm, tray_depth_mm,
                    leather_thickness_mm, leather_compression, forming_gap_mm, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cache_key, config_hash,
                 int(is_custom_configuration(data)), quality, preset_name(data),
                 dims["profile_kind"], dims["tray_length_mm"], dims["tray_width_mm"],
                 dims["tray_depth_mm"], dims["leather_thickness_mm"],
                 dims["leather_compression"], dims["forming_gap_mm"], utcnow()),
            )


def record_build_event(event_type: str, *, session_id: str | None = None, config_hash: str | None = None,
                       job_id: str | None = None, params=None, duration_ms: int | None = None,
                       error_code: str | None = None, output_format: str | None = None) -> None:
    """A preview or export reaching a known state, recorded server-side."""
    if event_type not in SERVER_EVENTS:
        return
    with session() as conn:
        if conn is None:
            return
        sid = _id(session_id)
        if sid:
            ensure_session(conn, sid)
        dims = dimensions(params) if params is not None else {}
        with conn:
            conn.execute(
                """INSERT INTO analytics_events
                   (event_type, session_id, created_at, config_hash, job_id, is_default, preset,
                    tray_length_mm, tray_width_mm, tray_depth_mm, leather_thickness_mm,
                    forming_gap_mm, output_format, duration_ms, error_code)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_type, sid, utcnow(), config_hash, job_id,
                 None if params is None else int(not is_custom_configuration(params)),
                 None if params is None else preset_name(params),
                 dims.get("tray_length_mm"), dims.get("tray_width_mm"), dims.get("tray_depth_mm"),
                 dims.get("leather_thickness_mm"), dims.get("forming_gap_mm"),
                 output_format, duration_ms, error_code),
            )


def record_download(cache_key: str, artifact_name: str, *, session_id: str | None = None,
                    visitor_id: str | None = None) -> None:
    """The one write that can move the public counter.

    Called only after the file has been found on disk and is about to be served,
    so a 404 or a probe for a key that does not exist cannot inflate anything.
    """
    fmt, part = parse_artifact(artifact_name)
    sid, vid = _id(session_id), _id(visitor_id)

    with session() as conn:
        if conn is None:
            return
        design = conn.execute(
            "SELECT * FROM designs WHERE cache_key=?", (cache_key,)
        ).fetchone()

        with conn:
            conn.execute(
                """INSERT INTO artifact_downloads
                   (session_id, visitor_id, config_hash, cache_key, artifact_name,
                    format, part, is_custom, downloaded_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (sid, vid, design["config_hash"] if design else None, cache_key,
                 artifact_name[:128], fmt, part,
                 design["is_custom"] if design else None, utcnow()),
            )

        # Every condition of the metric, in one place.
        if design is None or not design["is_custom"]:
            return
        if fmt not in QUALIFYING_FORMATS:
            return
        if not sid:
            # An anonymous download still counts towards the design-level
            # metric via artifact_downloads; it must not invent a session.
            return

        ensure_session(conn, sid, vid)
        row = conn.execute("SELECT source FROM sessions WHERE session_id=?", (sid,)).fetchone()
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO qualified_usages
                   (session_id, visitor_id, config_hash, first_download_at, source, preset,
                    profile_kind, tray_length_mm, tray_width_mm, tray_depth_mm,
                    leather_thickness_mm, leather_compression, forming_gap_mm)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, vid, design["config_hash"], utcnow(),
                 row["source"] if row else None, design["preset"], design["profile_kind"],
                 design["tray_length_mm"], design["tray_width_mm"], design["tray_depth_mm"],
                 design["leather_thickness_mm"], design["leather_compression"],
                 design["forming_gap_mm"]),
            )
            conn.execute(
                "INSERT INTO analytics_events (event_type, session_id, created_at, config_hash,"
                " output_format, output_part) VALUES (?,?,?,?,?,?)",
                ("artifact_downloaded", sid, utcnow(), design["config_hash"], fmt, part),
            )


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: tuple[float, dict] | None = None
CACHE_TTL_S = 45.0


def public_stats(*, ttl: float = CACHE_TTL_S) -> dict:
    """The three numbers the frontend may show. Cached briefly, never negative."""
    global _cache
    with _cache_lock:
        if _cache and time.monotonic() - _cache[0] < ttl:
            return dict(_cache[1])

    out = {"custom_molds_generated": 0, "unique_designs_downloaded": 0,
           "total_artifact_downloads": 0}
    with session() as conn:
        if conn is not None:
            out["custom_molds_generated"] = conn.execute(
                "SELECT COUNT(*) FROM qualified_usages").fetchone()[0]
            # Design-level and independent of sessions on purpose, so an
            # anonymous download of a genuinely new design still registers.
            # Restricted to the same formats the counter qualifies on: fetching
            # the preview GLB is the viewer doing its job, not a download.
            placeholders = ",".join("?" * len(QUALIFYING_FORMATS))
            out["unique_designs_downloaded"] = conn.execute(
                "SELECT COUNT(DISTINCT config_hash) FROM artifact_downloads"
                f" WHERE is_custom=1 AND config_hash IS NOT NULL AND format IN ({placeholders})",
                QUALIFYING_FORMATS).fetchone()[0]
            out["total_artifact_downloads"] = conn.execute(
                "SELECT COUNT(*) FROM artifact_downloads").fetchone()[0]

    with _cache_lock:
        _cache = (time.monotonic(), dict(out))
    return out


def invalidate_stats_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None
