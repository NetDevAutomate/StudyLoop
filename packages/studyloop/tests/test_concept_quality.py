"""The concept filter is tested against debris observed in a real graph.

Every string in ``JUNK`` was rendered as an actual node in the `python` mastery
graph, or handed to the study-plan agent as evidence by
``seed_from_history()``. Every string in ``REAL`` is a concept from the same
notes that must survive. A filter that drops the second list is worse than no
filter, so both directions are asserted.
"""

from __future__ import annotations

import pytest

from studyloop.learning.concept_quality import filter_concepts, is_usable_concept

#: Observed in the live mastery graph or the live interview seed.
JUNK = [
    "Unsupported markdown: list",
    "Unsupported markdown: heading",
    "'eat','tea','ate'",
    "(5+10) → 15 → (15*3) → 45 → (45 1) → 44",
    "(a) a function that accepts a function as an argument",
    "(b) a function that returns a function (closure / factory)",
    "'and' returns first falsy value or last value:",
    "'or' returns first truthy value or last value:",
    "useful for default values:",
    "study-notes/introd",
    "quick topic",
    "x",
    "def",
    # Found by looking at the rendered graph after the first filter shipped:
    # character-length rules let whole sentences and quoted fragments through,
    # and word count turned out to be the rule that actually discriminates.
    "'append' creates a new array — o(n) operation",
    "'button'",
    "'consider using a decorator here to reduce repetition.",
    "'this is terrible. any competent developer would use a decorator here.",
    "# with abstract methods get amount, get price data",
    "consider: what if items is empty",
    ".pre commit config.yaml",
    "005 notification patterns study notes",
    "2.8 two pointer technique",
]

#: Real concepts from the same source that must NOT be filtered out.
REAL = [
    "decorator pattern",
    "first-class functions",
    "closures",
    "abc-vs-protocol",
    "gil",
    "type annotations",
    "context managers",
    "generators",
    "structural typing",
    "dependency inversion",
    "single responsibility",
    "sql-joins",
    "outer-join",
    "composition over inheritance",
    "single responsibility principle",
    "2-phase commit",
    "3-tier architecture",
    # A backtick code span IS the concept in this domain. Caught by a real
    # test: rejecting all quote-like leading characters dropped the edge
    # `typing.protocol` -> duck typing [shape] and broke mermaid output.
    "`typing.protocol`",
    "duck typing [shape]",
]


class TestJunkIsRejected:
    @pytest.mark.parametrize("value", JUNK)
    def test_observed_debris_is_rejected(self, value: str) -> None:
        assert not is_usable_concept(value), f"debris survived the filter: {value!r}"


class TestRealConceptsSurvive:
    @pytest.mark.parametrize("value", REAL)
    def test_real_concept_survives(self, value: str) -> None:
        assert is_usable_concept(value), f"filter dropped a real concept: {value!r}"


class TestGilIsAnEdgeCase:
    """`gil` is 3 characters and is a real, load-bearing concept.

    It is also the single struggle signal in the live database, so a length rule
    that drops it would silently remove the one piece of evidence the plan agent
    has. Documented here because it is the reason MIN_CONCEPT_CHARS cannot rise.
    """

    def test_gil_survives(self) -> None:
        assert is_usable_concept("gil")

    def test_two_char_token_does_not(self) -> None:
        assert not is_usable_concept("ab")


class TestFilterConcepts:
    def test_preserves_order_and_deduplicates(self) -> None:
        out = filter_concepts(["closures", "x", "closures", "generators", "CLOSURES"])
        assert out == ["closures", "generators"]

    def test_handles_non_iterables_safely(self) -> None:
        """Callers pass whatever the database returned; never raise on shape."""
        assert filter_concepts(None) == []
        assert filter_concepts("") == []
        assert filter_concepts("closures") == [], "a bare string is not a list of concepts"
        assert filter_concepts([None, 42, "closures"]) == ["closures"]
