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


#: pi joined the core tier on 2026-09-16 with all five of issue #21's evidence
#: items green on a real install (docs/architecture/plan-integration/receipts/
#: harness-evidence-2026-09-16.md). OpenCode and Grok Build stay preview until
#: their own receipts are green -- the reasons are named in that receipt.
CORE_HARNESSES = ("kiro", "codex", "claude", "pi")
PREVIEW_HARNESSES = ("opencode", "grok")
#: The release SET is unchanged by a tier move; only the core/preview split is.
RELEASE_HARNESSES = (*CORE_HARNESSES, *PREVIEW_HARNESSES)

SESSION_SOURCE_BY_HARNESS: dict[str, str] = {
    "kiro": "kiro_cli",
    "codex": "codex",
    "claude": "claude_code",
    "opencode": "opencode",
    "pi": "pi",
    "grok": "grok",
}

HARNESSES: dict[str, Harness] = {
    "kiro": Harness("kiro", "Kiro CLI", "kiro-cli", True),
    "codex": Harness("codex", "Codex", "codex", True),
    "claude": Harness("claude", "Claude Code", "claude", True),
    "opencode": Harness("opencode", "OpenCode", "opencode", False),
    "pi": Harness("pi", "pi", "pi", True),
    # "Grok Build" is the product's own name for the `grok` binary (its user
    # guide and TUI header both use it); "Grok"/"Grok Builder" are not.
    "grok": Harness("grok", "Grok Build", "grok", False),
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
