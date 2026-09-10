"""The ADR-0011 v1.1 store: ingest typed sessions, add quote-bound claims.

Everything in this module is either one transaction or a read. There is no
"partially ingested session" state and no "claim whose citations didn't land"
state, because both would let unprovable provenance into the store.

Stage B.1 changes (council-reproduced defects, ADR v1.1):

* natural-language input to :meth:`Store.search_prose` goes through a planner;
  raw FTS syntax is the separate, explicit :meth:`Store.search_prose_raw`;
* evidence is per prose event, append-only, with native bytes retained alongside;
* a claim without a citation cannot be written, by the database;
* a child ingested before its parent parks the edge in ``lineage_pending`` and the
  parent's ingest reconciles it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
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
    "capture_evidence_id",
    "claim_id",
    "event_evidence_id",
    "plan_prose_query",
]

_UNSAFE: Final = frozenset({"Cc", "Cs"})
"""Unicode categories that FTS5 (a C-string parser) or SQLite's TEXT encoder reject."""

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
    """Ingest would have left a session with nothing citable, so it was rolled back."""


class ClaimValidationError(LearningMemoryError):
    """A claim's own fields are out of contract (kind, lengths, tags, confidence, citations)."""


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
    lineage_reconciled: int = 0
    """Pending edges that landed because THIS session is the parent they waited for."""
    lineage_deferred: tuple[str, ...] = ()
    """Parents of this session that are still absent: rows parked in ``lineage_pending``."""
    exporter_dupes_collapsed: int = 0
    """Echo of what the adapter folded before emitting (recorded on ``sessions``)."""


def _canonical_json(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def event_evidence_id(session_id: str, origin: str, body_sha256: str) -> str:
    """Id of a per-event (``REPORTED``) evidence row: ``sha256`` of a canonical payload.

    Deliberately **position-free**, unlike the event hash. The citation surface must
    survive re-derivation, reclassification and reordering (ADR v1.1, council
    finding 7): an evidence id is a function of *what the text is*, not of where in
    the session it sat, so re-ingesting a reordered parse produces no new evidence
    rows and no existing citation is stranded.

    The consequence, pinned by test: two prose events with byte-identical text in
    one session share one evidence row, whose ``event_id`` names the first
    occurrence. The body is still one message, so quote offsets stay unambiguous.
    """
    return _sha256_hex(
        _canonical_json(
            {
                "class": "event_prose",
                "session_id": session_id,
                "origin": origin,
                "basis": "REPORTED",
                "body_sha256": body_sha256,
            }
        )
    )


def capture_evidence_id(session_id: str, body_sha256: str) -> str:
    """Id of a native-capture (``OBSERVED``) evidence row.

    Carries a different ``class`` discriminator from :func:`event_evidence_id` so a
    single-message session whose native transcript IS that message cannot collide
    its capture row with its citation row.
    """
    return _sha256_hex(
        _canonical_json(
            {
                "class": "native_capture",
                "session_id": session_id,
                "origin": "native",
                "basis": "OBSERVED",
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
    """Content address of a claim. ``created_at`` is excluded so the id is stable.

    Stage E widens this to cover the citation-set fingerprint and ``supersedes``
    (council finding 12); until claims are written by a model there is nothing to
    fingerprint.
    """
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


def plan_prose_query(query: str) -> str:
    """Turn arbitrary human text into an FTS5 expression that cannot be misread.

    Every whitespace-separated token becomes a **phrase** (embedded ``"`` doubled)
    and the phrases are OR-joined, so nothing in the user's words can reach FTS5 as
    syntax: ``AND``, ``NOT``, ``(``, ``*``, a bare column name, or a bare number.
    ``WP-9`` stays one phrase, so it still matches adjacently rather than being
    split into two independent terms.

    Control characters and lone surrogates are stripped first. FTS5 parses its
    expression as a C string, so a NUL inside a phrase ends the string early and the
    closing quote is never seen (``OperationalError: unterminated string``); a lone
    surrogate cannot be encoded as TEXT at all.

    Tokens with no alphanumeric character left are dropped -- a phrase containing no
    tokens is not a legal FTS5 expression -- so ``"?"``, ``"---"`` and ``""`` plan to
    the empty string, which callers treat as "no query, no rows".

    Stage F measures OR against AND-then-OR-fallback on DEV; OR is the arm that
    cannot throw.
    """
    tokens: list[str] = []
    for raw_token in query.split():
        token = "".join(char for char in raw_token if unicodedata.category(char) not in _UNSAFE)
        if any(char.isalnum() for char in token):
            tokens.append(token)
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)


class Store:
    """A single-file SQLite learning-memory store.

    The live ``sessions.db`` is never opened by this class; a PoC store is its own
    file (ADR-0011 Consequences).

    :attr:`connection` is available for tests, the derivation pass and the scorer,
    but it is **not** the write contract: the invariants that matter are enforced by
    triggers, so a raw writer is refused rather than trusted.
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
        """The underlying connection. Read/diagnostic surface, not the write contract."""
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
        found = int(row["version"])
        if found != SCHEMA_VERSION:
            # No migration on purpose: nothing real has been ingested yet, so a
            # rebuild from the adapters is cheaper and more honest than an upgrade
            # path nobody has exercised.
            raise SchemaError(
                f"store is schema v{found}, this code writes v{SCHEMA_VERSION}; "
                f"v{found} predates ADR-0011 v1.1 and there is no migration -- "
                "rebuild the store from the adapters"
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
        """Commit, rolling back if a DEFERRED constraint fails at commit time."""
        try:
            self._conn.execute("COMMIT")
        except sqlite3.DatabaseError:
            # A failed COMMIT leaves the transaction open in SQLite; without this
            # the connection would be stuck inside a doomed transaction.
            self._rollback()
            raise

    # -------------------------------------------------------------------- ingest

    def ingest(self, parsed: ParsedSession) -> IngestResult:
        """Write one parsed session: session, events, evidence and lineage, atomically.

        Raises:
            NoEvidenceError: if the write would leave the session with no *citable*
                evidence, i.e. no per-event row. The transaction is rolled back, so
                no session row survives either. A native capture row alone is not
                enough: a session with nothing citable has nothing to retrieve.
        """
        self._begin()
        try:
            self._upsert_session(parsed)
            events_inserted, events_skipped = self._insert_events(parsed)
            evidence_inserted, evidence_skipped = self._insert_evidence(parsed)
            lineage_inserted, reconciled, deferred = self._reconcile_lineage(parsed)
            if self._citable_evidence_count(parsed.session.id) == 0:
                prose = sum(1 for event in parsed.events if event.kind in PROSE_KINDS)
                raise NoEvidenceError(
                    f"session {parsed.session.id!r} has nothing citable: "
                    f"prose events={prose}, "
                    f"native_source={'present' if parsed.native_source else 'absent'}"
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
            lineage_reconciled=reconciled,
            lineage_deferred=deferred,
            exporter_dupes_collapsed=parsed.exporter_dupes_collapsed,
        )

    def _upsert_session(self, parsed: ParsedSession) -> None:
        session: Session = parsed.session
        self._conn.execute(
            """
            INSERT INTO sessions(id, harness, project, branch, parent_id,
                                 started_at, ended_at, scope, intent, outcome,
                                 adapter_version, classifier_version,
                                 exporter_dupes_collapsed)
            VALUES (:id, :harness, :project, :branch, :parent_id,
                    :started_at, :ended_at, :scope, :intent, :outcome,
                    :adapter_version, :classifier_version, :exporter_dupes_collapsed)
            ON CONFLICT(id) DO UPDATE SET
                harness                  = excluded.harness,
                project                  = excluded.project,
                branch                   = excluded.branch,
                parent_id                = coalesce(excluded.parent_id, sessions.parent_id),
                started_at               = excluded.started_at,
                ended_at                 = excluded.ended_at,
                scope                    = excluded.scope,
                intent                   = excluded.intent,
                outcome                  = excluded.outcome,
                adapter_version          = excluded.adapter_version,
                classifier_version       = excluded.classifier_version,
                exporter_dupes_collapsed = excluded.exporter_dupes_collapsed
            """,
            {
                "id": session.id,
                "harness": session.harness,
                "project": session.project,
                "branch": session.branch,
                # A parent we have not ingested yet would trip the self-FK. The edge
                # is never lost: it is parked in `lineage_pending` below, which is
                # the authoritative record -- `sessions.parent_id` is a convenience
                # denormalisation that is only filled when the parent is present.
                "parent_id": session.parent_id if self._session_exists(session.parent_id) else None,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "scope": session.scope,
                "intent": session.intent,
                "outcome": session.outcome,
                "adapter_version": parsed.adapter_version,
                "classifier_version": parsed.classifier_version,
                "exporter_dupes_collapsed": parsed.exporter_dupes_collapsed,
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
        """Write the citation surface: one row per prose event, plus any capture.

        Reads the events back out of the database rather than trusting the parse, so
        a re-ingest of an already-stored session re-derives exactly the same rows
        (and inserts none of them twice).
        """
        session_id = parsed.session.id
        origin = "archive" if parsed.native_source is None else "native"
        inserted = 0
        skipped = 0
        rows = self._conn.execute(
            """
            SELECT id, text FROM events
            WHERE session_id = ? AND kind IN ('user', 'assistant_prose')
            ORDER BY turn_id, seq, id
            """,
            (session_id,),
        ).fetchall()
        for row in rows:
            text = str(row["text"])
            if not text.strip():
                continue
            body_sha256 = _sha256_hex(text.encode("utf-8"))
            added = self._insert_evidence_row(
                row_id=event_evidence_id(session_id, origin, body_sha256),
                session_id=session_id,
                event_id=int(row["id"]),
                body=text,
                body_sha256=body_sha256,
                raw=None,
                origin=origin,
                basis="REPORTED",
            )
            inserted += added
            skipped += 1 - added

        native = parsed.native_source
        if native is not None:
            # `replace` keeps a non-UTF-8 transcript ingestable; the raw bytes are
            # retained in full and body_sha256 is taken over them, so the row is a
            # capture receipt and `body` is explicitly a lossy text view of it.
            body = native.decode("utf-8", errors="replace")
            body_sha256 = _sha256_hex(native)
            added = self._insert_evidence_row(
                row_id=capture_evidence_id(session_id, body_sha256),
                session_id=session_id,
                event_id=None,
                body=body,
                body_sha256=body_sha256,
                raw=native,
                origin="native",
                basis="OBSERVED",
            )
            inserted += added
            skipped += 1 - added
        return inserted, skipped

    def _insert_evidence_row(
        self,
        *,
        row_id: str,
        session_id: str,
        event_id: int | None,
        body: str,
        body_sha256: str,
        raw: bytes | None,
        origin: str,
        basis: str,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO evidence(id, session_id, event_id, body, body_sha256,
                                 raw, origin, basis, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (row_id, session_id, event_id, body, body_sha256, raw, origin, basis, _now()),
        )
        return 1 if cur.rowcount == 1 else 0

    def _reconcile_lineage(self, parsed: ParsedSession) -> tuple[int, int, tuple[str, ...]]:
        """Land what can land, park what cannot, and collect what was waiting for us.

        Returns ``(edges_inserted, pending_reconciled, still_pending)``.
        """
        session_id = parsed.session.id
        # A declared `session.parent_id` is a lineage edge too: if it were only
        # honoured as a column it would be lost whenever the parent lands later.
        candidates: list[str] = list(parsed.lineage)
        if parsed.session.parent_id:
            candidates.append(parsed.session.parent_id)
        declared: list[str] = []
        for parent_id in candidates:
            if parent_id != session_id and parent_id not in declared:
                declared.append(parent_id)
        inserted = 0
        for parent_id in declared:
            if self._session_exists(parent_id):
                inserted += self._insert_lineage_edge(parent_id, session_id)
                self._conn.execute(
                    "DELETE FROM lineage_pending WHERE child_id = ? AND parent_id = ?",
                    (session_id, parent_id),
                )
            else:
                self._conn.execute(
                    "INSERT INTO lineage_pending(child_id, parent_id) VALUES (?, ?)"
                    " ON CONFLICT(child_id, parent_id) DO NOTHING",
                    (session_id, parent_id),
                )

        # This session may be the parent other children parked an edge for.
        cur = self._conn.execute(
            """
            INSERT INTO lineage(parent_id, child_id)
            SELECT parent_id, child_id FROM lineage_pending WHERE parent_id = ?
            ON CONFLICT(parent_id, child_id) DO NOTHING
            """,
            (session_id,),
        )
        reconciled = max(cur.rowcount, 0)
        self._conn.execute("DELETE FROM lineage_pending WHERE parent_id = ?", (session_id,))

        still_pending = tuple(
            str(row["parent_id"])
            for row in self._conn.execute(
                "SELECT parent_id FROM lineage_pending WHERE child_id = ? ORDER BY parent_id",
                (session_id,),
            ).fetchall()
        )
        return inserted, reconciled, still_pending

    def _insert_lineage_edge(self, parent_id: str, child_id: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO lineage(parent_id, child_id) VALUES (?, ?)"
            " ON CONFLICT(parent_id, child_id) DO NOTHING",
            (parent_id, child_id),
        )
        return 1 if cur.rowcount == 1 else 0

    def _citable_evidence_count(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT count(*) AS n FROM evidence WHERE session_id = ? AND event_id IS NOT NULL",
            (session_id,),
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
        or that occurs more than once inside that one evidence body (so "the"
        offsets are a guess), is refused. The database re-proves the binding in a
        trigger regardless.

        **Citations are written first** (ADR v1.1): ``claim_citations.claim_id`` is a
        DEFERRED foreign key, so the citations exist before the claim row does, and
        the ``claims_need_citation`` trigger can therefore refuse a claim that has
        none -- including one written by raw SQL.

        Returns:
            The content-addressed claim id.

        Raises:
            ClaimValidationError: the claim's own fields are out of contract, the
                session is unknown, or ``citations`` is empty.
            CitationError: one or more quotes could not be resolved. Nothing written.
            DuplicateClaimError: this exact claim already exists.
        """
        self._validate_claim(kind, title, statement, tags, confidence, writer, citations)
        new_id = claim_id(session_id, kind, title, statement, tags, confidence, writer)
        self._begin()
        try:
            if not self._session_exists(session_id):
                raise ClaimValidationError(f"unknown session {session_id!r}")
            if self._conn.execute("SELECT 1 FROM claims WHERE id = ?", (new_id,)).fetchone():
                raise DuplicateClaimError(f"claim {new_id} already exists")
            resolved = self._resolve_citations(session_id, citations)
            self._insert_citations(new_id, resolved)
            self._insert_claim(
                new_id,
                session_id,
                kind,
                title,
                statement,
                tags,
                confidence,
                writer,
                created_at,
                supersedes,
            )
        except BaseException:
            self._rollback()
            raise
        self._commit()
        return new_id

    def _insert_citations(self, claim: str, resolved: Sequence[tuple[str, int, int, str]]) -> None:
        for index, (ev_id, start, end, quote) in enumerate(resolved):
            try:
                self._conn.execute(
                    """
                    INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (claim, ev_id, start, end, quote),
                )
            except sqlite3.IntegrityError as err:
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

    def _insert_claim(
        self,
        claim: str,
        session_id: str,
        kind: str,
        title: str,
        statement: str,
        tags: Sequence[str],
        confidence: float,
        writer: str,
        created_at: str | None,
        supersedes: str | None,
    ) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO claims(id, session_id, kind, title, statement, tags,
                                   confidence, writer, created_at, supersedes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim,
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
            if "claims.id" in str(err):
                raise DuplicateClaimError(f"claim {claim} already exists") from err
            raise

    def _validate_claim(
        self,
        kind: str,
        title: str,
        statement: str,
        tags: Sequence[str],
        confidence: float,
        writer: str,
        citations: Sequence[Mapping[str, str]],
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
        if not citations:
            raise ClaimValidationError(
                "a claim needs at least one citation: an unproven claim is not a claim"
            )

    def _resolve_citations(
        self,
        session_id: str,
        citations: Sequence[Mapping[str, str]],
    ) -> list[tuple[str, int, int, str]]:
        """Turn ``{evidence_id, quote}`` into ``(evidence_id, start, end, quote)``.

        Offsets are code points, because that is what SQLite's ``substr()`` counts.
        Byte or UTF-16 arithmetic desynchronises on any astral character and would
        produce citations the trigger then refuses.

        Ambiguity is judged inside the named evidence body only, which under ADR
        v1.1 is one message: the same phrase in two events is two evidence rows, so
        naming the row disambiguates it.
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

    def visible_evidence(self, session_id: str) -> list[dict[str, Any]]:
        """The citation surface for ``session_id``: one row per prose event.

        Ordered by ``(turn_id, seq)`` -- reading order -- and carrying ``event_id``,
        so a writer can cite a specific message rather than hunting through a
        session-sized body. Native capture rows are deliberately absent; see
        :meth:`captures`.
        """
        rows = self._conn.execute(
            """
            SELECT ev.id, ev.body, ev.event_id, e.turn_id, e.seq, e.kind
            FROM evidence AS ev
            JOIN events AS e ON e.id = ev.event_id
            WHERE ev.session_id = ?
            ORDER BY e.turn_id, e.seq, ev.id
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def captures(self, session_id: str) -> list[dict[str, Any]]:
        """The ``OBSERVED`` native-capture rows: retained bytes plus their digest."""
        rows = self._conn.execute(
            """
            SELECT id, body_sha256, length(raw) AS raw_bytes, origin, captured_at
            FROM evidence
            WHERE session_id = ? AND event_id IS NULL
            ORDER BY captured_at, id
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_prose(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search prose events with arbitrary human text. Never raises on the query.

        The input goes through :func:`plan_prose_query`, so an ordinary question --
        ``"Which ADR path did the DoD and WP-9 require?"`` -- is a bag of phrases,
        not an FTS5 expression. For deliberate FTS5 syntax use
        :meth:`search_prose_raw`.
        """
        planned = plan_prose_query(query)
        if not planned:
            return []
        return self._match(planned, limit)

    def search_prose_raw(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search prose events with an explicit FTS5 expression.

        Raises:
            sqlite3.OperationalError: if ``query`` is not valid FTS5. That is the
                point of having this as a separate method.
        """
        return self._match(query, limit)

    def _match(self, expression: str, limit: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT e.id AS event_id, e.session_id, e.kind, e.text
            FROM prose_fts
            JOIN events AS e ON e.id = prose_fts.rowid
            WHERE prose_fts MATCH ?
            ORDER BY bm25(prose_fts)
            LIMIT ?
            """,
            (expression, limit),
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

    def pending_lineage(self) -> list[dict[str, str]]:
        """Every edge still waiting for its parent to be ingested."""
        rows = self._conn.execute(
            "SELECT child_id, parent_id FROM lineage_pending ORDER BY child_id, parent_id"
        ).fetchall()
        return [
            {"child_id": str(row["child_id"]), "parent_id": str(row["parent_id"])} for row in rows
        ]

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
