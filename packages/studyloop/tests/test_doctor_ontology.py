"""Tests for the tier-1 ontology-freshness doctor check (harness category).

Design authority: ``openspec/changes/sessionweaver-phase2-retrofit/design.md``
and spec ``health-and-diagnostics`` "New checkers cover ontology
freshness..." / "...classified report-only, never fatal". Every result must
be ``pass``/``warn``/``info`` with ``fix_auto=False`` -- never ``fail``, and
never able to move ``_compute_exit_code()`` to exit 2.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

SCHEMA_PATH = (
    Path(__file__).parent.parent.parent
    / "agent-session-tools"
    / "src"
    / "agent_session_tools"
    / "schema.sql"
)


def _make_db(tmp_path: Path, *, session_id: str = "doctor-session-001") -> Path:
    from agent_session_tools.migrations import migrate

    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text())
    migrate(conn)
    conn.execute(
        """
        INSERT INTO sessions(
            id, source, project_path, git_branch, created_at, updated_at, metadata
        ) VALUES (?, 'codex', '/tmp/doctor-project', 'main',
                  '2026-09-07T10:00:00Z', '2026-09-07T10:00:00Z', '{}')
        """,
        (session_id,),
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


class TestOntologyFreshnessCheckAvailability:
    def test_not_installed_reports_info(self):
        from studyloop.doctor.harness import check_ontology_freshness

        with patch("importlib.util.find_spec", return_value=None):
            results = check_ontology_freshness()
        assert len(results) == 1
        assert results[0].status == "info"
        assert results[0].category == "harness"
        assert "not installed" in results[0].message.lower()

    def test_missing_db_reports_info(self, tmp_path: Path):
        from studyloop.doctor.harness import check_ontology_freshness

        missing = tmp_path / "nope.db"
        with patch("studyloop.doctor.database._get_sessions_db_path", return_value=missing):
            results = check_ontology_freshness()
        assert len(results) == 1
        assert results[0].status == "info"


class TestOntologyFreshnessCheckReporting:
    def test_never_built_ontology_warns_coverage_and_freshness(self, tmp_path: Path):
        """A migrated DB (v48 installs the empty schema) whose ontology was
        never rebuilt: schema present, but coverage/freshness must warn."""
        from studyloop.doctor.harness import check_ontology_freshness

        db_path = _make_db(tmp_path)

        with patch("studyloop.doctor.database._get_sessions_db_path", return_value=db_path):
            results = check_ontology_freshness()

        by_name = {r.name: r for r in results}
        assert by_name["ontology_present"].status == "pass"
        assert by_name["ontology_coverage"].status == "warn"
        assert by_name["ontology_coverage"].fix_auto is False
        assert "session-maint ontology-rebuild" in by_name["ontology_coverage"].fix_hint
        assert by_name["ontology_freshness"].status == "warn"
        assert all(r.status != "fail" for r in results)

    def test_healthy_ontology_reports_all_pass(self, tmp_path: Path):
        from agent_session_tools import ontology
        from studyloop.doctor.harness import check_ontology_freshness

        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        ontology.rebuild_ontology(conn)
        conn.close()

        with patch("studyloop.doctor.database._get_sessions_db_path", return_value=db_path):
            results = check_ontology_freshness()

        assert results
        assert {r.status for r in results} == {"pass"}
        assert {r.category for r in results} == {"harness"}
        assert all(r.fix_auto is False for r in results)

    def test_stale_ontology_fixture_reports_coverage_and_freshness_warnings(self, tmp_path: Path):
        """Fixture-inserted red path: a new session lands after the last build."""
        from agent_session_tools import ontology
        from studyloop.doctor.harness import check_ontology_freshness

        db_path = _make_db(tmp_path, session_id="stale-fixture-session")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        ontology.rebuild_ontology(conn)

        # A session captured after the ontology was last built -- the "GIVEN
        # sessions have been captured since the last ontology build" scenario.
        conn.execute(
            """
            INSERT INTO sessions(
                id, source, project_path, git_branch, created_at, updated_at, metadata
            ) VALUES ('unbuilt-new-session', 'codex', '/tmp/doctor-project', 'main',
                      '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z', '{}')
            """
        )
        conn.commit()
        conn.close()

        with patch("studyloop.doctor.database._get_sessions_db_path", return_value=db_path):
            results = check_ontology_freshness()

        by_name = {r.name: r for r in results}
        assert by_name["ontology_present"].status == "pass"
        assert by_name["ontology_coverage"].status == "warn"
        assert "session-maint ontology-rebuild" in by_name["ontology_coverage"].fix_hint
        assert by_name["ontology_freshness"].status == "warn"
        # Never fail, never auto-fixed by doctor itself -- report-only.
        assert all(r.status != "fail" for r in results)
        assert all(r.fix_auto is False for r in results)

    def test_extraction_version_mismatch_fixture_reports_a_warning(self, tmp_path: Path):
        """Fixture-inserted red path: build state recorded under a stale extraction version."""
        from agent_session_tools import ontology
        from studyloop.doctor.harness import check_ontology_freshness

        db_path = _make_db(tmp_path, session_id="version-fixture-session")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        ontology.rebuild_ontology(conn)
        conn.execute("UPDATE ontology_build_state SET extraction_version = 'tier1-v0-obsolete'")
        conn.commit()
        conn.close()

        with patch("studyloop.doctor.database._get_sessions_db_path", return_value=db_path):
            results = check_ontology_freshness()

        by_name = {r.name: r for r in results}
        assert by_name["ontology_extraction_version"].status == "warn"
        assert "tier1-v0-obsolete" in by_name["ontology_extraction_version"].message
        assert all(r.status != "fail" for r in results)


class TestOntologyFreshnessNeverAffectsExitCode:
    def test_registered_results_never_move_exit_code_to_2(self, tmp_path: Path):
        """Spec: none of these checks shall cause doctor's exit code to be 2."""
        from studyloop.cli._doctor import _compute_exit_code
        from studyloop.doctor.harness import check_ontology_freshness

        db_path = _make_db(tmp_path, session_id="exit-code-fixture-session")
        with patch("studyloop.doctor.database._get_sessions_db_path", return_value=db_path):
            results = check_ontology_freshness()

        assert _compute_exit_code(results) != 2
