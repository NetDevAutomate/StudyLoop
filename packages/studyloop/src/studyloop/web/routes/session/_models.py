"""Pydantic models and constants for session start."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StartSessionRequest(BaseModel):
    """Request body for POST /api/session/start."""

    topic: str
    energy: int = Field(default=5, ge=1, le=10)
    agent: str | None = None
    transport: Literal["pty", "acp"] | None = Field(
        default=None,
        description=(
            "Session transport: 'pty' (default) or 'acp' (Agent Client "
            "Protocol, available for Kiro and Grok Build). Any other value — "
            "including the retired 'ttyd' — is rejected with 422, not silently "
            "downgraded. STUDYLOOP_TRANSPORT=pty is the only accepted env-var "
            "override; 'acp' is body-only to keep the kill-switch semantics "
            "focused on the safe path."
        ),
    )
    purpose: Literal["focus", "planning"] = Field(
        default="focus",
        description=(
            "What the session is for: 'focus' (default) is today's study "
            "session; 'planning' launches the study-plan architect with a "
            "planning brief as its own persona section. For 'planning' a blank "
            "topic resolves to the fixed label 'Study plan'. Only the purpose is "
            "persisted on the session state; no plan is created and no plan id "
            "is stored (design §5, D-10/D-11). Any other value is rejected with "
            "422."
        ),
    )


_AGENT_INSTALL_HINTS: dict[str, str] = {
    "claude": "Install the Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code",
    "codex": "Install codex: npm i -g @openai/codex (or see https://github.com/openai/codex).",
    "kiro": "Install Kiro CLI: https://kiro.dev/docs/cli",
    "opencode": "Install OpenCode: https://opencode.ai/docs/install",
    "pi": "Install pi: npm install -g @mariozechner/pi-coding-agent",
    "grok": "Install Grok Build: curl -fsSL https://x.ai/cli/install.sh | bash",
}


class SessionOption(BaseModel):
    """Selectable study target for the web start picker."""

    label: str
    value: str
    kind: str
    path: str | None = None
    parent: str | None = None
