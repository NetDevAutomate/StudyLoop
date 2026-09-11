"""The three arms, driven end-to-end against a temporary database.

The database is built the way the package builds one -- ``schema.sql`` plus
``migrations.migrate`` -- so the FTS5 table, its tokenizer and the scope
tables are the real ones and not hand-written DDL that could drift.

Three claims here are load-bearing for the whole harness:

* the MCP arm now *answers* a question that mixes ``and`` with a backtick --
  the phrasing that made 42 of 91 gold questions unanswerable -- and returns a
  ``retrieval_status`` saying how it searched;
* the frozen arm still crashes on that same question, byte-identically to the
  path stage 1 shipped, which is what keeps it usable as the control;
* the frozen planner reproduces ``golden/frozen_planner_pins.json`` exactly.
  That fixed table replaced an equality test against
  ``mcp_server._session_search_queries``, which no longer exists: the live
  planner changed by design, so comparing against it would fail for the right
  reason and prove nothing about the control staying frozen.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    not pytest.importorskip("fastmcp", reason="fastmcp not installed"),
    reason="fastmcp not installed",
)

from agent_session_tools.eval import arms as arms_module  # noqa: E402
from agent_session_tools.eval.arms import (  # noqa: E402
    ARMS,
    CliArm,
    FrozenShippedArm,
    McpArm,
    _frozen_escape_fts_query,
    _split_payload,
    build_arm,
    frozen_session_search_queries,
)
from agent_session_tools.eval.seam import ArmError, Query  # noqa: E402

SESSIONS = ("s-alpha", "s-beta", "s-gamma", "s-delta")
#: A nonsense token planted in one session only, so a hit is unambiguous.
PLANTED = "zebracorn"
#: The phrasing stage 1 could not survive: a lowercase ``and`` was read as an
#: FTS5 operator, so the backtick reached ``MATCH`` unescaped.
CRASHING_QUESTION = f"what does the `{PLANTED}` retrieval spike do and why"
#: The fixed table that keeps the frozen control frozen.
PINS_PATH = Path(__file__).parent / "golden" / "frozen_planner_pins.json"
#: The ten inputs the deleted ``_session_search_queries`` equality test used.
#: They must stay in the pin table, alongside every gold DEV question.
STAGE1_PIN_INPUTS = (
    PLANTED,
    "bootstrap resampling",
    "authentication middleware",
    "percentile OR bootstrap",
    "quokkasaurus",
    "what does `plan` do and why",
    "why? what happens",
    '"an exact phrase"',
    "a and b",
    "of the",
)


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

    def test_it_carries_the_rows_real_message_id_not_a_synthesised_one(self, eval_db):
        """The citation handle the census excludes by must be the row's own id.

        The fixture's message ids are ``m-1``..``m-10``; a synthesised id would
        read ``s-alpha#0:2026-01-01T10:01:00``.
        """
        hits = McpArm(eval_db, rows=10).search(Query(text=PLANTED), 5)
        assert hits[0].message_ids == ("m-1",)

    def test_a_question_with_and_plus_a_backtick_is_answered_not_crashed(self, eval_db):
        """Stage 2's whole point: this phrasing used to raise, and now answers.

        Stage 1 read the lowercase ``and`` as explicit FTS5 syntax, so the
        backtick reached ``MATCH`` unescaped and sqlite raised. The retrieval
        service plans the sentence into quoted terms instead.
        """
        arm = McpArm(eval_db, rows=10)
        hits = arm.search(Query(text=CRASHING_QUESTION), 5)
        assert [hit.session_id for hit in hits] == ["s-alpha"]
        assert arm.last_status is not None
        assert arm.last_status["mode"] == "lexical"
        assert arm.last_status["plan"] in {"and", "or"}

    def test_it_reports_the_retrieval_status_of_an_empty_result(self, eval_db):
        arm = McpArm(eval_db)
        assert arm.search(Query(text="quokkasaurus"), 5) == []
        assert arm.last_status is not None
        assert arm.last_status["queries"]  # "no rows" is never silent

    def test_sessions_are_distinct_and_capped_at_k(self, eval_db):
        # "the" is a stop word for the planner but every session matches
        # something in this corpus; k must still bound the sessions returned.
        hits = McpArm(eval_db, rows=10).search(Query(text="percentile OR bootstrap"), 2)
        assert len(hits) <= 2
        assert len({hit.session_id for hit in hits}) == len(hits)

    def test_it_excludes_a_message_id_inside_the_tool(self, eval_db):
        """The census gate: self-exclusion must happen in the tool's own SQL."""
        arm = McpArm(eval_db, rows=10)
        assert arm.supports_exclusion is True
        excluded = Query(text=PLANTED, exclude_message_ids=frozenset({"m-1"}))
        assert arm.search(excluded, 5) == []

    def test_it_drops_an_excluded_session_before_collapsing(self, eval_db):
        arm = McpArm(eval_db, rows=10)
        excluded = Query(text=PLANTED, exclude_session_ids=frozenset({"s-alpha"}))
        assert arm.search(excluded, 5) == []

    def test_a_tool_without_the_exclusion_argument_defers_to_the_ruler(
        self, eval_db, monkeypatch
    ):
        """Against the pre-stage-2 tool the flag is False and nothing is passed.

        The argument list is read from the tool's input schema at construction,
        so an older server is detected before the first query rather than by
        provoking a validation error and classifying the wreckage.
        """
        monkeypatch.setattr(
            arms_module,
            "_tool_argument_names",
            lambda _name: frozenset({"query", "limit", "source", "project"}),
        )
        arm = McpArm(eval_db, rows=10)
        assert arm.supports_exclusion is False
        # The tool cannot filter, so the arm must not pre-empt the ruler either.
        excluded = Query(text=PLANTED, exclude_message_ids=frozenset({"m-1"}))
        assert [hit.session_id for hit in arm.search(excluded, 5)] == ["s-alpha"]

    def test_describe_records_rows_db_commit_and_exclusion_support(self, eval_db):
        described = McpArm(eval_db, rows=7).describe()
        assert described["rows"] == 7
        assert described["db_path"] == str(eval_db)
        assert isinstance(described["git_commit"], str)
        assert described["supports_exclusion"] is True


class TestPayloadShapes:
    """Both payload shapes, because the harness must run either side of stage 2."""

    def test_the_service_payload_yields_rows_and_status(self):
        payload: dict[str, Any] = {
            "rows": [{"session_id": "s1", "message_id": "m1"}],
            "retrieval_status": {"mode": "lexical", "plan": "and"},
        }
        rows, status = _split_payload(payload)
        assert rows == [{"session_id": "s1", "message_id": "m1"}]
        assert status == {"mode": "lexical", "plan": "and"}

    def test_a_fastmcp_wrapped_list_is_the_pre_stage_2_tool(self):
        """FastMCP returns a ``dict`` as-is but wraps a ``list`` under "result"."""
        rows, status = _split_payload({"result": [{"session_id": "s1"}]})
        assert rows == [{"session_id": "s1"}]
        assert status is None

    def test_a_bare_list_is_the_pre_stage_2_cli(self):
        rows, status = _split_payload([{"session_id": "s1"}])
        assert rows == [{"session_id": "s1"}]
        assert status is None

    @pytest.mark.parametrize(
        "payload", [None, "text", 7, {"rows": "not a list"}, [1, 2, 3]]
    )
    def test_an_unreadable_payload_is_empty_not_an_exception(self, payload):
        assert _split_payload(payload) == ([], None)


class TestFrozenShippedArm:
    QUERIES = (
        PLANTED,
        "bootstrap resampling",
        "authentication middleware",
        "percentile OR bootstrap",
        "quokkasaurus",
    )

    def test_it_agrees_with_the_fixed_path_on_queries_stage_1_could_answer(
        self, eval_db
    ):
        """The fix must add answers, not move the ones stage 1 already got right.

        These five carry no lowercase operator and no punctuation, so stage 1's
        planner and the retrieval service plan them identically; any divergence
        here would be a regression rather than the intended repair.
        """
        mcp, frozen = McpArm(eval_db, rows=10), FrozenShippedArm(eval_db, rows=10)
        for text in self.QUERIES:
            assert _ids(frozen, text) == _ids(mcp, text), text

    def test_it_still_crashes_the_way_the_shipped_path_used_to(self, eval_db):
        """The control keeps the defect. This is what stage 2 is measured against."""
        for text in (CRASHING_QUESTION, "what does `plan` do and why"):
            with pytest.raises(ArmError) as raised:
                FrozenShippedArm(eval_db).search(Query(text=text), 5)
            assert raised.value.kind == "backtick", text

    def test_describe_names_the_freeze(self, eval_db):
        described = FrozenShippedArm(eval_db).describe()
        assert "frozen" in str(described["interface"])
        assert described["frozen_at"]


class TestFrozenPlannerPins:
    """The fixed table that keeps the stage-1 control frozen forever.

    It replaced an equality test against ``mcp_server._session_search_queries``,
    which stage 2 deleted. The pins were generated from that shipped helper at
    79425cbe, so the table *is* stage-1 behaviour -- recorded rather than
    recomputed, and importing nothing from ``mcp_server``.
    """

    def test_the_frozen_planner_reproduces_the_pins_byte_for_byte(self):
        recorded = json.loads(PINS_PATH.read_text(encoding="utf-8"))
        rebuilt = dict(recorded)
        rebuilt["pins"] = [
            {
                "query": pin["query"],
                "frozen_queries": list(frozen_session_search_queries(pin["query"])),
                "escaped": _frozen_escape_fts_query(pin["query"]),
            }
            for pin in recorded["pins"]
        ]
        expected = json.dumps(rebuilt, indent=2, ensure_ascii=False) + "\n"
        assert expected == PINS_PATH.read_text(encoding="utf-8")

    def test_the_table_still_covers_what_it_claims_to(self):
        """A shrunken table would pass the byte comparison and pin nothing."""
        recorded = json.loads(PINS_PATH.read_text(encoding="utf-8"))
        queries = [pin["query"] for pin in recorded["pins"]]
        assert len(queries) == len(set(queries)) == 96
        assert recorded["sources"]["gold_dev_items"] == 91
        assert set(STAGE1_PIN_INPUTS) <= set(queries)

    def test_the_pins_record_the_defect_the_control_exists_to_preserve(self):
        """The backtick sentence must be pinned as raw, unescaped passthrough."""
        recorded = json.loads(PINS_PATH.read_text(encoding="utf-8"))
        pin = next(
            p for p in recorded["pins"] if p["query"] == "what does `plan` do and why"
        )
        assert pin["frozen_queries"] == ["what does `plan` do and why"]


class TestCliArm:
    def test_it_finds_the_planted_keyword(self, eval_db):
        arm = CliArm(eval_db, rows=10)
        if not arm.available:
            pytest.skip(f"{arm.invocation} is not available on PATH")
        assert _ids(arm, PLANTED) == ["s-alpha"]

    def test_it_reads_the_rows_key_and_the_retrieval_status(self, eval_db):
        """The CLI prints the service payload, and its rows carry real ids."""
        arm = CliArm(eval_db, rows=10)
        if not arm.available:
            pytest.skip(f"{arm.invocation} is not available on PATH")
        hits = arm.search(Query(text=PLANTED), 5)
        assert [hit.session_id for hit in hits] == ["s-alpha"]
        assert hits[0].message_ids == ("m-1",)
        assert arm.last_status is not None
        assert arm.last_status["mode"] == "lexical"

    def test_a_backticked_question_is_answered_not_crashed(self, eval_db):
        arm = CliArm(eval_db, rows=10)
        if not arm.available:
            pytest.skip(f"{arm.invocation} is not available on PATH")
        assert _ids(arm, CRASHING_QUESTION) == ["s-alpha"]

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
    #: The arms that filter inside the engine rather than leaving it to the ruler:
    #: the frozen replica's ``NOT IN`` clauses, and the tool's own
    #: ``exclude_message_ids``. The CLI still has no such flag.
    EXCLUDING = {"frozen", "mcp"}

    @pytest.mark.parametrize("name", sorted(ARMS))
    def test_every_registered_arm_builds_and_reports_its_name(self, name, eval_db):
        arm = build_arm(name, eval_db, rows=4)
        assert arm.name == name
        assert arm.supports_exclusion is (arm.name in self.EXCLUDING)
        assert arm.describe()["rows"] == 4

    def test_an_unknown_arm_is_refused(self, eval_db):
        with pytest.raises(ValueError, match="unknown arm"):
            build_arm("semantic", eval_db)
