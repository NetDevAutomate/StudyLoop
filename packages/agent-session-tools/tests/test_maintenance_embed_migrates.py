"""``session-maint embed`` / ``embed-check`` on a database an older release last wrote.

Regression: a real database at schema v30 -- last written before migration 48
shipped -- crashed ``session-maint embed`` with ``OperationalError: no such
column: e.content_sha256``. The command read migration 48's table without
migrating first, unlike every other entry point (``session-export``, scrub, the
context store), which migrates on open.

The model, the vector extension and the sidecar index are stubbed: this file
proves the CLI brings the schema current before it touches the embedding
tables, and that a migration refusal is an error line and exit 1 (D-8), never a
traceback. The embed mechanics are tested in ``test_embedding_store.py``.
"""

from __future__ import annotations

import sqlite3
import struct
from importlib.resources import files
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_session_tools import embedding_store
from agent_session_tools.maintenance import app
from agent_session_tools.migrations import CURRENT_VERSION, MIGRATIONS

runner = CliRunner()

LONG = "a learner question long enough to be eligible, fifty characters or more here"


class FakeEncoder:
    name, dim, max_tokens = "fake-model", 4, 64

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode(self, texts):  # noqa: ANN001 - Protocol shape, checked by the store
        return [struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in texts]


def _database_at(path: Path, version: int) -> Path:
    """A database exactly as release ``version`` left it, holding one eligible message."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            files("agent_session_tools").joinpath("schema.sql").read_text()
        )
        conn.execute("BEGIN")
        for step in range(1, version + 1):
            MIGRATIONS[step][1](conn)
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
        conn.execute("INSERT INTO sessions(id, source) VALUES ('s', 'kiro_cli')")
        conn.execute(
            "INSERT INTO messages(id, session_id, role, content) VALUES ('m', 's', 'user', ?)",
            (LONG,),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _query(path: Path, sql: str):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def semantic_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Semantic layer installed and cached; the real embed() runs on a fake encoder."""
    real_embed = embedding_store.embed

    def embed_with_fake_encoder(conn, **kwargs):  # noqa: ANN001, ANN003
        return real_embed(conn, encoder=FakeEncoder(), **kwargs)

    monkeypatch.setattr(
        embedding_store,
        "availability",
        lambda model=None: embedding_store.Availability(True, True, True, ""),
    )
    monkeypatch.setattr("agent_session_tools.embeddings.is_available", lambda: True)
    monkeypatch.setattr(embedding_store, "embed", embed_with_fake_encoder)
    monkeypatch.setattr(
        embedding_store, "_resolve_pin", lambda model, encoder: ("fake-model", 4)
    )
    monkeypatch.setattr(embedding_store, "reconcile", lambda conn: (0, 0))


def test_embed_migrates_a_v30_database_before_embedding(tmp_path, semantic_ready):
    db = _database_at(tmp_path / "sessions.db", 30)

    result = runner.invoke(app, ["embed", "--db", str(db)])

    assert result.exception is None or isinstance(result.exception, SystemExit), (
        result.exception
    )
    assert result.exit_code == 0, result.output
    assert f"Applied {CURRENT_VERSION - 30} database migration(s)" in result.output
    assert _query(db, "PRAGMA user_version") == CURRENT_VERSION
    assert _query(db, "SELECT COUNT(*) FROM message_embeddings") == 1


def test_embed_check_migrates_a_v30_database_before_reporting(tmp_path):
    db = _database_at(tmp_path / "sessions.db", 30)

    result = runner.invoke(app, ["embed-check", "--db", str(db)])

    assert result.exception is None or isinstance(result.exception, SystemExit), (
        result.exception
    )
    assert result.exit_code == 0, result.output
    assert "1 still to embed" in result.output
    assert _query(db, "PRAGMA user_version") == CURRENT_VERSION


def test_embed_reports_a_refused_migration_without_a_traceback(
    tmp_path, semantic_ready
):
    """Migration 48 refuses to drop a populated legacy table: say so, exit 1, change nothing."""
    db = _database_at(tmp_path / "sessions.db", 47)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO message_embeddings(message_id, embedding) VALUES ('m', x'00')"
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["embed", "--db", str(db)])

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    assert "❌" in result.output
    assert "retired embedding layer" in result.output
    assert _query(db, "PRAGMA user_version") == 47
