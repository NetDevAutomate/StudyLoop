"""Tests for the OpenAI Codex CLI session exporter.

Validates:
- Constructor accepts an optional sessions_dir override.
- is_available() reflects directory existence.
- export_all() imports well-formed JSONL rollout files into the target DB.
- Session IDs are stable and derived from the rollout filename stem, prefixed
  with 'codex_'.
- Incremental mode behaviour (fingerprint-based skip).
- Empty rollout files produce no session row.
- Malformed JSONL lines are silently skipped.
- Content arrays (OpenAI content-parts format) are flattened to plain text.
- Metadata-only event lines (type=session_start/session_end) are not stored
  as messages but DO contribute project_path extraction.
- source column is always 'codex'.
"""

import json
from pathlib import Path

import pytest

from agent_session_tools.exporters.codex import CodexExporter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rollout(path: Path, lines: list[dict]) -> None:
    """Write a list of dicts as JSONL lines to the given rollout file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")


def _msg(
    role: str = "user",
    content: str | list | None = "Hello",
    msg_id: str | None = None,
    timestamp: str | None = "2025-01-15T12:00:00Z",
    model: str | None = None,
) -> dict:
    """Build a minimal Codex rollout message line."""
    obj: dict = {"role": role, "content": content}
    if msg_id:
        obj["id"] = msg_id
    if timestamp:
        obj["timestamp"] = timestamp
    if model:
        obj["model"] = model
    return obj


def _session_start(project_path: str = "/home/user/myproject") -> dict:
    """Build a session_start metadata line."""
    return {"type": "session_start", "project_path": project_path}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sessions_dir(tmp_path) -> Path:
    """Create a fake Codex sessions directory."""
    d = tmp_path / "codex_sessions"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestCodexConstructor:
    def test_default_sessions_dir(self):
        exporter = CodexExporter()
        assert exporter.sessions_dir == Path.home() / ".codex" / "sessions"

    def test_custom_sessions_dir(self, tmp_path):
        custom = tmp_path / "my-codex-sessions"
        exporter = CodexExporter(sessions_dir=custom)
        assert exporter.sessions_dir == custom

    def test_source_name(self):
        assert CodexExporter().source_name == "codex"


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestCodexIsAvailable:
    def test_available_when_dir_exists(self, sessions_dir):
        exporter = CodexExporter(sessions_dir=sessions_dir)
        assert exporter.is_available() is True

    def test_not_available_when_dir_missing(self, tmp_path):
        exporter = CodexExporter(sessions_dir=tmp_path / "no-such-dir")
        assert exporter.is_available() is False

    def test_not_available_for_default_path_on_this_machine(self):
        """~/.codex/sessions/ does not exist on this machine — confirmed skip path."""
        default_dir = Path.home() / ".codex" / "sessions"
        exporter = CodexExporter()
        # Only assert is_available returns a bool; it is False on this machine
        # but the important thing is it does NOT raise.
        result = exporter.is_available()
        assert isinstance(result, bool)
        # On this machine specifically (no codex sessions dir) it should be False
        if not default_dir.exists():
            assert result is False


# ---------------------------------------------------------------------------
# export_all — skip when unavailable
# ---------------------------------------------------------------------------


class TestCodexUnavailable:
    def test_returns_empty_stats_when_dir_missing(self, tmp_path, migrated_db):
        conn, _ = migrated_db
        exporter = CodexExporter(sessions_dir=tmp_path / "nonexistent")
        stats = exporter.export_all(conn)
        assert stats.added == 0
        assert stats.errors == 0
        assert stats.skipped == 0

    def test_no_rows_written_when_unavailable(self, tmp_path, migrated_db):
        conn, _ = migrated_db
        exporter = CodexExporter(sessions_dir=tmp_path / "nonexistent")
        exporter.export_all(conn)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# export_all — happy path
# ---------------------------------------------------------------------------


class TestCodexExportAll:
    def test_single_rollout_file(self, sessions_dir, migrated_db):
        conn, _ = migrated_db

        lines = [
            _session_start("/home/user/my-project"),
            _msg(role="user", content="Explain async/await.", msg_id="m-001",
                 timestamp="2025-01-15T12:00:00Z"),
            _msg(role="assistant", content="Sure! async/await allows...", msg_id="m-002",
                 timestamp="2025-01-15T12:00:05Z", model="o4-mini"),
        ]
        _write_rollout(sessions_dir / "abc123.jsonl", lines)

        exporter = CodexExporter(sessions_dir=sessions_dir)
        stats = exporter.export_all(conn)

        assert stats.added == 1
        assert stats.errors == 0

        session = conn.execute(
            "SELECT * FROM sessions WHERE id = 'codex_abc123'"
        ).fetchone()
        assert session is not None
        assert session["source"] == "codex"
        assert session["project_path"] == "/home/user/my-project"
        assert session["created_at"] == "2025-01-15T12:00:00Z"
        assert session["updated_at"] == "2025-01-15T12:00:05Z"

        msgs = conn.execute(
            "SELECT * FROM messages WHERE session_id = 'codex_abc123' ORDER BY seq"
        ).fetchall()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Explain async/await."
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["model"] == "o4-mini"

    def test_multiple_rollout_files(self, sessions_dir, migrated_db):
        conn, _ = migrated_db

        for i in range(3):
            _write_rollout(
                sessions_dir / f"session-{i}.jsonl",
                [_msg(msg_id=f"m-{i}", content=f"Message {i}")],
            )

        exporter = CodexExporter(sessions_dir=sessions_dir)
        stats = exporter.export_all(conn)

        assert stats.added == 3
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3

    def test_source_name_in_db_row(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(sessions_dir / "x.jsonl", [_msg()])

        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        row = conn.execute("SELECT source FROM sessions").fetchone()
        assert row["source"] == "codex"


# ---------------------------------------------------------------------------
# Stable session IDs
# ---------------------------------------------------------------------------


class TestCodexStableSessionIds:
    def test_session_id_prefixed_with_codex(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(sessions_dir / "deadbeef1234.jsonl", [_msg()])

        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        row = conn.execute("SELECT id FROM sessions").fetchone()
        assert row["id"] == "codex_deadbeef1234"

    def test_same_file_yields_same_id_across_runs(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        f = sessions_dir / "stable-id.jsonl"
        _write_rollout(f, [_msg()])

        exporter = CodexExporter(sessions_dir=sessions_dir)
        exporter.export_all(conn, incremental=False)
        id1 = conn.execute("SELECT id FROM sessions").fetchone()["id"]

        exporter.export_all(conn, incremental=False)
        id2 = conn.execute("SELECT id FROM sessions").fetchone()["id"]

        assert id1 == id2 == "codex_stable-id"


# ---------------------------------------------------------------------------
# Incremental skip (fingerprint-based)
# ---------------------------------------------------------------------------


class TestCodexIncremental:
    def test_unchanged_file_skipped_on_second_run(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(sessions_dir / "inc.jsonl", [_msg()])

        exporter = CodexExporter(sessions_dir=sessions_dir)
        stats1 = exporter.export_all(conn, incremental=True)
        assert stats1.added == 1

        # Second run — same file, same fingerprint → skip
        stats2 = exporter.export_all(conn, incremental=True)
        assert stats2.added == 0
        assert stats2.updated == 0

    def test_modified_file_is_reimported(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        f = sessions_dir / "mod.jsonl"
        # Use stable IDs so INSERT OR REPLACE replaces messages in-place
        _write_rollout(f, [_msg(msg_id="m-001", content="v1")])

        exporter = CodexExporter(sessions_dir=sessions_dir)
        exporter.export_all(conn, incremental=True)

        # Append a new message (changes mtime/size → new fingerprint)
        _write_rollout(
            f,
            [
                _msg(msg_id="m-001", content="v1"),
                _msg(msg_id="m-appended", content="v2"),
            ],
        )

        stats2 = exporter.export_all(conn, incremental=True)
        assert stats2.updated == 1

        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = 'codex_mod'"
        ).fetchone()[0]
        assert msg_count == 2

    def test_non_incremental_always_reimports(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(sessions_dir / "full.jsonl", [_msg()])

        exporter = CodexExporter(sessions_dir=sessions_dir)
        stats1 = exporter.export_all(conn, incremental=False)
        assert stats1.added == 1

        stats2 = exporter.export_all(conn, incremental=False)
        assert stats2.updated == 1


# ---------------------------------------------------------------------------
# Content flattening (OpenAI content-parts array)
# ---------------------------------------------------------------------------


class TestCodexContentFlattening:
    def test_string_content_passthrough(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(sessions_dir / "s.jsonl", [_msg(content="plain text")])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        row = conn.execute("SELECT content FROM messages").fetchone()
        assert row["content"] == "plain text"

    def test_content_parts_array_flattened(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        parts = [
            {"type": "text", "text": "First part."},
            {"type": "text", "text": "Second part."},
        ]
        _write_rollout(sessions_dir / "arr.jsonl", [_msg(content=parts)])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        row = conn.execute("SELECT content FROM messages").fetchone()
        assert row["content"] == "First part.\nSecond part."

    def test_text_field_fallback(self, sessions_dir, migrated_db):
        """If 'content' is absent, 'text' field is used as fallback."""
        conn, _ = migrated_db
        line = {"role": "assistant", "text": "fallback text", "timestamp": "2025-01-01T00:00:00Z"}
        _write_rollout(sessions_dir / "fb.jsonl", [line])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        row = conn.execute("SELECT content FROM messages").fetchone()
        assert row["content"] == "fallback text"

    def test_tool_call_in_content_array(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        parts = [
            {"type": "text", "text": "Calling a tool."},
            {"name": "bash", "type": "tool_call"},
        ]
        _write_rollout(sessions_dir / "tc.jsonl", [_msg(content=parts)])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        row = conn.execute("SELECT content FROM messages").fetchone()
        assert "[tool:bash]" in row["content"]


# ---------------------------------------------------------------------------
# session_start metadata extraction
# ---------------------------------------------------------------------------


class TestCodexSessionStart:
    def test_project_path_from_session_start(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        lines = [
            _session_start("/repos/my-app"),
            _msg(content="hello"),
        ]
        _write_rollout(sessions_dir / "sp.jsonl", lines)
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        row = conn.execute("SELECT project_path FROM sessions").fetchone()
        assert row["project_path"] == "/repos/my-app"

    def test_session_start_not_stored_as_message(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        lines = [_session_start(), _msg(content="real message")]
        _write_rollout(sessions_dir / "ns.jsonl", lines)
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 1  # only the real message


# ---------------------------------------------------------------------------
# Empty + malformed files
# ---------------------------------------------------------------------------


class TestCodexEdgeCases:
    def test_empty_file_produces_no_session(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        (sessions_dir / "empty.jsonl").touch()

        stats = CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        assert stats.added == 0
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0

    def test_malformed_lines_skipped(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        f = sessions_dir / "bad.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "w") as fh:
            fh.write(json.dumps(_msg(msg_id="good-1", content="valid")) + "\n")
            fh.write("{not valid json\n")
            fh.write(json.dumps(_msg(msg_id="good-2", content="also valid")) + "\n")

        stats = CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        assert stats.added == 1
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = 'codex_bad'"
        ).fetchone()[0]
        assert count == 2  # both valid lines were imported

    def test_session_end_event_not_stored_as_message(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        lines = [
            _msg(content="real"),
            {"type": "session_end", "exit_code": 0},
        ]
        _write_rollout(sessions_dir / "se.jsonl", lines)
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 1

    def test_fingerprint_stored_in_import_fingerprint_column(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(sessions_dir / "fp.jsonl", [_msg()])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        row = conn.execute("SELECT import_fingerprint FROM sessions").fetchone()
        assert row["import_fingerprint"] is not None
        assert ":" in row["import_fingerprint"]

    def test_seq_numbering(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        lines = [
            _msg(msg_id="a", content="first"),
            _msg(msg_id="b", content="second"),
            _msg(msg_id="c", content="third"),
        ]
        _write_rollout(sessions_dir / "seq.jsonl", lines)
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)

        rows = conn.execute(
            "SELECT seq FROM messages WHERE session_id = 'codex_seq' ORDER BY seq"
        ).fetchall()
        assert [r["seq"] for r in rows] == [1, 2, 3]
