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
        actual = planner_search(**case["arguments"])
        assert actual == case["results"], case["name"]
        assert all(list(row) == golden["row_keys"] for row in actual)
        assert all(
            len(row["preview"]) <= golden["preview_char_limit"] for row in actual
        )

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
        },
        {
            "session_id": "sess-auth-001",
            "source": "claude_code",
            "project_path": "/projects/webapp",
            "updated_at": "2026-01-01T12:00:00",
            "role": "user",
            "timestamp": "2026-01-01T10:02:00",
            "preview": "alpha only",
        },
    ]

    assert planner_search(query="alpha bravo") == expected
    assert planner_search(query="alpha bravo") == expected


def test_session_search_stops_after_and_fills_the_limit(planner_search) -> None:
    assert planner_search(query="error diagnostic", limit=1) == [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "assistant",
            "timestamp": "2026-01-02T09:01:00",
            "preview": "error diagnostic",
        }
    ]


def test_session_search_preserves_explicit_phrase_adjacency(planner_search) -> None:
    results = planner_search(query='"exact phrase"')

    assert [row["preview"] for row in results] == ["the exact phrase appears here"]
    assert "exact unrelated phrase" not in {row["preview"] for row in results}


def test_session_search_preserves_explicit_not_exclusion(planner_search) -> None:
    results = planner_search(query="delta NOT echo")

    assert [row["preview"] for row in results] == ["delta only"]
    assert "delta echo" not in {row["preview"] for row in results}


def test_session_search_preserves_explicit_and_or_controls(planner_search) -> None:
    assert planner_search(query="error AND diagnostic") == [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "assistant",
            "timestamp": "2026-01-02T09:01:00",
            "preview": "error diagnostic",
        }
    ]
    assert planner_search(query="error OR authentication") == [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "assistant",
            "timestamp": "2026-01-02T09:01:00",
            "preview": "error diagnostic",
        },
        {
            "session_id": "sess-auth-001",
            "source": "claude_code",
            "project_path": "/projects/webapp",
            "updated_at": "2026-01-01T12:00:00",
            "role": "assistant",
            "timestamp": "2026-01-01T10:01:00",
            "preview": "authentication " + "A" * 285,
        },
    ]


def test_session_search_safely_plans_adversarial_plain_text_punctuation(
    planner_search,
) -> None:
    expected = [
        "bravo only",
        "alpha only",
    ]

    first = planner_search(query="can't: alpha!!! bravo???")
    second = planner_search(query="can't: alpha!!! bravo???")

    assert [row["preview"] for row in first] == expected
    assert first == second


def test_session_search_does_not_widen_nonempty_implicit_and(planner_search) -> None:
    assert planner_search(query="error diagnostic") == [
        {
            "session_id": "sess-error-002",
            "source": "kiro_cli",
            "project_path": None,
            "updated_at": "2026-01-02T11:00:00",
            "role": "assistant",
            "timestamp": "2026-01-02T09:01:00",
            "preview": "error diagnostic",
        }
    ]
