"""Tests for the Claude Code session exporter.

Validates:
- Constructor accepts optional projects_dir override.
- is_available() reflects directory existence.
- export_all() imports well-formed JSONL sessions into the target DB.
- Session IDs are stable and derived from the filename stem.
- Incremental mode behaviour (fingerprint-based skip).
- Malformed JSONL lines are silently skipped without crashing.
- Content arrays are flattened to text.

NOTE — Known bug: commit_batch() does not persist import_fingerprint to the
sessions table (it only writes the 7 base columns).  As a result, incremental
fingerprint comparison in _process_session_file always sees NULL and never
short-circuits.  The tests in TestClaudeIncremental document actual behaviour.
"""

import json
from pathlib import Path

import pytest

from agent_session_tools.exporters.claude import ClaudeCodeExporter
from agent_session_tools.migrations import migrate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def migrated_db(temp_db):
    """Return a temp_db with all migrations applied so exporter columns exist."""
    conn, db_path = temp_db
    migrate(conn)
    return conn, db_path


@pytest.fixture()
def projects_dir(tmp_path) -> Path:
    """Create a fake Claude projects directory."""
    d = tmp_path / "projects"
    d.mkdir()
    return d


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    """Write a list of dicts as JSONL lines to the given file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_entry(
    role: str = "user",
    content: str | list | None = "Hello",
    uuid: str = "msg-001",
    parent_uuid: str | None = None,
    timestamp: str | None = "2024-06-01T10:00:00Z",
    model: str | None = None,
    git_branch: str | None = None,
) -> dict:
    """Build a single JSONL entry matching Claude Code's format."""
    entry: dict = {
        "uuid": uuid,
        "timestamp": timestamp,
        "message": {
            "role": role,
            "content": content,
        },
    }
    if parent_uuid:
        entry["parentUuid"] = parent_uuid
    if model:
        entry["message"]["model"] = model
    if git_branch:
        entry["gitBranch"] = git_branch
    return entry


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestClaudeCodeConstructor:
    def test_default_projects_dir(self):
        exporter = ClaudeCodeExporter()
        assert exporter.projects_dir == Path.home() / ".claude" / "projects"

    def test_custom_projects_dir(self, tmp_path):
        custom = tmp_path / "my-claude"
        exporter = ClaudeCodeExporter(projects_dir=custom)
        assert exporter.projects_dir == custom

    def test_source_name(self):
        exporter = ClaudeCodeExporter()
        assert exporter.source_name == "claude_code"


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestClaudeIsAvailable:
    def test_available_when_dir_exists(self, projects_dir):
        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        assert exporter.is_available() is True

    def test_not_available_when_dir_missing(self, tmp_path):
        exporter = ClaudeCodeExporter(projects_dir=tmp_path / "nope")
        assert exporter.is_available() is False


# ---------------------------------------------------------------------------
# export_all — happy path
# ---------------------------------------------------------------------------


class TestClaudeExportAll:
    def test_single_session_file(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        entries = [
            _make_entry(
                role="user",
                content="What is TDD?",
                uuid="u1",
                timestamp="2024-06-01T10:00:00Z",
                git_branch="main",
            ),
            _make_entry(
                role="assistant",
                content="Test-driven development.",
                uuid="u2",
                parent_uuid="u1",
                timestamp="2024-06-01T10:00:05Z",
                model="claude-4-opus",
            ),
        ]
        session_file = projects_dir / "my-project" / "agent-session-abc.jsonl"
        _write_jsonl(session_file, entries)

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        stats = exporter.export_all(conn)

        assert stats.added == 1
        assert stats.errors == 0

        # Session row
        session = conn.execute(
            "SELECT * FROM sessions WHERE id = 'agent-session-abc'"
        ).fetchone()
        assert session is not None
        assert session["source"] == "claude_code"
        assert "my-project" in session["project_path"]
        assert session["git_branch"] == "main"
        assert session["created_at"] == "2024-06-01T10:00:00Z"
        assert session["updated_at"] == "2024-06-01T10:00:05Z"

        # Messages
        msgs = conn.execute(
            "SELECT * FROM messages WHERE session_id = 'agent-session-abc' ORDER BY seq"
        ).fetchall()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "What is TDD?"
        assert msgs[1]["model"] == "claude-4-opus"

    def test_multiple_session_files(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        for i in range(3):
            _write_jsonl(
                projects_dir / f"proj-{i}" / f"agent-sess-{i}.jsonl",
                [_make_entry(uuid=f"m-{i}", content=f"Message {i}")],
            )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        stats = exporter.export_all(conn)

        assert stats.added == 3
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 3

    def test_returns_empty_stats_when_unavailable(self, tmp_path, migrated_db):
        conn, _ = migrated_db
        exporter = ClaudeCodeExporter(projects_dir=tmp_path / "nonexistent")
        stats = exporter.export_all(conn)
        assert stats.added == 0
        assert stats.errors == 0


# ---------------------------------------------------------------------------
# Stable session IDs
# ---------------------------------------------------------------------------


class TestClaudeStableSessionIds:
    def test_session_id_is_filename_stem(self, projects_dir, migrated_db):
        """Session ID must be the JSONL filename stem, not a random UUID."""
        conn, _ = migrated_db
        _write_jsonl(
            projects_dir / "project" / "agent-deadbeef-1234.jsonl",
            [_make_entry()],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        row = conn.execute("SELECT id FROM sessions").fetchone()
        assert row["id"] == "agent-deadbeef-1234"

    def test_same_file_yields_same_id_across_runs(self, projects_dir, migrated_db):
        """Re-importing the same file must produce the same session ID."""
        conn, _ = migrated_db
        session_file = projects_dir / "proj" / "agent-stable.jsonl"
        _write_jsonl(session_file, [_make_entry()])

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)

        exporter.export_all(conn, incremental=False)
        id1 = conn.execute("SELECT id FROM sessions").fetchone()["id"]

        exporter.export_all(conn, incremental=False)
        id2 = conn.execute("SELECT id FROM sessions").fetchone()["id"]

        assert id1 == id2 == "agent-stable"


# ---------------------------------------------------------------------------
# Incremental skip (fingerprint-based)
# ---------------------------------------------------------------------------


class TestClaudeIncremental:
    def test_unchanged_file_reimported_as_update(self, projects_dir, migrated_db):
        """Unchanged files are re-imported as 'updated' on second run.

        BUG: commit_batch() does not persist import_fingerprint to the sessions
        table, so _process_session_file always sees NULL when checking the
        stored fingerprint.  The file is re-processed every time incremental
        mode is used.  Once commit_batch is fixed to write import_fingerprint,
        this test should be updated to assert stats2.updated == 0.
        """
        conn, _ = migrated_db

        session_file = projects_dir / "proj" / "agent-inc.jsonl"
        _write_jsonl(session_file, [_make_entry()])

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)

        stats1 = exporter.export_all(conn, incremental=True)
        assert stats1.added == 1

        # Second run -- file unchanged, but fingerprint is not persisted by
        # commit_batch so the exporter cannot detect it as unchanged.
        stats2 = exporter.export_all(conn, incremental=True)
        assert stats2.added == 0
        # Session already exists so it is marked "updated"
        assert stats2.updated == 1

    def test_modified_file_is_reimported(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        session_file = projects_dir / "proj" / "agent-mod.jsonl"
        _write_jsonl(session_file, [_make_entry(content="v1")])

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn, incremental=True)

        # Modify the file (changes mtime and/or size -> new fingerprint)
        _write_jsonl(
            session_file,
            [
                _make_entry(content="v1"),
                _make_entry(uuid="u2", content="v2 -- appended message"),
            ],
        )

        stats2 = exporter.export_all(conn, incremental=True)
        # Should be counted as updated since session already existed
        assert stats2.updated == 1

        msgs = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = 'agent-mod'"
        ).fetchone()[0]
        assert msgs == 2

    def test_non_incremental_always_reimports(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        session_file = projects_dir / "proj" / "agent-full.jsonl"
        _write_jsonl(session_file, [_make_entry()])

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)

        stats1 = exporter.export_all(conn, incremental=False)
        assert stats1.added == 1

        # Second run non-incremental -- same file should be re-imported as update
        stats2 = exporter.export_all(conn, incremental=False)
        assert stats2.updated == 1


# ---------------------------------------------------------------------------
# Content array flattening
# ---------------------------------------------------------------------------


class TestClaudeContentFlattening:
    def test_text_array_flattened(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        content_array = [
            {"type": "text", "text": "First paragraph."},
            {"type": "text", "text": "Second paragraph."},
        ]
        _write_jsonl(
            projects_dir / "proj" / "agent-flat.jsonl",
            [_make_entry(content=content_array)],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        msg = conn.execute(
            "SELECT content FROM messages WHERE session_id = 'agent-flat'"
        ).fetchone()
        assert msg["content"] == "First paragraph.\nSecond paragraph."

    def test_tool_use_in_content_array(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        content_array = [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "name": "grep"},
        ]
        _write_jsonl(
            projects_dir / "proj" / "agent-tool.jsonl",
            [_make_entry(content=content_array)],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        msg = conn.execute(
            "SELECT content FROM messages WHERE session_id = 'agent-tool'"
        ).fetchone()
        assert "[tool:grep]" in msg["content"]

    def test_string_items_in_content_array(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        content_array = ["just a string", {"type": "text", "text": "and a dict"}]
        _write_jsonl(
            projects_dir / "proj" / "agent-strarray.jsonl",
            [_make_entry(content=content_array)],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        msg = conn.execute(
            "SELECT content FROM messages WHERE session_id = 'agent-strarray'"
        ).fetchone()
        assert "just a string" in msg["content"]
        assert "and a dict" in msg["content"]


# ---------------------------------------------------------------------------
# Malformed JSONL handling
# ---------------------------------------------------------------------------


class TestClaudeMalformedJsonl:
    def test_bad_lines_skipped_good_lines_imported(self, projects_dir, migrated_db):
        """Malformed JSONL lines should be silently skipped."""
        conn, _ = migrated_db

        session_file = projects_dir / "proj" / "agent-mixed.jsonl"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        with open(session_file, "w") as f:
            f.write(json.dumps(_make_entry(uuid="good-1", content="valid")) + "\n")
            f.write("{this is not valid json\n")
            f.write(json.dumps(_make_entry(uuid="good-2", content="also valid")) + "\n")

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        stats = exporter.export_all(conn)

        assert stats.added == 1
        msgs = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = 'agent-mixed'"
        ).fetchone()[0]
        # Both good lines should be imported (bad line skipped during parsing)
        assert msgs == 2

    def test_empty_file_produces_no_session(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        session_file = projects_dir / "proj" / "agent-empty.jsonl"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.touch()

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        stats = exporter.export_all(conn)

        assert stats.added == 0
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------


class TestClaudeBatching:
    def test_batch_size_commits_in_chunks(self, projects_dir, migrated_db):
        """All sessions import correctly even when batch_size < total."""
        conn, _ = migrated_db

        for i in range(5):
            _write_jsonl(
                projects_dir / f"proj-{i}" / f"agent-batch-{i}.jsonl",
                [_make_entry(uuid=f"m-{i}", content=f"Batch message {i}")],
            )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        stats = exporter.export_all(conn, batch_size=2)

        assert stats.added == 5
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 5


# ---------------------------------------------------------------------------
# Metadata and timestamps
# ---------------------------------------------------------------------------


class TestClaudeMetadata:
    def test_git_branch_extracted(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        _write_jsonl(
            projects_dir / "proj" / "agent-branch.jsonl",
            [_make_entry(git_branch="feature/cool-thing")],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        session = conn.execute("SELECT git_branch FROM sessions").fetchone()
        assert session["git_branch"] == "feature/cool-thing"

    def test_fingerprint_in_metadata_json(self, projects_dir, migrated_db):
        """The exporter stores the fingerprint inside the metadata JSON column.

        NOTE: import_fingerprint is NOT written to its own column because
        commit_batch() does not include it in its INSERT statement.  The
        fingerprint is available in the metadata JSON blob instead.
        """
        conn, _ = migrated_db

        _write_jsonl(
            projects_dir / "proj" / "agent-fp.jsonl",
            [_make_entry()],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        session = conn.execute("SELECT metadata FROM sessions").fetchone()
        meta = json.loads(session["metadata"])
        assert "fingerprint" in meta
        # Fingerprint format is "{mtime}:{size}"
        assert ":" in meta["fingerprint"]

    def test_import_fingerprint_column_is_null(self, projects_dir, migrated_db):
        """Document that import_fingerprint column is NOT populated.

        BUG: commit_batch() only inserts the 7 base session columns and does
        not include import_fingerprint.  This test documents the current
        (broken) behaviour.  When commit_batch is fixed, this test should be
        updated to assert the column IS populated.
        """
        conn, _ = migrated_db

        _write_jsonl(
            projects_dir / "proj" / "agent-fp2.jsonl",
            [_make_entry()],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        session = conn.execute("SELECT import_fingerprint FROM sessions").fetchone()
        # Currently always NULL due to commit_batch not writing this column
        assert session["import_fingerprint"] is None

    def test_message_uuid_preserved(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        _write_jsonl(
            projects_dir / "proj" / "agent-uuid.jsonl",
            [_make_entry(uuid="my-custom-uuid-123")],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        msg = conn.execute("SELECT id FROM messages").fetchone()
        assert msg["id"] == "my-custom-uuid-123"

    def test_seq_numbering(self, projects_dir, migrated_db):
        conn, _ = migrated_db

        _write_jsonl(
            projects_dir / "proj" / "agent-seq.jsonl",
            [
                _make_entry(uuid="a", content="first"),
                _make_entry(uuid="b", content="second"),
                _make_entry(uuid="c", content="third"),
            ],
        )

        exporter = ClaudeCodeExporter(projects_dir=projects_dir)
        exporter.export_all(conn)

        rows = conn.execute(
            "SELECT seq FROM messages WHERE session_id = 'agent-seq' ORDER BY seq"
        ).fetchall()
        assert [r["seq"] for r in rows] == [1, 2, 3]
