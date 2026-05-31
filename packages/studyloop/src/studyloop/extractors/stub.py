"""Stub extractor — deterministic, fixture-backed, zero LLM cost.

Implements the ``extract_struggles(messages, session_id) -> list[ExtractorResult]``
contract by returning hardcoded results loaded from
``tests/fixtures/stub_responses.yaml``.  This lets every pipeline-plumbing test
exercise the full export -> pre-filter -> extract -> upsert path without any
network call or API spend.

The stub deliberately ignores message *content* — it keys only on session_id —
because plumbing tests assert that record_progress is called with a valid
schema, not that any real inference happened.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from studyloop.extractors import ExtractorResult

if TYPE_CHECKING:
    from collections.abc import Sequence

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "stub_responses.yaml"
)


@lru_cache(maxsize=1)
def _load_fixture() -> dict[str, list[dict[str, Any]]]:
    """Load and cache the YAML fixture.  Cached so repeated calls are free."""
    with open(_FIXTURE_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"stub_responses.yaml must be a mapping, got {type(data).__name__}")
    return data


def extract_struggles(
    messages: Sequence[dict[str, Any]],  # noqa: ARG001 — stub ignores content by design
    session_id: str,
) -> list[ExtractorResult]:
    """Return the fixture results for ``session_id`` (or the ``default`` list).

    Each returned result is validated, so a malformed fixture fails loudly at
    the boundary rather than writing junk into study_progress.
    """
    fixture = _load_fixture()
    raw = fixture.get(session_id, fixture.get("default", []))
    return [
        ExtractorResult(
            topic=entry["topic"],
            concept=entry["concept"],
            confidence=entry["confidence"],
            notes=entry.get("notes"),
        ).validate()
        for entry in raw
    ]


__all__ = ["extract_struggles"]
