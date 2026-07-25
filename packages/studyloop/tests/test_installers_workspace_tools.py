"""Tests for editable workspace uv tool installation commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import call, patch

from studyloop.installers import install_workspace_tools

if TYPE_CHECKING:
    from pathlib import Path


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
            ["uv", "tool", "install", f"{agent_pkg}[all]", "--editable", "--force"],
            cwd=repo_root,
        ),
        call(
            [
                "uv",
                "tool",
                "install",
                f"{studyloop_pkg}[all]",
                "--with-editable",
                str(agent_pkg),
                "--editable",
                "--force",
            ],
            cwd=repo_root,
        ),
    ]


def test_install_workspace_tools_can_skip_sync_and_force(tmp_path: Path) -> None:
    repo_root = _workspace(tmp_path)

    with patch("studyloop.installers._run") as run:
        installed = install_workspace_tools(repo_root, sync_workspace=False, force=False)

    assert installed == ["agent-session-tools", "studyloop"]
    commands = [args.args[0] for args in run.call_args_list]
    assert ["uv", "sync", "--all-packages"] not in commands
    assert all("--force" not in command for command in commands)
