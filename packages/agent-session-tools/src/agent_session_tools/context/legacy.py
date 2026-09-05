"""Scoped reads shared by legacy CLI/MCP formatters.

No migration or classification is performed while answering a query. These helpers
return only rows visible under the explicitly configured current context scope.
"""

import sqlite3

from .provenance import Scope
from .scope import active_policy, visibility_sql


def legacy_global_visible(conn: sqlite3.Connection) -> bool:
    """Merged legacy derivations have no trustworthy classified ownership.

    Explicit unclassified inspection is retained only for an entirely unassigned
    database. A pointer to the latest source cannot label a merged record.
    """
    policy = active_policy()
    scope = policy.request_scope()
    visibility_sql(conn, "s.id", policy=policy, scope=scope)
    if scope != Scope.UNCLASSIFIED:
        return False
    has_assignments = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_session_projects'"
    ).fetchone()
    return (
        not has_assignments
        or not conn.execute("SELECT 1 FROM context_session_projects LIMIT 1").fetchone()
    )


def session_record(conn: sqlite3.Connection, session_id: str):
    clause, params = visibility_sql(conn, "s.id")
    return conn.execute(
        "SELECT s.* FROM sessions s WHERE s.id=? AND " + clause, (session_id, *params)
    ).fetchone()


def session_ids(conn: sqlite3.Connection, *, source: str, limit: int | None = None):
    """Select IDs within policy before handing them to a transcript consumer."""
    clause, params = visibility_sql(conn, "s.id")
    query = (
        "SELECT s.id FROM sessions s WHERE s.source=? AND "
        + clause
        + " ORDER BY s.updated_at DESC,s.id"
    )
    values = [source, *params]
    if limit is not None:
        if type(limit) is not int or limit < 1:
            raise ValueError("Session limit must be a positive integer")
        query += " LIMIT ?"
        values.append(limit)
    return [row[0] for row in conn.execute(query, values)]


def session_messages(
    conn: sqlite3.Connection, session_id: str, *, last_n: int | None = None
):
    clause, params = visibility_sql(conn, "m.session_id")
    query = "SELECT m.* FROM messages m WHERE m.session_id=? AND " + clause
    values = [session_id, *params]
    if last_n is not None:
        if type(last_n) is not int or last_n < 1:
            raise ValueError("Message limit must be a positive integer")
        query = (
            "SELECT * FROM ("
            + query
            + " ORDER BY timestamp DESC,seq DESC LIMIT ?) ORDER BY timestamp,seq"
        )
        values.append(last_n)
    else:
        query += " ORDER BY seq,timestamp"
    return conn.execute(query, values).fetchall()
