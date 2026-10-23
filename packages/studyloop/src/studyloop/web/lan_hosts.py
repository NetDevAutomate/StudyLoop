"""Which addresses another device on the LAN can reach this machine at.

One answer, shared by every surface that prints a dashboard address: the
``studyloop web`` command (``cli/_web.py``) and the session launcher
(``session/start.py``), which until lane S of the 2026-10 review each had their
own idea of "the LAN address" -- the launcher asked ``gethostbyname`` alone,
which on a host whose name resolves to ``127.0.1.1`` prints an address no other
device can use. Click-free on purpose: the launcher imports it, and the launcher
is framework-agnostic by contract (read its module docstring).

The result feeds :func:`studyloop.web.runtime_feedback.build_web_access_info`,
which drops the hosts a client cannot use (wildcard, loopback).
"""

from __future__ import annotations

import contextlib
import socket


def candidate_lan_hosts() -> tuple[str, ...]:
    """Best-effort LAN address discovery, most-likely-reachable first.

    Two probes, each suppressed on failure so a machine with no route still
    gets an answer from the other:

    1. the source address of a UDP socket "connected" to a public address --
       no packet is sent; the kernel just picks the interface it would route
       through, which is the address a device on the same LAN reaches;
    2. the address the hostname resolves to, which is what older callers used
       and is still right on many machines.

    Returns an empty tuple when neither probe answers; callers print their own
    placeholder for that case.
    """
    hosts: list[str] = []
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("8.8.8.8", 80))
        hosts.append(sock.getsockname()[0])
    with contextlib.suppress(OSError):
        hosts.append(socket.gethostbyname(socket.gethostname()))
    return tuple(hosts)
