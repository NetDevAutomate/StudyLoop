"""Tests for agent_session_tools.query_logic — the main business logic layer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_session_tools.migrations import migrate
from agent_session_tools.query_logic import (
    _generate_branch_context,
    _generate_resume_context,
    _generate_summary_context,
    check_size,
    estimate_tokens,
    export_context,
    get_connection,
    list_sessions,
    search,
    show_session,
    stats,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def schema_path() -> Path:
    return Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"


@pytest.fixture
def db(schema_path: Path):
    """In-memory database with schema + all migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(schema_path) as f:
        conn.executescript(f.read())
    migrate(conn)
    yield conn
    conn.close()


def _insert_session(conn: sqlite3.Connection, **overrides) -> dict:
    """Insert a session row and return its data dict."""
    defaults = {
        "id": "session-aabbccdd11223344",
        "source": "claude_code",
        "project_path": "/home/user/my-project",
        "git_branch": "main",
        "created_at": "2024-03-01T09:00:00",
        "updated_at": "2024-03-01T12:00:00",
        "metadata": None,
    }
    data = {**defaults, **overrides}
    conn.execute(
        "INSERT INTO sessions (id, source, project_path, git_branch, created_at, updated_at, metadata) "
        "VALUES (:id, :source, :project_path, :git_branch, :created_at, :updated_at, :metadata)",
        data,
    )
    conn.commit()
    return data


def _insert_message(conn: sqlite3.Connection, **overrides) -> dict:
    """Insert a message row and return its data dict."""
    defaults = {
        "id": "msg-001",
        "session_id": "session-aabbccdd11223344",
        "parent_id": None,
        "role": "user",
        "content": "How do I write unit tests?",
        "model": None,
        "timestamp": "2024-03-01T09:01:00",
        "metadata": None,
    }
    data = {**defaults, **overrides}
    conn.execute(
        "INSERT INTO messages (id, session_id, parent_id, role, content, model, timestamp, metadata) "
        "VALUES (:id, :session_id, :parent_id, :role, :content, :model, :timestamp, :metadata)",
        data,
    )
    conn.commit()
    return data


@pytest.fixture
def populated_db(db):
    """DB with one session and a pair of messages (user + assistant)."""
    _insert_session(db)
    _insert_message(db, id="msg-001", role="user", content="How do I write unit tests?")
    _insert_message(
        db,
        id="msg-002",
        role="assistant",
        content="Use pytest. Write small, focused tests.",
        timestamp="2024-03-01T09:02:00",
    )
    return db


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------


class TestGetConnection:
    def test_returns_connection_with_row_factory(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()

    def test_uses_provided_path(self, tmp_path: Path):
        db_path = tmp_path / "explicit.db"
        conn = get_connection(db_path)
        try:
            # SQLite creates the file on connect
            assert db_path.exists()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_finds_matching_content(self, populated_db, capsys):
        search(populated_db, "pytest", output_format="table")
        captured = capsys.readouterr()
        assert "pytest" in captured.out

    def test_search_table_format_shows_source(self, populated_db, capsys):
        search(populated_db, "unit tests", output_format="table")
        captured = capsys.readouterr()
        assert "claude_code" in captured.out

    def test_search_json_format_returns_valid_json(self, populated_db, capsys):
        search(populated_db, "pytest", output_format="json")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "session_id" in data[0]
        assert "role" in data[0]
        assert "preview" in data[0]

    def test_search_json_includes_full_content(self, populated_db, capsys):
        search(populated_db, "pytest", output_format="json")
        data = json.loads(capsys.readouterr().out)
        assert "full_content" in data[0]

    def test_search_markdown_format_has_header(self, populated_db, capsys):
        search(populated_db, "pytest", output_format="markdown")
        captured = capsys.readouterr()
        assert "# Search Results" in captured.out
        assert "**Query:**" in captured.out

    def test_search_no_results_produces_no_output_for_table(self, populated_db, capsys):
        search(populated_db, "xyznonexistentterm", output_format="table")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_search_no_results_json_is_empty_list(self, populated_db, capsys):
        search(populated_db, "xyznonexistentterm", output_format="json")
        data = json.loads(capsys.readouterr().out)
        assert data == []

    def test_search_limit_respected(self, db, capsys):
        _insert_session(db)
        for i in range(5):
            _insert_message(
                db,
                id=f"msg-{i}",
                role="user",
                content=f"pytest test number {i}",
                timestamp=f"2024-03-01T09:0{i}:00",
            )
        search(db, "pytest", limit=2, output_format="json")
        data = json.loads(capsys.readouterr().out)
        assert len(data) <= 2

    def test_search_with_date_filter(self, populated_db, capsys):
        # since date after the only message — should find nothing
        search(populated_db, "pytest", since="2025-01-01", output_format="json")
        data = json.loads(capsys.readouterr().out)
        assert data == []


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_lists_all_sessions_table_format(self, populated_db, capsys):
        list_sessions(populated_db, output_format="table")
        out = capsys.readouterr().out
        assert "claude_code" in out

    def test_filters_by_source(self, db, capsys):
        _insert_session(db, id="s1", source="claude_code")
        _insert_session(
            db, id="s2", source="kiro_cli", updated_at="2024-03-01T12:01:00"
        )
        list_sessions(db, source="kiro_cli", output_format="json")
        data = json.loads(capsys.readouterr().out)
        assert all(s["source"] == "kiro_cli" for s in data)

    def test_json_format_structure(self, populated_db, capsys):
        list_sessions(populated_db, output_format="json")
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        first = data[0]
        assert "id" in first
        assert "source" in first
        assert "project_path" in first
        assert "updated_at" in first

    def test_markdown_format_has_header(self, populated_db, capsys):
        list_sessions(populated_db, output_format="markdown")
        out = capsys.readouterr().out
        assert "# Session List" in out

    def test_full_ids_flag_shows_complete_id(self, populated_db, capsys):
        list_sessions(populated_db, output_format="table", full_ids=True)
        out = capsys.readouterr().out
        assert "session-aabbccdd11223344" in out

    def test_truncated_ids_by_default(self, populated_db, capsys):
        list_sessions(populated_db, output_format="table", full_ids=False)
        out = capsys.readouterr().out
        # Default truncation appends "..."
        assert "..." in out

    def test_limit_respected(self, db, capsys):
        for i in range(5):
            _insert_session(
                db,
                id=f"session-{i:04d}",
                updated_at=f"2024-03-0{i + 1}T12:00:00",
            )
        list_sessions(db, limit=2, output_format="json")
        data = json.loads(capsys.readouterr().out)
        assert len(data) <= 2

    def test_date_filter_excludes_old_sessions(self, populated_db, capsys):
        list_sessions(populated_db, since="2025-01-01", output_format="json")
        data = json.loads(capsys.readouterr().out)
        assert data == []


# ---------------------------------------------------------------------------
# show_session
# ---------------------------------------------------------------------------


class TestShowSession:
    def test_shows_session_messages(self, populated_db, capsys):
        show_session(populated_db, "session-aabbccdd11223344")
        out = capsys.readouterr().out
        assert "session-aabbccdd11223344" in out
        assert "How do I write unit tests?" in out

    def test_shows_role_labels(self, populated_db, capsys):
        show_session(populated_db, "session-aabbccdd11223344")
        out = capsys.readouterr().out
        assert "USER" in out
        assert "ASSISTANT" in out

    def test_partial_id_resolves(self, populated_db, capsys):
        # First 8 chars of session ID are unique here
        show_session(populated_db, "session-aabb")
        out = capsys.readouterr().out
        assert "How do I write unit tests?" in out

    def test_not_found_prints_error(self, populated_db, capsys):
        show_session(populated_db, "nonexistent-session-id")
        out = capsys.readouterr().out
        assert "❌" in out

    def test_session_with_no_messages_prints_error(self, db, capsys):
        _insert_session(db, id="empty-session-0001")
        show_session(db, "empty-session-0001")
        out = capsys.readouterr().out
        assert "❌" in out

    def test_content_truncated_at_2000_chars(self, db, capsys):
        _insert_session(db)
        long_content = "x" * 3000
        _insert_message(db, role="user", content=long_content)
        show_session(db, "session-aabbccdd11223344")
        out = capsys.readouterr().out
        # Should not contain the full 3000 chars — truncated at 2000
        assert "x" * 2001 not in out


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_plain_text_stats_shows_sections(self, populated_db, capsys):
        stats(populated_db, use_rich=False)
        out = capsys.readouterr().out
        assert "DATABASE OVERVIEW" in out
        assert "SESSIONS BY SOURCE" in out
        assert "MESSAGES BY ROLE" in out
        assert "TOP PROJECTS BY MESSAGE COUNT" in out

    def test_plain_text_stats_shows_source_count(self, populated_db, capsys):
        stats(populated_db, use_rich=False)
        out = capsys.readouterr().out
        assert "claude_code" in out

    def test_plain_text_stats_shows_size(self, populated_db, capsys):
        stats(populated_db, use_rich=False)
        out = capsys.readouterr().out
        assert "Size:" in out

    def test_rich_stats_does_not_raise(self, populated_db):
        # Rich output goes to the console object — just confirm no exception
        stats(populated_db, use_rich=True)


# ---------------------------------------------------------------------------
# check_size
# ---------------------------------------------------------------------------


class TestCheckSize:
    def test_returns_zero_for_ok_db(self, tmp_path: Path, schema_path: Path):
        db_path = tmp_path / "small.db"
        conn = sqlite3.connect(db_path)
        with open(schema_path) as f:
            conn.executescript(f.read())
        conn.close()
        result = check_size(db_path)
        assert result == 0

    def test_output_contains_file_path(self, tmp_path: Path, capsys):
        db_path = tmp_path / "check.db"
        db_path.touch()
        check_size(db_path)
        out = capsys.readouterr().out
        assert str(db_path) in out

    def test_output_shows_status(self, tmp_path: Path, capsys):
        db_path = tmp_path / "check.db"
        db_path.touch()
        check_size(db_path)
        out = capsys.readouterr().out
        assert "Status:" in out

    def test_returns_one_when_above_warning_threshold(self, tmp_path: Path):
        db_path = tmp_path / "large.db"
        # Write >100 MB to exceed the default warning threshold
        with (
            patch(
                "agent_session_tools.query_logic.get_db_size",
                return_value={
                    "mb": 200.0,
                    "formatted": "200.00 MB",
                    "bytes": 209715200,
                },
            ),
            patch(
                "agent_session_tools.query_logic.check_thresholds",
                return_value={
                    "status": "warning",
                    "message": "exceeds warning",
                    "warning_mb": 100,
                    "critical_mb": 500,
                },
            ),
        ):
            result = check_size(db_path)
        assert result == 1


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_approximate_count(self):
        # 40 chars ≈ 10 tokens via EstimateCounter (4 chars/token)
        result = estimate_tokens("a" * 40, accurate=False)
        assert result == 10

    def test_non_empty_returns_positive(self):
        assert estimate_tokens("hello world", accurate=False) > 0


# ---------------------------------------------------------------------------
# export_context
# ---------------------------------------------------------------------------


class TestExportContext:
    def test_not_found_session_prints_error(self, populated_db, capsys):
        export_context(populated_db, "nonexistent-session")
        out = capsys.readouterr().out
        assert "❌" in out

    def test_markdown_format_output(self, populated_db, capsys):
        export_context(populated_db, "session-aabbccdd11223344", format_type="markdown")
        out = capsys.readouterr().out
        assert "# Session Context:" in out or "# Context:" in out

    def test_compressed_format_output(self, populated_db, capsys):
        export_context(
            populated_db, "session-aabbccdd11223344", format_type="compressed"
        )
        out = capsys.readouterr().out
        assert "# Context:" in out

    def test_xml_format_output(self, populated_db, capsys):
        export_context(populated_db, "session-aabbccdd11223344", format_type="xml")
        out = capsys.readouterr().out
        assert "<?xml" in out

    def test_summary_format_output(self, populated_db, capsys):
        export_context(populated_db, "session-aabbccdd11223344", format_type="summary")
        out = capsys.readouterr().out
        assert "# Session Summary:" in out

    def test_context_only_format_output(self, populated_db, capsys):
        export_context(
            populated_db, "session-aabbccdd11223344", format_type="context-only"
        )
        out = capsys.readouterr().out
        assert "# Technical Context:" in out

    def test_tool_messages_excluded_by_default(self, db, capsys):
        _insert_session(db)
        _insert_message(db, id="m1", role="user", content="question")
        _insert_message(db, id="m2", role="tool_use", content="tool call here")
        _insert_message(db, id="m3", role="assistant", content="answer")
        export_context(db, "session-aabbccdd11223344", format_type="markdown")
        out = capsys.readouterr().out
        assert "tool call here" not in out

    def test_tool_messages_included_with_flag(self, db, capsys):
        _insert_session(db)
        _insert_message(db, id="m1", role="user", content="question")
        _insert_message(db, id="m2", role="tool_use", content="tool call here")
        _insert_message(db, id="m3", role="assistant", content="answer")
        export_context(
            db,
            "session-aabbccdd11223344",
            format_type="markdown",
            include_tools=True,
        )
        out = capsys.readouterr().out
        # The markdown formatter renders tool messages as "*[tool_use]*" markers,
        # not their raw content — the include_tools flag keeps them in the output.
        assert "*[tool_use]*" in out

    def test_only_code_filter_excludes_plain_messages(self, db, capsys):
        _insert_session(db)
        _insert_message(db, id="m1", role="user", content="What is Python?")
        _insert_message(
            db,
            id="m2",
            role="assistant",
            content="Python is a language.\n```python\nprint('hi')\n```",
        )
        export_context(
            db, "session-aabbccdd11223344", format_type="markdown", only_code=True
        )
        out = capsys.readouterr().out
        # Plain user message has no code — should be filtered out
        assert "What is Python?" not in out
        # Message with code block should be kept
        assert "print('hi')" in out

    def test_last_n_returns_most_recent_messages(self, db, capsys):
        """last_n selects the N most recent messages, ordered chronologically."""
        _insert_session(db)
        for i in range(6):
            _insert_message(
                db,
                id=f"m{i}",
                role="user",
                content=f"message number {i}",
                timestamp=f"2024-03-01T09:0{i}:00",
            )
        export_context(db, "session-aabbccdd11223344", format_type="markdown", last_n=2)
        out = capsys.readouterr().out
        # Should contain the last 2 messages (4 and 5), not earlier ones
        assert "message number 5" in out
        assert "message number 4" in out
        assert "message number 0" not in out

    def test_max_tokens_triggers_truncation(self, populated_db, capsys):
        # A very small token limit forces truncation of any real content
        export_context(
            populated_db,
            "session-aabbccdd11223344",
            format_type="markdown",
            max_tokens=5,
        )
        out = capsys.readouterr().out
        assert (
            "Truncated" in out or len(out) < 1000
        )  # either truncation notice or short

    def test_no_messages_in_session_prints_error(self, db, capsys):
        _insert_session(db)
        export_context(db, "session-aabbccdd11223344", format_type="markdown")
        out = capsys.readouterr().out
        assert "❌" in out

    def test_invalid_profile_prints_error(self, populated_db, capsys):
        with patch(
            "agent_session_tools.query_logic.load_profile",
            side_effect=FileNotFoundError("profile not found"),
        ):
            export_context(
                populated_db,
                "session-aabbccdd11223344",
                format_type="markdown",
                profile="nonexistent-profile",
            )
        out = capsys.readouterr().out
        assert "❌" in out

    def test_profile_applies_defaults(self, populated_db, capsys):
        fake_profile = {
            "name": "test-profile",
            "format": "xml",
            "defaults": {"max_tokens": 100000, "last_n": None},
        }
        with patch(
            "agent_session_tools.query_logic.load_profile", return_value=fake_profile
        ):
            export_context(
                populated_db,
                "session-aabbccdd11223344",
                profile="test-profile",
            )
        out = capsys.readouterr().out
        assert "<?xml" in out


# ---------------------------------------------------------------------------
# continue_session
# ---------------------------------------------------------------------------


class TestContinueSession:
    """Tests for continue_session via the _generate_* private helpers it delegates to."""

    def test_not_found_prints_error(self, populated_db, capsys):
        from agent_session_tools.query_logic import continue_session

        continue_session(populated_db, "nonexistent-session")
        out = capsys.readouterr().out
        assert "❌" in out

    def test_resume_type_produces_output(self, populated_db, capsys):
        from agent_session_tools.query_logic import continue_session

        continue_session(
            populated_db, "session-aabbccdd11223344", continuation_type="resume"
        )
        out = capsys.readouterr().out
        assert "# Resume Session:" in out

    def test_branch_type_produces_output(self, populated_db, capsys):
        from agent_session_tools.query_logic import continue_session

        continue_session(
            populated_db, "session-aabbccdd11223344", continuation_type="branch"
        )
        out = capsys.readouterr().out
        assert "# Branch Session:" in out

    def test_summarize_type_produces_output(self, populated_db, capsys):
        """continue_session with summarize generates a summary context."""
        from agent_session_tools.query_logic import continue_session

        continue_session(
            populated_db, "session-aabbccdd11223344", continuation_type="summarize"
        )
        out = capsys.readouterr().out
        assert "# Session Summary:" in out

    def test_unknown_type_defaults_to_resume(self, populated_db, capsys):
        from agent_session_tools.query_logic import continue_session

        continue_session(
            populated_db, "session-aabbccdd11223344", continuation_type="invalid"
        )
        out = capsys.readouterr().out
        assert "# Resume Session:" in out

    def test_session_with_no_messages_prints_error(self, db, capsys):
        from agent_session_tools.query_logic import continue_session

        _insert_session(db)
        continue_session(db, "session-aabbccdd11223344")
        out = capsys.readouterr().out
        assert "❌" in out


# ---------------------------------------------------------------------------
# _generate_resume_context (private helper — tested directly for logic coverage)
# ---------------------------------------------------------------------------


class TestGenerateResumeContext:
    def _make_row(self, role: str, content: str, seq: int = 0) -> dict:
        """Return a dict-like object that supports row["key"] access."""
        return {"role": role, "content": content, "seq": seq}

    def test_includes_last_user_request(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [
            {"role": "user", "content": "First question", "seq": 0},
            {"role": "user", "content": "Second question", "seq": 1},
        ]
        result = _generate_resume_context(session, messages, max_tokens=10000)
        assert "Second question" in result
        assert "## Last Request" in result

    def test_includes_last_assistant_response(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [
            {"role": "user", "content": "question", "seq": 0},
            {"role": "assistant", "content": "First answer.", "seq": 1},
            {"role": "assistant", "content": "Second answer.", "seq": 2},
        ]
        result = _generate_resume_context(session, messages, max_tokens=10000)
        assert "Second answer." in result

    def test_extracts_code_blocks(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [
            {
                "role": "assistant",
                "content": "Here is code:\n```python\nprint('hello')\n```",
                "seq": 0,
            }
        ]
        result = _generate_resume_context(session, messages, max_tokens=10000)
        assert "## Key Code" in result
        assert "print('hello')" in result

    def test_extracts_todo_items(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [
            {"role": "user", "content": "TODO: refactor the auth module", "seq": 0}
        ]
        result = _generate_resume_context(session, messages, max_tokens=10000)
        assert "## Outstanding Items" in result
        assert "TODO: refactor the auth module" in result

    def test_extracts_decisions(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [
            {
                "role": "assistant",
                "content": "We decided to use sqlite for storage.",
                "seq": 0,
            }
        ]
        result = _generate_resume_context(session, messages, max_tokens=10000)
        assert "## Key Decisions" in result

    def test_token_count_appended(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [{"role": "user", "content": "short", "seq": 0}]
        result = _generate_resume_context(session, messages, max_tokens=10000)
        assert "tokens" in result.lower()

    def test_truncated_when_exceeds_max_tokens(self):
        session = {"project_path": "/test", "id": "s1"}
        # Giant content to force truncation
        huge_content = "word " * 5000
        messages = [{"role": "user", "content": huge_content, "seq": 0}]
        result = _generate_resume_context(session, messages, max_tokens=100)
        # Result should be shorter than the original content
        assert len(result) < len(huge_content)

    def test_none_project_path_shows_unknown(self):
        session = {"project_path": None, "id": "s1"}
        messages = [{"role": "user", "content": "q", "seq": 0}]
        result = _generate_resume_context(session, messages, max_tokens=10000)
        assert "Unknown" in result

    def test_no_user_messages_still_returns(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [{"role": "assistant", "content": "unsolicited info", "seq": 0}]
        result = _generate_resume_context(session, messages, max_tokens=10000)
        assert "# Resume Session:" in result


# ---------------------------------------------------------------------------
# _generate_branch_context
# ---------------------------------------------------------------------------


class TestGenerateBranchContext:
    def test_header_includes_project_path(self):
        session = {"project_path": "/test/repo", "id": "s1"}
        messages = [
            {"role": "assistant", "content": "We implemented a new feature.", "seq": 0}
        ]
        result = _generate_branch_context(session, messages, max_tokens=10000)
        assert "# Branch Session: /test/repo" in result

    def test_key_points_extracted_from_assistant_messages(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [
            {
                "role": "assistant",
                "content": "The authentication module was refactored.",
                "seq": 0,
            }
        ]
        result = _generate_branch_context(session, messages, max_tokens=10000)
        assert "authentication module" in result

    def test_user_messages_not_included_as_key_points(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [
            {
                "role": "user",
                "content": "This user content should not appear.",
                "seq": 0,
            },
            {"role": "assistant", "content": "We solved the problem.", "seq": 1},
        ]
        result = _generate_branch_context(session, messages, max_tokens=10000)
        assert "user content should not appear" not in result

    def test_limits_to_last_five_points(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [
            {"role": "assistant", "content": f"Point {i} was completed.", "seq": i}
            for i in range(8)
        ]
        result = _generate_branch_context(session, messages, max_tokens=10000)
        assert "Point 7 was completed" in result
        # Points 0-2 should be dropped (only last 5 kept)
        assert "Point 2 was completed" not in result

    def test_branch_point_section_present(self):
        session = {"project_path": "/test", "id": "s1"}
        messages = [{"role": "assistant", "content": "Done.", "seq": 0}]
        result = _generate_branch_context(session, messages, max_tokens=10000)
        assert "## Branch Point" in result

    def test_none_project_path_shows_unknown(self):
        session = {"project_path": None, "id": "s1"}
        messages = [{"role": "assistant", "content": "Finished.", "seq": 0}]
        result = _generate_branch_context(session, messages, max_tokens=10000)
        assert "Unknown" in result


# ---------------------------------------------------------------------------
# _generate_summary_context
# ---------------------------------------------------------------------------


class TestGenerateSummaryContext:
    def test_header_includes_project_path(self):
        session = {
            "project_path": "/home/user/app",
            "id": "s1",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-02",
        }
        messages = [{"role": "user", "content": "goal", "seq": 0}]
        result = _generate_summary_context(session, messages, max_tokens=10000)
        assert "# Session Summary: /home/user/app" in result

    def test_goal_from_first_user_message(self):
        session = {
            "project_path": "/test",
            "id": "s1",
            "created_at": "",
            "updated_at": "",
        }
        messages = [
            {"role": "user", "content": "Build a login system.", "seq": 0},
            {"role": "user", "content": "Later question", "seq": 1},
        ]
        result = _generate_summary_context(session, messages, max_tokens=10000)
        assert "**Goal:** Build a login system." in result
        assert "Later question" not in result  # only first user message used

    def test_outcomes_section_present(self):
        session = {
            "project_path": "/test",
            "id": "s1",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-02",
        }
        messages = [{"role": "user", "content": "task", "seq": 0}]
        result = _generate_summary_context(session, messages, max_tokens=10000)
        assert "## Outcomes" in result
        assert "1 total messages" in result

    def test_counts_code_blocks(self):
        session = {
            "project_path": "/test",
            "id": "s1",
            "created_at": "",
            "updated_at": "",
        }
        messages = [
            {"role": "user", "content": "task", "seq": 0},
            {
                "role": "assistant",
                "content": "Here:\n```python\ncode\n```",
                "seq": 1,
            },
        ]
        result = _generate_summary_context(session, messages, max_tokens=10000)
        assert "1 code blocks" in result

    def test_no_user_messages_still_returns(self):
        session = {
            "project_path": "/test",
            "id": "s1",
            "created_at": "",
            "updated_at": "",
        }
        messages = [{"role": "assistant", "content": "unsolicited", "seq": 0}]
        result = _generate_summary_context(session, messages, max_tokens=10000)
        assert "# Session Summary:" in result
        assert "**Goal:**" not in result

    def test_token_count_appended(self):
        session = {
            "project_path": "/test",
            "id": "s1",
            "created_at": "",
            "updated_at": "",
        }
        messages = [{"role": "user", "content": "task", "seq": 0}]
        result = _generate_summary_context(session, messages, max_tokens=10000)
        assert "tokens" in result.lower()
