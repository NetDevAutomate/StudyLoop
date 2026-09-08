"""Concept-first, AND-to-OR recall over authorized concepts and raw sessions.

Ported from SessionWeaver v0.2.0. Recall reuses the B3 authorization seam,
queries no embeddings or ontology tables, and returns concepts before
source-session-deduplicated raw text hits.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from .context.authorization import AuthorizedConcept, authorized_concepts
from .context.public import AgentContext, open_context
from .context.scope import visibility_sql
from .query_planner import QueryPlan, plan

_CONCEPT_FTS_LIMIT = 200
_PROVENANCE_BOUND = "machine-confirmed citation"
_PROVENANCE_LEGACY = "legacy-unbound (session-level provenance)"


@dataclass(frozen=True)
class Citation:
    evidence_id: str
    start: int
    end: int

    def to_dict(self) -> dict[str, object]:
        return {"evidence_id": self.evidence_id, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class ConceptHit:
    concept_id: str
    kind: str
    title: str
    statement: str
    standing: str
    binding_state: str
    confidence: float
    source_session_id: str | None
    provenance_label: str
    citations: tuple[Citation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "concept_id": self.concept_id,
            "kind": self.kind,
            "title": self.title,
            "statement": self.statement,
            "standing": self.standing,
            "binding_state": self.binding_state,
            "confidence": self.confidence,
            "source_session_id": self.source_session_id,
            "provenance_label": self.provenance_label,
            "citations": [citation.to_dict() for citation in self.citations],
        }


@dataclass(frozen=True)
class SessionHit:
    session_id: str
    source: str
    project_path: str | None
    updated_at: str | None
    preview: str

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "source": self.source,
            "project_path": self.project_path,
            "updated_at": self.updated_at,
            "preview": self.preview,
        }


@dataclass(frozen=True)
class RecallReport:
    concepts: tuple[ConceptHit, ...]
    sessions: tuple[SessionHit, ...]
    plan: QueryPlan
    k: int
    project: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "concepts": [concept.to_dict() for concept in self.concepts],
            "sessions": [session.to_dict() for session in self.sessions],
            "plan": self.plan.to_dict(),
            "k": self.k,
            "project": self.project,
        }


def _concept_hit(authorized: AuthorizedConcept) -> ConceptHit:
    root = authorized.root
    bound = cast(str, root["binding_state"]) == "bound"
    citations = tuple(
        Citation(
            evidence_id=cast(str, citation["evidence_id"]),
            start=cast(int, citation["start_offset"]),
            end=cast(int, citation["end_offset"]),
        )
        for citation in authorized.citations
    )
    return ConceptHit(
        concept_id=authorized.concept_id,
        kind=cast(str, root["kind"]),
        title=cast(str, root["title"]),
        statement=cast(str, root["statement"]),
        standing=authorized.standing,
        binding_state=cast(str, root["binding_state"]),
        confidence=float(cast(float, root["confidence"])),
        source_session_id=cast(str | None, root["source_session_id"]),
        provenance_label=_PROVENANCE_BOUND if bound else _PROVENANCE_LEGACY,
        citations=citations,
    )


def _fts_ranked_concept_ids(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = _CONCEPT_FTS_LIMIT,
    offset: int = 0,
) -> list[str]:
    if not query:
        return []
    rows = conn.execute(
        "SELECT concept_id FROM context_concept_fts"
        " WHERE context_concept_fts MATCH ?"
        " ORDER BY bm25(context_concept_fts), concept_id"
        " LIMIT ? OFFSET ?",
        (query, limit, offset),
    ).fetchall()
    return [cast(str, row[0]) for row in rows]


def _select_concepts(
    conn: sqlite3.Connection,
    authorized_by_id: dict[str, AuthorizedConcept],
    and_query: str,
    or_query: str,
    k: int,
) -> tuple[tuple[ConceptHit, ...], bool]:
    selected: list[ConceptHit] = []
    seen: set[str] = set()
    fallback_used = False
    if not authorized_by_id:
        return (), fallback_used
    for query, is_fallback in ((and_query, False), (or_query, True)):
        if not query or len(selected) >= k:
            continue
        offset = 0
        while len(selected) < k:
            ranked_ids = _fts_ranked_concept_ids(conn, query, offset=offset)
            if not ranked_ids:
                break
            offset += len(ranked_ids)
            for concept_id in ranked_ids:
                if concept_id in seen:
                    continue
                seen.add(concept_id)
                authorized = authorized_by_id.get(concept_id)
                if authorized is None:
                    continue
                selected.append(_concept_hit(authorized))
                if is_fallback:
                    fallback_used = True
                if len(selected) == k:
                    break
            if len(ranked_ids) < _CONCEPT_FTS_LIMIT:
                break
    return tuple(selected), fallback_used


def _project_clause(context: AgentContext) -> tuple[str, tuple[object, ...]]:
    if context.project is None:
        return "", ()
    return (
        " AND EXISTS (SELECT 1 FROM context_session_projects sp"
        " WHERE sp.session_id=s.id AND sp.project_id=?)",
        (context.project,),
    )


def _select_sessions(
    context: AgentContext,
    and_query: str,
    or_query: str,
    k: int,
    exclude_session_ids: frozenset[str],
) -> tuple[tuple[SessionHit, ...], bool]:
    visibility_clause, visibility_params = visibility_sql(
        context.conn, "s.id", policy=context.policy, scope=context.scope
    )
    project_clause, project_params = _project_clause(context)
    selected: list[SessionHit] = []
    seen: set[str] = set(exclude_session_ids)
    fallback_used = False
    for query, is_fallback in ((and_query, False), (or_query, True)):
        if not query or len(selected) >= k:
            continue
        excluded = tuple(sorted(seen))
        exclusion_clause = ""
        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            exclusion_clause = f" AND m.session_id NOT IN ({placeholders})"
        sql = (
            "WITH ranked_messages AS ("
            " SELECT m.id AS message_id, m.session_id, s.source, s.project_path,"
            " s.updated_at, substr(m.content,1,300) AS preview,"
            " m.timestamp AS message_timestamp, bm25(messages_fts) AS match_rank"
            " FROM messages_fts"
            " JOIN messages m ON m.rowid=messages_fts.rowid"
            " JOIN sessions s ON s.id=m.session_id"
            f" WHERE messages_fts MATCH ? AND {visibility_clause}{project_clause}"
            f"{exclusion_clause}"
            "), best_messages AS ("
            " SELECT *, row_number() OVER ("
            " PARTITION BY session_id"
            " ORDER BY match_rank, message_timestamp DESC, message_id"
            " ) AS session_position"
            " FROM ranked_messages"
            ")"
            " SELECT session_id, source, project_path, updated_at, preview"
            " FROM best_messages"
            " WHERE session_position=1"
            " ORDER BY match_rank, message_timestamp DESC, session_id, message_id"
            " LIMIT ?"
        )
        rows = context.conn.execute(
            sql,
            (
                query,
                *visibility_params,
                *project_params,
                *excluded,
                k - len(selected),
            ),
        ).fetchall()
        for session_id, source, project_path, updated_at, preview in rows:
            seen.add(cast(str, session_id))
            selected.append(
                SessionHit(
                    session_id=cast(str, session_id),
                    source=cast(str, source),
                    project_path=cast(str | None, project_path),
                    updated_at=cast(str | None, updated_at),
                    preview=cast(str, preview),
                )
            )
            if is_fallback:
                fallback_used = True
    return tuple(selected), fallback_used


def recall(
    db: Path,
    question: str,
    *,
    k: int = 5,
    project: str | None = None,
) -> RecallReport:
    """Return authorized concepts first, then deduplicated raw-text sessions."""
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 50:
        raise ValueError("k must be an integer between 1 and 50")
    query_plan = plan(question)
    with open_context(db, project=project) as context:
        authorized_by_id = {
            authorized.concept_id: authorized
            for authorized in authorized_concepts(context, project=context.project)
        }
        concepts, concept_fallback = _select_concepts(
            context.conn,
            authorized_by_id,
            query_plan.and_query,
            query_plan.or_query,
            k,
        )
        exclude_session_ids = frozenset(
            concept.source_session_id
            for concept in concepts
            if concept.source_session_id
        )
        sessions, session_fallback = _select_sessions(
            context,
            query_plan.and_query,
            query_plan.or_query,
            k,
            exclude_session_ids,
        )
    return RecallReport(
        concepts=concepts,
        sessions=sessions,
        plan=replace(
            query_plan,
            fallback_used=concept_fallback or session_fallback,
        ),
        k=k,
        project=project,
    )
