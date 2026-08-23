"""Trusted evidence catalogue and source-tier policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import EvidenceValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import EvidenceRef

SOURCE_TIERS: dict[str, int] = {
    "studyloop_practice": 1,
    "studyloop_teach_back": 1,
    "studyloop_review": 1,
    "studyloop_progress": 1,
    "studyloop_completed_session": 1,
    "coding_harness_activity": 2,
    "learner_self_report": 3,
    "course_structure": 4,
    "course_access": 4,
    "supplied_material": 4,
    "notes": 4,
    "transcript": 4,
    "ai_augmented_notes": 4,
    "imported_plan": 4,
}


def tier_for_source(source_kind: str) -> int:
    """Return the normative tier for a trusted source kind."""
    try:
        return SOURCE_TIERS[source_kind]
    except KeyError as error:
        raise EvidenceValidationError(f"unknown evidence source kind {source_kind!r}") from error


class EvidenceCatalogue:
    """In-process projection of evidence identities issued by trusted adapters.

    It does not accept model-authored evidence objects. Product adapters may
    replace this implementation with one backed by StudyLoop stores as long as
    the same identity and tier checks hold.
    """

    def __init__(self, evidence: Iterable[EvidenceRef] = ()) -> None:
        self._items: dict[str, EvidenceRef] = {}
        for item in evidence:
            self.add_trusted(item)

    def add_trusted(self, item: EvidenceRef) -> None:
        expected = tier_for_source(item.source_kind)
        if item.tier != expected:
            raise EvidenceValidationError(
                f"source {item.source_kind!r} is tier {expected}, not supplied tier {item.tier}"
            )
        if not item.evidence_id.strip():
            raise EvidenceValidationError("trusted evidence id is required")
        existing = self._items.get(item.evidence_id)
        if existing is not None and existing != item:
            raise EvidenceValidationError(
                f"evidence id {item.evidence_id!r} already has different provenance"
            )
        self._items[item.evidence_id] = item

    def offered(self, requested_ids: tuple[str, ...] = ()) -> tuple[EvidenceRef, ...]:
        if not requested_ids:
            return tuple(sorted(self._items.values(), key=lambda item: item.evidence_id))
        if len(set(requested_ids)) != len(requested_ids):
            raise EvidenceValidationError("requested evidence ids must be unique")
        return self.resolve(requested_ids)

    def resolve(self, evidence_ids: Iterable[str]) -> tuple[EvidenceRef, ...]:
        resolved: list[EvidenceRef] = []
        for evidence_id in evidence_ids:
            try:
                resolved.append(self._items[evidence_id])
            except KeyError as error:
                raise EvidenceValidationError(f"unknown evidence id {evidence_id!r}") from error
        return tuple(resolved)
