"""Tests for the topic resolver — pure function, no mocking needed."""

from __future__ import annotations

from pathlib import Path

from studyctl.logic.topic_resolver import MatchKind, ResolveResult, resolve_topic
from studyctl.settings import TopicConfig


def _topic(name: str, tags: list[str] | None = None) -> TopicConfig:
    return TopicConfig(
        name=name,
        slug=name.lower().replace(" ", "-"),
        obsidian_path=Path("/fake"),
        tags=tags or [],
    )


TOPICS = [
    _topic("Python", tags=["python", "programming"]),
    _topic("SQL", tags=["sql", "databases"]),
    _topic("Data Engineering", tags=["data-engineering", "spark", "glue"]),
]


# ---------------------------------------------------------------------------
# Exact match
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_exact_name(self):
        result = resolve_topic("Python", TOPICS)
        assert result.kind == MatchKind.EXACT
        assert result.resolved is not None
        assert result.resolved.name == "Python"

    def test_exact_name_casefold(self):
        result = resolve_topic("python", TOPICS)
        assert result.kind == MatchKind.EXACT
        assert result.resolved.name == "Python"

    def test_exact_name_uppercase(self):
        result = resolve_topic("SQL", TOPICS)
        assert result.kind == MatchKind.EXACT
        assert result.resolved.name == "SQL"

    def test_exact_multi_word(self):
        result = resolve_topic("data engineering", TOPICS)
        assert result.kind == MatchKind.EXACT
        assert result.resolved.name == "Data Engineering"


# ---------------------------------------------------------------------------
# Name substring
# ---------------------------------------------------------------------------


class TestNameSubstring:
    def test_query_contains_name(self):
        """'Python Decorators' contains 'Python'."""
        result = resolve_topic("Python Decorators", TOPICS)
        assert result.kind == MatchKind.NAME
        assert result.resolved is not None
        assert result.resolved.name == "Python"

    def test_name_contains_query(self):
        """'Data' is contained in 'Data Engineering'."""
        result = resolve_topic("Data", TOPICS)
        assert result.kind == MatchKind.NAME
        assert result.resolved is not None
        assert result.resolved.name == "Data Engineering"

    def test_multiple_substring_matches(self):
        """Query matching multiple topics returns all candidates."""
        topics = [
            _topic("Python Basics"),
            _topic("Python Advanced"),
            _topic("SQL"),
        ]
        result = resolve_topic("Python", topics)
        assert result.kind == MatchKind.NAME
        assert result.resolved is None  # ambiguous
        assert len(result.matches) == 2

    def test_substring_case_insensitive(self):
        result = resolve_topic("python decorators", TOPICS)
        assert result.kind == MatchKind.NAME
        assert result.resolved.name == "Python"


# ---------------------------------------------------------------------------
# Tag match
# ---------------------------------------------------------------------------


class TestTagMatch:
    def test_single_tag_match(self):
        result = resolve_topic("Spark Joins", TOPICS)
        assert result.kind == MatchKind.TAG
        assert result.resolved is not None
        assert result.resolved.name == "Data Engineering"

    def test_tag_match_partial(self):
        """Tag 'databases' matches query containing 'databases'."""
        result = resolve_topic("databases fundamentals", TOPICS)
        assert result.kind == MatchKind.TAG
        assert result.resolved.name == "SQL"

    def test_tag_match_multiple(self):
        """Query matching tags on multiple topics returns all."""
        topics = [
            _topic("Python", tags=["coding"]),
            _topic("SQL", tags=["coding"]),
        ]
        result = resolve_topic("coding", topics)
        assert result.kind == MatchKind.TAG
        assert result.resolved is None
        assert len(result.matches) == 2


# ---------------------------------------------------------------------------
# Fuzzy match
# ---------------------------------------------------------------------------


class TestFuzzyMatch:
    def test_typo_correction(self):
        result = resolve_topic("Pyhton", TOPICS)
        assert result.kind == MatchKind.FUZZY
        assert any(t.name == "Python" for t in result.matches)

    def test_close_match(self):
        result = resolve_topic("Sequel", TOPICS)
        assert result.kind == MatchKind.FUZZY
        assert any(t.name == "SQL" for t in result.matches)


# ---------------------------------------------------------------------------
# No match
# ---------------------------------------------------------------------------


class TestNoMatch:
    def test_no_match_garbage(self):
        result = resolve_topic("xyzzy plugh", TOPICS)
        assert result.kind == MatchKind.NONE
        assert result.matches == []
        assert result.resolved is None

    def test_empty_query(self):
        result = resolve_topic("", TOPICS)
        assert result.kind == MatchKind.NONE

    def test_whitespace_only(self):
        result = resolve_topic("   ", TOPICS)
        assert result.kind == MatchKind.NONE

    def test_empty_topics_list(self):
        result = resolve_topic("Python", [])
        assert result.kind == MatchKind.NONE


# ---------------------------------------------------------------------------
# Unicode / casefold
# ---------------------------------------------------------------------------


class TestUnicode:
    def test_casefold_accent(self):
        topics = [_topic("Café Networking")]
        result = resolve_topic("café networking", topics)
        assert result.kind == MatchKind.EXACT
        assert result.resolved.name == "Café Networking"

    def test_casefold_german_eszett(self):
        topics = [_topic("Straße")]
        result = resolve_topic("strasse", topics)
        assert result.kind == MatchKind.EXACT


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


class TestPrecedence:
    def test_exact_beats_substring(self):
        """If exact match exists, don't fall through to substring."""
        topics = [
            _topic("Python"),
            _topic("Python Advanced"),
        ]
        result = resolve_topic("Python", topics)
        assert result.kind == MatchKind.EXACT
        assert result.resolved.name == "Python"

    def test_name_beats_tag(self):
        """Substring match on name wins over tag match."""
        topics = [
            _topic("Spark", tags=["data"]),
            _topic("Data Science", tags=["spark"]),
        ]
        result = resolve_topic("Spark Joins", topics)
        assert result.kind == MatchKind.NAME
        assert result.resolved.name == "Spark"


# ---------------------------------------------------------------------------
# ResolveResult properties
# ---------------------------------------------------------------------------


class TestResolveResult:
    def test_resolved_single(self):
        r = ResolveResult(MatchKind.EXACT, [_topic("Python")])
        assert r.resolved is not None
        assert r.resolved.name == "Python"

    def test_resolved_none_on_multiple(self):
        r = ResolveResult(MatchKind.NAME, [_topic("A"), _topic("B")])
        assert r.resolved is None

    def test_resolved_none_on_empty(self):
        r = ResolveResult(MatchKind.NONE, [])
        assert r.resolved is None
