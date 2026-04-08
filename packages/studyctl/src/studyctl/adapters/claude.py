"""Claude adapter — persona via --append-system-prompt-file flag.

Claude Code accepts a temp file path via this flag. The file is written
with 0600 permissions so persona content is not world-readable.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from studyctl.adapters._protocol import AgentAdapter
from studyctl.adapters._strategies import cli_flag_setup

if TYPE_CHECKING:
    from pathlib import Path


def _claude_launch(persona_path: Path, resume: bool) -> str:
    """Build Claude launch command with absolute binary path.

    Resolves to absolute path because tmux panes run non-interactive
    shells which don't source .zshrc (~/.local/bin not in PATH).
    """
    binary = shutil.which("claude") or "claude"
    if resume:
        return f"{binary} -r --append-system-prompt-file {persona_path}"
    return f"{binary} --append-system-prompt-file {persona_path}"


ADAPTER = AgentAdapter(
    name="claude",
    binary="claude",
    setup=cli_flag_setup,
    launch_cmd=_claude_launch,
)
