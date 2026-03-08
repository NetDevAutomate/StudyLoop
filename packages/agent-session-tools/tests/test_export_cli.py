"""Tests for the session-export CLI (Typer app)."""

from __future__ import annotations

from typer.testing import CliRunner

from agent_session_tools.export_sessions import SOURCE_CHOICES, app

runner = CliRunner()


class TestExportHelp:
    def test_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_shows_source_choices(self) -> None:
        result = runner.invoke(app, ["--help"])
        for source in SOURCE_CHOICES:
            assert source in result.output, f"Expected source '{source}' in help text"

    def test_help_mentions_supported_tools(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert "Claude Code" in result.output
        assert "Kiro CLI" in result.output
