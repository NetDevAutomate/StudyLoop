"""Read-only Second Brain launch-state API.

The single web surface for launch state (design: "Expose inert state through
a read-only route"): it serializes the pure resolver's target exactly, derives
Obsidian locality from the direct request peer only, and never mutates
configuration, launches anything server-side, redirects, or talks to a
provider over the network.
"""

from __future__ import annotations

import dataclasses
import ipaddress

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from studyloop.second_brain.launch import (
    PROVIDER_LABELS,
    DeviceLocality,
    LaunchTarget,
    resolve_launch_target,
)
from studyloop.settings import (
    SECOND_BRAIN_PROVIDERS,
    ConfigError,
    load_raw_config,
    normalize_provider,
    resolve_second_brain,
)

router = APIRouter()

INVALID_CONFIG_REASON = "Second Brain configuration is invalid."


def _device_locality(peer_host: str | None) -> DeviceLocality:
    if peer_host is None:
        return "unknown"
    try:
        peer = ipaddress.ip_address(peer_host)
    except ValueError:
        return "remote"
    return "local" if peer.is_loopback else "remote"


def _generic_invalid_target(raw: dict) -> LaunchTarget:
    """The redacted fallback for invalid configuration.

    A recognized raw provider keeps its safe label; anything else collapses to
    the generic ``none`` target. Nothing from the invalid configuration —
    especially not a rejected destination value — reaches the response.
    """
    section = raw.get("second_brain")
    raw_provider = section.get("provider", "none") if isinstance(section, dict) else "none"
    candidate = normalize_provider(raw_provider)
    provider = candidate if candidate in SECOND_BRAIN_PROVIDERS else "none"
    return LaunchTarget(
        provider=provider,
        label=PROVIDER_LABELS[provider],
        href=None,
        enabled=False,
        disabled_reason=INVALID_CONFIG_REASON,
        device_locality="unknown",
    )


@router.get("/second-brain/launch-target")
def get_launch_target(request: Request) -> JSONResponse:
    """Serialize the selected provider's launch state; never a config error's detail."""
    locality = _device_locality(request.client.host if request.client else None)
    raw: dict = {}
    try:
        raw = load_raw_config()
        target = resolve_launch_target(resolve_second_brain(raw), locality)
    except ConfigError:
        target = _generic_invalid_target(raw)
    return JSONResponse(
        content=dataclasses.asdict(target),
        headers={"Cache-Control": "no-store"},
    )
