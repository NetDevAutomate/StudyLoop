"""Every write path that touches ``message_embeddings``, driven through production code.

``test_embedding_schema.py`` pins the substrate (migration 48's shape, its two
triggers, and the alignment accounting). This file walks the nine paths of the
Stage 3 design's "Lifecycle tests" table and drives each one through the module
that owns it — ``exporters.base.commit_batch``, ``deduplication``,
``mcp_server.session_clean``, ``context.lifecycle.purge_session``,
``tiering.prune_hot`` and ``tiering.compact_database`` — rather than through SQL
that imitates them. Vectors are planted directly because the embed job needs a
model; the hash is always the real one, so a planted row is indistinguishable
from an embedded one to every check under test.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from importlib.resources import files
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_session_tools import embedding_alignment as align
from agent_session_tools.exporters.base import ExportStats, commit_batch
from agent_session_tools.migrations import migrate

MODEL = "fake-model"
DIM = 4
VEC = b"\x00\x00\x80\x3f" * DIM  # four float32 ones; the bytes are opaque here
#: Over the 50-character eligibility floor, so every seeded message is embeddable.
BODY = "a learner question long enough to embed, fifty characters or more here"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _db(path: Path) -> sqlite3.Connection:
    """A migrated file database in WAL mode.

    WAL is what makes the "same transaction" assertions provable: a second
    connection can hold a read snapshot across another connection's write, so
    the test can look for a half-applied state instead of assuming there is none.
    """
    conn = sqlite3.connect(path)
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)
    conn.commit()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _session(
    conn: sqlite3.Connection, session_id: str, source: str = "kiro_cli"
) -> None:
    conn.execute(
        "INSERT INTO sessions(id, source, content_hash) VALUES (?,?,?)",
        (session_id, source, "hash-" + session_id),
    )


def _message(
    conn: sqlite3.Connection,
    message_id: str,
    session_id: str,
    *,
    role: str = "user",
    content: str = BODY,
) -> None:
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content) VALUES (?,?,?,?)",
        (message_id, session_id, role, content),
    )


def _vector(
    conn: sqlite3.Connection,
    message_id: str,
    chunk_ix: int = 0,
    *,
    model: str = MODEL,
    dim: int = DIM,
    sha: str | None = None,
) -> None:
    """Plant one vector row, hashed from the message's current content."""
    if sha is None:
        row = conn.execute(
            "SELECT content FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        sha = align.content_sha256((row[0] if row and row[0] is not None else ""))
    conn.execute(
        "INSERT INTO message_embeddings"
        "(message_id, chunk_ix, model, dim, content_sha256, embedding) VALUES (?,?,?,?,?,?)",
        (message_id, chunk_ix, model, dim, sha, VEC),
    )


def _rows(conn: sqlite3.Connection, message_id: str | None = None) -> int:
    if message_id is None:
        return conn.execute("SELECT COUNT(*) FROM message_embeddings").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM message_embeddings WHERE message_id=?", (message_id,)
    ).fetchone()[0]


def _report(conn: sqlite3.Connection) -> align.AlignmentReport:
    return align.alignment_report(conn, model=MODEL, dim=DIM)


def _mcp_tools() -> dict:
    """The MCP tool callables, as ``test_mcp_server`` obtains them."""
    pytest.importorskip("fastmcp", reason="fastmcp not installed")
    from agent_session_tools.mcp_server import mcp

    run_async = import_module(
        f"{__package__}._helpers" if __package__ else "_helpers"
    ).run_async
    tools = run_async(mcp._list_tools())
    return {tool.name: tool.fn for tool in tools}  # type: ignore[attr-defined]


@pytest.fixture
def tiered(tmp_path, monkeypatch):
    """Hot + full database paths wired through ``STUDYLOOP_CONFIG``."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    full_dir = tmp_path / "external"
    full_dir.mkdir()
    hot = config_dir / "sessions.db"
    full = full_dir / "sessions_full.db"
    config_file = config_dir / "config.yaml"
    config_file.write_text(
        f"database:\n  path: {hot}\n  full_db_path: {full}\n"
        f"  backup_dir: {config_dir}\n"
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_file))
    return {"hot": hot, "full": full}


def _make_hot(path: Path, *, sessions: int = 2, days_old: int = 60) -> None:
    """A migrated hot DB whose messages are long enough to be eligible."""
    from agent_session_tools.export_sessions import init_db

    conn = init_db(str(path))
    ts = (datetime.now() - timedelta(days=days_old)).isoformat()
    try:
        for i in range(sessions):
            conn.execute(
                "INSERT INTO sessions (id, source, created_at, updated_at, content_hash) "
                "VALUES (?, 'claude_code', ?, ?, ?)",
                (f"s{i}", ts, ts, f"hash{i}"),
            )
            for j in range(2):
                conn.execute(
                    "INSERT INTO messages (id, session_id, role, content, timestamp) "
                    "VALUES (?, ?, 'user', ?, ?)",
                    (f"s{i}-m{j}", f"s{i}", f"{BODY} (chunk {i}-{j})", ts),
                )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# export: add, in-place update, identity shift
# ---------------------------------------------------------------------------


def test_export_add_creates_a_backlog_item_and_no_vector(tmp_path):
    """A new conversation is `missing`, never silently embedded by the exporter."""
    conn = _db(tmp_path / "sessions.db")
    before = _report(conn)
    assert before.eligible == 0 and before.missing == 0

    stats = ExportStats()
    commit_batch(
        conn,
        [{"id": "s1", "source": "codex"}],
        [{"id": "m1", "session_id": "s1", "role": "user", "content": BODY}],
        stats,
    )

    after = _report(conn)
    assert stats.added == 1 and not stats.errors
    assert after.eligible == 1
    assert after.missing == before.missing + 1
    assert after.rows == 0
    assert after.aligned and not after.complete


def test_export_update_drops_the_vector_in_the_same_transaction(tmp_path):
    """An in-place content rewrite through ``commit_batch`` takes the vectors with it.

    ``_preserve_message_identity`` re-keys an incoming row whose stored content is
    non-empty and different (that is the identity-shift test below), so the upsert
    rewrites content in place only for a stored row that is empty or NULL — the
    "empty legacy parser artefact" ``commit_batch`` names in its own reconcile
    branch. That is the path a vector must not survive, and the reader below proves
    the rewrite and the deletion are never observable apart.
    """
    path = tmp_path / "sessions.db"
    conn = _db(path)
    session = {"id": "s1", "source": "codex"}
    commit_batch(
        conn,
        [session],
        [{"id": "m1", "session_id": "s1", "role": "user", "content": "   "}],
        ExportStats(),
    )
    _vector(conn, "m1")
    conn.commit()
    assert _rows(conn) == 1

    reader = sqlite3.connect(path)
    reader.execute("BEGIN")  # deferred: the snapshot is taken by the first read
    assert reader.execute("SELECT content FROM messages WHERE id='m1'").fetchone()[
        0
    ] == ("   ")
    assert _rows(reader) == 1
    assert reader.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1

    commit_batch(
        conn,
        [session],
        [{"id": "m1", "session_id": "s1", "role": "user", "content": BODY}],
        ExportStats(),
    )
    assert conn.execute("SELECT content FROM messages WHERE id='m1'").fetchone()[0] == (
        BODY
    ), "the empty artefact is rewritten in place, not re-keyed"

    # Same read snapshot: neither half of the change has appeared.
    assert reader.execute("SELECT content FROM messages WHERE id='m1'").fetchone()[
        0
    ] == ("   ")
    assert _rows(reader) == 1
    reader.rollback()

    # New snapshot: both halves at once. A changed body beside a live vector —
    # the state in which the hash mismatch would be observable — never exists.
    assert reader.execute("SELECT content FROM messages WHERE id='m1'").fetchone()[
        0
    ] == (BODY)
    assert _rows(reader) == 0
    report = _report(conn)
    assert report.stale == 0 and report.orphaned == 0
    assert report.missing == 1, "the rewritten message is back in the backlog"


def test_export_identity_shift_leaves_no_orphan_and_no_stale_vector(tmp_path):
    """A re-keyed revision keeps the original message and its vector exact."""
    path = tmp_path / "sessions.db"
    conn = _db(path)
    session = {"id": "s1", "source": "codex"}
    commit_batch(
        conn,
        [session],
        [{"id": "m1", "session_id": "s1", "role": "user", "content": BODY, "seq": 0}],
        ExportStats(),
    )
    _vector(conn, "m1", 0)
    _vector(conn, "m1", 1)
    conn.commit()

    revised = BODY + " — and then the learner asked a follow-up about it"
    commit_batch(
        conn,
        [session],
        [
            {
                "id": "m1",
                "session_id": "s1",
                "role": "user",
                "content": revised,
                "seq": 0,
            }
        ],
        ExportStats(),
    )

    ids = {row[0]: row[1] for row in conn.execute("SELECT id, content FROM messages")}
    shifted = sorted(set(ids) - {"m1"})
    assert shifted and all(i.startswith("m1-rev-") for i in shifted), (
        "the shifted positional id becomes a revision id, not an overwrite"
    )
    assert ids["m1"] == BODY, "historical prose is preserved under its original id"
    assert ids[shifted[0]] == revised

    report = _report(conn)
    assert _rows(conn, "m1") == 2, "the original id's vectors still describe its text"
    assert _rows(conn) == 2, "no vector followed the id, so none was duplicated"
    assert report.orphaned == 0 and report.stale == 0
    assert report.missing == 1, "only the new revision is a backlog item"
    assert not conn.execute(
        "SELECT 1 FROM message_embeddings WHERE message_id LIKE 'm1-rev-%'"
    ).fetchone()


# ---------------------------------------------------------------------------
# dedup merge
# ---------------------------------------------------------------------------


def test_dedup_merge_preserves_the_moved_messages_vectors(tmp_path):
    """Re-parenting a legacy duplicate's messages is not a content change."""
    from agent_session_tools.deduplication import merge_duplicates

    conn = _db(tmp_path / "sessions.db")
    conn.row_factory = sqlite3.Row
    _session(conn, "primary", source="claude_code")
    _session(conn, "dup", source="claude_code")
    _message(conn, "p1", "primary")
    _message(conn, "d1", "dup", content=BODY + " (from the duplicate capture)")
    _vector(conn, "p1")
    _vector(conn, "d1", 0)
    _vector(conn, "d1", 1)
    conn.commit()
    assert _rows(conn) == 3

    stats = merge_duplicates(conn, "primary", ["dup"])

    assert stats == {"messages_moved": 1, "sessions_removed": 1}
    assert (
        conn.execute("SELECT session_id FROM messages WHERE id='d1'").fetchone()[0]
        == "primary"
    )
    assert _rows(conn, "d1") == 2, "a session_id move must not fire the content trigger"
    report = _report(conn)
    assert report.rows == 3
    assert report.orphaned == 0 and report.stale == 0
    assert report.aligned and report.complete


# ---------------------------------------------------------------------------
# scrub
# ---------------------------------------------------------------------------


def test_scrub_removes_the_vector_in_the_scrub_log_transaction(tmp_path):
    """``session_clean`` rewrites content, so the vectors go with the audit row."""
    tools = _mcp_tools()
    path = tmp_path / "sessions.db"
    conn = _db(path)
    secret_body = (
        "Deploying with key AKIAIOSFODNN7EXAMPLE for the staging account, "  # pragma: allowlist secret
        "which is long enough to be an embeddable message on its own."
    )
    _session(conn, "s1")
    _message(conn, "m1", "s1", content=secret_body)
    _message(conn, "m2", "s1", content=BODY)  # no secret: must keep its vectors
    _vector(conn, "m1", 0)
    _vector(conn, "m1", 1)
    _vector(conn, "m2", 0)
    conn.commit()
    conn.close()

    reader = sqlite3.connect(path)
    reader.execute("BEGIN")
    assert _rows(reader) == 3
    assert reader.execute("SELECT COUNT(*) FROM scrub_log").fetchone()[0] == 0

    with patch("agent_session_tools.mcp_server._get_db_path", return_value=path):
        result = tools["session_clean"](dry_run=False)
    assert result["dry_run"] is False
    assert result["messages_updated"] == 1
    assert "aws_access_key" in result["findings_by_type"]

    # The reader's snapshot still predates the whole change: the audit row is
    # never visible while the scrubbed message's vectors are still there.
    assert _rows(reader) == 3
    assert reader.execute("SELECT COUNT(*) FROM scrub_log").fetchone()[0] == 0
    reader.rollback()

    assert reader.execute("SELECT COUNT(*) FROM scrub_log").fetchone()[0] >= 1
    assert _rows(reader, "m1") == 0, "the scrubbed message's vectors are gone"
    assert _rows(reader, "m2") == 1, "an untouched message keeps its vector"
    content = reader.execute("SELECT content FROM messages WHERE id='m1'").fetchone()[0]
    assert "AKIAIOSFODNN7EXAMPLE" not in content  # pragma: allowlist secret
    report = _report(reader)
    assert report.stale == 0 and report.orphaned == 0
    assert report.missing == 1, "the scrubbed message needs re-embedding"


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------


def test_purge_session_takes_the_vectors_and_leaves_no_dependency(tmp_path):
    from agent_session_tools.context import records
    from agent_session_tools.context.lifecycle import purge_session
    from agent_session_tools.context.store import ContextStore

    conn = records.connect(tmp_path / "sessions.db")
    _session(conn, "gone")
    _session(conn, "kept")
    _message(conn, "g1", "gone")
    _message(conn, "g2", "gone", role="assistant")
    _message(conn, "k1", "kept")
    _vector(conn, "g1", 0)
    _vector(conn, "g1", 1)
    _vector(conn, "g2", 0)
    _vector(conn, "k1", 0)
    conn.commit()
    assert _rows(conn) == 4

    with ContextStore(conn)._atomic():
        purge_session(conn, "gone")

    assert _rows(conn) == 1 and _rows(conn, "k1") == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    report = _report(conn)
    assert report.orphaned == 0 and report.stale == 0
    assert report.aligned and report.complete


def test_forget_session_applied_removes_the_vectors_too(tmp_path):
    """``forget_session(apply=True)`` is the scope-authorized wrapper over purge."""
    from agent_session_tools.context import records
    from agent_session_tools.context.lifecycle import forget_session

    conn = records.connect(tmp_path / "sessions.db")
    _session(conn, "gone")
    _message(conn, "g1", "gone")
    _vector(conn, "g1", 0)
    _vector(conn, "g1", 1)
    conn.commit()

    result = forget_session(conn, "gone", apply=True)

    assert result["applied"] is True
    assert result["selected_counts"]["messages"] == 1
    assert _rows(conn) == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _report(conn).aligned


# ---------------------------------------------------------------------------
# tiering: prune_hot and compact_database
# ---------------------------------------------------------------------------


def test_prune_hot_still_evicts_when_only_the_hot_tier_has_vectors(tiered):
    """Lane C §4: embeddings are never synced, so they must not block eviction.

    ``_archive_context_complete`` requires every table in its comparison set to
    match row-for-row between hot and full. ``message_embeddings`` is derived and
    deliberately unsynced, so its presence in that set would fail the proof the
    moment one hot vector existed and ``prune_hot`` would silently stop evicting
    anything. Migration 48's commit closes that two ways — it dropped the literal
    entry from the set and subtracts ``_DERIVED_TABLES`` afterwards — and this
    test is bound to the outcome, not to either mechanism: restoring the literal
    *and* dropping the subtraction makes the assertion below fail.
    """
    from agent_session_tools import tiering

    _make_hot(tiered["hot"], sessions=2)
    tiering.sync_to_full()

    hot = sqlite3.connect(tiered["hot"])
    _vector(hot, "s0-m0", 0)
    _vector(hot, "s0-m0", 1)
    _vector(hot, "s1-m1", 0)
    hot.commit()
    assert _rows(hot) == 3
    hot.close()

    full = sqlite3.connect(tiered["full"])
    assert _rows(full) == 0, "embeddings are derived data and are never synced"
    full.close()

    probe = sqlite3.connect(tiered["hot"])
    probe.execute("ATTACH DATABASE ? AS full", (str(tiered["full"]),))
    assert tiering._archive_context_complete(probe) is True, (
        "a hot-only vector must not count against the whole-context retention proof"
    )
    probe.close()

    stats = tiering.prune_hot(days=30, dry_run=False, vacuum=False)

    assert stats.sessions_deleted == 2
    assert stats.skipped_unverified == 0 and stats.skipped_anchored == 0
    after = sqlite3.connect(tiered["hot"])
    assert _rows(after) == 0, "eviction removed the vectors with their messages"
    assert after.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert after.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _report(after).aligned
    after.close()

    survivor = sqlite3.connect(tiered["full"])
    assert survivor.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
    survivor.close()


def test_compact_database_copies_the_vectors_with_no_orphans(tmp_path):
    """No virtual table lives in ``sessions.db``, so compaction is a plain copy."""
    from agent_session_tools import tiering

    source = tmp_path / "bloated.db"
    _make_hot(source, sessions=2, days_old=0)
    conn = sqlite3.connect(source)
    _vector(conn, "s0-m0", 0)
    _vector(conn, "s0-m0", 1)
    _vector(conn, "s1-m0", 0)
    conn.commit()
    conn.close()

    dest = tmp_path / "clean.db"
    stats = tiering.compact_database(source, dest)

    assert stats.tables_copied["message_embeddings"] == 3
    assert stats.tables_copied["messages"] == 4
    clean = sqlite3.connect(dest)  # a plain connection: no extension loaded
    try:
        assert _rows(clean) == 3
        report = _report(clean)
        assert report.rows == 3
        assert report.orphaned == 0 and report.stale == 0
        assert report.model_mismatch == 0 and report.hidden == 0
        assert report.aligned
        assert clean.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert clean.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            clean.execute(
                "SELECT embedding FROM message_embeddings WHERE message_id='s0-m0' AND chunk_ix=1"
            ).fetchone()[0]
            == VEC
        )
    finally:
        clean.close()


# ---------------------------------------------------------------------------
# hidden source
# ---------------------------------------------------------------------------


def test_a_retired_source_is_never_eligible_and_its_vectors_are_swept(tmp_path):
    """D-6: a source retired after embedding leaves vectors the read path cannot see."""
    conn = _db(tmp_path / "sessions.db")
    _session(conn, "admitted", source="kiro_cli")
    _session(conn, "retired", source="aider")
    _message(conn, "a1", "admitted")
    _message(conn, "h1", "retired")
    _message(conn, "h2", "retired", role="assistant")
    _vector(conn, "a1", 0)
    _vector(conn, "h1", 0)
    _vector(conn, "h1", 1)
    _vector(conn, "h2", 0)
    conn.commit()

    report = _report(conn)
    assert report.eligible == 1, "a retired source is outside the eligibility predicate"
    assert report.missing == 0 and report.embedded == 1
    assert report.rows == 4 and report.hidden == 3
    assert not report.aligned

    swept = align.sweep(conn, model=MODEL, dim=DIM)
    conn.commit()

    assert swept.hidden == 3 and swept.deleted == 3
    assert _rows(conn) == 1 and _rows(conn, "a1") == 1
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 3, (
        "sweeping a hidden vector never deletes the conversation behind it"
    )
    after = _report(conn)
    assert after.hidden == 0
    assert after.aligned and after.complete
