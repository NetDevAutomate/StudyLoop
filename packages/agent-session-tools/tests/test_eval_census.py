"""Hermetic tests for the paraphrase census adapter over ``sessions.db``.

No model, no live database, no network: a temporary ``sessions.db`` is built
through the package's own schema and migrations (never hand-written DDL), and
the arm is a fake :class:`~agent_session_tools.eval.seam.Retriever` returning
planted rankings so every number the census reports is checked against a shape
the test authored.

The planted population, all of it in admitted sources so the scope predicate
keeps it, plus two rows it must withhold:

* ``sess-alpha`` -- question ``Q1`` plus an assistant answer that reuses most of
  ``Q1``'s content words (a high-overlap question);
* ``sess-beta`` -- ``Q1`` again, verbatim: alpha's one twin;
* ``sess-twin-1 .. sess-twin-8`` -- ``Q2`` verbatim in eight sessions, so each
  copy has seven twins and ``twins + 1 = 8 > 5`` makes it unwinnable at K=5;
* ``sess-island`` -- a question whose words appear nowhere else in its session
  (overlap 0.0, so a miss must be classed ``vocabulary_gap``);
* ``sess-hidden`` -- source ``aider``, a retired harness label the visibility
  predicate withholds: its question must never be collected;
* ``agent-sess-bot`` -- an agent-driven session id, excluded by the same rule
  the original census used.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.eval import K
from agent_session_tools.eval.census import (
    MAX_WORDS,
    CensusQuestion,
    census_receipt,
    collect_questions,
    content_tokens,
    run_census,
)
from agent_session_tools.eval.seam import ArmError, Hit, Query

Q1 = "How does the retriever planner escape a backtick in the phrase query?"
Q1_ANSWER = (
    "The planner escapes a backtick by quoting the phrase before the query "
    "reaches the retriever, so a stray backtick never terminates the token."
)
Q2 = "Why did the semantic arm regress after the embedding cache was rebuilt?"
ISLAND_Q = "Which vegetables belong in the allotment rotation next spring?"
ISLAND_OTHER = "Kubernetes ingress controllers terminate TLS at the edge."
TWIN_SESSIONS = tuple(f"sess-twin-{n}" for n in range(1, 9))


def _add_session(
    conn: sqlite3.Connection, session_id: str, source: str = "kiro_cli"
) -> None:
    conn.execute(
        "INSERT INTO sessions (id, source, project_path, git_branch, created_at, updated_at) "
        "VALUES (?, ?, '/projects/studyloop', 'main', "
        "'2026-01-01T10:00:00', '2026-01-01T12:00:00')",
        (session_id, source),
    )


def _add_message(
    conn: sqlite3.Connection,
    message_id: str,
    session_id: str,
    role: str,
    content: str,
    seq: int = 1,
) -> None:
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp, seq) "
        "VALUES (?, ?, ?, ?, '2026-01-01T10:00:00', ?)",
        (message_id, session_id, role, content, seq),
    )


@pytest.fixture
def census_db(tmp_path: Path) -> sqlite3.Connection:
    """A temporary ``sessions.db`` carrying the planted census population."""
    db_path = tmp_path / "census.db"
    conn = sqlite3.connect(db_path)
    schema = (
        Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    ).read_text()
    conn.executescript(schema)
    from agent_session_tools.migrations import migrate

    migrate(conn)

    _add_session(conn, "sess-alpha")
    _add_message(conn, "m-alpha-q", "sess-alpha", "user", Q1, 1)
    _add_message(conn, "m-alpha-a", "sess-alpha", "assistant", Q1_ANSWER, 2)

    _add_session(conn, "sess-beta", source="claude_code")
    _add_message(conn, "m-beta-q", "sess-beta", "user", Q1, 1)
    _add_message(
        conn, "m-beta-a", "sess-beta", "assistant", "Quote the phrase first.", 2
    )

    for n, session_id in enumerate(TWIN_SESSIONS, 1):
        _add_session(conn, session_id)
        _add_message(conn, f"m-twin-{n}-q", session_id, "user", Q2, 1)
        _add_message(
            conn,
            f"m-twin-{n}-a",
            session_id,
            "assistant",
            "The embedding cache rebuild changed the semantic arm's neighbours.",
            2,
        )

    _add_session(conn, "sess-island")
    _add_message(conn, "m-island-q", "sess-island", "user", ISLAND_Q, 1)
    _add_message(conn, "m-island-a", "sess-island", "assistant", ISLAND_OTHER, 2)

    # Ineligible: too short (fewer than three content tokens) and pasted material.
    _add_session(conn, "sess-edges")
    _add_message(conn, "m-edge-short", "sess-edges", "user", "ok thanks", 1)
    _add_message(
        conn,
        "m-edge-pasted",
        "sess-edges",
        "user",
        " ".join(f"traceback-line-{n}" for n in range(MAX_WORDS + 5)),
        2,
    )
    _add_message(conn, "m-edge-a", "sess-edges", "assistant", "Noted.", 3)

    # Withheld: a retired harness label, and an agent-driven session id.
    _add_session(conn, "sess-hidden", source="aider")
    _add_message(conn, "m-hidden-q", "sess-hidden", "user", Q1, 1)
    _add_session(conn, "agent-sess-bot")
    _add_message(conn, "m-agent-q", "agent-sess-bot", "user", Q1, 1)

    conn.commit()
    return conn


class FakeArm:
    """An exclusion-capable arm returning rankings the test planted.

    ``supports_exclusion = True``: like the frozen arm's ``NOT IN`` clauses, it
    drops the query's excluded message ids and sessions itself, which is the
    only kind of arm a self-retrieval census may run through (the census
    refuses the other kind -- see :class:`NoExclusionArm`).
    """

    name = "fake"
    supports_exclusion = True

    def __init__(
        self,
        rankings: dict[str, list[tuple[str, str]]] | None = None,
        *,
        crash_on: str | None = None,
    ) -> None:
        self.rankings = rankings or {}
        self.crash_on = crash_on
        self.calls: list[tuple[Query, int]] = []

    def search(self, query: Query, k: int) -> list[Hit]:
        self.calls.append((query, k))
        if self.crash_on is not None and self.crash_on in query.text:
            raise ArmError("backtick", "fts5: unterminated ` in query")
        ranked = [
            (session_id, message_id)
            for session_id, message_id in self.rankings.get(query.text, [])
            if message_id not in query.exclude_message_ids
            and session_id not in query.exclude_session_ids
        ]
        return [
            Hit(session_id, (message_id,), None, "fake")
            for session_id, message_id in ranked
        ][:k]

    def describe(self) -> dict[str, object]:
        return {"arm": "fake", "planted": len(self.rankings)}


class NoExclusionArm(FakeArm):
    """What the shipped MCP tool is today: no message ids, no way to exclude."""

    name = "no-exclusion"
    supports_exclusion = False


def _by_id(questions: list[CensusQuestion]) -> dict[str, CensusQuestion]:
    return {question.message_id: question for question in questions}


def test_collect_questions_applies_eligibility_and_withholds_hidden_sessions(census_db):
    questions = collect_questions(census_db)
    by_id = _by_id(questions)

    # Eight Q2 copies + two Q1 copies + the island question.
    assert len(questions) == 11
    assert "m-alpha-q" in by_id
    assert "m-beta-q" in by_id
    assert "m-island-q" in by_id
    # A retired source label and an agent-driven session are never questions.
    assert "m-hidden-q" not in by_id
    assert "m-agent-q" not in by_id
    # Under three content tokens, and over MAX_WORDS.
    assert "m-edge-short" not in by_id
    assert "m-edge-pasted" not in by_id
    assert by_id["m-alpha-q"].source == "kiro_cli"
    assert by_id["m-beta-q"].source == "claude_code"


def test_twins_count_other_visible_sessions_only(census_db):
    by_id = _by_id(collect_questions(census_db))

    # Q1 lives in alpha and beta only: the hidden-source and agent copies do not
    # count, so one twin each, and both stay winnable at K=5.
    assert by_id["m-alpha-q"].twins == 1
    assert by_id["m-beta-q"].twins == 1
    assert by_id["m-alpha-q"].tied(K) is False

    # Q2 lives in eight sessions: seven twins each, 7 + 1 > 5.
    assert by_id["m-twin-1-q"].twins == 7
    assert all(by_id[f"m-twin-{n}-q"].tied(K) is True for n in range(1, 9))
    assert by_id["m-twin-1-q"].tied(7) is True
    assert by_id["m-twin-1-q"].tied(8) is False

    # A question with no twin is winnable at any k >= 1.
    assert by_id["m-island-q"].twins == 0
    assert by_id["m-island-q"].tied(1) is False


def test_whitespace_normalised_text_still_counts_as_a_twin(census_db):
    _add_session(census_db, "sess-gamma")
    _add_message(
        census_db, "m-gamma-q", "sess-gamma", "user", Q1.replace(" ", "\n  "), 1
    )
    census_db.commit()

    by_id = _by_id(collect_questions(census_db))
    assert by_id["m-alpha-q"].twins == 2
    assert by_id["m-gamma-q"].twins == 2


def test_overlap_uses_other_prose_and_excludes_identical_reasks(census_db):
    questions = collect_questions(census_db)
    result = run_census(census_db, FakeArm(), questions, k=K)
    rows = {row.message_id: row for row in result.rows}

    # Alpha's answer reuses most of Q1's content words, so overlap is high but
    # the verbatim twin in another session cannot contribute to it.
    assert rows["m-alpha-q"].overlap > 0.5
    assert rows["m-alpha-q"].overlap < 1.0
    # Beta's only other prose is a short reply, so its overlap is lower.
    assert rows["m-beta-q"].overlap < rows["m-alpha-q"].overlap
    # The island question's words appear nowhere else in its session.
    assert rows["m-island-q"].overlap == 0.0


def test_a_lone_question_whose_only_prose_is_itself_has_zero_overlap(census_db):
    _add_session(census_db, "sess-lonely")
    _add_message(
        census_db, "m-lonely-q", "sess-lonely", "user", "profiling the arrow writer", 1
    )
    _add_message(
        census_db, "m-lonely-q2", "sess-lonely", "user", "profiling the arrow writer", 2
    )
    census_db.commit()

    questions = [
        q for q in collect_questions(census_db) if q.session_id == "sess-lonely"
    ]
    result = run_census(census_db, FakeArm(), questions, k=K)

    # Both rows are identical re-asks of each other, so subtracting the self rows
    # leaves no other prose message holding any of the tokens.
    assert [row.overlap for row in result.rows] == [0.0, 0.0]


def test_zero_overlap_miss_is_a_vocabulary_gap_and_a_worded_miss_is_ranking(census_db):
    questions = collect_questions(census_db)
    result = run_census(census_db, FakeArm(), questions, k=K)
    rows = {row.message_id: row for row in result.rows}

    assert rows["m-island-q"].hit is False
    assert rows["m-island-q"].miss_class == "vocabulary_gap"
    assert rows["m-alpha-q"].miss_class == "ranking"
    assert result.miss_vocab == 1
    assert result.miss_ranking == len(questions) - 1
    assert result.hits == 0


def test_own_message_is_excluded_at_query_time_so_the_session_drops_out(census_db):
    """The arm ranks alpha's own question first; the census must not count it."""
    arm = FakeArm({Q1: [("sess-alpha", "m-alpha-q"), ("sess-beta", "m-beta-q")]})
    questions = [q for q in collect_questions(census_db) if q.message_id == "m-alpha-q"]
    result = run_census(census_db, arm, questions, k=K)

    query, requested = arm.calls[0]
    assert requested == K
    assert query.exclude_message_ids == frozenset({"m-alpha-q"})
    row = result.rows[0]
    assert row.hit is False
    assert row.miss_class == "ranking"


def test_the_own_session_reached_through_another_message_is_a_hit(census_db):
    arm = FakeArm({Q1: [("sess-beta", "m-beta-q"), ("sess-alpha", "m-alpha-a")]})
    questions = [q for q in collect_questions(census_db) if q.message_id == "m-alpha-q"]
    result = run_census(census_db, arm, questions, k=K)

    assert result.rows[0].hit is True
    assert result.rows[0].rank == 2
    assert result.rows[0].miss_class is None
    assert result.hits == 1


def test_identical_reasks_in_the_same_session_are_excluded_too(census_db):
    _add_message(census_db, "m-alpha-q2", "sess-alpha", "user", Q1, 3)
    census_db.commit()
    arm = FakeArm({Q1: [("sess-alpha", "m-alpha-q2")]})
    questions = [q for q in collect_questions(census_db) if q.message_id == "m-alpha-q"]
    result = run_census(census_db, arm, questions, k=K)

    query, _ = arm.calls[0]
    assert query.exclude_message_ids == frozenset({"m-alpha-q", "m-alpha-q2"})
    assert result.rows[0].hit is False


def test_ceiling_arithmetic_counts_unwinnable_twins_out_of_the_denominator(census_db):
    # One winnable hit (alpha via its assistant message) and one lucky hit on an
    # unwinnable twin question.
    arm = FakeArm(
        {
            Q1: [("sess-alpha", "m-alpha-a")],
            Q2: [("sess-twin-1", "m-twin-1-a")],
        }
    )
    questions = collect_questions(census_db)
    result = run_census(census_db, arm, questions, k=K)

    assert result.n_eligible == 11
    assert result.n_tied == 8
    assert result.untied_share == pytest.approx(3 / 11)
    # alpha hits; among the twins only sess-twin-1 gets its own session back.
    assert result.hits == 2
    assert result.hit_rate == pytest.approx(2 / 11)
    # The twin hit is luck on an unwinnable question: reported, never credited.
    assert result.hits_tied == 1
    assert result.hit_rate_untied == pytest.approx(1 / 3)
    assert result.miss_ranking == 8
    assert result.miss_ranking_untied == 1
    assert result.miss_vocab == 1
    assert (
        result.miss_vocab + result.miss_crash + result.miss_ranking + result.hits
        == result.n_eligible
    )


def test_twin_histogram_and_per_source_breakdown(census_db):
    arm = FakeArm({Q1: [("sess-alpha", "m-alpha-a")]})
    result = run_census(census_db, arm, collect_questions(census_db), k=K)

    assert result.twin_histogram == {0: 1, 1: 2, 7: 8}
    assert sum(result.twin_histogram.values()) == result.n_eligible
    assert result.by_source["kiro_cli"]["n"] == 10
    assert result.by_source["kiro_cli"]["hits"] == 1
    assert result.by_source["kiro_cli"]["tied"] == 8
    assert result.by_source["claude_code"] == {
        "n": 1,
        "tied": 0,
        "hits": 0,
        "miss_vocab": 0,
        "miss_crash": 0,
        "miss_ranking": 1,
        "miss_ranking_untied": 1,
        "hit_rate": 0.0,
    }


def test_examples_quote_zero_overlap_and_winnable_ranking_misses(census_db):
    result = run_census(census_db, FakeArm(), collect_questions(census_db), k=K)

    assert [example["session_id"] for example in result.zero_overlap_examples] == [
        "sess-island"
    ]
    assert result.zero_overlap_examples[0]["text"] == ISLAND_Q[:160]
    winnable = {
        example["session_id"] for example in result.untied_ranking_miss_examples
    }
    # The eight unwinnable twin questions are ranking misses but not headroom.
    assert winnable == {"sess-alpha", "sess-beta"}
    assert len(result.untied_ranking_miss_examples) == 2


def test_an_arm_crash_is_a_miss_not_a_skip(census_db):
    arm = FakeArm(crash_on="backtick")
    result = run_census(census_db, arm, collect_questions(census_db), k=K)

    assert result.n_eligible == 11
    assert result.crashes == {"backtick": 2}  # both Q1 copies mention "backtick"
    assert result.hits == 0


def test_sampling_is_deterministic_for_a_seed_and_different_for_another(census_db):
    first = collect_questions(census_db, sample=5, seed=4242)
    second = collect_questions(census_db, sample=5, seed=4242)
    other = collect_questions(census_db, sample=5, seed=99)

    assert [q.message_id for q in first] == [q.message_id for q in second]
    assert len(first) == 5
    assert {q.message_id for q in first} <= {
        q.message_id for q in collect_questions(census_db)
    }
    assert [q.message_id for q in first] != [q.message_id for q in other]
    # A sample at or above the population size is the whole population.
    assert len(collect_questions(census_db, sample=50)) == 11


def test_collect_questions_rejects_a_useless_cut_off(census_db):
    with pytest.raises(ValueError, match="k must be at least 1"):
        collect_questions(census_db, k=0)


def test_run_census_refuses_an_empty_population(census_db):
    with pytest.raises(ValueError, match="at least one eligible question"):
        run_census(census_db, FakeArm(), [], k=K)


def test_receipt_is_json_able_and_keeps_timings_out_of_the_metrics(census_db, tmp_path):
    arm = FakeArm({Q1: [("sess-alpha", "m-alpha-a")]})
    result = run_census(census_db, arm, collect_questions(census_db), k=K)
    db_file = tmp_path / "receipt-source.db"
    db_file.write_bytes(b"not really a database")

    receipt = census_receipt(result, db_path=db_file, arm_describe=arm.describe())

    import json

    assert json.loads(json.dumps(receipt))["artefact"] == "paraphrase-census"
    assert receipt["metrics"]["n_eligible"] == 11
    assert receipt["metrics"]["n_tied"] == 8
    assert receipt["metrics"]["twin_histogram"] == {"0": 1, "1": 2, "7": 8}
    assert receipt["arm"] == {"name": "fake", "config": {"arm": "fake", "planted": 1}}
    assert receipt["database"]["size_bytes"] == len(b"not really a database")
    assert len(receipt["database"]["sha256"]) == 64
    # Wall-clock numbers never sit inside the metrics block.
    assert "timings" not in receipt["metrics"]
    assert set(receipt["timings"]) == {"elapsed_seconds", "questions_per_second"}
    assert receipt["parameters"]["k"] == K


def test_the_tokenizer_stems_stops_and_drops_bare_numbers():
    # The ported stemmer strips the first matching suffix in its own order, so
    # "planners" loses only the trailing "s" and "retries" loses "ies".
    assert content_tokens("The planners were failing at 2026 retries") == {
        "planner",
        "fail",
        "retr",
    }
    assert content_tokens("ok thanks") == set()
    assert "src/agent_session_tools/eval" in content_tokens(
        "read src/agent_session_tools/eval"
    )


def test_census_refuses_an_arm_that_cannot_exclude_the_question_itself(census_db):
    """Fail closed: through such an arm a hit could be the question finding itself."""
    arm = NoExclusionArm({Q1: [("sess-alpha", "m-alpha-q")]})
    questions = [q for q in collect_questions(census_db) if q.message_id == "m-alpha-q"]
    with pytest.raises(ValueError, match="cannot exclude"):
        run_census(census_db, arm, questions, k=K)


def test_ruler_side_exclusion_drops_hits_of_unknown_provenance():
    """A hit with no message ids cannot be cleared when messages are excluded."""
    from agent_session_tools.eval.seam import apply_exclusions

    query = Query("q", exclude_message_ids=frozenset({"m-1"}))
    hits = [Hit("s-unknown", ()), Hit("s-clean", ("m-2",)), Hit("s-self", ("m-1",))]
    assert [h.session_id for h in apply_exclusions(hits, query, 5)] == ["s-clean"]
