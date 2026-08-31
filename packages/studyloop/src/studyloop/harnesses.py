"""Authoritative coding-harness scope for the initial pre-release.

Every user-facing harness surface imports this module.  Keeping the contract
closed by default prevents experimental or out-of-scope adapters from being
accidentally advertised by filesystem discovery.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Harness:
    """Stable product metadata for one supported coding harness."""

    name: str
    label: str
    binary: str
    core: bool


CORE_HARNESSES = ("kiro", "codex", "claude")
PREVIEW_HARNESSES = ("opencode", "pi")
RELEASE_HARNESSES = (*CORE_HARNESSES, *PREVIEW_HARNESSES)

SESSION_SOURCE_BY_HARNESS: dict[str, str] = {
    "kiro": "kiro_cli",
    "codex": "codex",
    "claude": "claude_code",
    "opencode": "opencode",
    "pi": "pi",
}

HARNESSES: dict[str, Harness] = {
    "kiro": Harness("kiro", "Kiro CLI", "kiro-cli", True),
    "codex": Harness("codex", "Codex", "codex", True),
    "claude": Harness("claude", "Claude Code", "claude", True),
    "opencode": Harness("opencode", "OpenCode", "opencode", False),
    "pi": Harness("pi", "pi", "pi", False),
}


def get_harness(name: str) -> Harness:
    """Return supported harness metadata, failing closed for unknown names."""
    try:
        return HARNESSES[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported StudyLoop harness: {name}") from exc


__all__ = [
    "CORE_HARNESSES",
    "HARNESSES",
    "PREVIEW_HARNESSES",
    "RELEASE_HARNESSES",
    "SESSION_SOURCE_BY_HARNESS",
    "Harness",
    "get_harness",
]
