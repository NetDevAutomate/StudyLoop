"""Tests for the heuristic judge — TDD: written before implementation."""

from __future__ import annotations

from studyctl.eval.models import HeuristicResult, Scenario


def _make_scenario(
    topic: str = "Python decorators",
    prompt: str = "I don't understand decorators at all",
    heuristic_checks: list[str] | None = None,
) -> Scenario:
    """Helper: build a minimal Scenario inline (not a fixture)."""
    return Scenario(
        id="test-001",
        name="Test scenario",
        priority="normal",
        topic=topic,
        energy=5,
        prompt=prompt,
        heuristic_checks=heuristic_checks or [],
    )


# ---------------------------------------------------------------------------
# contains_question
# ---------------------------------------------------------------------------


def test_contains_question_pass() -> None:
    from studyctl.eval.judge.heuristic import _contains_question

    scenario = _make_scenario()
    assert _contains_question("What do you think about this?", scenario) is True


def test_contains_question_fail() -> None:
    from studyctl.eval.judge.heuristic import _contains_question

    scenario = _make_scenario()
    assert _contains_question("This is a statement with no question.", scenario) is False


# ---------------------------------------------------------------------------
# no_rsd_triggers
# ---------------------------------------------------------------------------


def test_no_rsd_triggers_pass() -> None:
    from studyctl.eval.judge.heuristic import _no_rsd_triggers

    scenario = _make_scenario()
    assert _no_rsd_triggers("Let me walk you through this concept.", scenario) is True


def test_no_rsd_triggers_fail() -> None:
    from studyctl.eval.judge.heuristic import _no_rsd_triggers

    scenario = _make_scenario()
    # "simply" is in the trigger list
    assert _no_rsd_triggers("You simply need to add the @ symbol.", scenario) is False


def test_no_rsd_triggers_fail_case_insensitive() -> None:
    from studyctl.eval.judge.heuristic import _no_rsd_triggers

    scenario = _make_scenario()
    assert _no_rsd_triggers("It's Easy to understand.", scenario) is False


# ---------------------------------------------------------------------------
# references_topic
# ---------------------------------------------------------------------------


def test_references_topic_pass() -> None:
    from studyctl.eval.judge.heuristic import _references_topic

    scenario = _make_scenario(topic="Python decorators")
    assert _references_topic("Let us look at decorators in Python.", scenario) is True


def test_references_topic_fail() -> None:
    from studyctl.eval.judge.heuristic import _references_topic

    scenario = _make_scenario(topic="Python decorators")
    assert _references_topic("That is a really great attitude!", scenario) is False


def test_references_topic_skips_short_words() -> None:
    from studyctl.eval.judge.heuristic import _references_topic

    # Topic "to do" — "to" and "do" are both ≤2 chars so should be skipped
    # meaning the check effectively has no words to match → False
    scenario = _make_scenario(topic="to do")
    assert _references_topic("Let us walk through this together.", scenario) is False


# ---------------------------------------------------------------------------
# suggests_break
# ---------------------------------------------------------------------------


def test_suggests_break_pass() -> None:
    from studyctl.eval.judge.heuristic import _suggests_break

    scenario = _make_scenario()
    assert _suggests_break("Maybe take a short break and come back.", scenario) is True


def test_suggests_break_fail() -> None:
    from studyctl.eval.judge.heuristic import _suggests_break

    scenario = _make_scenario()
    assert _suggests_break("Let us keep going — you are doing great!", scenario) is False


# ---------------------------------------------------------------------------
# suggests_park
# ---------------------------------------------------------------------------


def test_suggests_park_pass() -> None:
    from studyctl.eval.judge.heuristic import _suggests_park

    scenario = _make_scenario()
    assert _suggests_park("We can save for later and come back to this.", scenario) is True


def test_suggests_park_fail() -> None:
    from studyctl.eval.judge.heuristic import _suggests_park

    scenario = _make_scenario()
    assert _suggests_park("Let us push through and keep going!", scenario) is False


# ---------------------------------------------------------------------------
# does_not_shame (alias of no_rsd_triggers)
# ---------------------------------------------------------------------------


def test_does_not_shame_pass() -> None:
    from studyctl.eval.judge.heuristic import _does_not_shame

    scenario = _make_scenario()
    assert _does_not_shame("Great thinking! What led you there?", scenario) is True


def test_does_not_shame_fail() -> None:
    from studyctl.eval.judge.heuristic import _does_not_shame

    scenario = _make_scenario()
    assert _does_not_shame("You should know this by now.", scenario) is False


# ---------------------------------------------------------------------------
# contains_positive_recognition
# ---------------------------------------------------------------------------


def test_contains_positive_recognition_pass() -> None:
    from studyctl.eval.judge.heuristic import _contains_positive_recognition

    scenario = _make_scenario()
    assert _contains_positive_recognition("Exactly! That is the right idea.", scenario) is True


def test_contains_positive_recognition_fail() -> None:
    from studyctl.eval.judge.heuristic import _contains_positive_recognition

    scenario = _make_scenario()
    assert (
        _contains_positive_recognition("Let me explain what a decorator does.", scenario) is False
    )


# ---------------------------------------------------------------------------
# recognition_is_specific
# ---------------------------------------------------------------------------


def test_recognition_is_specific_pass() -> None:
    from studyctl.eval.judge.heuristic import _recognition_is_specific

    scenario = _make_scenario(prompt="I think decorators wrap functions")
    response = "Exactly! You noticed that decorators wrap functions — that is the key insight."
    assert _recognition_is_specific(response, scenario) is True


def test_recognition_is_specific_fail_no_prompt_words() -> None:
    from studyctl.eval.judge.heuristic import _recognition_is_specific

    scenario = _make_scenario(prompt="I think decorators wrap functions")
    # Contains recognition language but does not echo any prompt content
    response = "Great job! You are really making progress."
    assert _recognition_is_specific(response, scenario) is False


def test_recognition_is_specific_fail_no_recognition_language() -> None:
    from studyctl.eval.judge.heuristic import _recognition_is_specific

    scenario = _make_scenario(prompt="I think decorators wrap functions")
    # Echoes prompt words but has no recognition language
    response = "Yes, decorators wrap functions by returning a new callable."
    assert _recognition_is_specific(response, scenario) is False


# ---------------------------------------------------------------------------
# run_heuristics integration tests
# ---------------------------------------------------------------------------


def test_run_heuristics_all_pass() -> None:
    from studyctl.eval.judge.heuristic import run_heuristics

    scenario = _make_scenario(
        topic="Python decorators",
        prompt="I think they wrap functions",
        heuristic_checks=["contains_question", "no_rsd_triggers", "references_topic"],
    )
    response = "Nice thinking! How do Python decorators change the wrapped function's behaviour?"
    result = run_heuristics(response, scenario)
    assert isinstance(result, HeuristicResult)
    assert result.passed is True
    assert result.checks == {
        "contains_question": True,
        "no_rsd_triggers": True,
        "references_topic": True,
    }
    assert result.messages == []


def test_run_heuristics_one_fails() -> None:
    from studyctl.eval.judge.heuristic import run_heuristics

    scenario = _make_scenario(
        topic="Python decorators",
        heuristic_checks=["contains_question", "no_rsd_triggers"],
    )
    # no_rsd_triggers will fail because of "simply"
    response = "You simply need to remember the @ symbol. How does that land?"
    result = run_heuristics(response, scenario)
    assert result.passed is False
    assert result.checks["contains_question"] is True
    assert result.checks["no_rsd_triggers"] is False
    assert "Failed: no_rsd_triggers" in result.messages


def test_unknown_check_fails() -> None:
    from studyctl.eval.judge.heuristic import run_heuristics

    scenario = _make_scenario(
        heuristic_checks=["contains_question", "nonexistent_check"],
    )
    response = "What do you think about this?"
    result = run_heuristics(response, scenario)
    assert result.passed is False
    assert result.checks["nonexistent_check"] is False
    assert any("Unknown check" in msg for msg in result.messages)


def test_empty_checks_passes() -> None:
    from studyctl.eval.judge.heuristic import run_heuristics

    scenario = _make_scenario(heuristic_checks=[])
    result = run_heuristics("Any response at all.", scenario)
    assert result.passed is True
    assert result.checks == {}
    assert result.messages == []
