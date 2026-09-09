"""Usage analytics.

Deliberately small, deliberately anonymous, and deliberately unable to break the
application it observes. Every function is a no-op when `TRAYMOLD_ANALYTICS_DB`
is unset, and swallows its own errors when it is.

    analytics.record_design(...)        what a cache key was built from
    analytics.record_build_event(...)   a preview or export reaching a state
    analytics.record_download(...)      an artifact actually served
    analytics.record_client_event(...)  one of four events the browser may send
    analytics.public_stats()            the three numbers the frontend may show

The public counter is driven exclusively by `record_download`, which the API
calls only after a file has been located on disk and is about to be streamed.
Nothing a browser sends can increment it.
"""

from .custom import dimensions, is_custom_configuration, preset_name
from .db import connect, enabled, migrate, reset_thread_state, utcnow
from .service import (
    CLIENT_EVENTS,
    SERVER_EVENTS,
    ensure_session,
    invalidate_stats_cache,
    parse_artifact,
    public_stats,
    record_build_event,
    record_client_event,
    record_design,
    record_download,
)
from .sources import normalize_source, referrer_host

__all__ = [
    "CLIENT_EVENTS", "SERVER_EVENTS",
    "connect", "enabled", "migrate", "reset_thread_state", "utcnow",
    "dimensions", "is_custom_configuration", "preset_name",
    "ensure_session", "invalidate_stats_cache", "parse_artifact", "public_stats",
    "record_build_event", "record_client_event", "record_design", "record_download",
    "normalize_source", "referrer_host",
]
