"""Native authority, atomic projection, backfill and capture-health boundaries."""

import json
import sqlite3
from dataclasses import replace
from typing import Any

import pytest
from typer.testing import CliRunner

from agent_session_tools.context.capture import capture_health, capture_run
from agent_session_tools.context.cli import app
from agent_session_tools.context.lifecycle import eviction
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, _hash
from agent_session_tools.exporters.base import ExportStats, commit_batch
from agent_session_tools.exporters.claude import ClaudeCodeExporter
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.exporters.grok import GrokExporter
from agent_session_tools.exporters.kiro import KiroCliExporter
from agent_session_tools.exporters.native import (
    NativeCollector,
    claude_record,
    codex_record,
    grok_record,
    kiro_entry,
)

STAMP = "2026-09-01T12:00:00Z"


def collector(harness="codex"):
    return NativeCollector("session", harness, "/fixture/archive", "native-test-v1")


def command(code: Any = 0, status: Any = "completed"):
    return {
        "timestamp": STAMP,
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "item": {
                "type": "CommandExecution",
                "id": "call-a",
                "status": status,
                "exit_code": code,
                "command": ["python", "-m", "pytest"],
                "aggregated_output": "Tests passed. This claim is not semantic validation.",
            },
        },
    }


def message(text="All checks passed", role="assistant"):
    return {
        "timestamp": STAMP,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": "output_text", "text": text}],
        },
    }


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in records))


@pytest.mark.parametrize(
    "code,status,expected",
    [
        (0, "completed", Origin.PROCESS_EXIT),
        (2, "failed", Origin.PROCESS_EXIT),
        (None, "completed", Origin.TOOL_RESULT),
        ("0", "completed", Origin.TOOL_RESULT),
        (False, "completed", Origin.TOOL_RESULT),
        (0, "running", Origin.TOOL_RESULT),
        (0, None, Origin.TOOL_RESULT),
    ],
)
def test_only_typed_terminal_record_establishes_process_exit(code, status, expected):
    c = collector()
    codex_record(c, command(code, status), 4)
    source = c.sources[0]
    assert source.origin == expected
    assert source.exit_code == (code if expected == Origin.PROCESS_EXIT else None)
    assert source.target == '["python","-m","pytest"]'
    assert source.revision is None and source.machine_id == "unknown"
    assert source.native_locator.endswith("#line/4/payload/item")


def test_prose_and_generic_tool_outputs_do_not_gain_execution_authority():
    c = collector()
    codex_record(c, message(json.dumps(command())), 1)
    codex_record(
        c,
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "a",
                "output": "Process exited with code 0. All tests passed.",
            },
        },
        2,
    )
    assert [s.origin for s in c.sources] == [Origin.CONVERSATION, Origin.TOOL_RESULT]
    assert all(s.exit_code is None for s in c.sources)


def test_invocation_and_session_start_revision_cannot_supply_validation_metadata():
    c = collector()
    codex_record(
        c, {"type": "session_meta", "payload": {"git": {"commit_hash": "abc"}}}, 1
    )
    codex_record(
        c,
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": '{"cmd":"pytest"}',
                "call_id": "x",
            },
        },
        2,
    )
    codex_record(c, command(), 3)
    assert [s.origin for s in c.sources] == [Origin.UNKNOWN, Origin.PROCESS_EXIT]
    assert all(s.revision is None for s in c.sources)


def test_claude_tool_result_is_not_user_conversation_and_excludes_hidden_media():
    c = collector("claude_code")
    claude_record(
        c,
        {
            "uuid": "native-u",
            "timestamp": STAMP,
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-x",
                        "content": [
                            {"type": "text", "text": "Tests passed"},
                            {"type": "image", "source": {"data": "IMAGE-BYTES"}},
                        ],
                    },
                    {"type": "thinking", "thinking": "HIDDEN-THINKING"},
                ],
            },
        },
        9,
    )
    assert len(c.sources) == 1
    s = c.sources[0]
    assert s.origin == Origin.TOOL_RESULT and s.exit_code is None
    assert s.call_id == "call-x" and "native-id:native-u" in s.native_key
    assert "Tests passed" in s.body
    assert "IMAGE-BYTES" not in s.body and "HIDDEN-THINKING" not in s.body


@pytest.mark.parametrize("shape", ["dict", "pair"])
def test_kiro_native_results_have_no_inferred_process_exit(shape):
    c = collector("kiro_cli")
    user = {
        "env_context": "PRIVATE-ENV",
        "additional_context": "PRIVATE-CONTEXT",
        "content": {
            "ToolUseResults": {
                "tool_use_results": [
                    {
                        "tool_use_id": "call-k",
                        "status": "Success",
                        "content": [{"Text": "exit_code: 0"}, {"Image": "IMAGE-BYTES"}],
                    }
                ]
            }
        },
    }
    assistant = {
        "ToolUse": {
            "message_id": "m",
            "content": "I ran it",
            "thinking": "HIDDEN-THINKING",
            "tool_uses": [],
        }
    }
    entry = (
        {"user": user, "assistant": assistant} if shape == "dict" else [user, assistant]
    )
    kiro_entry(c, entry, 3)
    assert [s.origin for s in c.sources] == [Origin.TOOL_RESULT, Origin.CONVERSATION]
    body = "".join(s.body for s in c.sources)
    assert all(
        marker not in body
        for marker in [
            "PRIVATE-ENV",
            "PRIVATE-CONTEXT",
            "IMAGE-BYTES",
            "HIDDEN-THINKING",
        ]
    )
    assert c.sources[0].call_id == "call-k" and c.sources[0].exit_code is None
    assert c.sources[0].recorded_at is None


def test_grok_synthetic_reason_is_excluded_and_result_retained():
    c = collector("grok")
    grok_record(
        c,
        {
            "type": "assistant",
            "synthetic_reason": "summary",
            "content": "DO-NOT-CAPTURE",
        },
        1,
    )
    grok_record(
        c, {"type": "tool_result", "tool_call_id": "call-g", "content": "success"}, 2
    )
    assert len(c.sources) == 1 and c.sources[0].origin == Origin.TOOL_RESULT
    assert c.sources[0].call_id == "call-g" and c.sources[0].recorded_at is None


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-09-01T12:00:00"])
def test_unavailable_or_naive_timestamp_stays_unknown(timestamp):
    c = collector()
    record = message()
    record["timestamp"] = timestamp
    codex_record(c, record, 1)
    assert c.sources[0].recorded_at is None


@pytest.mark.parametrize("harness", ["codex", "claude_code", "kiro_cli", "grok"])
def test_real_exporter_captures_native_only_session(
    harness, migrated_db, tmp_path, monkeypatch
):
    conn, _ = migrated_db
    root = tmp_path / "native"
    if harness == "codex":
        write_jsonl(root / "rollout-one.jsonl", [command()])
        exporter = CodexExporter(sessions_dir=root)
    elif harness == "claude_code":
        write_jsonl(
            root / "project" / "one.jsonl",
            [
                {
                    "uuid": "u",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "a",
                                "content": "done",
                            }
                        ],
                    },
                }
            ],
        )
        exporter = ClaudeCodeExporter(projects_dir=root)
    elif harness == "grok":
        write_jsonl(
            root / "one" / "chat_history.jsonl",
            [{"type": "tool_result", "tool_call_id": "a", "content": "done"}],
        )
        (root / "one" / "summary.json").write_text(json.dumps({"info": {"id": "one"}}))
        exporter = GrokExporter(sessions_dir=root)
    else:
        path = tmp_path / "kiro.sqlite3"
        native = sqlite3.connect(path)
        native.execute(
            "CREATE TABLE conversations_v2(key TEXT,conversation_id TEXT,value TEXT,created_at INTEGER,updated_at INTEGER)"
        )
        native.execute(
            "INSERT INTO conversations_v2 VALUES (?,?,?,?,?)",
            (
                "/fixture/project",
                "one",
                json.dumps(
                    {
                        "conversation_id": "one",
                        "history": [
                            {
                                "user": {
                                    "content": {
                                        "ToolUseResults": {
                                            "tool_use_results": [
                                                {
                                                    "tool_use_id": "a",
                                                    "status": "Success",
                                                    "content": [{"Text": "done"}],
                                                }
                                            ]
                                        }
                                    }
                                }
                            }
                        ],
                    }
                ),
                1,
                2,
            ),
        )
        native.commit()
        native.close()
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", path)
        exporter = KiroCliExporter()
    stats = exporter.export_all(conn)
    assert (stats.added, stats.errors, stats.empty) == (1, 0, 0)
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    source = conn.execute("SELECT * FROM context_evidence").fetchone()
    assert source["harness"] == harness
    assert source["origin"] == ("process_exit" if harness == "codex" else "tool_result")
    identity = source["id"]
    exporter.export_all(conn, incremental=False)
    assert [r[0] for r in conn.execute("SELECT id FROM context_evidence")] == [identity]
    assert exporter.export_all(conn).skipped == 1
    # A native parser upgrade must backfill even identical archive bytes.
    metadata = json.loads(
        conn.execute("SELECT metadata FROM sessions").fetchone()[0] or "{}"
    )
    fingerprint = (
        metadata.get("kiro_import_fingerprint")
        if harness == "kiro_cli"
        else conn.execute("SELECT import_fingerprint FROM sessions").fetchone()[0]
    )
    current, rest = fingerprint.split(":", 1)
    previous = {
        "codex-v3": "codex-v2",
        "claude-v3": "claude-v2",
        "kiro-v5": "kiro-v4",
        "grok-v2": "grok-v1",
    }[current]
    # Model a pre-capture archive, not a user's permanent forget. The modern
    # DELETE trigger intentionally prevents a retired identity being backfilled.
    with ContextStore(conn)._atomic(), eviction(conn):
        conn.execute("DELETE FROM context_evidence")
    if harness == "kiro_cli":
        metadata["kiro_import_fingerprint"] = previous + ":" + rest
        conn.execute("UPDATE sessions SET metadata=?", (json.dumps(metadata),))
    else:
        conn.execute(
            "UPDATE sessions SET import_fingerprint=?", (previous + ":" + rest,)
        )
    conn.commit()
    assert exporter.export_all(conn).updated == 1
    assert conn.execute("SELECT id FROM context_evidence").fetchone()[0] == identity


def test_updated_source_preserves_old_bytes_and_rendering_links(migrated_db, tmp_path):
    conn, _ = migrated_db
    path = tmp_path / "native" / "rollout-one.jsonl"
    write_jsonl(path, [message("first")])
    exporter = CodexExporter(sessions_dir=path.parent)
    exporter.export_all(conn)
    old_id = conn.execute("SELECT id FROM context_evidence").fetchone()[0]
    write_jsonl(path, [message("second")])
    assert exporter.export_all(conn).updated == 1
    assert {r[0] for r in conn.execute("SELECT body FROM context_evidence")} == {
        "first",
        "second",
    }
    links = conn.execute(
        "SELECT m.content,n.rendered_body_sha256,e.body FROM context_native_message_sources n JOIN messages m ON m.id=n.message_id JOIN context_evidence e ON e.id=n.evidence_id"
    ).fetchall()
    assert len(links) == 2
    assert all(_hash(r[0]) == r[1] and r[0] == r[2] for r in links)
    assert (
        conn.execute(
            "SELECT body FROM context_evidence WHERE id=?", (old_id,)
        ).fetchone()[0]
        == "first"
    )
    path.write_text(path.read_text() + "{invalid")
    assert exporter.export_all(conn).errors > 0
    assert conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 2


def test_capture_failure_rolls_back_legacy_native_and_links(
    migrated_db, tmp_path, monkeypatch
):
    conn, _ = migrated_db
    path = tmp_path / "rollout-one.jsonl"
    write_jsonl(path, [message("first"), message("second")])
    original = ContextStore.capture
    calls = 0

    def fail_second(self, source):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("fixture native capture failure")
        return original(self, source)

    monkeypatch.setattr(ContextStore, "capture", fail_second)
    try:
        CodexExporter(sessions_dir=tmp_path).export_all(conn)
    except ValueError:
        pass
    for table in [
        "sessions",
        "messages",
        "context_evidence",
        "context_native_message_sources",
    ]:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert conn.execute("SELECT outcome FROM context_capture_runs").fetchone()[0] in (
        "failed",
        "partial",
    )


def test_forgetting_does_not_block_other_sessions_in_batch(migrated_db):
    conn, _ = migrated_db
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO context_tombstones VALUES ('gone','retired','2026-09-01T00:00:00Z')"
    )
    conn.commit()
    c = collector()
    codex_record(c, message(), 1)
    sessions = [
        {
            "id": sid,
            "source": "codex",
            "native_sources": [replace(c.sources[0], session_id=sid)],
        }
        for sid in ("gone", "kept")
    ]
    stats = ExportStats()
    commit_batch(conn, sessions, [], stats)
    assert (stats.added, stats.forgotten, stats.errors) == (1, 1, 0)
    assert [r[0] for r in conn.execute("SELECT id FROM sessions")] == ["kept"]
    assert [r[0] for r in conn.execute("SELECT session_id FROM context_evidence")] == [
        "kept"
    ]


def test_capture_follows_applied_roots_but_preserves_explicit_owners(
    migrated_db, tmp_path, monkeypatch
):
    conn, _ = migrated_db
    policy = ScopePolicy.from_config(
        {
            "memory": {
                "projects": {
                    "p": {"scope": "personal", "roots": ["/fixture/p"]},
                    "w": {"scope": "work", "roots": ["/fixture/w"]},
                }
            }
        }
    )
    monkeypatch.setattr(
        "agent_session_tools.context.capture.active_policy", lambda: policy
    )
    apply_policy(conn, policy, actor="test", dry_run=False)
    conn.execute("PRAGMA foreign_keys=ON")

    def capture(path):
        commit_batch(
            conn,
            [{"id": "s", "source": "codex", "project_path": path}],
            [],
            ExportStats(),
        )

    capture("/fixture/p/repo")
    assert (
        conn.execute("SELECT project_id FROM context_session_projects").fetchone()[0]
        == "p"
    )
    capture("/fixture/w/repo")
    assert (
        conn.execute("SELECT project_id FROM context_session_projects").fetchone()[0]
        == "w"
    )
    capture("/outside")
    assert (
        conn.execute("SELECT count(*) FROM context_session_projects").fetchone()[0] == 0
    )
    conn.execute("INSERT INTO context_session_projects VALUES ('s','p','explicit')")
    conn.commit()
    capture("/fixture/w/repo")
    assert (
        conn.execute("SELECT project_id FROM context_session_projects").fetchone()[0]
        == "p"
    )
    monkeypatch.setattr(
        "agent_session_tools.context.capture.active_policy",
        lambda: ScopePolicy.from_config({}),
    )
    commit_batch(
        conn,
        [{"id": "new", "source": "codex", "project_path": "/fixture/p/repo"}],
        [],
        ExportStats(),
    )
    assert (
        conn.execute(
            "SELECT 1 FROM context_session_projects WHERE session_id='new'"
        ).fetchone()
        is None
    )


@pytest.mark.parametrize(
    "outcome", ["completed", "partial", "unavailable", "failed", "interrupted"]
)
def test_capture_receipts_distinguish_attempt_outcomes_without_error_bodies(
    migrated_db, outcome
):
    conn, _ = migrated_db

    class FixtureExporter:
        source_name = "codex"

        def is_available(self):
            return outcome != "unavailable"

        @capture_run("codex-native-v1")
        def export_all(self, connection):
            if outcome == "failed":
                raise RuntimeError("PRIVATE-ERROR-BODY")
            if outcome == "interrupted":
                raise KeyboardInterrupt()
            return ExportStats(errors=1 if outcome == "partial" else 0)

    try:
        FixtureExporter().export_all(conn)
    except (RuntimeError, KeyboardInterrupt):
        pass
    health = capture_health(conn)
    codex = health["harnesses"][0]
    assert codex["attempt_state"] == (
        "incomplete_attempt" if outcome == "interrupted" else outcome
    )
    assert "PRIVATE-ERROR-BODY" not in json.dumps(health)
    assert health["hook_liveness"] == "not_established"
    assert health["archive_completeness"] == "not_established"
    assert codex["latest_attempt"]["error_class"] == (
        "RuntimeError" if outcome == "failed" else None
    )


def test_export_rejects_borrowed_transaction_without_committing_it(
    migrated_db, tmp_path
):
    conn, _ = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES ('pending','codex')")
    with pytest.raises(ValueError, match="caller transaction"):
        CodexExporter(sessions_dir=tmp_path).export_all(conn)
    assert conn.in_transaction
    assert conn.execute("SELECT count(*) FROM context_capture_runs").fetchone()[0] == 0
    conn.rollback()
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_health_reads_without_migration_or_private_bodies(migrated_db):
    conn, path = migrated_db
    conn.execute(
        "INSERT INTO sessions(id,source,project_path) VALUES ('legacy','codex','PRIVATE-PATH')"
    )
    conn.commit()
    before = path.read_bytes()
    result = CliRunner().invoke(app, ["health", "--db", str(path)])
    assert result.exit_code == 0, result.output
    health = json.loads(result.output)
    assert health["harnesses"][0]["sessions_needing_native_backfill"] == 1
    assert health["harnesses"][0]["attempt_state"] == "no_attempt_recorded"
    assert "PRIVATE-PATH" not in result.output
    assert path.read_bytes() == before


def test_interrupt_rolls_back_pending_batch_and_keeps_attempt_incomplete(migrated_db):
    conn, _ = migrated_db

    class Interrupted:
        source_name = "codex"

        @capture_run("codex-native-v1")
        def export_all(self, connection):
            connection.execute(
                "INSERT INTO sessions(id,source) VALUES ('partial','codex')"
            )
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        Interrupted().export_all(conn)
    assert not conn.in_transaction
    conn.commit()
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert capture_health(conn)["harnesses"][0]["attempt_state"] == "incomplete_attempt"


def test_digest_fallback_keeps_identical_native_records_distinct():
    c = collector()
    codex_record(c, message(), 1)
    codex_record(c, message(), 2)
    assert len(c.sources) == 2
    assert c.sources[0].body == c.sources[1].body
    assert c.sources[0].native_key != c.sources[1].native_key


def test_unknown_command_status_and_nonzero_exit_do_not_imply_validation():
    c = collector()
    for index, (code, status) in enumerate(
        [(-9, "failed"), (0, "cancelled"), (None, "timed_out")]
    ):
        codex_record(c, command(code, status), index)
    assert [s.origin for s in c.sources] == [
        Origin.PROCESS_EXIT,
        Origin.TOOL_RESULT,
        Origin.TOOL_RESULT,
    ]
    assert [s.exit_code for s in c.sources] == [-9, None, None]


def test_structured_invocation_media_is_omitted_without_interpreting_text():
    c = collector("claude_code")
    claude_record(
        c,
        {
            "uuid": "u",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call",
                        "name": "inspect",
                        "input": {
                            "media": {"type": "input_image", "data": "BINARY-MARKER"},
                            "text": '{"type":"image","source":"this is quoted text"}',
                        },
                    }
                ],
            },
        },
        1,
    )
    assert "BINARY-MARKER" not in c.sources[0].body
    assert "this is quoted text" in c.sources[0].body


def test_health_for_older_schema_requests_migration_without_writing(temp_db):
    conn, _ = temp_db
    changes = conn.total_changes
    assert capture_health(conn) == {"status": "migration_required", "harnesses": []}
    assert conn.total_changes == changes
