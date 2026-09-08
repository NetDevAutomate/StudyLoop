"""Repair safety, completeness, and repeated-run acceptance tests."""

import sqlite3

import pytest

from agent_session_tools.repair import RepairReport, apply_staged, compare


def database(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, project_path TEXT);
        CREATE TABLE messages(id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id),
                              role TEXT, content TEXT);
        CREATE TABLE annotations(id TEXT, session_id TEXT REFERENCES sessions(id));
    """)
    from agent_session_tools.migrations import CURRENT_VERSION

    conn.execute(f"PRAGMA user_version={CURRENT_VERSION}")
    return conn


def session(conn, ident="s", source="kiro"):
    conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (ident, source, "/project"))


def message(conn, ident, text, role="assistant", sid="s"):
    conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", (ident, sid, role, text))


def test_backfill_preserves_unavailable_history_and_annotations_and_is_idempotent(
    tmp_path,
):
    path = tmp_path / "sessions.db"
    target = database(path)
    session(target)
    message(target, "u", "question", "user")
    session(target, "remote")
    message(target, "remote-message", "only on other machine", sid="remote")
    target.execute("INSERT INTO annotations VALUES ('note', 's')")
    target.commit()
    stage = database(":memory:")
    session(stage)
    message(stage, "u", "question", "user")
    message(stage, "a", "recovered answer")
    report = compare(stage, target)
    assert report.missing_messages == 1
    apply_staged(stage, path, report)
    assert report.applied
    assert target.execute("SELECT count(*) FROM messages").fetchone()[0] == 3
    assert target.execute("SELECT count(*) FROM annotations").fetchone()[0] == 1
    assert report.backup is not None
    with sqlite3.connect(report.backup) as backup:
        assert backup.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    assert (tmp_path / report.backup).stat().st_mode & 0o777 == 0o600
    second = compare(stage, target)
    assert second.missing_messages == second.changed_messages == 0
    apply_staged(stage, path, second)
    assert target.execute("SELECT count(*) FROM messages").fetchone()[0] == 3
    # Continued conversations import the next message without duplicating history.
    message(stage, "next", "next answer")
    apply_staged(stage, path, compare(stage, target))
    assert target.execute("SELECT count(*) FROM messages").fetchone()[0] == 4


def test_identity_collision_blocks_apply(tmp_path):
    path = tmp_path / "sessions.db"
    target = database(path)
    session(target, source="claude")
    target.commit()
    stage = database(":memory:")
    session(stage)
    report = compare(stage, target)
    assert report.conflicts
    with pytest.raises(ValueError, match="blocked"):
        apply_staged(stage, path, report)
    assert not list(tmp_path.glob("*.bak"))


def test_errors_block_partial_repair(tmp_path):
    path = tmp_path / "sessions.db"
    target = database(path)
    stage = database(":memory:")
    report = RepairReport(errors=["source could not be read"])
    with pytest.raises(ValueError, match="blocked"):
        apply_staged(stage, path, report)
    target.close()


def test_shortened_reindexed_source_does_not_overwrite_old_history(tmp_path):
    path = tmp_path / "sessions.db"
    target = database(path)
    session(target)
    message(target, "0", "original")
    message(target, "1", "original later")
    target.commit()
    stage = database(":memory:")
    session(stage)
    message(stage, "0", "compacted summary")
    report = compare(stage, target)
    assert report.retained_messages == 1
    with pytest.raises(ValueError, match="manual reconciliation"):
        apply_staged(stage, path, report)
    assert (
        target.execute("SELECT content FROM messages WHERE id='0'").fetchone()[0]
        == "original"
    )


def test_inspection_does_not_change_database(tmp_path):
    path = tmp_path / "sessions.db"
    target = database(path)
    target.close()
    before = path.read_bytes()
    stage = database(":memory:")
    session(stage)
    message(stage, "a", "new")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as readonly:
        report = compare(stage, readonly)
    assert report.missing_sessions == report.missing_messages == 1
    assert path.read_bytes() == before


def test_database_merge_preserves_target_metadata_and_unknown_sources(tmp_path):
    from agent_session_tools.repair import merge_database

    target_path, source_path = tmp_path / "local.db", tmp_path / "remote.db"
    target, source = database(target_path), database(source_path)
    session(target)
    target.execute("UPDATE sessions SET project_path='/local/project'")
    target.execute("INSERT INTO annotations VALUES ('local-note', 's')")
    message(target, "u", "same", "user")
    target.commit()
    session(source)
    message(source, "u", "same", "user")
    message(source, "a", "new remote answer")
    session(source, "unknown", "future-harness")
    message(source, "future", "unknown source evidence", sid="unknown")
    source.commit()
    dry = merge_database(target_path, source_path)
    assert dry.missing_messages == 2
    assert target.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    report = merge_database(target_path, source_path, apply=True)
    assert report.applied
    assert (
        target.execute("SELECT project_path FROM sessions WHERE id='s'").fetchone()[0]
        == "/local/project"
    )
    assert target.execute("SELECT count(*) FROM annotations").fetchone()[0] == 1
    assert (
        target.execute("SELECT source FROM sessions WHERE id='unknown'").fetchone()[0]
        == "future-harness"
    )
    assert merge_database(target_path, source_path).missing_messages == 0


def test_database_merge_preserves_conflicting_text_as_stable_revision(tmp_path):
    from agent_session_tools.repair import merge_database

    target_path, source_path = tmp_path / "local.db", tmp_path / "remote.db"
    target, source = database(target_path), database(source_path)
    for conn in (target, source):
        session(conn)
    message(target, "a", "local")
    target.execute("CREATE TABLE evidence(message_id TEXT REFERENCES messages(id))")
    target.execute("INSERT INTO evidence VALUES ('a')")
    message(source, "a", "remote")
    target.commit()
    source.commit()
    report = merge_database(target_path, source_path, apply=True)
    assert report.message_revisions == 1
    assert report.missing_messages == 1
    assert not report.conflicts
    assert (
        target.execute("SELECT content FROM messages WHERE id='a'").fetchone()[0]
        == "local"
    )
    assert {row[0] for row in target.execute("SELECT content FROM messages")} == {
        "local",
        "remote",
    }
    assert target.execute("SELECT message_id FROM evidence").fetchone()[0] == "a"
    repeated = merge_database(target_path, source_path, apply=True)
    assert repeated.missing_messages == repeated.changed_messages == 0
    assert target.execute("SELECT count(*) FROM messages").fetchone()[0] == 2


def test_native_repair_uses_seed_identity_and_deletes_only_explicit_stale_rows(
    tmp_path, monkeypatch
):
    from agent_session_tools.exporters.base import ExportStats
    from agent_session_tools.repair import run_repair

    path = tmp_path / "sessions.db"
    target = database(path)
    session(target)
    message(target, "stable", "question", "user")
    message(target, "stale-empty", "")
    session(target, "remote")
    message(target, "remote-only", "retain", sid="remote")
    target.commit()

    class Exporter:
        def is_available(self):
            return True

        def export_all(self, conn, incremental):
            assert incremental is False
            assert (
                conn.execute(
                    "SELECT id FROM messages WHERE content='question'"
                ).fetchone()[0]
                == "stable"
            )
            conn.execute("DELETE FROM messages WHERE id='stale-empty'")
            message(conn, "recovered", "answer")
            conn.commit()
            return ExportStats(updated=1)

    monkeypatch.setattr("agent_session_tools.repair.get_exporter", lambda _: Exporter())
    saved = tmp_path / "staged.db"
    report = run_repair(path, ["kiro"], apply=True, stage_output=saved)
    assert report.removed_messages == 1
    assert report.applied
    assert {row[0] for row in target.execute("SELECT id FROM messages")} == {
        "stable",
        "remote-only",
        "recovered",
    }
    with sqlite3.connect(saved) as snapshot:
        assert snapshot.execute("SELECT count(*) FROM messages").fetchone()[0] == 3


def test_target_change_during_native_staging_blocks_apply(tmp_path, monkeypatch):
    from agent_session_tools.exporters.base import ExportStats
    from agent_session_tools.repair import run_repair

    path = tmp_path / "sessions.db"
    target = database(path)
    session(target)
    target.commit()

    class Exporter:
        def is_available(self):
            return True

        def export_all(self, conn, incremental):
            message(target, "concurrent", "new live evidence")
            target.commit()
            message(conn, "staged", "recovered")
            conn.commit()
            return ExportStats(updated=1)

    monkeypatch.setattr("agent_session_tools.repair.get_exporter", lambda _: Exporter())
    with pytest.raises(ValueError, match="changed during staging"):
        run_repair(path, ["kiro"], apply=True)
    assert {row[0] for row in target.execute("SELECT id FROM messages")} == {
        "concurrent"
    }


def test_native_repair_preserves_compacted_history_and_repeated_occurrences(
    tmp_path, monkeypatch
):
    from agent_session_tools.exporters.base import ExportStats
    from agent_session_tools.repair import run_repair

    path = tmp_path / "sessions.db"
    target = database(path)
    session(target)
    message(target, "first", "repeated")
    message(target, "second", "repeated")
    message(target, "history", "older conversation lost to compaction")
    target.commit()

    class Exporter:
        def is_available(self):
            return True

        def export_all(self, conn, incremental):
            conn.execute("DELETE FROM messages")
            message(conn, "replacement", "repeated")
            conn.commit()
            return ExportStats(updated=1)

    monkeypatch.setattr("agent_session_tools.repair.get_exporter", lambda _: Exporter())
    report = run_repair(path, ["kiro"], apply=True)
    assert report.preserved_historical_messages == 2
    assert report.removed_messages == 1
    assert report.removed_roles == [
        {"role": "assistant", "nonempty": True, "messages": 1}
    ]
    assert (
        target.execute(
            "SELECT count(*) FROM messages WHERE content='repeated'"
        ).fetchone()[0]
        == 2
    )
    assert (
        target.execute("SELECT content FROM messages WHERE id='history'").fetchone()[0]
        == "older conversation lost to compaction"
    )


def test_database_merge_keeps_target_metadata_and_nonempty_text(tmp_path):
    from agent_session_tools.repair import merge_database

    target_path, source_path = tmp_path / "local.db", tmp_path / "remote.db"
    target, source = database(target_path), database(source_path)
    for conn in (target, source):
        conn.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        conn.execute("ALTER TABLE messages ADD COLUMN timestamp TEXT")
        session(conn)
        conn.execute(
            "INSERT INTO messages VALUES ('same', 's', 'assistant', 'same content', '{}', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO messages VALUES ('empty', 's', 'assistant', NULL, '{}', NULL)"
        )
    target.execute(
        "UPDATE messages SET metadata='{"
        "local"
        ": true}', timestamp='2026-02-01' WHERE id='same'"
    )
    target.execute(
        "UPDATE messages SET content='valuable target content' WHERE id='empty'"
    )
    target.execute(
        "INSERT INTO messages VALUES ('extra', 's', 'user', 'target longer history', '{}', NULL)"
    )
    target.commit()
    source.commit()
    expected_metadata = target.execute(
        "SELECT metadata FROM messages WHERE id='same'"
    ).fetchone()[0]
    report = merge_database(target_path, source_path, apply=True)
    assert report.preserved_target_metadata == 1
    assert report.preserved_target_nonempty == 1
    assert report.changed_messages == report.missing_messages == 0
    assert (
        target.execute("SELECT metadata FROM messages WHERE id='same'").fetchone()[0]
        == expected_metadata
    )
    assert (
        target.execute("SELECT content FROM messages WHERE id='empty'").fetchone()[0]
        == "valuable target content"
    )
    assert target.execute("SELECT count(*) FROM messages").fetchone()[0] == 3


def test_database_merge_cross_session_identity_collision_still_blocks(tmp_path):
    from agent_session_tools.repair import merge_database

    target_path, source_path = tmp_path / "local.db", tmp_path / "remote.db"
    target, source = database(target_path), database(source_path)
    session(target, "local")
    session(source, "remote")
    message(target, "collision", "same text", sid="local")
    message(source, "collision", "same text", sid="remote")
    target.commit()
    source.commit()
    assert merge_database(target_path, source_path).conflicts
    with pytest.raises(ValueError, match="blocked"):
        merge_database(target_path, source_path, apply=True)
    assert target.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def test_database_merge_revision_roundtrip_has_no_duplicate_growth(tmp_path):
    from agent_session_tools.repair import merge_database

    local_path, remote_path = tmp_path / "local.db", tmp_path / "remote.db"
    local, remote = database(local_path), database(remote_path)
    for conn, content in ((local, "local evidence"), (remote, "remote evidence")):
        conn.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        session(conn)
        conn.execute(
            "INSERT INTO messages VALUES ('same-id', 's', 'assistant', ?, '{}')",
            (content,),
        )
        conn.commit()
    merge_database(local_path, remote_path, apply=True)
    merge_database(remote_path, local_path, apply=True)
    for target_path, source_path in (
        (local_path, remote_path),
        (remote_path, local_path),
    ):
        report = merge_database(target_path, source_path, apply=True)
        assert report.missing_messages == 0
        assert report.message_revisions == 0
    for conn in (local, remote):
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
        assert {row[0] for row in conn.execute("SELECT content FROM messages")} == {
            "local evidence",
            "remote evidence",
        }


def test_database_merge_does_not_resurrect_empty_native_artifacts(tmp_path):
    from agent_session_tools.repair import merge_database

    local_path, remote_path = tmp_path / "local.db", tmp_path / "remote.db"
    local, remote = database(local_path), database(remote_path)
    for conn in (local, remote):
        session(conn)
    message(local, "target-empty-with-reference", "")
    local.execute("CREATE TABLE evidence(message_id TEXT REFERENCES messages(id))")
    local.execute("INSERT INTO evidence VALUES ('target-empty-with-reference')")
    message(remote, "empty", "")
    message(remote, "whitespace", "  \n")
    message(remote, "null", None)
    message(remote, "prose", "Recovered answer")
    local.commit()
    remote.commit()
    report = merge_database(local_path, remote_path, apply=True)
    assert report.skipped_empty_messages == 3
    assert report.missing_messages == 1
    assert local.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    assert (
        local.execute("SELECT message_id FROM evidence").fetchone()[0]
        == "target-empty-with-reference"
    )
    assert merge_database(local_path, remote_path).missing_messages == 0


def _old_version_database(path, monkeypatch):
    from agent_session_tools import migrations
    from agent_session_tools.export_sessions import init_db

    with monkeypatch.context() as setup:
        setup.setattr(migrations, "CURRENT_VERSION", 27)
        conn = init_db(str(path))
        conn.close()


def test_native_repair_migrates_schema_even_without_conversation_changes(
    tmp_path, monkeypatch
):
    from agent_session_tools.migrations import CURRENT_VERSION
    from agent_session_tools.repair import run_repair

    path = tmp_path / "old.db"
    _old_version_database(path, monkeypatch)
    report = run_repair(path, [])
    assert len(report.migrations_needed) == CURRENT_VERSION - 27
    assert report.migrations_applied == []
    assert report.missing_messages == report.changed_messages == 0
    with sqlite3.connect(path) as current:
        assert current.execute("PRAGMA user_version").fetchone()[0] == 27
        assert "updated_at" not in {
            row[1] for row in current.execute("PRAGMA table_info(study_sessions)")
        }
    applied = run_repair(path, [], apply=True)
    assert applied.applied
    assert applied.migrations_applied == applied.migrations_needed
    assert applied.backup is not None
    with sqlite3.connect(path) as current:
        assert current.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION
        assert "updated_at" in {
            row[1] for row in current.execute("PRAGMA table_info(study_sessions)")
        }
    with sqlite3.connect(applied.backup) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 27
    assert run_repair(path, []).migrations_needed == []


def test_native_repair_schema_and_data_rollback_together(tmp_path, monkeypatch):
    from agent_session_tools import repair

    path = tmp_path / "old.db"
    _old_version_database(path, monkeypatch)
    original_upsert = repair._upsert

    def fail_live_merge(conn, table, rows):
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        if db_path == str(path):
            # Prove migration happened inside the still-open transaction.
            assert "updated_at" in {
                row[1] for row in conn.execute("PRAGMA table_info(study_sessions)")
            }
            raise RuntimeError("injected post-migration merge failure")
        return original_upsert(conn, table, rows)

    monkeypatch.setattr(repair, "_upsert", fail_live_merge)
    with pytest.raises(RuntimeError, match="post-migration"):
        repair.run_repair(path, [], apply=True)
    with sqlite3.connect(path) as current:
        assert current.execute("PRAGMA user_version").fetchone()[0] == 27
        assert "updated_at" not in {
            row[1] for row in current.execute("PRAGMA table_info(study_sessions)")
        }
        assert current.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert len(list(tmp_path.glob("*.bak"))) == 1


@pytest.mark.parametrize("source", ["opencode", "pi"])
def test_native_identity_matchers_make_second_inspect_zero_delta(
    tmp_path, monkeypatch, source
):
    """BL-2: parser-native IDs replace legacy IDs once, then inspection is quiet."""
    from agent_session_tools.exporters.base import ExportStats
    from agent_session_tools.repair import run_repair

    path = tmp_path / "sessions.db"
    target = database(path)
    session(target, source=source)
    message(target, "legacy-id", "same native content", "assistant")
    target.commit()

    calls = 0

    class Exporter:
        def is_available(self):
            return True

        def export_all(self, conn, incremental):
            nonlocal calls
            calls += 1
            assert incremental is False
            conn.execute("DELETE FROM messages WHERE session_id='s'")
            message(
                conn,
                f"{source}-native-id-{calls}",
                "same native content",
                "assistant",
            )
            conn.commit()
            return ExportStats(updated=1)

    monkeypatch.setattr("agent_session_tools.repair.get_exporter", lambda _: Exporter())

    first = run_repair(path, [source], apply=True)
    assert first.applied
    second = run_repair(path, [source])
    assert (
        second.missing_sessions,
        second.changed_sessions,
        second.missing_messages,
        second.changed_messages,
        second.removed_messages,
    ) == (0, 0, 0, 0, 0)
