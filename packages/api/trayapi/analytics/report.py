"""Command-line analytics summary.

    TRAYMOLD_ANALYTICS_DB=/var/lib/traymold/analytics/analytics.sqlite3 \
        python -m trayapi.analytics.report

In the container it needs no arguments, the path already being in the
environment:

    docker compose exec api python -m trayapi.analytics.report

There is no authenticated admin surface in this application, so there is no
internal analytics endpoint either: a private summary reachable over HTTP with
no auth in front of it is a worse answer than a shell command on the host.

Every figure is a SQL aggregate. The events table is never read into Python.
"""

from __future__ import annotations

import argparse
import sys

from .db import connect, enabled
from .service import QUALIFYING_FORMATS

#: `format IN (?,?,?)` for the formats a real download uses, so a viewer
#: fetching the preview GLB is never mistaken for someone taking the mold away.
_TOOK_IT_AWAY = (
    "format IN (" + ",".join("'" + f + "'" for f in QUALIFYING_FORMATS) + ")"
)


def _scalar(conn, sql: str, args: tuple = ()) -> int:
    row = conn.execute(sql, args).fetchone()
    return int(row[0] or 0)


def _percentile(conn, table: str, column: str, fraction: float, where: str = "1=1") -> float | None:
    """Nearest-rank percentile in SQL: order, offset, take one."""
    total = _scalar(conn, f"SELECT COUNT({column}) FROM {table} WHERE {where} AND {column} IS NOT NULL")
    if total == 0:
        return None
    offset = max(0, min(total - 1, int(round(fraction * (total - 1)))))
    row = conn.execute(
        f"SELECT {column} FROM {table} WHERE {where} AND {column} IS NOT NULL"
        f" ORDER BY {column} LIMIT 1 OFFSET ?", (offset,)
    ).fetchone()
    return None if row is None else float(row[0])


def summary(conn) -> str:
    out: list[str] = []
    def line(label: str, value) -> None:
        out.append(f"{label:<34}{value:>10}")

    def breakdown(heading: str, sql: str) -> None:
        out.append(heading)
        rows = conn.execute(sql).fetchall()
        if not rows:
            out.append("  (none yet)")
        else:
            out.extend(f"  {r[0]:<20}{r[1]:>6}" for r in rows)
        out.append("")

    visitors = _scalar(conn, "SELECT COUNT(DISTINCT visitor_id) FROM sessions")
    sessions = _scalar(conn, "SELECT COUNT(*) FROM sessions")
    engaged = _scalar(conn, "SELECT COUNT(DISTINCT session_id) FROM analytics_events"
                            " WHERE event_type='config_engaged'")
    previews_ok = _scalar(conn, "SELECT COUNT(*) FROM analytics_events"
                                " WHERE event_type='preview_completed'")
    previews_bad = _scalar(conn, "SELECT COUNT(*) FROM analytics_events"
                                 " WHERE event_type='preview_failed'")
    exports_ok = _scalar(conn, "SELECT COUNT(*) FROM analytics_events"
                               " WHERE event_type='export_completed'")
    exports_bad = _scalar(conn, "SELECT COUNT(*) FROM analytics_events"
                                " WHERE event_type='export_failed'")
    exporting = _scalar(conn, "SELECT COUNT(DISTINCT session_id) FROM analytics_events"
                              " WHERE event_type='export_requested' AND session_id IS NOT NULL")
    downloading = _scalar(conn, "SELECT COUNT(DISTINCT session_id) FROM artifact_downloads"
                                " WHERE session_id IS NOT NULL AND " + _TOOK_IT_AWAY)
    previewing = _scalar(conn, "SELECT COUNT(DISTINCT session_id) FROM analytics_events"
                               " WHERE event_type='preview_completed' AND session_id IS NOT NULL")
    qualified = _scalar(conn, "SELECT COUNT(*) FROM qualified_usages")
    unique_designs = _scalar(conn, "SELECT COUNT(DISTINCT config_hash) FROM artifact_downloads"
                                   " WHERE is_custom=1 AND config_hash IS NOT NULL"
                                   " AND " + _TOOK_IT_AWAY)
    downloads = _scalar(conn, "SELECT COUNT(*) FROM artifact_downloads")
    returning = _scalar(conn, "SELECT COUNT(*) FROM (SELECT visitor_id FROM sessions"
                              " GROUP BY visitor_id HAVING COUNT(*) > 1)")
    makerworld_out = _scalar(conn, "SELECT COUNT(*) FROM analytics_events"
                                   " WHERE event_type='makerworld_clicked'")
    shares = _scalar(conn, "SELECT COUNT(*) FROM analytics_events"
                           " WHERE event_type='share_link_copied'")

    line("Visitors:", f"{visitors:,}")
    line("Sessions:", f"{sessions:,}")
    line("Engaged sessions:", f"{engaged:,}")
    line("Successful previews:", f"{previews_ok:,}")
    line("Exporting sessions:", f"{exporting:,}")
    line("Downloading sessions:", f"{downloading:,}")
    line("Qualified custom usages:", f"{qualified:,}")
    line("Unique custom designs downloaded:", f"{unique_designs:,}")
    line("Artifact downloads:", f"{downloads:,}")
    line("Returning visitors:", f"{returning:,}")
    out.append("")

    def rate(numerator: int, denominator: int) -> str:
        return "—" if denominator == 0 else f"{100.0 * numerator / denominator:.1f}%"

    line("Preview → download conversion:", rate(downloading, previewing))
    line("Engaged → download conversion:", rate(downloading, engaged))
    builds = previews_ok + previews_bad + exports_ok + exports_bad
    line("Build failure rate:", rate(previews_bad + exports_bad, builds))
    for label, kind in (("Median preview time:", "preview_completed"),
                        ("Median export time:", "export_completed")):
        ms = _percentile(conn, "analytics_events", "duration_ms", 0.5,
                         f"event_type='{kind}'")
        line(label, "—" if ms is None else f"{ms / 1000:.1f}s")
    out.append("")

    breakdown("Source (qualified usages):",
              "SELECT COALESCE(source,'unknown') AS s, COUNT(*) AS n"
              " FROM qualified_usages GROUP BY s ORDER BY n DESC")
    breakdown("Sessions by source:",
              "SELECT source, COUNT(*) AS n FROM sessions"
              " GROUP BY source ORDER BY n DESC")

    for label, column, unit in (("tray length", "tray_length_mm", "mm"),
                                ("tray width", "tray_width_mm", "mm"),
                                ("tray depth", "tray_depth_mm", "mm"),
                                ("leather thickness", "leather_thickness_mm", "mm"),
                                ("forming gap", "forming_gap_mm", "mm")):
        p25 = _percentile(conn, "qualified_usages", column, 0.25)
        p50 = _percentile(conn, "qualified_usages", column, 0.50)
        p75 = _percentile(conn, "qualified_usages", column, 0.75)
        if p50 is None:
            continue
        out.append(f"Most common {label}:")
        out.append(f"  median {p50:g} {unit}")
        out.append(f"  p25    {p25:g} {unit}")
        out.append(f"  p75    {p75:g} {unit}")
    out.append("")

    custom = _scalar(conn, "SELECT COUNT(*) FROM artifact_downloads WHERE is_custom=1")
    default = _scalar(conn, "SELECT COUNT(*) FROM artifact_downloads WHERE is_custom=0")
    line("Custom downloads:", f"{custom:,}")
    line("Default downloads:", f"{default:,}")
    line("Share links copied:", f"{shares:,}")
    line("MakerWorld clicks out:", f"{makerworld_out:,}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Usage summary from the analytics database.")
    parser.add_argument("--db", help="path to the analytics SQLite file "
                                     "(default: $TRAYMOLD_ANALYTICS_DB)")
    args = parser.parse_args(argv)
    if not args.db and not enabled():
        print("analytics is disabled: set TRAYMOLD_ANALYTICS_DB or pass --db", file=sys.stderr)
        return 2
    conn = connect(args.db) if args.db else connect()
    print(summary(conn))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
