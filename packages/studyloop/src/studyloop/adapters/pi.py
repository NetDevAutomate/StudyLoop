"""pi adapter using its native project context and resume command."""

from __future__ import annotations

import shlex
import shutil
from typing import TYPE_CHECKING

from studyloop import installers
from studyloop.adapters._protocol import AgentAdapter

if TYPE_CHECKING:
    from pathlib import Path


def _pi_setup(canonical_content: str, session_dir: Path) -> Path:
    """Write the AGENTS.md that pi discovers from its working directory."""
    persona_path = session_dir / "AGENTS.md"
    persona_path.write_text(canonical_content, encoding="utf-8")
    return persona_path


def _pi_launch(_persona_path: Path, resume: bool) -> str:
    """Build the launch without choosing a user model or the learner's extensions.

    ``--no-extensions`` keeps the learner's own pi extensions out of a mentor
    session; ``-e`` then loads StudyLoop's session-export extension alone, at
    the path the installer writes it to (pi documents that explicit ``-e``
    paths still work under ``--no-extensions``). Without it installed the
    launch is plain ``--no-extensions`` and the mandate is the only export path
    (council pass 3, D3).
    """
    # Quoted: the launch string runs under `/bin/sh -c` and in a tmux pane (F-CLI-23).
    binary = shlex.quote(shutil.which("pi") or "pi")
    base = f"{binary} --no-extensions"
    extension = installers._pi_hook_path()
    if extension.is_file():
        base = f"{base} -e {shlex.quote(str(extension))}"
    return f"{base} --continue" if resume else base


ADAPTER = AgentAdapter(
    name="pi",
    binary="pi",
    setup=_pi_setup,
    launch_cmd=_pi_launch,
)
