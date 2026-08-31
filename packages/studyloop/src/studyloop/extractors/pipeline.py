"""Pipeline glue: pre-filter, then extract-and-write.

Deterministic Python — no LLM here. The extractor function is injected so tests
can use an isolated double while production supplies the live extractor.

Pre-filter contract:
- Only process sessions exported by the five release harnesses. The CLI requires
  an explicit session id or harness selection, so supporting Claude/Codex does
  not imply scanning arbitrary coding history.
- Skip a session when more than ``TOOL_USE_THRESHOLD`` of its messages are
  tool_use / tool_result roles (subagent tool-noise, not study Q&A).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from studyloop.harnesses import SESSION_SOURCE_BY_HARNESS

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from studyloop.extractors import ExtractorResult

# Roles that signal machine tool-noise rather than study conversation.
_TOOL_ROLES = frozenset({"tool_use", "tool_result"})

# Sessions with a higher fraction of tool-noise than this are skipped.
TOOL_USE_THRESHOLD = 0.50

# Exporter source names admitted by the release harness contract.
STUDY_SOURCES = frozenset(SESSION_SOURCE_BY_HARNESS.values())


def pre_filter(
    session_id: str,
    source: str | None,
    messages: Sequence[dict[str, Any]],
) -> bool:
    """Return True if this session should be processed by the extractor.

    A session qualifies when its source belongs to a release harness and it is
    not dominated by tool-noise. Empty sessions are rejected.
    """
    if source not in STUDY_SOURCES:
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
    connection: Any | None = None,
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
    from studyloop.history.progress import _record_progress_on_connection

    results = extractor_fn(messages, session_id)
    for result in results:
        result.validate()  # defensive: never write an invalid row
    if dry_run:
        return len(results)

    owns_connection = connection is None
    conn = connection
    if conn is None:
        from studyloop.history import _connection

        conn = _connection._connect()
    if conn is None:
        raise RuntimeError("Could not open sessions database for progress write")

    try:
        for result in results:
            _record_progress_on_connection(
                conn,
                topic=result.topic,
                concept=result.concept,
                confidence=result.confidence,
                notes=result.notes,
                source_session_id=session_id,
                created_by="extractor",
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()
    return len(results)


__all__ = ["STUDY_SOURCES", "TOOL_USE_THRESHOLD", "extract_and_write", "pre_filter"]
