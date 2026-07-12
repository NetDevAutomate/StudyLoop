"""Pydantic models and constants for session start."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StartSessionRequest(BaseModel):
    """Request body for POST /api/session/start."""

    topic: str
    energy: int = Field(default=5, ge=1, le=10)
    agent: str | None = None
    transport: str | None = Field(
        default=None,
        description=(
            "Session transport: 'pty' (default), 'ttyd' (legacy fallback), or "
            "'acp' (Agent Client Protocol, Kiro, Gemini, and Grok — §2.2). "
            "STUDYLOOP_TRANSPORT env var forces 'pty' or 'ttyd' regardless of "
            "this field; 'acp' is body-only to keep the kill-switch semantics "
            "focused on the safe paths."
        ),
    )


_AGENT_INSTALL_HINTS: dict[str, str] = {
    "claude": "Install the Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code",
    "codex": "Install codex: npm i -g @openai/codex (or see https://github.com/openai/codex).",
    "gemini": ("Install the Gemini CLI: https://github.com/google-gemini/gemini-cli#installation"),
    "grok": "Install Grok Build: npm i -g @xai-official/grok (or run https://x.ai/cli/install.sh).",
    "kiro": "Install Kiro CLI: https://kiro.dev/docs/cli",
    "opencode": "Install OpenCode: https://opencode.ai/docs/install",
}


class SessionOption(BaseModel):
    """Selectable study target for the web start picker."""

    label: str
    value: str
    kind: str
    path: str | None = None
    parent: str | None = None
