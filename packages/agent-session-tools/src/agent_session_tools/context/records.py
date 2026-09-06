"""Explicit ownership and scoped SQL for existing application records.

These rows are mutable application state, not captured evidence. The registry
owns their privacy boundary and deletion dependency; it does not attest content.
All SQL identifiers are internal and restricted. Callers own the transaction.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .legacy import legacy_global_visible
from .provenance import Scope
from .record_schema import TABLES
from .scope import ScopeError, active_policy, visibility_sql
from .store import _now


def available(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_record_owners'"
        ).fetchone()
        is not None
    )


@contextmanager
def policy_guard(conn: sqlite3.Connection):
    """Validate policy inside a caller-owned write transaction and before commit."""
    if not conn.in_transaction:
        raise RuntimeError("Policy guard requires a write transaction")
    policy = active_policy()
    scope = policy.request_scope()
    visibility_sql(conn, "s.id", policy=policy, scope=scope)
    yield
    latest = active_policy()
    if latest.digest != policy.digest or latest.request_scope() != scope:
        raise ScopeError(
            "Context scope changed during the write; retry after policy apply"
        )


def _table(table: str) -> None:
    if table not in TABLES:
        raise ValueError("Unsupported owned record table")


def visible_sql(
    conn: sqlite3.Connection, table: str, column: str = "r.id"
) -> tuple[str, list]:
    """Filter before reading bodies/counts/LIMIT; retain a consistent read snapshot."""
    _table(table)
    if not re.fullmatch(r"[A-Za-z_]\w*\.[A-Za-z_]\w*", column):
        raise ValueError("Invalid internal record SQL identifier")
    policy = active_policy()
    scope = policy.request_scope()
    source, source_values = visibility_sql(
        conn, "own.session_id", policy=policy, scope=scope
    )
    has_assignments = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_session_projects'"
    ).fetchone()
    legacy = scope == Scope.UNCLASSIFIED and (
        not has_assignments
        or not conn.execute("SELECT 1 FROM context_session_projects LIMIT 1").fetchone()
    )
    if not available(conn):
        return ("1" if legacy else "0"), []
    projects = [p.id for p in policy.projects if p.scope == scope]
    owned_project = "0"
    project_values = []
    if projects:
        owned_project = (
            "own.project_id IN (SELECT p.id FROM context_projects p WHERE p.scope=? "
            f"AND p.id IN ({','.join('?' for _ in projects)}))"
        )
        project_values = [scope.value, *projects]
    owned = (
        "EXISTS (SELECT 1 FROM context_record_owners own WHERE own.table_name=? "
        f"AND own.row_id=CAST({column} AS TEXT) AND ("
        "(own.session_id IS NOT NULL AND EXISTS (SELECT 1 FROM sessions native "
        "WHERE native.id=own.session_id) AND "
        + source
        + ") OR "
        + owned_project
        + " OR own.scope=?))"
    )
    values = [table, *source_values, *project_values, scope.value]
    if legacy:
        owned = (
            "(" + owned + " OR NOT EXISTS (SELECT 1 FROM context_record_owners unowned "
            f"WHERE unowned.table_name=? AND unowned.row_id=CAST({column} AS TEXT)))"
        )
        values.append(table)
    return owned, values


def is_visible(conn: sqlite3.Connection, table: str, identity: str | int) -> bool:
    where, values = visible_sql(conn, table)
    return (
        conn.execute(
            f"SELECT 1 FROM {table} r WHERE r.id=? AND " + where, [identity, *values]
        ).fetchone()
        is not None
    )


def bind(
    conn: sqlite3.Connection,
    table: str,
    identity: str | int,
    *,
    session_id: str | None = None,
) -> str | None:
    """Bind a just-inserted row inside its write transaction, never reclassify it.

    A native session reference follows that session's current classification.
    Otherwise configured CWD project or explicit process/default scope owns it.
    Legacy schemas permit only the existing explicit unclassified operation.
    """
    _table(table)
    if not conn.in_transaction:
        raise RuntimeError("Insert and ownership binding require one write transaction")
    policy = active_policy()
    scope = policy.request_scope()
    source, values = visibility_sql(conn, "s.id", policy=policy, scope=scope)
    if not available(conn):
        if not legacy_global_visible(conn):
            raise ScopeError("Learning record ownership needs database migration")
        return None
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (identity,)).fetchone():
        raise ValueError("Cannot own a nonexistent record")
    existing = conn.execute(
        "SELECT id FROM context_record_owners WHERE table_name=? AND row_id=?",
        (table, str(identity)),
    ).fetchone()
    if existing:
        raise ValueError("Record already has immutable ownership")
    project = policy.project_for_path(Path.cwd())
    if project and project.scope != scope:
        project = None
    if session_id is not None:
        if not conn.execute(
            "SELECT 1 FROM sessions s WHERE s.id=? AND " + source, [session_id, *values]
        ).fetchone():
            raise ScopeError("Source session is unavailable in the configured scope")
        project_id, explicit_scope = None, None
    else:
        project_id = project.id if project else None
        explicit_scope = None if project else scope.value
    owner_id = uuid4().hex
    conn.execute(
        "INSERT INTO context_record_owners VALUES (?,?,?,?,?,?,?)",
        (
            owner_id,
            table,
            str(identity),
            session_id,
            project_id,
            explicit_scope,
            _now(),
        ),
    )
    return owner_id
