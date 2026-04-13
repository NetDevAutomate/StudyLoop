"""Codex adapter — persona via AGENTS.md in session CWD.

Codex CLI auto-loads AGENTS.md from the current working directory.
The setup function writes the canonical persona as plain markdown in
the session directory; launch just invokes the codex binary there.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from studyctl.adapters._protocol import AgentAdapter

if TYPE_CHECKING:
    from pathlib import Path


def _codex_setup(canonical_content: str, session_dir: Path) -> Path:
    """Write AGENTS.md to the session dir for Codex auto-discovery."""
    persona_path = session_dir / "AGENTS.md"
    persona_path.write_text(canonical_content)
    return persona_path


def _codex_launch(_persona_path: Path, resume: bool) -> str:
    """Build Codex launch command. Codex reads AGENTS.md from cwd."""
    binary = shutil.which("codex") or "codex"
    if resume:
        return f"{binary} --resume"
    return binary


ADAPTER = AgentAdapter(
    name="codex",
    binary="codex",
    setup=_codex_setup,
    launch_cmd=_codex_launch,
)
