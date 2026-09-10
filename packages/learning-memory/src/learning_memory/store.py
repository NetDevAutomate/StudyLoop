"""The ADR-0011 store: ingest typed sessions, add quote-bound claims.

Everything in this module is either one transaction or a read. There is no
"partially ingested session" state and no "claim whose citations didn't land"
state, because both would let unprovable provenance into the store.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Literal, Self

from learning_memory.model import (
    CLAIM_KINDS,
    PROSE_KINDS,
    ClaimKind,
    ParsedSession,
    Session,
)
from learning_memory.schema import (
    DEFAULT_TOKENIZER,
    PRAGMAS,
    SCHEMA_VERSION,
    Tokenizer,
    ddl,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path
    from types import TracebackType

__all__ = [
    "CitationError",
    "CitationProblem",
    "ClaimValidationError",
    "DuplicateClaimError",
    "IngestResult",
    "LearningMemoryError",
    "NoEvidenceError",
    "SchemaError",
    "Store",
]

_EVIDENCE_JOINER: Final = "\n\n"
"""How REPORTED prose is concatenated into one evidence body."""

CitationReason = Literal[
    "unknown_evidence",
    "foreign_evidence",
    "empty_quote",
    "quote_not_found",
    "ambiguous_quote",
    "duplicate_citation",
    "not_bound",
]


class LearningMemoryError(Exception):
    """Base class for every error this package raises deliberately."""


class SchemaError(LearningMemoryError):
    """The database on disk is not the schema this code writes."""


class NoEvidenceError(LearningMemoryError):
    """Ingest would have left a session with zero evidence rows, so it was rolled back."""


class ClaimValidationError(LearningMemoryError):
    """A claim's own fields are out of contract (kind, lengths, tags, confidence)."""


class DuplicateClaimError(LearningMemoryError):
    """This exact claim (same session, kind, title, statement, tags, confidence, writer) exists."""


@dataclass(frozen=True, slots=True)
class CitationProblem:
    """Why one citation could not be bound. Structured so a caller can act on it."""

    index: int
    evidence_id: str
    quote: str
    reason: CitationReason
    detail: str


class CitationError(LearningMemoryError):
    """One or more citations could not be bound; nothing was written.

    Carries every problem found, not just the first: a writer fixing citations
    one round-trip at a time is a writer that gives up and stops citing.
    """

    def __init__(self, problems: Sequence[CitationProblem]) -> None:
        self.problems: tuple[CitationProblem, ...] = tuple(problems)
        summary = "; ".join(f"[{p.index}] {p.reason}: {p.detail}" for p in self.problems)
        super().__init__(f"{len(self.problems)} citation(s) could not be bound: {summary}")


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one ``ingest()`` call actually changed."""

    session_id: str
    events_inserted: int
    events_skipped: int
    evidence_inserted: int
    evidence_skipped: int
    lineage_inserted: int
    lineage_deferred: tuple[str, ...] = ()
    """Parent ids not yet present in ``sessions``; re-ingest the child once they are."""


def _canonical_json(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def evidence_id(session_id: str, origin: str, basis: str, body_sha256: str) -> str:
    """``evidence.id`` = sha256 of the canonical payload (ADR-0011 schema).

    Content-addressed so re-ingesting the same session re-derives the same id and
    the insert is a no-op instead of a duplicate row.
    """
    return _sha256_hex(
        _canonical_json(
            {
                "session_id": session_id,
                "origin": origin,
                "basis": basis,
                "body_sha256": body_sha256,
            }
        )
    )


def claim_id(
    session_id: str,
    kind: str,
    title: str,
    statement: str,
    tags: Sequence[str],
    confidence: float,
    writer: str,
) -> str:
    """Content address of a claim. ``created_at`` is excluded so the id is stable."""
    return _sha256_hex(
        _canonical_json(
            {
                "session_id": session_id,
                "kind": kind,
                "title": title,
                "statement": statement,
                "tags": sorted(tags),
                "confidence": confidence,
                "writer": writer,
            }
        )
    )


class Store:
    """A single-file SQLite learning-memory store.

    The live ``sessions.db`` is never opened by this class; a PoC store is its own
    file (ADR-0011 Consequences).
    """

    def __init__(self, conn: sqlite3.Connection, tokenizer: Tokenizer = DEFAULT_TOKENIZER) -> None:
        self._conn = conn
        self._tokenizer: Tokenizer = tokenizer

    # ---------------------------------------------------------------- lifecycle

    @classmethod
    def connect(cls, path: str | Path, tokenizer: Tokenizer = DEFAULT_TOKENIZER) -> Self:
        """Open (creating if needed) the store at ``path`` with FKs on and WAL set."""
        conn = sqlite3.connect(str(path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        for pragma in PRAGMAS:
            conn.execute(pragma)
        return cls(conn, tokenizer)

    @property
    def connection(self) -> sqlite3.Connection:
        """The underlying connection. Exposed for tests and for the derivation pass."""
        return self._conn

    @property
    def tokenizer(self) -> Tokenizer:
        return self._tokenizer

    def install(self) -> None:
        """Create the schema, or verify an existing one was built the same way."""
        existing = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
        ).fetchone()
        if existing is not None:
            self._verify_installed()
            return
        self._conn.executescript(ddl(self._tokenizer))
        self._conn.execute(
            "INSERT INTO schema_version(version, tokenizer, applied_at) VALUES (?, ?, ?)",
            (SCHEMA_VERSION, self._tokenizer, _now()),
        )

    def _verify_installed(self) -> None:
        row = self._conn.execute(
            "SELECT version, tokenizer FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise SchemaError("schema_version table exists but is empty")
        if int(row["version"]) != SCHEMA_VERSION:
            raise SchemaError(
                f"store is schema v{row['version']}, this code writes v{SCHEMA_VERSION}"
            )
        if str(row["tokenizer"]) != self._tokenizer:
            raise SchemaError(
                f"store was built with tokenizer {row['tokenizer']!r}, "
                f"opened with {self._tokenizer!r}; FTS results would not be comparable"
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -------------------------------------------------------------- transactions

    def _begin(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")

    def _rollback(self) -> None:
        self._conn.execute("ROLLBACK")

    def _commit(self) -> None:
        self._conn.execute("COMMIT")

    # -------------------------------------------------------------------- ingest

    def ingest(self, parsed: ParsedSession) -> IngestResult:
        """Write one parsed session: session, events, evidence and lineage, atomically.

        Raises:
            NoEvidenceError: if the write would leave the session with no evidence.
                The transaction is rolled back, so no session row survives either.
        """
        self._begin()
        try:
            self._upsert_session(parsed.session)
            events_inserted, events_skipped = self._insert_events(parsed)
            evidence_inserted, evidence_skipped = self._insert_evidence(parsed)
            lineage_inserted, deferred = self._insert_lineage(parsed)
            if self._evidence_count(parsed.session.id) == 0:
                raise NoEvidenceError(
                    f"session {parsed.session.id!r} would have no evidence: "
                    f"basis={parsed.evidence_basis}, "
                    f"native_source={'present' if parsed.native_source else 'absent'}, "
                    f"prose events={sum(1 for e in parsed.events if e.kind in PROSE_KINDS)}"
                )
        except BaseException:
            self._rollback()
            raise
        self._commit()
        return IngestResult(
            session_id=parsed.session.id,
            events_inserted=events_inserted,
            events_skipped=events_skipped,
            evidence_inserted=evidence_inserted,
            evidence_skipped=evidence_skipped,
            lineage_inserted=lineage_inserted,
            lineage_deferred=deferred,
        )

    def _upsert_session(self, session: Session) -> None:
        self._conn.execute(
            """
            INSERT INTO sessions(id, harness, project, branch, parent_id,
                                 started_at, ended_at, scope, intent, outcome)
            VALUES (:id, :harness, :project, :branch, :parent_id,
                    :started_at, :ended_at, :scope, :intent, :outcome)
            ON CONFLICT(id) DO UPDATE SET
                harness    = excluded.harness,
                project    = excluded.project,
                branch     = excluded.branch,
                parent_id  = excluded.parent_id,
                started_at = excluded.started_at,
                ended_at   = excluded.ended_at,
                scope      = excluded.scope,
                intent     = excluded.intent,
                outcome    = excluded.outcome
            """,
            {
                "id": session.id,
                "harness": session.harness,
                "project": session.project,
                "branch": session.branch,
                # A parent we have not ingested yet would trip the self-FK, and the
                # edge is already recorded in `lineage`.
                "parent_id": session.parent_id if self._session_exists(session.parent_id) else None,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "scope": session.scope,
                "intent": session.intent,
                "outcome": session.outcome,
            },
        )

    def _session_exists(self, session_id: str | None) -> bool:
        if session_id is None:
            return False
        row = self._conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row is not None

    def _insert_events(self, parsed: ParsedSession) -> tuple[int, int]:
        inserted = 0
        skipped = 0
        seen: set[str] = set()
        for event in parsed.events:
            content_hash = event.content_hash
            if content_hash in seen:
                skipped += 1
                continue
            seen.add(content_hash)
            cur = self._conn.execute(
                """
                INSERT INTO events(session_id, turn_id, seq, kind, actor,
                                   text, tool_name, ts, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, content_hash) DO NOTHING
                """,
                (
                    parsed.session.id,
                    event.turn_id,
                    event.seq,
                    event.kind,
                    event.actor,
                    event.text,
                    event.tool_name,
                    event.ts,
                    content_hash,
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped

    def _insert_evidence(self, parsed: ParsedSession) -> tuple[int, int]:
        """Insert the one evidence row this parse justifies, if any.

        OBSERVED needs the harness's native bytes. REPORTED (the archive path) has
        none, so the prose we hold becomes the evidence, labelled ``origin='archive'``
        -- the honest label for "this is a copy, not the original".
        """
        if parsed.evidence_basis == "REPORTED":
            body = _EVIDENCE_JOINER.join(
                event.text for event in parsed.events if event.kind in PROSE_KINDS and event.text
            )
            origin = "archive"
            source_bytes = body.encode("utf-8")
        else:
            native = parsed.native_source
            if native is None:
                return 0, 0
            # `replace` keeps a non-UTF-8 transcript ingestable; body_sha256 is still
            # taken over the native bytes, so the row records what was captured and
            # the body is explicitly a lossy text view of it.
            body = native.decode("utf-8", errors="replace")
            origin = "native"
            source_bytes = native
        if not body.strip():
            return 0, 0
        body_sha256 = _sha256_hex(source_bytes)
        row_id = evidence_id(parsed.session.id, origin, parsed.evidence_basis, body_sha256)
        cur = self._conn.execute(
            """
            INSERT INTO evidence(id, session_id, body, body_sha256,
                                 origin, basis, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                row_id,
                parsed.session.id,
                body,
                body_sha256,
                origin,
                parsed.evidence_basis,
                _now(),
            ),
        )
        return (1, 0) if cur.rowcount == 1 else (0, 1)

    def _insert_lineage(self, parsed: ParsedSession) -> tuple[int, tuple[str, ...]]:
        inserted = 0
        deferred: list[str] = []
        for parent_id in parsed.lineage:
            if parent_id == parsed.session.id:
                continue
            if not self._session_exists(parent_id):
                deferred.append(parent_id)
                continue
            cur = self._conn.execute(
                "INSERT INTO lineage(parent_id, child_id) VALUES (?, ?)"
                " ON CONFLICT(parent_id, child_id) DO NOTHING",
                (parent_id, parsed.session.id),
            )
            inserted += cur.rowcount if cur.rowcount > 0 else 0
        return inserted, tuple(deferred)

    def _evidence_count(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT count(*) AS n FROM evidence WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["n"])

    # -------------------------------------------------------------------- claims

    def add_claim(
        self,
        session_id: str,
        kind: ClaimKind,
        title: str,
        statement: str,
        tags: Sequence[str],
        confidence: float,
        writer: str,
        citations: Sequence[Mapping[str, str]] = (),
        *,
        created_at: str | None = None,
        supersedes: str | None = None,
    ) -> str:
        """Insert a claim and its quote-bound citations, all-or-nothing.

        Each citation is ``{"evidence_id": ..., "quote": ...}``. The quote is
        resolved to code-point offsets with ``str.find``; a quote that is missing,
        or that occurs more than once (so "the" offsets are a guess), is refused.
        The database re-proves the binding in a trigger regardless.

        Returns:
            The content-addressed claim id.

        Raises:
            ClaimValidationError: the claim's own fields are out of contract.
            CitationError: one or more quotes could not be resolved. Nothing written.
            DuplicateClaimError: this exact claim already exists.
        """
        self._validate_claim(kind, title, statement, tags, confidence, writer)
        new_id = claim_id(session_id, kind, title, statement, tags, confidence, writer)
        self._begin()
        try:
            if not self._session_exists(session_id):
                raise ClaimValidationError(f"unknown session {session_id!r}")
            resolved = self._resolve_citations(session_id, citations)
            try:
                self._conn.execute(
                    """
                    INSERT INTO claims(id, session_id, kind, title, statement, tags,
                                       confidence, writer, created_at, supersedes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id,
                        session_id,
                        kind,
                        title,
                        statement,
                        json.dumps(list(tags), ensure_ascii=False),
                        float(confidence),
                        writer,
                        created_at or _now(),
                        supersedes,
                    ),
                )
            except sqlite3.IntegrityError as err:
                if "claims.id" in str(err) or "UNIQUE" in str(err).upper():
                    raise DuplicateClaimError(f"claim {new_id} already exists") from err
                raise
            for index, (ev_id, start, end, quote) in enumerate(resolved):
                try:
                    self._conn.execute(
                        """
                        INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (new_id, ev_id, start, end, quote),
                    )
                except sqlite3.IntegrityError as err:
                    # The claim row is already in this transaction, so the rollback in
                    # the outer handler is what keeps "all or nothing" true here.
                    message = str(err)
                    reason: CitationReason = (
                        "duplicate_citation"
                        if "UNIQUE" in message.upper() or "PRIMARY KEY" in message.upper()
                        else "not_bound"
                    )
                    raise CitationError(
                        [
                            CitationProblem(
                                index=index,
                                evidence_id=ev_id,
                                quote=quote,
                                reason=reason,
                                detail=message,
                            )
                        ]
                    ) from err
        except BaseException:
            self._rollback()
            raise
        self._commit()
        return new_id

    def _validate_claim(
        self,
        kind: str,
        title: str,
        statement: str,
        tags: Sequence[str],
        confidence: float,
        writer: str,
    ) -> None:
        if kind not in CLAIM_KINDS:
            raise ClaimValidationError(f"kind {kind!r} not in {CLAIM_KINDS}")
        if not title or len(title) > 120:
            raise ClaimValidationError(f"title must be 1..120 chars, got {len(title)}")
        if not statement or len(statement) > 500:
            raise ClaimValidationError(f"statement must be 1..500 chars, got {len(statement)}")
        if not 2 <= len(tags) <= 5:
            raise ClaimValidationError(f"tags must hold 2..5 entries, got {len(tags)}")
        if not 0.5 <= float(confidence) <= 1.0:
            raise ClaimValidationError(f"confidence must be 0.5..1.0, got {confidence}")
        if not writer:
            raise ClaimValidationError("writer is required")

    def _resolve_citations(
        self,
        session_id: str,
        citations: Sequence[Mapping[str, str]],
    ) -> list[tuple[str, int, int, str]]:
        """Turn ``{evidence_id, quote}`` into ``(evidence_id, start, end, quote)``.

        Offsets are code points, because that is what SQLite's ``substr()`` counts.
        Byte or UTF-16 arithmetic desynchronises on any astral character and would
        produce citations the trigger then refuses.
        """
        problems: list[CitationProblem] = []
        resolved: list[tuple[str, int, int, str]] = []
        for index, citation in enumerate(citations):
            ev_id = citation.get("evidence_id", "")
            quote = citation.get("quote", "")
            row = self._conn.execute(
                "SELECT session_id, body FROM evidence WHERE id = ?", (ev_id,)
            ).fetchone()
            if row is None:
                problems.append(
                    CitationProblem(index, ev_id, quote, "unknown_evidence", "no such evidence row")
                )
                continue
            if str(row["session_id"]) != session_id:
                problems.append(
                    CitationProblem(
                        index,
                        ev_id,
                        quote,
                        "foreign_evidence",
                        f"evidence belongs to session {row['session_id']!r}, not {session_id!r}",
                    )
                )
                continue
            if not quote:
                problems.append(
                    CitationProblem(index, ev_id, quote, "empty_quote", "quote must be non-empty")
                )
                continue
            body = str(row["body"])
            start = body.find(quote)
            if start < 0:
                problems.append(
                    CitationProblem(
                        index, ev_id, quote, "quote_not_found", "quote is not present in the body"
                    )
                )
                continue
            if body.find(quote, start + 1) >= 0:
                problems.append(
                    CitationProblem(
                        index,
                        ev_id,
                        quote,
                        "ambiguous_quote",
                        f"quote occurs {body.count(quote)} times; offsets would be a guess",
                    )
                )
                continue
            resolved.append((ev_id, start, start + len(quote), quote))
        if problems:
            raise CitationError(problems)
        return resolved

    # --------------------------------------------------------------------- reads

    def visible_evidence(self, session_id: str) -> list[dict[str, str]]:
        """Every evidence body available for citation in ``session_id``."""
        rows = self._conn.execute(
            "SELECT id, body FROM evidence WHERE session_id = ? ORDER BY captured_at, id",
            (session_id,),
        ).fetchall()
        return [{"id": str(row["id"]), "body": str(row["body"])} for row in rows]

    def search_prose(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """FTS5 search over prose events only (``user`` / ``assistant_prose``)."""
        rows = self._conn.execute(
            """
            SELECT e.id AS event_id, e.session_id, e.kind, e.text
            FROM prose_fts
            JOIN events AS e ON e.id = prose_fts.rowid
            WHERE prose_fts MATCH ?
            ORDER BY bm25(prose_fts)
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def claim_citations(self, claim: str) -> list[dict[str, Any]]:
        """The citations bound to one claim, with their quotes and offsets."""
        rows = self._conn.execute(
            """
            SELECT evidence_id, "start" AS start, "end" AS end, quote
            FROM claim_citations WHERE claim_id = ? ORDER BY evidence_id, "start"
            """,
            (claim,),
        ).fetchall()
        return [dict(row) for row in rows]

    def row_counts(self) -> dict[str, int]:
        """Row count per table. The cheap way to assert "this changed nothing"."""
        names = [
            str(row["name"])
            for row in self._conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                  AND name NOT LIKE 'prose_fts%'
                ORDER BY name
                """
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for name in names:
            row = self._conn.execute(f'SELECT count(*) AS n FROM "{name}"').fetchone()
            counts[name] = int(row["n"])
        return counts

    def __iter__(self) -> Iterator[str]:
        """Session ids, oldest first. Convenience for the derivation pass."""
        for row in self._conn.execute(
            "SELECT id FROM sessions ORDER BY started_at IS NULL, started_at, id"
        ).fetchall():
            yield str(row["id"])
