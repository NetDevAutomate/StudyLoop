"""Black-box contract tests for the session_search planner retrofit."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.migrations import migrate

_GOLDEN = Path(__file__).parent / "golden" / "session_search_pre_planner.json"


@pytest.fixture
def planner_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return the public session_search callable over the frozen golden corpus."""
    db_path = tmp_path / "golden.db"
    conn = sqlite3.connect(db_path)
    schema = Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    conn.executescript(schema.read_text(encoding="utf-8"))
    migrate(conn)
    conn.executemany(
        "INSERT INTO sessions(id,source,project_path,updated_at) VALUES (?,?,?,?)",
        (
            (
                "sess-auth-001",
                "claude_code",
                "/projects/webapp",
                "2026-01-01T12:00:00",
            ),
            ("sess-error-002", "kiro_cli", None, "2026-01-02T11:00:00"),
        ),
    )
    conn.executemany(
        "INSERT INTO messages(id,session_id,role,content,timestamp,seq) "
        "VALUES (?,?,?,?,?,?)",
        (
            (
                "msg-auth",
                "sess-auth-001",
                "assistant",
                "authentication " + "A" * 400,
                "2026-01-01T10:01:00",
                1,
            ),
            (
                "msg-alpha",
                "sess-auth-001",
                "user",
                "alpha only",
                "2026-01-01T10:02:00",
                2,
            ),
            (
                "msg-bravo",
                "sess-error-002",
                "user",
                "bravo only",
                "2026-01-02T09:00:00",
                1,
            ),
            (
                "msg-phrase",
                "sess-auth-001",
                "user",
                "the exact phrase appears here",
                "2026-01-01T10:03:00",
                3,
            ),
            (
                "msg-error",
                "sess-error-002",
                "assistant",
                "error diagnostic",
                "2026-01-02T09:01:00",
                2,
            ),
            (
                "msg-separated-phrase",
                "sess-error-002",
                "user",
                "exact unrelated phrase",
                "2026-01-02T09:02:00",
                3,
            ),
            (
                "msg-delta",
                "sess-auth-001",
                "user",
                "delta only",
                "2026-01-01T10:04:00",
                4,
            ),
            (
                "msg-delta-echo",
                "sess-error-002",
                "user",
                "delta echo",
                "2026-01-02T09:03:00",
                4,
            ),
            (
                "msg-diagnostic",
                "sess-auth-001",
                "user",
                "diagnostic standalone",
                "2026-01-01T10:05:00",
                5,
            ),
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("agent_session_tools.mcp_server._get_db_path", lambda: db_path)
    from agent_session_tools.mcp_server import mcp

    tools = {
        tool.name: tool.fn  # type: ignore[attr-defined]
        for tool in asyncio.run(mcp._list_tools())
    }
    return tools["session_search"]


def test_session_search_preserves_every_non_widened_golden_case(planner_search) -> None:
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))

    for case in golden["cases"]:
        if case["name"] == "two-term-and-empty":
            continue
        payload = planner_search(**case["arguments"])
        rows = payload["rows"]
        assert rows == case["results"], case["name"]
        assert all(list(row) == golden["row_keys"] for row in rows)
        assert all(len(row["preview"]) <= golden["preview_char_limit"] for row in rows)
        assert payload["retrieval_status"]["mode"] == "lexical", case["name"]

    single = next(case for case in golden["cases"] if case["name"] == "single-term")
    assert len(single["results"][0]["preview"]) == 300


def test_session_search_falls_back_to_or_when_implicit_and_is_empty(
    planner_search,
) -> None:
    expected = [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "user",
            "timestamp": "2026-01-02T09:00:00",
            "preview": "bravo only",
            "message_id": "msg-bravo",
        },
        {
            "session_id": "sess-auth-001",
            "source": "claude_code",
            "project_path": "/projects/webapp",
            "updated_at": "2026-01-01T12:00:00",
            "role": "user",
            "timestamp": "2026-01-01T10:02:00",
            "preview": "alpha only",
            "message_id": "msg-alpha",
        },
    ]

    payload = planner_search(query="alpha bravo")
    assert payload["rows"] == expected
    assert planner_search(query="alpha bravo")["rows"] == expected

    status = payload["retrieval_status"]
    assert status["plan"] == "or"
    assert status["widened"] is True
    assert status["terms"] == ["alpha", "bravo"]
    assert status["queries"] == ['"alpha" AND "bravo"', '"alpha" OR "bravo"']


def test_session_search_stops_after_and_fills_the_limit(planner_search) -> None:
    payload = planner_search(query="error diagnostic", limit=1)

    assert payload["rows"] == [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "assistant",
            "timestamp": "2026-01-02T09:01:00",
            "preview": "error diagnostic",
            "message_id": "msg-error",
        }
    ]
    status = payload["retrieval_status"]
    assert status["plan"] == "and"
    assert status["widened"] is False
    assert status["queries"] == ['"error" AND "diagnostic"']


def test_session_search_preserves_explicit_phrase_adjacency(planner_search) -> None:
    payload = planner_search(query='"exact phrase"')

    assert [row["preview"] for row in payload["rows"]] == [
        "the exact phrase appears here"
    ]
    assert "exact unrelated phrase" not in {row["preview"] for row in payload["rows"]}
    # The double-quoted span survives planning as a phrase term, so adjacency
    # holds without the caller opting into explicit FTS5.
    assert payload["retrieval_status"]["terms"] == ['"exact phrase"']
    assert payload["retrieval_status"]["queries"] == ['"exact phrase"']


def test_session_search_preserves_explicit_not_exclusion(planner_search) -> None:
    payload = planner_search(query="delta NOT echo")

    assert [row["preview"] for row in payload["rows"]] == ["delta only"]
    assert "delta echo" not in {row["preview"] for row in payload["rows"]}
    assert payload["retrieval_status"]["plan"] == "explicit"
    assert payload["retrieval_status"]["queries"] == ["delta NOT echo"]


def test_session_search_preserves_explicit_and_or_controls(planner_search) -> None:
    conjunction = planner_search(query="error AND diagnostic")
    assert conjunction["rows"] == [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "assistant",
            "timestamp": "2026-01-02T09:01:00",
            "preview": "error diagnostic",
            "message_id": "msg-error",
        }
    ]
    assert conjunction["retrieval_status"]["plan"] == "explicit"

    disjunction = planner_search(query="error OR authentication")
    assert disjunction["rows"] == [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "assistant",
            "timestamp": "2026-01-02T09:01:00",
            "preview": "error diagnostic",
            "message_id": "msg-error",
        },
        {
            "session_id": "sess-auth-001",
            "source": "claude_code",
            "project_path": "/projects/webapp",
            "updated_at": "2026-01-01T12:00:00",
            "role": "assistant",
            "timestamp": "2026-01-01T10:01:00",
            "preview": "authentication " + "A" * 285,
            "message_id": "msg-auth",
        },
    ]
    assert disjunction["retrieval_status"]["plan"] == "explicit"


def test_session_search_treats_lowercase_operators_as_words(planner_search) -> None:
    """A real learner's sentence: lowercase operators, a backtick, a question mark."""
    payload = planner_search(
        query="how did the `authentication` error and the alpha not the bravo?"
    )

    assert isinstance(payload, dict)
    status = payload["retrieval_status"]
    # Never explicit: only an uppercase operator or the fts: prefix opts in.
    assert status["plan"] == "or"
    assert status["mode"] == "lexical"
    assert status["terms"] == ["authentication", "error", "alpha", "bravo"]
    assert {row["message_id"] for row in payload["rows"]} == {
        "msg-auth",
        "msg-error",
        "msg-alpha",
        "msg-bravo",
    }


def test_session_search_passes_the_fts_prefix_through_verbatim(planner_search) -> None:
    payload = planner_search(query="fts:error OR authentication")

    assert payload["retrieval_status"]["plan"] == "explicit"
    assert payload["retrieval_status"]["queries"] == ["error OR authentication"]
    assert [row["message_id"] for row in payload["rows"]] == ["msg-error", "msg-auth"]


def test_session_search_degrades_a_rejected_explicit_query(planner_search) -> None:
    payload = planner_search(query="fts:bad `syntax` AND ?")

    assert isinstance(payload["rows"], list)
    note = payload["retrieval_status"]["note"]
    assert note is not None
    assert "rejected" in note
    assert "natural language" in note


def test_session_search_reports_a_query_with_no_content_terms(planner_search) -> None:
    payload = planner_search(query="what is the?")

    assert payload["rows"] == []
    status = payload["retrieval_status"]
    assert status["plan"] == "none"
    assert status["terms"] == []
    assert status["note"] is not None
    assert "stop words" in status["note"]


def test_session_search_excludes_named_message_ids(planner_search) -> None:
    everything = planner_search(query="error OR authentication")
    assert [row["message_id"] for row in everything["rows"]] == [
        "msg-error",
        "msg-auth",
    ]

    remaining = planner_search(
        query="error OR authentication", exclude_message_ids=["msg-error"]
    )
    assert [row["message_id"] for row in remaining["rows"]] == ["msg-auth"]


def test_session_search_does_not_widen_nonempty_implicit_and(planner_search) -> None:
    payload = planner_search(query="error diagnostic")

    assert payload["rows"] == [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "assistant",
            "timestamp": "2026-01-02T09:01:00",
            "preview": "error diagnostic",
            "message_id": "msg-error",
        }
    ]
    assert payload["retrieval_status"]["widened"] is False
    assert payload["retrieval_status"]["queries"] == ['"error" AND "diagnostic"']


def test_session_search_safely_plans_adversarial_plain_text_punctuation(
    planner_search,
) -> None:
    expected = [
        "bravo only",
        "alpha only",
    ]

    first = planner_search(query="can't: alpha!!! bravo???")
    second = planner_search(query="can't: alpha!!! bravo???")

    assert [row["preview"] for row in first["rows"]] == expected
    assert first == second
    assert first["retrieval_status"]["plan"] == "or"


def test_session_search_survives_nested_fts_prefixes_and_a_twice_broken_query(
    planner_search,
) -> None:
    """Council Stage 2 F1: the fallback after a rejected explicit query must plan
    as natural language only. Re-entering explicit detection ran ``alpha?``
    unguarded and crashed the tool."""
    for query in ("fts:fts:alpha?", 'fts:"alpha" OR ? AND', "fts:  fts: alpha ?"):
        payload = planner_search(query=query)
        status = payload["retrieval_status"]
        assert status["plan"] in {"and", "or"}, (query, status)
        assert "rejected" in (status["note"] or ""), (query, status)
        assert [row["session_id"] for row in payload["rows"]] == ["sess-auth-001"]


def test_session_search_keeps_an_operator_inside_quotes_as_part_of_the_phrase(
    planner_search,
) -> None:
    """Council Stage 2 F2: ``"error OR warning" recovery`` is a phrase plus a
    word, so it plans (and widens) like any sentence; uppercase and lowercase
    inside the quotes must behave identically. The fixture has no message
    containing both, so only the OR widening can reach ``error diagnostic``."""
    upper = planner_search(query='"error OR warning" recovery')
    lower = planner_search(query='"error or warning" recovery')
    assert (
        upper["retrieval_status"]["plan"] == lower["retrieval_status"]["plan"] == "or"
    )
    assert upper["retrieval_status"]["queries"] == [
        '"error OR warning" AND "recovery"',
        '"error OR warning" OR "recovery"',
    ]
    assert upper["rows"] == lower["rows"] or [
        r["session_id"] for r in upper["rows"]
    ] == [r["session_id"] for r in lower["rows"]]
    # An operator OUTSIDE the quotes is still explicit.
    explicit = planner_search(query='"exact phrase" OR authentication')
    assert explicit["retrieval_status"]["plan"] == "explicit"
