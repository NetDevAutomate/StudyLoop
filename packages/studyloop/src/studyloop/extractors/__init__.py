"""Struggle-extraction pipeline.

Reads study-session transcripts from sessions.db, identifies topics the learner
struggled with, and upserts structured rows into ``study_progress`` via
``record_progress()``.

The production extractor is :mod:`studyloop.extractors.llm`. Pipeline tests
inject their deterministic double from the test package; fixture-backed
extractors are never distributed with StudyLoop.

Confidence values mirror the ``study_progress`` vocabulary used elsewhere in the
codebase (see ``mcp/tools.py`` ``_CONFIDENCE_MAP``).
"""

from __future__ import annotations

from dataclasses import dataclass

# The only confidence labels an extractor may emit.  Matches the values
# record_progress() and the web struggling-topics query already understand.
VALID_CONFIDENCE = frozenset({"struggling", "learning", "confident"})


@dataclass(frozen=True, slots=True)
class ExtractorResult:
    """One (topic, concept, confidence) struggle signal extracted from a session.

    Frozen so a result cannot be mutated after validation, and so results are
    hashable — handy for de-duping within a single session's output.
    """

    topic: str
    concept: str
    confidence: str
    notes: str | None = None

    def validate(self) -> ExtractorResult:
        """Return self if structurally valid, else raise ``ValueError``.

        Structural validity only — never asserts semantic correctness of the
        extracted content (that is the quality-eval tier's job).  Checks:
        topic and concept are non-empty after strip; confidence is one of
        :data:`VALID_CONFIDENCE`.
        """
        if not self.topic or not self.topic.strip():
            raise ValueError(f"ExtractorResult.topic must be non-empty, got {self.topic!r}")
        if not self.concept or not self.concept.strip():
            raise ValueError(f"ExtractorResult.concept must be non-empty, got {self.concept!r}")
        if self.confidence not in VALID_CONFIDENCE:
            allowed = ", ".join(sorted(VALID_CONFIDENCE))
            raise ValueError(
                f"ExtractorResult.confidence must be one of {{{allowed}}}, got {self.confidence!r}"
            )
        return self


__all__ = ["VALID_CONFIDENCE", "ExtractorResult"]
