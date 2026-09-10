"""Pipeline glue: pre-filter, then extract-and-write.

Deterministic Python — no LLM here. The extractor function is injected so tests
can use an isolated double while production supplies the live extractor.

Pre-filter contract:
- Only process sessions exported by the six release harnesses. The CLI requires
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
    """Run ``extractor_fn`` on a session and bind each result to its exact input.

    Returns the number of rows written (or that *would* be written when
    ``dry_run`` is True). Identical input and results deduplicate on the current
    schema. Changed inputs remain separate reports. The legacy schema retains
    its older aggregate behavior for explicitly unclassified inspection only.

    The DB-write path resolves its connection through
    ``studyloop.history._connection._connect`` — tests monkeypatch that to a
    tmp DB, so this function never touches the user's live sessions.db under
    test.
    """
    from studyloop.history.progress import _record_progress_on_connection

    def validated_results():
        results = extractor_fn(messages, session_id)
        for result in results:
            result.validate()  # validate the entire batch before its first write
        return results

    if dry_run:
        return len(validated_results())

    owns_connection = connection is None
    conn = connection
    if conn is None:
        from studyloop.history import _connection

        conn = _connection._connect()
    if conn is None:
        raise RuntimeError("Could not open sessions database for progress write")
    if conn.in_transaction:
        if owns_connection:
            conn.close()
        raise ValueError("End the caller transaction before invoking an external extractor")

    try:
        from agent_session_tools.context.legacy import legacy_global_visible
        from agent_session_tools.context.legacy_sources import (
            persist_session_input,
            prepare_session_input,
        )
        from agent_session_tools.context.scope import ScopeError, active_policy
        from studyloop.history import observations

        evidence_ids = None
        policy = active_policy()
        requested_scope = policy.request_scope()
        captured = None
        if observations.available(conn):
            captured = prepare_session_input(conn, session_id)
            if captured.messages != list(messages):
                raise ValueError("Extractor input does not match the captured source snapshot")
        elif not legacy_global_visible(conn):
            raise ScopeError(
                "Progress writes require source-owned learning records for classified context. "
                "Use --dry-run for scoped inspection while ownership integration is pending."
            )
        # Release the read snapshot before network I/O. Recheck under the writer
        # transaction afterwards so a concurrent scope change cannot admit data.
        conn.rollback()
        results = validated_results()
        conn.execute("BEGIN IMMEDIATE")
        current_policy = active_policy()
        if (current_policy.digest, current_policy.request_scope()) != (
            policy.digest,
            requested_scope,
        ):
            raise ScopeError("Context policy changed during extraction; retry in the current scope")
        if captured is not None:
            evidence_ids = persist_session_input(conn, captured)
        elif observations.available(conn) or not legacy_global_visible(conn):
            raise ScopeError("Context ownership changed during extraction; retry")
        for result in results:
            _record_progress_on_connection(
                conn,
                topic=result.topic,
                concept=result.concept,
                confidence=result.confidence,
                notes=result.notes,
                source_session_id=session_id,
                created_by="extractor",
                evidence_ids=evidence_ids,
                input_snapshot=captured,
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
