"""Codex resume launches the ``resume`` subcommand, never a ``--resume`` flag.

Codex CLI has no ``--resume`` option: ``codex --resume`` exits with
``error: unexpected argument '--resume' found`` (codex-cli 0.160.1). Resuming
is the subcommand ``codex resume``; ``--last`` picks the most recent session
for the current working directory without opening the interactive picker
(``codex resume --help``). ``studyloop study --resume`` runs this command in
the session pane, so a flag Codex does not have ends the session at once
(review F-CLI-01).
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest


@pytest.mark.parametrize("binary", ["/usr/local/bin/codex", None])
def test_resume_uses_subcommand_not_flag(monkeypatch: pytest.MonkeyPatch, binary) -> None:
    from studyloop.adapters import codex

    monkeypatch.setattr(codex.shutil, "which", lambda _name: binary)

    argv = shlex.split(codex.ADAPTER.launch_cmd(Path("/tmp/AGENTS.md"), True))

    assert argv[0] == (binary or "codex")
    assert argv[1:] == ["resume", "--last"]
    assert "--resume" not in argv


def test_fresh_launch_is_the_bare_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    from studyloop.adapters import codex

    monkeypatch.setattr(codex.shutil, "which", lambda _name: "/usr/local/bin/codex")

    argv = shlex.split(codex.ADAPTER.launch_cmd(Path("/tmp/AGENTS.md"), False))

    assert argv == ["/usr/local/bin/codex"]
