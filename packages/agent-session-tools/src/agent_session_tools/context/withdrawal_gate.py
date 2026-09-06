"""Shared read predicates for pending replica withdrawal, including retained rows."""

import re


def available(conn, schema="main"):
    if not re.fullmatch(r"[A-Za-z_]\w*", schema):
        raise ValueError("Unsupported withdrawal schema")
    return bool(
        conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name='context_replica_denials'"
        ).fetchone()
    )


def predicate(conn, kind, column, *, schema="main"):
    if kind not in (
        "session",
        "evidence",
        "assertion",
        "relation",
        "observation",
        "record",
    ) or not re.fullmatch(r"[A-Za-z_]\w*\.[A-Za-z_]\w*", column):
        raise ValueError("Unsupported withdrawal predicate")
    if not available(conn, schema):
        return "1"
    return f"NOT EXISTS (SELECT 1 FROM {schema}.context_replica_denials denied WHERE denied.kind='{kind}' AND denied.object_id={column} AND denied.status!='released')"
