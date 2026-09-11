"""Migration 48 and the alignment accounting it makes possible.

Unit tier: pure sqlite, no model, no extension. The lifecycle-path tests
(export update, scrub, dedup merge, purge, prune, compact) live in
``test_embedding_lifecycle.py``; this file pins the substrate they rely on.
"""

from __future__ import annotations

import sqlite3
from importlib.resources import files

import pytest

from agent_session_tools import embedding_alignment as align
from agent_session_tools.migrations import CURRENT_VERSION, MIGRATIONS, migrate

MODEL = "fake-model"
DIM = 4
VEC = b"\x00\x00\x80\x3f" * DIM  # four float32 ones; the bytes are opaque here


def _fresh(tmp_path, *, foreign_keys: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "sessions.db")
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)  # migration 6 turns foreign_keys ON; set the mode we want after it
    conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == int(foreign_keys)
    return conn


def _seed(conn: sqlite3.Connection, *, source: str = "kiro_cli") -> None:
    conn.execute("INSERT INTO sessions(id, source) VALUES ('s1', ?)", (source,))
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content) VALUES "
        "('m1', 's1', 'user', ?), ('m2', 's1', 'assistant', ?), ('m3', 's1', 'tool_result', ?)",
        ("a learner question long enough to embed, fifty characters or more here",) * 3,
    )


def _vector(conn, message_id, chunk_ix=0, *, model=MODEL, dim=DIM, sha=None) -> None:
    if sha is None:
        content = conn.execute(
            "SELECT content FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        sha = align.content_sha256(content[0] if content else "")
    conn.execute(
        "INSERT INTO message_embeddings(message_id, chunk_ix, model, dim, content_sha256, embedding) "
        "VALUES (?,?,?,?,?,?)",
        (message_id, chunk_ix, model, dim, sha, VEC),
    )


def _rows(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM message_embeddings").fetchone()[0]


# ---------------------------------------------------------------------------
# migration 48
# ---------------------------------------------------------------------------


def test_migration_48_is_current_and_registered():
    assert CURRENT_VERSION == 48
    assert 48 in MIGRATIONS


def test_fresh_database_has_the_aligned_shape_and_no_session_vectors(tmp_path):
    conn = _fresh(tmp_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 48
    columns = {r[1]: r for r in conn.execute("PRAGMA table_info(message_embeddings)")}
    assert set(columns) == {
        "message_id",
        "chunk_ix",
        "model",
        "dim",
        "content_sha256",
        "truncated",
        "embedding",
        "created_at",
    }
    pk = sorted((r[5], r[1]) for r in columns.values() if r[5])
    assert [name for _, name in pk] == ["message_id", "chunk_ix"]
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='session_embeddings'"
    ).fetchone()
    triggers = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='messages'"
        )
    }
    assert {
        "message_embeddings_content_changed",
        "message_embeddings_message_deleted",
    } <= triggers


def test_migration_refuses_when_the_retired_tables_hold_rows(tmp_path):
    """Nothing in production wrote migration 7's tables; rows mean a hand-run backfill."""
    conn = sqlite3.connect(tmp_path / "sessions.db")
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    # Walk to version 47 only, then plant a legacy row.
    conn.execute("BEGIN")
    for version in range(1, 48):
        MIGRATIONS[version][1](conn)
    conn.execute("PRAGMA user_version = 47")
    conn.commit()
    conn.execute("INSERT INTO sessions(id, source) VALUES ('s', 'kiro_cli')")
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content) VALUES ('m','s','user','x')"
    )
    conn.execute(
        "INSERT INTO message_embeddings(message_id, embedding) VALUES ('m', x'00')"
    )
    conn.commit()
    with pytest.raises(RuntimeError, match="retired embedding layer"):
        migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 47
    assert conn.execute("SELECT COUNT(*) FROM message_embeddings").fetchone()[0] == 1


def test_bad_hash_length_and_negative_chunk_are_refused(tmp_path):
    conn = _fresh(tmp_path)
    _seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _vector(conn, "m1", sha="not-a-sha256")
    with pytest.raises(sqlite3.IntegrityError):
        _vector(conn, "m1", chunk_ix=-1)


@pytest.mark.parametrize("foreign_keys", [True, False])
def test_content_change_and_delete_sweep_vectors_with_or_without_fk(
    tmp_path, foreign_keys
):
    conn = _fresh(tmp_path, foreign_keys=foreign_keys)
    _seed(conn)
    _vector(conn, "m1", 0)
    _vector(conn, "m1", 1)
    _vector(conn, "m2", 0)
    assert _rows(conn) == 3
    conn.execute("UPDATE messages SET role='user' WHERE id='m1'")
    assert _rows(conn) == 3, "a non-content update keeps the vectors"
    conn.execute("UPDATE messages SET content=content WHERE id='m1'")
    assert _rows(conn) == 3, "rewriting identical content keeps the vectors"
    conn.execute("UPDATE messages SET content='rewritten text' WHERE id='m1'")
    assert _rows(conn) == 1, "a content change drops every chunk of that message"
    conn.execute("DELETE FROM messages WHERE id='m2'")
    assert _rows(conn) == 0, (
        "a delete drops the vectors whether or not FKs are enforced"
    )


@pytest.mark.parametrize("foreign_keys", [True, False])
def test_id_rekey_never_leaves_a_vector_pointing_at_the_old_id(tmp_path, foreign_keys):
    conn = _fresh(tmp_path, foreign_keys=foreign_keys)
    _seed(conn)
    _vector(conn, "m1")
    conn.execute("UPDATE messages SET id='m1-rev-abc' WHERE id='m1'")
    # With FKs on, ON UPDATE CASCADE may move the row before the trigger fires;
    # with them off, the trigger deletes it. Either way: no orphan, no stale id.
    assert not conn.execute(
        "SELECT 1 FROM message_embeddings WHERE message_id='m1'"
    ).fetchone()
    assert align.alignment_report(conn, model=MODEL, dim=DIM).orphaned == 0


def test_plain_connection_maintenance_works_with_vectors_present(tmp_path):
    """No virtual table lives in sessions.db: integrity_check and VACUUM INTO need no extension."""
    conn = _fresh(tmp_path)
    _seed(conn)
    _vector(conn, "m1")
    conn.commit()
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.execute("VACUUM INTO ?", (str(tmp_path / "clone.db"),))
    clone = sqlite3.connect(tmp_path / "clone.db")
    assert clone.execute("SELECT COUNT(*) FROM message_embeddings").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# alignment accounting
# ---------------------------------------------------------------------------


def test_eligibility_is_admitted_source_prose_role_and_length(tmp_path):
    conn = _fresh(tmp_path)
    _seed(conn)
    conn.execute("INSERT INTO sessions(id, source) VALUES ('hidden', 'aider')")
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content) VALUES "
        "('h1', 'hidden', 'user', ?), ('short', 's1', 'user', 'too short')",
        ("a long enough message in a session whose source was retired long ago",),
    )
    report = align.alignment_report(conn, model=MODEL, dim=DIM)
    assert report.eligible == 2, (
        "m1 and m2: not the tool_result, not the short, not the hidden"
    )
    assert report.missing == 2 and report.embedded == 0 and report.rows == 0
    assert report.aligned and not report.complete


def test_every_misaligned_state_is_counted_then_swept_and_missing_is_left_alone(
    tmp_path,
):
    conn = _fresh(tmp_path, foreign_keys=False)
    _seed(conn)
    conn.execute("INSERT INTO sessions(id, source) VALUES ('hidden', 'aider')")
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content) VALUES ('h1', 'hidden', 'user', ?)",
        ("a long enough message in a session whose source was retired long ago",),
    )
    _vector(conn, "m1")  # aligned
    _vector(conn, "m2", sha="0" * 64)  # stale: hash does not match the content
    _vector(conn, "h1")  # hidden: admitted at embed time, source retired since
    _vector(conn, "m1", chunk_ix=1, model="other-model")  # model mismatch
    _vector(conn, "m1", chunk_ix=2, dim=DIM + 1)  # dimension mismatch
    # An orphan can only pre-date the triggers (or be written with FKs off, as
    # here): a vector whose message never existed on this connection.
    _vector(conn, "ghost", sha=align.content_sha256(""))

    report = align.alignment_report(conn, model=MODEL, dim=DIM)
    assert report.to_dict() == {
        "model": MODEL,
        "dim": DIM,
        "min_content_length": 50,
        "eligible": 2,
        "embedded": 2,
        "missing": 0,
        "orphaned": 1,
        "stale": 1,
        "model_mismatch": 2,
        "hidden": 1,
        "rows": 6,
        "aligned": False,
        "complete": False,
    }

    swept = align.sweep(conn, model=MODEL, dim=DIM)
    assert swept.to_dict() == {
        "orphaned": 1,
        "stale": 1,
        "model_mismatch": 2,
        "hidden": 1,
        "deleted": 5,
    }
    after = align.alignment_report(conn, model=MODEL, dim=DIM)
    assert after.aligned
    assert after.rows == 1 and after.missing == 1, (
        "the stale m2 is now a backlog item, not deleted content"
    )
    assert align.missing_messages(conn, model=MODEL) == [
        ("m2", conn.execute("SELECT content FROM messages WHERE id='m2'").fetchone()[0])
    ]


def test_missing_messages_is_bounded_and_ordered_by_rowid(tmp_path):
    conn = _fresh(tmp_path)
    _seed(conn)
    assert [m for m, _ in align.missing_messages(conn, model=MODEL, limit=1)] == ["m1"]
    assert [m for m, _ in align.missing_messages(conn, model=MODEL)] == ["m1", "m2"]


def test_content_sha256_is_the_hash_the_triggers_and_doctor_agree_on():
    assert align.content_sha256("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
