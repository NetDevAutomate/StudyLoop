"""Business helpers for web session-start routes."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

TransportName = Literal["pty", "acp", "ttyd"]

# Agents that speak the Agent Client Protocol. Single source of truth shared by
# the session-start ACP guard and the options endpoint (_options.py). Claude
# Code and Codex are PTY-only; only these three have an ACP transport.
ACP_CAPABLE_AGENTS: frozenset[str] = frozenset({"kiro", "gemini", "grok"})


def slug_session_dir(topic: str) -> str:
    """Return a filesystem-safe slug for a user-supplied topic.

    The topic is attacker-controlled (POST body), and the slug becomes a path
    segment under ``SESSION_DIR/sessions``. Collapse everything outside
    ``[a-z0-9]`` to ``-`` so path-traversal vectors (``/``, ``\\``, ``..``)
    cannot escape the sessions directory. Falls back to ``"session"`` when the
    topic slugs to nothing (e.g. all punctuation).
    """
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug[:20] or "session"


def session_dir_name(topic: str, study_id: str, *, prefix: str = "pty") -> str:
    """Return the stable session directory name used by web-started sessions.

    ``topic`` is user-controlled; :func:`slug_session_dir` guarantees the
    returned name is a single safe path segment (no ``/``, ``\\`` or ``..``).
    """
    return f"{prefix}-{slug_session_dir(topic)}-{study_id[:8]}"


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
        # PTY/ACP starts own no tmux session. write_session_state is a
        # read-merge-write, so a PTY session started after a legacy ttyd one
        # would otherwise inherit that session's dead tmux_session key and be
        # misclassified as a tmux zombie. Clear it explicitly at the source.
        "tmux_session": None,
    }
    if persona_file is not None:
        payload["persona_file"] = persona_file
    return payload
