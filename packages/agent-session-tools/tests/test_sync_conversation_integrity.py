"""Conservative conversation sync must preserve evidence and committed state."""

import sqlite3
from unittest.mock import patch

import pytest

from agent_session_tools.sync import (
    _build_insert_select_sql,
    _get_sync_state,
    _stream_sql_to_target,
)


@pytest.fixture(autouse=True)
def isolated_sync_log(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent_session_tools.sync.get_log_path", lambda config: tmp_path / "sync.log"
    )


def test_fill_missing_preserve_nonempty_and_annotations(migrated_db, capsys):
    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES('m','s','unknown',NULL)"
    )
    conn.execute(
        "INSERT INTO session_notes(session_id,notes) VALUES('s','keep my notes')"
    )
    conn.commit()
    sql = "INSERT INTO messages(id,session_id,role,content) VALUES('m','s','assistant','recovered') ON CONFLICT(id) DO UPDATE SET role=CASE WHEN COALESCE(messages.content,'')='' THEN excluded.role ELSE messages.role END, content=COALESCE(NULLIF(messages.content,''),excluded.content);"
    assert _stream_sql_to_target(sql, path)
    assert tuple(conn.execute("SELECT role,content FROM messages").fetchone()) == (
        "assistant",
        "recovered",
    )
    assert _stream_sql_to_target(sql.replace("'recovered'", "'different answer'"), path)
    assert conn.execute("SELECT content FROM messages").fetchone()[0] == "recovered"
    assert "divergent message" in capsys.readouterr().out
    assert (
        conn.execute("SELECT notes FROM session_notes").fetchone()[0] == "keep my notes"
    )


def test_failed_import_rolls_back_earlier_rows(migrated_db):
    conn, path = migrated_db
    sql = "INSERT INTO sessions(id,source) VALUES('new','codex'); INSERT INTO missing_table VALUES(1);"
    assert not _stream_sql_to_target(sql, path)
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_identity_conflict_rolls_back_without_stealing(migrated_db):
    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.commit()
    assert not _stream_sql_to_target(
        "INSERT INTO sessions(id,source) VALUES('s','claude_code') ON CONFLICT(id) DO NOTHING;",
        path,
    )
    assert conn.execute("SELECT source FROM sessions").fetchone()[0] == "codex"


def test_reconcile_revisits_same_timestamp(migrated_db):
    conn, path = migrated_db
    conn.execute(
        "INSERT INTO sessions(id,source,updated_at) VALUES('s','codex','2026-01-01')"
    )
    conn.commit()
    with patch("agent_session_tools.sync._remote_sql", return_value="s|2026-01-01"):
        assert _get_sync_state(path, "host", "remote") == (set(), set())
        assert _get_sync_state(path, "host", "remote", reconcile=True) == (set(), {"s"})


def test_generated_upsert_retains_rowid_and_local_message(migrated_db):
    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES('m','s','assistant','evidence')"
    )
    original = conn.execute("SELECT rowid FROM messages").fetchone()[0]
    conn.commit()
    sql = "\n".join(
        row[0]
        for table in ("sessions", "messages")
        for row in conn.execute(_build_insert_select_sql(table))
    )
    assert _stream_sql_to_target(sql, path)
    assert conn.execute("SELECT rowid FROM messages").fetchone()[0] == original


def test_dump_carries_available_message_sequence(migrated_db):
    from agent_session_tools.sync import _dump_delta_sql

    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content,seq) VALUES('m','s','assistant','evidence',17)"
    )
    conn.commit()
    sql = _dump_delta_sql(path, {"s"})
    assert '"seq"' in sql
    conn.execute("UPDATE messages SET seq=NULL")
    conn.commit()
    assert _stream_sql_to_target(sql, path)
    assert conn.execute("SELECT seq FROM messages").fetchone()[0] == 17


def test_all_pushes_every_peer_before_pulling(monkeypatch):
    from agent_session_tools import sync as sync_mod
    from typer.testing import CliRunner

    monkeypatch.setattr(
        sync_mod, "get_endpoints", lambda config: {"first": {}, "second": {}}
    )
    calls = []
    monkeypatch.setattr(sync_mod, "push", lambda **kw: calls.append(("push", kw)))
    monkeypatch.setattr(sync_mod, "pull", lambda **kw: calls.append(("pull", kw)))
    result = CliRunner().invoke(sync_mod.app, ["all"])
    assert result.exit_code == 0, result.output
    assert [(phase, kw["remote"]) for phase, kw in calls] == [
        ("push", "first"),
        ("push", "second"),
        ("pull", "first"),
        ("pull", "second"),
    ]
    assert all(kw["reconcile"] is True for _, kw in calls)


def test_all_continues_other_peers_and_reports_failure(monkeypatch):
    from agent_session_tools import sync as sync_mod
    from typer.testing import CliRunner

    monkeypatch.setattr(
        sync_mod, "get_endpoints", lambda config: {"offline": {}, "online": {}}
    )
    calls = []

    def push(**kw):
        calls.append(("push", kw["remote"]))
        if kw["remote"] == "offline":
            raise RuntimeError("unreachable")

    monkeypatch.setattr(sync_mod, "push", push)
    monkeypatch.setattr(
        sync_mod, "pull", lambda **kw: calls.append(("pull", kw["remote"]))
    )
    result = CliRunner().invoke(sync_mod.app, ["all", "--incremental"])
    assert result.exit_code == 1
    assert calls == [
        ("push", "offline"),
        ("push", "online"),
        ("pull", "offline"),
        ("pull", "online"),
    ]
    assert "push offline" in result.output


def test_all_uses_hosts_config_and_excludes_local(monkeypatch):
    from agent_session_tools import sync as sync_mod
    from typer.testing import CliRunner

    monkeypatch.setattr(sync_mod, "_setup_logging", lambda: None)
    monkeypatch.setattr("socket.gethostname", lambda: "local-mac.local")
    monkeypatch.setattr(
        sync_mod,
        "_get_config",
        lambda: {
            "logging": {"level": "INFO"},
            "hosts": {
                "self": {"hostname": "local-mac"},
                "remote": {
                    "hostname": "other",
                    "user": "person",
                    "ip_address": "192.0.2.1",
                    "sessions_db": "/tmp/sessions.db",
                },
            },
        },
    )
    calls = []
    monkeypatch.setattr(sync_mod, "push", lambda **kw: calls.append(kw["remote"]))
    monkeypatch.setattr(sync_mod, "pull", lambda **kw: calls.append(kw["remote"]))
    result = CliRunner().invoke(sync_mod.app, ["all"])
    assert result.exit_code == 0, result.output
    assert calls == ["remote", "remote"]


def test_all_empty_config_is_actionable(monkeypatch):
    from agent_session_tools import sync as sync_mod
    from typer.testing import CliRunner

    monkeypatch.setattr(sync_mod, "get_endpoints", lambda config: {})
    result = CliRunner().invoke(sync_mod.app, ["all"])
    assert result.exit_code == 1
    assert "No remote sync targets" in result.output


@pytest.mark.parametrize("operation", ["pull", "sync"])
def test_local_backup_failure_blocks_import(operation, migrated_db, monkeypatch):
    import typer
    from agent_session_tools import sync as sync_mod

    _, path = migrated_db
    monkeypatch.setattr(
        sync_mod, "_resolve_remote", lambda *args: ("peer", "/remote.db")
    )
    monkeypatch.setattr(sync_mod, "create_backup", lambda _: None)
    calls = []
    monkeypatch.setattr(sync_mod, "_remote_sql", lambda *args: calls.append(args))
    monkeypatch.setattr(
        sync_mod, "_stream_sql_to_target", lambda *args: calls.append(args)
    )
    with pytest.raises(typer.Exit) as exc:
        getattr(sync_mod, operation)(
            remote="peer", db=path, no_backup=False, tier="hot", reconcile=True
        )
    assert exc.value.exit_code == 1
    assert calls == []


def test_source_only_empty_artifacts_not_resurrected(migrated_db, tmp_path):
    from agent_session_tools.sync import _dump_delta_sql

    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    for ident, content in [
        ("ghost-null", None),
        ("ghost-blank", "   "),
        ("real", "answer"),
    ]:
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES(?, 's', 'assistant', ?)",
            (ident, content),
        )
    conn.commit()
    sql = _dump_delta_sql(path, {"s"})
    target_path = tmp_path / "target.db"
    with sqlite3.connect(target_path) as target:
        conn.backup(target)
        target.execute("DELETE FROM messages")
        target.execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES('real','s','unknown',NULL)"
        )
    assert _stream_sql_to_target(sql, target_path)
    with sqlite3.connect(target_path) as target:
        assert target.execute("SELECT id,content FROM messages").fetchall() == [
            ("real", "answer")
        ]


def test_source_only_empty_referenced_message_aborts_safely(migrated_db, tmp_path):
    from agent_session_tools.sync import _dump_delta_sql

    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES('ghost','s','assistant',NULL)"
    )
    conn.execute(
        "INSERT INTO file_references(id,session_id,message_id,file_path,tool_name) VALUES(1,'s','ghost','example.py','read')"
    )
    conn.commit()
    sql = _dump_delta_sql(path, {"s"})
    target_path = tmp_path / "referenced.db"
    with sqlite3.connect(target_path) as target:
        conn.backup(target)
        target.execute("DELETE FROM file_references")
        target.execute("DELETE FROM messages")
    assert not _stream_sql_to_target(sql, target_path)
    with sqlite3.connect(target_path) as target:
        assert target.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert target.execute("SELECT count(*) FROM file_references").fetchone()[0] == 0


def test_schema_preflight_reports_old_remote_before_dump(migrated_db, monkeypatch):
    from agent_session_tools import sync as sync_mod

    _, path = migrated_db
    monkeypatch.setattr(
        sync_mod, "_resolve_remote", lambda *args: ("peer", "/remote.db")
    )
    monkeypatch.setattr(sync_mod, "_remote_db_exists", lambda *args: True)
    monkeypatch.setattr(sync_mod, "_remote_sql", lambda *args: "27")
    dumps = []
    monkeypatch.setattr(sync_mod, "_dump_delta_sql", lambda *args: dumps.append(args))
    with pytest.raises(
        RuntimeError, match=r"schema v27.*remote machine peer.*session-repair --apply"
    ):
        sync_mod.push(remote="peer", db=path, tier="hot", reconcile=True)
    assert dumps == []


def test_schema_preflight_current_and_newer(migrated_db, monkeypatch):
    from agent_session_tools import sync as sync_mod
    from agent_session_tools.migrations import CURRENT_VERSION

    conn, path = migrated_db
    sync_mod._require_current_schema(path)
    conn.execute(f"PRAGMA user_version={CURRENT_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer than this tool"):
        sync_mod._require_current_schema(path)


@pytest.mark.parametrize("legacy", [False, True])
def test_parked_natural_key_merges_preserving_target_identity(
    migrated_db, tmp_path, legacy
):
    from agent_session_tools.sync import _dump_delta_sql

    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.execute(
        "INSERT INTO study_sessions(id,topic,started_at) VALUES('study','python','2026-01-01')"
    )
    conn.execute(
        "INSERT INTO parked_topics(id,sync_key,study_session_id,question,context,updated_at) VALUES(1,'source-key','study','Question','newer context','2026-02-01')"
    )
    conn.commit()
    sql = _dump_delta_sql(path, {"s"})
    target_path = tmp_path / "parked-target.db"
    with sqlite3.connect(target_path) as target:
        conn.backup(target)
        target.execute(
            "UPDATE parked_topics SET id=99,sync_key='target-key',context='older context',updated_at='2026-01-01'"
        )
        if legacy:
            target.execute("DROP INDEX uix_parked_topics_question_source_pending")
            target.execute(
                "CREATE UNIQUE INDEX uix_parked_topics_session_question ON parked_topics(study_session_id,question,source)"
            )
    assert _stream_sql_to_target(sql, target_path)
    with sqlite3.connect(target_path) as target:
        assert target.execute(
            "SELECT id,sync_key,context FROM parked_topics"
        ).fetchall() == [(99, "target-key", "newer context")]


def test_concept_natural_key_remaps_incoming_references(migrated_db, tmp_path):
    from agent_session_tools.sync import _dump_delta_sql

    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES('m','s','assistant','evidence')"
    )
    conn.execute(
        "INSERT INTO concepts(id,name,domain,description,updated_at) VALUES('source-concept','Closures','python','new description','2026-02-01')"
    )
    conn.execute(
        "INSERT INTO concept_aliases(alias,concept_id) VALUES('closure','source-concept')"
    )
    conn.execute(
        "INSERT INTO message_concepts(message_id,concept_id) VALUES('m','source-concept')"
    )
    conn.commit()
    sql = _dump_delta_sql(path, {"s"})
    target_path = tmp_path / "concept-target.db"
    with sqlite3.connect(target_path) as target:
        conn.backup(target)
        target.execute("DELETE FROM concept_aliases")
        target.execute("DELETE FROM message_concepts")
        target.execute(
            "UPDATE concepts SET id='target-concept',description='old description',updated_at='2026-01-01'"
        )
    assert _stream_sql_to_target(sql, target_path)
    with sqlite3.connect(target_path) as target:
        assert target.execute("SELECT id,description FROM concepts").fetchall() == [
            ("target-concept", "new description")
        ]
        assert target.execute("SELECT concept_id FROM concept_aliases").fetchall() == [
            ("target-concept",)
        ]
        assert target.execute("SELECT concept_id FROM message_concepts").fetchall() == [
            ("target-concept",)
        ]
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []


def test_complete_parked_variants_archived_idempotently_and_propagated(
    migrated_db, tmp_path
):
    import json
    from agent_session_tools.sync import _dump_delta_sql

    conn, path = migrated_db
    conn.execute("ALTER TABLE parked_topics ADD COLUMN extra_notes TEXT")
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.execute(
        "INSERT INTO parked_topics(id,sync_key,question,context,extra_notes,status,updated_at) VALUES(1,'source-key','Repeated question','new source context','source note outside allowlist','pending','2026-02-01')"
    )
    conn.commit()
    sql = _dump_delta_sql(path, {"s"})
    target_path = tmp_path / "archive-target.db"
    with sqlite3.connect(target_path) as target:
        conn.backup(target)
        target.execute(
            "UPDATE parked_topics SET id=9,sync_key='target-key',context='original target context',extra_notes='original target note',updated_at='2026-01-01'"
        )
    assert _stream_sql_to_target(sql, target_path)
    with sqlite3.connect(target_path) as target:
        snapshots = [
            json.loads(row[0])
            for row in target.execute(
                "SELECT row_json FROM sync_row_archive WHERE table_name='parked_topics'"
            )
        ]
        assert any(
            row["sync_key"] == "source-key"
            and row["context"] == "new source context"
            and row["extra_notes"] == "source note outside allowlist"
            and row["status"] == "pending"
            for row in snapshots
        )
        assert any(
            row["sync_key"] == "target-key"
            and row["context"] == "original target context"
            and row["extra_notes"] == "original target note"
            for row in snapshots
        )
        original_count = len(snapshots)
    assert _stream_sql_to_target(sql, target_path)
    with sqlite3.connect(target_path) as target:
        assert (
            target.execute("SELECT count(*) FROM sync_row_archive").fetchone()[0]
            == original_count
        )
    # Reverse sync carries archived source variants even when no live row has
    # that original sync key any more.
    onward_sql = _dump_delta_sql(target_path, {"s"})
    assert _stream_sql_to_target(onward_sql, path)
    archived = [
        json.loads(row[0])
        for row in conn.execute("SELECT row_json FROM sync_row_archive")
    ]
    assert all(row in archived for row in snapshots)


def test_same_concept_id_different_meaning_aborts(migrated_db, tmp_path):
    from agent_session_tools.sync import _dump_delta_sql

    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES('s','codex')")
    conn.execute(
        "INSERT INTO concepts(id,name,domain) VALUES('same','Closures','python')"
    )
    conn.commit()
    sql = _dump_delta_sql(path, {"s"})
    target_path = tmp_path / "identity-target.db"
    with sqlite3.connect(target_path) as target:
        conn.backup(target)
        target.execute("UPDATE concepts SET name='Different meaning'")
    assert not _stream_sql_to_target(sql, target_path)
    with sqlite3.connect(target_path) as target:
        assert (
            target.execute("SELECT name FROM concepts").fetchone()[0]
            == "Different meaning"
        )
