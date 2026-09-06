"""Scoped graph contributions; a source relationship is not semantic validation.

Reports use the memory package's immutable observations. Bridges are projected
from their current owned rows, so corrections/deletions need no copied-edge
repair. Same-label contributions keep separate provenance identities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_session_tools.context import records
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.scope import active_policy
from agent_session_tools.context.store import _hash, _json

if TYPE_CHECKING:
    import sqlite3

CONCEPT = "studyloop.concept"
DEPENDENCY = "studyloop.dependency"


def available(conn: sqlite3.Connection) -> bool:
    return bool(
        conn.execute("SELECT 1 FROM sqlite_master WHERE name='context_observations'").fetchone()
    )


def legacy_subject_visible(conn, kind: str, subject: str) -> bool:
    """A copied legacy aggregate cannot revive a replaced or forgotten report."""
    if not available(conn):
        return True
    digest = _hash(_json([kind, subject]))
    return not conn.execute(
        "SELECT 1 FROM context_observations WHERE subject_sha256=? "
        "UNION ALL SELECT 1 FROM context_observation_retired_subjects "
        "WHERE subject_sha256=? LIMIT 1",
        (digest, digest),
    ).fetchone()


def report(conn, kind: str, subject: str, payload: dict) -> str:
    """Explicit report update, limited to this owner and this trusted adapter."""
    if not conn.in_transaction:
        raise RuntimeError("Graph reports require an owned write transaction")
    policy = active_policy()
    scope = policy.request_scope()
    from pathlib import Path

    project = policy.project_for_path(Path.cwd())
    owner = {
        "project_id": project.id if project and project.scope == scope else None,
        "fixed_scope": None if project and project.scope == scope else scope.value,
    }
    store = ObservationStore(conn)
    previous = [
        r
        for r in store.list(kind, subject=subject)
        if r["owner"] == owner and r["producer"] == "studyloop.graph.report"
    ]
    if len(previous) == 1 and previous[0]["payload"] == payload:
        return previous[0]["id"]
    return store.append(
        kind=kind,
        subject=subject,
        payload=payload,
        producer="studyloop.graph.report",
        authority="reported",
        supersedes=[r["id"] for r in previous],
    )


def reports(conn, kind: str, *, subject: str | None = None) -> list[dict]:
    if not available(conn):
        return []
    return [
        {
            **r["payload"],
            "id": r["id"],
            "provenance": {
                "kind": "owned_report",
                "observation_id": r["id"],
                "binding_sha256": r["binding_sha256"],
                "owner": r["owner"],
                "authority": r["authority"],
                "semantic_validation": "not_established",
                "confidence_meaning": "reported_weight_not_probability",
            },
        }
        for r in ObservationStore(conn).list(kind, subject=subject)
    ]


def bridges(conn, topic: str | None = None) -> list[dict]:
    """Scope predicates run before labels/mappings are selected from the source."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_bridges'").fetchone():
        return []
    clause, values = records.visible_sql(conn, "knowledge_bridges")
    if topic is not None:
        clause += " AND (lower(r.source_domain)=? OR lower(r.target_domain)=?)"
        values.extend([topic.lower(), topic.lower()])
    rows = conn.execute(
        "SELECT r.id,r.source_concept,r.source_domain,r.target_concept,r.target_domain,"
        "r.structural_mapping,r.quality,r.created_by FROM knowledge_bridges r WHERE "
        + clause
        + " ORDER BY r.id",
        values,
    ).fetchall()
    result = []
    for row in rows:
        source = dict(row)
        owner = (
            conn.execute(
                "SELECT id FROM context_record_owners "
                "WHERE table_name='knowledge_bridges' AND row_id=?",
                (str(row["id"]),),
            ).fetchone()
            if records.available(conn)
            else None
        )
        result.append(
            {
                **source,
                "provenance": {
                    "kind": "application_record",
                    "table": "knowledge_bridges",
                    "record_id": row["id"],
                    "owner_id": owner[0] if owner else None,
                    "snapshot_sha256": _hash(_json(source)),
                    "authority": "reported",
                    "semantic_validation": "not_established",
                    "confidence_meaning": "display_weight_not_probability",
                    "quality_report": row["quality"],
                    "structural_mapping": row["structural_mapping"],
                    "source_domain": row["source_domain"],
                    "target_domain": row["target_domain"],
                    "decision_role": "analogy_context_only",
                },
            }
        )
    return result


def concept_rows(conn, domain: str | None = None) -> list[dict]:
    rows = [r for r in reports(conn, CONCEPT) if domain is None or r["domain"] == domain]
    for bridge in bridges(conn, domain):
        for end in ("source", "target"):
            item_domain = bridge[f"{end}_domain"].lower()
            if domain is not None and item_domain != domain:
                continue
            rows.append(
                {
                    "id": f"bridge:{bridge['provenance']['owner_id'] or bridge['id']}:{end}",
                    "name": bridge[f"{end}_concept"].lower(),
                    "domain": item_domain,
                    "description": bridge["structural_mapping"],
                    "provenance": bridge["provenance"],
                }
            )
    return rows


def dependency_rows(conn, topic: str) -> list[dict]:
    rows = [r for r in reports(conn, DEPENDENCY) if r["topic"] == topic]
    for bridge in bridges(conn, topic):
        rows.append(
            {
                "topic": topic,
                "source_concept": bridge["source_concept"].lower(),
                "target_concept": bridge["target_concept"].lower(),
                "relation_type": "bridge",
                "evidence": f"knowledge_bridges:{bridge['id']}",
                "source_type": "knowledge_bridge",
                "confidence": 0.0,
                "provenance": bridge["provenance"],
            }
        )
    return rows
