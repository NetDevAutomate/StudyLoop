"""The missing-runtime hint names the venv that raised it (issue #46 item 1).

``embedding_store.INSTALL_HINT`` was the literal
``uv tool install 'agent-session-tools[semantic]'`` wherever it was printed:
the warm's failure detail (the web header chip's tooltip), ``session-maint
embed`` and ``doctor``. That command installs into agent-session-tools' own
tool venv. The interpreter that raised the error is almost never that one --
``studyloop web`` runs in the ``studyloop`` tool venv, a developer's
``session-maint`` runs in the workspace ``.venv`` -- so following the hint
changed nothing the learner could see, and on one machine it sent the learner
to reinstall a tool venv that was already correct.

The hint is now computed from the interpreter's prefix: it names that prefix
and a command that fixes it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_session_tools import embedding_store


@pytest.fixture
def uv_tool_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tool_dir = tmp_path / "uv" / "tools"
    tool_dir.mkdir(parents=True)
    monkeypatch.setenv("UV_TOOL_DIR", str(tool_dir))
    return tool_dir


def test_studyloop_tool_venv_is_fixed_by_the_tool_installer(uv_tool_dir: Path):
    prefix = uv_tool_dir / "studyloop"
    hint = embedding_store.install_hint(prefix)
    assert str(prefix) in hint
    assert "./scripts/install.sh --tools-only" in hint
    assert "uv tool install 'agent-session-tools[semantic]'" not in hint


def test_agent_session_tools_tool_venv_is_fixed_by_the_same_installer(
    uv_tool_dir: Path,
):
    prefix = uv_tool_dir / "agent-session-tools"
    hint = embedding_store.install_hint(prefix)
    assert str(prefix) in hint
    assert "./scripts/install.sh --tools-only" in hint


def test_workspace_venv_is_fixed_by_uv_sync_with_the_extra(tmp_path: Path):
    checkout = tmp_path / "studyloop"
    (checkout / ".venv").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        "[tool.uv.workspace]\nmembers = ['packages/*']\n"
    )
    hint = embedding_store.install_hint(checkout / ".venv")
    assert str(checkout / ".venv") in hint
    assert "uv sync --all-packages --group dev --extra semantic" in hint
    assert "uv tool install" not in hint


def test_an_unrecognised_interpreter_is_still_named_with_the_extra(tmp_path: Path):
    prefix = tmp_path / "somewhere" / "else"
    prefix.mkdir(parents=True)
    hint = embedding_store.install_hint(prefix)
    assert str(prefix) in hint
    assert "agent-session-tools[semantic]" in hint


def test_the_module_constant_is_the_hint_for_the_running_interpreter():
    assert embedding_store.INSTALL_HINT == embedding_store.install_hint(sys.prefix)
    assert sys.prefix in embedding_store.INSTALL_HINT


def test_uv_tool_dir_defaults_follow_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without UV_TOOL_DIR, uv uses $XDG_DATA_HOME/uv/tools, else ~/.local/share/uv/tools."""
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert embedding_store._uv_tool_dir() == tmp_path / "data" / "uv" / "tools"
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert (
        embedding_store._uv_tool_dir()
        == tmp_path / "home" / ".local" / "share" / "uv" / "tools"
    )
