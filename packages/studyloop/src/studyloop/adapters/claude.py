"""Claude adapter — persona via --append-system-prompt-file flag.

Claude Code accepts a temp file path via this flag. The file is written
with 0600 permissions so persona content is not world-readable.
"""

from __future__ import annotations

import shlex
import shutil
from typing import TYPE_CHECKING

from studyloop.adapters._protocol import AgentAdapter
from studyloop.adapters._strategies import cli_flag_setup

if TYPE_CHECKING:
    from pathlib import Path


def _claude_launch(persona_path: Path, resume: bool) -> str:
    """Build Claude launch command with absolute binary path.

    Resolves to absolute path because tmux panes run non-interactive
    shells which don't source .zshrc (~/.local/bin not in PATH).

    Quoted with shlex.quote() because the caller (web/routes/session/
    _transport.py) executes this string via `/bin/sh -c` -- persona_path
    comes from tempfile.mkstemp() under $TMPDIR, which can contain a space
    (a custom $TMPDIR, or a home directory with one), and binary is quoted
    defensively for the same reason even though shutil.which() rarely
    returns a path with spaces (R-35).
    """
    binary = shlex.quote(shutil.which("claude") or "claude")
    quoted_persona = shlex.quote(str(persona_path))
    if resume:
        return f"{binary} -r --append-system-prompt-file {quoted_persona}"
    return f"{binary} --append-system-prompt-file {quoted_persona}"


ADAPTER = AgentAdapter(
    name="claude",
    binary="claude",
    setup=cli_flag_setup,
    launch_cmd=_claude_launch,
)
