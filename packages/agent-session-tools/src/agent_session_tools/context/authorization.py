"""Shared concept-authorization seam: current standing plus scope-visible roots.

``projection.py`` (disposable Markdown projection) and ``recall.py``
(concept-first retrieval) must agree on exactly one answer to "which concept
roots may this caller see right now" -- retired concepts excluded, bound roots
visible only through their citation closure, legacy roots visible only through
their claimed session's scope visibility. This module is that one seam; both
callers use it instead of re-deriving the selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from .public import AgentContext

from .concept_schema import verify_installed_schema


@dataclass(frozen=True)
class AuthorizedConcept:
    """One non-retired concept root, visible under the caller's pinned scope.

    ``root`` is the full ``context_concepts`` row (as a plain column-name-keyed
    dict) returned by ``_ConceptRepository.authorized_root`` -- the same
    visibility check used for lifecycle transitions and legacy binding.
    ``citations`` holds every exact citation for a bound root, sorted
    deterministically by ``(evidence_id, start_offset, end_offset)``; it is
    always empty for a legacy-unbound root.
    """

    concept_id: str
    standing: str
    root: dict[str, Any]
    citations: tuple[dict[str, Any], ...] = ()


def _current_standings(context: AgentContext) -> list[tuple[str, str]]:
    """Every concept id's current standing under the deterministic event order.

    Ties break exactly as ``concepts.py``'s ``current_event`` does: retired >
    accepted > proposed, then logical clock, origin instance/seq, then event id.
    """
    return [
        (cast(str, row[0]), cast(str, row[1]))
        for row in context.conn.execute(
            """WITH ranked AS (
                 SELECT concept_id,standing,
                   row_number() OVER (
                     PARTITION BY concept_id
                     ORDER BY CASE standing WHEN 'retired' THEN 2
                                            WHEN 'accepted' THEN 1 ELSE 0 END DESC,
                              logical_time DESC,origin_instance DESC,origin_seq DESC,id DESC
                   ) AS position
                 FROM context_concept_events
               )
               SELECT c.id,r.standing
               FROM context_concepts c
               JOIN ranked r ON r.concept_id=c.id AND r.position=1
               ORDER BY c.id"""
        )
    ]


def authorized_concepts(
    context: AgentContext, *, project: str | None = None
) -> tuple[AuthorizedConcept, ...]:
    """Every non-retired concept visible under ``context``'s pinned scope.

    ``project`` must equal the project ``context`` itself was opened with --
    ``AgentContext`` already enforces project scoping at construction time, so
    a caller passing a different value here is a programming error, not a data
    condition to filter on.

    A store that has never had the concept sidecar schema installed (no
    wind-down/import has ever run against it) provably has zero concepts;
    that is answered here as an empty tuple rather than a schema-mismatch
    error, so a read-only caller like ``recall()`` can still search sessions.
    Callers that need schema *presence* itself verified up front (projection
    already does, via ``_require_concept_schema``) are unaffected: they fail
    before ever reaching this function.
    """
    if project != context.project:
        raise ValueError("authorized_concepts project must match the open context")
    installed = (
        context.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_concepts'"
        ).fetchone()
        is not None
    )
    if not installed:
        return ()
    from .concepts import _ConceptRepository

    verify_installed_schema(context.conn)
    repository = _ConceptRepository(context.conn)
    result: list[AuthorizedConcept] = []
    for concept_id, standing in _current_standings(context):
        if standing == "retired":
            continue
        root = repository.authorized_root(context, concept_id)
        if root is None:
            continue
        citations: tuple[dict[str, Any], ...] = ()
        if root["binding_state"] == "bound":
            assertion = context._assertion(cast(str, root["assertion_id"]))
            if assertion is None:
                # The two visibility checks run in the same pinned snapshot, so
                # this is unreachable in practice; treat it as unavailable
                # rather than trusting a root this seam cannot re-verify.
                continue
            citations = tuple(
                sorted(
                    cast(list[dict[str, Any]], assertion["citations"]),
                    key=lambda citation: (
                        cast(str, citation["evidence_id"]),
                        cast(int, citation["start_offset"]),
                        cast(int, citation["end_offset"]),
                    ),
                )
            )
        result.append(
            AuthorizedConcept(
                concept_id=concept_id, standing=standing, root=root, citations=citations
            )
        )
    return tuple(result)
