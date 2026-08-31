"""Tests for the session-export CLI (Typer app)."""

from __future__ import annotations

from unittest import mock

from typer.testing import CliRunner

from agent_session_tools import export_sessions
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


class TestEntryPointParsesArgv:
    """Guards against regressing the entry-point wiring.

    The ``[project.scripts]`` entry point targets ``main`` (a plain wrapper),
    NOT the ``@app.command()``-decorated command function. Pointing the entry
    point at a decorated command object bypasses Typer's argument parsing — every
    flag silently falls back to its default. These tests fail if that wiring
    regresses.
    """

    def test_main_delegates_to_app(self) -> None:
        """``main()`` must invoke the Typer ``app`` (which parses argv)."""
        with mock.patch.object(export_sessions, "app") as mock_app:
            export_sessions.main()
        mock_app.assert_called_once_with()

    def test_command_function_is_not_named_main(self) -> None:
        """The command must NOT be named ``main`` — else the entry point would
        call the decorated command object directly and skip argument parsing."""
        assert callable(export_sessions.main)
        # The decorated command is registered on the app, exposed as ``export``.
        assert hasattr(export_sessions, "export")

    def test_full_flag_disables_incremental(self) -> None:
        """``--full`` must reach ``_run_export`` as ``incremental=False``."""
        with mock.patch.object(export_sessions, "_run_export") as mock_run:
            result = runner.invoke(app, ["--full", "--claude-only"])
        assert result.exit_code == 0
        # _run_export(output_path, export_sources, incremental)
        assert mock_run.call_args.args[2] is False

    def test_default_is_incremental(self) -> None:
        """Without ``--full``, ``_run_export`` receives ``incremental=True``."""
        with mock.patch.object(export_sessions, "_run_export") as mock_run:
            result = runner.invoke(app, ["--claude-only"])
        assert result.exit_code == 0
        assert mock_run.call_args.args[2] is True

    def test_output_flag_is_honored(self) -> None:
        """``-o`` must reach ``_run_export`` as the output path."""
        with mock.patch.object(export_sessions, "_run_export") as mock_run:
            result = runner.invoke(app, ["-o", "/tmp/custom_sessions.db"])
        assert result.exit_code == 0
        assert str(mock_run.call_args.args[0]) == "/tmp/custom_sessions.db"
