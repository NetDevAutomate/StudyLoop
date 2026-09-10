"""Claim-centric learning memory (ADR-0011 v1.1 PoC).

Capture is lossless and typed; usefulness is derived at capture time and bound to
provenance the database itself can prove.
"""

from __future__ import annotations

from learning_memory.model import (
    CLAIM_KINDS,
    EVENT_KINDS,
    PROSE_KINDS,
    ClaimKind,
    ClaimRelationKind,
    ConceptSource,
    Event,
    EventKind,
    EvidenceBasis,
    HarnessAdapter,
    ParsedSession,
    ReviewItemKind,
    Session,
    SourceRef,
    collapse_adjacent_duplicates,
    event_content_hash,
)
from learning_memory.schema import (
    DEFAULT_TOKENIZER,
    PRAGMAS,
    SCHEMA_VERSION,
    TOKENIZERS,
    Tokenizer,
    ddl,
)
from learning_memory.store import (
    CitationError,
    CitationProblem,
    ClaimValidationError,
    DuplicateClaimError,
    IngestResult,
    LearningMemoryError,
    NoEvidenceError,
    SchemaError,
    Store,
    capture_evidence_id,
    claim_id,
    event_evidence_id,
    plan_prose_query,
)

__version__ = "0.1.0"

__all__ = [
    "CLAIM_KINDS",
    "DEFAULT_TOKENIZER",
    "EVENT_KINDS",
    "PRAGMAS",
    "PROSE_KINDS",
    "SCHEMA_VERSION",
    "TOKENIZERS",
    "CitationError",
    "CitationProblem",
    "ClaimKind",
    "ClaimRelationKind",
    "ClaimValidationError",
    "ConceptSource",
    "DuplicateClaimError",
    "Event",
    "EventKind",
    "EvidenceBasis",
    "HarnessAdapter",
    "IngestResult",
    "LearningMemoryError",
    "NoEvidenceError",
    "ParsedSession",
    "ReviewItemKind",
    "SchemaError",
    "Session",
    "SourceRef",
    "Store",
    "Tokenizer",
    "__version__",
    "capture_evidence_id",
    "claim_id",
    "collapse_adjacent_duplicates",
    "ddl",
    "event_content_hash",
    "event_evidence_id",
    "plan_prose_query",
]
