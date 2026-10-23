"""The FTS invariant covers ``context_evidence_fts`` as well as ``messages_fts``.

``context_evidence_fts`` is an external-content FTS5 table: ``SELECT count(*)``
on it reads the content table, so its own index cardinality is the row count of
its ``_docsize`` shadow (one row per indexed document). A drifted evidence index
went unreported because ``fts_integrity`` looked at messages only (council pass
7, Q4; remediation plan 6, lane T unit T6 / R13).
"""

from __future__ import annotations

import sqlite3

from agent_session_tools.export_sessions import init_db
from agent_session_tools.tiering import FtsIntegrity, fts_integrity, repair_fts

EVIDENCE = (
    "INSERT INTO context_evidence VALUES (?,'k','s','codex','jsonl','/x','v1','m',"
    "NULL,'2026-01-01',?,'sha','conversation_message',NULL,NULL,NULL,NULL)"
)


def _db(tmp_path) -> sqlite3.Connection:
    conn = init_db(str(tmp_path / "sessions.db"))
    conn.execute("INSERT INTO sessions(id,source) VALUES ('s','codex')")
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('m','s','user','hello')"
    )
    for i in range(3):
        conn.execute(EVIDENCE, (f"e{i}", f"evidence body {i} decorators"))
    conn.commit()
    return conn


def test_fts_integrity_covers_context_evidence(tmp_path):
    conn = _db(tmp_path)
    healthy = fts_integrity(conn)
    assert healthy.healthy
    assert (healthy.evidence_rows, healthy.evidence_fts_rows) == (3, 3)

    # Drop one document from the index without touching the evidence row.
    conn.execute(
        "INSERT INTO context_evidence_fts(context_evidence_fts, rowid, body) "
        "SELECT 'delete', rowid, body FROM context_evidence WHERE id='e0'"
    )
    conn.commit()
    lost = fts_integrity(conn)
    assert lost.drift == 0, "messages_fts is untouched"
    assert lost.evidence_drift == -1
    assert not lost.healthy

    repaired = repair_fts(conn)
    assert repaired.healthy
    assert (repaired.evidence_rows, repaired.evidence_fts_rows) == (3, 3)
    hits = conn.execute(
        "SELECT count(*) FROM context_evidence_fts WHERE context_evidence_fts MATCH 'decorators'"
    ).fetchone()[0]
    assert hits == 3
    conn.close()


def test_a_ghost_evidence_index_row_is_drift(tmp_path):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO context_evidence_fts(rowid, body) VALUES (999, 'ghost')")
    conn.commit()
    assert fts_integrity(conn).evidence_drift == 1
    assert repair_fts(conn).evidence_drift == 0
    conn.close()


def test_positional_construction_still_means_messages_only():
    assert FtsIntegrity(10, 10).healthy
    assert FtsIntegrity(10, 12).drift == 2
    assert not FtsIntegrity(10, 10, 4, 3).healthy


def test_a_database_without_the_evidence_index_is_still_checked(tmp_path):
    """Doctor and older databases call these on a messages-only schema."""
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.execute(
        "CREATE TABLE messages (id TEXT, session_id TEXT, role TEXT, content TEXT)"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE messages_fts USING fts5(content, session_id, role)"
    )
    conn.execute("INSERT INTO messages VALUES ('m','s','user','hello')")
    conn.execute(
        "INSERT INTO messages_fts(rowid,content,session_id,role) VALUES (1,'hello','s','user')"
    )
    conn.commit()
    result = fts_integrity(conn)
    assert result.healthy and result.evidence_rows == 0
    assert repair_fts(conn).healthy
    conn.close()


def test_fts_check_names_evidence_drift_and_fix_repairs_it(tmp_path):
    from typer.testing import CliRunner

    from agent_session_tools.maintenance import app

    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO context_evidence_fts(context_evidence_fts, rowid, body) "
        "SELECT 'delete', rowid, body FROM context_evidence WHERE id='e1'"
    )
    conn.commit()
    conn.close()
    db = str(tmp_path / "sessions.db")
    runner = CliRunner()
    check = runner.invoke(app, ["fts-check", "--db", db])
    assert check.exit_code == 1, check.output
    assert "context_evidence_fts" in check.output and "drift -1" in check.output
    fixed = runner.invoke(app, ["fts-check", "--db", db, "--fix"])
    assert fixed.exit_code == 0, fixed.output
    assert runner.invoke(app, ["fts-check", "--db", db]).exit_code == 0
