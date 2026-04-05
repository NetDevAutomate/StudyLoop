"""Tests for LLMJudge — the LLM-backed rubric scorer.

Uses unittest.mock to avoid real HTTP calls.
All fixtures are inline (no conftest.py).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from studyctl.eval.judge.llm import LLMJudge
from studyctl.eval.llm_client import LLMClientError
from studyctl.eval.models import Scenario

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_JSON = json.dumps(
    {
        "clarity": 3,
        "socratic_quality": 4,
        "emotional_safety": 3,
        "energy_adaptation": 2,
        "tool_usage": 3,
        "topic_focus": 4,
        "win_recognition": 2,
    }
)

_ALL_DIMENSIONS = [
    "clarity",
    "socratic_quality",
    "emotional_safety",
    "energy_adaptation",
    "tool_usage",
    "topic_focus",
    "win_recognition",
]


def _make_scenario(
    *,
    heuristic_checks: list[str] | None = None,
    topic: str = "Python decorators",
    prompt: str = "How do decorators work?",
    energy: int = 7,
    elapsed_minutes: int = 15,
) -> Scenario:
    return Scenario(
        id="test-001",
        name="Test Scenario",
        priority="high",
        topic=topic,
        energy=energy,
        prompt=prompt,
        elapsed_minutes=elapsed_minutes,
        heuristic_checks=heuristic_checks or [],
        rubric_weights=dict.fromkeys(_ALL_DIMENSIONS, 1.0),
    )


def _mock_client(return_value: str = _VALID_JSON) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = return_value
    return client


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def test_builds_prompt_with_scenario_context() -> None:
    """The prompt passed to client.chat() must embed all scenario fields."""
    scenario = _make_scenario(
        topic="Python decorators",
        prompt="How do decorators work?",
        energy=7,
        elapsed_minutes=15,
    )
    client = _mock_client()
    judge = LLMJudge(client)
    response = "What do you think a decorator does to the function it wraps?"

    judge.score(scenario, response)

    # client.chat was called once
    assert client.chat.call_count == 1
    sent_messages = client.chat.call_args[0][0]  # positional arg 0
    assert len(sent_messages) == 1
    prompt_text = sent_messages[0]["content"]

    assert "Test Scenario" in prompt_text
    assert "7" in prompt_text  # energy
    assert "15" in prompt_text  # elapsed_minutes
    assert "Python decorators" in prompt_text
    assert "How do decorators work?" in prompt_text
    assert "What do you think a decorator does" in prompt_text


# ---------------------------------------------------------------------------
# Score parsing
# ---------------------------------------------------------------------------


def test_parses_valid_json_scores() -> None:
    """All seven dimensions are extracted with correct integer values."""
    client = _mock_client(_VALID_JSON)
    judge = LLMJudge(client)
    result = judge.score(_make_scenario(), "A response about Python decorators?")

    assert result.heuristic_pass is True
    assert result.dimensions == {
        "clarity": 3,
        "socratic_quality": 4,
        "emotional_safety": 3,
        "energy_adaptation": 2,
        "tool_usage": 3,
        "topic_focus": 4,
        "win_recognition": 2,
    }


def test_clamps_out_of_range_high() -> None:
    """Scores above 4 are clamped to 4."""
    high_scores = dict.fromkeys(_ALL_DIMENSIONS, 5)
    client = _mock_client(json.dumps(high_scores))
    judge = LLMJudge(client)
    result = judge.score(_make_scenario(), "A response about Python decorators?")

    for dim in _ALL_DIMENSIONS:
        assert result.dimensions[dim] == 4, f"{dim} should be clamped to 4"


def test_clamps_out_of_range_low() -> None:
    """Scores below 1 are clamped to 1."""
    low_scores = dict.fromkeys(_ALL_DIMENSIONS, 0)
    client = _mock_client(json.dumps(low_scores))
    judge = LLMJudge(client)
    result = judge.score(_make_scenario(), "A response about Python decorators?")

    for dim in _ALL_DIMENSIONS:
        assert result.dimensions[dim] == 1, f"{dim} should be clamped to 1"


def test_malformed_json_returns_ones() -> None:
    """Completely unparseable response → all dimensions default to 1."""
    client = _mock_client("this is not json at all")
    judge = LLMJudge(client)
    result = judge.score(_make_scenario(), "A response about Python decorators?")

    assert result.heuristic_pass is True
    for dim in _ALL_DIMENSIONS:
        assert result.dimensions[dim] == 1, f"{dim} should default to 1"


def test_json_with_surrounding_text() -> None:
    """JSON embedded in surrounding prose is still extracted and parsed."""
    surrounded = f"Here are the scores: {_VALID_JSON} That's my assessment."
    client = _mock_client(surrounded)
    judge = LLMJudge(client)
    result = judge.score(_make_scenario(), "A response about Python decorators?")

    assert result.dimensions["clarity"] == 3
    assert result.dimensions["socratic_quality"] == 4


def test_missing_dimension_defaults_to_one() -> None:
    """A dimension absent from the LLM's JSON → defaults to 1."""
    partial = {d: 3 for d in _ALL_DIMENSIONS if d != "win_recognition"}
    client = _mock_client(json.dumps(partial))
    judge = LLMJudge(client)
    result = judge.score(_make_scenario(), "A response about Python decorators?")

    assert result.dimensions["win_recognition"] == 1
    # Other dimensions are still present
    for dim in _ALL_DIMENSIONS:
        if dim != "win_recognition":
            assert result.dimensions[dim] == 3


# ---------------------------------------------------------------------------
# Heuristic gating
# ---------------------------------------------------------------------------


def test_heuristic_fail_skips_llm() -> None:
    """If heuristic checks fail, client.chat() must never be called."""
    # contains_question fails when response has no "?"
    scenario = _make_scenario(heuristic_checks=["contains_question"])
    client = _mock_client()
    judge = LLMJudge(client)

    result = judge.score(scenario, "No question mark in this response at all.")

    client.chat.assert_not_called()
    assert result.heuristic_pass is False
    assert result.dimensions == {}


def test_llm_error_returns_empty_dimensions() -> None:
    """LLMClientError → heuristic_pass=True but dimensions={} and raw_response='LLM_ERROR'."""
    # Use references_topic with a response containing the topic word so heuristic passes
    scenario = _make_scenario(
        heuristic_checks=["references_topic"],
        topic="Python decorators",
    )
    client = MagicMock()
    client.chat.side_effect = LLMClientError("connection refused")
    judge = LLMJudge(client)

    result = judge.score(scenario, "Python decorators are interesting.")

    assert result.heuristic_pass is True
    assert result.dimensions == {}
    assert result.raw_response == "LLM_ERROR"
