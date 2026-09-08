"""Transactional concept/evidence/lifecycle core behind one deep service seam."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from ..config_loader import get_db_path, load_config
from .public import MAX_BODY_CHARS, AgentContext, open_context
from .scope import ScopeError, visibility_sql

from .concept_schema import _MAX_COUNTER, _ensure_schema
from .okf_import import (
    _SESSION_ID,
    _SESSION_URI_PREFIX,
    MAX_ERROR_ENTRIES,
    ImportReport,
    _OKFRecord,
    _OKFScan,
    _scan_okf,
)
from .okf_import import ImportError as OKFImportError
from .projection import ProjectionReport, project_concepts
from .winddown import (
    _Concept,
    _Issue,
    _parse_bind_document,
    _parse_winddown,
    _Quote,
)

Standing = Literal["proposed", "accepted", "retired"]
TransitionStanding = Literal["accepted", "retired"]


@dataclass(frozen=True)
class BatchResult:
    """Outcome of an atomic wind-down batch."""

    writes: int
    concept_ids: tuple[str, ...] = ()
    errors: tuple[_Issue, ...] = ()


@dataclass(frozen=True)
class TransitionResult:
    """Outcome of one lifecycle transition."""

    writes: int
    concept_id: str
    standing: str | None = None
    event_id: str | None = None
    errors: tuple[_Issue, ...] = ()


@dataclass(frozen=True)
class BindResult:
    """Outcome of atomically binding one legacy root."""

    writes: int
    legacy_concept_id: str
    concept_id: str | None = None
    assertion_id: str | None = None
    errors: tuple[_Issue, ...] = ()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _error(path: str, code: str, message: str) -> _Issue:
    return _Issue(path=path, code=code, message=message)


def _call_text(value: object, path: str, maximum: int) -> _Issue | None:
    if not isinstance(value, str):
        return _error(path, "invalid_type", "Value must be text")
    if not value.strip():
        return _error(path, "blank", "Value must not be blank")
    if len(value.strip()) > maximum:
        return _error(path, "too_long", f"Value must be at most {maximum} code points")
    return None


def _rows(
    conn: sqlite3.Connection, sql: str, params: Sequence[object] = ()
) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor]


class _EvidenceResolver:
    """Resolve exact citations after applying the pinned context visibility policy."""

    def __init__(self, context: AgentContext, session_id: str) -> None:
        self._context = context
        self._session_id = session_id
        self._sources: dict[str, str] | None = None
        self._sources_degrade_oversized: bool | None = None
        self._oversized_evidence_count = 0

    def _visible_sources(self, *, degrade_oversized: bool = False) -> dict[str, str]:
        """Return every scope-visible evidence body for the claimed session.

        When ``degrade_oversized`` is false (the default, used by wind-down and
        explicit bind citation resolution), a body over the upstream bounded
        reader's ``MAX_BODY_CHARS`` limit raises exactly as before -- this
        method's contract is otherwise unchanged for those callers.

        When ``degrade_oversized`` is true (used only by ``import_okf``'s
        per-record classification), any evidence row whose body exceeds
        ``MAX_BODY_CHARS`` is excluded from the returned mapping instead of
        raising, and counted in ``self._oversized_evidence_count``. The oversized
        body itself is never loaded into memory: its length is checked directly
        against the already-fetched ``context_evidence.body`` column length.

        The cache is keyed on ``degrade_oversized``: every caller of one
        resolver instance must agree on the flag, since a mismatched second
        call would otherwise silently return the first call's degraded (or
        undegraded) mapping under the other mode.
        """
        if self._sources is not None:
            if degrade_oversized != self._sources_degrade_oversized:
                raise RuntimeError(
                    "_visible_sources was called with a different degrade_oversized flag"
                )
            return self._sources
        store_clause, store_params = self._context.store._where(self._context.access)
        visibility_clause, visibility_params = visibility_sql(
            self._context.conn,
            "e.session_id",
            policy=self._context.policy,
            scope=self._context.scope,
        )
        rows = self._context.conn.execute(
            """SELECT e.id, length(e.body) FROM context_evidence e
               LEFT JOIN context_session_projects sp ON sp.session_id=e.session_id
               LEFT JOIN context_projects p ON p.id=sp.project_id
               WHERE e.session_id=? AND """
            + store_clause
            + " AND "
            + visibility_clause
            + " ORDER BY e.id",
            (self._session_id, *store_params, *visibility_params),
        ).fetchall()
        sources: dict[str, str] = {}
        oversized_evidence_count = 0
        for identity, body_length in rows:
            if (
                degrade_oversized
                and body_length is not None
                and body_length > MAX_BODY_CHARS
            ):
                oversized_evidence_count += 1
                continue
            source = self._context._source(identity)
            if source is not None:
                sources[identity] = source["body"]
        self._sources = sources
        self._sources_degrade_oversized = degrade_oversized
        self._oversized_evidence_count = oversized_evidence_count
        return sources

    @staticmethod
    def _occurrences(body: str, quote: str) -> list[int]:
        starts: list[int] = []
        offset = body.find(quote)
        while offset >= 0:
            starts.append(offset)
            offset = body.find(quote, offset + 1)
        return starts

    def resolve(
        self, quotes: Sequence[_Quote], *, path: str
    ) -> tuple[tuple[dict[str, object], ...], tuple[_Issue, ...]]:
        sources = self._visible_sources()
        citations: list[dict[str, object]] = []
        issues: list[_Issue] = []
        seen: set[tuple[str, int, int, str]] = set()
        for index, locator in enumerate(quotes):
            quote_path = f"{path}/{index}"
            citation: tuple[str, int, int, str] | None = None
            if locator.evidence_id is not None:
                body = sources.get(locator.evidence_id)
                if body is None:
                    issues.append(
                        _error(
                            quote_path,
                            "evidence_unavailable",
                            "Evidence is unavailable in the requested session and scope",
                        )
                    )
                    continue
                assert locator.start is not None and locator.end is not None
                if (
                    locator.end > len(body)
                    or body[locator.start : locator.end] != locator.quote
                ):
                    issues.append(
                        _error(
                            quote_path,
                            "locator_mismatch",
                            "Locator does not bind the literal quote to this evidence version",
                        )
                    )
                    continue
                citation = (
                    locator.evidence_id,
                    locator.start,
                    locator.end,
                    locator.quote,
                )
            else:
                matches = [
                    (identity, start, start + len(locator.quote), locator.quote)
                    for identity, body in sources.items()
                    for start in self._occurrences(body, locator.quote)
                ]
                if not matches:
                    issues.append(
                        _error(
                            quote_path,
                            "quote_not_found",
                            "Literal quote was not found in visible evidence for this session",
                        )
                    )
                    continue
                if len(matches) > 1:
                    issues.append(
                        _error(
                            quote_path,
                            "ambiguous_quote",
                            "Literal quote has multiple visible occurrences; supply a locator",
                        )
                    )
                    continue
                citation = matches[0]
            if citation in seen:
                issues.append(
                    _error(
                        quote_path,
                        "duplicate_citation",
                        "Resolved citations must be unique",
                    )
                )
                continue
            seen.add(citation)
            citations.append(
                {
                    "evidence_id": citation[0],
                    "start": citation[1],
                    "end": citation[2],
                    "quote": citation[3],
                }
            )
        return tuple(citations), tuple(issues)


class _ConceptRepository:
    """Private SQL adapter for immutable roots, events, clocks, and FTS."""

    def __init__(
        self, conn: sqlite3.Connection, *, now: Callable[[], str] | None = None
    ) -> None:
        self.conn = conn
        self._now = now or globals()["_now"]

    def _checkpoint(self, name: str) -> None:
        """No-op fault boundary monkeypatched by rollback tests."""

    def _allocate(self) -> tuple[str, int, int]:
        maximum = self.conn.execute(
            "SELECT COALESCE(max(logical_time),0) FROM context_concept_events"
        ).fetchone()[0]
        expected = self.conn.execute(
            "SELECT instance FROM context_access_state WHERE id=1"
        ).fetchone()
        clock = self.conn.execute(
            """SELECT origin_instance,origin_seq,logical_time
               FROM context_concept_clock WHERE id=1"""
        ).fetchone()
        if expected is None or clock is None or clock[0] != expected[0]:
            raise RuntimeError("Concept clock is unavailable or changed identity")
        if (
            type(maximum) is not int
            or type(clock[1]) is not int
            or type(clock[2]) is not int
            or maximum < 0
            or not 0 <= clock[1] <= _MAX_COUNTER
            or not 0 <= clock[2] <= _MAX_COUNTER
        ):
            raise RuntimeError("Concept clock counters are invalid")
        if (
            maximum >= _MAX_COUNTER
            or clock[1] >= _MAX_COUNTER
            or clock[2] >= _MAX_COUNTER
        ):
            raise RuntimeError("Concept clock counter space is exhausted")
        row = self.conn.execute(
            """UPDATE context_concept_clock
               SET origin_seq=origin_seq+1,
                   logical_time=max(logical_time,?)+1
               WHERE id=1 AND origin_instance=?
                 AND origin_seq=? AND logical_time=?
               RETURNING origin_instance,origin_seq,logical_time""",
            (maximum, clock[0], clock[1], clock[2]),
        ).fetchone()
        if row is None:
            raise RuntimeError("Concept clock is unavailable or changed identity")
        self._checkpoint("after_clock")
        return cast(tuple[str, int, int], tuple(row))

    def append_event(
        self,
        *,
        concept_id: str,
        parent_event_id: str | None,
        standing: Standing,
        actor: str,
        reason: str,
    ) -> str:
        origin_instance, origin_seq, logical_time = self._allocate()
        display_timestamp = self._now()
        payload = {
            "concept_id": concept_id,
            "parent_event_id": parent_event_id,
            "standing": standing,
            "actor": actor,
            "reason": reason,
            "display_timestamp": display_timestamp,
            "origin_instance": origin_instance,
            "origin_seq": origin_seq,
            "logical_time": logical_time,
        }
        identity = _hash_payload(payload)
        self.conn.execute(
            """INSERT INTO context_concept_events(
               id,concept_id,initial_concept_id,parent_event_id,standing,actor,reason,
               display_timestamp,origin_instance,origin_seq,logical_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                identity,
                concept_id,
                concept_id if parent_event_id is None else None,
                parent_event_id,
                standing,
                actor,
                reason,
                display_timestamp,
                origin_instance,
                origin_seq,
                logical_time,
            ),
        )
        self._checkpoint("after_event")
        return identity

    def insert_bound(
        self,
        *,
        assertion_id: str,
        origin: Literal["winddown", "legacy-bind"],
        kind: str,
        title: str,
        statement: str,
        tags: Sequence[str],
        confidence: float,
        source_session_id: str,
        source_uri: str,
        producer: str,
        legacy_file_sha256: str | None = None,
        supersedes_concept_id: str | None = None,
    ) -> str:
        self.conn.execute(
            """INSERT INTO context_concepts(
               id,assertion_id,binding_state,origin,kind,title,statement,canonical_tags,
               confidence,source_session_id,source_uri,producer,created_at,
               legacy_file_sha256,supersedes_concept_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                assertion_id,
                assertion_id,
                "bound",
                origin,
                kind,
                title,
                statement,
                _canonical_json(sorted(tags)),
                confidence,
                source_session_id,
                source_uri,
                producer,
                self._now(),
                legacy_file_sha256,
                supersedes_concept_id,
            ),
        )
        self._checkpoint("after_root")
        return assertion_id

    def seed_legacy(
        self,
        *,
        original_bytes: bytes,
        kind: str,
        title: str,
        statement: str,
        tags: Sequence[str],
        confidence: float,
        source_session_id: str | None,
        source_uri: str,
        producer: str,
        event_actor: str | None = None,
    ) -> str:
        """Insert one immutable legacy root and its initial proposed event."""
        if not isinstance(original_bytes, bytes):
            raise ValueError("Legacy identity requires original file bytes")
        digest = hashlib.sha256(original_bytes).hexdigest()
        identity = "legacy:" + digest
        self.conn.execute(
            """INSERT INTO context_concepts(
               id,assertion_id,binding_state,origin,kind,title,statement,canonical_tags,
               confidence,source_session_id,source_uri,producer,created_at,
               legacy_file_sha256,supersedes_concept_id)
               VALUES (?,NULL,'legacy-unbound','legacy-okf',?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                identity,
                kind,
                title,
                statement,
                _canonical_json(sorted(tags)),
                confidence,
                source_session_id,
                source_uri,
                producer,
                self._now(),
                digest,
            ),
        )
        self._checkpoint("after_root")
        self.append_event(
            concept_id=identity,
            parent_event_id=None,
            standing="proposed",
            actor=event_actor or producer,
            reason="legacy import",
        )
        return identity

    def current_event(self, concept_id: str) -> dict[str, Any]:
        # Frozen cross-machine standing order (design.md): the winner is
        # max(events, key=(lamport, machine_id, event_id)) -- nothing else.
        # Locally allocated events already have strictly increasing lamports,
        # so this matches the reference's single-database behaviour; under
        # replication only the pure triple decides, never standing kind.
        rows = _rows(
            self.conn,
            """SELECT * FROM context_concept_events WHERE concept_id=?
               ORDER BY logical_time DESC,origin_instance DESC,origin_seq DESC,id DESC
               LIMIT 1""",
            (concept_id,),
        )
        if not rows:
            raise RuntimeError("Concept has no lifecycle event")
        return rows[0]

    @staticmethod
    def _session_visible(context: AgentContext, session_id: str) -> bool:
        clause, params = visibility_sql(
            context.conn,
            "s.id",
            policy=context.policy,
            scope=context.scope,
        )
        project_clause = ""
        project_params: tuple[object, ...] = ()
        if context.project is not None:
            project_clause = (
                " AND EXISTS (SELECT 1 FROM context_session_projects sp "
                "WHERE sp.session_id=s.id AND sp.project_id=?)"
            )
            project_params = (context.project,)
        return (
            context.conn.execute(
                "SELECT 1 FROM sessions s WHERE s.id=? AND " + clause + project_clause,
                (session_id, *params, *project_params),
            ).fetchone()
            is not None
        )

    def authorized_root(
        self, context: AgentContext, concept_id: str
    ) -> dict[str, Any] | None:
        head = self.conn.execute(
            """SELECT assertion_id,binding_state,source_session_id
               FROM context_concepts WHERE id=?""",
            (concept_id,),
        ).fetchone()
        if head is None:
            return None
        assertion_id, binding_state, source_session_id = head
        if binding_state == "bound":
            if assertion_id is None or context._assertion(assertion_id) is None:
                return None
        elif source_session_id is None or not self._session_visible(
            context, source_session_id
        ):
            return None
        rows = _rows(
            self.conn, "SELECT * FROM context_concepts WHERE id=?", (concept_id,)
        )
        return rows[0] if rows else None

    def authorized_legacy_for_bind(
        self,
        context: AgentContext,
        concept_id: str,
    ) -> tuple[dict[str, Any], str] | None:
        """Return an unbound root only after its claimed session is scope-visible."""
        rows = _rows(
            self.conn,
            """SELECT * FROM context_concepts
               WHERE id=? AND binding_state='legacy-unbound'""",
            (concept_id,),
        )
        if not rows:
            return None
        root = rows[0]
        source_session_id = root["source_session_id"]
        if source_session_id is None:
            source_uri = root["source_uri"]
            if not isinstance(source_uri, str) or not source_uri.startswith(
                _SESSION_URI_PREFIX
            ):
                return None
            claimed_id = source_uri.removeprefix(_SESSION_URI_PREFIX)
            if _SESSION_ID.fullmatch(claimed_id) is None:
                return None
            source_session_id = claimed_id
        if not isinstance(source_session_id, str) or not self._session_visible(
            context, source_session_id
        ):
            return None
        return root, source_session_id

    def search_fts(self, query: str) -> list[dict[str, Any]]:
        """Private A3a read-model proof; A4 owns the public recall surface."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("FTS query must be nonempty text")
        rows = _rows(
            self.conn,
            """WITH ranked AS (
                 SELECT e.*,
                   row_number() OVER (
                     PARTITION BY concept_id
                     ORDER BY logical_time DESC,origin_instance DESC,
                              origin_seq DESC,id DESC
                   ) AS position
                 FROM context_concept_events e
               )
               SELECT c.id AS concept_id,c.title,c.statement,c.canonical_tags,c.kind,
                      c.binding_state,r.standing
               FROM context_concept_fts
               JOIN context_concepts c ON c.id=context_concept_fts.concept_id
               JOIN ranked r ON r.concept_id=c.id AND r.position=1
               WHERE context_concept_fts MATCH ? AND r.standing!='retired'
               ORDER BY c.id""",
            (query,),
        )
        return [
            {
                **row,
                "trust_label": (
                    "legacy-unbound"
                    if row["binding_state"] == "legacy-unbound"
                    else "model-proposed"
                ),
            }
            for row in rows
        ]


class ConceptService:
    """Small external seam for transactional concept operations."""

    def __init__(
        self,
        db: Path | None = None,
        *,
        now: Callable[[], str] | None = None,
        prepare_schema: bool = True,
    ) -> None:
        self._db = (db or get_db_path(load_config())).expanduser().resolve()
        self._now = now or globals()["_now"]
        if prepare_schema:
            self._prepare_schema()

    def _prepare_schema(self) -> None:
        from .managed_history import require_query_target

        require_query_target(self._db)
        conn = sqlite3.connect(self._db.as_uri() + "?mode=rw", uri=True)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            _ensure_schema(conn)
        finally:
            conn.rollback()
            conn.close()

    @staticmethod
    def _call_issues(
        *,
        session_id: object | None = None,
        concept_id: object | None = None,
        actor: object,
        reason: object | None = None,
    ) -> tuple[_Issue, ...]:
        issues: list[_Issue] = []
        if session_id is not None:
            issue = _call_text(session_id, "/session_id", 128)
            if issue:
                issues.append(issue)
        if concept_id is not None:
            issue = _call_text(concept_id, "/concept_id", 128)
            if issue:
                issues.append(issue)
        issue = _call_text(actor, "/actor", 128)
        if issue:
            issues.append(issue)
        if reason is not None:
            issue = _call_text(reason, "/reason", 2000)
            if issue:
                issues.append(issue)
        return tuple(issues)

    def project(
        self,
        out: Path,
        *,
        project: str | None = None,
    ) -> ProjectionReport:
        """Rebuild disposable Markdown from scope-authorized concept state."""
        return project_concepts(self._db, out, project=project)

    def winddown(
        self,
        session_id: str,
        document: object,
        *,
        actor: str,
        project: str | None = None,
    ) -> BatchResult:
        concepts, parse_issues = _parse_winddown(document)
        issues = (*parse_issues, *self._call_issues(session_id=session_id, actor=actor))
        if issues:
            return BatchResult(writes=0, errors=issues)
        if not concepts:
            return BatchResult(writes=0)
        with open_context(self._db, write=True, project=project) as context:
            _ensure_schema(context.conn)
            repository = _ConceptRepository(context.conn, now=self._now)
            resolver = _EvidenceResolver(context, session_id)
            resolved: list[tuple[_Concept, tuple[dict[str, object], ...]]] = []
            resolution_issues: list[_Issue] = []
            for index, concept in enumerate(concepts):
                citations, citation_issues = resolver.resolve(
                    concept.quotes, path=f"/concepts/{index}/quotes"
                )
                resolved.append((concept, citations))
                resolution_issues.extend(citation_issues)
            if resolution_issues:
                return BatchResult(writes=0, errors=tuple(resolution_issues))
            concept_ids: list[str] = []
            for concept, citations in resolved:
                proposal = context.propose(
                    statement=concept.description,
                    state="unknown",
                    target=None,
                    citations=list(citations),
                    producer=actor,
                )
                assertion_id = cast(str, proposal["assertion_id"])
                repository._checkpoint("after_assertion")
                repository.insert_bound(
                    assertion_id=assertion_id,
                    origin="winddown",
                    kind=concept.kind,
                    title=concept.title,
                    statement=concept.description,
                    tags=concept.tags,
                    confidence=concept.confidence,
                    source_session_id=session_id,
                    source_uri=f"sessionweaver://session/{session_id}",
                    producer=actor,
                )
                repository.append_event(
                    concept_id=assertion_id,
                    parent_event_id=None,
                    standing="proposed",
                    actor=actor,
                    reason="winddown",
                )
                concept_ids.append(assertion_id)
            return BatchResult(writes=len(concept_ids), concept_ids=tuple(concept_ids))

    def transition(
        self,
        concept_id: str,
        standing: TransitionStanding,
        *,
        actor: str,
        reason: str,
        project: str | None = None,
    ) -> TransitionResult:
        issues = list(
            self._call_issues(concept_id=concept_id, actor=actor, reason=reason)
        )
        if standing not in ("accepted", "retired"):
            issues.append(_error("/standing", "invalid_choice", "Unknown standing"))
        if issues:
            return TransitionResult(
                writes=0, concept_id=concept_id, errors=tuple(issues)
            )
        with open_context(self._db, write=True, project=project) as context:
            _ensure_schema(context.conn)
            repository = _ConceptRepository(context.conn, now=self._now)
            root = repository.authorized_root(context, concept_id)
            if root is None:
                return TransitionResult(
                    writes=0,
                    concept_id=concept_id,
                    errors=(
                        _error(
                            "/concept_id",
                            "concept_unavailable",
                            "Concept is unavailable under the requested scope",
                        ),
                    ),
                )
            if root["binding_state"] == "legacy-unbound" and standing == "accepted":
                return TransitionResult(
                    writes=0,
                    concept_id=concept_id,
                    errors=(
                        _error(
                            "/standing",
                            "legacy_unbound_requires_bind",
                            "Legacy-unbound concepts require exact evidence binding",
                        ),
                    ),
                )
            current = repository.current_event(concept_id)
            current_standing = current["standing"]
            if current_standing == "retired":
                return TransitionResult(
                    writes=0,
                    concept_id=concept_id,
                    errors=(
                        _error(
                            "/standing",
                            "retired_terminal",
                            "Retired concepts are terminal",
                        ),
                    ),
                )
            allowed = (
                current_standing == "proposed" and standing in ("accepted", "retired")
            ) or (current_standing == "accepted" and standing == "retired")
            if not allowed:
                return TransitionResult(
                    writes=0,
                    concept_id=concept_id,
                    errors=(
                        _error(
                            "/standing",
                            "invalid_transition",
                            f"Cannot transition {current_standing} to {standing}",
                        ),
                    ),
                )
            event_id = repository.append_event(
                concept_id=concept_id,
                parent_event_id=cast(str, current["id"]),
                standing=standing,
                actor=actor,
                reason=reason,
            )
            return TransitionResult(
                writes=1,
                concept_id=concept_id,
                standing=standing,
                event_id=event_id,
            )

    def _bind_resolved_legacy(
        self,
        *,
        context: AgentContext,
        repository: _ConceptRepository,
        root: dict[str, Any],
        current: dict[str, Any],
        citations: Sequence[dict[str, object]],
        source_session_id: str,
        actor: str,
        reason: str,
    ) -> BindResult:
        """Run the reviewed A3a safe-bind writes inside the caller's transaction."""
        concept_id = cast(str, root["id"])
        proposal = context.propose(
            statement=cast(str, root["statement"]),
            state="unknown",
            target=None,
            citations=list(citations),
            producer=actor,
        )
        assertion_id = cast(str, proposal["assertion_id"])
        repository._checkpoint("after_assertion")
        repository.insert_bound(
            assertion_id=assertion_id,
            origin="legacy-bind",
            kind=cast(str, root["kind"]),
            title=cast(str, root["title"]),
            statement=cast(str, root["statement"]),
            tags=tuple(json.loads(cast(str, root["canonical_tags"]))),
            confidence=float(root["confidence"]),
            source_session_id=source_session_id,
            source_uri=cast(str, root["source_uri"]),
            producer=cast(str, root["producer"]),
            legacy_file_sha256=cast(str, root["legacy_file_sha256"]),
            supersedes_concept_id=concept_id,
        )
        repository.append_event(
            concept_id=assertion_id,
            parent_event_id=None,
            standing="proposed",
            actor=actor,
            reason=reason,
        )
        repository._checkpoint("after_bound_initial_event")
        repository.append_event(
            concept_id=concept_id,
            parent_event_id=cast(str, current["id"]),
            standing="retired",
            actor=actor,
            reason=f"{reason}; bound_to={assertion_id}",
        )
        repository._checkpoint("after_legacy_retired_event")
        return BindResult(
            writes=4,
            legacy_concept_id=concept_id,
            concept_id=assertion_id,
            assertion_id=assertion_id,
        )

    def bind_legacy(
        self,
        concept_id: str,
        document: object,
        *,
        actor: str,
        reason: str,
        project: str | None = None,
    ) -> BindResult:
        quotes, parse_issues = _parse_bind_document(document)
        issues = (
            *parse_issues,
            *self._call_issues(concept_id=concept_id, actor=actor, reason=reason),
        )
        if issues:
            return BindResult(writes=0, legacy_concept_id=concept_id, errors=issues)
        with open_context(self._db, write=True, project=project) as context:
            _ensure_schema(context.conn)
            repository = _ConceptRepository(context.conn, now=self._now)
            visible_root = repository.authorized_root(context, concept_id)
            if (
                visible_root is not None
                and visible_root["binding_state"] != "legacy-unbound"
            ):
                return BindResult(
                    writes=0,
                    legacy_concept_id=concept_id,
                    errors=(
                        _error(
                            "/concept_id",
                            "not_legacy_unbound",
                            "Only legacy-unbound roots can be bound",
                        ),
                    ),
                )
            authorized = repository.authorized_legacy_for_bind(context, concept_id)
            if authorized is None:
                return BindResult(
                    writes=0,
                    legacy_concept_id=concept_id,
                    errors=(
                        _error(
                            "/concept_id",
                            "concept_unavailable",
                            "Concept is unavailable under the requested scope",
                        ),
                    ),
                )
            root, binding_session_id = authorized
            current = repository.current_event(concept_id)
            if current["standing"] == "retired":
                return BindResult(
                    writes=0,
                    legacy_concept_id=concept_id,
                    errors=(
                        _error(
                            "/concept_id",
                            "legacy_already_retired",
                            "Retired legacy roots cannot be bound",
                        ),
                    ),
                )
            resolver = _EvidenceResolver(context, binding_session_id)
            citations, resolution_issues = resolver.resolve(quotes, path="/quotes")
            if resolution_issues:
                return BindResult(
                    writes=0,
                    legacy_concept_id=concept_id,
                    errors=resolution_issues,
                )
            return self._bind_resolved_legacy(
                context=context,
                repository=repository,
                root=root,
                current=current,
                citations=citations,
                source_session_id=binding_session_id,
                actor=actor,
                reason=reason,
            )

    def import_okf(
        self,
        root: Path,
        *,
        actor: str,
        project: str | None = None,
        dry_run: bool = False,
    ) -> ImportReport:
        """Import valid OKF roots atomically after complete parse and resolution.

        Per-record binding classification precedence (checked in this exact
        order; the first matching rule decides the record's ``legacy_unbound``
        sub-reason, or ``bound``):

        1. ``missing_session`` -- the claimed session is not scope-visible;
           evidence is never queried.
        2. ``no_exact_match`` -- the record's full body exceeds the 2,000
           code-point exact-citation limit; evidence is never queried.
        3. ``no_visible_evidence`` -- the session is visible, zero evidence rows
           are visible under the active scope, and none were excluded for
           exceeding ``MAX_BODY_CHARS``.
        4. ``oversized_evidence`` -- at least one visible evidence row exceeds
           ``MAX_BODY_CHARS`` and was excluded from exact-match search (its body
           is never loaded into memory for this purpose), *and* either no
           normal-sized row remains visible, or none of the remaining
           normal-sized rows contain the record's full body. This sub-reason
           takes precedence over ``no_visible_evidence`` and ``no_exact_match``
           in exactly those two situations, because "evidence existed but was
           too large to use" is a more informative explanation than either.
        5. ``no_exact_match`` -- normal-sized visible evidence exists, none was
           excluded for size, and the full body matches zero rows.
        6. ``ambiguous_match`` -- the full body matches more than one
           normal-sized visible row. This is decided before the oversized rule
           is considered, so an ambiguous match always wins even when another
           row was also excluded for size.
        7. ``bound`` -- the full body matches exactly one normal-sized visible
           row; a single exact citation is proposed against it.

        A record's classification never aborts the batch: every other record is
        still classified and, in write mode, every classified record (bound or
        not) is imported as an immutable legacy root inside the one outer
        transaction.
        """

        def operation_report(*issues: _Issue) -> ImportReport:
            return ImportReport(
                errors=tuple(
                    OKFImportError("", issue.code, issue.path) for issue in issues
                )
            )

        def build_report(
            scan: _OKFScan,
            updates: dict[str, int] | None = None,
            *,
            errors: tuple[OKFImportError, ...] | None = None,
        ) -> ImportReport:
            base_values: dict[str, int] = {
                name: cast(int, value)
                for name, value in scan.report.to_dict().items()
                if name != "errors"
            }
            values = {**base_values, **(updates or {})}
            return ImportReport(
                **values,
                errors=scan.report.errors if errors is None else errors,
            )

        call_issues: list[_Issue] = []
        actor_issue = _call_text(actor, "/actor", 128)
        if actor_issue is not None:
            call_issues.append(actor_issue)
        if project is not None:
            project_issue = _call_text(project, "/project", 128)
            if project_issue is not None:
                call_issues.append(project_issue)
        if call_issues:
            return operation_report(*call_issues)

        scan: _OKFScan | None = None
        counters = {
            "already_present": 0,
            "bound": 0,
            "legacy_unbound": 0,
            "missing_session": 0,
            "no_visible_evidence": 0,
            "no_exact_match": 0,
            "ambiguous_match": 0,
            "oversized_evidence": 0,
        }
        plans: list[
            tuple[_OKFRecord, tuple[dict[str, object], ...] | None, str | None]
        ] = []
        imported = 0
        writes = 0
        try:
            with open_context(self._db, write=not dry_run, project=project) as context:
                scan = _scan_okf(root)
                if not scan.records:
                    return scan.report

                has_sidecar = (
                    context.conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_concepts'"
                    ).fetchone()
                    is not None
                )
                repository = _ConceptRepository(context.conn, now=self._now)
                for record in scan.records:
                    if (
                        has_sidecar
                        and context.conn.execute(
                            "SELECT 1 FROM context_concepts "
                            "WHERE id=? OR supersedes_concept_id=? LIMIT 1",
                            (record.legacy_id, record.legacy_id),
                        ).fetchone()
                        is not None
                    ):
                        counters["already_present"] += 1
                        continue

                    citations: tuple[dict[str, object], ...] | None = None
                    source_session_id: str | None
                    if not repository._session_visible(context, record.session_id):
                        reason = "missing_session"
                        source_session_id = None
                    else:
                        source_session_id = record.session_id
                        resolver = _EvidenceResolver(context, record.session_id)
                        if len(record.statement) > 2000:
                            reason = "no_exact_match"
                        else:
                            sources = resolver._visible_sources(degrade_oversized=True)
                            had_oversized_evidence = (
                                resolver._oversized_evidence_count > 0
                            )
                            if not sources:
                                reason = (
                                    "oversized_evidence"
                                    if had_oversized_evidence
                                    else "no_visible_evidence"
                                )
                            else:
                                matches = [
                                    (
                                        identity,
                                        start,
                                        start + len(record.statement),
                                        record.statement,
                                    )
                                    for identity, body in sources.items()
                                    for start in resolver._occurrences(
                                        body, record.statement
                                    )
                                ]
                                if not matches:
                                    reason = (
                                        "oversized_evidence"
                                        if had_oversized_evidence
                                        else "no_exact_match"
                                    )
                                elif len(matches) > 1:
                                    reason = "ambiguous_match"
                                else:
                                    reason = "bound"
                                    match = matches[0]
                                    citations = (
                                        {
                                            "evidence_id": match[0],
                                            "start": match[1],
                                            "end": match[2],
                                            "quote": match[3],
                                        },
                                    )
                    counters[reason] += 1
                    if reason != "bound":
                        counters["legacy_unbound"] += 1
                    plans.append((record, citations, source_session_id))

                if dry_run:
                    return build_report(scan, counters)

                _ensure_schema(context.conn)
                for record, citations, source_session_id in plans:
                    repository.seed_legacy(
                        original_bytes=record.original_bytes,
                        kind=record.kind,
                        title=record.title,
                        statement=record.statement,
                        tags=record.tags,
                        confidence=record.confidence,
                        source_session_id=source_session_id,
                        source_uri=record.source_uri,
                        producer=record.actor,
                        event_actor=actor,
                    )
                    imported += 1
                    writes += 1
                    if citations is not None:
                        if source_session_id is None:
                            raise RuntimeError(
                                "Bound import lost its authorized session"
                            )
                        legacy_root = repository.authorized_root(
                            context, record.legacy_id
                        )
                        if legacy_root is None:
                            raise RuntimeError("Imported legacy root is unavailable")
                        current = repository.current_event(record.legacy_id)
                        bound_result = self._bind_resolved_legacy(
                            context=context,
                            repository=repository,
                            root=legacy_root,
                            current=current,
                            citations=citations,
                            source_session_id=source_session_id,
                            actor=actor,
                            reason="legacy OKF exact-body binding",
                        )
                        writes += bound_result.writes
                return build_report(
                    scan, {**counters, "imported": imported, "writes": writes}
                )
        except ScopeError:
            code = "project_unavailable" if project is not None else "scope_unavailable"
            field = "/project" if project is not None else "/scope"
            return ImportReport(errors=(OKFImportError("", code, field),))
        except Exception:
            if scan is None:
                raise
            failure_count = len(plans) or len(scan.records) or 1
            return build_report(
                scan,
                {
                    **counters,
                    "imported": 0,
                    "write_failures": failure_count,
                    "writes": 0,
                },
                errors=(
                    *scan.report.errors[: MAX_ERROR_ENTRIES - 1],
                    OKFImportError("", "write_failed", "/"),
                ),
            )
