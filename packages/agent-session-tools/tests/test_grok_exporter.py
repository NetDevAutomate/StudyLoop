"""Tests for the xAI Grok CLI session exporter.

Fixtures mirror the real on-disk layout: each session is a directory holding a
``summary.json`` (metadata) and ``chat_history.jsonl`` (one message object per
line, role discriminated by ``type``), nested one level under a URL-encoded-cwd
parent.

Validates: constructor override, availability, recursive discovery, stable
``grok_<id>`` ids, ``updated_at``-based incremental skip, content flattening,
role filtering (system/tool_result dropped), and edge cases.
"""

import json
from pathlib import Path

import pytest

from agent_session_tools.exporters.grok import GrokExporter


# ---------------------------------------------------------------------------
# Helpers — build a real-shaped session directory
# ---------------------------------------------------------------------------


def _make_session(
    parent: Path,
    session_id: str = "019f-abc",
    *,
    cwd: str = "/home/user/proj",
    created_at: str = "2026-06-26T23:52:39Z",
    updated_at: str = "2026-06-26T23:52:53Z",
    model: str = "grok-bedrock",
    title: str = "which model is being used?",
    branch: str = "main",
    chat_lines: list[dict] | None = None,
    write_chat: bool = True,
) -> Path:
    """Create ``<parent>/<url-encoded-cwd>/<session_id>/`` with summary + chat."""
    enc_cwd = cwd.replace("/", "%2F")
    sess_dir = parent / enc_cwd / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "info": {"id": session_id, "cwd": cwd},
        "session_summary": title,
        "created_at": created_at,
        "updated_at": updated_at,
        "current_model_id": model,
        "generated_title": title,
        "head_branch": branch,
        "git_root_dir": cwd + "/",
    }
    (sess_dir / "summary.json").write_text(json.dumps(summary))

    if write_chat:
        if chat_lines is None:
            chat_lines = [
                {"type": "system", "content": "You are Grok ..."},
                {"type": "user", "content": [{"type": "text", "text": "which model?"}]},
                {
                    "type": "assistant",
                    "content": "Grok 4.3 on Bedrock.",
                    "model_id": "xai.grok-4.3",
                    "tool_calls": [],
                },
            ]
        with open(sess_dir / "chat_history.jsonl", "w", encoding="utf-8") as fh:
            for obj in chat_lines:
                fh.write(json.dumps(obj) + "\n")

    return sess_dir


@pytest.fixture()
def sessions_dir(tmp_path) -> Path:
    d = tmp_path / "grok_sessions"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Constructor / availability
# ---------------------------------------------------------------------------


class TestGrokConstructor:
    def test_default_dir(self):
        assert GrokExporter().sessions_dir == Path.home() / ".grok" / "sessions"

    def test_custom_dir(self, tmp_path):
        assert GrokExporter(sessions_dir=tmp_path / "x").sessions_dir == tmp_path / "x"

    def test_source_name(self):
        assert GrokExporter().source_name == "grok"


class TestGrokIsAvailable:
    def test_available(self, sessions_dir):
        assert GrokExporter(sessions_dir=sessions_dir).is_available() is True

    def test_not_available(self, tmp_path):
        assert GrokExporter(sessions_dir=tmp_path / "nope").is_available() is False

    def test_returns_empty_when_unavailable(self, tmp_path, migrated_db):
        conn, _ = migrated_db
        stats = GrokExporter(sessions_dir=tmp_path / "nope").export_all(conn)
        assert (stats.added, stats.errors, stats.skipped) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestGrokExportAll:
    def test_single_session(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _make_session(sessions_dir, "019f-abc", cwd="/home/user/proj", branch="dev")

        stats = GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (stats.added, stats.errors) == (1, 0)

        session = conn.execute(
            "SELECT * FROM sessions WHERE id = 'grok_019f-abc'"
        ).fetchone()
        assert session["source"] == "grok"
        assert session["project_path"] == "/home/user/proj"
        assert session["git_branch"] == "dev"
        assert session["created_at"] == "2026-06-26T23:52:39Z"
        assert session["updated_at"] == "2026-06-26T23:52:53Z"
        assert json.loads(session["metadata"])["model"] == "grok-bedrock"

    def test_only_user_and_assistant_stored(self, sessions_dir, migrated_db):
        """system + tool_result lines are dropped."""
        conn, _ = migrated_db
        _make_session(
            sessions_dir,
            chat_lines=[
                {"type": "system", "content": "prompt"},
                {"type": "user", "content": [{"type": "text", "text": "hi"}]},
                {"type": "tool_result", "content": "raw tool output"},
                {"type": "assistant", "content": "hello", "model_id": "xai.grok-4.3"},
            ],
        )
        GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        rows = conn.execute(
            "SELECT role, content, model FROM messages ORDER BY seq"
        ).fetchall()
        assert [(r["role"], r["content"]) for r in rows] == [
            ("user", "hi"),
            ("assistant", "hello"),
        ]
        assert rows[1]["model"] == "xai.grok-4.3"

    def test_multiple_sessions_across_cwd_parents(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _make_session(sessions_dir, "s1", cwd="/a")
        _make_session(sessions_dir, "s2", cwd="/b")
        stats = GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        assert stats.added == 2
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# Stable ids + incremental
# ---------------------------------------------------------------------------


class TestGrokIncremental:
    def test_id_prefixed_and_stable(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _make_session(sessions_dir, "deadbeef")
        GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (
            conn.execute("SELECT id FROM sessions").fetchone()["id"] == "grok_deadbeef"
        )

    def test_unchanged_skipped(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _make_session(sessions_dir, "inc")
        exporter = GrokExporter(sessions_dir=sessions_dir)
        assert exporter.export_all(conn, incremental=True).added == 1
        stats2 = exporter.export_all(conn, incremental=True)
        assert (stats2.added, stats2.updated, stats2.skipped) == (0, 0, 1)

    def test_updated_at_change_reimports_without_dupes(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _make_session(sessions_dir, "mod", updated_at="2026-06-26T23:52:53Z")
        exporter = GrokExporter(sessions_dir=sessions_dir)
        exporter.export_all(conn, incremental=True)

        # Same id, newer updated_at, more messages.
        _make_session(
            sessions_dir,
            "mod",
            updated_at="2026-06-27T10:00:00Z",
            chat_lines=[
                {"type": "user", "content": "q1"},
                {"type": "assistant", "content": "a1", "model_id": "xai.grok-4.3"},
                {"type": "user", "content": "q2"},
            ],
        )
        stats2 = exporter.export_all(conn, incremental=True)
        assert stats2.updated == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = 'grok_mod'"
            ).fetchone()[0]
            == 3
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestGrokEdgeCases:
    def test_no_user_or_assistant_is_empty(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _make_session(
            sessions_dir,
            chat_lines=[
                {"type": "system", "content": "prompt"},
                {"type": "tool_result", "content": "output"},
            ],
        )
        stats = GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (stats.added, stats.empty) == (0, 1)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0

    def test_missing_chat_history_is_empty(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _make_session(sessions_dir, write_chat=False)
        stats = GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        assert (stats.added, stats.empty) == (0, 1)

    def test_malformed_summary_counts_as_error(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        bad = sessions_dir / "%2Fx" / "broken"
        bad.mkdir(parents=True)
        (bad / "summary.json").write_text("{not json")
        stats = GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        assert stats.errors == 1
        assert stats.added == 0

    def test_malformed_chat_lines_skipped(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        sess = _make_session(sessions_dir, "chatbad", write_chat=False)
        with open(sess / "chat_history.jsonl", "w") as fh:
            fh.write(json.dumps({"type": "user", "content": "good"}) + "\n")
            fh.write("{not json\n")
            fh.write(
                json.dumps(
                    {"type": "assistant", "content": "also good", "model_id": "m"}
                )
                + "\n"
            )
        stats = GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        assert stats.added == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = 'grok_chatbad'"
            ).fetchone()[0]
            == 2
        )

    def test_seq_numbering(self, sessions_dir, migrated_db):
        conn, _ = migrated_db
        _make_session(
            sessions_dir,
            "seq",
            chat_lines=[
                {"type": "user", "content": "a"},
                {"type": "assistant", "content": "b", "model_id": "m"},
                {"type": "user", "content": "c"},
            ],
        )
        GrokExporter(sessions_dir=sessions_dir).export_all(conn)
        rows = conn.execute(
            "SELECT seq FROM messages WHERE session_id = 'grok_seq' ORDER BY seq"
        ).fetchall()
        assert [r["seq"] for r in rows] == [1, 2, 3]
