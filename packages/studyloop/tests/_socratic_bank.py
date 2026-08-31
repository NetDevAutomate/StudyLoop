"""Deterministic Socratic question bank for harness runs.

WHY THIS EXISTS
---------------
The e2e harness must prove two things that a canned echo cannot:

1. the mentor asks questions **relevant to the topic the learner is studying**
   (not generic filler), and
2. there is a **correct answer** the mentor recognises — so a right answer is
   accepted and a wrong answer is not.

An LLM can do both but is non-deterministic and needs credentials; a stub that
replies "tell me more" does neither. This bank is the middle ground: real
topic-specific questions with graded answers, keyed by topic, shared by
the test child process (which asks them) and the e2e tests (which assert
relevance and grading). One source of truth means a test cannot drift from
what the agent actually says.

Grading is keyword-based on purpose: it is auditable, has no dependencies, and
its accept/reject boundary is asserted directly in the tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SocraticQuestion:
    """One guiding question plus what counts as understanding it."""

    #: The question the mentor asks. Phrased Socratically (asks, never tells).
    question: str
    #: Lowercased keywords; an answer must contain ``min_hits`` of them.
    accepted_keywords: tuple[str, ...]
    #: The canonical answer the mentor reveals *after* the learner attempts it.
    correct_answer: str
    #: How many keywords constitute a correct answer.
    min_hits: int = 2
    #: Follow-up prompt used when the learner has not got there yet.
    hint: str = "What happens to the original function when the decorator returns?"

    def grade(self, answer: str) -> bool:
        """True when *answer* demonstrates the concept."""
        low = answer.lower()
        hits = sum(1 for kw in self.accepted_keywords if kw in low)
        return hits >= self.min_hits


@dataclass(frozen=True)
class TopicBank:
    """The concept vocabulary and question set for one study topic."""

    topic: str
    #: Words that make a question *about this topic*. The harness asserts the
    #: mentor's questions contain at least one — that is the machine-checkable
    #: form of "relevant to what the user is studying".
    concept_vocabulary: tuple[str, ...]
    questions: tuple[SocraticQuestion, ...] = field(default_factory=tuple)


PYTHON_DECORATORS = TopicBank(
    topic="Python Decorators",
    concept_vocabulary=(
        "decorator",
        "wrapper",
        "function",
        "functools",
        "wraps",
        "closure",
        "@",
    ),
    questions=(
        SocraticQuestion(
            question=(
                "Before we touch syntax — when you write @timed above a function, "
                "what do you think Python actually does to that function?"
            ),
            accepted_keywords=("wrap", "returns", "function", "replace", "call"),
            correct_answer=(
                "It rebinds the name: f = timed(f). The decorator is called with the "
                "function and its return value takes the original name."
            ),
            hint="What is the decorator called with, and what does the name point at afterwards?",
        ),
        SocraticQuestion(
            question=(
                "You said the wrapper replaces the function. So what happens to the "
                "original function's __name__ and docstring, and why would that matter?"
            ),
            accepted_keywords=("wraps", "functools", "metadata", "__name__", "docstring", "lost"),
            correct_answer=(
                "The wrapper's own metadata shadows the original, so __name__ becomes "
                "'wrapper' and the docstring disappears — functools.wraps copies them back."
            ),
            hint="Which helper in functools exists specifically to fix this?",
        ),
        SocraticQuestion(
            question=(
                "Last one: how does the wrapper still reach the function it decorated, "
                "once the decorator has already returned?"
            ),
            accepted_keywords=("closure", "scope", "enclosing", "captures", "cell", "reference"),
            correct_answer=(
                "Through a closure — the wrapper captures the enclosing scope's `func` "
                "name, so the reference outlives the decorator call."
            ),
            hint="What do we call a function that remembers names from where it was defined?",
        ),
    ),
)

SQL_WINDOW_FUNCTIONS = TopicBank(
    topic="SQL Window Functions",
    concept_vocabulary=("window", "partition", "over", "row_number", "aggregate", "rank"),
    questions=(
        SocraticQuestion(
            question=(
                "You already know GROUP BY collapses rows. What do you expect a window "
                "function to do differently to the rows it reads?"
            ),
            accepted_keywords=("keeps", "rows", "not collapse", "per row", "retain", "each row"),
            correct_answer=(
                "It computes across a set of rows but returns a value per row — the rows "
                "are not collapsed the way GROUP BY collapses them."
            ),
            hint="How many output rows do you get compared with the input?",
        ),
        SocraticQuestion(
            question=(
                "If OVER() with no PARTITION BY sees every row, what does adding "
                "PARTITION BY customer_id change about what each row can see?"
            ),
            accepted_keywords=(
                "partition",
                "window",
                "independent",
                "subset",
                "restricts",
                "only sees",
                "its own",
            ),
            correct_answer=(
                "PARTITION BY splits the rows into independent windows; each row's "
                "calculation only sees rows within its own partition."
            ),
            hint="What is the scope of the calculation for a single row afterwards?",
        ),
    ),
)

#: Registry keyed by a normalised topic string.
BANKS: tuple[TopicBank, ...] = (PYTHON_DECORATORS, SQL_WINDOW_FUNCTIONS)

#: Used when the topic has no dedicated bank — still topic-aware, because the
#: topic string itself is interpolated into the question.
GENERIC_VOCABULARY = ("concept", "example", "why", "how")


def _normalise(value: str) -> str:
    return " ".join(value.replace("-", " ").replace("_", " ").split()).lower()


def bank_for_topic(topic: str) -> TopicBank:
    """Return the question bank whose topic best matches *topic*.

    Matching is deliberately loose (substring both ways on the normalised
    strings) so the same bank serves "Python Decorators", "python-decorators"
    and "decorators in python".
    """
    want = _normalise(topic)
    for bank in BANKS:
        have = _normalise(bank.topic)
        if want == have or want in have or have in want:
            return bank
    # Any bank whose vocabulary appears in the requested topic.
    for bank in BANKS:
        if any(kw in want for kw in bank.concept_vocabulary):
            return bank
    return _generic_bank(topic)


def _generic_bank(topic: str) -> TopicBank:
    """Build a topic-interpolated fallback bank for an unknown topic."""
    label = topic.strip() or "this topic"
    return TopicBank(
        topic=label,
        concept_vocabulary=tuple(_normalise(label).split()) + GENERIC_VOCABULARY,
        questions=(
            SocraticQuestion(
                question=(
                    f"What do you already know about {label}, and where does your "
                    "understanding stop?"
                ),
                accepted_keywords=("because", "so", "means", "when", "it"),
                correct_answer=(
                    f"Any honest account of what you know about {label} and where the "
                    "gap starts is the right answer here."
                ),
                min_hits=1,
                hint=f"Say one true thing about {label} and one thing that confuses you.",
            ),
        ),
    )


def topic_from_persona(text: str) -> str:
    """Extract the study topic from a StudyLoop persona/briefing file.

    Real personas write the topic as ``**Topic:** Python Decorators`` and the
    briefing block adds ``## Study Briefing: <topic>``. Both forms (and plain
    ``Topic:``) are accepted: markdown emphasis and heading markers are
    stripped before matching so a formatting change upstream does not silently
    turn every harness question generic.

    Returns an empty string when no topic line is present; callers turn that
    into the generic bank.
    """
    markers = ("study briefing:", "topic:")
    for raw in text.splitlines():
        # Strip heading hashes, list bullets and emphasis so "**Topic:** X",
        # "## Study Briefing: X" and "- Topic: X" all normalise.
        line = raw.strip().lstrip("#-*> ").strip()
        cleaned = line.replace("**", "").replace("__", "").replace("*", "").strip()
        low = cleaned.lower()
        for marker in markers:
            if low.startswith(marker):
                return cleaned[len(marker) :].strip(" :*_")
    return ""
