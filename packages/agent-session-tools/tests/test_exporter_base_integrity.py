"""Exporter writes preserve annotations and roll back incomplete batches."""

import pytest
from agent_session_tools.exporters.base import ExportStats, commit_batch


def test_upsert_preserves_references_and_fts(migrated_db):
    c, _ = migrated_db
    c.execute("PRAGMA foreign_keys=ON")
    session = {"id": "s", "source": "codex"}
    msg = {"id": "m", "session_id": "s", "role": "user", "content": "old"}
    commit_batch(c, [session], [msg], ExportStats())
    c.execute(
        "CREATE TABLE annotations (message_id TEXT REFERENCES messages(id) ON DELETE CASCADE)"
    )
    c.execute(
        "CREATE TABLE session_annotations (session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE)"
    )
    c.execute("INSERT INTO annotations VALUES ('m')")
    c.execute("INSERT INTO session_annotations VALUES ('s')")
    c.commit()
    commit_batch(c, [session], [{**msg, "content": "revised"}], ExportStats())
    assert c.execute("SELECT count(*) FROM annotations").fetchone()[0] == 1
    assert c.execute("SELECT count(*) FROM session_annotations").fetchone()[0] == 1
    assert (
        c.execute(
            "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'revised'"
        ).fetchone()[0]
        == 1
    )
    assert (
        c.execute(
            "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'old'"
        ).fetchone()[0]
        == 1
    )


def test_stale_referenced_message_aborts_whole_batch(migrated_db):
    c, _ = migrated_db
    s = {"id": "s", "source": "codex", "project_path": "original"}
    m = {"id": "m", "session_id": "s", "role": "user", "content": ""}
    commit_batch(c, [s], [m], ExportStats())
    c.execute("CREATE TABLE annotations (evidence_message_id TEXT)")
    c.execute("INSERT INTO annotations VALUES ('m')")
    c.commit()
    stats = ExportStats()
    with pytest.raises(ValueError, match="evidence references"):
        commit_batch(
            c, [{**s, "project_path": "changed", "replace_messages": True}], [], stats
        )
    assert c.execute("SELECT project_path FROM sessions").fetchone()[0] == "original"
    assert c.execute("SELECT content FROM messages").fetchone()[0] == ""
    assert stats.added == 0
    assert stats.errors == 1


def test_collision_does_not_move_message(migrated_db):
    c, _ = migrated_db
    m = {"id": "shared", "session_id": "one", "role": "user", "content": "original"}
    commit_batch(c, [{"id": "one", "source": "claude_code"}], [m], ExportStats())
    with pytest.raises(ValueError, match="collision"):
        commit_batch(
            c,
            [{"id": "two", "source": "claude_code"}],
            [{**m, "session_id": "two"}],
            ExportStats(),
        )
    assert c.execute("SELECT session_id FROM messages").fetchone()[0] == "one"
    assert c.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_compaction_preserves_prose_and_ids_without_growth(migrated_db):
    c, _ = migrated_db
    session = {"id": "s", "source": "grok", "replace_messages": True}

    def batch(texts):
        return [
            {"id": f"s-{i}", "session_id": "s", "role": "user", "content": t, "seq": i}
            for i, t in enumerate(texts)
        ]

    commit_batch(c, [session], batch(["A", "B", "C"]), ExportStats())
    commit_batch(c, [session], batch(["B", "C", "D"]), ExportStats())
    saved = dict(c.execute("SELECT id,content FROM messages"))
    assert saved["s-0"] == "A" and saved["s-1"] == "B" and saved["s-2"] == "C"
    assert sorted(saved.values()) == ["A", "B", "C", "D"]
    commit_batch(c, [session], batch(["B", "C", "D"]), ExportStats())
    assert dict(c.execute("SELECT id,content FROM messages")) == saved
