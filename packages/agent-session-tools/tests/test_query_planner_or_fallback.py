"""§5 stream (council D-12): the prose-OR widen candidate and the door in front of it.

The candidate is ``plan_prose_query`` from the archived ``feat/knowledge-proof``
branch, ported as :func:`agent_session_tools.query_planner.prose_or_query`: every
whitespace token of the *raw* question, control and surrogate characters
stripped, tokens without an alphanumeric dropped, each survivor double-quoted
(embedded quotes doubled) and joined with ``OR``. No stop list, no length
filter -- that is the whole hypothesis, and the reason it may only ever run
as the OR *widen* step after the shipped AND arm found nothing.

Two things are pinned here regardless of the adopt/reject verdict:

* the explicit door (``fts:`` prefix, uppercase operator outside quotes) is
  classified by :func:`retrieval.plan_query` before any natural-language
  planning and is passed through verbatim -- the candidate never sees it;
* ``tests/golden/session_search_pre_planner.json`` is byte-identical to the
  form committed at ``d060d3f2`` (freeze guardrail 4; §5 adopt clause 4).
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_session_tools import retrieval
from agent_session_tools.migrations import migrate
from agent_session_tools.query_planner import prose_or_query
from agent_session_tools.retrieval import plan_natural_language, plan_query, search

_GOLDEN = Path(__file__).parent / "golden" / "session_search_pre_planner.json"
#: sha256 of the golden as committed at ``d060d3f2`` (Stage 2 surfaces commit).
#: A content digest of a committed public fixture, not a credential.
PRE_PLANNER_GOLDEN_SHA256 = "7152dae40af4918dffd6a51cc4b7d399c433384a3caa9a7ca64164e7a56795f6"  # pragma: allowlist secret
_NATURAL_LANGUAGE_ENTRY = "agent_session_tools.retrieval.plan_natural_language"


@pytest.fixture
def conn() -> sqlite3.Connection:
    """The package's own schema (porter unicode61 FTS5) over three tiny messages."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema = Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    connection.executescript(schema.read_text(encoding="utf-8"))
    migrate(connection)
    connection.execute(
        "INSERT INTO sessions(id, source, project_path, updated_at) VALUES (?,?,?,?)",
        ("sess-1", "claude_code", "/projects/x", "2026-01-01T12:00:00"),
    )
    connection.executemany(
        "INSERT INTO messages(id, session_id, role, content, timestamp, seq) "
        "VALUES (?,?,?,?,?,?)",
        (
            (
                "m-error",
                "sess-1",
                "assistant",
                "error diagnostic",
                "2026-01-01T10:01:00",
                1,
            ),
            (
                "m-auth",
                "sess-1",
                "user",
                "authentication token",
                "2026-01-01T10:02:00",
                2,
            ),
            (
                "m-phrase",
                "sess-1",
                "user",
                "the exact phrase",
                "2026-01-01T10:03:00",
                3,
            ),
        ),
    )
    connection.commit()
    return connection


def _door_leaked(query: str) -> retrieval.QueryPlan:
    raise AssertionError(
        f"the explicit door leaked into natural-language planning: {query!r}"
    )


def test_explicit_fts_prefix_is_verbatim(conn: sqlite3.Connection) -> None:
    """``fts:`` hands the body to FTS5 untouched; no planner -- shipped or candidate -- runs."""
    with patch(_NATURAL_LANGUAGE_ENTRY, side_effect=_door_leaked):
        plan = plan_query("fts:error OR authentication")
        assert plan.explicit is True
        assert plan.terms == ()
        assert plan.queries == ("error OR authentication",)

        result = search(conn, "fts:error OR authentication", mode="lexical")
    assert result.status.plan == "explicit"
    assert result.status.widened is False
    assert result.status.queries == ("error OR authentication",)
    assert {hit.message_id for hit in result.hits} == {"m-error", "m-auth"}


def test_uppercase_operator_outside_quotes_is_verbatim(
    conn: sqlite3.Connection,
) -> None:
    """An uppercase operator outside every double-quoted span is explicit FTS5."""
    with patch(_NATURAL_LANGUAGE_ENTRY, side_effect=_door_leaked):
        for query in ("error OR authentication", '"exact phrase" OR authentication'):
            plan = plan_query(query)
            assert plan.explicit is True, query
            assert plan.queries == (query,), query

        result = search(conn, "error OR authentication", mode="lexical")
    assert result.status.plan == "explicit"
    assert result.status.queries == ("error OR authentication",)
    assert {hit.message_id for hit in result.hits} == {"m-error", "m-auth"}


def test_quoted_operator_is_not_explicit() -> None:
    """``"error OR warning" recovery`` is a phrase plus a word: it reaches the
    natural-language planner, which is exactly where the candidate's widen would apply."""
    with patch(_NATURAL_LANGUAGE_ENTRY, wraps=plan_natural_language) as spy:
        plan = plan_query('"error OR warning" recovery')
    assert plan.explicit is False
    spy.assert_called_once_with('"error OR warning" recovery')
    assert plan.terms == ('"error OR warning"', "recovery")
    assert plan.queries[0] == '"error OR warning" AND "recovery"'
    # The lowercase form classifies identically: operators are uppercase by definition.
    assert plan_query('"error or warning" recovery').explicit is False


def test_prose_or_quotes_embedded_quotes_and_strips_controls() -> None:
    """Every raw token is kept -- stop words included -- quoted with embedded quotes
    doubled; Cc (control) and Cs (surrogate) characters are removed before quoting."""
    query = 'the "quoted" token\x07 and a\x00nul \ud800lone'
    assert prose_or_query(query) == (
        '"the" OR """quoted""" OR "token" OR "and" OR "anul" OR "lone"'
    )
    # A token of only quote marks around letters is still one quoted phrase.
    assert prose_or_query('"a"') == '"""a"""'
    # Whitespace of any kind separates tokens; nothing else does.
    assert prose_or_query("alpha\tbravo\ncharlie") == '"alpha" OR "bravo" OR "charlie"'


def test_prose_or_drops_tokens_without_alphanumerics() -> None:
    """Punctuation-only tokens carry nothing FTS5 can match and are dropped whole;
    a token that mixes punctuation and letters is kept as-is (the tokenizer strips it)."""
    assert prose_or_query("alpha --- ??? ... bravo!") == '"alpha" OR "bravo!"'
    assert prose_or_query("??? --") == ""
    assert prose_or_query("") == ""
    assert prose_or_query("   ") == ""


@pytest.mark.parametrize(
    "query",
    [
        "how did the `authentication` error and the alpha not the bravo?",
        'fts:"alpha" OR ? AND',
        '"unterminated OR',
        "a AND OR NOT NEAR b",
        'weird """" quotes "" here',
        "col:value ^caret star* (paren) {brace} [bracket]",
        "unicode ✓ 日本語 émigré",
    ],
)
def test_prose_or_cannot_fail_to_parse(conn: sqlite3.Connection, query: str) -> None:
    """The candidate's claim, for the inputs named here: the nonempty OR form is
    valid FTS5. (An empty return is the caller's to handle -- an empty ``MATCH``
    is itself a syntax error -- and backend limits are not exercised.)"""
    match = prose_or_query(query)
    assert match, query
    conn.execute("SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?", (match,))


def test_pre_planner_golden_unchanged() -> None:
    """Freeze guardrail 4 / §5 adopt clause 4: the golden is byte-identical to ``d060d3f2``."""
    assert hashlib.sha256(_GOLDEN.read_bytes()).hexdigest() == PRE_PLANNER_GOLDEN_SHA256
