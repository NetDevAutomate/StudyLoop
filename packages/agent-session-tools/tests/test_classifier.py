"""Tests for the session classifier module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.classifier import (
    CATEGORIES,
    ClassificationResult,
    classify_all_sessions,
    classify_session,
    classify_text,
    reclassify_sessions,
)
from agent_session_tools.migrations import migrate


# ---------------------------------------------------------------------------
# Helpers / inline fixtures
# ---------------------------------------------------------------------------


def _make_db() -> sqlite3.Connection:
    """Return an in-memory DB with schema + all migrations applied."""
    schema_path = (
        Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    )
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(schema_path.read_text())
    migrate(conn)
    return conn


def _insert_session(
    conn: sqlite3.Connection, session_id: str, session_type: str = "work"
) -> None:
    conn.execute(
        "INSERT INTO sessions (id, source, project_path, created_at, updated_at, session_type)"
        " VALUES (?, 'test', '/proj', '2024-01-01', '2024-01-01', ?)",
        (session_id, session_type),
    )
    conn.commit()


def _insert_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    seq: int = 1,
) -> None:
    msg_id = f"{session_id}-{role}-{seq}"
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, seq)"
        " VALUES (?, ?, ?, ?, ?)",
        (msg_id, session_id, role, content, seq),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# CATEGORIES constant
# ---------------------------------------------------------------------------


class TestCategoriesConstant:
    def test_all_five_categories_present(self):
        assert set(CATEGORIES.keys()) == {
            "learning",
            "debugging",
            "refactoring",
            "planning",
            "work",
        }

    def test_each_category_has_required_keys(self):
        for name, config in CATEGORIES.items():
            assert "keywords" in config, f"{name} missing keywords"
            assert "patterns" in config, f"{name} missing patterns"
            assert "weight" in config, f"{name} missing weight"

    def test_work_has_lowest_weight(self):
        assert CATEGORIES["work"]["weight"] == 1.0

    def test_learning_has_highest_weight(self):
        weights = {name: cfg["weight"] for name, cfg in CATEGORIES.items()}
        assert weights["learning"] == max(weights.values())


# ---------------------------------------------------------------------------
# classify_text — pure function, no DB needed
# ---------------------------------------------------------------------------


class TestClassifyTextReturnShape:
    def test_returns_dict_with_all_categories(self):
        scores = classify_text("hello world")
        assert set(scores.keys()) == set(CATEGORIES.keys())

    def test_empty_string_all_zeros(self):
        scores = classify_text("")
        assert all(v == 0.0 for v in scores.values())

    def test_scores_are_floats(self):
        scores = classify_text("implement a feature")
        assert all(isinstance(v, float) for v in scores.values())


class TestClassifyTextKeywordMatching:
    def test_learning_keywords_boost_learning_score(self):
        scores = classify_text(
            "can you explain what is the concept behind this tutorial"
        )
        assert scores["learning"] > scores["work"]

    def test_debugging_keywords_boost_debugging_score(self):
        scores = classify_text("there is an error exception traceback bug failing")
        assert scores["debugging"] > scores["work"]

    def test_refactoring_keywords_boost_refactoring_score(self):
        scores = classify_text("refactor cleanup restructure optimize consolidate")
        assert scores["refactoring"] > scores["work"]

    def test_planning_keywords_boost_planning_score(self):
        scores = classify_text(
            "architecture design decision trade-off strategy proposal"
        )
        assert scores["planning"] > scores["work"]

    def test_work_keywords_produce_nonzero_score(self):
        scores = classify_text("implement create add build develop write")
        assert scores["work"] > 0.0

    def test_repeated_keyword_increases_score(self):
        single = classify_text("error")
        double = classify_text("error error")
        assert double["debugging"] > single["debugging"]


class TestClassifyTextPatternMatching:
    def test_what_is_pattern_triggers_learning(self):
        scores = classify_text("what is a decorator?")
        assert scores["learning"] > 0.0

    def test_how_does_pattern_triggers_learning(self):
        scores = classify_text("how does asyncio work?")
        assert scores["learning"] > 0.0

    def test_traceback_pattern_triggers_debugging(self):
        scores = classify_text("Traceback (most recent call last)")
        assert scores["debugging"] > 0.0

    def test_failed_to_pattern_triggers_debugging(self):
        scores = classify_text("failed to connect to database")
        assert scores["debugging"] > 0.0

    def test_refactor_method_pattern_triggers_refactoring(self):
        scores = classify_text("extract method from this class")
        assert scores["refactoring"] > 0.0

    def test_design_decision_pattern_triggers_planning(self):
        scores = classify_text("design decision about database choice")
        assert scores["planning"] > 0.0


class TestClassifyTextCaseInsensitive:
    def test_uppercase_keywords_still_score(self):
        lower = classify_text("error bug fix")
        upper = classify_text("ERROR BUG FIX")
        assert upper["debugging"] == lower["debugging"]

    def test_mixed_case_works(self):
        scores = classify_text("Can you Explain This Concept to me?")
        assert scores["learning"] > 0.0


class TestClassifyTextWeightApplication:
    def test_learning_weight_applied(self):
        # Identical keyword count; learning should outscore work due to weight
        # "explain" is a learning keyword; "implement" is a work keyword
        scores = classify_text("explain implement")
        # Both get one keyword hit. learning weight=1.5, work weight=1.0
        assert scores["learning"] > scores["work"]


# ---------------------------------------------------------------------------
# ClassificationResult dataclass
# ---------------------------------------------------------------------------


class TestClassificationResult:
    def test_fields_accessible(self):
        result = ClassificationResult(
            session_id="s1",
            category="learning",
            confidence=0.9,
            scores={"learning": 1.0},
            sample_evidence=["some text"],
        )
        assert result.session_id == "s1"
        assert result.category == "learning"
        assert result.confidence == 0.9
        assert result.scores == {"learning": 1.0}
        assert result.sample_evidence == ["some text"]


# ---------------------------------------------------------------------------
# classify_session — requires DB with messages table
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    """In-memory DB with schema + migrations for each test."""
    conn = _make_db()
    yield conn
    conn.close()


class TestClassifySessionNoMessages:
    def test_empty_session_returns_work_with_zero_confidence(self, db):
        _insert_session(db, "s-empty")
        result = classify_session(db, "s-empty")
        assert result.category == "work"
        assert result.confidence == 0.0
        assert result.scores == {}
        assert result.sample_evidence == []

    def test_returns_classification_result_type(self, db):
        _insert_session(db, "s-type")
        result = classify_session(db, "s-type")
        assert isinstance(result, ClassificationResult)

    def test_session_id_preserved_in_result(self, db):
        _insert_session(db, "s-id-check")
        result = classify_session(db, "s-id-check")
        assert result.session_id == "s-id-check"


class TestClassifySessionWithMessages:
    def test_learning_messages_classify_as_learning(self, db):
        _insert_session(db, "s-learn")
        _insert_message(
            db,
            "s-learn",
            "user",
            "explain what is a decorator and how does it work?",
            seq=1,
        )
        _insert_message(
            db, "s-learn", "user", "can you walk me through the concept again?", seq=2
        )
        result = classify_session(db, "s-learn")
        assert result.category == "learning"

    def test_debugging_messages_classify_as_debugging(self, db):
        _insert_session(db, "s-debug")
        _insert_message(
            db,
            "s-debug",
            "user",
            "there is an error traceback exception failing crash",
            seq=1,
        )
        _insert_message(
            db, "s-debug", "user", "the bug is not working fix it debug this", seq=2
        )
        result = classify_session(db, "s-debug")
        assert result.category == "debugging"

    def test_refactoring_messages_classify_as_refactoring(self, db):
        _insert_session(db, "s-refactor")
        _insert_message(
            db,
            "s-refactor",
            "user",
            "refactor this code cleanup and restructure optimize simplify",
            seq=1,
        )
        _insert_message(
            db,
            "s-refactor",
            "user",
            "extract method rename consolidate reorganize",
            seq=2,
        )
        result = classify_session(db, "s-refactor")
        assert result.category == "refactoring"

    def test_planning_messages_classify_as_planning(self, db):
        _insert_session(db, "s-plan")
        _insert_message(
            db,
            "s-plan",
            "user",
            "architecture design decision trade-off strategy proposal rfc adr",
            seq=1,
        )
        result = classify_session(db, "s-plan")
        assert result.category == "planning"

    def test_confidence_is_between_zero_and_one(self, db):
        _insert_session(db, "s-conf")
        _insert_message(db, "s-conf", "user", "explain what is python", seq=1)
        result = classify_session(db, "s-conf")
        assert 0.0 <= result.confidence <= 1.0

    def test_scores_dict_has_all_categories(self, db):
        _insert_session(db, "s-scores")
        _insert_message(db, "s-scores", "user", "fix the bug", seq=1)
        result = classify_session(db, "s-scores")
        assert set(result.scores.keys()) == set(CATEGORIES.keys())

    def test_winning_category_score_is_one_after_normalisation(self, db):
        _insert_session(db, "s-norm")
        _insert_message(
            db, "s-norm", "user", "fix error traceback exception bug", seq=1
        )
        result = classify_session(db, "s-norm")
        assert result.scores[result.category] == pytest.approx(1.0)

    def test_sample_evidence_collected_for_scored_messages(self, db):
        _insert_session(db, "s-evid")
        _insert_message(
            db, "s-evid", "user", "explain what is a context manager?", seq=1
        )
        result = classify_session(db, "s-evid")
        assert len(result.sample_evidence) >= 1

    def test_evidence_snippets_truncated_to_100_chars(self, db):
        _insert_session(db, "s-trunc")
        long_content = "explain " + "x" * 200
        _insert_message(db, "s-trunc", "user", long_content, seq=1)
        result = classify_session(db, "s-trunc")
        for snippet in result.sample_evidence:
            assert len(snippet) <= 100

    def test_evidence_capped_at_five_snippets(self, db):
        _insert_session(db, "s-cap")
        for i in range(10):
            _insert_message(
                db, "s-cap", "user", f"explain what is concept number {i}", seq=i + 1
            )
        result = classify_session(db, "s-cap")
        assert len(result.sample_evidence) <= 5

    def test_user_messages_weighted_higher_than_assistant(self, db):
        # Session with a strong user learning signal and neutral assistant reply
        _insert_session(db, "s-weight")
        _insert_message(
            db,
            "s-weight",
            "user",
            "explain what is tutorial concept basics fundamentals",
            seq=1,
        )
        _insert_message(
            db,
            "s-weight",
            "assistant",
            "implement add create build develop write update",
            seq=2,
        )
        result = classify_session(db, "s-weight")
        # User message (learning) should overpower assistant (work)
        assert result.category == "learning"

    def test_message_limit_respected(self, db):
        """With limit=1 only the first message is considered."""
        _insert_session(db, "s-limit")
        # First message is learning-heavy
        _insert_message(
            db, "s-limit", "user", "explain what is a decorator tutorial concept", seq=1
        )
        # Subsequent messages are noise — with limit=1 only the first is read
        for i in range(20):
            _insert_message(
                db, "s-limit", "user", "implement add build create", seq=i + 2
            )
        result_limited = classify_session(db, "s-limit", message_limit=1)
        assert result_limited.category == "learning"

    def test_tool_use_and_tool_result_messages_excluded(self, db):
        """Only user/assistant roles should be scored."""
        _insert_session(db, "s-roles")
        _insert_message(
            db, "s-roles", "tool_use", "fix error bug traceback crash exception", seq=1
        )
        _insert_message(
            db,
            "s-roles",
            "tool_result",
            "fix error bug traceback crash exception",
            seq=2,
        )
        _insert_message(db, "s-roles", "user", "explain the concept please", seq=3)
        result = classify_session(db, "s-roles")
        # tool_use/tool_result should be ignored; only the learning user message counts
        assert result.category == "learning"

    def test_null_content_messages_excluded(self, db):
        """Messages with NULL content should not cause errors."""
        _insert_session(db, "s-null")
        conn_raw = db
        conn_raw.execute(
            "INSERT INTO messages (id, session_id, role, content, seq) VALUES (?, ?, ?, NULL, ?)",
            ("null-msg", "s-null", "user", 1),
        )
        conn_raw.commit()
        _insert_message(db, "s-null", "user", "explain what is python", seq=2)
        result = classify_session(db, "s-null")
        assert result.category == "learning"


# ---------------------------------------------------------------------------
# classify_all_sessions
# ---------------------------------------------------------------------------


class TestClassifyAllSessions:
    def test_returns_category_counts_dict(self, db):
        _insert_session(db, "s-all-1")
        _insert_message(db, "s-all-1", "user", "explain what is concept", seq=1)
        counts = classify_all_sessions(db, update_db=False)
        assert isinstance(counts, dict)
        assert sum(counts.values()) == 1

    def test_counts_sum_to_total_sessions(self, db):
        for i in range(3):
            _insert_session(db, f"s-count-{i}")
            _insert_message(db, f"s-count-{i}", "user", "implement create add", seq=1)
        counts = classify_all_sessions(db, update_db=False)
        assert sum(counts.values()) == 3

    def test_update_db_true_writes_session_type(self, db):
        _insert_session(db, "s-write")
        _insert_message(
            db, "s-write", "user", "explain what is concept tutorial basics", seq=1
        )
        classify_all_sessions(db, update_db=True)
        row = db.execute(
            "SELECT session_type FROM sessions WHERE id = 's-write'"
        ).fetchone()
        assert row["session_type"] is not None

    def test_update_db_false_does_not_write(self, db):
        _insert_session(db, "s-nowrite", session_type="work")
        _insert_message(
            db, "s-nowrite", "user", "explain what is concept tutorial basics", seq=1
        )
        classify_all_sessions(db, update_db=False)
        row = db.execute(
            "SELECT session_type FROM sessions WHERE id = 's-nowrite'"
        ).fetchone()
        # Type should remain as originally inserted ("work"), not overwritten
        assert row["session_type"] == "work"

    def test_session_limit_restricts_processing(self, db):
        for i in range(5):
            _insert_session(db, f"s-lim-{i}")
        counts = classify_all_sessions(db, update_db=False, session_limit=2)
        assert sum(counts.values()) == 2

    def test_empty_database_returns_empty_dict(self, db):
        counts = classify_all_sessions(db, update_db=False)
        assert counts == {}


# ---------------------------------------------------------------------------
# reclassify_sessions
# ---------------------------------------------------------------------------


class TestReclassifySessions:
    def test_returns_dict_with_expected_keys(self, db):
        result = reclassify_sessions(db, dry_run=True)
        assert "total_sessions" in result
        assert "changes" in result
        assert "category_distribution" in result
        assert "sample_changes" in result

    def test_total_sessions_matches_db_count(self, db):
        for i in range(4):
            _insert_session(db, f"s-rc-{i}")
        result = reclassify_sessions(db, dry_run=True)
        assert result["total_sessions"] == 4

    def test_dry_run_does_not_persist_changes(self, db):
        _insert_session(db, "s-dry", session_type="planning")
        _insert_message(
            db, "s-dry", "user", "explain what is concept tutorial basics", seq=1
        )
        reclassify_sessions(db, dry_run=True)
        row = db.execute(
            "SELECT session_type FROM sessions WHERE id = 's-dry'"
        ).fetchone()
        # Still "planning" — dry run must not write
        assert row["session_type"] == "planning"

    def test_wet_run_persists_changes(self, db):
        _insert_session(db, "s-wet", session_type="planning")
        _insert_message(
            db, "s-wet", "user", "explain what is concept tutorial basics", seq=1
        )
        reclassify_sessions(db, dry_run=False)
        row = db.execute(
            "SELECT session_type FROM sessions WHERE id = 's-wet'"
        ).fetchone()
        # Category should now reflect message content
        assert row["session_type"] == "learning"

    def test_change_detected_when_type_differs(self, db):
        _insert_session(db, "s-change", session_type="planning")
        _insert_message(
            db, "s-change", "user", "fix error bug traceback exception crash", seq=1
        )
        result = reclassify_sessions(db, dry_run=True)
        assert result["changes"] >= 1

    def test_no_change_when_type_already_correct(self, db):
        _insert_session(db, "s-nochange", session_type="learning")
        _insert_message(
            db, "s-nochange", "user", "explain what is concept tutorial basics", seq=1
        )
        result = reclassify_sessions(db, dry_run=True)
        assert result["changes"] == 0

    def test_sample_changes_capped_at_ten(self, db):
        for i in range(15):
            _insert_session(db, f"s-sample-{i}", session_type="planning")
            _insert_message(
                db, f"s-sample-{i}", "user", "fix error bug traceback exception", seq=1
            )
        result = reclassify_sessions(db, dry_run=True)
        assert len(result["sample_changes"]) <= 10

    def test_change_entry_has_expected_fields(self, db):
        _insert_session(db, "s-fields", session_type="planning")
        _insert_message(
            db, "s-fields", "user", "fix error bug traceback exception crash", seq=1
        )
        result = reclassify_sessions(db, dry_run=True)
        if result["changes"] > 0:
            change = result["sample_changes"][0]
            assert "session_id" in change
            assert "from" in change
            assert "to" in change
            assert "confidence" in change

    def test_category_distribution_sums_to_total(self, db):
        for i in range(3):
            _insert_session(db, f"s-dist-{i}")
            _insert_message(
                db, f"s-dist-{i}", "user", "implement create add build", seq=1
            )
        result = reclassify_sessions(db, dry_run=True)
        assert sum(result["category_distribution"].values()) == result["total_sessions"]

    def test_empty_db_returns_zero_total(self, db):
        result = reclassify_sessions(db, dry_run=True)
        assert result["total_sessions"] == 0
        assert result["changes"] == 0
