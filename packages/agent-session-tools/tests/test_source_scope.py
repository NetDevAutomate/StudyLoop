"""Retired harness labels are withheld from product reads, never deleted.

Receipt: ``docs/architecture/session-memory/receipts/adapter-scope-2026-09-10.md``
§4.4-4.5, §5 "Stage 4". ``aider`` is used deliberately as the retired label under
test — it is one of the seven real labels carried by the live database, and this
module is the guard that asserts it stays unreachable by default and reachable
on request.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_session_tools.context.provenance import Scope
from agent_session_tools.context.scope import (
    ScopePolicy,
    retirement_selection_sql,
    visibility_sql,
)
from agent_session_tools.migrations import migrate
from agent_session_tools.query_logic import list_sessions, search, stats
from agent_session_tools.sources import (
    FIRST_PARTY_SOURCES,
    SUPPORTED_SOURCES,
    is_supported,
    retired_source_counts,
)

# (session id, source, message body) — one admitted current harness, one
# newly-admitted harness, the first-party checkpoint label, and one retired label.
FIXTURE_SESSIONS = (
    ("sess-kiro-001", "kiro_cli", "kiroprose about a partition strategy"),
    ("sess-grok-002", "grok", "grokprose about a partition strategy"),
    ("sess-tutor-003", "study_mentor", "tutorprose about a partition strategy"),
    ("sess-aider-004", "aider", "aiderprose about a partition strategy"),
)

TOTAL_STORED = len(FIXTURE_SESSIONS)


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    schema = (
        Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    ).read_text()
    conn.executescript(schema)
    migrate(conn)
    for index, (session_id, source, body) in enumerate(FIXTURE_SESSIONS):
        conn.execute(
            "INSERT INTO sessions (id, source, project_path, git_branch, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (
                session_id,
                source,
                "/projects/pipeline",
                "main",
                f"2026-03-0{index + 1}T09:00:00",
                f"2026-03-0{index + 1}T12:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
            "VALUES (?,?,?,?,?,?)",
            (
                f"msg-{session_id}",
                session_id,
                "user",
                body,
                f"2026-03-0{index + 1}T09:00:00",
                1,
            ),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def scoped_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "scoped.db"
    _build_db(db_path)
    return db_path


@pytest.fixture
def scoped_db(scoped_db_path: Path):
    conn = sqlite3.connect(scoped_db_path.resolve().as_uri(), uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _raw_session_count(path: Path) -> int:
    """Count every stored row on a separate connection, past every predicate."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
    finally:
        conn.close()


class TestSupportedSources:
    def test_is_the_six_harnesses_plus_the_first_party_label(self):
        assert SUPPORTED_SOURCES == {
            "claude_code",
            "codex",
            "grok",
            "kiro_cli",
            "opencode",
            "pi",
            "study_mentor",
        }

    def test_study_mentor_is_first_party_not_a_harness(self):
        # tutor_checkpoint writes it live; no exporter declares it.
        assert FIRST_PARTY_SOURCES == {"study_mentor"}
        assert SUPPORTED_SOURCES - FIRST_PARTY_SOURCES == {
            "claude_code",
            "codex",
            "grok",
            "kiro_cli",
            "opencode",
            "pi",
        }

    def test_retired_labels_are_not_supported(self):
        for retired in (
            "repoprompt",
            "aider",
            "kilocode_cli",
            "litellm-proxy",
            "gemini_cli",
            "bedrock_proxy",
            "omp",
        ):
            assert not is_supported(retired)


class TestListSessions:
    def test_hides_a_retired_source_by_default(self, scoped_db, capsys):
        list_sessions(scoped_db, output_format="json")
        listed = {row["source"] for row in json.loads(capsys.readouterr().out)}
        assert listed == {"kiro_cli", "grok", "study_mentor"}

    def test_shows_a_retired_source_when_named_explicitly(self, scoped_db, capsys):
        list_sessions(scoped_db, source="aider", output_format="json")
        rows = json.loads(capsys.readouterr().out)
        assert [row["id"] for row in rows] == ["sess-aider-004"]

    def test_naming_a_supported_source_stays_scoped(self, scoped_db, capsys):
        list_sessions(scoped_db, source="grok", output_format="json")
        rows = json.loads(capsys.readouterr().out)
        assert [row["id"] for row in rows] == ["sess-grok-002"]


class TestSearch:
    def test_hides_a_retired_source_by_default(self, scoped_db, capsys):
        search(scoped_db, "partition", output_format="json")
        payload = json.loads(capsys.readouterr().out)
        found = {row["source"] for row in payload["rows"]}
        assert found == {"kiro_cli", "grok", "study_mentor"}

    def test_body_of_a_retired_session_is_not_returned(self, scoped_db, capsys):
        search(scoped_db, "aiderprose", output_format="json")
        assert json.loads(capsys.readouterr().out)["rows"] == []


class TestStats:
    def test_reports_the_hidden_count_without_deleting(self, scoped_db, capsys):
        stats(scoped_db, use_rich=False)
        out = capsys.readouterr().out
        assert "HIDDEN SOURCES" in out
        assert "1 sessions in 1 retired sources (hidden, not deleted)" in out
        assert "aider: 1" in out

    def test_sessions_by_source_omits_the_retired_label(self, scoped_db, capsys):
        stats(scoped_db, use_rich=False)
        sessions_section = capsys.readouterr().out.split("HIDDEN SOURCES")[0]
        assert "kiro_cli" in sessions_section
        assert "aider" not in sessions_section

    def test_rich_output_does_not_raise(self, scoped_db):
        stats(scoped_db, use_rich=True)


class TestRetiredSourceCounts:
    def test_counts_only_retired_labels(self, scoped_db):
        assert retired_source_counts(scoped_db) == {"aider": 1}

    def test_rejects_an_invalid_schema_identifier(self, scoped_db):
        with pytest.raises(ValueError):
            retired_source_counts(scoped_db, schema="main; DROP TABLE sessions")


class TestNothingIsDeleted:
    def test_raw_row_count_is_unchanged_by_every_read_surface(
        self, scoped_db, scoped_db_path, capsys
    ):
        assert _raw_session_count(scoped_db_path) == TOTAL_STORED
        list_sessions(scoped_db, output_format="json")
        search(scoped_db, "partition", output_format="json")
        stats(scoped_db, use_rich=False)
        capsys.readouterr()
        scoped_db.rollback()
        assert _raw_session_count(scoped_db_path) == TOTAL_STORED

    def test_the_row_is_still_readable_by_direct_sql(self, scoped_db):
        row = scoped_db.execute(
            "SELECT source FROM sessions WHERE id='sess-aider-004'"
        ).fetchone()
        assert row["source"] == "aider"


class TestPredicate:
    def test_visibility_sql_withholds_then_admits_on_request(self, scoped_db):
        hidden, params = visibility_sql(scoped_db, "s.id")
        rows = scoped_db.execute(
            "SELECT s.id FROM sessions s WHERE " + hidden, params
        ).fetchall()
        assert "sess-aider-004" not in {row["id"] for row in rows}

        scoped_db.rollback()
        shown, params = visibility_sql(scoped_db, "s.id", include_retired_sources=True)
        rows = scoped_db.execute(
            "SELECT s.id FROM sessions s WHERE " + shown, params
        ).fetchall()
        assert "sess-aider-004" in {row["id"] for row in rows}

    def test_message_column_form_is_scoped_too(self, scoped_db):
        visible, params = visibility_sql(scoped_db, "m.session_id")
        rows = scoped_db.execute(
            "SELECT m.session_id FROM messages m WHERE " + visible, params
        ).fetchall()
        assert "sess-aider-004" not in {row["session_id"] for row in rows}

    def test_forget_still_selects_a_retired_source(self, scoped_db):
        policy = ScopePolicy.from_config({"memory": {"default_scope": "unclassified"}})
        clause, params = retirement_selection_sql(
            scoped_db, policy=policy, scope=Scope.UNCLASSIFIED
        )
        rows = scoped_db.execute(
            "SELECT s.id FROM sessions s WHERE " + clause, params
        ).fetchall()
        assert "sess-aider-004" in {row["id"] for row in rows}


class TestMcpSurfaces:
    """The MCP tools are the other product read path onto the same predicate."""

    @pytest.fixture(autouse=True)
    def _require_fastmcp(self):
        pytest.importorskip("fastmcp", reason="fastmcp not installed")

    @staticmethod
    def _tools():
        from importlib import import_module

        from agent_session_tools.mcp_server import mcp

        run_async = import_module(
            f"{__package__}._helpers" if __package__ else "_helpers"
        ).run_async
        return {tool.name: tool.fn for tool in run_async(mcp._list_tools())}

    def test_session_list_hides_then_admits(self, scoped_db_path):
        with patch(
            "agent_session_tools.mcp_server._get_db_path", return_value=scoped_db_path
        ):
            tools = self._tools()
            default = {row["source"] for row in tools["session_list"]()}
            assert default == {"kiro_cli", "grok", "study_mentor"}
            named = tools["session_list"](source="aider")
            assert [row["id"] for row in named] == ["sess-aider-004"]

    def test_session_search_hides_then_admits(self, scoped_db_path):
        with patch(
            "agent_session_tools.mcp_server._get_db_path", return_value=scoped_db_path
        ):
            tools = self._tools()
            # "partition" is a shared token in every fixture body, so an empty
            # result would be a tokenizer artefact rather than proof of scoping.
            default = {
                row["source"]
                for row in tools["session_search"](query="partition")["rows"]
            }
            assert default == {"kiro_cli", "grok", "study_mentor"}
            named = tools["session_search"](query="partition", source="aider")["rows"]
            assert [row["session_id"] for row in named] == ["sess-aider-004"]

    def test_session_stats_reports_hidden_sources(self, scoped_db_path):
        with patch(
            "agent_session_tools.mcp_server._get_db_path", return_value=scoped_db_path
        ):
            report = self._tools()["session_stats"]()
        assert report["total_sessions"] == TOTAL_STORED - 1
        hidden = report["hidden_sources"]
        assert hidden["total_sessions"] == 1
        assert hidden["source_count"] == 1
        assert hidden["sources"] == [{"source": "aider", "count": 1}]
        assert hidden["note"] == "1 sessions in 1 retired sources (hidden, not deleted)"
        assert _raw_session_count(scoped_db_path) == TOTAL_STORED
