"""The schema, as an ordered list of migrations.

Each entry is one version. Append, never edit: an applied migration has already
run somewhere. `PRAGMA user_version` records how far a file has got.

No cross-table foreign key names a session from `analytics_events` or
`artifact_downloads` on purpose - a download can arrive carrying a session id
this process never saw (a link opened in a new tab, a restarted server), and
losing that download would be worse than an unreferenced id. `qualified_usages`
does declare one, because the public counter is the one place a dangling
reference would be a real defect, and the writer inserts a stub session first.
"""

from __future__ import annotations

MIGRATIONS: list[list[str]] = [
    # -- v1 ---------------------------------------------------------------
    [
        """
        CREATE TABLE sessions (
            session_id     TEXT PRIMARY KEY,
            visitor_id     TEXT NOT NULL,
            first_seen_at  TEXT NOT NULL,
            last_seen_at   TEXT NOT NULL,
            source         TEXT NOT NULL,
            medium         TEXT,
            campaign       TEXT,
            referrer_host  TEXT,
            landing_path   TEXT
        )
        """,
        "CREATE INDEX sessions_visitor ON sessions(visitor_id)",
        "CREATE INDEX sessions_source ON sessions(source)",
        "CREATE INDEX sessions_first_seen ON sessions(first_seen_at)",

        # What a cache key was built from. The artifact route knows only the
        # key, so without this row a download cannot be attributed to a design
        # without rebuilding geometry - which is exactly what must not happen.
        """
        CREATE TABLE designs (
            cache_key            TEXT PRIMARY KEY,
            config_hash          TEXT NOT NULL,
            is_custom            INTEGER NOT NULL,
            quality              TEXT,
            preset               TEXT,
            profile_kind         TEXT,
            tray_length_mm       REAL,
            tray_width_mm        REAL,
            tray_depth_mm        REAL,
            leather_thickness_mm REAL,
            leather_compression  REAL,
            forming_gap_mm       REAL,
            created_at           TEXT NOT NULL
        )
        """,
        "CREATE INDEX designs_config ON designs(config_hash)",

        """
        CREATE TABLE analytics_events (
            id                   INTEGER PRIMARY KEY,
            event_type           TEXT NOT NULL,
            session_id           TEXT,
            created_at           TEXT NOT NULL,
            config_hash          TEXT,
            job_id               TEXT,
            is_default           INTEGER,
            preset               TEXT,
            tray_length_mm       REAL,
            tray_width_mm        REAL,
            tray_depth_mm        REAL,
            leather_thickness_mm REAL,
            forming_gap_mm       REAL,
            output_format        TEXT,
            output_part          TEXT,
            duration_ms          INTEGER,
            error_code           TEXT,
            metadata             TEXT
        )
        """,
        "CREATE INDEX events_type_time ON analytics_events(event_type, created_at)",
        "CREATE INDEX events_session ON analytics_events(session_id, event_type)",

        # The public counter. The UNIQUE constraint is the deduplication - not a
        # Python check that could be raced by two downloads arriving together.
        """
        CREATE TABLE qualified_usages (
            id                   INTEGER PRIMARY KEY,
            session_id           TEXT NOT NULL REFERENCES sessions(session_id),
            visitor_id           TEXT,
            config_hash          TEXT NOT NULL,
            first_download_at    TEXT NOT NULL,
            source               TEXT,
            preset               TEXT,
            profile_kind         TEXT,
            tray_length_mm       REAL,
            tray_width_mm        REAL,
            tray_depth_mm        REAL,
            leather_thickness_mm REAL,
            leather_compression  REAL,
            forming_gap_mm       REAL,
            UNIQUE(session_id, config_hash)
        )
        """,
        "CREATE INDEX usages_source ON qualified_usages(source)",
        "CREATE INDEX usages_config ON qualified_usages(config_hash)",
        "CREATE INDEX usages_time ON qualified_usages(first_download_at)",

        """
        CREATE TABLE artifact_downloads (
            id             INTEGER PRIMARY KEY,
            session_id     TEXT,
            visitor_id     TEXT,
            config_hash    TEXT,
            cache_key      TEXT,
            artifact_name  TEXT NOT NULL,
            format         TEXT,
            part           TEXT,
            is_custom      INTEGER,
            downloaded_at  TEXT NOT NULL
        )
        """,
        "CREATE INDEX downloads_time ON artifact_downloads(downloaded_at)",
        "CREATE INDEX downloads_config ON artifact_downloads(config_hash, is_custom)",
    ],
]
