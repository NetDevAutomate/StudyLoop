"""Tests for query_sessions module."""

from datetime import datetime, timedelta

import pytest

from agent_session_tools.query_logic import estimate_tokens
from agent_session_tools.query_utils import (
    build_date_filter,
    check_thresholds,
    get_db_size,
    parse_date,
)


class TestParseDate:
    """Tests for parse_date function."""

    def test_iso_format(self):
        """Test parsing ISO date format."""
        result = parse_date("2024-01-15")
        assert "2024-01-15" in result

    def test_relative_last_week(self):
        """Test parsing 'last-week' relative date."""
        result = parse_date("last-week")
        expected_date = datetime.now() - timedelta(days=7)
        # Should be within same day
        assert expected_date.strftime("%Y-%m-%d") in result

    def test_relative_last_month(self):
        """Test parsing 'last-month' relative date."""
        result = parse_date("last-month")
        expected_date = datetime.now() - timedelta(days=30)
        assert expected_date.strftime("%Y-%m-%d") in result

    def test_relative_last_n_days(self):
        """Test parsing 'last-N-days' format."""
        result = parse_date("last-14-days")
        expected_date = datetime.now() - timedelta(days=14)
        assert expected_date.strftime("%Y-%m-%d") in result

    def test_invalid_format_raises(self):
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid date format"):
            parse_date("not-a-date")

    def test_case_insensitive(self):
        """Test that parsing is case insensitive."""
        result = parse_date("LAST-WEEK")
        assert result is not None


class TestBuildDateFilter:
    """Tests for build_date_filter function."""

    def test_no_filters(self):
        """Test with no date filters."""
        where, params = build_date_filter()
        assert where == ""
        assert params == []

    def test_since_only(self):
        """Test with only 'since' filter."""
        where, params = build_date_filter(since="2024-01-01")
        assert "updated_at >= ?" in where
        assert len(params) == 1

    def test_before_only(self):
        """Test with only 'before' filter."""
        where, params = build_date_filter(before="2024-12-31")
        assert "updated_at <= ?" in where
        assert len(params) == 1

    def test_both_filters(self):
        """Test with both 'since' and 'before' filters."""
        where, params = build_date_filter(since="2024-01-01", before="2024-12-31")
        assert "updated_at >= ?" in where
        assert "updated_at <= ?" in where
        assert " AND " in where
        assert len(params) == 2


class TestCheckThresholds:
    """Tests for check_thresholds function."""

    _config = {"thresholds": {"warning_mb": 100, "critical_mb": 500}}

    def test_ok_status(self):
        """Test status is 'ok' when below warning threshold."""
        result = check_thresholds(50.0, self._config)
        assert result["status"] == "ok"

    def test_warning_status(self):
        """Test status is 'warning' when above warning but below critical."""
        result = check_thresholds(150.0, self._config)
        assert result["status"] == "warning"

    def test_critical_status(self):
        """Test status is 'critical' when above critical threshold."""
        result = check_thresholds(600.0, self._config)
        assert result["status"] == "critical"

    def test_result_has_message(self):
        """Test that result includes a message."""
        result = check_thresholds(50.0, self._config)
        assert "message" in result
        assert result["message"] is not None


class TestGetDbSize:
    """Tests for get_db_size function."""

    def test_nonexistent_path(self, tmp_path):
        """Test with nonexistent file."""
        result = get_db_size(tmp_path / "nonexistent.db")
        assert result["bytes"] == 0
        assert result["mb"] == 0
        assert result["formatted"] == "0 B"

    def test_existing_file(self, tmp_path):
        """Test with existing file."""
        test_file = tmp_path / "test.db"
        test_file.write_bytes(b"x" * 1024)  # 1 KB
        result = get_db_size(test_file)
        assert result["bytes"] == 1024
        assert result["formatted"].endswith("KB")


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_string(self):
        """Test token estimation for empty string."""
        assert estimate_tokens("") == 0

    def test_short_string(self):
        """Test token estimation for short string."""
        # 12 characters ≈ 3 tokens
        result = estimate_tokens("Hello world!")
        assert result == 3

    def test_longer_string(self):
        """Test token estimation for longer string."""
        # 400 characters ≈ 100 tokens
        text = "a" * 400
        result = estimate_tokens(text)
        assert result == 100


class TestSearchFunctionality:
    """Tests for search functionality using fixtures."""

    def test_search_with_populated_db(self, populated_db):
        """Test that search works with populated database."""
        conn, _ = populated_db

        # Verify data exists
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count > 0

        # Test FTS search
        result = conn.execute(
            "SELECT * FROM messages_fts WHERE messages_fts MATCH 'test'"
        ).fetchall()
        assert len(result) > 0

    def test_session_query(self, populated_db):
        """Test querying sessions."""
        conn, _ = populated_db

        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(sessions) == 1
        assert sessions[0]["source"] == "claude_code"
        assert sessions[0]["project_path"] == "/test/project"
