"""The archive adapter: the only path for StudyLoop's 5,879 rotated-away sessions.

ADR-0011 v1.1, "Adapter contract". The legacy store (``sessions.db``) is the sole
surviving copy of 5,261 of those sessions, so this adapter never writes to it: it
opens the file with ``mode=ro`` and every statement it issues is a SELECT.

The classifier is **pure and versioned**. A change to any rule is a new
``classifier_version``, which produces new event rows (the event hash is
position- and kind-bearing) and leaves existing citations bound to the fragments
they were written against — council finding 8.

Measured shape of the corpus this was written against (all counts verified against
the live file, read-only, on 2026-09-10):

* 143,903 messages over 5,879 sessions; roles ``assistant`` 125,063, ``user``
  18,540, ``toolResult`` 127, ``info`` 89, ``error`` 61, ``system`` 23.
* 75,497 assistant rows carry a ``[tool:NAME]`` marker. **75,493 are bare** — no
  arguments, no output. The 4 exceptions are a second marker on the following
  line, not a payload. The archive therefore records *that* a tool ran and its
  name, never its arguments, so a derivation rule needing arguments cannot be
  computed from history.
* 5,438 user rows are harness XML (``<observed_from_primary_session>`` 3,376,
  ``<file_tree>`` 415, ``<codex_internal_context>`` 263, ``<system-reminder>``
  237, ...). Every one parsed as a real tag; none was prose that merely began
  with ``<``.
* 728 assistant rows are XML-tagged. 163 of those are tool invocations in XML
  (``<execute_command>``, ``<read_file>``, ...) — see :data:`TOOL_XML_TAGS`.
* ``messages.seq`` is unusable for ordering: 678 NULL, 924 duplicate
  ``(session_id, seq)`` pairs, 5,615 sessions not starting at 0. Ordering is by
  ``messages.id`` (insertion order), which is the transcript order.
* ``sessions.content_hash`` is NULL for all 5,879 rows, so ``source_sha256`` is
  computed here instead (see :meth:`ArchiveAdapter.discover`).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import TYPE_CHECKING, Final, NamedTuple

from learning_memory.model import (
    Event,
    EventKind,
    ParsedSession,
    Session,
    SourceRef,
    collapse_adjacent_duplicates,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "ARCHIVE_ADAPTER_VERSION",
    "ARCHIVE_CLASSIFIER_VERSION",
    "TOOL_XML_TAGS",
    "USER_PROSE_XML_TAGS",
    "ArchiveAdapter",
    "Classified",
    "classify",
    "open_readonly",
]

ARCHIVE_HARNESS: Final = "archive"
ARCHIVE_ADAPTER_VERSION: Final = "archive-v1"
ARCHIVE_CLASSIFIER_VERSION: Final = "archive-classifier-v1"

_TOOL_MARKER: Final = re.compile(r"^\[tool:([^\]]+)\](.*)$", re.DOTALL)
_LITELLM_REQUEST: Final = re.compile(r"^\[LiteLLM Request:\s*([^\]]*)\]")
_XML_TAG: Final = re.compile(r"^<\s*([A-Za-z_][\w.:-]*)")

TOOL_XML_TAGS: Final[frozenset[str]] = frozenset(
    {
        # Roo/Kilocode-style tool invocations written as XML by the assistant.
        # These are tool CALLS, not prose: ADR-0011's adapter contract requires
        # "no tool text in prose events", so they cannot fall through to
        # assistant_prose however noisy the fallback rule is otherwise.
        "apply_diff",
        "ask_followup_question",
        "attempt_completion",
        "delete_file",
        "execute_command",
        "fetch_instructions",
        "list_files",
        "new_task",
        "read_file",
        "search_files",
        "switch_mode",
        "update_todo_list",
        "use_mcp_tool",
        "write_to_file",
    }
)
"""Assistant XML tags that are tool invocations (163 rows), tag name = tool name."""

_THINKING_XML_TAGS: Final[frozenset[str]] = frozenset({"think", "thinking", "scratchpad"})

USER_PROSE_XML_TAGS: Final[frozenset[str]] = frozenset({"task", "user_query"})
"""User XML tags that WRAP the learner's own words, so the row is a learner turn.

Kilocode writes the learner's request as ``<task>...</task>`` (247 rows) and grok
writes ``<user_query>...</user_query>`` (148). Classifying those as harness
injection threw away real learner voice -- 136 kilocode sessions had nothing else,
so they were refused for having nothing citable. Measured, not assumed: every other
``<``-leading user tag in the corpus is machine output
(``<observed_from_primary_session>`` 3,376, ``<file_tree>`` 415,
``<codex_internal_context>`` 263, ``<system-reminder>`` 237,
``<task-notification>`` 112, ``<environment_context>`` 82, ...).

``<teammate-message>`` (149) is deliberately NOT here: it is an orchestrating
agent's brief to a sub-agent, so counting it as the learner would inflate the
learner-voice corpus the ADR measures. It is a one-line change if that call is
revisited.

The text is stored with its wrapper intact. Unwrapping would make the citation
surface bytes the archive never held.
"""

_PROSE_FALLBACK: Final[EventKind] = "assistant_prose"


class Classified(NamedTuple):
    """The classifier's whole output. A tuple, so it unpacks as the spec's 4-tuple."""

    kind: EventKind
    actor: str
    tool_name: str | None
    text: str


def classify(role: str, content: str | None, source: str) -> Classified:
    """Map one archive message row to a typed event. Pure, total, versioned.

    ``source`` is the session's harness (``sessions.source``); it is the actor of
    last resort, because 13,450 assistant rows and every ``error``/``info`` row
    have no ``model``.

    Total by construction: an unknown role classifies as ``system`` rather than
    raising, so a new legacy role can never silently drop a message. Only
    ``tool_call`` may carry empty text — a bare ``[tool:Bash]`` marker is a real
    event whose payload the archive never stored.
    """
    text = content or ""
    if role == "user":
        return _classify_user(text, source)
    if role == "assistant":
        return _classify_assistant(text, source)
    if role == "toolResult":
        return Classified("tool_result", "tool", None, text)
    if role == "error":
        return Classified("error", source, None, text)
    # system, info, and any role a future exporter invents.
    return Classified("system", source, None, text)


def _classify_user(text: str, source: str) -> Classified:
    litellm = _LITELLM_REQUEST.match(text)
    if litellm:
        # A proxy request envelope, not the learner speaking.
        return Classified("system", "litellm", litellm.group(1).strip() or None, text)
    stripped = text.lstrip()
    tag = _XML_TAG.match(stripped)
    if tag:
        if tag.group(1) in USER_PROSE_XML_TAGS:
            # The learner's own words, wrapped by the harness.
            return Classified("user", "learner", None, text)
        # Harness injection: reminders, file trees, observed-from-primary blocks.
        return Classified("system", source, None, text)
    if stripped.startswith("{"):
        # Structured envelopes (12 are Python reprs of {'text': ...} that wrap real
        # learner prose; unwrapping them is Stage D's, not a capture-time guess).
        return Classified("system", source, None, text)
    return Classified("user", "learner", None, text)


def _classify_assistant(text: str, source: str) -> Classified:
    marker = _TOOL_MARKER.match(text)
    if marker:
        # 75,493 of 75,497 are bare: the name is all the archive kept.
        return Classified("tool_call", source, marker.group(1).strip(), marker.group(2))
    if text.startswith("[LiteLLM"):
        return Classified("system", "litellm", None, text)
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return Classified("tool_result", source, None, text)
    tag = _XML_TAG.match(stripped)
    if tag:
        name = tag.group(1)
        if name in TOOL_XML_TAGS:
            return Classified("tool_call", source, name, text)
        if name in _THINKING_XML_TAGS:
            return Classified("thinking", source, None, text)
    return Classified(_PROSE_FALLBACK, source, None, text)


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Open the legacy store read-only. The ONLY way this module opens that file.

    ``mode=ro`` is enforced by SQLite itself, so a stray INSERT raises
    ``OperationalError: attempt to write a readonly database`` rather than
    corrupting the only surviving copy of 5,261 sessions.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


class ArchiveAdapter:
    """Reads `sessions.db` and emits typed sessions under a named classifier version."""

    harness: str = ARCHIVE_HARNESS
    adapter_version: str = ARCHIVE_ADAPTER_VERSION
    classifier_version: str = ARCHIVE_CLASSIFIER_VERSION

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, path: str | Path) -> ArchiveAdapter:
        return cls(open_readonly(path))

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ discover

    def discover(self) -> Iterator[SourceRef]:
        """One ref per ``sessions`` row, ordered by ``(created_at, id)``.

        ``source_sha256`` is a digest over the session's message rows, NOT
        ``sessions.content_hash``: that column is NULL for all 5,879 rows, so using
        it as specified would leave every receipt unable to name its own input.
        The digest is over ``(id, content)`` per message in id order — the same
        shape the ruler's ``corpus_digest`` uses.
        """
        digests = self._message_digests()
        for row in self._conn.execute(
            "SELECT id, created_at FROM sessions ORDER BY created_at, id"
        ).fetchall():
            session_id = str(row["id"])
            yield SourceRef(
                harness=ARCHIVE_HARNESS,
                locator=session_id,
                source_sha256=digests.get(session_id),
            )

    def _message_digests(self) -> dict[str, str]:
        """One pass over 143,903 rows, giving every session a content identity."""
        digests: dict[str, str] = {}
        current: str | None = None
        hasher = hashlib.sha256()
        for row in self._conn.execute(
            "SELECT session_id, id, content FROM messages ORDER BY session_id, id"
        ):
            session_id = str(row["session_id"])
            if session_id != current:
                if current is not None:
                    digests[current] = hasher.hexdigest()
                current = session_id
                hasher = hashlib.sha256()
            hasher.update(str(row["id"]).encode())
            hasher.update((row["content"] or "").encode("utf-8", "replace"))
        if current is not None:
            digests[current] = hasher.hexdigest()
        return digests

    def session_ids(self) -> list[str]:
        """Ingest order: parents before children, then ``(created_at, id)``.

        Lineage edges do not need this — a child parks its edge in
        ``lineage_pending`` and the parent reconciles it — but ``sessions.parent_id``
        is only filled when the parent is already present, so ordering costs nothing
        and makes that column true. Verified acyclic: no parent is itself a child.
        """
        parents = self.lineage_map()
        ordered = [
            str(row["id"])
            for row in self._conn.execute("SELECT id FROM sessions ORDER BY created_at, id")
        ]
        known = set(ordered)
        seen: set[str] = set()
        result: list[str] = []

        def emit(session_id: str, depth: int = 0) -> None:
            if session_id in seen or session_id not in known or depth > 8:
                return
            parent = parents.get(session_id)
            if parent is not None and parent not in seen:
                emit(parent, depth + 1)
            if session_id not in seen:
                seen.add(session_id)
                result.append(session_id)

        for session_id in ordered:
            emit(session_id)
        return result

    def lineage_map(self) -> dict[str, str]:
        """``child -> parent`` from ``metadata.$.source_session_id``.

        The only recoverable lineage in the archive, and only for ``agent-*`` ids:
        485 of the 3,477 ``agent-*`` sessions name a parent and all 485 parents
        exist. The other 126 rows carrying the key point at THEMSELVES (a session
        recording its own id) and are skipped. No time-window inference: a guessed
        edge is indistinguishable from a real one once stored.
        """
        edges: dict[str, str] = {}
        for row in self._conn.execute(
            """
            SELECT id, json_extract(metadata, '$.source_session_id') AS parent
            FROM sessions
            WHERE parent IS NOT NULL AND id LIKE 'agent-%'
            ORDER BY id
            """
        ):
            child = str(row["id"])
            parent = str(row["parent"])
            if parent and parent != child:
                edges[child] = parent
        return edges

    def unrecoverable_lineage(self) -> list[str]:
        """``agent-*`` sessions whose parent the archive did not record (2,992)."""
        return [
            str(row["id"])
            for row in self._conn.execute(
                """
                SELECT id FROM sessions
                WHERE id LIKE 'agent-%'
                  AND (json_extract(metadata, '$.source_session_id') IS NULL
                       OR json_extract(metadata, '$.source_session_id') = id)
                ORDER BY id
                """
            )
        ]

    def self_referencing_lineage(self) -> list[str]:
        """Sessions whose ``source_session_id`` is their own id (126); skipped."""
        return [
            str(row["id"])
            for row in self._conn.execute(
                """
                SELECT id FROM sessions
                WHERE json_extract(metadata, '$.source_session_id') = id
                ORDER BY id
                """
            )
        ]

    def source_counts(self) -> dict[str, int]:
        return {
            str(row["source"]): int(row["n"])
            for row in self._conn.execute(
                "SELECT source, count(*) AS n FROM sessions GROUP BY source ORDER BY n DESC, source"
            )
        }

    # --------------------------------------------------------------------- parse

    def parse(self, ref: SourceRef) -> ParsedSession:
        """Turn one archive session into typed events.

        ``Session.id`` is the archive id unchanged (ADR §6), so every existing gold
        question, receipt and pin scores this store without translation.
        ``native_source`` is always ``None``: the harnesses rotated the originals
        away, which is the whole reason this adapter exists.
        """
        row = self._conn.execute(
            """
            SELECT id, source, project_path, git_branch, created_at, updated_at, metadata
            FROM sessions WHERE id = ?
            """,
            (ref.locator,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no archive session {ref.locator!r}")
        source = str(row["source"])

        raw: list[Event] = []
        turn = 0
        stamps: list[str] = []
        for index, message in enumerate(
            self._conn.execute(
                # ORDER BY id, not seq: seq has 678 NULLs and 924 duplicate
                # (session_id, seq) pairs, so it cannot order a transcript.
                "SELECT id, role, content, model, timestamp FROM messages"
                " WHERE session_id = ? ORDER BY id",
                (ref.locator,),
            )
        ):
            kind, actor, tool_name, text = classify(
                str(message["role"]), message["content"], source
            )
            if kind == "user":
                turn += 1
            model = message["model"]
            stamp = message["timestamp"]
            if stamp:
                stamps.append(str(stamp))
            raw.append(
                Event(
                    turn_id=turn,
                    seq=index,
                    kind=kind,
                    text=text,
                    # The model is the truest actor for a machine turn; `actor` from
                    # the classifier is the fallback where the archive has none.
                    actor=str(model) if model else actor,
                    tool_name=tool_name,
                    ts=str(stamp) if stamp else None,
                )
            )

        events, collapsed = collapse_adjacent_duplicates(raw)
        parent = self.lineage_map().get(str(row["id"]))
        return ParsedSession(
            session=Session(
                id=str(row["id"]),
                harness=source,
                project=row["project_path"],
                branch=row["git_branch"],
                parent_id=parent,
                started_at=str(row["created_at"]) if row["created_at"] else _first(stamps),
                ended_at=str(row["updated_at"]) if row["updated_at"] else _last(stamps),
                # scope/intent/outcome are Stage D's to derive; the archive has none.
            ),
            events=events,
            native_source=None,
            lineage=[parent] if parent else [],
            adapter_version=ARCHIVE_ADAPTER_VERSION,
            classifier_version=ARCHIVE_CLASSIFIER_VERSION,
            exporter_dupes_collapsed=collapsed,
        )

    def parse_id(self, session_id: str) -> ParsedSession:
        """``parse`` addressed by session id, for the ingest CLI's ordered pass."""
        return self.parse(SourceRef(harness=ARCHIVE_HARNESS, locator=session_id))

    def session_metadata(self, session_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT metadata FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None or not row["metadata"]:
            return {}
        try:
            parsed = json.loads(str(row["metadata"]))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def _first(stamps: list[str]) -> str | None:
    return min(stamps) if stamps else None


def _last(stamps: list[str]) -> str | None:
    return max(stamps) if stamps else None
