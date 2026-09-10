"""Tests for the B2 ontology-refresh seam wired into ``export_sessions._run_export``.

Design authority: ``openspec/changes/sessionweaver-phase2-retrofit/design.md``
"Refresh-failure seam for B2"; specs ``session-export`` (both ADDED
Requirements) and ``EXECUTION-ERRATA.md`` #7 ("session capture is
authoritative"). The seam is
``export_sessions.refresh_ontology_after_export`` -- a single, separately
named call so a test can monkeypatch it to raise without touching any
export/exporter code.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_session_tools import export_sessions, ontology
from agent_session_tools.export_sessions import (
    _run_export,
    refresh_ontology_after_export,
)
from agent_session_tools.migrations import migrate

SCHEMA_PATH = Path(export_sessions.__file__).parent / "schema.sql"


def _make_db(
    tmp_path: Path, session_ids: tuple[str, ...] = ("refresh-session-001",)
) -> Path:
    """A minimal populated, fully migrated DB -- ``messages.seq`` needs migration."""
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    migrate(conn)
    for index, session_id in enumerate(session_ids):
        conn.execute(
            """
            INSERT INTO sessions(
                id, source, project_path, git_branch, created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "claude_code",
                "/tmp/refresh-project",
                "main",
                f"2026-09-07T10:0{index}:00Z",
                f"2026-09-07T10:0{index}:00Z",
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO messages(id, session_id, role, content, timestamp, metadata, seq)
            VALUES (?, ?, ?, ?, ?, '{}', ?)
            """,
            (
                f"{session_id}-msg-1",
                session_id,
                "user",
                "hello world",
                f"2026-09-07T10:0{index}:00Z",
                1,
            ),
        )
    conn.commit()
    conn.close()
    return db_path


class TestOntologyRefreshHookInvocation:
    """Every export run calls the hook; a full run scopes to the whole corpus."""

    def test_run_export_reports_the_ontology_refresh_outcome_in_its_summary(
        self, tmp_path
    ):
        db_path = _make_db(tmp_path)
        summary = _run_export(output_path=db_path, sources=set(), incremental=True)

        assert summary["ontology_refresh"]["status"] == "ok"
        # First-ever refresh always falls back to full: there is no prior
        # build state to reuse yet.
        assert summary["ontology_refresh"]["mode"] == "full"

    def test_full_export_run_refreshes_the_whole_corpus_not_a_delta(self, tmp_path):
        db_path = _make_db(tmp_path, session_ids=("full-a", "full-b"))
        # Establish a build state first via one incremental run.
        first = _run_export(output_path=db_path, sources=set(), incremental=True)
        assert first["ontology_refresh"]["candidate_sessions"] == 2

        # Nothing changed since, so an incremental run would see zero
        # candidates -- a full run must still cover both sessions.
        full = _run_export(output_path=db_path, sources=set(), incremental=False)
        assert full["ontology_refresh"]["mode"] == "full"
        assert full["ontology_refresh"]["candidate_sessions"] == 2

    def test_incremental_export_scopes_the_refresh_to_touched_sessions(self, tmp_path):
        db_path = _make_db(tmp_path, session_ids=("scope-a", "scope-b"))
        first = _run_export(output_path=db_path, sources=set(), incremental=True)
        assert first["ontology_refresh"]["candidate_sessions"] == 2

        # Must be strictly after the first build's `completed_at` (recorded
        # via the real wall clock), not a calendar-date literal -- a fixed
        # past-looking string breaks the instant the real date catches up to
        # it. Derived from `datetime.now(UTC)` so this test stays correct on
        # any day it runs.
        touched_at = (
            (datetime.now(UTC) + timedelta(days=1))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = 'scope-a'", (touched_at,)
        )
        conn.commit()
        conn.close()

        second = _run_export(output_path=db_path, sources=set(), incremental=True)
        assert second["ontology_refresh"]["status"] == "ok"
        assert second["ontology_refresh"]["mode"] == "incremental"
        assert second["ontology_refresh"]["candidate_sessions"] == 1


class TestOntologyRefreshFailureSeam:
    """A refresh failure never rolls back captured sessions and is recoverable."""

    def test_refresh_failure_survives_capture_and_recovers_via_maintenance_sweep(
        self,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        db_path = _make_db(tmp_path, session_ids=("refresh-failure-session",))

        def failing_refresh(conn, session_ids, *, incremental=True):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            export_sessions, "refresh_ontology_after_export", failing_refresh
        )

        with caplog.at_level(
            logging.WARNING, logger="agent_session_tools.export_sessions"
        ):
            summary = _run_export(output_path=db_path, sources=set(), incremental=True)

        # 1. The failure is reported, not swallowed -- and never raised.
        assert summary["ontology_refresh"]["status"] == "failed"
        assert summary["ontology_refresh"]["error_class"] == "RuntimeError"

        # 2. Captured session and message rows are present and unchanged.
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        session_row = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", ("refresh-failure-session",)
        ).fetchone()
        message_row = conn.execute(
            "SELECT id FROM messages WHERE session_id = ?", ("refresh-failure-session",)
        ).fetchone()
        conn.close()
        assert session_row is not None
        assert message_row is not None

        # 3. A structured warning fired on the named channel/field.
        matching = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "ontology_refresh_failed"
        ]
        assert len(matching) == 1
        assert matching[0].error_class == "RuntimeError"

        # 4. A follow-up maintenance sweep (session-maint ontology-rebuild's
        #    own logic) converges the ontology to a healthy, fully-covered
        #    state -- the failure was a staleness window, not a permanent gap.
        conn = sqlite3.connect(db_path)
        try:
            ontology.rebuild_ontology(conn)
            status = ontology.ontology_status(conn)
        finally:
            conn.close()
        assert status.healthy is True
        assert status.coverage_ratio == 1.0
        assert status.missing_sessions == 0

    def test_refresh_hook_is_a_single_separately_named_call(self):
        """The seam is monkeypatchable by name, per the design's contract."""
        assert (
            export_sessions.refresh_ontology_after_export
            is refresh_ontology_after_export
        )
        assert callable(export_sessions.refresh_ontology_after_export)
