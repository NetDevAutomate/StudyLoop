"""Tests for agent_session_tools.corpus — the single message-kind classifier.

The load-bearing property is that the Python predicate and the SQL CASE
expression return the SAME label for every row, because they will be applied
by different readers to the same database and any disagreement is a leak in
one direction or the other.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools import corpus
from agent_session_tools.corpus import (
    ALL_KINDS,
    KIND_ACK,
    KIND_BRIEF,
    KIND_EMPTY,
    KIND_HUMAN,
    KIND_INJECTED,
    KIND_OTHER,
    KIND_PROSE,
    KIND_PROXY_PROBE,
    KIND_STUB,
    KIND_TOOL_ECHO,
    LEARNER_KINDS,
    MESSAGE_KIND_SQL,
    build_message_kind_sql,
    learner_kinds_sql,
    message_kind,
)

# One representative per kind, plus the shapes that actually occur in the live
# corpus (sampled 2026-09-12). The comment on each row is the reason it exists.
FIXTURE: list[tuple[str, str | None, str]] = [
    ("assistant", "[tool:Bash]", KIND_TOOL_ECHO),
    ("assistant", "[tool:Read] /some/path.py", KIND_TOOL_ECHO),  # trailer after marker
    ("assistant", "[tool:StructuredOutput]\n", KIND_TOOL_ECHO),  # trailing newline
    ("assistant", "  [tool:Bash]  ", KIND_TOOL_ECHO),  # padded
    (
        "assistant",
        "[tool:Bash]\nRan tests, 3 failed.",
        KIND_STUB,
    ),  # echo + narration: not pure
    ("assistant", "Let me fix the escaping:", KIND_STUB),
    ("assistant", "4", KIND_STUB),
    ("assistant", "x" * 39, KIND_STUB),  # boundary: below
    ("assistant", "x" * 40, KIND_PROSE),  # boundary: at
    ("assistant", "All 3 replaced correctly. Let's run the suite now.", KIND_PROSE),
    ("user", "[LiteLLM Request: eu.mistral.pixtral-large-2502-v1:0]", KIND_PROXY_PROBE),
    ("user", "What is 2+2? Reply with just the number.", KIND_PROXY_PROBE),
    ("user", "Warmup", KIND_PROXY_PROBE),
    ("user", "# AGENTS.md instructions for /x\n\n<INSTRUCTIONS>\n...", KIND_INJECTED),
    ("user", "You are a research agent for an AWS analytics PoC.", KIND_INJECTED),
    (
        "user",
        "<system-reminder>\nOther agents active.\n</system-reminder>",
        KIND_INJECTED,
    ),
    (
        "user",
        "<observed_from_primary_session>\n<what_happened>Bash</what_happened>",
        KIND_INJECTED,
    ),
    ("user", "<command-name>/model</command-name>", KIND_INJECTED),
    (
        "user",
        "@src/main.py please review this file for me",
        KIND_INJECTED,
    ),  # @-mention envelope
    (
        "user",
        "[execute_command for 'rm x'] Result: ok",
        KIND_INJECTED,
    ),  # '[' but not a probe
    ("user", "some text with <INSTRUCTIONS> in the middle of it", KIND_INJECTED),
    ("user", "--- MODE SWITCH: PROGRESS SUMMARY ---", KIND_INJECTED),
    ("user", "ok", KIND_ACK),
    ("user", "thank you", KIND_ACK),
    ("user", "x" * 19, KIND_ACK),  # boundary: below
    ("user", "x" * 20, KIND_HUMAN),  # boundary: at
    ("user", "Can you help with the optional step7_ml_training.py?", KIND_HUMAN),
    (
        "user",
        "the script just has:\n\nexport PYSPARK_DRIVER_PYTHON=jupyter\n",
        KIND_HUMAN,
    ),
    ("user", "y" * 1999, KIND_HUMAN),  # boundary: below
    ("user", "y" * 2000, KIND_BRIEF),  # boundary: at
    ("user", "", KIND_EMPTY),
    ("user", "   \n\t ", KIND_EMPTY),
    ("assistant", None, KIND_EMPTY),
    ("toolResult", "exit 0", KIND_OTHER),
    ("tool_use", "{}", KIND_OTHER),
    ("system", "hello there system message", KIND_OTHER),
    ("info", "x", KIND_OTHER),
    # LIKE metacharacters inside content must not be treated as wildcards.
    ("user", "100% sure this_is a real question about %s formatting?", KIND_HUMAN),
    ("assistant", "[tool:Bash] echo 100%_done", KIND_TOOL_ECHO),
]


def _sql_kind(
    conn: sqlite3.Connection,
    role: str,
    content: str | None,
    expr: str = MESSAGE_KIND_SQL,
) -> str:
    return conn.execute(
        f"SELECT {expr} FROM (SELECT ? AS role, ? AS content)", (role, content)
    ).fetchone()[0]


@pytest.fixture
def conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def test_every_kind_has_at_least_one_fixture() -> None:
    covered = {k for _, _, k in FIXTURE}
    assert covered == ALL_KINDS, f"kinds with no fixture: {sorted(ALL_KINDS - covered)}"


@pytest.mark.parametrize(("role", "content", "expected"), FIXTURE)
def test_python_form(role: str, content: str | None, expected: str) -> None:
    assert message_kind(role, content) == expected


@pytest.mark.parametrize(("role", "content", "expected"), FIXTURE)
def test_sql_form_matches_python(
    conn: sqlite3.Connection, role: str, content: str | None, expected: str
) -> None:
    assert _sql_kind(conn, role, content) == expected


def test_python_is_total_over_arbitrary_input() -> None:
    weird = [
        "",
        " ",
        "\n",
        "[",
        "]",
        "[tool:",
        "<",
        "@",
        "%",
        "_",
        "'",
        '"',
        "\\",
        "\x00",
        "é" * 50,
    ]
    for role in ("user", "assistant", "tool_use", None, ""):
        for text in weird:
            assert message_kind(role, text) in ALL_KINDS


def test_sql_and_python_agree_on_adversarial_input(conn: sqlite3.Connection) -> None:
    weird = [
        "",
        " ",
        "\n",
        "[",
        "]",
        "[tool:",
        "[tool:]",
        "[tool:x] y\n",
        "<",
        "@",
        "%",
        "_",
        "'",
        "\\",
        "é" * 50,
        "[tool:Bash]" + " " * 30,
        "\t[tool:Bash]\t",
        "What is 2+2",
        "You are",
        "You are X",
        "x" * 40,
        "x" * 39,
    ]
    for role in ("user", "assistant", "tool_use", "info"):
        for text in weird:
            assert _sql_kind(conn, role, text) == message_kind(role, text), (role, text)


def test_qualified_columns(conn: sqlite3.Connection) -> None:
    expr = build_message_kind_sql("m.role", "m.content")
    got = conn.execute(
        f"SELECT {expr} FROM (SELECT 'assistant' AS role, '[tool:Bash]' AS content) AS m"
    ).fetchone()[0]
    assert got == KIND_TOOL_ECHO


def test_learner_kinds_sql_selects_only_human_and_prose(
    conn: sqlite3.Connection,
) -> None:
    conn.execute("CREATE TABLE messages (role TEXT, content TEXT)")
    conn.executemany(
        "INSERT INTO messages VALUES (?, ?)", [(r, c) for r, c, _ in FIXTURE]
    )
    kept = conn.execute(
        f"SELECT {MESSAGE_KIND_SQL} FROM messages WHERE {learner_kinds_sql()}"
    ).fetchall()
    assert {k for (k,) in kept} == LEARNER_KINDS
    expected_n = sum(1 for _, _, k in FIXTURE if k in LEARNER_KINDS)
    assert len(kept) == expected_n


def test_markers_are_plain_literals() -> None:
    # The SQL form expresses markers with LIKE prefix/substring only, so a marker
    # must be a plain literal: no newline (LIKE prefix cannot span one the same
    # way strip() does) and nothing that reads as a LIKE wildcard unescaped.
    # '.' is fine — it is literal to both str.startswith and (escaped) LIKE.
    for marker in (
        corpus.INJECTED_PREFIXES
        + corpus.INJECTED_SUBSTRINGS
        + corpus.PROXY_PROBE_PREFIXES
    ):
        assert marker == marker.lstrip(), (
            f"leading whitespace can never match stripped text: {marker!r}"
        )
        assert "\n" not in marker, marker
        assert marker, "empty marker would match everything"


_LIVE = Path(
    os.environ.get("STUDYLOOP_LIVE_DB", Path.home() / ".config/studyloop/sessions.db")
)


@pytest.mark.skipif(not _LIVE.exists(), reason="live sessions.db not present")
def test_sql_and_python_agree_on_real_rows() -> None:
    """Read-only spot check against the operator's real database, when present.

    Fixtures cannot reproduce the shapes a live corpus contains; this is the
    check that catches the shape nobody thought of. Opens read-only, samples a
    fixed slice, never writes.
    """
    live = sqlite3.connect(f"file:{_LIVE}?mode=ro", uri=True)
    try:
        rows = live.execute(
            f"SELECT role, content, {MESSAGE_KIND_SQL} FROM messages "
            "WHERE rowid % 97 = 0 LIMIT 3000"
        ).fetchall()
    finally:
        live.close()
    assert rows, "sample was empty"
    disagreements = [
        (r, (c or "")[:80], sql_k, message_kind(r, c))
        for r, c, sql_k in rows
        if sql_k != message_kind(r, c)
    ]
    assert not disagreements, disagreements[:10]
