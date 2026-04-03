"""Knowledge bridge CRUD and graph migration."""

from __future__ import annotations

import sqlite3
import uuid

from . import _connection


def record_bridge(
    source_concept: str,
    source_domain: str,
    target_concept: str,
    target_domain: str,
    structural_mapping: str | None = None,
    quality: str = "proposed",
    created_by: str = "agent",
) -> bool:
    """Record a knowledge bridge between two concepts."""
    conn = _connection._connect()
    if not conn:
        return False
    try:
        conn.execute(
            """
            INSERT INTO knowledge_bridges
                (source_concept, source_domain, target_concept, target_domain,
                 structural_mapping, quality, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_concept,
                source_domain,
                target_concept,
                target_domain,
                structural_mapping,
                quality,
                created_by,
            ),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def get_bridges(
    target_domain: str | None = None,
    source_domain: str | None = None,
    quality: str | None = None,
) -> list[dict]:
    """Get knowledge bridges, optionally filtered."""
    conn = _connection._connect()
    if not conn:
        return []
    try:
        conditions = []
        params: list[str] = []
        if target_domain:
            conditions.append("target_domain = ?")
            params.append(target_domain)
        if source_domain:
            conditions.append("source_domain = ?")
            params.append(source_domain)
        if quality:
            conditions.append("quality = ?")
            params.append(quality)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"""
            SELECT id, source_concept, source_domain, target_concept, target_domain,
                   structural_mapping, quality, times_used, times_helpful,
                   created_by, created_at
            FROM knowledge_bridges
            {where}
            ORDER BY times_helpful DESC, created_at DESC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def update_bridge_usage(bridge_id: int, helpful: bool) -> bool:
    """Record that a bridge was used, and whether it was helpful."""
    conn = _connection._connect()
    if not conn:
        return False
    try:
        helpful_increment = 1 if helpful else 0
        conn.execute(
            """
            UPDATE knowledge_bridges
            SET times_used = times_used + 1,
                times_helpful = times_helpful + ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (helpful_increment, bridge_id),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def migrate_bridges_to_graph() -> int:
    """One-time migration of knowledge_bridges -> concept graph.

    Creates concept rows and analogy_to relations from existing bridges.
    Returns the number of bridges migrated.
    """
    conn = _connection._connect()
    if not conn:
        return 0

    try:
        # Check if both tables exist
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "knowledge_bridges" not in tables or "concepts" not in tables:
            return 0

        bridges = conn.execute(
            """
            SELECT source_concept, source_domain, target_concept, target_domain,
                   structural_mapping, quality, created_by
            FROM knowledge_bridges
            """
        ).fetchall()

        count = 0
        for b in bridges:
            src_name = b["source_concept"].lower()
            tgt_name = b["target_concept"].lower()
            src_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{b['source_domain']}:{src_name}"))
            tgt_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{b['target_domain']}:{tgt_name}"))

            conn.execute(
                "INSERT OR IGNORE INTO concepts (id, name, domain) VALUES (?, ?, ?)",
                (src_id, src_name, b["source_domain"]),
            )
            conn.execute(
                "INSERT OR IGNORE INTO concepts (id, name, domain) VALUES (?, ?, ?)",
                (tgt_id, tgt_name, b["target_domain"]),
            )

            quality = b["quality"]
            confidence = 1.0 if quality == "effective" else 0.7 if quality == "validated" else 0.3

            conn.execute(
                """
                INSERT OR IGNORE INTO concept_relations
                    (source_concept_id, target_concept_id, relation_type,
                     confidence, created_by)
                VALUES (?, ?, 'analogy_to', ?, ?)
                """,
                (src_id, tgt_id, confidence, b["created_by"]),
            )
            count += 1

        conn.commit()
        return count
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()
