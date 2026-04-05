"""Fast structural heuristic checks for agent responses.

Each check is a pure function ``(response: str, scenario: Scenario) -> bool``.
``run_heuristics`` drives them via the registry, returning a ``HeuristicResult``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from studyctl.eval.models import HeuristicResult, Scenario

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Trigger / keyword lists
# ---------------------------------------------------------------------------

_RSD_TRIGGERS: list[str] = [
    "it's easy",
    "it's simple",
    "just do",
    "simply",
    "obviously",
    "you should know",
]

_BREAK_PHRASES: list[str] = [
    "break",
    "pause",
    "rest",
    "stretch",
    "step away",
    "take a moment",
]

_PARK_PHRASES: list[str] = [
    "park",
    "studyctl park",
    "come back to",
    "save for later",
    "note that down",
]

_RECOGNITION_WORDS: list[str] = [
    "great",
    "excellent",
    "exactly",
    "well done",
    "nice",
    "good point",
    "right",
    "correct",
    "spotted",
    "noticed",
]

# Common short words excluded when testing whether recognition echoes the prompt
_COMMON_WORDS: frozenset[str] = frozenset(
    {
        "i",
        "a",
        "an",
        "the",
        "to",
        "of",
        "in",
        "is",
        "it",
        "at",
        "on",
        "do",
        "be",
        "my",
        "we",
        "so",
        "or",
        "if",
        "as",
        "up",
        "by",
        "no",
        "he",
        "me",
        "us",
        "am",
        "and",
        "for",
        "not",
        "but",
        "you",
        "are",
        "was",
        "has",
        "had",
        "can",
        "did",
        "its",
        "yet",
        "any",
        "all",
        "too",
        "how",
        "now",
    }
)


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


def _contains_question(response: str, scenario: Scenario) -> bool:
    """Return True iff the response contains a question mark."""
    _ = scenario  # unused — part of the uniform check signature
    return "?" in response


def _no_rsd_triggers(response: str, scenario: Scenario) -> bool:
    """Return True iff the response contains none of the RSD trigger phrases."""
    _ = scenario
    lower = response.lower()
    return not any(trigger in lower for trigger in _RSD_TRIGGERS)


def _references_topic(response: str, scenario: Scenario) -> bool:
    """Return True iff the response mentions a significant word from the topic."""
    lower_response = response.lower()
    for word in scenario.topic.split():
        if len(word) <= 2:
            continue
        if word.lower() in lower_response:
            return True
    return False


def _suggests_break(response: str, scenario: Scenario) -> bool:
    """Return True iff the response suggests taking a break."""
    _ = scenario
    lower = response.lower()
    return any(phrase in lower for phrase in _BREAK_PHRASES)


def _suggests_park(response: str, scenario: Scenario) -> bool:
    """Return True iff the response suggests parking the topic."""
    _ = scenario
    lower = response.lower()
    return any(phrase in lower for phrase in _PARK_PHRASES)


def _does_not_shame(response: str, scenario: Scenario) -> bool:
    """Alias for ``_no_rsd_triggers`` — same logic, distinct semantic label."""
    return _no_rsd_triggers(response, scenario)


def _contains_positive_recognition(response: str, scenario: Scenario) -> bool:
    """Return True iff the response contains a positive recognition phrase."""
    _ = scenario
    lower = response.lower()
    return any(word in lower for word in _RECOGNITION_WORDS)


def _recognition_is_specific(response: str, scenario: Scenario) -> bool:
    """Return True iff the response both recognises the student AND echoes their words.

    Requires:
    - At least one recognition phrase from ``_RECOGNITION_WORDS``.
    - At least one non-common, non-trivial word from the student's prompt
      appears in the response — tying the praise to something concrete.
    """
    if not _contains_positive_recognition(response, scenario):
        return False

    lower_response = response.lower()
    prompt_words = [
        w.strip(".,!?;:'\"").lower()
        for w in scenario.prompt.split()
        if len(w.strip(".,!?;:'\"")) > 2 and w.strip(".,!?;:'\"").lower() not in _COMMON_WORDS
    ]
    return any(pw in lower_response for pw in prompt_words)


# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

CHECKS: dict[str, Callable[[str, Scenario], bool]] = {
    "contains_question": _contains_question,
    "no_rsd_triggers": _no_rsd_triggers,
    "references_topic": _references_topic,
    "suggests_break": _suggests_break,
    "suggests_park": _suggests_park,
    "does_not_shame": _does_not_shame,
    "contains_positive_recognition": _contains_positive_recognition,
    "recognition_is_specific": _recognition_is_specific,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_heuristics(response: str, scenario: Scenario) -> HeuristicResult:
    """Run the checks listed in ``scenario.heuristic_checks`` and aggregate.

    Unknown check names are recorded as failures with an explanatory message.
    An empty ``heuristic_checks`` list → ``HeuristicResult(passed=True, ...)``.
    """
    checks: dict[str, bool] = {}
    messages: list[str] = []

    for check_name in scenario.heuristic_checks:
        fn = CHECKS.get(check_name)
        if fn is None:
            checks[check_name] = False
            messages.append(f"Unknown check: {check_name}")
            continue
        passed = fn(response, scenario)
        checks[check_name] = passed
        if not passed:
            messages.append(f"Failed: {check_name}")

    return HeuristicResult(
        passed=all(checks.values()),
        checks=checks,
        messages=messages,
    )
