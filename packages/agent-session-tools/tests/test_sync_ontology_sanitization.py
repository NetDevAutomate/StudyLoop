"""Sync boundary for the tier-1 ontology (B2, R7 sync tests).

Design authority: ``openspec/changes/sessionweaver-phase2-retrofit/design.md``
"Seed sanitization"; spec ``data-store-and-sync`` "Migration v48 installs a
derived tier-1 ontology that never joins either sync-table list" and
"Seeding a never-before-synced remote strips ontology rows and triggers a
destination-local rebuild".
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from agent_session_tools import ontology, sync
from agent_session_tools.sync import (
    GLOBAL_SYNC_TABLES,
    SYNC_TABLES,
    _sanitize_ontology_snapshot,
)


class TestOntologyNeverJoinsEitherSyncTableList:
    """Positive control: the lists themselves are non-empty and contain real tables."""

    def test_sync_tables_is_non_empty_and_contains_sessions(self) -> None:
        assert SYNC_TABLES
        assert "sessions" in SYNC_TABLES

    def test_global_sync_tables_is_non_empty(self) -> None:
        assert GLOBAL_SYNC_TABLES

    def test_neither_list_contains_any_ontology_table(self) -> None:
        for table in ontology.ONTOLOGY_TABLES:
            assert table not in SYNC_TABLES, (
                f"{table} must never be a per-session sync table"
            )
            assert table not in GLOBAL_SYNC_TABLES, (
                f"{table} must never be a global sync table"
            )

    def test_neither_list_contains_ontology_build_state(self) -> None:
        assert "ontology_build_state" not in SYNC_TABLES
        assert "ontology_build_state" not in GLOBAL_SYNC_TABLES


def _make_ontology_populated_db(
    db_path: Path, session_id: str = "seed-source-session"
) -> None:
    """A minimal DB with sessions/messages and a populated ontology (no migrate())."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, project_path TEXT,
            git_branch TEXT, created_at TEXT, updated_at TEXT, metadata JSON
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
            role TEXT NOT NULL, content TEXT, timestamp TEXT, metadata JSON, seq INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO sessions(id, source, project_path, git_branch, created_at, updated_at, metadata) "
        "VALUES (?, 'codex', '/tmp/seed-project', 'main', '2026-09-07T10:00:00Z', "
        "'2026-09-07T10:00:00Z', '{}')",
        (session_id,),
    )
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content, timestamp, metadata, seq) "
        "VALUES (?, ?, 'user', 'hello world', '2026-09-07T10:00:00Z', '{}', 1)",
        (f"{session_id}-msg-1", session_id),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    ontology.rebuild_ontology(conn)
    conn.close()


class TestSanitizeOntologySnapshot:
    """Unit test of the stripping step itself, on two temp DBs."""

    def test_strips_ontology_rows_from_a_snapshot_but_leaves_the_source_untouched(
        self, tmp_path: Path
    ) -> None:
        source_path = tmp_path / "source.db"
        snapshot_path = tmp_path / "snapshot.db"
        _make_ontology_populated_db(source_path)

        # SQLite Online Backup, never cp, into the second temp DB.
        with (
            sqlite3.connect(source_path) as source,
            sqlite3.connect(snapshot_path) as dest,
        ):
            source.backup(dest)

        source_conn = sqlite3.connect(source_path)
        try:
            source_counts_before = {
                table: source_conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
                for table in ontology.ONTOLOGY_TABLES
            }
        finally:
            source_conn.close()
        assert source_counts_before["ontology_class"] > 0
        assert source_counts_before["ontology_build_state"] == 1

        _sanitize_ontology_snapshot(snapshot_path)

        snapshot_conn = sqlite3.connect(snapshot_path)
        try:
            for table in ontology.ONTOLOGY_TABLES:
                count = snapshot_conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
                assert count == 0, f"{table} must be empty in the sanitized snapshot"
            # Schema stays present -- the snapshot must still open without error
            # and be immediately migratable/rebuildable on the destination.
            tables = {
                row[0]
                for row in snapshot_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert ontology.ONTOLOGY_TABLES <= tables
            # sessions/messages (the never-derived, always-synced data) are untouched.
            assert (
                snapshot_conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                == 1
            )
            assert (
                snapshot_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                == 1
            )
        finally:
            snapshot_conn.close()

        # Source is completely unaffected by sanitizing the snapshot.
        source_conn = sqlite3.connect(source_path)
        try:
            for table, expected in source_counts_before.items():
                actual = source_conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
                assert actual == expected, (
                    f"sanitizing the snapshot must not touch the source's {table}"
                )
        finally:
            source_conn.close()

    def test_is_a_no_op_when_the_snapshot_predates_migration_v48(
        self, tmp_path: Path
    ) -> None:
        """A pre-v48 snapshot has no ontology tables at all -- nothing to strip, no error."""
        snapshot_path = tmp_path / "legacy-snapshot.db"
        conn = sqlite3.connect(snapshot_path)
        conn.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        _sanitize_ontology_snapshot(snapshot_path)  # must not raise

        conn = sqlite3.connect(snapshot_path)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        conn.close()

    def test_snapshot_reaches_100_percent_coverage_after_a_destination_local_rebuild(
        self, tmp_path: Path
    ) -> None:
        """After sanitization, the destination's own rebuild reconstructs everything."""
        source_path = tmp_path / "source.db"
        snapshot_path = tmp_path / "snapshot.db"
        _make_ontology_populated_db(
            source_path, session_id="destination-rebuild-session"
        )

        with (
            sqlite3.connect(source_path) as source,
            sqlite3.connect(snapshot_path) as dest,
        ):
            source.backup(dest)
        _sanitize_ontology_snapshot(snapshot_path)

        dest_conn = sqlite3.connect(snapshot_path)
        dest_conn.execute("PRAGMA foreign_keys = ON")
        try:
            result = ontology.rebuild_ontology(dest_conn)
            status = ontology.ontology_status(dest_conn)
        finally:
            dest_conn.close()

        assert result.mode == "full"  # no build state survived sanitization
        assert status.healthy is True
        assert status.coverage_ratio == 1.0


class TestSeedRemoteDbSanitizesBeforeTransfer:
    """Integration: ``_seed_remote_db`` itself sanitizes before ``scp``."""

    def test_seed_remote_db_sanitizes_the_snapshot_before_scp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A pre-context (no context_projects) source so the whole-file legacy
        # guard does not refuse before we ever reach sanitization -- the guard
        # itself is out of scope here; only the stripping step is under test.
        source_path = tmp_path / "legacy-source.db"
        _make_ontology_populated_db(source_path, session_id="seed-remote-session")

        captured: dict[str, dict[str, int]] = {}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "scp":
                snapshot_path = Path(cmd[-2])
                conn = sqlite3.connect(snapshot_path)
                try:
                    captured["counts"] = {
                        table: conn.execute(
                            f'SELECT COUNT(*) FROM "{table}"'
                        ).fetchone()[0]
                        for table in ontology.ONTOLOGY_TABLES
                    }
                finally:
                    conn.close()
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sync.subprocess, "run", fake_run)

        result = sync._seed_remote_db("host", "/remote/sessions.db", source_path)

        assert result is True
        assert captured, "scp was never invoked"
        for table, count in captured["counts"].items():
            assert count == 0, f"{table} was not stripped before scp"
