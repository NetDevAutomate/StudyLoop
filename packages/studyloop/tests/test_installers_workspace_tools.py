"""Tests for editable workspace uv tool installation commands."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import call, patch

from studyloop.installers import install_workspace_tools

if TYPE_CHECKING:
    from pathlib import Path

# The invoking interpreter's minor version (the synced venv under `uv run`).
# install_workspace_tools pins every `uv tool install` to this value (A3) so
# the new tool venvs share the workspace's minor rather than whatever `uv
# tool install` would otherwise resolve on its own.
_PY_VER = f"{sys.version_info.major}.{sys.version_info.minor}"


def _workspace(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    (repo_root / "packages" / "agent-session-tools").mkdir(parents=True)
    (repo_root / "packages" / "studyloop").mkdir()
    return repo_root


def test_install_workspace_tools_installs_expected_tool_commands(tmp_path: Path) -> None:
    repo_root = _workspace(tmp_path)

    with patch("studyloop.installers._run") as run:
        installed = install_workspace_tools(repo_root, sync_workspace=True, force=True)

    agent_pkg = repo_root / "packages" / "agent-session-tools"
    studyloop_pkg = repo_root / "packages" / "studyloop"

    assert installed == ["agent-session-tools", "studyloop"]
    assert run.call_args_list == [
        call(["uv", "sync", "--all-packages"], cwd=repo_root),
        call(
            [
                "uv",
                "tool",
                "install",
                "--python",
                _PY_VER,
                f"{agent_pkg}[all]",
                "--editable",
                "--force",
            ],
            cwd=repo_root,
        ),
        call(
            [
                "uv",
                "tool",
                "install",
                "--python",
                _PY_VER,
                f"{studyloop_pkg}[all]",
                "--with-editable",
                f"{agent_pkg}[all]",
                "--editable",
                "--force",
            ],
            cwd=repo_root,
        ),
    ]


def test_the_studyloop_tool_env_gets_agent_session_tools_with_its_runtime_extras(
    tmp_path: Path,
) -> None:
    """`studyloop web` imports agent_session_tools in-process, in the STUDYLOOP
    tool venv: the server's boot-time encoder warm and every hybrid search run
    tokenizers, onnxruntime, huggingface_hub, numpy and sqlite_vec there. The
    standalone agent-session-tools tool gets ``[all]``, but that is a different
    venv. Co-installed bare, the studyloop venv had none of them, so the warm
    failed at import in ~10 ms and the header chip read ``semantic: failed
    (0.0s)`` -- while `doctor`, running in the same venv, called the encoder
    check "does not apply".
    """
    repo_root = _workspace(tmp_path)

    with patch("studyloop.installers._run") as run:
        install_workspace_tools(repo_root, sync_workspace=False)

    studyloop_spec = f"{repo_root / 'packages' / 'studyloop'}[all]"
    command = next(c.args[0] for c in run.call_args_list if studyloop_spec in c.args[0])
    co_installed = command[command.index("--with-editable") + 1]
    assert co_installed == f"{repo_root / 'packages' / 'agent-session-tools'}[all]"


def test_install_workspace_tools_can_skip_sync_and_force(tmp_path: Path) -> None:
    repo_root = _workspace(tmp_path)

    with patch("studyloop.installers._run") as run:
        installed = install_workspace_tools(repo_root, sync_workspace=False, force=False)

    assert installed == ["agent-session-tools", "studyloop"]
    commands = [args.args[0] for args in run.call_args_list]
    assert ["uv", "sync", "--all-packages"] not in commands
    assert all("--force" not in command for command in commands)
    assert all(command[:5][:4] == ["uv", "tool", "install", "--python"] for command in commands)
    assert all(command[4] == _PY_VER for command in commands)
