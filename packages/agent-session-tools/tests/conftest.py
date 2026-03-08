"""Pytest configuration and shared fixtures."""

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Initialize schema
    schema_path = (
        Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    )
    with open(schema_path) as f:
        conn.executescript(f.read())

    yield conn, db_path

    conn.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary config directory."""
    config_dir = tmp_path / ".config" / "agent_session"
    config_dir.mkdir(parents=True)
    return config_dir


@pytest.fixture
def sample_session_data():
    """Sample session data for testing."""
    return {
        "id": "test-session-001",
        "source": "claude_code",
        "project_path": "/test/project",
        "git_branch": "main",
        "created_at": "2024-01-01T10:00:00",
        "updated_at": "2024-01-01T12:00:00",
        "metadata": None,
    }


@pytest.fixture
def sample_message_data():
    """Sample message data for testing."""
    return {
        "id": "test-msg-001",
        "session_id": "test-session-001",
        "parent_id": None,
        "role": "user",
        "content": "Hello, this is a test message.",
        "model": None,
        "timestamp": "2024-01-01T10:00:00",
        "metadata": None,
    }


@pytest.fixture
def populated_db(temp_db, sample_session_data, sample_message_data):
    """Create a database with sample data."""
    conn, db_path = temp_db

    # Insert sample session
    conn.execute(
        """
        INSERT INTO sessions (id, source, project_path, git_branch, created_at, updated_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sample_session_data["id"],
            sample_session_data["source"],
            sample_session_data["project_path"],
            sample_session_data["git_branch"],
            sample_session_data["created_at"],
            sample_session_data["updated_at"],
            sample_session_data["metadata"],
        ),
    )

    # Insert sample message
    conn.execute(
        """
        INSERT INTO messages (id, session_id, parent_id, role, content, model, timestamp, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sample_message_data["id"],
            sample_message_data["session_id"],
            sample_message_data["parent_id"],
            sample_message_data["role"],
            sample_message_data["content"],
            sample_message_data["model"],
            sample_message_data["timestamp"],
            sample_message_data["metadata"],
        ),
    )

    conn.commit()

    yield conn, db_path
