"""StudyLoop consumes only explicitly scoped history before model exposure."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest
from click.testing import CliRunner

from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.migrations import migrate
from studyloop.cli import _extract, cli
from studyloop.history import search, sessions, streaks


@pytest.fixture
def consumer_db(tmp_path, monkeypatch):
    monkeypatch.delenv("SESSION_CONTEXT_SCOPE", raising=False)
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)
    now = datetime.now(UTC)
    for index, (sid, root, word) in enumerate(
        [("personal", "/consumer/personal", "python"), ("work", "/consumer/work", "redshift")]
    ):
        timestamp = (now - timedelta(minutes=2 - index)).isoformat()
        conn.execute(
            "INSERT INTO sessions(id,source,project_path,created_at,updated_at) VALUES (?,?,?,?,?)",
            (sid, "kiro_cli", root, timestamp, timestamp),
        )
        for seq, role in enumerate(["user", "assistant"]):
            conn.execute(
                "INSERT INTO messages(id,session_id,role,content,seq,timestamp) "
                "VALUES (?,?,?,?,?,?)",
                (sid + str(seq), sid, role, f"{word} question? {sid.upper()}_ONLY", seq, timestamp),
            )
    conn.execute(
        "INSERT INTO study_progress(id,topic,concept,confidence,first_seen,last_seen) "
        "VALUES (?,?,?,?,?,?)",
        ("merged", "sql", "UNSCOPED_MERGED_CONTENT", "learning", now.isoformat(), now.isoformat()),
    )
    conn.execute(
        "INSERT INTO study_progress(id,topic,concept,confidence,first_seen,last_seen) "
        "VALUES (?,?,?,?,?,?)",
        ("win", "python", "UNSCOPED_WIN", "confident", now.isoformat(), now.isoformat()),
    )
    conn.execute(
        "INSERT INTO study_sessions(id,topic,started_at,duration_minutes) VALUES (?,?,?,?)",
        ("learning-session", "UNSCOPED_STUDY_SESSION", now.isoformat(), 20),
    )
    conn.commit()
    config = tmp_path / "memory.yaml"
    settings = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": ["/consumer/personal"]},
                "work": {"scope": "work", "roots": ["/consumer/work"]},
            },
        }
    }
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("STUDYLOOP_DB", str(db))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False)
    conn.close()
    return db, config, settings


def test_history_resume_and_streaks_exclude_newer_work_source(consumer_db):
    found = search.topic_frequency(["python", "redshift"])
    assert {row["session_id"] for row in found} == {"personal"}
    struggles = search.struggle_topics(min_sessions=1)
    assert "redshift" not in json.dumps(struggles)
    assert "python" in json.dumps(struggles)
    summary = sessions.get_last_session_summary()
    assert summary is not None
    assert summary["session_id"] == "personal"
    assert "PERSONAL_ONLY" in summary["last_message_preview"]
    assert "WORK_ONLY" not in json.dumps(summary)
    assert "UNSCOPED_MERGED_CONTENT" not in json.dumps(summary)
    assert summary["concepts_scope_status"] == "withheld_missing_scope_lineage"
    assert streaks.get_study_streaks()["sessions_this_week"] == 1


def test_extractor_selection_and_body_reads_filter_before_provider(consumer_db):
    db, _, _ = consumer_db
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    received = []

    def provider(messages, session_id):
        received.append((session_id, messages))
        return []

    try:
        assert _extract._most_recent_session(conn, "kiro_cli") == "personal"
        assert _extract._sessions_for_source(conn, "kiro_cli", None) == ["personal"]
        assert _extract._fetch_messages(conn, "work") == []
        assert _extract._session_source(conn, "work") is None
        with pytest.raises(ScopeError, match="unavailable"):
            _extract._process_one(conn, "work", provider, dry_run=True)
        assert received == []
        _extract._process_one(conn, "personal", provider, dry_run=True)
        assert len(received) == 1 and received[0][0] == "personal"
        assert "WORK_ONLY" not in json.dumps(received)
    finally:
        conn.close()


def test_classified_progress_write_is_refused_before_provider(consumer_db):
    from studyloop.extractors.pipeline import extract_and_write

    db, _, _ = consumer_db
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    called = []
    try:
        before = conn.execute("SELECT * FROM study_progress ORDER BY id").fetchall()
        with pytest.raises(ScopeError, match="source-owned learning records"):
            extract_and_write(
                "personal", [], lambda *args: called.append(args) or [], connection=conn
            )
        assert called == []
        assert conn.execute("SELECT * FROM study_progress ORDER BY id").fetchall() == before
    finally:
        conn.close()


def test_eval_withholds_excluded_labels_and_uses_read_only_database(consumer_db, monkeypatch):
    from studyloop.extractors import eval_runner

    db, _, _ = consumer_db
    golden = [{"session_id": sid, "is_negative": False} for sid in ["personal", "work"]]
    monkeypatch.setattr(
        eval_runner,
        "_load",
        lambda path: (
            golden if path == eval_runner._GOLDEN_PATH else {"train": ["personal", "work"]}
        ),
    )
    received = []

    def provider(messages, session_id, **kwargs):
        received.append((session_id, messages))
        return []

    monkeypatch.setattr(eval_runner, "extract_struggles", provider)
    _, _, scores = eval_runner.run_eval("train", db_path=db, model="fixture")
    assert [sid for sid, _ in received] == ["personal"]
    assert scores[1].error == "Session unavailable in the configured scope"
    assert "WORK_ONLY" not in json.dumps(received)
    missing = db.parent / "absent.db"
    with pytest.raises(sqlite3.OperationalError):
        eval_runner.run_eval("train", db_path=missing, model="fixture")
    assert not missing.exists()


def test_resume_cli_explains_withholding_and_policy_error(consumer_db):
    _, config, settings = consumer_db
    runner = CliRunner()
    result = runner.invoke(cli, ["resume"])
    assert result.exit_code == 0, repr(result.exception)
    assert "work/personal scope is known" in result.output
    assert "WORK_ONLY" not in result.output
    settings["memory"]["projects"]["personal"]["scope"] = "work"
    config.write_text(json.dumps(settings))
    result = runner.invoke(cli, ["resume"])
    assert result.exit_code == 1
    assert "session-context policy apply" in result.output
    assert "PERSONAL_ONLY" not in result.output


def test_studyloop_mcp_history_withholds_unowned_learning_fields(consumer_db):
    from studyloop.history import get_wins
    from studyloop.mcp.server import mcp

    tool = mcp._tool_manager._tools["get_study_history"].fn
    result = tool(topic="python")
    assert result["last_studied"] is not None
    assert result["session_stats"] == []
    assert result["wins"] == []
    assert result["learning_scope_status"] == "withheld_missing_scope_lineage"
    assert "UNSCOPED" not in json.dumps(result)
    assert sessions.get_study_session_stats() == []
    assert get_wins() == []


def test_memory_config_is_recognised_by_studyloop(consumer_db):
    from studyloop.settings import unknown_top_level_keys

    assert "memory" not in unknown_top_level_keys()


def test_studyloop_stdio_history_keeps_scope_across_requests(consumer_db):
    import asyncio
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, config, settings = consumer_db

    async def journey():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "studyloop.mcp.server"],
            env=dict(os.environ),
        )
        async with (
            stdio_client(params) as (reader, writer),
            ClientSession(reader, writer) as client,
        ):
            await client.initialize()
            response = await client.call_tool("get_study_history", {"topic": "python"})
            assert not response.isError
            text = "".join(block.text for block in response.content if block.type == "text")
            assert "withheld_missing_scope_lineage" in text
            assert "UNSCOPED" not in text and "WORK_ONLY" not in text
            settings["memory"]["projects"]["personal"]["scope"] = "work"
            config.write_text(json.dumps(settings))
            response = await client.call_tool("get_study_history", {"topic": "python"})
            assert response.isError
            text = "".join(block.text for block in response.content if block.type == "text")
            assert "policy apply" in text
            assert "PERSONAL_ONLY" not in text and "WORK_ONLY" not in text

    asyncio.run(journey())


@pytest.mark.parametrize("read", [sessions.get_last_session_summary, streaks.get_study_streaks])
def test_missing_policy_is_not_presented_as_no_history(consumer_db, read):
    _, config, _ = consumer_db
    config.write_text("memory: {}\n")
    with pytest.raises(ScopeError, match="No context scope"):
        read()
