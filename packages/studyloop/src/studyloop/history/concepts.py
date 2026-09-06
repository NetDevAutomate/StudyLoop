"""Concept management: seed from config, list, and query."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import NamedTuple

from agent_session_tools.context.legacy import legacy_global_visible
from agent_session_tools.context.scope import ScopeError
from agent_session_tools.context.store import _json

from . import _connection, graph

logger = logging.getLogger(__name__)


class ConceptSummary(NamedTuple):
    id: str
    name: str
    domain: str
    description: str | None
    provenance: dict | None = None


def seed_concepts_from_config() -> int:
    """Create concept rows from configured topics + tags.

    Returns the number of concepts seeded.
    """
    conn = _connection._connect()
    if not conn:
        return 0

    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "concepts" not in tables:
            return 0

        # Config paths have not yet acquired source ownership. Do not copy
        # globally loaded tags into whichever classified scope is active.
        if not legacy_global_visible(conn):
            raise ScopeError(
                "Config concept import requires classified file ownership; "
                "use unclassified inspection"
            )
        conn.rollback()

        from ..topics import get_topics

        count = 0
        for topic in get_topics():
            domain = topic.name.lower()
            for tag in topic.tags:
                name = tag.lower().strip()
                concept_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{domain}:{name}"))
                conn.execute(
                    "INSERT OR IGNORE INTO concepts (id, name, domain) VALUES (?, ?, ?)",
                    (concept_id, name, domain),
                )
                count += 1

        conn.commit()
        return count
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("seed_concepts_from_config failed: %s", exc)
            raise
        return 0
    finally:
        conn.close()


def list_concepts(domain: str | None = None) -> list[ConceptSummary]:
    """List all concepts, optionally filtered by domain."""
    conn = _connection._connect()
    if not conn:
        return []
    try:
        result = [
            ConceptSummary(r["id"], r["name"], r["domain"], r.get("description"), r["provenance"])
            for r in graph.concept_rows(conn, domain)
        ]
        if not legacy_global_visible(conn):
            return sorted(result, key=lambda r: (r.domain, r.name, r.id))
        if domain:
            rows = conn.execute(
                "SELECT id, name, domain, description FROM concepts WHERE domain = ? ORDER BY name",
                (domain,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, domain, description FROM concepts ORDER BY domain, name"
            ).fetchall()
        result.extend(
            ConceptSummary(
                id=r[0],
                name=r[1],
                domain=r[2],
                description=r[3],
                provenance={
                    "kind": "unclassified_legacy",
                    "semantic_validation": "not_established",
                },
            )
            for r in rows
            if graph.legacy_subject_visible(conn, graph.CONCEPT, _json([r[2], r[1]]))
        )
        return sorted(result, key=lambda r: (r.domain, r.name, r.id))
    except sqlite3.OperationalError as exc:
        # R-22b: a bare `except sqlite3.OperationalError: return []` cannot
        # tell a genuinely missing table (an old schema, pre-migration --
        # safe to treat as "no concepts") apart from a real lock/timeout
        # fault, which used to read back indistinguishably as "no concepts
        # exist" instead of surfacing the failure.
        if not _connection.is_missing_table_error(exc):
            logger.warning("list_concepts failed: %s", exc)
            raise
        return []
    finally:
        conn.close()


def record_concept(name: str, domain: str, description: str | None = None) -> str | None:
    """Explicitly report a concept in the current owner scope, without file import."""
    name, domain = name.strip().lower(), domain.strip().lower()
    if not name or not domain:
        raise ValueError("Concept needs a name and domain")
    conn = _connection._connect()
    if conn is None:
        return None
    try:
        with _connection.owned_write(conn):
            return graph.report(
                conn,
                graph.CONCEPT,
                _json([domain, name]),
                {"name": name, "domain": domain, "description": description},
            )
    finally:
        conn.close()
