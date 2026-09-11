"""The three arms, driven end-to-end against a temporary database.

The database is built the way the package builds one -- ``schema.sql`` plus
``migrations.migrate`` -- so the FTS5 table, its tokenizer and the scope
tables are the real ones and not hand-written DDL that could drift.

Two claims here are load-bearing for the whole stage:

* the MCP arm crashes on a question that mixes ``and`` with a backtick, which
  is what makes 42 of 91 gold questions unanswerable today;
* the frozen arm returns exactly what the MCP arm returns, which is what
  makes it usable as a control after the shipped path is fixed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not pytest.importorskip("fastmcp", reason="fastmcp not installed"),
    reason="fastmcp not installed",
)

from agent_session_tools.eval.arms import (  # noqa: E402
    ARMS,
    CliArm,
    FrozenShippedArm,
    McpArm,
    build_arm,
    frozen_session_search_queries,
)
from agent_session_tools.eval.seam import ArmError, Query  # noqa: E402

SESSIONS = ("s-alpha", "s-beta", "s-gamma", "s-delta")
#: A nonsense token planted in one session only, so a hit is unambiguous.
PLANTED = "zebracorn"


@pytest.fixture
def eval_db(tmp_path: Path) -> Path:
    """Four sessions, ten messages, built through the package's own schema."""
    db_path = tmp_path / "eval.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    schema = Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    conn.executescript(schema.read_text())

    from agent_session_tools.migrations import migrate

    migrate(conn)

    for index, session_id in enumerate(SESSIONS, start=1):
        conn.execute(
            "INSERT INTO sessions (id, source, project_path, git_branch, "
            "created_at, updated_at, session_type) VALUES (?,?,?,?,?,?,?)",
            (
                session_id,
                "claude_code",
                f"/projects/{session_id}",
                "main",
                f"2026-01-0{index}T10:00:00",
                f"2026-01-0{index}T12:00:00",
                "work",
            ),
        )
    bodies = [
        ("s-alpha", f"The {PLANTED} retrieval spike lives in the planner."),
        ("s-alpha", "Authentication middleware rejected the expired token."),
        ("s-beta", "We tuned bm25 weights for the message index."),
        ("s-beta", "The migration renamed the sessions table primary key."),
        ("s-gamma", "Latency percentiles moved after the vacuum ran."),
        ("s-gamma", "Cluster bootstrap resampling needs a fixed seed."),
        ("s-delta", "Scope visibility hides retired harness labels."),
        ("s-delta", "The census pairs paraphrases against their own turns."),
        ("s-alpha", "Percentile intervals widened once clusters shrank."),
        ("s-beta", "Token budget trimming dropped the oldest excerpt."),
    ]
    for seq, (session_id, content) in enumerate(bodies, start=1):
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
            "VALUES (?,?,?,?,?,?)",
            (
                f"m-{seq}",
                session_id,
                "user" if seq % 2 else "assistant",
                content,
                f"2026-01-01T10:{seq:02d}:00",
                seq,
            ),
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(autouse=True)
def unclassified_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A hermetic config: the arms must never read the developer's own scope."""
    config = tmp_path / "config.yaml"
    config.write_text(json.dumps({"memory": {"default_scope": "unclassified"}}))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    return config


def _ids(arm, text: str, k: int = 5) -> list[str]:
    return [hit.session_id for hit in arm.search(Query(text=text), k)]


class TestMcpArm:
    def test_it_finds_the_planted_keyword_through_the_real_tool(self, eval_db):
        arm = McpArm(eval_db, rows=10)
        hits = arm.search(Query(text=PLANTED), 5)
        assert [hit.session_id for hit in hits] == ["s-alpha"]
        assert hits[0].method == "mcp"
        assert hits[0].message_ids  # the evidence that ranked it is carried

    def test_a_question_with_and_plus_a_backtick_crashes_today(self, eval_db):
        """Stage 2 flips this: the fixed lexical path must answer this question.

        ``and`` makes ``_session_search_queries`` treat the text as explicit
        FTS syntax, so the backtick reaches FTS5 unescaped and sqlite raises.
        """
        arm = McpArm(eval_db, rows=10)
        with pytest.raises(ArmError) as raised:
            arm.search(Query(text="what does `plan` do and why"), 5)
        assert raised.value.kind == "backtick"

    def test_an_unmatched_query_is_empty_not_an_error(self, eval_db):
        assert McpArm(eval_db).search(Query(text="quokkasaurus"), 5) == []

    def test_sessions_are_distinct_and_capped_at_k(self, eval_db):
        # "the" is a stop word for the planner but every session matches
        # something in this corpus; k must still bound the sessions returned.
        hits = McpArm(eval_db, rows=10).search(Query(text="percentile OR bootstrap"), 2)
        assert len(hits) <= 2
        assert len({hit.session_id for hit in hits}) == len(hits)

    def test_describe_records_rows_db_and_commit(self, eval_db):
        described = McpArm(eval_db, rows=7).describe()
        assert described["rows"] == 7
        assert described["db_path"] == str(eval_db)
        assert isinstance(described["git_commit"], str)


class TestFrozenShippedArm:
    QUERIES = (
        PLANTED,
        "bootstrap resampling",
        "authentication middleware",
        "percentile OR bootstrap",
        "quokkasaurus",
    )

    def test_it_returns_exactly_what_the_mcp_arm_returns(self, eval_db):
        mcp, frozen = McpArm(eval_db, rows=10), FrozenShippedArm(eval_db, rows=10)
        for text in self.QUERIES:
            assert _ids(frozen, text) == _ids(mcp, text), text

    def test_it_crashes_the_same_way_the_shipped_path_does(self, eval_db):
        with pytest.raises(ArmError) as raised:
            FrozenShippedArm(eval_db).search(
                Query(text="what does `plan` do and why"), 5
            )
        assert raised.value.kind == "backtick"

    def test_the_frozen_planner_matches_the_shipped_planner_today(self):
        from agent_session_tools.mcp_server import _session_search_queries

        for text in (
            *TestFrozenShippedArm.QUERIES,
            "what does `plan` do and why",
            "why? what happens",
            '"an exact phrase"',
            "a and b",
            "of the",
        ):
            assert frozen_session_search_queries(text) == _session_search_queries(
                text
            ), text

    def test_describe_names_the_freeze(self, eval_db):
        described = FrozenShippedArm(eval_db).describe()
        assert "frozen" in str(described["interface"])
        assert described["frozen_at"]


class TestCliArm:
    def test_it_finds_the_planted_keyword(self, eval_db):
        arm = CliArm(eval_db, rows=10)
        if not arm.available:
            pytest.skip(f"{arm.invocation} is not available on PATH")
        assert _ids(arm, PLANTED) == ["s-alpha"]

    def test_a_two_word_natural_question_is_empty_not_an_error(self, eval_db):
        arm = CliArm(eval_db, rows=10)
        if not arm.available:
            pytest.skip(f"{arm.invocation} is not available on PATH")
        assert arm.search(Query(text="quokkasaurus platypodes"), 5) == []

    def test_describe_records_the_invocation_it_resolved(self, eval_db):
        described = CliArm(eval_db, rows=3).describe()
        assert described["rows"] == 3
        assert "search" in str(described["interface"])


class TestRegistry:
    @pytest.mark.parametrize("name", sorted(ARMS))
    def test_every_registered_arm_builds_and_reports_its_name(self, name, eval_db):
        arm = build_arm(name, eval_db, rows=4)
        assert arm.name == name
        assert arm.supports_exclusion is False
        assert arm.describe()["rows"] == 4

    def test_an_unknown_arm_is_refused(self, eval_db):
        with pytest.raises(ValueError, match="unknown arm"):
            build_arm("semantic", eval_db)
