"""Extended tests for query_utils -- FTS escaping and session ID resolution."""

import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.query_utils import escape_fts_query, resolve_session_id

SCHEMA_PATH = (
    Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
)


class TestEscapeFtsQuery:
    def test_multi_word_wraps_in_quotes(self):
        assert escape_fts_query("hello world") == '"hello world"'

    def test_single_word_unquoted(self):
        assert escape_fts_query("hello") == "hello"

    def test_preserves_and_operator(self):
        result = escape_fts_query("foo AND bar")
        assert result == "foo AND bar"

    def test_preserves_or_operator(self):
        result = escape_fts_query("foo OR bar")
        assert result == "foo OR bar"

    def test_preserves_not_operator(self):
        result = escape_fts_query("foo NOT bar")
        assert result == "foo NOT bar"

    def test_strips_existing_quotes(self):
        assert escape_fts_query('"already quoted"') == '"already quoted"'


class TestResolveSessionId:
    @pytest.fixture
    def db_with_session(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_PATH.read_text())
        conn.execute(
            "INSERT INTO sessions (id, source, project_path, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("abc-123-def-456", "claude_code", "/project", "2024-01-01", "2024-01-01"),
        )
        conn.commit()
        yield conn
        conn.close()

    def test_exact_match(self, db_with_session):
        result = resolve_session_id(db_with_session, "abc-123-def-456")
        assert result == "abc-123-def-456"

    def test_prefix_match(self, db_with_session):
        result = resolve_session_id(db_with_session, "abc-123")
        assert result == "abc-123-def-456"

    def test_no_match_raises(self, db_with_session):
        with pytest.raises(ValueError, match="No sessions found"):
            resolve_session_id(db_with_session, "zzz-nonexistent")
