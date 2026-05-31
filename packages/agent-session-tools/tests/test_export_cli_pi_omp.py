"""Tests for --pi-only / --omp-only CLI flags and pi/omp SOURCE_CHOICES entries."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from agent_session_tools.export_sessions import SOURCE_CHOICES, app

runner = CliRunner()


class TestSourceChoicesContainsPiOmp:
    def test_pi_in_source_choices(self) -> None:
        assert "pi" in SOURCE_CHOICES

    def test_omp_in_source_choices(self) -> None:
        assert "omp" in SOURCE_CHOICES

    def test_source_choices_sorted(self) -> None:
        assert SOURCE_CHOICES == sorted(SOURCE_CHOICES), (
            "SOURCE_CHOICES must be alphabetically sorted"
        )


class TestPiOnlyFlag:
    def test_pi_only_flag_accepted(self, tmp_path: Path) -> None:
        """--pi-only must be accepted without 'invalid choice' / exit-code 2."""
        db = tmp_path / "sessions.db"
        result = runner.invoke(app, ["--pi-only", "--output", str(db)])
        # Exit code 2 means arg-parse error (Bad Parameter); any other outcome is fine.
        assert result.exit_code != 2, (
            f"--pi-only was rejected as invalid: {result.output}"
        )

    def test_pi_only_in_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--pi-only" in result.output

    def test_pi_only_exports_only_pi_source(self, tmp_path: Path) -> None:
        """When --pi-only is given, only the 'pi' source is queried."""
        db = tmp_path / "sessions.db"
        # Invoke with a non-existent pi dir — the exporter should attempt pi only.
        # We verify by checking DB stats: no other source rows should be present.
        result = runner.invoke(app, ["--pi-only", "--output", str(db)])
        assert result.exit_code != 2, (
            f"--pi-only flagged as bad parameter: {result.output}"
        )
        if db.exists():
            conn = sqlite3.connect(db)
            sources_in_db = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT source FROM sessions"
                ).fetchall()
            }
            conn.close()
            # If anything was written, it must only be 'pi'.
            assert sources_in_db <= {"pi"}, (
                f"--pi-only wrote unexpected sources: {sources_in_db}"
            )


class TestOmpOnlyFlag:
    def test_omp_only_flag_accepted(self, tmp_path: Path) -> None:
        """--omp-only must be accepted without 'invalid choice' / exit-code 2."""
        db = tmp_path / "sessions.db"
        result = runner.invoke(app, ["--omp-only", "--output", str(db)])
        assert result.exit_code != 2, (
            f"--omp-only was rejected as invalid: {result.output}"
        )

    def test_omp_only_in_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--omp-only" in result.output

    def test_omp_only_exports_only_omp_source(self, tmp_path: Path) -> None:
        """When --omp-only is given, only the 'omp' source is queried."""
        db = tmp_path / "sessions.db"
        result = runner.invoke(app, ["--omp-only", "--output", str(db)])
        assert result.exit_code != 2, (
            f"--omp-only flagged as bad parameter: {result.output}"
        )
        if db.exists():
            conn = sqlite3.connect(db)
            sources_in_db = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT source FROM sessions"
                ).fetchall()
            }
            conn.close()
            assert sources_in_db <= {"omp"}, (
                f"--omp-only wrote unexpected sources: {sources_in_db}"
            )


class TestMutualExclusivity:
    def test_pi_and_omp_together_rejected(self, tmp_path: Path) -> None:
        """Specifying two --*-only flags simultaneously must be rejected."""
        db = tmp_path / "sessions.db"
        result = runner.invoke(app, ["--pi-only", "--omp-only", "--output", str(db)])
        # The code raises BadParameter when more than one *_only flag is active.
        assert result.exit_code != 0, (
            "Expected non-zero exit when two --*-only flags are combined"
        )

    def test_pi_and_claude_together_rejected(self, tmp_path: Path) -> None:
        db = tmp_path / "sessions.db"
        result = runner.invoke(app, ["--pi-only", "--claude-only", "--output", str(db)])
        assert result.exit_code != 0, (
            "Expected non-zero exit when --pi-only and --claude-only are combined"
        )


class TestSourcesArgumentAcceptsPiOmp:
    def test_sources_pi_accepted(self, tmp_path: Path) -> None:
        db = tmp_path / "sessions.db"
        result = runner.invoke(app, ["--sources", "pi", "--output", str(db)])
        assert result.exit_code != 2, (
            f"'pi' rejected as invalid --sources value: {result.output}"
        )

    def test_sources_omp_accepted(self, tmp_path: Path) -> None:
        db = tmp_path / "sessions.db"
        result = runner.invoke(app, ["--sources", "omp", "--output", str(db)])
        assert result.exit_code != 2, (
            f"'omp' rejected as invalid --sources value: {result.output}"
        )
