"""Refuse legacy SQL transfer once explicit scope or modern context is present.

This protects the old entry points while the structured coordinator is integrated.
It does not make legacy SQL a supported scoped replication protocol.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import re

from ..config_loader import load_config

MESSAGE = (
    "Legacy SQL sync cannot transfer scoped or source-grounded memory. "
    "The structured sync coordinator and lifecycle reconciliation are required; "
    "this build does not yet expose that complete path. No legacy fallback is allowed."
)


class LegacySyncRefused(RuntimeError):
    """Protected memory needs the structured protocol, never executable SQL."""


def check_config(config):
    memory = config.get("memory", {})
    if not isinstance(memory, dict) or (
        memory.get("projects")
        or memory.get("sync")
        or memory.get("default_scope") not in (None, "unclassified")
    ):
        raise LegacySyncRefused(MESSAGE)


def _protected(tables, schema=None):
    """(table, existence predicate) pairs; metadata-only, no identities or bodies."""
    if schema is not None and not re.fullmatch(r"[A-Za-z_]\w*", schema):
        raise ValueError("Invalid internal legacy schema")
    for table in sorted(tables):
        if (
            not table.startswith("context_")
            or table in ("context_access_state", "context_replica_content_state")
            or table.startswith("context_evidence_fts_")
        ):
            continue
        quoted = '"' + table.replace('"', '""') + '"'
        if schema is not None:
            quoted = f"{schema}.{quoted}"
        condition = (
            " WHERE applied_at IS NOT NULL"
            if table == "context_policy_state"
            else " WHERE mode!='ordinary'"
            if table == "context_lifecycle_mode"
            else ""
        )
        yield table, f"SELECT 1 FROM {quoted}{condition} LIMIT 1"


def protected_queries(tables, schema=None):
    """Metadata-only existence predicates; no source identities or bodies returned."""
    for _table, query in _protected(tables, schema):
        yield query


def refusal_message(tables):
    """The fixed refusal plus the protected table(s) that hold rows.

    Every current-schema export writes ``context_evidence``; a delete writes
    ``context_tombstones`` (and its retirement/erasure markers); parking seeds
    ``context_board_columns``. Naming the trigger lets a learner tell which it was.
    """
    return MESSAGE + " Protected rows found in: " + ", ".join(sorted(tables)) + "."


def check_database(conn, schema="main"):
    if not re.fullmatch(r"[A-Za-z_]\w*", schema):
        raise ValueError("Invalid internal legacy schema")
    tables = {
        r[0]
        for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"
        )
    }
    offending = [
        table
        for table, query in _protected(tables, schema)
        if conn.execute(query).fetchone()
    ]
    if offending:
        raise LegacySyncRefused(refusal_message(offending))


def check_path(path, *, whole_file=False):
    check_config(load_config())
    path = Path(path).expanduser().resolve()
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            check_database(conn)
            if (
                whole_file
                and conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='context_projects'"
                ).fetchone()
            ):
                # Whole files include free pages and derived indexes, not merely
                # the currently visible rows inspected by the legacy guard.
                raise LegacySyncRefused(MESSAGE)


def transaction_guard(tables):
    """Run inside the transfer transaction, before source selection or body writes."""
    checks = list(protected_queries(tables))
    if not checks:
        return ""
    return (
        "CREATE TEMP TABLE legacy_sync_guard(allowed INTEGER CHECK(allowed=0));\n"
        + "".join(
            "INSERT INTO legacy_sync_guard SELECT 1 WHERE EXISTS(" + query + ");\n"
            for query in checks
        )
        + "DROP TABLE legacy_sync_guard;\n"
    )
