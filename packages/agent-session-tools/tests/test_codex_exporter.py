"""Tests for the OpenAI Codex CLI session exporter.

Fixtures mirror the **real** on-disk rollout format:
- Files live in a ``YYYY/MM/DD`` subtree and are named ``rollout-*.jsonl``.
- The first line is a ``session_meta`` event carrying ``payload.cwd`` +
  ``payload.git.branch``.
- Conversation turns are ``response_item`` events whose ``payload.type`` is
  ``message``, with ``content`` as OpenAI content-parts (``input_text`` /
  ``output_text``) and the timestamp on the envelope, not the payload.
- The injected ``developer`` role and non-message ``response_item`` payloads
  (reasoning, function_call, ...) are skipped.

Validates: constructor override, availability, recursive discovery, stable
``codex_<stem>`` ids, fingerprint-based incremental skip, content flattening,
metadata extraction, role filtering, and edge cases.
"""

import json
from pathlib import Path

import pytest

from agent_session_tools.exporters.codex import CodexExporter


# ---------------------------------------------------------------------------
# Helpers — build real-shaped rollout lines
# ---------------------------------------------------------------------------


def _write_rollout(path: Path, lines: list[dict]) -> None:
    """Write a list of dicts as JSONL lines to a rollout file (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")


def _session_meta(cwd: str = "/home/user/myproject", branch: str = "main") -> dict:
    """A ``session_meta`` line as Codex writes it."""
    return {
        "timestamp": "2026-06-03T20:37:05.264Z",
        "type": "session_meta",
        "payload": {"id": "abc", "cwd": cwd, "git": {"branch": branch}},
    }


def _msg(
    role: str = "user",
    text: str | None = "Hello",
    content: list | None = None,
    timestamp: str | None = "2026-01-15T12:00:00Z",
    model: str | None = None,
) -> dict:
    """A ``response_item`` message line.

    ``text`` is wrapped in an ``input_text``/``output_text`` part to match what
    Codex actually writes; pass ``content`` to supply explicit parts instead.
    """
    if content is None:
        part_type = "output_text" if role == "assistant" else "input_text"
        content = [{"type": part_type, "text": text}] if text is not None else []
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": content,
            "model": model,
        },
    }


def _non_message(payload_type: str = "reasoning") -> dict:
    """A ``response_item`` that is not a message (reasoning, function_call, ...)."""
    return {
        "timestamp": "2026-01-15T12:00:01Z",
        "type": "response_item",
        "payload": {"type": payload_type, "content": "ignored"},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sessions_dir(tmp_path) -> Path:
    """A fake Codex sessions root."""
    d = tmp_path / "codex_sessions"
    d.mkdir()
    return d


def _dated(sessions_dir: Path, name: str) -> Path:
    """Path to a rollout file inside a realistic YYYY/MM/DD subtree."""
    return sessions_dir / "2026" / "06" / "03" / name


# ---------------------------------------------------------------------------
# Constructor / availability
# ---------------------------------------------------------------------------


class TestCodexConstructor:
    def test_default_sessions_dir(self):
        assert CodexExporter().sessions_dir == Path.home() / ".codex" / "sessions"

    def test_custom_sessions_dir(self, tmp_path):
        custom = tmp_path / "my-codex-sessions"
        assert CodexExporter(sessions_dir=custom).sessions_dir == custom

    def test_source_name(self):
        assert CodexExporter().source_name == "codex"


class TestCodexIsAvailable:
    def test_available_when_dir_exists(self, sessions_dir):
        assert CodexExporter(sessions_dir=sessions_dir).is_available() is True

    def test_not_available_when_dir_missing(self, tmp_path):
        assert CodexExporter(sessions_dir=tmp_path / "nope").is_available() is False


class TestCodexUnavailable:
    def test_returns_empty_stats_when_dir_missing(self, tmp_path, migrated_db):
        conn, _ = migrated_db
        stats = CodexExporter(sessions_dir=tmp_path / "nonexistent").export_all(conn)
        assert (stats.added, stats.errors, stats.skipped) == (0, 0, 0)

    def test_no_rows_written_when_unavailable(self, tmp_path, migrated_db):
        conn, _ = migrated_db
        CodexExporter(sessions_dir=tmp_path / "nonexistent").export_all(conn)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestCodexExportAll:
    def test_single_rollout_file_nested_dir(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        lines = [
            _session_meta("/home/user/my-project", branch="feature/x"),
            _msg("user", "Explain async/await.", timestamp="2026-01-15T12:00:00Z"),
            _msg(
                "assistant",
                "Sure! async/await allows...",
                timestamp="2026-01-15T12:00:05Z",
                model="gpt-5",
            ),
        ]
        _write_rollout(_dated(sessions_dir, "rollout-abc123.jsonl"), lines)

        stats = CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (stats.added, stats.errors) == (1, 0)

        session = conn.execute(
            "SELECT * FROM sessions WHERE id = 'codex_rollout-abc123'"
        ).fetchone()
        assert session is not None
        assert session["source"] == "codex"
        assert session["project_path"] == "/home/user/my-project"
        assert session["git_branch"] == "feature/x"
        assert session["created_at"] == "2026-01-15T12:00:00Z"
        assert session["updated_at"] == "2026-01-15T12:00:05Z"

        msgs = conn.execute(
            "SELECT * FROM messages WHERE session_id = 'codex_rollout-abc123' ORDER BY seq"
        ).fetchall()
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("user", "Explain async/await."),
            ("assistant", "Sure! async/await allows..."),
        ]
        assert msgs[1]["model"] == "gpt-5"

    def test_multiple_files_across_subdirs(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(
            sessions_dir / "2026" / "06" / "03" / "rollout-a.jsonl", [_msg(text="A")]
        )
        _write_rollout(
            sessions_dir / "2026" / "06" / "04" / "rollout-b.jsonl", [_msg(text="B")]
        )
        stats = CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert stats.added == 2
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2

    def test_source_name_in_db_row(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(_dated(sessions_dir, "rollout-x.jsonl"), [_msg()])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (
            conn.execute("SELECT source FROM sessions").fetchone()["source"] == "codex"
        )


# ---------------------------------------------------------------------------
# Stable ids
# ---------------------------------------------------------------------------


class TestCodexStableSessionIds:
    def test_session_id_prefixed_with_codex(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(_dated(sessions_dir, "rollout-deadbeef.jsonl"), [_msg()])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (
            conn.execute("SELECT id FROM sessions").fetchone()["id"]
            == "codex_rollout-deadbeef"
        )

    def test_same_file_yields_same_id_across_runs(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        f = _dated(sessions_dir, "rollout-stable.jsonl")
        _write_rollout(f, [_msg()])
        exporter = CodexExporter(sessions_dir=sessions_dir)
        exporter.export_all(conn, incremental=False)
        exporter.export_all(conn, incremental=False)
        ids = [r["id"] for r in conn.execute("SELECT id FROM sessions").fetchall()]
        assert ids == ["codex_rollout-stable"]


# ---------------------------------------------------------------------------
# Incremental skip (fingerprint-based)
# ---------------------------------------------------------------------------


class TestCodexIncremental:
    def test_unchanged_file_skipped_on_second_run(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(_dated(sessions_dir, "rollout-inc.jsonl"), [_msg()])
        exporter = CodexExporter(sessions_dir=sessions_dir)
        assert exporter.export_all(conn, incremental=True).added == 1
        stats2 = exporter.export_all(conn, incremental=True)
        assert (stats2.added, stats2.updated, stats2.skipped) == (0, 0, 1)

    def test_modified_file_is_reimported_without_dupes(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        f = _dated(sessions_dir, "rollout-mod.jsonl")
        _write_rollout(f, [_msg(text="v1")])
        exporter = CodexExporter(sessions_dir=sessions_dir)
        exporter.export_all(conn, incremental=True)

        _write_rollout(f, [_msg(text="v1"), _msg(role="assistant", text="v2")])
        stats2 = exporter.export_all(conn, incremental=True)
        assert stats2.updated == 1
        # Positional ids + delete-on-update ⇒ exactly the new message set.
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = 'codex_rollout-mod'"
            ).fetchone()[0]
            == 2
        )

    def test_non_incremental_always_reimports(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(_dated(sessions_dir, "rollout-full.jsonl"), [_msg()])
        exporter = CodexExporter(sessions_dir=sessions_dir)
        assert exporter.export_all(conn, incremental=False).added == 1
        assert exporter.export_all(conn, incremental=False).updated == 1


# ---------------------------------------------------------------------------
# Content flattening / role filtering
# ---------------------------------------------------------------------------


class TestCodexContent:
    def test_content_parts_flattened(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        parts = [
            {"type": "input_text", "text": "First part."},
            {"type": "input_text", "text": "Second part."},
        ]
        _write_rollout(_dated(sessions_dir, "rollout-arr.jsonl"), [_msg(content=parts)])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (
            conn.execute("SELECT content FROM messages").fetchone()["content"]
            == "First part.\nSecond part."
        )

    def test_developer_role_skipped(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        lines = [
            _msg("developer", "SYSTEM PROMPT — huge injected blob"),
            _msg("user", "real question"),
        ]
        _write_rollout(_dated(sessions_dir, "rollout-dev.jsonl"), lines)
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        rows = conn.execute("SELECT role, content FROM messages").fetchall()
        assert [(r["role"], r["content"]) for r in rows] == [("user", "real question")]

    def test_non_message_response_items_skipped(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        lines = [
            _msg("user", "hi"),
            _non_message("reasoning"),
            _non_message("function_call"),
            _msg("assistant", "hello"),
        ]
        _write_rollout(_dated(sessions_dir, "rollout-mix.jsonl"), lines)
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestCodexEdgeCases:
    def test_meta_only_file_is_empty(self, sessions_dir, migrated_db):
        """A rollout with metadata + non-message events but no real turns."""
        conn, _ = migrated_db
        lines = [_session_meta(), _non_message("reasoning")]
        _write_rollout(_dated(sessions_dir, "rollout-meta.jsonl"), lines)
        stats = CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (stats.added, stats.empty) == (0, 1)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0

    def test_truly_empty_file_is_empty(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        f = _dated(sessions_dir, "rollout-empty.jsonl")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()
        stats = CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (stats.added, stats.empty) == (0, 1)

    def test_malformed_lines_skipped(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        f = _dated(sessions_dir, "rollout-bad.jsonl")
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "w") as fh:
            fh.write(json.dumps(_msg(text="valid")) + "\n")
            fh.write("{not valid json\n")
            fh.write(json.dumps(_msg(role="assistant", text="also valid")) + "\n")
        stats = CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        assert stats.added == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = 'codex_rollout-bad'"
            ).fetchone()[0]
            == 2
        )

    def test_fingerprint_stored(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _write_rollout(_dated(sessions_dir, "rollout-fp.jsonl"), [_msg()])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        fp = conn.execute("SELECT import_fingerprint FROM sessions").fetchone()[0]
        assert fp is not None and ":" in fp

    def test_seq_numbering(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        lines = [_msg(text="a"), _msg(text="b"), _msg(role="assistant", text="c")]
        _write_rollout(_dated(sessions_dir, "rollout-seq.jsonl"), lines)
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        rows = conn.execute(
            "SELECT seq FROM messages WHERE session_id = 'codex_rollout-seq' ORDER BY seq"
        ).fetchall()
        assert [r["seq"] for r in rows] == [1, 2, 3]

    def test_project_path_falls_back_to_parent_dir(self, sessions_dir, migrated_db):
        """No session_meta ⇒ project_path defaults to the file's parent dir."""
        conn, _ = migrated_db
        f = _dated(sessions_dir, "rollout-nopath.jsonl")
        _write_rollout(f, [_msg(text="hi")])
        CodexExporter(sessions_dir=sessions_dir).export_all(conn)
        row = conn.execute("SELECT project_path FROM sessions").fetchone()
        assert row["project_path"] == str(f.parent)
