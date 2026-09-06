"""Canonical source versions and scoped citations, independent of StudyLoop.

This internal boundary is not yet wired to the legacy CLI/MCP/sync interfaces.
Capture/configuration methods are trusted importer/admin operations. Agent-facing
adapters may submit interpretations and stored source IDs, never capture receipts
or an arbitrary access policy. SQLite ownership is a local application boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..migrations import CURRENT_VERSION
from .provenance import (
    CapturedReceipt,
    ExecutionState,
    Origin,
    Scope,
    ScopeAssignment,
    derive_provenance,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, kw_only=True)
class Access:
    """Resolved local policy for one scope and optional explicit project set."""

    scope: Scope
    projects: frozenset[str] | None = None
    include_unassigned: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope, Scope):
            raise ValueError("An explicit scope is required")
        if type(self.include_unassigned) is not bool or (
            self.include_unassigned and self.scope != Scope.UNCLASSIFIED
        ):
            raise ValueError("Only unclassified access can include unassigned sources")
        if self.projects is not None:
            if not isinstance(self.projects, frozenset):
                raise ValueError("Projects must be a frozen set")
            for project in self.projects:
                _text(project, "project")


@dataclass(frozen=True, kw_only=True)
class NativeSource:
    """Trusted parser output; native_key must be stable across repeated imports."""

    session_id: str
    native_key: str
    harness: str
    native_kind: str
    native_locator: str
    parser_version: str
    machine_id: str
    body: str
    origin: Origin
    recorded_at: str | None = None
    call_id: str | None = None
    target: str | None = None
    revision: str | None = None
    exit_code: int | None = None

    def __post_init__(self) -> None:
        for field in (
            "session_id",
            "native_key",
            "harness",
            "native_kind",
            "native_locator",
            "parser_version",
            "machine_id",
        ):
            _text(getattr(self, field), field)
        if not isinstance(self.body, str):
            raise ValueError("Source body must be text")
        if (
            self.recorded_at is not None
            and datetime.fromisoformat(self.recorded_at).tzinfo is None
        ):
            raise ValueError("Source time must include a timezone or remain unknown")
        for field in ("call_id", "target", "revision"):
            value = getattr(self, field)
            if value is not None:
                _text(value, field)
        CapturedReceipt(
            receipt_id="validation",
            origin=self.origin,
            target=self.target,
            exit_code=self.exit_code,
        )

    def payload(self) -> dict[str, Any]:
        record = asdict(self)
        if self.recorded_at is not None:
            record["recorded_at"] = (
                datetime.fromisoformat(self.recorded_at).astimezone(UTC).isoformat()
            )
        native_key = record.pop("native_key")
        record["source_key"] = _hash(_json([self.harness, self.session_id, native_key]))
        record["body_sha256"] = _hash(self.body)
        return record


@dataclass(frozen=True, kw_only=True)
class Citation:
    evidence_id: str
    start: int
    end: int
    quote: str

    def __post_init__(self) -> None:
        _text(self.evidence_id, "evidence_id")
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError(
                "Citation offsets must be integer Unicode code-point offsets"
            )
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Invalid citation range")
        _text(self.quote, "quote")


class ContextStore:
    """Every source/assertion read requires an explicit resolved access policy."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._check_version()
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "context_evidence" not in tables:
            raise RuntimeError("Context schema missing; migrate this database first")
        # Explicit deletions are still used for lifecycle work; require FK checks
        # so new references cannot become dangling when sources disappear.
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError(
                "Context storage requires foreign_keys=ON before its transaction"
            )

    def _check_version(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if not 31 <= version <= CURRENT_VERSION:
            raise RuntimeError(
                f"Unsupported context schema v{version}; expected v31-v{CURRENT_VERSION}"
            )

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        self._check_version()
        if self.conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("Context storage requires foreign_keys=ON")
        owned = not self.conn.in_transaction
        savepoint = "context_" + uuid4().hex
        self.conn.execute("BEGIN IMMEDIATE" if owned else f"SAVEPOINT {savepoint}")
        try:
            yield
            if owned:
                self.conn.commit()
            else:
                self.conn.execute(f"RELEASE {savepoint}")
        except Exception:
            if owned:
                self.conn.rollback()
            else:
                self.conn.execute(f"ROLLBACK TO {savepoint}")
                self.conn.execute(f"RELEASE {savepoint}")
            raise

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        self._check_version()
        cursor = self.conn.execute(sql, params)
        names = [col[0] for col in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor]

    def configure_project(self, assignment: ScopeAssignment) -> None:
        """Trusted explicit configuration; never infer a scope from a harness."""
        if assignment.project_id is None:
            raise ValueError("A stored project requires an identity")
        with self._atomic():
            self.conn.execute(
                """INSERT INTO context_projects(id,scope,policy_id,updated_at) VALUES (?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET scope=excluded.scope,
                   policy_id=excluded.policy_id,updated_at=excluded.updated_at""",
                (
                    assignment.project_id,
                    assignment.scope.value,
                    assignment.policy_id,
                    _now(),
                ),
            )

    def assign_session(self, session_id: str, project_id: str) -> None:
        """Trusted explicit assignment. Existing evidence follows current project policy."""
        with self._atomic():
            if self.conn.execute(
                "SELECT 1 FROM context_tombstones WHERE session_id=?", (session_id,)
            ).fetchone():
                raise ValueError("Source session was forgotten")
            self.conn.execute(
                """INSERT INTO context_session_projects(session_id,project_id) VALUES (?,?)
                   ON CONFLICT(session_id) DO UPDATE SET project_id=excluded.project_id""",
                (session_id, project_id),
            )

    def capture(self, source: NativeSource) -> str:
        """Append an immutable version. No annotation/model fields are accepted here."""
        payload = source.payload()
        identity = _hash(_json(payload))
        with self._atomic():
            if self.conn.execute(
                "SELECT 1 FROM context_tombstones WHERE session_id=?",
                (source.session_id,),
            ).fetchone():
                raise ValueError("Source session was forgotten")
            existing = self.conn.execute(
                "SELECT id FROM context_evidence WHERE id=?", (identity,)
            ).fetchone()
            if existing:
                return identity
            columns = ["id", *payload, "first_captured_at"]
            self.conn.execute(
                f"INSERT INTO context_evidence({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})",
                (identity, *payload.values(), _now()),
            )
        return identity

    @staticmethod
    def _where(access: Access) -> tuple[str, list[Any]]:
        # Unassigned sessions are unclassified; an explicit unclassified request
        # can inspect them, but a personal/work request cannot.
        clause = """COALESCE(p.scope,'unclassified')=? AND NOT EXISTS
            (SELECT 1 FROM context_tombstones t WHERE t.session_id=e.session_id)"""
        values: list[Any] = [access.scope.value]
        if access.projects is not None:
            projects = "0"
            if access.projects:
                projects = "p.id IN (" + ",".join("?" for _ in access.projects) + ")"
            if access.include_unassigned:
                projects = "(" + projects + " OR sp.session_id IS NULL)"
            clause += " AND " + projects
            values.extend(sorted(access.projects))
        return clause, values

    def _sources(
        self, access: Access, predicate: str, params: Sequence[Any], suffix: str = ""
    ) -> list[dict[str, Any]]:
        scope, values = self._where(access)
        return self._rows(
            """SELECT e.*, p.id AS project_id, COALESCE(p.scope,'unclassified') AS scope,
               COALESCE(p.policy_id,'unassigned') AS policy_id FROM context_evidence e
               LEFT JOIN context_session_projects sp ON sp.session_id=e.session_id
               LEFT JOIN context_projects p ON p.id=sp.project_id
               WHERE """
            + scope
            + " AND "
            + predicate
            + suffix,
            (*values, *params),
        )

    @staticmethod
    def _checked(row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            k: v
            for k, v in row.items()
            if k not in ("id", "project_id", "scope", "policy_id", "first_captured_at")
        }
        if (
            _hash(row["body"]) != row["body_sha256"]
            or _hash(_json(payload)) != row["id"]
        ):
            raise ValueError("Stored source binding failed")
        provenance = derive_provenance(
            ScopeAssignment(
                scope=Scope(row["scope"]),
                project_id=row["project_id"],
                policy_id=row["policy_id"],
            ),
            CapturedReceipt(
                receipt_id=row["id"],
                origin=Origin(row["origin"]),
                target=row["target"],
                exit_code=row["exit_code"],
            ),
        )
        return {**row, "provenance": asdict(provenance)}

    def source(self, evidence_id: str, access: Access) -> dict[str, Any] | None:
        rows = self._sources(access, "e.id=?", (evidence_id,))
        return self._checked(rows[0]) if rows else None

    def search(
        self, query: str, access: Access, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Literal lexical candidate search. A match is not decision sufficiency."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Search limit must be between 1 and 100")
        terms = re.findall(r"\w+", query, flags=re.UNICODE)[:16]
        if not terms:
            return []
        expression = " OR ".join('"' + t[:80] + '"' for t in terms)
        rows = self._sources(
            access,
            "e.rowid IN (SELECT rowid FROM context_evidence_fts WHERE context_evidence_fts MATCH ?)",
            (expression, limit),
            " ORDER BY e.recorded_at DESC,e.id LIMIT ?",
        )
        return [
            {
                **self._checked(row),
                "why_selected": {
                    "method": "literal lexical match",
                    "query_terms": terms,
                    "ordering": "source time descending; unknown last; not a truth ranking",
                    "scope": access.scope.value,
                },
            }
            for row in rows
        ]

    def propose(
        self,
        *,
        statement: str,
        state: ExecutionState,
        target: str | None,
        generator: str,
        citations: Sequence[Citation],
        access: Access,
    ) -> str:
        """Retain an unverified assertion only after binding all its exact citations."""
        _text(statement, "statement")
        _text(generator, "generator")
        if not isinstance(state, ExecutionState) or not citations:
            raise ValueError(
                "An assertion needs a valid state and supporting citations"
            )
        if target is not None:
            _text(target, "target")
        with self._atomic():
            for citation in citations:
                row = self.source(citation.evidence_id, access)
                if row is None:
                    raise ValueError("Citation is unavailable under the current scope")
                body = row["body"]
                if (
                    citation.end > len(body)
                    or body[citation.start : citation.end] != citation.quote
                ):
                    raise ValueError(
                        "Citation does not match its immutable source version"
                    )
            identity = uuid4().hex
            self.conn.execute(
                """INSERT INTO context_assertions
                (id,statement,proposed_state,proposed_target,generator,created_at)
                VALUES (?,?,?,?,?,?)""",
                (identity, statement, state.value, target, generator, _now()),
            )
            self.conn.executemany(
                """INSERT INTO context_citations
                (assertion_id,evidence_id,start_offset,end_offset,quote) VALUES (?,?,?,?,?)""",
                [(identity, c.evidence_id, c.start, c.end, c.quote) for c in citations],
            )
        return identity

    def assertion(self, assertion_id: str, access: Access) -> dict[str, Any] | None:
        # Authorize all supporting sources in SQL before fetching the statement or
        # quotes. This also invalidates access after any project is reclassified.
        scope, values = self._where(access)
        rows = self._rows(
            """SELECT a.* FROM context_assertions a WHERE a.id=?
            AND EXISTS (SELECT 1 FROM context_citations c WHERE c.assertion_id=a.id)
            AND NOT EXISTS (
              SELECT 1 FROM context_citations c
              LEFT JOIN context_evidence e ON e.id=c.evidence_id
              LEFT JOIN context_session_projects sp ON sp.session_id=e.session_id
              LEFT JOIN context_projects p ON p.id=sp.project_id
              WHERE c.assertion_id=a.id AND (e.id IS NULL OR COALESCE(("""
            + scope
            + "),0)=0))",
            (assertion_id, *values),
        )
        if not rows:
            return None
        citations = self._rows(
            "SELECT * FROM context_citations WHERE assertion_id=?", (assertion_id,)
        )
        for citation in citations:
            source = self.source(citation["evidence_id"], access)
            if source is None:
                return None
            if (
                source["body"][citation["start_offset"] : citation["end_offset"]]
                != citation["quote"]
            ):
                raise ValueError("Stored citation binding failed")
        return {
            **rows[0],
            "semantic_status": "unverified_interpretation",
            "citations": citations,
        }

    def relate(
        self, from_id: str, to_id: str, relation: str, proposer: str, access: Access
    ) -> str:
        """Record a proposed relationship; a correction does not overwrite history."""
        if relation not in ("supports", "contradicts", "corrects") or from_id == to_id:
            raise ValueError("Invalid relationship")
        _text(proposer, "proposer")
        with self._atomic():
            if (
                self.assertion(from_id, access) is None
                or self.assertion(to_id, access) is None
            ):
                raise ValueError(
                    "Relationship endpoint unavailable under the current scope"
                )
            existing = self.conn.execute(
                """SELECT id FROM context_relations WHERE
                from_assertion=? AND to_assertion=? AND relation=? AND proposer=?""",
                (from_id, to_id, relation, proposer),
            ).fetchone()
            if existing:
                return existing[0]
            identity = uuid4().hex
            self.conn.execute(
                "INSERT INTO context_relations VALUES (?,?,?,?,?,?)",
                (identity, from_id, to_id, relation, proposer, _now()),
            )
        return identity

    def relations(self, assertion_id: str, access: Access) -> list[dict[str, Any]]:
        if self.assertion(assertion_id, access) is None:
            return []
        rows = self._rows(
            """SELECT * FROM context_relations
            WHERE from_assertion=? OR to_assertion=? ORDER BY created_at,id""",
            (assertion_id, assertion_id),
        )
        return [
            {**row, "semantic_status": "unverified_relationship"}
            for row in rows
            if self.assertion(row["from_assertion"], access) is not None
            and self.assertion(row["to_assertion"], access) is not None
        ]
