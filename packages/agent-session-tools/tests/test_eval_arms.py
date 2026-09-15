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
import os
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.skipif(
    not pytest.importorskip("fastmcp", reason="fastmcp not installed"),
    reason="fastmcp not installed",
)

from agent_session_tools import retrieval  # noqa: E402
from agent_session_tools.eval import arms as arms_module  # noqa: E402
from agent_session_tools.eval.arms import (  # noqa: E402
    ARMS,
    PLANNERS,
    CliArm,
    FrozenShippedArm,
    McpArm,
    _frozen_escape_fts_query,
    _split_payload,
    build_arm,
    frozen_session_search_queries,
    plan_and_first_unfiltered,
    plan_and_then_prose_or,
    plan_or_first_filtered,
    plan_or_only_unfiltered,
    split_arm_name,
)
from agent_session_tools.eval.seam import ArmError, Query  # noqa: E402
from agent_session_tools.query_planner import prose_or_query  # noqa: E402
from agent_session_tools.retrieval import plan_natural_language  # noqa: E402

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
    EXCLUDING = {"frozen", "mcp", "hybrid"}

    @pytest.mark.parametrize("name", sorted(ARMS))
    def test_every_registered_arm_builds_and_reports_its_name(self, name, eval_db):
        arm = build_arm(name, eval_db, rows=4)
        assert arm.name == name
        assert arm.supports_exclusion is (arm.name in self.EXCLUDING)
        assert arm.describe()["rows"] == 4

    def test_an_unknown_arm_is_refused(self, eval_db):
        with pytest.raises(ValueError, match="unknown arm"):
            build_arm("semantic", eval_db)


class TestPlannerVariants:
    """§5 (D-12): the planner axis is orthogonal to the transport axis.

    Each variant is a pure function standing in for
    ``retrieval.plan_natural_language``; the explicit door in ``plan_query`` is
    never substituted, so it is identical across variants by construction.
    """

    #: A sentence with stop words, a short token and one planted term.
    SENTENCE = f"is the {PLANTED} a spike"

    def test_the_five_planners_are_registered_and_shipped_substitutes_nothing(self):
        assert list(PLANNERS) == [
            "shipped",
            "or_first_filtered",
            "and_first_unfiltered",
            "or_only_unfiltered",
            "and_then_prose_or",
        ]
        assert PLANNERS["shipped"] is None
        assert all(callable(fn) for name, fn in PLANNERS.items() if name != "shipped")

    def test_or_first_filtered_is_the_shipped_or_form_alone(self):
        plan = plan_or_first_filtered(self.SENTENCE)
        assert plan.explicit is False
        assert plan.terms == (PLANTED, "spike")
        assert plan.queries == (f'"{PLANTED}" OR "spike"',)

    def test_and_first_unfiltered_keeps_every_raw_token(self):
        plan = plan_and_first_unfiltered(self.SENTENCE)
        assert plan.terms == ("is", "the", PLANTED, "a", "spike")
        assert plan.queries == (
            f'"is" AND "the" AND "{PLANTED}" AND "a" AND "spike"',
            f'"is" OR "the" OR "{PLANTED}" OR "a" OR "spike"',
        )

    def test_or_only_unfiltered_is_the_branch_function_verbatim(self):
        plan = plan_or_only_unfiltered(self.SENTENCE)
        assert plan.queries == (prose_or_query(self.SENTENCE),)
        assert plan.queries == (f'"is" OR "the" OR "{PLANTED}" OR "a" OR "spike"',)

    def test_the_candidate_keeps_the_shipped_and_arm_and_swaps_only_the_widen(self):
        shipped = plan_natural_language(self.SENTENCE)
        candidate = plan_and_then_prose_or(self.SENTENCE)
        assert candidate.terms == shipped.terms == (PLANTED, "spike")
        assert candidate.queries[0] == shipped.queries[0] == f'"{PLANTED}" AND "spike"'
        assert candidate.queries[1] == prose_or_query(self.SENTENCE)
        assert candidate.queries[1] != shipped.queries[1]
        assert len(candidate.queries) == 2

    def test_the_candidate_keeps_the_shipped_no_content_terms_return(self):
        """The widen is never reached without an AND arm in front of it."""
        shipped = plan_natural_language("what is the?")
        candidate = plan_and_then_prose_or("what is the?")
        assert candidate == shipped
        assert candidate.queries == ()
        assert candidate.note and "stop words" in candidate.note
        # The unfiltered arms DO search such a query: that is their hypothesis.
        assert plan_or_only_unfiltered("what is the?").queries == (
            '"what" OR "is" OR "the?"',
        )

    def test_the_candidate_deduplicates_when_the_widen_equals_the_and_arm(self):
        plan = plan_and_then_prose_or(PLANTED)
        assert plan.queries == (f'"{PLANTED}"',)

    def test_the_candidate_keeps_phrases_in_the_and_arm(self):
        plan = plan_and_then_prose_or('"error OR warning" recovery')
        assert plan.terms == ('"error OR warning"', "recovery")
        assert plan.queries == (
            '"error OR warning" AND "recovery"',
            '"""error" OR "OR" OR "warning""" OR "recovery"',
        )

    @pytest.mark.parametrize("name", [n for n in PLANNERS if n != "shipped"])
    def test_every_unfiltered_or_filtered_plan_is_never_explicit(self, name):
        variant = PLANNERS[name]
        assert variant is not None
        for query in ("fts:fts:alpha?", "alpha OR ?", 'NOT "x" AND', "???"):
            plan = variant(query)
            assert plan.explicit is False, (name, query)

    def test_split_arm_name(self):
        assert split_arm_name("mcp") == ("mcp", "shipped")
        assert split_arm_name("mcp:and_then_prose_or") == ("mcp", "and_then_prose_or")
        assert split_arm_name("hybrid:or_only_unfiltered") == (
            "hybrid",
            "or_only_unfiltered",
        )

    def test_build_arm_carries_the_variant_in_name_and_describe(self, eval_db):
        arm = build_arm("mcp:and_then_prose_or", eval_db, rows=4)
        assert isinstance(arm, McpArm)
        assert arm.name == "mcp:and_then_prose_or"
        assert arm.planner == "and_then_prose_or"
        assert arm.describe()["planner"] == "and_then_prose_or"
        assert arm.describe()["arm"] == "mcp:and_then_prose_or"
        assert build_arm("mcp:shipped", eval_db).name == "mcp"
        assert build_arm("mcp", eval_db).describe()["planner"] == "shipped"

    def test_an_unknown_planner_is_refused(self, eval_db):
        with pytest.raises(ValueError, match="unknown planner"):
            build_arm("mcp:plan_prose", eval_db)

    @pytest.mark.parametrize("transport", ["cli", "frozen", "cli-hybrid"])
    def test_out_of_process_and_control_arms_refuse_a_variant(self, transport, eval_db):
        with pytest.raises(ValueError, match="cannot take a planner variant"):
            build_arm(f"{transport}:and_then_prose_or", eval_db)

    def test_the_candidate_widens_through_the_real_tool_with_the_prose_or(
        self, eval_db
    ):
        """End to end: the AND arm finds nothing, the prose-OR widen runs, and
        ``retrieval_status.queries`` shows the substituted widen string."""
        shipped = McpArm(eval_db, rows=10)
        candidate = McpArm(eval_db, rows=10, planner="and_then_prose_or")
        query = Query(text=f"is {PLANTED} a quokkasaurus")

        shipped_ids = [hit.session_id for hit in shipped.search(query, 5)]
        assert shipped.last_status is not None
        assert shipped.last_status["plan"] == "or"
        assert shipped.last_status["queries"] == [
            f'"{PLANTED}" AND "quokkasaurus"',
            f'"{PLANTED}" OR "quokkasaurus"',
        ]

        candidate_ids = [hit.session_id for hit in candidate.search(query, 5)]
        assert candidate.last_status is not None
        assert candidate.last_status["plan"] == "or"
        assert candidate.last_status["widened"] is True
        assert candidate.last_status["terms"] == [PLANTED, "quokkasaurus"]
        assert candidate.last_status["queries"] == [
            f'"{PLANTED}" AND "quokkasaurus"',
            f'"is" OR "{PLANTED}" OR "a" OR "quokkasaurus"',
        ]
        assert "s-alpha" in candidate_ids
        assert shipped_ids == ["s-alpha"]

    def test_the_substitution_never_leaks_past_the_call(self, eval_db):
        before = retrieval.plan_natural_language
        McpArm(eval_db, planner="or_only_unfiltered").search(Query(text=PLANTED), 5)
        assert retrieval.plan_natural_language is before

    def test_the_explicit_door_is_identical_under_every_variant(self, eval_db):
        shipped = McpArm(eval_db, rows=10)
        expected = _ids(shipped, "percentile OR bootstrap")
        for name in PLANNERS:
            arm = McpArm(eval_db, rows=10, planner=name)
            assert _ids(arm, "percentile OR bootstrap") == expected, name
            assert arm.last_status is not None
            assert arm.last_status["plan"] == "explicit", name
            assert _ids(arm, "fts:percentile OR bootstrap") == expected, name


class TestPlannerIsolation:
    """Council review (GPT §3): the candidate's binding constraints, pinned one by one.

    The pre-registration binds the candidate to change *one thing* -- the widen
    string -- and binds the substitution to the natural-language entry only.
    Each test here is one of those bindings, stated against the code as it
    ran on 2026-09-15; none of them changed the code.
    """

    SENTENCE = f"is the {PLANTED} a spike"

    def test_candidate_preserves_and_terms_and_note(self):
        """Terms, the AND string and the note are the shipped planner's, verbatim."""
        for query in (
            self.SENTENCE,
            '"error OR warning" recovery',
            "what is the?",  # no content terms: the shipped note travels with it
            "___",  # a content term with no alphanumeric: shipped terms, empty widen
        ):
            shipped = plan_natural_language(query)
            candidate = plan_and_then_prose_or(query)
            assert candidate.explicit is shipped.explicit is False, query
            assert candidate.terms == shipped.terms, query
            assert candidate.note == shipped.note, query
            assert candidate.queries[:1] == shipped.queries[:1], query  # the AND arm
        assert plan_and_then_prose_or("what is the?").note is not None

    def test_candidate_empty_content_never_searches(self, eval_db, monkeypatch):
        """No content terms: the shipped ``plan=none`` return, and the widen is never built."""
        never = Mock(side_effect=AssertionError("the widen was built with no AND arm"))
        monkeypatch.setattr(arms_module, "prose_or_query", never)
        arm = McpArm(eval_db, rows=10, planner="and_then_prose_or")
        for text in ("what is the?", "is it", "   "):
            assert arm.search(Query(text=text), 5) == [], text
            assert arm.last_status is not None, text
            assert arm.last_status["plan"] == "none", text
            assert arm.last_status["queries"] == [], text
            assert arm.last_status["widened"] is False, text
        never.assert_not_called()

    def test_candidate_deduplicates_equal_queries(self):
        """One lowercase content token: AND string and prose widen coincide, one query runs."""
        assert plan_and_then_prose_or(PLANTED).queries == (f'"{PLANTED}"',)
        # Case is a real difference: the shipped arm lowercases, the prose widen does not.
        capitalised = PLANTED.capitalize()
        assert plan_and_then_prose_or(capitalised).queries == (
            f'"{PLANTED}"',
            f'"{capitalised}"',
        )
        # Whatever the input, a plan never tries the same string twice.
        for query in (PLANTED, capitalised, self.SENTENCE, "bm25 bm25", "___"):
            queries = plan_and_then_prose_or(query).queries
            assert len(queries) == len(set(queries)), query

    def test_candidate_empty_widen_is_dropped_not_searched(self):
        """A content term with no alphanumeric (``___``) is a shipped term the prose
        tokeniser drops: the widen string is empty, and an empty ``MATCH`` cannot run.

        The review asked whether any shipped-content input reaches this branch;
        these do. The shipped planner widens ``"---" AND "..."`` to its own OR
        form; the candidate has no widen string to try and stops at the AND arm.
        """
        assert prose_or_query("___") == ""
        assert plan_and_then_prose_or("___").queries == ('"___"',)
        shipped = plan_natural_language("--- ...")
        candidate = plan_and_then_prose_or("--- ...")
        assert shipped.queries == ('"---" AND "..."', '"---" OR "..."')
        assert candidate.terms == shipped.terms == ("---", "...")
        assert candidate.queries == ('"---" AND "..."',)

    def test_all_variants_bypass_planning_for_explicit_input(
        self, eval_db, monkeypatch
    ):
        """Explicit FTS5 never reaches a substituted planner: ``plan_query`` classifies
        first, and only natural language is handed on. Each variant is wrapped in a
        spy so the claim is "not called", not merely "same result"."""
        for name, variant in PLANNERS.items():
            if variant is None:
                continue
            spy = Mock(wraps=variant)
            monkeypatch.setitem(arms_module.PLANNERS, name, spy)
            arm = McpArm(eval_db, rows=10, planner=name)
            for text in (
                "percentile OR bootstrap",
                "fts:percentile OR bootstrap",
                '"exact phrase" OR authentication',
                "fts:",
            ):
                arm.search(Query(text=text), 5)
                assert arm.last_status is not None, (name, text)
                assert arm.last_status["plan"] in {"explicit", "none"}, (name, text)
            spy.assert_not_called()
            # The spy is live: natural language does reach it, once per call.
            arm.search(Query(text=PLANTED), 5)
            spy.assert_called_once_with(PLANTED)

    def test_rejected_explicit_syntax_is_replanned_by_the_planner_in_force(
        self, eval_db, monkeypatch
    ):
        """The one route from the explicit door to a planner: FTS5 rejects the
        explicit string and the service re-plans it as natural language. That
        re-plan goes through whichever natural-language planner is in force --
        the shipped one on the shipped arm, the variant on a variant arm -- so
        it is the same route under every arm, and the S.1 door tests (well-formed
        explicit input) are unaffected. Recorded here so the boundary is written
        down rather than assumed."""
        spy = Mock(wraps=plan_and_then_prose_or)
        monkeypatch.setitem(arms_module.PLANNERS, "and_then_prose_or", spy)
        arm = McpArm(eval_db, rows=10, planner="and_then_prose_or")
        arm.search(
            Query(text=f"{PLANTED} OR"), 5
        )  # a trailing operator: explicit, rejected
        assert arm.last_status is not None
        assert arm.last_status["note"] and "rejected" in arm.last_status["note"]
        spy.assert_called_once_with(f"{PLANTED} OR")

    def test_planner_patch_restored_after_tool_error(self, eval_db, monkeypatch):
        """A transport failure inside the patched call restores the module attribute
        and the environment, so the next arm -- shipped included -- plans as itself."""
        before = retrieval.plan_natural_language
        mode_before = os.environ.get("STUDYLOOP_RETRIEVAL_MODE")
        arm = McpArm(eval_db, rows=10, planner="and_then_prose_or")

        def explode(coro):
            coro.close()  # the coroutine is never awaited; do not warn about it
            raise RuntimeError("tool transport failed")

        monkeypatch.setattr(arms_module, "_run", explode)
        with pytest.raises(ArmError) as raised:
            arm.search(Query(text=PLANTED), 5)
        assert raised.value.kind == "other"
        assert "tool transport failed" in str(raised.value)
        assert retrieval.plan_natural_language is before
        assert os.environ.get("STUDYLOOP_RETRIEVAL_MODE") == mode_before
        monkeypatch.undo()

        shipped = McpArm(eval_db, rows=10)
        assert _ids(shipped, f"is {PLANTED} a quokkasaurus") == ["s-alpha"]
        assert shipped.last_status is not None
        assert shipped.last_status["queries"] == [
            f'"{PLANTED}" AND "quokkasaurus"',
            f'"{PLANTED}" OR "quokkasaurus"',  # the shipped widen, not the prose one
        ]
