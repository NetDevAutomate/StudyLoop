"""Tests for typed install commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from studyctl.cli import cli

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestInstallTools:
    def test_install_tools_dispatches(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("studyctl.cli._install.require_repo_root", return_value=tmp_path),
            patch(
                "studyctl.cli._install.install_workspace_tools",
                return_value=["agent-session-tools", "studyctl"],
            ) as mock_install,
        ):
            result = runner.invoke(cli, ["install", "tools", "--repo-root", str(tmp_path)])

        assert result.exit_code == 0, result.output
        mock_install.assert_called_once_with(tmp_path, sync_workspace=True, force=True)
        assert "Installed tools" in result.output


class TestInstallAgents:
    def test_install_agents_dispatches(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("studyctl.cli._install.require_repo_root", return_value=tmp_path),
            patch(
                "studyctl.cli._install.install_agent_definitions",
                return_value={"shared": 1, "codex": 1},
            ) as mock_install,
        ):
            result = runner.invoke(
                cli, ["install", "agents", "--repo-root", str(tmp_path), "--tool", "codex"]
            )

        assert result.exit_code == 0, result.output
        mock_install.assert_called_once_with(tmp_path, tools=["codex"], uninstall=False)
        assert "Updated agent definitions" in result.output
