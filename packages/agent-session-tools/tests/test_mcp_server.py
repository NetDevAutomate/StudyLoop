"""Tests for the MCP server tool functions.

Tests the tool functions directly rather than through the MCP protocol,
since the functions are regular Python that FastMCP wraps.
"""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(
    not pytest.importorskip("fastmcp", reason="fastmcp not installed"),
    reason="fastmcp not installed",
)


@pytest.fixture
def mcp_db(tmp_path):
    """Create a populated test database for MCP tool testing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    schema_path = (
        Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    )
    with open(schema_path) as f:
        conn.executescript(f.read())

    from agent_session_tools.migrations import migrate

    migrate(conn)

    # Insert test sessions
    conn.execute(
        "INSERT INTO sessions (id, source, project_path, git_branch, "
        "created_at, updated_at, session_type) "
        "VALUES ('sess-auth-001', 'claude_code', '/projects/webapp', "
        "'feat/auth', '2026-01-01T10:00:00', '2026-01-01T12:00:00', 'work')"
    )
    conn.execute(
        "INSERT INTO sessions (id, source, project_path, git_branch, "
        "created_at, updated_at, session_type) "
        "VALUES ('sess-debug-002', 'kiro_cli', '/projects/api', "
        "'main', '2026-01-02T09:00:00', '2026-01-02T11:00:00', 'work')"
    )

    # Insert test messages (seq populated for ordering)
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
        "VALUES ('msg-1', 'sess-auth-001', 'user', "
        "'How do I add authentication middleware?', "
        "'2026-01-01T10:00:00', 1)"
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
        "VALUES ('msg-2', 'sess-auth-001', 'assistant', "
        "'Use the JWT middleware pattern for auth.', "
        "'2026-01-01T10:01:00', 2)"
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
        "VALUES ('msg-3', 'sess-debug-002', 'user', "
        "'Getting a TypeError in the API endpoint', "
        "'2026-01-02T09:00:00', 1)"
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
        "VALUES ('msg-4', 'sess-debug-002', 'assistant', "
        "'The error is caused by passing None to the serializer.', "
        "'2026-01-02T09:01:00', 2)"
    )

    # Message with a secret for scrub testing
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
        "VALUES ('msg-5', 'sess-auth-001', 'user', "
        "'My key is AKIAIOSFODNN7EXAMPLE', "  # pragma: allowlist secret
        "'2026-01-01T10:02:00', 3)"
    )

    # Insert file_references for hotspot testing
    conn.execute(
        "INSERT INTO file_references "
        "(session_id, message_id, file_path, tool_name, timestamp) "
        "VALUES ('sess-auth-001', 'msg-2', '/src/auth.py', 'Read', "
        "'2026-01-01T10:01:00')"
    )
    conn.execute(
        "INSERT INTO file_references "
        "(session_id, message_id, file_path, tool_name, timestamp) "
        "VALUES ('sess-auth-001', 'msg-2', '/src/middleware.py', 'Read', "
        "'2026-01-01T10:01:00')"
    )
    conn.execute(
        "INSERT INTO file_references "
        "(session_id, message_id, file_path, tool_name, timestamp) "
        "VALUES ('sess-debug-002', 'msg-4', '/src/auth.py', 'Edit', "
        "'2026-01-02T09:01:00')"
    )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mock_db_path(mcp_db):
    """Patch _get_db_path to return our test database."""
    with patch("agent_session_tools.mcp_server._get_db_path", return_value=mcp_db):
        yield mcp_db


def _get_tools():
    """Import tool functions from the MCP server."""
    import asyncio

    from agent_session_tools.mcp_server import mcp

    tools = asyncio.run(mcp._list_tools())
    return {tool.name: tool.fn for tool in tools}  # type: ignore[attr-defined]


class TestSessionSearch:
    def test_search_returns_results(self, mock_db_path):
        tools = _get_tools()
        results = tools["session_search"](query="authentication")
        assert len(results) > 0
        assert results[0]["session_id"] == "sess-auth-001"

    def test_search_no_results(self, mock_db_path):
        tools = _get_tools()
        results = tools["session_search"](query="nonexistent_xyz_term")
        assert len(results) == 0

    def test_search_with_source_filter(self, mock_db_path):
        tools = _get_tools()
        results = tools["session_search"](
            query="error OR authentication", source="kiro_cli"
        )
        for r in results:
            assert r["source"] == "kiro_cli"

    def test_search_with_project_filter(self, mock_db_path):
        tools = _get_tools()
        results = tools["session_search"](query="middleware", project="webapp")
        assert len(results) > 0
        assert "webapp" in results[0]["project_path"]

    def test_search_respects_limit(self, mock_db_path):
        tools = _get_tools()
        results = tools["session_search"](query="the", limit=1)
        assert len(results) <= 1


class TestSessionList:
    def test_list_returns_sessions(self, mock_db_path):
        tools = _get_tools()
        results = tools["session_list"]()
        assert len(results) == 2
        # Ordered by updated_at DESC
        assert results[0]["id"] == "sess-debug-002"
        assert results[1]["id"] == "sess-auth-001"

    def test_list_with_source_filter(self, mock_db_path):
        tools = _get_tools()
        results = tools["session_list"](source="claude_code")
        assert len(results) == 1
        assert results[0]["source"] == "claude_code"

    def test_list_with_project_filter(self, mock_db_path):
        tools = _get_tools()
        results = tools["session_list"](project="api")
        assert len(results) == 1
        assert "api" in results[0]["project_path"]

    def test_list_pagination(self, mock_db_path):
        tools = _get_tools()
        page1 = tools["session_list"](limit=1, offset=0)
        page2 = tools["session_list"](limit=1, offset=1)
        assert len(page1) == 1
        assert len(page2) == 1
        assert page1[0]["id"] != page2[0]["id"]


class TestSessionShow:
    def test_show_returns_session_and_messages(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_show"](session_id="sess-auth-001")
        assert "session" in result
        assert "messages" in result
        assert result["session"]["id"] == "sess-auth-001"
        assert result["message_count"] == 3  # msg-1, msg-2, msg-5

    def test_show_partial_id(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_show"](session_id="sess-auth")
        assert result["session"]["id"] == "sess-auth-001"

    def test_show_nonexistent_session(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_show"](session_id="nonexistent-session-id")
        assert "error" in result

    def test_show_messages_ordered(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_show"](session_id="sess-auth-001")
        messages = result["messages"]
        assert messages[0]["role"] == "user"
        assert "authentication" in messages[0]["content"]


class TestSessionStats:
    def test_stats_returns_structure(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_stats"]()
        assert result["total_sessions"] == 2
        assert result["total_messages"] == 5
        assert "sources" in result
        assert "date_range" in result
        assert "storage" in result

    def test_stats_sources_breakdown(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_stats"]()
        sources = {s["source"]: s["count"] for s in result["sources"]}
        assert sources["claude_code"] == 1
        assert sources["kiro_cli"] == 1

    def test_stats_storage_size(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_stats"]()
        assert result["storage"]["bytes"] > 0
        assert result["storage"]["mb"] >= 0


class TestServerCreation:
    def test_server_has_correct_name(self):
        from agent_session_tools.mcp_server import mcp

        assert mcp.name == "session-db"

    def test_server_has_all_tools(self):
        import asyncio

        from agent_session_tools.mcp_server import mcp

        tools = asyncio.run(mcp._list_tools())
        tool_names = {t.name for t in tools}
        expected = {
            "session_search",
            "session_list",
            "session_show",
            "session_context",
            "session_stats",
            "session_clean",
            "session_hotspots",
        }
        assert tool_names == expected

    def test_main_without_fastmcp_shows_error(self):
        """Test that main() gives a clear error when fastmcp is not installed."""
        with patch("agent_session_tools.mcp_server._HAS_FASTMCP", False):
            from agent_session_tools.mcp_server import main

            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


class TestSessionClean:
    def test_clean_dry_run_reports_findings(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_clean"](dry_run=True)
        assert result["dry_run"] is True
        assert result["messages_scanned"] == 5
        assert result["total_findings"] >= 1  # At least the AWS key
        assert "aws_access_key" in result["findings_by_type"]

    def test_clean_dry_run_does_not_modify(self, mock_db_path):
        tools = _get_tools()
        tools["session_clean"](dry_run=True)

        # Verify original still there
        conn = sqlite3.connect(mock_db_path)
        content = conn.execute(
            "SELECT content FROM messages WHERE id = 'msg-5'"
        ).fetchone()[0]
        conn.close()
        assert "AKIAIOSFODNN7EXAMPLE" in content  # pragma: allowlist secret

    def test_clean_execute_scrubs(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_clean"](dry_run=False)
        assert result["dry_run"] is False
        assert result.get("messages_updated", 0) >= 1

        conn = sqlite3.connect(mock_db_path)
        content = conn.execute(
            "SELECT content FROM messages WHERE id = 'msg-5'"
        ).fetchone()[0]
        conn.close()
        assert "AKIAIOSFODNN7EXAMPLE" not in content  # pragma: allowlist secret
        assert "[AWS_ACCESS_KEY-" in content

    def test_clean_specific_session(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_clean"](session_id="sess-auth-001", dry_run=True)
        assert result["messages_scanned"] == 3  # Only sess-auth-001 messages


class TestSessionHotspots:
    def test_hotspots_returns_ranked_files(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_hotspots"](days=0)  # 0 = all time
        assert len(result) > 0
        # auth.py has 2 refs (Read + Edit), should be first
        assert result[0]["file_path"] == "/src/auth.py"
        assert result[0]["ref_count"] == 2

    def test_hotspots_filter_by_project(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_hotspots"](project="/projects/webapp", days=0)
        paths = [r["file_path"] for r in result]
        assert "/src/auth.py" in paths
        assert "/src/middleware.py" in paths

    def test_hotspots_empty_when_no_data(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_hotspots"](project="nonexistent", days=0)
        assert result == []

    def test_hotspots_respects_limit(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_hotspots"](limit=1, days=0)
        assert len(result) == 1


class TestSessionContext:
    def test_context_compressed_default(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_context"](session_id="sess-auth-001")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_context_summary_format(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_context"](session_id="sess-auth-001", format="summary")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_context_markdown_format(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_context"](session_id="sess-auth-001", format="markdown")
        assert isinstance(result, str)
        # markdown format should include session ID or project path
        assert "sess-auth-001" in result or "/projects/webapp" in result

    def test_context_xml_format(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_context"](session_id="sess-auth-001", format="xml")
        assert isinstance(result, str)
        # xml format should have structured tags
        assert "<" in result and ">" in result

    def test_context_only_format(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_context"](
            session_id="sess-auth-001", format="context_only"
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_context_nonexistent_session(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_context"](session_id="nonexistent-xyz-session")
        assert isinstance(result, str)
        # Should return an error string, not raise
        assert "error" in result.lower() or "not found" in result.lower()

    def test_context_respects_token_limit(self, mock_db_path):
        tools = _get_tools()
        # Use max_tokens=5 (≈20 chars) to guarantee truncation on small test data
        short = tools["session_context"](session_id="sess-auth-001", max_tokens=5)
        long = tools["session_context"](session_id="sess-auth-001", max_tokens=4000)
        assert len(short) < len(long)
        assert "Truncated" in short


class TestSessionCleanExtended:
    def test_clean_writes_audit_trail(self, mock_db_path):
        tools = _get_tools()
        tools["session_clean"](dry_run=False)

        conn = sqlite3.connect(mock_db_path)
        rows = conn.execute("SELECT * FROM scrub_log").fetchall()
        conn.close()
        assert len(rows) >= 1

    def test_clean_no_secrets_found(self, mock_db_path):
        tools = _get_tools()
        # sess-debug-002 has no secrets in its messages
        result = tools["session_clean"](session_id="sess-debug-002", dry_run=False)
        assert "messages_updated" not in result


class TestSessionHotspotsExtended:
    def test_hotspots_since_days_filter(self, mock_db_path):
        # Insert an old file_reference (2025) that should be excluded by days=1
        conn = sqlite3.connect(mock_db_path)
        conn.execute(
            "INSERT INTO file_references "
            "(session_id, message_id, file_path, tool_name, timestamp) "
            "VALUES ('sess-auth-001', 'msg-1', '/src/old_file.py', 'Read', "
            "'2025-01-01T10:00:00')"
        )
        conn.commit()
        conn.close()

        tools = _get_tools()
        result = tools["session_hotspots"](days=1)
        paths = [r["file_path"] for r in result]
        assert "/src/old_file.py" not in paths

    def test_hotspots_session_count_field(self, mock_db_path):
        tools = _get_tools()
        result = tools["session_hotspots"](days=0)
        # auth.py appears in both sess-auth-001 and sess-debug-002
        auth_row = next(r for r in result if r["file_path"] == "/src/auth.py")
        assert auth_row["session_count"] == 2
