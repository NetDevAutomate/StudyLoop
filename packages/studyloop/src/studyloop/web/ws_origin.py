"""WebSocket Origin checks shared by LAN-exposed routes."""

from __future__ import annotations

import os
from urllib.parse import urlparse

_LOCALHOST_NAMES = frozenset({"localhost", "127.0.0.1"})


def _allowed_exact_origins() -> set[str]:
    extra = os.environ.get("STUDYLOOP_ALLOWED_ORIGINS", "").strip()
    if not extra:
        return set()
    return {origin.strip() for origin in extra.split(",") if origin.strip()}


def origin_allowed(origin: str, *, host: str = "") -> bool:
    """Return whether a WebSocket Origin is allowed for the request Host.

    Rules are intentionally narrow:
    - localhost / 127.0.0.1 are allowed on any port for local development.
    - STUDYLOOP_ALLOWED_ORIGINS entries are exact matches.
    - LAN origins are allowed only when the origin netloc matches Host exactly.
    """
    origin = origin.strip()
    if not origin:
        return False

    if origin in _allowed_exact_origins():
        return True

    parsed = urlparse(origin)
    if not parsed.scheme or not parsed.netloc:
        return False

    hostname = (parsed.hostname or "").lower()
    if parsed.scheme in {"http", "https"} and hostname in _LOCALHOST_NAMES:
        return True

    return bool(host) and parsed.netloc.lower() == host.strip().lower()
