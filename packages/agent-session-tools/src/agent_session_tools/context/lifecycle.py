"""Canonical local purging, permanent retirement and physical cleanup.

Peer withdrawal/acknowledgement and managed backup restore are separate operations.
These helpers never claim those have occurred from a local database transaction.
"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from uuid import uuid4

from ..migrations import CURRENT_VERSION
from . import records
from .scope import ScopeError, active_policy, retirement_selection_sql
from .store import ContextStore, _now


def require_schema(conn):
    if not 41 <= conn.execute("PRAGMA user_version").fetchone()[0] <= CURRENT_VERSION:
        raise RuntimeError("Lifecycle operations require a supported schema41 or later")


@contextmanager
def eviction(conn):
    """Internal reversible purge mode, held only inside the caller's transaction."""
    require_schema(conn)
    if not conn.in_transaction:
        raise RuntimeError("Eviction mode requires an existing write transaction")
    if (
        conn.execute("SELECT mode FROM context_lifecycle_mode WHERE id=1").fetchone()[0]
        != "ordinary"
    ):
        raise RuntimeError("A lifecycle operation is already active")
    conn.execute("UPDATE context_lifecycle_mode SET mode='evict' WHERE id=1")
    try:
        yield
    finally:
        # SQLite may abort the entire transaction (for example RAISE(ROLLBACK)).
        # That already restored ordinary mode. Do not start a new transaction
        # while unwinding the original error.
        if conn.in_transaction:
            conn.execute("UPDATE context_lifecycle_mode SET mode='ordinary' WHERE id=1")


@contextmanager
def selected_records(conn, session_id):
    """Capture IDs before cascades/SET NULL can detach older learner rows."""
    prefix = "purge_" + uuid4().hex
    study = prefix + "_study"
    selected = prefix + "_records"
    conn.execute(f"CREATE TEMP TABLE {study}(id TEXT PRIMARY KEY)")
    conn.execute(
        f"""INSERT INTO {study} SELECT s.id FROM study_sessions s
        LEFT JOIN context_record_owners own ON own.table_name='study_sessions' AND own.row_id=s.id
        WHERE s.session_id=? OR own.session_id=?""",
        (session_id, session_id),
    )
    conn.execute(
        f"CREATE TEMP TABLE {selected}(table_name TEXT,row_id TEXT,PRIMARY KEY(table_name,row_id))"
    )
    try:
        for table in records.TABLES:
            predicate = "own.session_id=?"
            values = [table, session_id]
            if table in (
                "study_sessions",
                "teach_back_scores",
                "parked_topics",
                "study_notes",
            ):
                predicate += " OR r.session_id=?"
                values.append(session_id)
            if table in ("parked_topics", "study_notes"):
                predicate += f" OR r.study_session_id IN (SELECT id FROM {study})"
            conn.execute(
                f"""INSERT INTO {selected} SELECT ?,CAST(r.id AS TEXT) FROM {table} r
                LEFT JOIN context_record_owners own ON own.table_name='{table}' AND own.row_id=CAST(r.id AS TEXT)
                WHERE {predicate}""",
                values,
            )
        yield selected
    finally:
        conn.execute(f"DROP TABLE IF EXISTS {selected}")
        conn.execute(f"DROP TABLE IF EXISTS {study}")


def purge_session(conn, session_id, *, permanent=True):
    """Trusted storage operation; caller authorizes scope and owns the transaction."""
    require_schema(conn)
    if (
        not conn.in_transaction
        or conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1
    ):
        raise RuntimeError(
            "Session purge requires a transaction with foreign keys enabled"
        )
    mode = conn.execute(
        "SELECT mode FROM context_lifecycle_mode WHERE id=1"
    ).fetchone()[0]
    if mode != ("ordinary" if permanent else "evict"):
        raise RuntimeError("Purge mode does not match the requested lifecycle action")
    with selected_records(conn, session_id) as selected:
        if permanent:
            conn.execute(
                "INSERT OR IGNORE INTO context_tombstones VALUES (?,?,?)",
                (session_id, uuid4().hex, _now()),
            )
        # Sources purge source-linked observations, assertions, reviews and edges.
        conn.execute("DELETE FROM context_evidence WHERE session_id=?", (session_id,))
        conn.execute(
            "DELETE FROM context_observations WHERE id IN (SELECT observation_id FROM context_observation_session_owners WHERE session_id=?)",
            (session_id,),
        )
        for table in (
            *[t for t in records.TABLES if t != "study_sessions"],
            "study_sessions",
        ):
            conn.execute(
                f"DELETE FROM {table} WHERE CAST(id AS TEXT) IN (SELECT row_id FROM {selected} WHERE table_name=?)",
                (table,),
            )
        conn.execute(
            "DELETE FROM context_record_owners WHERE session_id=?", (session_id,)
        )
        conn.execute(
            "DELETE FROM message_concepts WHERE message_id IN (SELECT id FROM messages WHERE session_id=?)",
            (session_id,),
        )
        # Explicit FTS deletion also removes old orphan rows from earlier REPLACE imports.
        conn.execute("DELETE FROM messages_fts WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        for table in (
            "session_notes",
            "session_tags",
            "session_learning_metadata",
            "file_references",
            "scrub_log",
            "session_embeddings",
            "context_session_projects",
        ):
            conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        # Eviction also needs file cleanup, but must not create permanent controls.
        conn.execute(
            "INSERT INTO context_erasure_pending VALUES (1,?) ON CONFLICT(id) DO UPDATE SET requested_at=excluded.requested_at",
            (_now(),),
        )
    if conn.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError(
            "Purge violated a database dependency; transaction must roll back"
        )


def forget_session(conn, session_id: str, *, apply: bool = False):
    """Scope-authorized local forget; preview returns counts without source bodies."""
    if not isinstance(session_id, str) or not session_id or len(session_id) > 512:
        raise ValueError("Invalid session identity")
    require_schema(conn)
    policy = active_policy()
    scope = policy.request_scope()
    with ContextStore(conn)._atomic():
        clause, values = retirement_selection_sql(conn, policy=policy, scope=scope)
        if not conn.execute(
            "SELECT 1 FROM sessions s WHERE s.id=? AND " + clause, [session_id, *values]
        ).fetchone():
            raise ScopeError("Session is unavailable in the configured scope")
        counts = {
            table: conn.execute(
                f"SELECT count(*) FROM {table} WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            for table in ("messages", "context_evidence")
        }
        with selected_records(conn, session_id) as selected:
            counts["learner_records"] = conn.execute(
                f"SELECT count(*) FROM {selected}"
            ).fetchone()[0]
        if apply:
            conn.execute("PRAGMA secure_delete=ON")
            purge_session(conn, session_id)
        latest = active_policy()
        if latest != policy or latest.request_scope() != scope:
            raise ScopeError("Scope changed during forgetting; no change committed")
        return {
            "session_id": session_id,
            "applied": apply,
            "selected_counts": counts,
            "scope": scope.value,
            "replica_reconciliation": "not_performed",
            "canonical_file_cleanup": "pending" if apply else "not_requested",
            "managed_restore_reconciled": False,
        }


def reconcile_local_retirements(conn):
    """Reapply durable intent before compaction/managed restore can serve old rows."""
    require_schema(conn)
    with ContextStore(conn)._atomic():
        conn.execute("""INSERT OR IGNORE INTO context_tombstones
            SELECT object_id,lower(hex(randomblob(16))),retired_at
            FROM context_retirements WHERE kind='session'""")
        present = [
            r[0]
            for r in conn.execute(
                "SELECT s.id FROM sessions s JOIN context_tombstones t ON t.session_id=s.id"
            )
        ]
        for identity in present:
            purge_session(conn, identity)
        for kind, table in (
            ("record", "context_record_owners"),
            ("evidence", "context_evidence"),
            ("assertion", "context_assertions"),
            ("relation", "context_relations"),
            ("observation", "context_observations"),
        ):
            conn.execute(
                f"DELETE FROM {table} WHERE id IN (SELECT object_id FROM context_retirements WHERE kind=?)",
                (kind,),
            )
        conn.execute(
            "DELETE FROM context_observations WHERE id IN (SELECT observation_id FROM context_observation_tombstones)"
        )


def compact(path: Path):
    """Compact canonical DB/WAL after commit; a busy reader leaves durable pending work."""
    conn = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=rw", uri=True, timeout=1
    )
    try:
        require_schema(conn)
        conn.execute("PRAGMA foreign_keys=ON")
        with ContextStore(conn)._atomic():
            reconcile_local_retirements(conn)
            conn.execute(
                "INSERT INTO context_erasure_pending VALUES (1,?) "
                "ON CONFLICT(id) DO UPDATE SET requested_at=excluded.requested_at",
                (_now(),),
            )
            # messages_fts owns its text, so its own FTS 'rebuild' would preserve
            # stale rows. Reconstruct from live canonical messages instead.
            conn.execute("DELETE FROM messages_fts")
            conn.execute("""INSERT INTO messages_fts(rowid,content,session_id,role)
                SELECT rowid,content,session_id,role FROM messages WHERE content IS NOT NULL""")
            conn.execute(
                "INSERT INTO context_evidence_fts(context_evidence_fts) VALUES ('rebuild')"
            )
            conn.execute(
                "DELETE FROM message_embeddings WHERE message_id NOT IN (SELECT id FROM messages)"
            )
            conn.execute(
                "DELETE FROM session_embeddings WHERE session_id NOT IN (SELECT id FROM sessions)"
            )
            # Bind the completion guard to exactly the reconciled snapshot.
            # A control arriving after this transaction must remain pending.
            revision = conn.execute(
                "SELECT revision FROM context_access_state WHERE id=1"
            ).fetchone()[0]
        conn.execute("PRAGMA secure_delete=ON")
        if conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
            return {"complete": False, "reason": "database_in_use"}
        conn.execute("VACUUM")
        if conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
            return {"complete": False, "reason": "database_in_use"}
        conn.execute("BEGIN IMMEDIATE")
        if (
            conn.execute(
                "SELECT revision FROM context_access_state WHERE id=1"
            ).fetchone()[0]
            != revision
        ):
            conn.rollback()
            return {"complete": False, "reason": "state_changed_during_cleanup"}
        conn.execute("DELETE FROM context_erasure_pending WHERE id=1")
        conn.commit()
        if conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
            conn.execute(
                "INSERT OR REPLACE INTO context_erasure_pending VALUES (1,?)", (_now(),)
            )
            conn.commit()
            return {"complete": False, "reason": "database_in_use"}
        if conn.execute("SELECT 1 FROM context_erasure_pending").fetchone():
            return {"complete": False, "reason": "new_cleanup_pending"}
        return {"complete": True, "coverage": "canonical_database_and_wal_only"}
    except sqlite3.OperationalError:
        conn.rollback()
        return {"complete": False, "reason": "database_maintenance_unavailable"}
    finally:
        conn.close()
