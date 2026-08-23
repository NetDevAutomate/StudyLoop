"""Versioned SHA-256 digests for file-first study plans.

Document digests cover canonical Markdown bytes while blanking the document's
own digest field. Structure digests cover an explicit canonical-JSON
projection; generated Markdown (including Mermaid) and wall-clock timestamps
therefore cannot change structural identity.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from hashlib import sha256
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import StudyPlan

DIGEST_ALGORITHM = "sha256"
DIGEST_VERSION = 1
DIGEST_PREFIX = f"{DIGEST_ALGORITHM}:v{DIGEST_VERSION}:"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---(?P<tail>\s*\n?)", re.DOTALL)
_DOCUMENT_DIGEST_RE = re.compile(r"^document_digest\s*:.*$", re.MULTILINE)


def _versioned_sha256(payload: bytes) -> str:
    return f"{DIGEST_PREFIX}{sha256(payload).hexdigest()}"


def canonical_document_bytes(document: str | bytes) -> bytes:
    """Return document bytes with the frontmatter digest value excluded.

    Only the frontmatter field is normalised. A learner-authored line with the
    same words in the Markdown body remains covered by the digest.
    """
    text = document.decode("utf-8") if isinstance(document, bytes) else document
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return text.encode("utf-8")
    frontmatter = _DOCUMENT_DIGEST_RE.sub("document_digest: ", match.group("body"))
    canonical = f"---\n{frontmatter}\n---{match.group('tail')}{text[match.end() :]}"
    return canonical.encode("utf-8")


def compute_document_digest(document: str | bytes) -> str:
    """Return the versioned SHA-256 digest of canonical document bytes."""
    return _versioned_sha256(canonical_document_bytes(document))


def structure_projection(plan: StudyPlan) -> dict[str, Any]:
    """Return the versioned structural projection used for confirmation.

    Lists retain their meaningful order. Object keys are sorted when encoded.
    Timestamps, revisions, digests, checkpoints, decisions, learning records,
    and generated views are deliberately absent.
    """
    return {
        "projection_version": DIGEST_VERSION,
        "schema_version": plan.schema_version,
        "plan_id": plan.plan_id,
        "title": plan.title,
        "status": plan.status,
        "topics": list(plan.topics),
        "energy_floor": plan.energy_floor,
        "target_date": plan.target_date,
        "review_cadence_days": plan.review_cadence_days,
        "mission": asdict(plan.mission),
        "next_action": plan.next_action,
        "goals": [asdict(item) for item in plan.goals],
        "milestones": [asdict(item) for item in plan.milestones],
        "concepts": [asdict(item) for item in plan.concepts],
        "concept_relations": [asdict(item) for item in plan.concept_relations],
        "unknowns": [asdict(item) for item in plan.unknowns],
        "resources": [asdict(item) for item in plan.resources],
    }


def canonical_structure_bytes(plan: StudyPlan) -> bytes:
    """Encode :func:`structure_projection` as deterministic UTF-8 JSON."""
    return json.dumps(
        structure_projection(plan),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def compute_structure_digest(plan: StudyPlan) -> str:
    """Return the versioned SHA-256 digest of the plan's structure."""
    return _versioned_sha256(canonical_structure_bytes(plan))


def is_versioned_digest(value: str) -> bool:
    """Return whether ``value`` is a well-formed digest this code understands."""
    if not value.startswith(DIGEST_PREFIX):
        return False
    payload = value.removeprefix(DIGEST_PREFIX)
    return len(payload) == 64 and all(character in "0123456789abcdef" for character in payload)
