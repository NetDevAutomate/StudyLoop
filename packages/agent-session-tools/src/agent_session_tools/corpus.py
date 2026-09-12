"""Corpus hygiene: one definition of what a message row *is*.

Four readers used to decide independently what counted as noise — the
extractor pre-filter keyed on ``role`` (dead against this corpus, which stores
tool echoes as ``assistant`` content), the embedding ingest keyed on length,
``struggle_topics`` keyed on ``LIKE '%?%'``, and ad-hoc census scripts used
their own regexes. Measured 2026-09-12 on the live database: 52.5% of all rows
were literal ``[tool:Bash]``-style echoes, 2,059 were LiteLLM warm-up probes,
1,786 were injected AGENTS.md / system-reminder blocks, and only ~3.7% were a
human asking something. Every reader should agree on that, so the decision
lives here once.

Two forms are exported and a test pins them to identical verdicts:

``message_kind(role, content)``
    Pure Python, for ingest-time filtering and in-process consumers.

``MESSAGE_KIND_SQL``
    A ``CASE`` expression over columns ``role`` and ``content`` that yields the
    same label, for readers that must classify inside a query (the corpus
    audit, the filtered rebuild, the derived-struggle scan). It costs nothing
    at read time and needs no new column, so it works on the schema as-is.

The vocabulary is deliberately small and mechanical. Nothing here is a
judgement about *quality*; it is a judgement about *authorship* — did a person
type this, did a model write prose, or did a harness emit bookkeeping.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Final

# ── Vocabulary ────────────────────────────────────────────────────────────────

KIND_HUMAN: Final = "human"  # a person typed it (role=user, not machine text)
KIND_PROSE: Final = "prose"  # a model wrote readable prose (role=assistant)
KIND_TOOL_ECHO: Final = "tool_echo"  # ``[tool:Name]`` marker and nothing else
KIND_STUB: Final = "stub"  # assistant narration under STUB_MAX_CHARS
KIND_INJECTED: Final = "injected"  # AGENTS.md / system-reminder / agent brief
KIND_PROXY_PROBE: Final = "proxy_probe"  # LiteLLM warm-up / health probe
KIND_ACK: Final = "ack"  # user turn under ACK_MAX_CHARS ("ok", "thanks")
KIND_BRIEF: Final = "brief"  # user turn at/over BRIEF_MIN_CHARS (pasted task)
KIND_EMPTY: Final = "empty"
KIND_OTHER: Final = "other"  # tool_use / tool_result / info / error / system

ALL_KINDS: Final[frozenset[str]] = frozenset(
    {
        KIND_HUMAN,
        KIND_PROSE,
        KIND_TOOL_ECHO,
        KIND_STUB,
        KIND_INJECTED,
        KIND_PROXY_PROBE,
        KIND_ACK,
        KIND_BRIEF,
        KIND_EMPTY,
        KIND_OTHER,
    }
)

#: The kinds a learner-facing reader (struggle derivation, study retrieval,
#: the filtered rebuild) keeps. Everything else is harness bookkeeping.
LEARNER_KINDS: Final[frozenset[str]] = frozenset({KIND_HUMAN, KIND_PROSE})

# ── Thresholds (shared by both forms) ─────────────────────────────────────────

STUB_MAX_CHARS: Final = 40
ACK_MAX_CHARS: Final = 20
BRIEF_MIN_CHARS: Final = 2000

# ── Machine-text markers (shared by both forms) ───────────────────────────────
# Kept as plain prefixes/substrings so the SQL form can express them with
# LIKE and substr(); no regex-only construct may appear here.

INJECTED_PREFIXES: Final[tuple[str, ...]] = (
    "You are ",
    "This session is being continued",
    "# AGENTS.md",
    "<system-reminder>",
    "<observed_from_primary_session>",
    "<command-name>",
    "<file_tree>",
    "<teammate-message",
    "--- MODE SWITCH",
)
INJECTED_SUBSTRINGS: Final[tuple[str, ...]] = ("<INSTRUCTIONS>",)
#: A user turn whose first character is one of these is a harness envelope,
#: not a person: ``[LiteLLM Request: …]``, ``@file`` mentions, ``<tag>`` blocks.
INJECTED_FIRST_CHARS: Final[tuple[str, ...]] = ("[", "@", "<")

PROXY_PROBE_PREFIXES: Final[tuple[str, ...]] = (
    "[LiteLLM Request:",
    "What is 2+2",
    "Warmup",
)

_TOOL_ECHO_RE: Final = re.compile(r"\[tool:[^\]\n]*\][^\n]*\Z")


def message_kind(role: str | None, content: str | None) -> str:
    """Classify one message row. Total: every input yields a kind in ALL_KINDS."""
    text = (content or "").strip()
    if not text:
        return KIND_EMPTY
    if role == "assistant":
        if _TOOL_ECHO_RE.fullmatch(text):
            return KIND_TOOL_ECHO
        if len(text) < STUB_MAX_CHARS:
            return KIND_STUB
        return KIND_PROSE
    if role == "user":
        if text.startswith(PROXY_PROBE_PREFIXES):
            return KIND_PROXY_PROBE
        if text.startswith(INJECTED_PREFIXES) or any(
            s in text for s in INJECTED_SUBSTRINGS
        ):
            return KIND_INJECTED
        if text[0] in INJECTED_FIRST_CHARS:
            return KIND_INJECTED
        if len(text) < ACK_MAX_CHARS:
            return KIND_ACK
        if len(text) >= BRIEF_MIN_CHARS:
            return KIND_BRIEF
        return KIND_HUMAN
    return KIND_OTHER


# ── SQL form ──────────────────────────────────────────────────────────────────


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _like_prefix(col: str, prefix: str) -> str:
    # Escape LIKE metacharacters so a literal '_' or '%' in a marker cannot widen
    # the match; '\' is the declared escape character.
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{col} LIKE {_sql_str(escaped + '%')} ESCAPE '\\'"


def _like_contains(col: str, needle: str) -> str:
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{col} LIKE {_sql_str('%' + escaped + '%')} ESCAPE '\\'"


def _any(clauses: tuple[str, ...]) -> str:
    return "(" + " OR ".join(clauses) + ")"


def build_message_kind_sql(role_col: str = "role", content_col: str = "content") -> str:
    """Return a CASE expression equivalent to :func:`message_kind`.

    ``role_col`` / ``content_col`` may be qualified (``m.role``). The expression
    is safe to embed in SELECT, WHERE and GROUP BY.
    """
    # Python's str.strip() removes all whitespace; SQLite's one-arg trim()
    # removes spaces only. Pass the same whitespace set so a trailing newline
    # cannot make the two forms disagree about a tool echo.
    t = f"trim({content_col}, ' ' || char(9) || char(10) || char(13))"
    # SQLite has no regex; the tool-echo shape "[tool:…]…" with no newline is
    # expressed as: starts with '[tool:', contains ']', and contains no '\n'.
    tool_echo = (
        f"({_like_prefix(t, '[tool:')} AND instr({t}, ']') > 0 "
        f"AND instr({t}, char(10)) = 0)"
    )
    probe = _any(tuple(_like_prefix(t, p) for p in PROXY_PROBE_PREFIXES))
    injected = _any(
        tuple(_like_prefix(t, p) for p in INJECTED_PREFIXES)
        + tuple(_like_contains(t, s) for s in INJECTED_SUBSTRINGS)
        + (
            f"substr({t}, 1, 1) IN ({', '.join(_sql_str(c) for c in INJECTED_FIRST_CHARS)})",
        )
    )
    return f"""CASE
  WHEN {content_col} IS NULL OR {t} = '' THEN {_sql_str(KIND_EMPTY)}
  WHEN {role_col} = 'assistant' THEN CASE
    WHEN {tool_echo} THEN {_sql_str(KIND_TOOL_ECHO)}
    WHEN length({t}) < {STUB_MAX_CHARS} THEN {_sql_str(KIND_STUB)}
    ELSE {_sql_str(KIND_PROSE)} END
  WHEN {role_col} = 'user' THEN CASE
    WHEN {probe} THEN {_sql_str(KIND_PROXY_PROBE)}
    WHEN {injected} THEN {_sql_str(KIND_INJECTED)}
    WHEN length({t}) < {ACK_MAX_CHARS} THEN {_sql_str(KIND_ACK)}
    WHEN length({t}) >= {BRIEF_MIN_CHARS} THEN {_sql_str(KIND_BRIEF)}
    ELSE {_sql_str(KIND_HUMAN)} END
  ELSE {_sql_str(KIND_OTHER)}
END"""


#: Unqualified form for queries over ``messages`` directly.
MESSAGE_KIND_SQL: Final = build_message_kind_sql()


def learner_kinds_sql(kind_expr: str = MESSAGE_KIND_SQL) -> str:
    """WHERE fragment: keep only learner-facing rows."""
    return f"({kind_expr}) IN ({', '.join(_sql_str(k) for k in sorted(LEARNER_KINDS))})"


# ── Read-only audit (the manifest a filtered rebuild is judged against) ───────


@dataclass(frozen=True, slots=True)
class SourceAudit:
    """Per-``sessions.source`` composition."""

    source: str
    sessions: int
    messages: int
    by_kind: dict[str, int]
    sessions_kept: int  # sessions with >= 1 learner-kind message

    @property
    def learner_messages(self) -> int:
        return sum(self.by_kind.get(k, 0) for k in LEARNER_KINDS)


@dataclass(frozen=True, slots=True)
class CorpusAudit:
    """What the corpus is made of, and what a learner-only filter would keep.

    Everything here is derived from ``MESSAGE_KIND_SQL`` inside one read-only
    query per table, so the numbers are exactly the ones the filtered rebuild
    will act on — not an approximation of them.
    """

    messages: int
    sessions: int
    by_kind: dict[str, int]
    per_source: tuple[SourceAudit, ...]
    learning_tier: dict[str, int]

    @property
    def learner_messages(self) -> int:
        return sum(self.by_kind.get(k, 0) for k in LEARNER_KINDS)

    @property
    def sessions_kept(self) -> int:
        return sum(s.sessions_kept for s in self.per_source)

    @property
    def sessions_dropped(self) -> int:
        return self.sessions - self.sessions_kept

    def share(self, kind: str) -> float:
        return self.by_kind.get(kind, 0) / self.messages if self.messages else 0.0


#: Learner-facing tables whose row counts the audit reports. All were zero on
#: the live database on 2026-09-12 except study_plans/study_sessions/parked_topics
#: at one row each — the fact that motivated this module.
LEARNING_TIER_TABLES: Final[tuple[str, ...]] = (
    "study_sessions",
    "study_progress",
    "parked_topics",
    "teach_back_scores",
    "concepts",
    "knowledge_bridges",
    "practice_attempts",
    "card_reviews",
    "study_plans",
)


def audit_corpus(conn: sqlite3.Connection) -> CorpusAudit:
    """Classify every message in ``conn`` and summarise. Reads only."""
    kind_expr = build_message_kind_sql("m.role", "m.content")
    total_by_kind: dict[str, int] = {}
    per_source: list[SourceAudit] = []

    rows = conn.execute(
        f"""
        SELECT s.source, {kind_expr} AS kind, COUNT(*) AS n
        FROM messages m JOIN sessions s ON s.id = m.session_id
        GROUP BY s.source, kind
        """
    ).fetchall()
    kinds_by_source: dict[str, dict[str, int]] = {}
    for source, kind, n in rows:
        kinds_by_source.setdefault(source or "", {})[kind] = n
        total_by_kind[kind] = total_by_kind.get(kind, 0) + n

    session_counts = dict(
        conn.execute("SELECT source, COUNT(*) FROM sessions GROUP BY source").fetchall()
    )
    kept_counts = dict(
        conn.execute(
            f"""
            SELECT s.source, COUNT(DISTINCT s.id)
            FROM sessions s JOIN messages m ON m.session_id = s.id
            WHERE {learner_kinds_sql(kind_expr)}
            GROUP BY s.source
            """
        ).fetchall()
    )
    for source in sorted(
        set(session_counts) | set(kinds_by_source), key=lambda s: s or ""
    ):
        by_kind = kinds_by_source.get(source or "", {})
        per_source.append(
            SourceAudit(
                source=source or "",
                sessions=session_counts.get(source, 0),
                messages=sum(by_kind.values()),
                by_kind=by_kind,
                sessions_kept=kept_counts.get(source, 0),
            )
        )

    tier: dict[str, int] = {}
    for table in LEARNING_TIER_TABLES:
        try:
            tier[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        except sqlite3.OperationalError:
            continue  # table absent on an older schema — report what exists

    return CorpusAudit(
        messages=sum(total_by_kind.values()),
        sessions=sum(session_counts.values()),
        by_kind=total_by_kind,
        per_source=tuple(per_source),
        learning_tier=tier,
    )


def render_audit(audit: CorpusAudit) -> str:
    """Plain-text manifest: totals, per-kind shares, per-source keep/drop, tier."""
    out: list[str] = []
    out.append(f"messages: {audit.messages:,}   sessions: {audit.sessions:,}")
    out.append("")
    out.append("BY KIND")
    for kind, n in sorted(audit.by_kind.items(), key=lambda kv: -kv[1]):
        mark = "keep" if kind in LEARNER_KINDS else "drop"
        out.append(f"  {kind:12s} {n:>9,}  {audit.share(kind):6.1%}  {mark}")
    out.append("")
    out.append(
        f"LEARNER-ONLY FILTER keeps {audit.learner_messages:,} messages "
        f"({audit.learner_messages / audit.messages if audit.messages else 0:.1%}) "
        f"in {audit.sessions_kept:,} sessions; drops {audit.sessions_dropped:,} sessions "
        "that contain no learner-kind message"
    )
    out.append("")
    out.append("PER SOURCE            sessions   kept    messages   learner")
    for s in sorted(audit.per_source, key=lambda s: -s.messages):
        out.append(
            f"  {s.source:18s} {s.sessions:>8,} {s.sessions_kept:>6,} {s.messages:>11,} "
            f"{s.learner_messages:>9,}"
        )
    out.append("")
    out.append("LEARNING TIER (row counts, carried verbatim)")
    for table, n in audit.learning_tier.items():
        out.append(f"  {table:20s} {n:>6,}")
    return "\n".join(out)


__all__ = [
    "ACK_MAX_CHARS",
    "CorpusAudit",
    "LEARNING_TIER_TABLES",
    "SourceAudit",
    "audit_corpus",
    "render_audit",
    "ALL_KINDS",
    "BRIEF_MIN_CHARS",
    "KIND_ACK",
    "KIND_BRIEF",
    "KIND_EMPTY",
    "KIND_HUMAN",
    "KIND_INJECTED",
    "KIND_OTHER",
    "KIND_PROSE",
    "KIND_PROXY_PROBE",
    "KIND_STUB",
    "KIND_TOOL_ECHO",
    "LEARNER_KINDS",
    "MESSAGE_KIND_SQL",
    "STUB_MAX_CHARS",
    "build_message_kind_sql",
    "learner_kinds_sql",
    "message_kind",
]
