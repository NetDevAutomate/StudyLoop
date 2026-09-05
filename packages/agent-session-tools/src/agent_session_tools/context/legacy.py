"""Scoped reads shared by legacy CLI/MCP formatters.

No migration or classification is performed while answering a query. These helpers
return only rows visible under the explicitly configured current context scope.
"""

import sqlite3

from .scope import visibility_sql


def session_record(conn: sqlite3.Connection, session_id: str):
    clause, params = visibility_sql(conn, "s.id")
    return conn.execute(
        "SELECT s.* FROM sessions s WHERE s.id=? AND " + clause, (session_id, *params)
    ).fetchone()


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
