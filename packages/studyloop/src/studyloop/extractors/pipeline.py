"""Pipeline glue: pre-filter, then extract-and-write.

Deterministic Python — no LLM here.  The extractor function is injected so the
same pipeline runs against either the stub (tests) or the real LLM extractor
(production).

Pre-filter contract (from the handoff red-team):
- Only process sessions whose ``source == 'kiro_cli'`` (study harness).  Build
  sessions (claude_code subagents) are skipped — they generate false-positive
  "struggles" from debugging episodes.
- Skip a session when more than ``TOOL_USE_THRESHOLD`` of its messages are
  tool_use / tool_result roles (subagent tool-noise, not study Q&A).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from studyloop.history import record_progress

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from studyloop.extractors import ExtractorResult

logger = logging.getLogger(__name__)

# Roles that signal machine tool-noise rather than study conversation.
_TOOL_ROLES = frozenset({"tool_use", "tool_result"})

# Sessions with a higher fraction of tool-noise than this are skipped.
TOOL_USE_THRESHOLD = 0.50

# The only source we treat as study material by default.
STUDY_SOURCE = "kiro_cli"


def pre_filter(
    session_id: str,  # noqa: ARG001 — kept for caller symmetry / future logging
    source: str | None,
    messages: Sequence[dict[str, Any]],
) -> bool:
    """Return True if this session should be processed by the extractor.

    A session qualifies when its source is the study harness AND it is not
    dominated by tool-noise.  Empty sessions are rejected (nothing to extract).
    """
    if source != STUDY_SOURCE:
        return False
    if not messages:
        return False
    tool_count = sum(1 for m in messages if m.get("role") in _TOOL_ROLES)
    tool_fraction = tool_count / len(messages)
    return tool_fraction < TOOL_USE_THRESHOLD


def extract_and_write(
    session_id: str,
    messages: Sequence[dict[str, Any]],
    extractor_fn: Callable[[Sequence[dict[str, Any]], str], list[ExtractorResult]],
    *,
    dry_run: bool = False,
) -> int:
    """Run ``extractor_fn`` on a session and upsert each result.

    Returns the number of rows written (or that *would* be written when
    ``dry_run`` is True).  Idempotent on re-run: record_progress() keys on a
    uuid5 of (topic, concept), so re-processing the same session updates rather
    than duplicates.

    The DB-write path resolves its connection through
    ``studyloop.history._connection._connect`` — tests monkeypatch that to a
    tmp DB, so this function never touches the user's live sessions.db under
    test.
    """
    results = extractor_fn(messages, session_id)
    written = 0
    for result in results:
        result.validate()  # defensive: never write an invalid row
        if dry_run:
            written += 1
            continue
        if record_progress(
            topic=result.topic,
            concept=result.concept,
            confidence=result.confidence,
            notes=result.notes,
        ):
            written += 1
        else:
            logger.warning(
                "record_progress returned False for %s/%s in session %s",
                result.topic,
                result.concept,
                session_id,
            )
    return written


__all__ = ["pre_filter", "extract_and_write", "TOOL_USE_THRESHOLD", "STUDY_SOURCE"]
