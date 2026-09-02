"""Concept management: seed from config, list, and query."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import NamedTuple

from . import _connection

logger = logging.getLogger(__name__)


class ConceptSummary(NamedTuple):
    id: str
    name: str
    domain: str
    description: str | None


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
    except (sqlite3.OperationalError, Exception):
        return 0
    finally:
        conn.close()


def list_concepts(domain: str | None = None) -> list[ConceptSummary]:
    """List all concepts, optionally filtered by domain."""
    conn = _connection._connect()
    if not conn:
        return []
    try:
        if domain:
            rows = conn.execute(
                "SELECT id, name, domain, description FROM concepts WHERE domain = ? ORDER BY name",
                (domain,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, domain, description FROM concepts ORDER BY domain, name"
            ).fetchall()
        return [ConceptSummary(id=r[0], name=r[1], domain=r[2], description=r[3]) for r in rows]
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
