"""Project aliases broaden retrieval only through explicit, bounded identities."""

import json
import pytest

from agent_session_tools.query_utils import build_project_filter
from agent_session_tools.semantic_search import SearchContext, _fts_search


@pytest.fixture
def aliases(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(
        json.dumps(
            {
                "memory": {"default_scope": "unclassified"},
                "project_aliases": {
                    "/current/personal/studyloop": [
                        "/old/person/studyloop",
                        "-old-person-studyloop",
                        "/worktrees/known/studyloop",
                    ],
                },
            }
        )
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))


def test_alias_boundaries_and_reverse_lookup(aliases, migrated_db):
    conn, _ = migrated_db
    paths = [
        "/current/personal/studyloop",
        "/old/person/studyloop",
        "-old-person-studyloop/session/subagents",
        "/worktrees/known/studyloop",
        "/old/person/studyloop-other",
        "/work/studyloop",
        "-old-person-studyloop-other",
    ]
    for idx, path in enumerate(paths):
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES(?,?,?)",
            (str(idx), "codex", path),
        )
    for requested in [
        "/current/personal/studyloop/",
        "/old/person/studyloop",
        "-old-person-studyloop",
    ]:
        clause, params = build_project_filter(requested)
        matches = [
            row[0]
            for row in conn.execute(
                "SELECT s.id FROM sessions s WHERE " + clause, params
            )
        ]
        assert set(matches) == {"0", "1", "2", "3"}


def test_unconfigured_paths_do_not_expand_but_names_still_search(aliases):
    clause, params = build_project_filter("/work/studyloop")
    assert "/old/person/studyloop" not in params
    assert build_project_filter("studyloop") == (
        "s.project_path LIKE ? ESCAPE '\\'",
        ["%studyloop%"],
    )
    with pytest.raises(ValueError):
        build_project_filter("studyloop", "unsafe SQL")


def test_fts_uses_configured_aliases(aliases, migrated_db):
    conn, _ = migrated_db
    conn.execute(
        "INSERT INTO sessions(id,source,project_path) VALUES('historical','claude_code','/old/person/studyloop')"
    )
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES('evidence','historical','assistant','Closure evidence')"
    )
    results = _fts_search(
        conn,
        "Closure",
        limit=10,
        context=SearchContext(project_path="/current/personal/studyloop"),
    )
    assert len(results) == 1
    assert results[0]["session_id"] == "historical"


@pytest.mark.parametrize("command", ["search", "search-cmd"])
def test_plain_query_cli_project_aliases(command, aliases, migrated_db):
    from typer.testing import CliRunner
    from agent_session_tools.query_sessions import app

    conn, path = migrated_db
    for session_id, project in [
        ("yes", "/old/person/studyloop"),
        ("no", "/work/studyloop"),
    ]:
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES(?,?,?)",
            (session_id, "codex", project),
        )
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES(?,?,?,?)",
            ("msg-" + session_id, session_id, "assistant", "retrieval evidence"),
        )
    conn.commit()
    result = CliRunner().invoke(
        app,
        [
            command,
            "retrieval",
            "--db",
            str(path),
            "--project",
            "/current/personal/studyloop",
            "--local-only",
            "--output-format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [row["session_id"] for row in payload["rows"]] == ["yes"]
