"""Tests for the exercise MCP tools — called as plain Python functions.

The agent-facing surface needs the same guarantee as the HTTP one: a mentor agent
driving these tools must not be handed the answer while the learner is working.
"""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from studyloop.mcp.server import mcp
from studyloop.planning.exercises import store as exercise_store

REFERENCE = """def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment"""

AUTHORED = """---
id: python--closures
plan_id: python
topic: closures
concepts:
  - closures
---

# Closures

## Blank Slate

### Requirements

- `make_counter()` returns a callable that counts its own calls

### Rubric

- [1] Defines the factory `(check: def\\s+make_counter)` `(ask: What has to exist first)`
- [3] Keeps state in scope `(check: nonlocal\\s+\\w+)` `(ask: Where must the count live)`

### Reference Solution

```python
def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment
```

## Multiple Choice

### Q1 — What keeps a closure's variable alive?

- [ ] The global namespace `(why: globals are shared between counters)`
- [x] A cell object held by the function
"""


def _tool(name: str):
    tools = mcp._tool_manager._tools
    if name not in tools:
        msg = f"Tool {name!r} not found. Available: {sorted(tools)}"
        raise KeyError(msg)
    return tools[name].fn


@pytest.fixture(autouse=True)
def isolated_exercises(tmp_path, monkeypatch):
    monkeypatch.setenv(exercise_store.EXERCISES_DIR_ENV, str(tmp_path / "exercises"))


@pytest.fixture
def imported():
    return _tool("exercise_import")(markdown=AUTHORED)


def test_all_exercise_tools_are_registered() -> None:
    for name in (
        "exercise_list",
        "exercise_get",
        "exercise_review",
        "exercise_create",
        "exercise_import",
    ):
        assert _tool(name) is not None


def test_create_drafts_all_three_formats() -> None:
    result = _tool("exercise_create")(
        topic="closures",
        plan_id="python",
        requirements=["make_counter() returns a callable"],
        reference_solution=REFERENCE,
    )
    assert result["created"] is True
    formats = result["set"]["formats"]
    assert formats["blank_slate"] is not None
    assert formats["completion"] is not None
    assert formats["completion"]["has_starter_code"] is True
    # Nothing invented: no rubric checks, no quiz — reported, not fabricated.
    assert result["readiness"]["ready"] is False


def test_create_requires_a_topic() -> None:
    with pytest.raises(Exception, match="topic is required"):
        _tool("exercise_create")(topic="   ")


def test_import_parses_an_authored_document(imported) -> None:
    assert imported["created"] is True
    assert imported["set"]["set_id"] == "python--closures"
    assert imported["readiness"]["missing_formats"] == ["completion"]


def test_import_rejects_an_empty_document() -> None:
    with pytest.raises(Exception, match="markdown is required"):
        _tool("exercise_import")(markdown="  ")


def test_list_reports_missing_formats(imported) -> None:
    result = _tool("exercise_list")(plan_id="python")
    assert result["count"] == 1
    assert result["sets"][0]["missing_formats"] == ["completion"]


def test_get_withholds_the_answer_by_default(imported) -> None:
    """An agent that has not read the solution cannot leak it."""
    payload = _tool("exercise_get")(set_id="python--closures")

    assert "reference_solution" not in payload["blank_slate"]
    assert "nonlocal count" not in payload["markdown"]
    assert "- [x]" not in payload["markdown"]
    for criterion in payload["blank_slate"]["rubric"]:
        assert set(criterion) == {"title", "weight"}
    for choice in payload["multiple_choice"][0]["choices"]:
        assert set(choice) == {"label", "text"}


def test_get_serves_answers_to_authors_on_request(imported) -> None:
    payload = _tool("exercise_get")(set_id="python--closures", include_answers=True)
    assert "nonlocal count" in payload["blank_slate"]["reference_solution"]
    assert any(c.get("correct") for c in payload["multiple_choice"][0]["choices"])


def test_get_rejects_an_unknown_set() -> None:
    with pytest.raises(Exception, match="no exercise set"):
        _tool("exercise_get")(set_id="nope")


def test_review_scores_and_returns_questions(imported) -> None:
    result = _tool("exercise_review")(
        set_id="python--closures",
        kind="blank_slate",
        submission="def make_counter():\n    pass\n",
    )
    review = result["review"]
    assert review["score"] == 25
    assert review["mentoring"]
    assert all(q.endswith("?") for q in review["mentoring"])
    # The review payload is what the agent sees — it must not carry the answer.
    assert "nonlocal count" not in result["markdown"]


def test_review_of_multiple_choice_mentors_from_the_misconception(imported) -> None:
    result = _tool("exercise_review")(
        set_id="python--closures",
        kind="multiple_choice",
        answers={"0": [0]},
    )
    review = result["review"]
    assert review["score"] == 0
    question = review["results"][0]["question"]
    assert "globals are shared" in question
    assert question.endswith("?")
    assert "A cell object held by the function" not in question


def test_review_rejects_an_unknown_kind(imported) -> None:
    with pytest.raises(Exception, match="kind must be one of"):
        _tool("exercise_review")(set_id="python--closures", kind="essay")


def test_review_rejects_malformed_answers(imported) -> None:
    with pytest.raises(Exception, match="question indexes"):
        _tool("exercise_review")(
            set_id="python--closures",
            kind="multiple_choice",
            answers={"zero": [0]},
        )


def test_review_rejects_a_missing_format(imported) -> None:
    with pytest.raises(Exception, match="no 'completion' exercise"):
        _tool("exercise_review")(set_id="python--closures", kind="completion", submission="x")


def test_review_can_record_progress(imported, monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_record(topic, concept, confidence, notes=None, **kwargs):
        calls.append((topic, concept, confidence))
        return True

    monkeypatch.setattr("studyloop.history.progress.record_progress", fake_record)
    result = _tool("exercise_review")(
        set_id="python--closures",
        kind="blank_slate",
        submission=REFERENCE,
        record=True,
    )
    assert result["recorded"] is True
    assert calls == [("closures", "closures", "mastered")]
