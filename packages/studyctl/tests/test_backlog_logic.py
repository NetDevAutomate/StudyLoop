"""Tests for studyctl backlog logic — functional core (no mocks, no DB)."""

from __future__ import annotations

from studyctl.backlog_logic import (
    BacklogItem,
    ScoringInput,
    build_backlog_summary,
    format_backlog_list,
    plan_auto_persist,
    score_backlog_items,
)
from studyctl.session_state import TopicEntry


def _item(
    item_id: int = 1,
    question: str = "Test topic",
    topic_tag: str | None = None,
    tech_area: str | None = None,
    source: str = "parked",
    context: str | None = None,
    parked_at: str = "2026-04-03 10:00:00",
    session_topic: str | None = None,
) -> BacklogItem:
    """Factory for test BacklogItems."""
    return BacklogItem(
        id=item_id,
        question=question,
        topic_tag=topic_tag,
        tech_area=tech_area,
        source=source,
        context=context,
        parked_at=parked_at,
        session_topic=session_topic,
    )


# ─── format_backlog_list ────────────────────────────────────────


class TestFormatBacklogList:
    def test_empty_list(self):
        result = format_backlog_list([])
        assert result.total == 0
        assert result.items == []
        assert result.by_tech == {}
        assert result.by_source == {}

    def test_groups_by_tech_area(self):
        items = [
            _item(item_id=1, question="Decorators", tech_area="Python"),
            _item(item_id=2, question="Window funcs", tech_area="SQL"),
            _item(item_id=3, question="Generators", tech_area="Python"),
        ]
        result = format_backlog_list(items)
        assert result.total == 3
        assert len(result.by_tech["Python"]) == 2
        assert len(result.by_tech["SQL"]) == 1

    def test_groups_by_source(self):
        items = [
            _item(item_id=1, source="parked"),
            _item(item_id=2, source="struggled"),
            _item(item_id=3, source="manual"),
            _item(item_id=4, source="parked"),
        ]
        result = format_backlog_list(items)
        assert result.by_source == {"parked": 2, "struggled": 1, "manual": 1}

    def test_filter_by_tech(self):
        items = [
            _item(item_id=1, tech_area="Python"),
            _item(item_id=2, tech_area="SQL"),
        ]
        result = format_backlog_list(items, tech_filter="Python")
        assert result.total == 1
        assert result.items[0].tech_area == "Python"

    def test_filter_by_source(self):
        items = [
            _item(item_id=1, source="parked"),
            _item(item_id=2, source="struggled"),
        ]
        result = format_backlog_list(items, source_filter="struggled")
        assert result.total == 1
        assert result.items[0].source == "struggled"

    def test_none_tech_grouped_as_uncategorized(self):
        items = [_item(item_id=1, tech_area=None)]
        result = format_backlog_list(items)
        assert "Uncategorized" in result.by_tech


# ─── build_backlog_summary ──────────────────────────────────────


class TestBuildBacklogSummary:
    def test_no_items_returns_none(self):
        assert build_backlog_summary([], "Python") is None

    def test_builds_markdown_with_items(self):
        items = [
            _item(item_id=1, question="Decorators", tech_area="Python"),
            _item(item_id=2, question="Window funcs", tech_area="SQL"),
        ]
        result = build_backlog_summary(items, "Python Patterns")
        assert result is not None
        assert "Decorators" in result
        assert "Window funcs" in result
        assert "2" in result  # count

    def test_prioritises_matching_tech(self):
        items = [
            _item(item_id=1, question="SQL joins", tech_area="SQL"),
            _item(item_id=2, question="Decorators", tech_area="Python"),
        ]
        result = build_backlog_summary(items, "Python Patterns")
        assert result is not None
        # Python item should appear before SQL item
        python_pos = result.index("Decorators")
        sql_pos = result.index("SQL joins")
        assert python_pos < sql_pos


# ─── plan_auto_persist ──────────────────────────────────────────


class TestPlanAutoPersist:
    def test_no_struggled_returns_empty(self):
        entries = [
            TopicEntry(time="10:00", topic="Decorators", status="learning", note="Going well"),
        ]
        result = plan_auto_persist(entries, existing_questions=set(), study_session_id="sess-1")
        assert result == []

    def test_struggled_entries_become_persist_actions(self):
        entries = [
            TopicEntry(time="10:00", topic="Decorators", status="struggling", note="Hard"),
            TopicEntry(time="10:30", topic="Generators", status="learning", note="OK"),
        ]
        result = plan_auto_persist(entries, existing_questions=set(), study_session_id="sess-1")
        assert len(result) == 1
        assert result[0].question == "Decorators"
        assert result[0].source == "struggled"
        assert result[0].study_session_id == "sess-1"

    def test_deduplicates_against_existing(self):
        entries = [
            TopicEntry(time="10:00", topic="Decorators", status="struggling", note="Hard"),
        ]
        result = plan_auto_persist(
            entries,
            existing_questions={"Decorators"},
            study_session_id="sess-1",
        )
        assert result == []

    def test_multiple_struggled_all_persisted(self):
        entries = [
            TopicEntry(time="10:00", topic="Decorators", status="struggling", note="Hard"),
            TopicEntry(time="10:30", topic="Metaclasses", status="struggling", note="Very hard"),
        ]
        result = plan_auto_persist(entries, existing_questions=set(), study_session_id="sess-1")
        assert len(result) == 2

    def test_context_from_note(self):
        entries = [
            TopicEntry(time="10:00", topic="Decorators", status="struggling", note="Need examples"),
        ]
        result = plan_auto_persist(entries, existing_questions=set(), study_session_id="sess-1")
        assert result[0].context == "Need examples"


# ─── score_backlog_items ────────────────────────────────────────


def _scoring_input(
    item_id: int = 1,
    question: str = "Test topic",
    frequency: int = 1,
    priority: int | None = None,
    tech_area: str | None = None,
) -> ScoringInput:
    """Factory for test ScoringInputs."""
    return ScoringInput(
        item=_item(item_id=item_id, question=question, tech_area=tech_area),
        frequency=frequency,
        priority=priority,
    )


class TestScoreBacklogItems:
    def test_empty_list(self):
        result = score_backlog_items([])
        assert result == []

    def test_single_item_gets_scored(self):
        inputs = [_scoring_input(item_id=1, question="Decorators", frequency=3, priority=4)]
        result = score_backlog_items(inputs)
        assert len(result) == 1
        assert result[0].score > 0
        assert result[0].frequency == 3
        assert result[0].priority == 4
        assert result[0].reasoning != ""

    def test_higher_priority_ranks_first(self):
        inputs = [
            _scoring_input(item_id=1, question="Niche topic", frequency=2, priority=1),
            _scoring_input(item_id=2, question="OOP fundamentals", frequency=2, priority=5),
        ]
        result = score_backlog_items(inputs)
        assert result[0].item.question == "OOP fundamentals"
        assert result[0].score > result[1].score

    def test_higher_frequency_ranks_higher_at_same_priority(self):
        inputs = [
            _scoring_input(item_id=1, question="Rare topic", frequency=1, priority=3),
            _scoring_input(item_id=2, question="Common struggle", frequency=5, priority=3),
        ]
        result = score_backlog_items(inputs)
        assert result[0].item.question == "Common struggle"

    def test_priority_outweighs_frequency(self):
        """A high-priority low-frequency item beats a low-priority high-frequency one."""
        inputs = [
            _scoring_input(item_id=1, question="Frequent niche", frequency=10, priority=1),
            _scoring_input(item_id=2, question="Rare fundamental", frequency=1, priority=5),
        ]
        result = score_backlog_items(inputs)
        assert result[0].item.question == "Rare fundamental"

    def test_null_priority_defaults_to_3(self):
        inputs = [
            _scoring_input(item_id=1, question="Unassessed", frequency=2, priority=None),
        ]
        result = score_backlog_items(inputs)
        assert result[0].priority == 3  # default

    def test_reasoning_explains_score(self):
        inputs = [_scoring_input(item_id=1, question="Closures", frequency=4, priority=5)]
        result = score_backlog_items(inputs)
        reasoning = result[0].reasoning.lower()
        assert "frequency" in reasoning or "importance" in reasoning

    def test_scores_sorted_descending(self):
        inputs = [
            _scoring_input(item_id=1, question="Low", frequency=1, priority=1),
            _scoring_input(item_id=2, question="Mid", frequency=3, priority=3),
            _scoring_input(item_id=3, question="High", frequency=5, priority=5),
        ]
        result = score_backlog_items(inputs)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)
