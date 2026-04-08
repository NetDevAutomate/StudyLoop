"""Gemini adapter — persona via GEMINI.md in session CWD.

Gemini CLI auto-loads GEMINI.md from the current working directory
(3-tier hierarchy: global, workspace, JIT). MCP config goes in
.gemini/settings.json in the session directory.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from studyctl.adapters._protocol import AgentAdapter
from studyctl.adapters._strategies import write_mcp_config

if TYPE_CHECKING:
    from pathlib import Path


def _gemini_setup(canonical_content: str, session_dir: Path) -> Path:
    """Write GEMINI.md to session dir (auto-loaded by Gemini CLI from cwd)."""
    persona_path = session_dir / "GEMINI.md"
    persona_path.write_text(canonical_content)
    return persona_path


def _gemini_launch(_persona_path: Path, resume: bool) -> str:
    """Build Gemini launch command. Gemini picks up GEMINI.md from cwd."""
    binary = shutil.which("gemini") or "gemini"
    if resume:
        return f"{binary} -r"
    return binary


def _gemini_mcp(session_dir: Path) -> None:
    """Write .gemini/settings.json with studyctl-mcp server config."""
    write_mcp_config(session_dir, fmt="gemini")


ADAPTER = AgentAdapter(
    name="gemini",
    binary="gemini",
    setup=_gemini_setup,
    launch_cmd=_gemini_launch,
    mcp_setup=_gemini_mcp,
)
