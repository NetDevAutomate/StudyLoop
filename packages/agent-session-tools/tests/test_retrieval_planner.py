"""Pure planner classification: what is explicit FTS5 and what is a sentence.

These pin the two rules the Stage 2 council review sharpened -- operators count
only outside double-quoted spans, and the fallback after a rejected explicit
query can never itself be explicit.
"""

from __future__ import annotations

import pytest

from agent_session_tools.retrieval import plan_natural_language, plan_query


@pytest.mark.parametrize(
    "query",
    [
        "error OR authentication",
        'error NOT "exact phrase"',
        "fts:anything at all?",
        '"exact phrase" OR authentication',
        "alpha NEAR bravo",
    ],
)
def test_uppercase_operators_outside_quotes_and_the_prefix_are_explicit(query):
    assert plan_query(query).explicit is True


@pytest.mark.parametrize(
    "query",
    [
        "how do I read and write files, or not?",
        '"error OR warning" recovery',
        'docker "NOT found" and cache',
        "ORDER and ANDROID are words",
        "and or not",
    ],
)
def test_lowercase_or_quoted_operators_are_words(query):
    plan = plan_query(query)
    assert plan.explicit is False
    for match in plan.queries:
        # Every planned MATCH string is a conjunction/disjunction of quoted terms.
        assert all(
            part.startswith('"') and part.endswith('"') for part in match.split(" AND ")
        )


def test_natural_language_planning_never_returns_an_explicit_plan():
    for query in ("fts:fts:alpha?", "alpha OR ?", 'NOT "x" AND', "fts:"):
        plan = plan_natural_language(query)
        assert plan.explicit is False
        assert all(
            part.startswith('"')
            for match in plan.queries
            for part in match.split(" OR ")
        )


def test_a_phrase_with_an_inner_operator_survives_as_one_term():
    plan = plan_query('"error OR warning" recovery')
    assert plan.terms == ('"error OR warning"', "recovery")
    assert plan.queries == (
        '"error OR warning" AND "recovery"',
        '"error OR warning" OR "recovery"',
    )


@pytest.mark.parametrize(
    "query",
    [
        '"" OR "alpha"',  # the empty pair must not swallow the operator into a phrase
        '"alpha"AND"bravo"',  # an operator between two phrases is outside both
        '"unterminated OR',  # an unmatched quote opens no phrase; what follows is outside
    ],
)
def test_quote_edge_cases_are_classified_by_a_scanner_not_a_regex(query):
    """Escalation council F1/F2: the regex ``"([^"]+)"`` skipped an empty pair and
    read ``" OR "`` as the phrase, so ``"" OR "alpha"`` planned the word ``OR``."""
    assert plan_query(query).explicit is True


def test_phrase_extraction_uses_the_same_scanner_as_classification():
    plan = plan_natural_language('"" OR "alpha"')
    assert plan.terms == ('"alpha"',)  # the empty span is dropped, OR is a stop word
    plan = plan_natural_language('alpha "bravo')
    assert plan.terms == ("alpha", "bravo")  # the unmatched quote is not a phrase
    plan = plan_natural_language('"a" "b" c')
    assert plan.terms == ('"a"', '"b"')  # phrases keep their length; ``c`` is too short
