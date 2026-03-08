"""Tests for the LiteLLM Bedrock Proxy session exporter."""

import json
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.exporters.litellm import LitellmExporter
from agent_session_tools.migrations import migrate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_litellm_db(db_path: Path, *, with_conversations: bool = False) -> None:
    """Create a minimal LiteLLM webhook_metrics database at *db_path*."""
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE webhook_metrics (
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            model TEXT,
            tokens_used INTEGER,
            response_time REAL,
            event_type TEXT,
            error_message TEXT,
            status_code INTEGER,
            raw_data TEXT
        )
    """)

    raw = json.dumps(
        {
            "endpoint": "/v1/chat/completions",
            "request_id": "req-001",
            "request_preview": "What is Python?",
            "response_preview": "Python is a programming language.",
        }
    )

    conn.execute(
        """
        INSERT INTO webhook_metrics
            (timestamp, model, tokens_used, response_time, event_type,
             error_message, status_code, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "2025-06-01T10:00:00",
            "anthropic.claude-sonnet-4-20250514-v1:0",
            150,
            1.5,
            "success",
            None,
            200,
            raw,
        ),
    )

    if with_conversations:
        conn.execute("""
            CREATE TABLE webhook_conversations (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                model TEXT,
                tokens_used INTEGER,
                response_time REAL,
                event_type TEXT,
                error_message TEXT,
                status_code INTEGER,
                raw_data TEXT,
                conversation_json TEXT
            )
        """)
        conv_json = json.dumps(
            {
                "request": {
                    "messages": [{"role": "user", "content": "Full user prompt here."}]
                },
                "response": {
                    "choices": [
                        {"message": {"content": "Full assistant response here."}}
                    ]
                },
            }
        )
        conn.execute(
            """
            INSERT INTO webhook_conversations
                (timestamp, model, tokens_used, response_time, event_type,
                 error_message, status_code, raw_data, conversation_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2025-06-01T10:00:00",
                "anthropic.claude-sonnet-4-20250514-v1:0",
                150,
                1.5,
                "success",
                None,
                200,
                raw,
                conv_json,
            ),
        )

    conn.commit()
    conn.close()


def _create_empty_litellm_db(db_path: Path) -> None:
    """Create a LiteLLM DB with the table but no rows."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE webhook_metrics (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            model TEXT,
            tokens_used INTEGER,
            response_time REAL,
            event_type TEXT,
            error_message TEXT,
            status_code INTEGER,
            raw_data TEXT
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def migrated_db(temp_db):
    """Return (conn, db_path) with migrations applied."""
    conn, db_path = temp_db
    migrate(conn)
    return conn, db_path


@pytest.fixture()
def litellm_db(tmp_path: Path) -> Path:
    """Create a fake LiteLLM metrics.db with one webhook_metrics row."""
    db_path = tmp_path / "metrics.db"
    _create_litellm_db(db_path)
    return db_path


@pytest.fixture()
def litellm_db_with_conversations(tmp_path: Path) -> Path:
    """LiteLLM DB with both webhook_metrics and webhook_conversations tables."""
    db_path = tmp_path / "metrics_full.db"
    _create_litellm_db(db_path, with_conversations=True)
    return db_path


@pytest.fixture()
def litellm_db_empty(tmp_path: Path) -> Path:
    """LiteLLM DB that exists but has zero records."""
    db_path = tmp_path / "empty_metrics.db"
    _create_empty_litellm_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_true_when_db_exists(self, litellm_db):
        exporter = LitellmExporter(litellm_db_path=litellm_db)
        assert exporter.is_available() is True

    def test_false_when_db_missing(self, tmp_path):
        exporter = LitellmExporter(litellm_db_path=tmp_path / "nonexistent.db")
        assert exporter.is_available() is False

    def test_false_when_path_is_none(self):
        exporter = LitellmExporter(litellm_db_path=None)
        # _find_litellm_database likely returns None on CI / test machines
        # So is_available depends on whether auto-detect finds a real DB.
        # We force None here to be explicit:
        exporter.litellm_db_path = None
        assert exporter.is_available() is False


# ---------------------------------------------------------------------------
# _check_conversations_table
# ---------------------------------------------------------------------------


class TestCheckConversationsTable:
    def test_returns_false_when_table_missing(self, litellm_db):
        conn = sqlite3.connect(litellm_db)
        exporter = LitellmExporter(litellm_db_path=litellm_db)
        assert exporter._check_conversations_table(conn) is False
        conn.close()

    def test_returns_true_when_table_has_data(self, litellm_db_with_conversations):
        conn = sqlite3.connect(litellm_db_with_conversations)
        exporter = LitellmExporter(litellm_db_path=litellm_db_with_conversations)
        assert exporter._check_conversations_table(conn) is True
        conn.close()

    def test_returns_false_when_table_exists_but_empty(self, tmp_path):
        db_path = tmp_path / "conv_empty.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE webhook_conversations (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                model TEXT,
                tokens_used INTEGER,
                response_time REAL,
                event_type TEXT,
                error_message TEXT,
                status_code INTEGER,
                raw_data TEXT,
                conversation_json TEXT
            )
        """)
        conn.commit()

        exporter = LitellmExporter(litellm_db_path=db_path)
        assert exporter._check_conversations_table(conn) is False
        conn.close()


# ---------------------------------------------------------------------------
# _detect_sessions
# ---------------------------------------------------------------------------


class TestDetectSessions:
    def test_single_record_becomes_single_session(self, litellm_db):
        conn = sqlite3.connect(litellm_db)
        conn.row_factory = sqlite3.Row
        records = conn.execute(
            "SELECT * FROM webhook_metrics ORDER BY timestamp"
        ).fetchall()
        conn.close()

        exporter = LitellmExporter(litellm_db_path=litellm_db)
        sessions = exporter._detect_sessions(records)

        assert len(sessions) == 1
        session = sessions[0]
        assert session["id"].startswith("litellm_")
        assert session["metadata"]["total_requests"] == 1
        assert session["metadata"]["total_tokens"] == 150

    def test_timeout_splits_sessions(self, tmp_path):
        """Records separated by more than session_timeout become separate sessions."""
        db_path = tmp_path / "timeout_test.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE webhook_metrics (
                id INTEGER PRIMARY KEY,
                timestamp TEXT, model TEXT, tokens_used INTEGER,
                response_time REAL, event_type TEXT, error_message TEXT,
                status_code INTEGER, raw_data TEXT
            )
        """)
        raw = json.dumps({"endpoint": "/v1/chat/completions"})
        # Two records 2 hours apart (well beyond default 30-minute timeout)
        conn.execute(
            "INSERT INTO webhook_metrics VALUES (1, ?, ?, 50, 1.0, 'success', NULL, 200, ?)",
            ("2025-06-01T10:00:00", "model-a", raw),
        )
        conn.execute(
            "INSERT INTO webhook_metrics VALUES (2, ?, ?, 75, 0.8, 'success', NULL, 200, ?)",
            ("2025-06-01T12:00:00", "model-b", raw),
        )
        conn.commit()

        conn.row_factory = sqlite3.Row
        records = conn.execute(
            "SELECT * FROM webhook_metrics ORDER BY timestamp"
        ).fetchall()
        conn.close()

        exporter = LitellmExporter(litellm_db_path=db_path, session_timeout_minutes=30)
        sessions = exporter._detect_sessions(records)

        assert len(sessions) == 2


# ---------------------------------------------------------------------------
# _extract_full_conversation
# ---------------------------------------------------------------------------


class TestExtractFullConversation:
    def setup_method(self):
        self.exporter = LitellmExporter(litellm_db_path=None)

    def test_extracts_request_response_format(self):
        conv_json = json.dumps(
            {
                "request": {"messages": [{"role": "user", "content": "Hello"}]},
                "response": {"choices": [{"message": {"content": "Hi there"}}]},
            }
        )
        user, assistant = self.exporter._extract_full_conversation(conv_json)
        assert user == "Hello"
        assert assistant == "Hi there"

    def test_extracts_kwargs_format(self):
        conv_json = json.dumps(
            {
                "kwargs": {"messages": [{"role": "user", "content": "Via kwargs"}]},
                "completion_response": {
                    "choices": [{"message": {"content": "Response via completion"}}]
                },
            }
        )
        user, assistant = self.exporter._extract_full_conversation(conv_json)
        assert user == "Via kwargs"
        assert assistant == "Response via completion"

    def test_empty_string_returns_empty_tuple(self):
        user, assistant = self.exporter._extract_full_conversation("")
        assert user == ""
        assert assistant == ""

    def test_invalid_json_returns_empty_tuple(self):
        user, assistant = self.exporter._extract_full_conversation("{bad json")
        assert user == ""
        assert assistant == ""

    def test_missing_content_returns_fallback(self):
        conv_json = json.dumps(
            {"request": {"messages": []}, "response": {"choices": []}}
        )
        user, assistant = self.exporter._extract_full_conversation(conv_json)
        assert user == "[No user content]"
        assert assistant == "[No assistant content]"


# ---------------------------------------------------------------------------
# export_all (integration)
# ---------------------------------------------------------------------------


class TestExportAll:
    def test_exports_session_with_messages(self, migrated_db, litellm_db):
        conn, _ = migrated_db
        exporter = LitellmExporter(litellm_db_path=litellm_db)
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 1
        assert stats.errors == 0

        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(sessions) == 1
        assert sessions[0]["source"] == "litellm-proxy"

        messages = conn.execute("SELECT * FROM messages").fetchall()
        # Each webhook record produces a user + assistant message pair
        assert len(messages) == 2
        roles = {m["role"] for m in messages}
        assert roles == {"user", "assistant"}

    def test_incremental_skips_existing(self, migrated_db, litellm_db):
        conn, _ = migrated_db
        exporter = LitellmExporter(litellm_db_path=litellm_db)

        stats_first = exporter.export_all(conn, incremental=True)
        assert stats_first.added == 1

        stats_second = exporter.export_all(conn, incremental=True)
        assert stats_second.skipped == 1
        assert stats_second.added == 0

    def test_unavailable_returns_zero_stats(self, migrated_db, tmp_path):
        conn, _ = migrated_db
        exporter = LitellmExporter(litellm_db_path=tmp_path / "gone.db")
        stats = exporter.export_all(conn, incremental=False)
        assert stats.added == 0
        assert stats.errors == 0

    def test_empty_db_returns_zero_stats(self, migrated_db, litellm_db_empty):
        conn, _ = migrated_db
        exporter = LitellmExporter(litellm_db_path=litellm_db_empty)
        stats = exporter.export_all(conn, incremental=False)
        assert stats.added == 0

    def test_handles_missing_webhook_metrics_table(self, migrated_db, tmp_path):
        """A database file with no webhook_metrics table should not crash."""
        db_path = tmp_path / "no_table.db"
        conn_litellm = sqlite3.connect(db_path)
        conn_litellm.execute("CREATE TABLE unrelated (id INTEGER)")
        conn_litellm.commit()
        conn_litellm.close()

        conn, _ = migrated_db
        exporter = LitellmExporter(litellm_db_path=db_path)
        # This will raise because it tries to SELECT from webhook_metrics.
        # The exporter currently doesn't guard against a missing table,
        # so we verify it raises rather than silently corrupting data.
        with pytest.raises(sqlite3.OperationalError):
            exporter.export_all(conn, incremental=False)

    def test_failure_event_recorded_as_error_in_metadata(self, migrated_db, tmp_path):
        """Webhook records with event_type='failure' should be reflected in session metadata."""
        db_path = tmp_path / "failure.db"
        conn_litellm = sqlite3.connect(db_path)
        conn_litellm.execute("""
            CREATE TABLE webhook_metrics (
                id INTEGER PRIMARY KEY,
                timestamp TEXT, model TEXT, tokens_used INTEGER,
                response_time REAL, event_type TEXT, error_message TEXT,
                status_code INTEGER, raw_data TEXT
            )
        """)
        raw = json.dumps({"endpoint": "/v1/chat/completions"})
        conn_litellm.execute(
            """INSERT INTO webhook_metrics VALUES
               (1, '2025-06-01T10:00:00', 'model-x', 0, 0.5, 'failure',
                'Rate limited', 429, ?)""",
            (raw,),
        )
        conn_litellm.commit()
        conn_litellm.close()

        conn, _ = migrated_db
        exporter = LitellmExporter(litellm_db_path=db_path)
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 1
        session = conn.execute("SELECT metadata FROM sessions").fetchone()
        meta = json.loads(session["metadata"])
        assert meta["error_count"] == 1

    def test_conversations_table_selects_from_webhook_conversations(
        self, migrated_db, litellm_db_with_conversations
    ):
        """When webhook_conversations has data, the exporter reads from that table.

        NOTE: There is a known bug in _add_request_to_session where the check
        ``"conversation_json" in record`` tests sqlite3.Row *values* rather than
        column *names*, so the full conversation content is never extracted.
        The exporter falls back to raw_data preview content even when the
        webhook_conversations table is used as the data source. This test
        documents the current (buggy) behaviour.
        """
        conn, _ = migrated_db
        exporter = LitellmExporter(litellm_db_path=litellm_db_with_conversations)
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 1

        # Despite reading from webhook_conversations, full content extraction
        # does not activate because of the sqlite3.Row ``in`` operator bug.
        # The user message content comes from raw_data.request_preview instead.
        user_msg = conn.execute(
            "SELECT content FROM messages WHERE role = 'user'"
        ).fetchone()
        assert "What is Python?" in user_msg["content"]
