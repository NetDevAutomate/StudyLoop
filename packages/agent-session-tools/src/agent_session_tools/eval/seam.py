"""The retriever seam: one contract every arm implements and both rulers consume.

An *arm* is anything that answers a natural-language query with ranked
sessions: the real MCP tool through FastMCP ``call_tool`` (the agent's
interface, and the arm that gates acceptance), the ``session-query`` CLI as
a subprocess, a frozen replica of today's shipped SQL, and later the fixed
lexical service, the semantic arm and the hybrid. The rulers never know
which one they are scoring.

Rules of the contract:

* ``search`` returns **distinct sessions in rank order**, at most ``k``. When
  an engine ranks messages, collapse them to sessions keeping first-seen
  order and carry the contributing message ids (fusion and the census need
  them).
* Failures are raised as :class:`ArmError` carrying a stable ``kind`` so a
  ruler can count crashes by class instead of swallowing them. A crash is a
  miss, never a skip.
* ``Query.exclude_message_ids`` / ``exclude_session_ids`` are honoured by the
  arm when it can (self-exclusion for the census); an arm that cannot filter
  at query time reports ``supports_exclusion = False`` and the ruler filters
  the returned hits instead.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Query:
    """One retrieval request as an agent (or a ruler on its behalf) would pose it."""

    text: str
    project: str | None = None
    source: str | None = None
    exclude_message_ids: frozenset[str] = field(default_factory=frozenset)
    exclude_session_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Hit:
    """One ranked session and the evidence that ranked it."""

    session_id: str
    message_ids: tuple[str, ...] = ()
    score: float | None = None
    #: How the session was reached: ``lexical``, ``semantic``, ``hybrid``,
    #: ``mcp``, ``cli`` ... Free text, but stable per arm.
    method: str = ""


class ArmError(Exception):
    """A retrieval failure with a stable classification.

    ``kind`` is one of the FTS5 failure classes the crash census counts
    (``backtick``, ``question-mark``, ``comma``, ``no-such-column``) or
    ``other``; the original exception is chained.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


#: The four failure classes Stage 4 counted, keyed by the FTS5 token they name.
_NAMED_TOKENS = {"`": "backtick", "?": "question-mark", ",": "comma"}
_SYNTAX_NEAR = re.compile(r'syntax error near "((?:[^"\\]|\\.)*)"')


def classify_failure(exc: BaseException) -> str:
    """Map an exception raised by an engine to a crash-census class.

    FTS5 syntax errors are classified by the offending token so a census can
    name every hat the one raw-pass-through defect wears: ``backtick``,
    ``question-mark`` and ``comma`` keep their Stage 4 names, any other token
    becomes ``syntax:<token>`` (``syntax:<``, ``syntax:/``, ``syntax:and`` ...).
    A column-filter misparse is ``no-such-column``; anything else from SQLite
    is ``operational-error``; everything else is ``other``.
    """
    text = str(exc)
    match = _SYNTAX_NEAR.search(text)
    if match:
        token = match.group(1)
        return _NAMED_TOKENS.get(token, f"syntax:{token[:24] or 'empty'}")
    if "no such column" in text:
        return "no-such-column"
    if isinstance(exc, sqlite3.OperationalError) or "OperationalError" in text:
        return "operational-error"
    return "other"


def collapse_to_sessions(
    ranked_messages: Iterable[tuple[str, str]], k: int, *, method: str = ""
) -> list[Hit]:
    """Collapse ``(session_id, message_id)`` pairs in rank order to ``k`` sessions.

    First-seen order is the session's rank; every contributing message id is
    kept so a later fusion or the census can see what ranked the session.
    """
    order: list[str] = []
    members: dict[str, list[str]] = {}
    for session_id, message_id in ranked_messages:
        if session_id not in members:
            if len(order) == k:
                continue
            order.append(session_id)
            members[session_id] = []
        members[session_id].append(message_id)
    return [Hit(sid, tuple(members[sid]), None, method) for sid in order]


@runtime_checkable
class Retriever(Protocol):
    """What every arm provides."""

    #: Stable arm name used as the receipt key (``mcp``, ``cli``, ``frozen`` ...).
    name: str
    #: Whether ``Query.exclude_*`` is applied inside the engine.
    supports_exclusion: bool

    def search(self, query: Query, k: int) -> list[Hit]: ...

    def describe(self) -> dict[str, object]:
        """Configuration worth recording in a receipt (limits, paths, commits)."""
        ...


def apply_exclusions(hits: list[Hit], query: Query, k: int) -> list[Hit]:
    """Ruler-side exclusion for arms that cannot filter at query time.

    Drops excluded sessions and excluded message ids; a hit whose every
    message was excluded disappears, and so does a hit that carries no
    message ids when messages are being excluded (unknown provenance is
    treated as excluded -- fail closed). Truncates to ``k``.
    """
    out: list[Hit] = []
    for hit in hits:
        if hit.session_id in query.exclude_session_ids:
            continue
        if query.exclude_message_ids and not hit.message_ids:
            # Provenance unknown: the ruler cannot tell whether an excluded
            # message produced this hit, so it is dropped (fail closed).
            continue
        kept = tuple(m for m in hit.message_ids if m not in query.exclude_message_ids)
        if hit.message_ids and not kept:
            continue
        out.append(Hit(hit.session_id, kept, hit.score, hit.method))
        if len(out) == k:
            break
    return out


__all__ = [
    "ArmError",
    "Hit",
    "Query",
    "Retriever",
    "apply_exclusions",
    "classify_failure",
    "collapse_to_sessions",
]
