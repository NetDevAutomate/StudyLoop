"""Grok Build adapter — persona via AGENTS.md in session CWD.

Grok Build reads the AGENTS.md instruction-file family from the current
working directory (and, inside a git repository, from the repository root
down to it). The setup function writes the canonical persona into the
StudyLoop session directory; launch invokes the interactive Grok Build TUI
from that directory.

Grok Build also gates every fresh directory behind a modal "Do you trust the
contents of this directory?" (y/n) that swallows anything else typed at it.
The first real-auth live run for grok (issue #21, 2026-09-16) sat on that
dialog for both scripted turns. Grok persists the answer in
``$GROK_HOME/trusted_folders.toml`` (``[folders."<path>"] trusted = true``,
``decided_at = <epoch seconds>``; Grok CLI 1.0.30), so setup pre-trusts the
session dir and its parent there -- the same thing ``_ensure_claude_trust``
does for Claude Code in ``~/.claude/settings.json``, and nothing more: no
other Grok permission (``ui.yolo``, tool approval, hooks trust) is touched.
"""

from __future__ import annotations

import os
import shutil
import time
import tomllib
from pathlib import Path

from studyloop.adapters._protocol import AgentAdapter

TRUSTED_FOLDERS_FILE = "trusted_folders.toml"


def _grok_home() -> Path:
    """``$GROK_HOME`` when set, else ``~/.grok`` -- the rule the installer and
    the exporter apply too."""
    override = os.environ.get("GROK_HOME")
    return Path(override) if override else Path.home() / ".grok"


def _toml_string(value: str) -> str:
    """A TOML basic string: paths may contain backslashes or quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ensure_grok_trust(directory: Path) -> None:
    """Record ``directory`` as trusted in Grok Build's own trusted-folders file.

    Append-only and idempotent: an existing file is never re-serialised (Grok
    owns its layout and any other tables in it), a folder already marked
    trusted is left alone, and a machine with no Grok home at all is left
    without one -- pre-trusting is for a Grok that exists.
    """
    home = _grok_home()
    if not home.is_dir():
        return
    path = home / TRUSTED_FOLDERS_FILE
    key = str(directory)
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        try:
            folders = tomllib.loads(existing).get("folders", {})
        except tomllib.TOMLDecodeError:
            return  # not ours to repair; Grok will re-ask, which is the safe failure
        if isinstance(folders, dict) and folders.get(key, {}).get("trusted") is True:
            return
    entry = f"[folders.{_toml_string(key)}]\ntrusted = true\ndecided_at = {int(time.time())}\n"
    separator = (
        ""
        if not existing or existing.endswith("\n\n")
        else ("\n" if existing.endswith("\n") else "\n\n")
    )
    path.write_text(existing + separator + entry, encoding="utf-8")


def _grok_setup(canonical_content: str, session_dir: Path) -> Path:
    """Write AGENTS.md to the session dir for Grok Build auto-discovery, and
    pre-trust the session dir (and its parent, for future sessions) so the
    trust dialog never blocks an automated session."""
    persona_path = session_dir / "AGENTS.md"
    persona_path.write_text(canonical_content, encoding="utf-8")
    _ensure_grok_trust(session_dir.parent)
    _ensure_grok_trust(session_dir)
    return persona_path


def _grok_launch(_persona_path: Path, resume: bool) -> str:
    """Build the Grok Build launch command. Grok reads AGENTS.md from cwd."""
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
