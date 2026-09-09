"""Usage analytics: the public counter, and everything it must refuse to count.

The counter is a number shown to the public, so most of these tests are about
what does *not* increment it. Every test runs against a temporary SQLite file;
nothing here touches a real database.
"""

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from trayapi import analytics
from trayapi.analytics import custom, db, service, sources


@pytest.fixture
def adb(tmp_path, monkeypatch):
    """A fresh analytics database, wired in for the duration of one test."""
    path = tmp_path / "analytics.sqlite3"
    monkeypatch.setenv("TRAYMOLD_ANALYTICS_DB", str(path))
    db.reset_thread_state()
    service.invalidate_stats_cache()
    yield path
    db.reset_thread_state()
    service.invalidate_stats_cache()


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.setenv("TRAYMOLD_ANALYTICS_DB", "")
    db.reset_thread_state()
    service.invalidate_stats_cache()
    yield
    db.reset_thread_state()


def design(adb, key, params, *, config_hash=None):
    from traymold.api import params_hash

    analytics.record_design(key, config_hash or params_hash(params), params, "export")


def custom_params(**overrides):
    """The reference design with one geometry value moved, so it is custom."""
    from traymold.presets import REF_4X7_STEP

    tray = REF_4X7_STEP.tray.model_copy(update={"depth": overrides.get("depth", 31.0)})
    return REF_4X7_STEP.model_copy(update={"tray": tray})


# --------------------------------------------------------------------------
# 1-2. schema
# --------------------------------------------------------------------------
def test_schema_initialises_on_an_empty_database(adb):
    conn = db.connect(adb)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sessions", "designs", "analytics_events",
            "qualified_usages", "artifact_downloads"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_migration_is_idempotent(adb):
    conn = db.connect(adb)
    before = conn.execute("PRAGMA user_version").fetchone()[0]
    db.migrate(conn)
    db.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == before
    # A second migration on a table that already exists would raise, not pass.
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_wal_and_foreign_keys_are_on(adb):
    conn = db.connect(adb)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_everything_is_a_no_op_when_analytics_is_disabled(disabled):
    analytics.record_design("k", "h", custom_params(), "export")
    analytics.record_download("k", "male.stl", session_id="s", visitor_id="v")
    analytics.record_client_event("app_opened", "s", "v")
    assert analytics.public_stats() == {
        "custom_molds_generated": 0,
        "unique_designs_downloaded": 0,
        "total_artifact_downloads": 0,
    }


# --------------------------------------------------------------------------
# 3. analytics must never break the application
# --------------------------------------------------------------------------
def test_a_broken_database_does_not_break_recording(adb, monkeypatch):
    """A corrupt file is a logged warning, not an exception reaching a route."""
    Path(adb).write_bytes(b"this is not a database")
    db.reset_thread_state()
    analytics.record_design("k", "h", custom_params(), "export")
    analytics.record_download("k", "male.stl", session_id="s")
    assert analytics.public_stats()["custom_molds_generated"] == 0


def test_analytics_failure_does_not_break_artifact_download(client, cache, monkeypatch):
    """A download survives analytics throwing, not merely analytics behaving.

    The stub raises unconditionally, so this passes only because the route
    wraps the call - not because the analytics package happens to catch its own
    errors today.
    """
    def explode(*args, **kwargs):
        raise RuntimeError("analytics is on fire")

    monkeypatch.setattr("trayapi.main.analytics.record_download", explode)
    key = "abc123"
    directory = cache.dir_for(key)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "male.stl").write_bytes(b"solid\n")

    response = client.get(f"/api/artifacts/{key}/male.stl")
    assert response.status_code == 200
    assert response.content == b"solid\n"


def test_a_failing_stats_query_serves_zeros_rather_than_an_error(client, monkeypatch):
    def explode():
        raise RuntimeError("the database went away")

    monkeypatch.setattr("trayapi.main.analytics.public_stats", explode)
    response = client.get("/api/stats")
    assert response.status_code == 200
    assert response.json()["custom_molds_generated"] == 0


def test_a_failing_recorder_does_not_break_a_build_request(client, ref_params, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("analytics is on fire")

    monkeypatch.setattr("trayapi.main.analytics.record_design", explode)
    monkeypatch.setattr("trayapi.main.analytics.record_build_event", explode)
    response = client.post("/api/validate", json={"params": ref_params})
    assert response.status_code == 200


def test_the_real_recorder_never_raises_however_it_is_called(adb):
    analytics.record_download("no-such-key", "male.stl", session_id=None)
    analytics.record_download("no-such-key", "weird-name-no-extension")
    analytics.record_client_event("not_a_real_event", "s", "v")
    analytics.record_build_event("not_a_real_event", session_id="s")


# --------------------------------------------------------------------------
# 4-7. the counting rules
# --------------------------------------------------------------------------
def test_one_downloaded_artifact_is_one_qualified_usage(adb):
    params = custom_params()
    design(adb, "k1", params)
    analytics.record_download("k1", "male.stl", session_id="s1", visitor_id="v1")
    assert analytics.public_stats()["custom_molds_generated"] == 1


def test_five_files_from_one_session_and_config_are_still_one_usage(adb):
    params = custom_params()
    design(adb, "k1", params)
    for name in ("male.stl", "female.stl", "male.step", "female.step", "bundle.zip"):
        analytics.record_download("k1", name, session_id="s1", visitor_id="v1")
    stats = analytics.public_stats()
    assert stats["custom_molds_generated"] == 1
    # The individual downloads are still all recorded; only the counter dedupes.
    assert stats["total_artifact_downloads"] == 5


def test_the_same_session_downloading_a_different_design_counts_again(adb):
    design(adb, "k1", custom_params(depth=31.0))
    design(adb, "k2", custom_params(depth=32.0))
    analytics.record_download("k1", "male.stl", session_id="s1")
    analytics.record_download("k2", "male.stl", session_id="s1")
    assert analytics.public_stats()["custom_molds_generated"] == 2


def test_a_different_session_downloading_the_same_design_counts_again(adb):
    design(adb, "k1", custom_params())
    analytics.record_download("k1", "male.stl", session_id="s1")
    analytics.record_download("k1", "male.stl", session_id="s2")
    stats = analytics.public_stats()
    assert stats["custom_molds_generated"] == 2
    # ...but it is one design, however many people take it away.
    assert stats["unique_designs_downloaded"] == 1


def test_deduplication_is_enforced_by_the_database_not_by_python(adb):
    """The UNIQUE constraint is the guarantee; Python is only the caller."""
    design(adb, "k1", custom_params())
    analytics.record_download("k1", "male.stl", session_id="s1")
    conn = db.connect(adb)
    row = conn.execute("SELECT config_hash FROM qualified_usages").fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO qualified_usages (session_id, config_hash, first_download_at)"
            " VALUES (?,?,?)", ("s1", row["config_hash"], "2026-01-01T00:00:00+00:00"))


# --------------------------------------------------------------------------
# 8-10. what does not count
# --------------------------------------------------------------------------
def test_the_default_configuration_is_not_a_custom_mold(adb):
    from traymold.params import Params

    design(adb, "k1", Params())
    analytics.record_download("k1", "male.stl", session_id="s1")
    stats = analytics.public_stats()
    assert stats["custom_molds_generated"] == 0
    assert stats["total_artifact_downloads"] == 1  # still telemetry, just not a usage


def test_an_untouched_preset_is_not_a_custom_mold(adb):
    from traymold.presets import REF_4X7_STEP

    design(adb, "k1", REF_4X7_STEP)
    analytics.record_download("k1", "male.stl", session_id="s1")
    assert analytics.public_stats()["custom_molds_generated"] == 0


def test_a_preview_does_not_count(adb):
    """A GLB is what the viewer renders, not something anyone downloaded."""
    design(adb, "k1", custom_params())
    analytics.record_download("k1", "preview.glb", session_id="s1")
    stats = analytics.public_stats()
    assert stats["custom_molds_generated"] == 0
    assert stats["unique_designs_downloaded"] == 0
    assert stats["total_artifact_downloads"] == 1


def test_a_preview_of_a_design_already_exported_does_not_double_count_it(adb):
    """The preview and the export of one design are two cache keys.

    They hash to different keys because the quality differs, so a viewer that
    fetches the GLB after an export must not look like a second design. Only the
    raw download tally moves.
    """
    params = custom_params()
    design(adb, "export-key", params)
    design(adb, "preview-key", params, config_hash="preview-hash")
    analytics.record_download("export-key", "male.stl", session_id="s1")
    analytics.record_download("preview-key", "preview.glb", session_id="s1")
    stats = analytics.public_stats()
    assert stats["custom_molds_generated"] == 1
    assert stats["unique_designs_downloaded"] == 1
    assert stats["total_artifact_downloads"] == 2


def test_a_failed_export_leaves_nothing_to_download_and_counts_nothing(adb):
    analytics.record_build_event("export_failed", session_id="s1", config_hash="h",
                                 error_code="geometry_build_error")
    assert analytics.public_stats()["custom_molds_generated"] == 0
    conn = db.connect(adb)
    assert conn.execute("SELECT COUNT(*) FROM analytics_events"
                        " WHERE event_type='export_failed'").fetchone()[0] == 1


def test_a_download_of_an_unknown_key_records_nothing_qualifying(adb):
    analytics.record_download("never-built", "male.stl", session_id="s1")
    stats = analytics.public_stats()
    assert stats["custom_molds_generated"] == 0
    assert stats["total_artifact_downloads"] == 1


def test_an_anonymous_download_counts_as_a_design_but_not_a_usage(adb):
    design(adb, "k1", custom_params())
    analytics.record_download("k1", "male.stl", session_id=None)
    stats = analytics.public_stats()
    assert stats["custom_molds_generated"] == 0
    assert stats["unique_designs_downloaded"] == 1


# --------------------------------------------------------------------------
# 11-12. the API surface
# --------------------------------------------------------------------------
def test_a_client_cannot_invent_a_download(adb, client):
    """The one thing the endpoint must never accept."""
    design(adb, "k1", custom_params())
    for payload in (
        {"event": "artifact_downloaded", "session_id": "s1"},
        {"event": "qualified_usage", "session_id": "s1"},
        {"event": "app_opened", "session_id": "s1", "config_hash": "h", "downloaded": True},
    ):
        client.post("/api/analytics/event", json=payload)
    assert analytics.public_stats()["custom_molds_generated"] == 0


def test_an_unknown_event_name_is_rejected_by_validation(client):
    response = client.post("/api/analytics/event", json={"event": "made_up", "session_id": "s"})
    assert response.status_code == 422


def test_the_four_allowed_events_are_accepted(adb, client):
    for name in analytics.CLIENT_EVENTS:
        response = client.post("/api/analytics/event",
                               json={"event": name, "session_id": "s1", "visitor_id": "v1"})
        assert response.status_code == 204, name
    conn = db.connect(adb)
    assert conn.execute("SELECT COUNT(*) FROM analytics_events").fetchone()[0] == 4


def test_stats_endpoint_returns_the_aggregate(adb, client):
    design(adb, "k1", custom_params(depth=31.0))
    design(adb, "k2", custom_params(depth=33.0))
    analytics.record_download("k1", "male.stl", session_id="s1")
    analytics.record_download("k1", "female.stl", session_id="s1")
    analytics.record_download("k2", "male.step", session_id="s2")
    service.invalidate_stats_cache()

    body = client.get("/api/stats").json()
    assert body == {
        "custom_molds_generated": 2,
        "unique_designs_downloaded": 2,
        "total_artifact_downloads": 3,
    }


def test_stats_is_zero_and_serves_fine_with_analytics_disabled(disabled, client):
    assert client.get("/api/stats").json()["custom_molds_generated"] == 0


def test_an_oversized_event_field_is_rejected(client):
    response = client.post("/api/analytics/event",
                           json={"event": "app_opened", "session_id": "x" * 500})
    assert response.status_code == 422


# --------------------------------------------------------------------------
# 13-15. attribution
# --------------------------------------------------------------------------
@pytest.mark.parametrize("host,expected", [
    ("makerworld.com", "makerworld"),
    ("www.makerworld.com", "makerworld"),
    ("www.google.co.uk", "google"),
    ("news.google.com", "google"),
    ("old.reddit.com", "reddit"),
    ("github.com", "github"),
    ("some-blog.example", "other"),
    (None, "direct"),
])
def test_referrer_hosts_normalise_to_a_small_closed_set(host, expected):
    assert sources.normalize_source(None, host) == expected


def test_an_explicit_utm_source_beats_the_referrer(adb):
    # Arriving on a MakerWorld campaign link via a Google redirect is a
    # MakerWorld visit; the campaign says so and the referrer only says who
    # bounced the browser along.
    assert sources.normalize_source("makerworld", "www.google.com") == "makerworld"
    conn = db.connect(adb)
    service.ensure_session(conn, "s1", "v1", source="makerworld",
                           referrer="https://www.google.com/search?q=leather+tray")
    row = conn.execute("SELECT source, referrer_host FROM sessions").fetchone()
    assert row["source"] == "makerworld"
    assert row["referrer_host"] == "www.google.com"


def test_only_the_referrer_hostname_is_stored(adb):
    conn = db.connect(adb)
    service.ensure_session(
        conn, "s1", "v1",
        referrer="https://www.google.com/search?q=private+search+terms&hl=en#frag")
    row = conn.execute("SELECT referrer_host FROM sessions").fetchone()
    assert row["referrer_host"] == "www.google.com"
    # The path, the query and the fragment must not be anywhere in the row.
    stored = json.dumps(dict(row))
    for leak in ("private", "search?q", "hl=en", "frag", "/search"):
        assert leak not in stored


def test_first_touch_attribution_is_not_overwritten(adb):
    conn = db.connect(adb)
    service.ensure_session(conn, "s1", "v1", source="makerworld", campaign="leather_tray")
    service.ensure_session(conn, "s1", "v1", source="google")  # a later internal event
    row = conn.execute("SELECT source, campaign FROM sessions").fetchone()
    assert row["source"] == "makerworld"
    assert row["campaign"] == "leather_tray"


def test_the_session_source_is_carried_onto_the_usage(adb):
    conn = db.connect(adb)
    service.ensure_session(conn, "s1", "v1", source="makerworld", medium="model",
                           campaign="leather_tray")
    design(adb, "k1", custom_params())
    analytics.record_download("k1", "male.stl", session_id="s1", visitor_id="v1")
    row = db.connect(adb).execute("SELECT source FROM qualified_usages").fetchone()
    assert row["source"] == "makerworld"


# --------------------------------------------------------------------------
# 16. identity
# --------------------------------------------------------------------------
def test_no_identifying_column_exists_anywhere_in_the_schema(adb):
    """A schema-level guarantee, so a future column has to argue with a test."""
    conn = db.connect(adb)
    forbidden = ("ip", "address", "email", "name", "user_agent", "useragent",
                 "fingerprint", "latitude", "longitude", "geo")
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        for row in conn.execute(f"PRAGMA table_info({table})"):
            column = row[1].lower()
            # "artifact_name" and "campaign" are names of things, not of people.
            if column in ("artifact_name", "campaign", "profile_kind"):
                continue
            assert not any(bad in column for bad in forbidden), f"{table}.{column}"


def test_ids_are_stored_verbatim_and_never_derived(adb):
    """The server records the opaque id it is given; it computes nothing."""
    conn = db.connect(adb)
    service.ensure_session(conn, "session-abc", "visitor-xyz")
    row = conn.execute("SELECT session_id, visitor_id FROM sessions").fetchone()
    assert row["session_id"] == "session-abc"
    assert row["visitor_id"] == "visitor-xyz"


def test_oversized_ids_are_bounded_rather_than_trusted(adb):
    analytics.record_client_event("app_opened", "s" * 500, "v" * 500)
    row = db.connect(adb).execute("SELECT session_id, visitor_id FROM sessions").fetchone()
    assert len(row["session_id"]) == 64
    assert len(row["visitor_id"]) == 64


# --------------------------------------------------------------------------
# is_custom_configuration
# --------------------------------------------------------------------------
def test_is_custom_configuration(ref_params):
    from traymold.params import Params
    from traymold.presets import REF_4X7_STEP

    assert not custom.is_custom_configuration(Params())
    assert not custom.is_custom_configuration(REF_4X7_STEP)
    assert custom.is_custom_configuration(custom_params())


@pytest.mark.parametrize("field,value", [("name", "my tray")])
def test_naming_a_design_does_not_make_it_custom(field, value):
    from traymold.presets import REF_4X7_STEP

    assert not custom.is_custom_configuration(REF_4X7_STEP.model_copy(update={field: value}))


def test_preview_quality_does_not_make_a_design_custom():
    from traymold.presets import REF_4X7_STEP

    assert not custom.is_custom_configuration(REF_4X7_STEP.with_quality("preview"))


def test_which_halves_were_exported_does_not_make_a_design_custom():
    from traymold.api import apply_options
    from traymold.presets import REF_4X7_STEP

    male_only = apply_options(REF_4X7_STEP, None, {"male": True, "female": False})
    assert not custom.is_custom_configuration(male_only)


def test_a_geometry_change_does_make_a_design_custom():
    from traymold.presets import REF_4X7_STEP

    for update in ({"depth": 30.0}, {"draft_angle": 1.0}):
        changed = REF_4X7_STEP.model_copy(
            update={"tray": REF_4X7_STEP.tray.model_copy(update=update)})
        assert custom.is_custom_configuration(changed), update


def test_dimensions_are_extracted_for_product_research():
    params = custom_params()
    dims = custom.dimensions(params)
    assert dims["tray_length_mm"] == 175.0
    assert dims["tray_depth_mm"] == 31.0
    assert dims["leather_thickness_mm"] == 3.0
    assert dims["forming_gap_mm"] == pytest.approx(3.0)


def test_recorded_usages_carry_the_dimensions(adb):
    design(adb, "k1", custom_params(depth=42.0))
    analytics.record_download("k1", "male.stl", session_id="s1")
    row = db.connect(adb).execute(
        "SELECT tray_length_mm, tray_depth_mm, leather_thickness_mm FROM qualified_usages"
    ).fetchone()
    assert row["tray_depth_mm"] == 42.0
    assert row["tray_length_mm"] == 175.0
    assert row["leather_thickness_mm"] == 3.0


# --------------------------------------------------------------------------
# the CLI
# --------------------------------------------------------------------------
def test_the_report_runs_on_a_populated_database(adb, capsys):
    from trayapi.analytics import report

    conn = db.connect(adb)
    service.ensure_session(conn, "s1", "v1", source="makerworld")
    design(adb, "k1", custom_params())
    analytics.record_client_event("config_engaged", "s1", "v1")
    analytics.record_build_event("preview_completed", session_id="s1", duration_ms=2400)
    analytics.record_download("k1", "male.stl", session_id="s1")

    assert report.main(["--db", str(adb)]) == 0
    out = capsys.readouterr().out
    assert "Qualified custom usages:" in out
    assert "makerworld" in out


def test_the_report_refuses_cleanly_when_analytics_is_disabled(disabled, capsys):
    from trayapi.analytics import report

    assert report.main([]) == 2
    assert "disabled" in capsys.readouterr().err


def test_a_cache_hit_still_records_a_completed_build(adb, live_client, ref_params):
    """A cache hit never reaches on_finish, so the route records it instead.

    The artifact cache is content-addressed and long-lived, so this is the
    common path: without it the funnel would count every request and lose most
    of the successes.
    """
    from tests.conftest import poll

    body = {"params": ref_params, "session_id": "s-cache"}
    first = live_client.post("/api/preview", json=body)
    poll(live_client, first.json()["id"])

    second = live_client.post("/api/preview", json=body)
    assert second.status_code == 200, "expected a cache hit"
    assert second.json()["cached"] is True

    conn = db.connect(adb)
    completed = conn.execute(
        "SELECT duration_ms FROM analytics_events"
        " WHERE event_type='preview_completed' AND session_id='s-cache'"
    ).fetchall()
    assert len(completed) == 2, "the build and the cache hit both count as a preview"
    # The cache hit contributes no duration, so it cannot drag the median down.
    assert sorted(row[0] is None for row in completed) == [False, True]
