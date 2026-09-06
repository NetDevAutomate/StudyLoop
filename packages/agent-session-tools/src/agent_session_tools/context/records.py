"""Explicit ownership and scoped SQL for existing application records.

These rows are mutable application state, not captured evidence. The registry
owns their privacy boundary and deletion dependency; it does not attest content.
All SQL identifiers are internal and restricted. Callers own the transaction.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from .legacy import legacy_global_visible
from .provenance import Scope
from .learner_schema import TABLES
from .scope import ScopeError, active_policy, visibility_sql
from .store import _hash, _json, _now


def connect(path):
    """Open the canonical application schema; migration failures remain failures."""
    from ..migrations import migrate

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        path.chmod(0o600)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='sessions'"
        ).fetchone():
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                + files("agent_session_tools").joinpath("schema.sql").read_text()
                + "\nCOMMIT;"
            )
        migrate(conn)
        return conn
    except BaseException:
        conn.close()
        raise


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
    return _visible_sql(conn, table, column, active_policy())


def _visible_sql(conn, table, column, policy, *, scope=None):
    _table(table)
    if not re.fullmatch(r"[A-Za-z_]\w*\.[A-Za-z_]\w*", column):
        raise ValueError("Invalid internal record SQL identifier")
    scope = policy.request_scope() if scope is None else scope
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
    if table in ("parked_topics", "study_notes"):
        parent, parent_values = _visible_sql(
            conn, "study_sessions", "parent.id", policy, scope=scope
        )
        owned = (
            "("
            + owned
            + " AND NOT EXISTS (SELECT 1 FROM context_record_study_links link "
            + (
                "JOIN context_record_owners dep ON dep.id=link.record_id "
                f"WHERE dep.table_name=? AND dep.row_id=CAST({column} AS TEXT) "
                "AND NOT EXISTS (SELECT 1 FROM study_sessions parent "
                "WHERE parent.id=link.study_session_id AND " + parent + ")))"
            )
        )
        values.extend([table, *parent_values])
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
    study_session_id: str | None = None,
    owner_path: Path | None = None,
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
    session_id, project_id, explicit_scope = _owner(
        conn,
        session_id=session_id,
        study_session_id=study_session_id,
        owner_path=owner_path,
    )
    if study_session_id and table not in ("parked_topics", "study_notes"):
        raise ValueError("Unsupported study-record dependency")
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
    if study_session_id:
        conn.execute(
            "INSERT INTO context_record_study_links VALUES (?,?)",
            (owner_id, study_session_id),
        )
    return owner_id


def request_scope(conn):
    policy = active_policy()
    scope = policy.request_scope()
    visibility_sql(conn, "s.id", policy=policy, scope=scope)
    return scope.value


def _owner(conn, *, session_id=None, study_session_id=None, owner_path=None):
    policy = active_policy()
    scope = policy.request_scope()
    source, values = visibility_sql(conn, "s.id", policy=policy, scope=scope)
    parent = None
    if study_session_id:
        if not is_visible(conn, "study_sessions", study_session_id):
            raise ScopeError("Study session is unavailable in the configured scope")
        parent = conn.execute(
            "SELECT session_id,project_id,scope FROM context_record_owners "
            "WHERE table_name='study_sessions' AND row_id=?",
            (study_session_id,),
        ).fetchone()
        if parent is None and not legacy_global_visible(conn):
            raise ScopeError("Study session has no ownership")
    project = policy.project_for_path(owner_path or Path.cwd())
    if owner_path and project and project.scope != scope:
        raise ScopeError("Record working directory is outside the requested scope")
    if project and project.scope != scope:
        project = None
    if session_id is not None:
        if not conn.execute(
            "SELECT 1 FROM sessions s WHERE s.id=? AND " + source, [session_id, *values]
        ).fetchone():
            raise ScopeError("Source session is unavailable in the configured scope")
        project_id, explicit_scope = None, None
    else:
        if parent is not None:
            return tuple(parent)
        project_id = project.id if project else None
        explicit_scope = None if project else scope.value
    return session_id, project_id, explicit_scope


def owner_key(conn, *, session_id=None, study_session_id=None):
    """Exact provenance identity for deduplication, not a guessed semantic identity."""
    owner = _owner(conn, session_id=session_id, study_session_id=study_session_id)
    return _hash(_json([*owner, study_session_id]))


def ensure_study_reference(conn, *, session_id=None, study_session_id=None):
    """An application study placeholder may be owned; a native session is never invented."""
    if session_id:
        _owner(conn, session_id=session_id)
    if study_session_id:
        if not conn.execute(
            "SELECT 1 FROM study_sessions WHERE id=?", (study_session_id,)
        ).fetchone():
            conn.execute(
                "INSERT INTO study_sessions(id,started_at) VALUES (?,?)",
                (study_session_id, _now()),
            )
            bind(conn, "study_sessions", study_session_id, session_id=session_id)
        if not is_visible(conn, "study_sessions", study_session_id):
            raise ScopeError("Study session is unavailable in the configured scope")


def observation_clause(conn, policy, *, scope=None):
    """All application dependencies must be visible before observation text is read."""
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_record_observations'"
    ).fetchone():
        return "1", []
    options, values = [], []
    for table in TABLES:
        clause, params = _visible_sql(conn, table, "dep.row_id", policy, scope=scope)
        options.append("(dep.table_name=? AND " + clause + ")")
        values.extend([table, *params])
    return (
        "NOT EXISTS (SELECT 1 FROM context_record_observations link "
        "JOIN context_record_owners dep ON dep.id=link.record_id "
        "WHERE link.observation_id=o.id AND NOT (" + " OR ".join(options) + "))",
        values,
    )


def link_observation(conn, record_id, observation_id):
    if (
        record_id is None
        or not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='context_record_observations'"
        ).fetchone()
    ):
        return
    if not conn.in_transaction:
        raise RuntimeError("Record observation links require a write transaction")
    owner = conn.execute(
        "SELECT table_name,row_id FROM context_record_owners WHERE id=?", (record_id,)
    ).fetchone()
    if owner is None or not is_visible(conn, owner[0], owner[1]):
        raise ScopeError("Observation record dependency is unavailable")
    from .observations import ObservationStore

    if ObservationStore(conn).get(observation_id) is None:
        raise ScopeError("Observation is unavailable")
    conn.execute(
        "INSERT OR IGNORE INTO context_record_observations VALUES (?,?)",
        (record_id, observation_id),
    )
