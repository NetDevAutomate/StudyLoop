"""Request-boundary checks shared by the web server and its WebSocket routes.

Two questions are answered here:

- Which ``Host`` this server answers to (:func:`host_allowed`). A DNS-rebinding
  page reaches 127.0.0.1 under the attacker's own name, and the browser puts that
  name in ``Host``; refusing names the server does not own is what stops it
  (F-WEB-03 in the 2026-10-21 review).
- Which ``Origin`` may open a WebSocket (:func:`origin_allowed`).
"""

from __future__ import annotations

import ipaddress
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOCALHOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})

#: Starlette's ``TestClient`` talks to the app in-process; its scope's ``server``
#: is taken from the client's base URL, ``http://testserver`` by default. A real
#: listener's ``server`` is the socket it accepted on, so this name can only
#: appear there for the in-process client and is honoured for that case only.
IN_PROCESS_TEST_HOST = "testserver"


def _allowed_exact_origins() -> set[str]:
    extra = os.environ.get("STUDYLOOP_ALLOWED_ORIGINS", "").strip()
    if not extra:
        return set()
    return {origin.strip() for origin in extra.split(",") if origin.strip()}


def _allowed_origin_hostnames() -> set[str]:
    """Hostnames named by ``STUDYLOOP_ALLOWED_ORIGINS`` (e.g. a LAN ``.local`` name)."""
    names: set[str] = set()
    for origin in _allowed_exact_origins():
        hostname = urlparse(origin).hostname
        if hostname:
            names.add(hostname.lower())
    return names


def _host_name(host_header: str) -> str | None:
    """The hostname in a ``Host`` header value, lower-cased; None when malformed.

    Accepts ``name``, ``name:port``, ``[v6]`` and ``[v6]:port``.
    """
    value = host_header.strip().lower()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        name, rest = value[1:end], value[end + 1 :]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        return name or None
    name, sep, port = value.partition(":")
    if sep and not port.isdigit():
        return None
    return name or None


def _is_ip_literal(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def is_in_process_test_scope(scope: Mapping[str, Any]) -> bool:
    """Whether this ASGI scope came from Starlette's in-process ``TestClient``."""
    server = scope.get("server")
    return bool(server) and server[0] == IN_PROCESS_TEST_HOST


def host_allowed(host_header: str, *, in_process_test: bool = False) -> bool:
    """Return whether this server answers a request whose ``Host`` is *host_header*.

    Allowed: ``localhost``; any IP literal; hostnames named in
    ``STUDYLOOP_ALLOWED_ORIGINS``; and :data:`IN_PROCESS_TEST_HOST` when
    *in_process_test* says the request never crossed a socket.

    Any IP literal is safe to answer: DNS rebinding needs a NAME the attacker
    controls, and a browser only sends an IP literal in ``Host`` when it was
    pointed at that address itself. That is also what keeps ``--lan`` working
    from a tablet that browses to ``http://192.168.x.y:8567`` without the server
    having to discover every address it owns.
    """
    name = _host_name(host_header)
    if name is None:
        return False
    if name == "localhost" or _is_ip_literal(name):
        return True
    if name in _allowed_origin_hostnames():
        return True
    return in_process_test and name == IN_PROCESS_TEST_HOST


def origin_allowed(origin: str, *, host: str = "", in_process_test: bool = False) -> bool:
    """Return whether a WebSocket Origin is allowed for the request Host.

    Rules are intentionally narrow:
    - localhost / 127.0.0.1 / [::1] are allowed on any port for local development.
    - STUDYLOOP_ALLOWED_ORIGINS entries are exact matches.
    - Any other origin must be same-origin with this server: its netloc equals
      Host exactly AND that Host passes :func:`host_allowed`.

    The Host condition is the F-WEB-03 fix. Under DNS rebinding Origin and Host
    are both the attacker's name, so "Origin == Host" alone admitted it. The
    equality is still required on top of the Host allowlist: the allowlist
    answers any IP literal, so "origin is on the allowlist" alone would let a
    page served from some other address open the terminal socket.
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

    return (
        bool(host)
        and parsed.netloc.lower() == host.strip().lower()
        and host_allowed(host, in_process_test=in_process_test)
    )
