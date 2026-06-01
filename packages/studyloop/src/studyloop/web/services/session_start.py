"""Business helpers for web session-start routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

TransportName = Literal["pty", "acp", "ttyd"]


def session_dir_name(topic: str, study_id: str, *, prefix: str = "pty") -> str:
    """Return the stable session directory name used by web-started sessions."""
    slug = topic.lower().replace(" ", "-")[:20]
    return f"{prefix}-{slug}-{study_id[:8]}"


def build_session_state_payload(
    *,
    study_id: str,
    topic: str,
    energy: int,
    energy_label: str,
    agent: str,
    session_dir: str,
    persona_hash: str,
    transport: TransportName,
    now: datetime,
    persona_file: str | None = None,
) -> dict[str, object]:
    """Build the common state payload for PTY and ACP web session starts."""
    timestamp = now.isoformat()
    payload: dict[str, object] = {
        "study_session_id": study_id,
        "topic": topic,
        "energy": energy,
        "energy_label": energy_label,
        "mode": "focus",
        "timer_mode": "energy",
        "started_at": timestamp,
        "start_time": timestamp,
        "paused_at": None,
        "total_paused_seconds": 0,
        "session_dir": session_dir,
        "agent": agent,
        "persona_hash": persona_hash,
        "transport": transport,
    }
    if persona_file is not None:
        payload["persona_file"] = persona_file
    return payload
