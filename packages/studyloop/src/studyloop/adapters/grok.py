"""Grok Build adapter — persona via AGENTS.md in session CWD.

Grok Build reads the AGENTS.md instruction-file family from the current
directory up to the repository root. The setup function writes the
canonical persona into the StudyLoop session directory; launch invokes
the interactive Grok TUI from that directory.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from studyloop.adapters._protocol import AgentAdapter

if TYPE_CHECKING:
    from pathlib import Path


def _grok_setup(canonical_content: str, session_dir: Path) -> Path:
    """Write AGENTS.md to the session dir for Grok auto-discovery."""
    persona_path = session_dir / "AGENTS.md"
    persona_path.write_text(canonical_content)
    return persona_path


def _grok_launch(_persona_path: Path, resume: bool) -> str:
    """Build Grok launch command. Grok reads AGENTS.md from cwd."""
    binary = shutil.which("grok") or "grok"
    if resume:
        return f"{binary} --resume"
    return binary


ADAPTER = AgentAdapter(
    name="grok",
    binary="grok",
    setup=_grok_setup,
    launch_cmd=_grok_launch,
)
