"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agent_session_tools.migrations import CURRENT_VERSION, migrate


@pytest.fixture(autouse=True)
def _close_sqlite_connections_created_by_tests(monkeypatch):
    """Close every sqlite connection a test opens, even on assertion failure.

    Many unit helpers intentionally return in-memory connections to their test
    rather than owning a fixture. Python 3.13 now reports those forgotten
    handles as ResourceWarning during coverage's forced GC. Track the real
    boundary once and close idempotently after each test; explicit closes and
    the temp_db fixture remain valid.
    """
    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    yield
    for connection in reversed(opened):
        with contextlib.suppress(sqlite3.ProgrammingError):
            connection.close()


@pytest.fixture(autouse=True)
def _isolated_studyloop_config(tmp_path, monkeypatch):
    """Point every test at an isolated config so ambient user config
    (real DB paths, tiering full_db_path) can never leak into tests.

    Tests that need specific config set STUDYLOOP_CONFIG themselves after
    this fixture. Module-level config caches are reset for the same reason.
    """
    isolated = tmp_path / "isolated-studyloop-config.yaml"
    # Legacy fixtures intentionally have no project classification. Explicitly
    # inspect that scope in tests; production defaults still require a choice.
    isolated.write_text("memory:\n  default_scope: unclassified\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(isolated))
    monkeypatch.delenv("SESSION_CONTEXT_SCOPE", raising=False)
    import agent_session_tools.maintenance as maintenance_mod
    import agent_session_tools.query_db as query_db_mod
    import agent_session_tools.sync as sync_mod

    monkeypatch.setattr(query_db_mod, "_config", None)
    monkeypatch.setattr(sync_mod, "_config", None)
    monkeypatch.setattr(maintenance_mod, "_config", None)


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(db_path.resolve().as_uri(), uri=True)
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
def migrated_db(temp_db):
    """Return a temp_db with all migrations applied so exporter columns exist."""
    conn, db_path = temp_db
    migrate(conn)
    return conn, db_path


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


SCHEMA_PATH = (
    Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
)


@dataclass(frozen=True)
class OntologyProductionStore:
    """A migrated, two-session-corpus database shared by ontology test modules.

    Ported from SessionWeaver's reference ``tests/conftest.py``
    ``production_store`` fixture -- this package's own
    ``exporters.base.commit_batch`` / ``context.store`` / ``context.provenance``
    build the identical fixture corpus, since SessionWeaver depends on this
    exact package. ``test_ontology.py`` and ``test_ontology_live.py`` both use
    this fixture so the two-session corpus (and its exact structural/message
    content) is defined in exactly one place.
    """

    conn: sqlite3.Connection
    db_path: Path


def _ontology_native_source(
    *,
    session_id: str,
    harness: str,
    parser_version: str,
    native_key: str,
    native_kind: str,
    body: str,
    origin: Any,
) -> Any:
    from agent_session_tools.context.store import NativeSource

    return NativeSource(
        session_id=session_id,
        native_key=native_key,
        harness=harness,
        native_kind=native_kind,
        native_locator=f"fixture://{harness}/{session_id}#{native_key}",
        parser_version=parser_version,
        machine_id="fixture-machine",
        body=body,
        origin=origin,
        recorded_at="2026-09-07T12:00:00+00:00",
    )


def _ontology_fixture_rows(
    project_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return representative sessions and messages with native source records."""
    from agent_session_tools.context.provenance import Origin

    sessions: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    harnesses = (("codex", "codex-native-v1"), ("kiro_cli", "kiro-native-v1"))

    for index, (harness, parser_version) in enumerate(harnesses, start=1):
        session_id = f"fixture-session-{index}"
        sessions.append(
            {
                "id": session_id,
                "source": harness,
                "project_path": str(project_path),
                "git_branch": "feat/sessionweaver-phase2",
                "created_at": f"2026-09-07T12:0{index}:00+00:00",
                "updated_at": f"2026-09-07T12:1{index}:00+00:00",
                "metadata": "{}",
                "status": "added",
                "native_sources": [
                    _ontology_native_source(
                        session_id=session_id,
                        harness=harness,
                        parser_version=parser_version,
                        native_key="session-envelope",
                        native_kind="session:metadata",
                        body=f"Fixture envelope for {harness}.",
                        origin=Origin.UNKNOWN,
                    )
                ],
            }
        )
        for seq, (role, content) in enumerate(
            (
                ("user", f"How does fixture session {index} reach context evidence?"),
                ("assistant", "Through commit_batch and production capture_batch."),
            ),
            start=1,
        ):
            message_id = f"fixture-message-{index}-{seq}"
            messages.append(
                {
                    "id": message_id,
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "model": "fixture-model",
                    "timestamp": f"2026-09-07T12:2{seq}:00+00:00",
                    "metadata": "{}",
                    "seq": seq,
                    "native_sources": [
                        _ontology_native_source(
                            session_id=session_id,
                            harness=harness,
                            parser_version=parser_version,
                            native_key=f"message-{seq}",
                            native_kind=f"message:{role}",
                            body=content,
                            origin=Origin.CONVERSATION,
                        )
                    ],
                }
            )

    return sessions, messages


@pytest.fixture
def ontology_production_store(tmp_path):
    """Yield a migrated, populated store mirroring a real capture batch."""
    from agent_session_tools.exporters.base import ExportStats, commit_batch

    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_PATH.read_text())
        migrate(conn)
        if conn.execute("PRAGMA user_version").fetchone()[0] != CURRENT_VERSION:
            raise RuntimeError(
                "ontology fixture migration did not reach CURRENT_VERSION"
            )

        sessions, messages = _ontology_fixture_rows(tmp_path / "fixture-project")
        stats = ExportStats()
        commit_batch(conn, sessions, messages, stats)
        yield OntologyProductionStore(conn=conn, db_path=db_path)
    finally:
        conn.close()
