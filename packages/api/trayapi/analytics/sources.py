"""First-touch traffic attribution, reduced to a handful of names.

Only a normalized source, a medium, a campaign and a referrer *hostname* are
kept. A full referring URL can carry a search query or a private path, so the
host is where the useful signal stops and the liability starts.
"""

from __future__ import annotations

from urllib.parse import urlsplit

#: Everything that is not recognised becomes "other", so the column stays a
#: small closed set that GROUP BY can be trusted with.
KNOWN = ("makerworld", "google", "reddit", "github", "youtube", "facebook",
         "instagram", "bing", "duckduckgo", "printables", "thingiverse", "direct")

#: Hostname fragment -> source. Matched on the registrable-looking tail so
#: "www.google.co.uk" and "news.google.com" both land on "google".
_HOST_MAP = (
    ("makerworld", "makerworld"),
    ("bambulab", "makerworld"),
    ("google.", "google"),
    ("reddit", "reddit"),
    ("github", "github"),
    ("youtube", "youtube"),
    ("youtu.be", "youtube"),
    ("facebook", "facebook"),
    ("instagram", "instagram"),
    ("bing.", "bing"),
    ("duckduckgo", "duckduckgo"),
    ("printables", "printables"),
    ("thingiverse", "thingiverse"),
)

MAX_LEN = 64


def referrer_host(referrer: str | None) -> str | None:
    """The hostname of a referrer, and nothing else from it."""
    if not referrer:
        return None
    try:
        host = urlsplit(referrer).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.lower()[:MAX_LEN]


def normalize_source(utm_source: str | None, host: str | None) -> str:
    """First-touch source: an explicit utm_source wins over the referrer.

    A campaign link says what the campaign is; the referrer only says which page
    the browser came from, which may be a redirector on the way.
    """
    if utm_source:
        cleaned = utm_source.strip().lower()[:MAX_LEN]
        if cleaned in KNOWN:
            return cleaned
        for fragment, name in _HOST_MAP:
            if fragment.rstrip(".") in cleaned:
                return name
        return "other" if cleaned else "direct"
    if not host:
        return "direct"
    for fragment, name in _HOST_MAP:
        if fragment in host:
            return name
    return "other"


def clean(value: str | None, limit: int = MAX_LEN) -> str | None:
    """Trim a free-text attribution field to something a column can hold."""
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None
