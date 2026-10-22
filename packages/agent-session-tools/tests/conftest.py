"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from pathlib import Path

# Writable-state isolation at IMPORT time, before any agent_session_tools import.
#
# A path-scoped run (``pytest packages/agent-session-tools/tests``, or ``pytest
# tests`` from this package) takes this package's pyproject as its config, so
# the workspace-root conftest.py -- which hard-assigns these three -- is never
# loaded. The autouse fixtures below redirect them per test, but test-module
# imports, collection hooks and session-scoped fixtures run before any of them
# and saw whatever the caller's shell exported: a learner's real sessions.db,
# state dir and config.
#
# Hard-assign, never ``setdefault``, once per process under the same pid marker
# the workspace-root conftest uses: in a workspace run that file has already
# claimed the sandbox and this block leaves it alone, so the two never disagree.
# A child process inherits the marker with its parent's pid, so it redirects
# again.
_SANDBOX_OWNER_ENV = "_STUDYLOOP_SUITE_SANDBOX_PID"
if os.environ.get(_SANDBOX_OWNER_ENV) != str(os.getpid()):
    _TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="agent-session-tools-test-state-"))
    os.environ["STUDYLOOP_STATE_DIR"] = str(_TEST_STATE_ROOT / "state")
    os.environ["STUDYLOOP_DB"] = str(_TEST_STATE_ROOT / "sessions.db")
    os.environ["STUDYLOOP_CONFIG"] = str(_TEST_STATE_ROOT / "config.yaml")
    os.environ[_SANDBOX_OWNER_ENV] = str(os.getpid())

import pytest  # noqa: E402

from agent_session_tools.migrations import migrate  # noqa: E402


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
    #
    # `semantic_search.auto_embed: false` is part of the same isolation, added
    # with the D-7 export hook: `_maybe_auto_embed` runs after every successful
    # export and embeds for real whenever the model is ALREADY in the local
    # Hugging Face cache — which it is on a developer's own machine. That turned
    # unrelated export tests into minutes of CPU and pytest-timeout failures.
    # The learner's cached model is ambient state, and keeping ambient state out
    # of tests is exactly what this fixture is for. Tests that exercise the hook
    # enable it explicitly and stub `embedding_store` (see
    # test_export_auto_embed.py).
    isolated.write_text(
        "memory:\n  default_scope: unclassified\nsemantic_search:\n  auto_embed: false\n"
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(isolated))
    monkeypatch.delenv("SESSION_CONTEXT_SCOPE", raising=False)
    import agent_session_tools.maintenance as maintenance_mod
    import agent_session_tools.query_db as query_db_mod
    import agent_session_tools.sync as sync_mod

    monkeypatch.setattr(query_db_mod, "_config", None)
    monkeypatch.setattr(sync_mod, "_config", None)
    monkeypatch.setattr(maintenance_mod, "_config", None)


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    """Point writable state at a per-test directory, never the learner's own.

    The repo-root ``conftest.py`` does this for the whole workspace, but it is
    only loaded when pytest's rootdir is the repo root -- this package has its
    own ``pyproject.toml``, so running its tests directly (or naming a path
    under it on the command line) makes THIS the rootdir and that file is
    never imported. Without this fixture, anything that persists state
    (``load_indicator``'s encoder-load durations, lane A4) writes into the
    learner's real ``~/.local/share/studyloop`` from a unit test, which is
    exactly the leak
    ``private-docs/0005-vendor-picker-lists-repo-directories.md`` records.

    ``STUDYLOOP_DB`` is mirrored for the same reason: ``get_db_path()`` falls
    through to the learner's real ``~/.config/studyloop/sessions.db`` without
    it, so a reader that resolves the database at call time (the query-encoder
    warm's model pin) saw whatever that machine's corpus was last embedded with
    -- a test that passed on one machine and failed on another.
    """
    state = tmp_path / "isolated-state"
    monkeypatch.setenv("STUDYLOOP_STATE_DIR", str(state))
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "isolated-sessions.db"))


@pytest.fixture(autouse=True)
def _hf_hub_offline_does_not_leak_between_tests():
    """Restore ``HF_HUB_OFFLINE`` after each test.

    ``retrieval._encoder``, the query-encoder warm and the export's auto-embed
    all write ``HF_HUB_OFFLINE=1`` straight into ``os.environ`` -- deliberately,
    as a courtesy for libraries that read it, and harmless in the one-shot
    processes they run in. A test process is not one-shot: the first warm test
    to run left the flag set for every later test, and ``artefact_fetch``
    (which reads it as "do not fetch") then reported ``offline_skip`` wherever
    a test expected ``fetched``. ``monkeypatch`` cannot see a write made by
    production code, so this fixture snapshots and restores the variable
    itself.
    """
    before = os.environ.get("HF_HUB_OFFLINE")
    yield
    if before is None:
        os.environ.pop("HF_HUB_OFFLINE", None)
    else:
        os.environ["HF_HUB_OFFLINE"] = before


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
