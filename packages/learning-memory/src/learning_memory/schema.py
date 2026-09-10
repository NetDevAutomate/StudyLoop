"""SQLite DDL for the ADR-0011 v1.1 claim-centric learning-memory store.

Schema v2 (Stage B.1). What is load-bearing here, and must not be "simplified":

1. ``UNIQUE(session_id, content_hash)`` on ``events`` — re-parse of the same source
   is a no-op. The hash is **position-bearing** (v1.1 council finding 5), so every
   observed occurrence is its own row and a repeated tool call stays two rows.
2. ``claim_citation_bound_proof`` — a claim's quote must actually be the bytes at
   the offsets it names, checked *in the database*, so no writer (model, agent or
   human) can assert provenance it does not have. Offsets are **code points**:
   SQLite's ``substr()`` on a TEXT value counts characters, which is what Python's
   ``str`` indexing counts too, so the two agree for astral characters where byte
   or UTF-16 arithmetic would not.
3. ``claims_need_citation`` (v1.1 council finding 1) — a claim with no citation is
   refused by the database. This works only because ``claim_citations.claim_id`` is
   ``DEFERRABLE INITIALLY DEFERRED`` and the store writes citations *first*.
4. ``claims_immutable`` — a claim is superseded, never edited.
5. ``evidence_immutable_*`` (v1.1 council finding 2) — evidence is append-only. A
   re-capture is a new row with a new id, so a citation can never be re-pointed at
   text that changed under it.
6. ``prose_events`` is a VIEW and ``prose_fts`` is external-content over the VIEW
   (v1.1 council finding 4), so FTS5's own ``'rebuild'`` cannot pull tool output
   into the index — the filter lives in the content source, not only in triggers.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

__all__ = [
    "DEFAULT_TOKENIZER",
    "PRAGMAS",
    "SCHEMA_VERSION",
    "TOKENIZERS",
    "Tokenizer",
    "ddl",
]

SCHEMA_VERSION: Final = 2
"""v1 was Stage B. v2 is the council-revised (ADR v1.1) shape.

There is no migration: nothing real has been ingested yet, so ``install()`` refuses
an older file by version rather than pretending to upgrade it.
"""

Tokenizer = Literal["porter unicode61", "unicode61"]
"""ADR-0011 leaves the tokenizer open, "to be settled by measurement".

So it is a parameter, not a constant — but a closed one, because it is
interpolated into DDL.
"""

TOKENIZERS: Final[tuple[Tokenizer, ...]] = get_args(Tokenizer)

DEFAULT_TOKENIZER: Final[Tokenizer] = "porter unicode61"

PRAGMAS: Final[tuple[str, ...]] = (
    # Every FK in this schema is a real constraint; SQLite ignores them unless
    # asked, per connection. The deferred FK on claim_citations is inert without it.
    "PRAGMA foreign_keys = ON",
    "PRAGMA journal_mode = WAL",
    "PRAGMA busy_timeout = 5000",
)

_DDL: Final = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    tokenizer  TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id                       TEXT PRIMARY KEY,
    harness                  TEXT NOT NULL,
    project                  TEXT,
    branch                   TEXT,
    parent_id                TEXT REFERENCES sessions(id),
    started_at               TEXT,
    ended_at                 TEXT,
    scope                    TEXT,
    intent                   TEXT,
    outcome                  TEXT,
    -- v1.1: provenance of the typing itself. A classifier change produces new
    -- event rows under a new version rather than silently restating old ones.
    adapter_version          TEXT NOT NULL DEFAULT 'unspecified',
    classifier_version       TEXT,
    -- Adjacent exporter duplicates the ADAPTER folded before emitting (v1.1
    -- council finding 5): recorded so the count is auditable, not inferred.
    exporter_dupes_collapsed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    session_id   TEXT    NOT NULL REFERENCES sessions(id),
    turn_id      INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN (
                     'user', 'assistant_prose', 'tool_call',
                     'tool_result', 'system', 'thinking', 'error')),
    actor        TEXT,
    text         TEXT    NOT NULL,
    tool_name    TEXT,
    ts           TEXT,
    content_hash TEXT    NOT NULL,
    UNIQUE (session_id, content_hash)
);

CREATE INDEX IF NOT EXISTS events_session_seq ON events(session_id, turn_id, seq);

-- v1.1: one REPORTED row per prose EVENT (event_id set) is the citation surface;
-- one OBSERVED row per native capture keeps the raw bytes (raw, event_id NULL).
CREATE TABLE IF NOT EXISTS evidence (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    event_id    INTEGER REFERENCES events(id),
    body        TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    raw         BLOB,
    origin      TEXT NOT NULL,
    basis       TEXT NOT NULL CHECK (basis IN ('OBSERVED', 'REPORTED')),
    captured_at TEXT NOT NULL,
    CHECK (basis <> 'REPORTED' OR event_id IS NOT NULL),
    CHECK (basis <> 'OBSERVED' OR raw IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS evidence_session ON evidence(session_id);
CREATE INDEX IF NOT EXISTS evidence_event ON evidence(event_id);

-- Append-only. Not "append-only unless the row is uncited": a mutable body would
-- make every citation's bound-proof a statement about the past.
CREATE TRIGGER IF NOT EXISTS evidence_immutable_update
BEFORE UPDATE ON evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence is append-only: capture a new row instead');
END;

CREATE TRIGGER IF NOT EXISTS evidence_immutable_delete
BEFORE DELETE ON evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence is append-only: rows are never deleted');
END;

CREATE TABLE IF NOT EXISTS lineage (
    parent_id TEXT NOT NULL REFERENCES sessions(id),
    child_id  TEXT NOT NULL REFERENCES sessions(id),
    PRIMARY KEY (parent_id, child_id)
);

-- v1.1 council finding 6: a child ingested before its parent records the edge HERE,
-- in its own transaction. The parent's ingest reconciles it into `lineage`. parent_id
-- deliberately carries no FK — that absence is the whole point of the table.
CREATE TABLE IF NOT EXISTS lineage_pending (
    child_id  TEXT NOT NULL REFERENCES sessions(id),
    parent_id TEXT NOT NULL,
    PRIMARY KEY (child_id, parent_id)
);

CREATE INDEX IF NOT EXISTS lineage_pending_parent ON lineage_pending(parent_id);

-- The filter that keeps tool output out of recall, expressed as the FTS content
-- source so 'rebuild' and 'integrity-check' obey it too.
CREATE VIEW IF NOT EXISTS prose_events AS
SELECT id, text FROM events WHERE kind IN ('user', 'assistant_prose');

CREATE VIRTUAL TABLE IF NOT EXISTS prose_fts USING fts5(
    text,
    content='prose_events',
    content_rowid='id',
    tokenize='{tokenizer}'
);

CREATE TRIGGER IF NOT EXISTS events_prose_ai AFTER INSERT ON events
WHEN NEW.kind IN ('user', 'assistant_prose')
BEGIN
    INSERT INTO prose_fts(rowid, text) VALUES (NEW.id, NEW.text);
END;

CREATE TRIGGER IF NOT EXISTS events_prose_ad AFTER DELETE ON events
WHEN OLD.kind IN ('user', 'assistant_prose')
BEGIN
    INSERT INTO prose_fts(prose_fts, rowid, text) VALUES ('delete', OLD.id, OLD.text);
END;

CREATE TRIGGER IF NOT EXISTS events_prose_au AFTER UPDATE ON events
BEGIN
    INSERT INTO prose_fts(prose_fts, rowid, text)
    SELECT 'delete', OLD.id, OLD.text
    WHERE OLD.kind IN ('user', 'assistant_prose');
    INSERT INTO prose_fts(rowid, text)
    SELECT NEW.id, NEW.text
    WHERE NEW.kind IN ('user', 'assistant_prose');
END;

-- v1.1: derivation output is versioned and rebuilt per version, rather than
-- assuming UNIQUE(session_id, turn_id) survives a renumbering.
CREATE TABLE IF NOT EXISTS exchanges (
    id                 INTEGER PRIMARY KEY,
    session_id         TEXT    NOT NULL REFERENCES sessions(id),
    derivation_version TEXT    NOT NULL,
    turn_id            INTEGER NOT NULL,
    question_event_id  INTEGER REFERENCES events(id),
    answer_event_ids   TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(answer_event_ids)),
    is_question        INTEGER NOT NULL DEFAULT 0 CHECK (is_question IN (0, 1)),
    had_error          INTEGER NOT NULL DEFAULT 0 CHECK (had_error IN (0, 1)),
    retried            INTEGER NOT NULL DEFAULT 0 CHECK (retried IN (0, 1)),
    -- NULL is "could not be threaded deterministically" (quarantined), not "no".
    resolved           INTEGER CHECK (resolved IN (0, 1)),
    UNIQUE (session_id, derivation_version, turn_id)
);

-- v1.1: canonical concept id + aliases, replacing recurrence.session_ids JSON.
CREATE TABLE IF NOT EXISTS concepts (
    id        TEXT PRIMARY KEY,
    canonical TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS concept_aliases (
    alias      TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL REFERENCES concepts(id)
);

CREATE TABLE IF NOT EXISTS concept_tags (
    exchange_id INTEGER NOT NULL REFERENCES exchanges(id),
    concept_id  TEXT    NOT NULL REFERENCES concepts(id),
    source      TEXT    NOT NULL CHECK (source IN ('vocab', 'alias', 'model')),
    PRIMARY KEY (exchange_id, concept_id, source)
);

CREATE TABLE IF NOT EXISTS concept_occurrences (
    concept_id         TEXT NOT NULL REFERENCES concepts(id),
    session_id         TEXT NOT NULL REFERENCES sessions(id),
    derivation_version TEXT NOT NULL,
    observed_at        TEXT NOT NULL,
    PRIMARY KEY (concept_id, session_id, derivation_version, observed_at)
);

CREATE TABLE IF NOT EXISTS claims (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    kind       TEXT NOT NULL CHECK (kind IN (
                   'Problem', 'Finding', 'Decision', 'Procedure', 'Preference')),
    title      TEXT NOT NULL CHECK (length(title) > 0 AND length(title) <= 120),
    statement  TEXT NOT NULL CHECK (length(statement) > 0 AND length(statement) <= 500),
    tags       TEXT NOT NULL CHECK (
                   json_valid(tags)
                   AND json_type(tags) = 'array'
                   AND json_array_length(tags) BETWEEN 2 AND 5),
    confidence REAL NOT NULL CHECK (confidence >= 0.5 AND confidence <= 1.0),
    writer     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    supersedes TEXT REFERENCES claims(id)
);

CREATE INDEX IF NOT EXISTS claims_session ON claims(session_id);
CREATE INDEX IF NOT EXISTS claims_supersedes ON claims(supersedes);

-- `start`/`end` are code-point offsets into evidence.body, half-open [start, end).
-- `end` is a keyword, hence quoted throughout.
-- claim_id's FK is DEFERRED so citations can be written BEFORE the claim they
-- belong to; that write order is what lets claims_need_citation below be a real
-- constraint instead of advice.
CREATE TABLE IF NOT EXISTS claim_citations (
    claim_id    TEXT    NOT NULL REFERENCES claims(id) DEFERRABLE INITIALLY DEFERRED,
    evidence_id TEXT    NOT NULL REFERENCES evidence(id),
    "start"     INTEGER NOT NULL CHECK ("start" >= 0),
    "end"       INTEGER NOT NULL,
    quote       TEXT    NOT NULL CHECK (length(quote) > 0),
    PRIMARY KEY (claim_id, evidence_id, "start", "end"),
    CHECK ("end" > "start")
);

CREATE INDEX IF NOT EXISTS claim_citations_evidence ON claim_citations(evidence_id);

-- The bound-proof. A citation may only exist if the quote IS the text at the
-- offsets it claims. SQLite substr() is 1-based, so start+1.
CREATE TRIGGER IF NOT EXISTS claim_citation_bound_proof
BEFORE INSERT ON claim_citations
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM evidence
        WHERE evidence.id = NEW.evidence_id
          AND substr(evidence.body, NEW."start" + 1, NEW."end" - NEW."start") = NEW.quote
    ) THEN RAISE(ABORT, 'citation does not bind') END;
END;

-- Same proof on the UPDATE path: rebinding a citation to offsets that do not
-- hold would otherwise launder an unbound quote past the INSERT trigger.
CREATE TRIGGER IF NOT EXISTS claim_citation_bound_proof_update
BEFORE UPDATE ON claim_citations
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM evidence
        WHERE evidence.id = NEW.evidence_id
          AND substr(evidence.body, NEW."start" + 1, NEW."end" - NEW."start") = NEW.quote
    ) THEN RAISE(ABORT, 'citation does not bind') END;
END;

-- v1.1 council finding 1: an unproven claim cannot exist, whoever writes it.
CREATE TRIGGER IF NOT EXISTS claims_need_citation
AFTER INSERT ON claims
WHEN NOT EXISTS (SELECT 1 FROM claim_citations WHERE claim_id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'claim has no citation: write citations first');
END;

CREATE TRIGGER IF NOT EXISTS claims_immutable
BEFORE UPDATE ON claims
BEGIN
    SELECT RAISE(ABORT, 'claims are immutable: supersede instead');
END;

CREATE TABLE IF NOT EXISTS claim_relations (
    from_id TEXT NOT NULL REFERENCES claims(id),
    to_id   TEXT NOT NULL REFERENCES claims(id),
    kind    TEXT NOT NULL CHECK (kind IN ('supports', 'contradicts', 'corrects')),
    PRIMARY KEY (from_id, to_id, kind)
);

CREATE TABLE IF NOT EXISTS review_items (
    id         INTEGER PRIMARY KEY,
    claim_id   TEXT NOT NULL REFERENCES claims(id),
    front      TEXT NOT NULL,
    back       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('flashcard', 'quiz', 'teach_back')),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS review_items_claim ON review_items(claim_id);
"""


def ddl(tokenizer: Tokenizer = DEFAULT_TOKENIZER) -> str:
    """Return the whole schema script for ``tokenizer``.

    Raises:
        ValueError: if ``tokenizer`` is not one of :data:`TOKENIZERS`. The value is
            interpolated into DDL, so the allowlist is a security boundary, not a
            typo check -- ``Tokenizer`` is erased at runtime.
    """
    if tokenizer not in TOKENIZERS:
        raise ValueError(f"unsupported tokenizer {tokenizer!r}; expected one of {TOKENIZERS}")
    return _DDL.replace("{tokenizer}", tokenizer)
