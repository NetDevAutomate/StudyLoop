"""Tests for the ``session-maint ontology-rebuild`` / ``ontology-status`` commands."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from agent_session_tools import ontology
from agent_session_tools.maintenance import app
from agent_session_tools.migrations import migrate

runner = CliRunner()

SCHEMA_PATH = (
    Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
)


def _make_db(tmp_path: Path, session_id: str = "maint-session-001") -> Path:
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text())
    migrate(conn)
    conn.execute(
        """
        INSERT INTO sessions(
            id, source, project_path, git_branch, created_at, updated_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            "codex",
            "/tmp/maint-project",
            "main",
            "2026-09-07T10:00:00Z",
            "2026-09-07T10:00:00Z",
            "{}",
        ),
    )
    conn.execute(
        """
        INSERT INTO messages(id, session_id, role, content, timestamp, metadata, seq)
        VALUES (?, ?, 'user', 'hello world', '2026-09-07T10:00:00Z', '{}', 1)
        """,
        (f"{session_id}-msg-1", session_id),
    )
    conn.commit()
    conn.close()
    return db_path


class TestOntologyRebuildCommand:
    def test_rebuild_on_missing_db_fails(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["ontology-rebuild", "--db", str(tmp_path / "missing.db")]
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_full_rebuild_populates_the_graph_and_reports_counts(
        self, tmp_path: Path
    ) -> None:
        db_path = _make_db(tmp_path)

        result = runner.invoke(app, ["ontology-rebuild", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert "rebuilt" in result.output.lower()
        conn = sqlite3.connect(db_path)
        try:
            status = ontology.ontology_status(conn)
        finally:
            conn.close()
        assert status.healthy is True
        assert status.coverage_ratio == 1.0

    def test_incremental_flag_reaches_rebuild_ontology(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        # Establish a build state first.
        runner.invoke(app, ["ontology-rebuild", "--db", str(db_path)])

        result = runner.invoke(
            app, ["ontology-rebuild", "--db", str(db_path), "--incremental"]
        )

        assert result.exit_code == 0, result.output
        assert "incremental" in result.output.lower()

    def test_rebuild_recovers_a_deliberately_stale_ontology(
        self, tmp_path: Path
    ) -> None:
        """The maintenance sweep: a stale/missing build state is not a permanent gap."""
        db_path = _make_db(tmp_path, session_id="stale-session")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO sessions(
                id, source, project_path, git_branch, created_at, updated_at, metadata
            ) VALUES ('second-session', 'codex', '/tmp/maint-project', 'main',
                      '2026-09-07T11:00:00Z', '2026-09-07T11:00:00Z', '{}')
            """
        )
        conn.commit()
        conn.close()

        result = runner.invoke(app, ["ontology-rebuild", "--db", str(db_path)])
        assert result.exit_code == 0, result.output

        conn = sqlite3.connect(db_path)
        try:
            status = ontology.ontology_status(conn)
        finally:
            conn.close()
        assert status.healthy is True
        assert status.coverage_ratio == 1.0
        assert status.missing_sessions == 0


class TestOntologyStatusCommand:
    def test_status_on_missing_db_fails(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["ontology-status", "--db", str(tmp_path / "missing.db")]
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_status_is_read_only_and_reports_unhealthy_before_any_rebuild(
        self, tmp_path: Path
    ) -> None:
        db_path = _make_db(tmp_path)
        before = db_path.read_bytes()

        result = runner.invoke(app, ["ontology-status", "--db", str(db_path)])

        assert result.exit_code == 1  # unhealthy: never built
        assert "unhealthy" in result.output.lower()
        assert db_path.read_bytes() == before, (
            "ontology-status must never mutate the database"
        )

    def test_status_reports_healthy_after_a_rebuild(self, tmp_path: Path) -> None:
        db_path = _make_db(tmp_path)
        runner.invoke(app, ["ontology-rebuild", "--db", str(db_path)])

        result = runner.invoke(app, ["ontology-status", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert "healthy" in result.output.lower()
        assert "coverage: 1/1" in result.output.lower()
