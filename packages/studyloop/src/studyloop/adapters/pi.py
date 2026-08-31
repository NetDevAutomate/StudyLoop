"""pi adapter using its native project context and resume command."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from studyloop.adapters._protocol import AgentAdapter

if TYPE_CHECKING:
    from pathlib import Path


def _pi_setup(canonical_content: str, session_dir: Path) -> Path:
    """Write the AGENTS.md that pi discovers from its working directory."""
    persona_path = session_dir / "AGENTS.md"
    persona_path.write_text(canonical_content, encoding="utf-8")
    return persona_path


def _pi_launch(_persona_path: Path, resume: bool) -> str:
    """Build an extension-independent launch without choosing a user model."""
    binary = shutil.which("pi") or "pi"
    base = f"{binary} --no-extensions"
    return f"{base} --continue" if resume else base


ADAPTER = AgentAdapter(
    name="pi",
    binary="pi",
    setup=_pi_setup,
    launch_cmd=_pi_launch,
)
