"""API tests for the three topic exercise formats.

The security-shaped assertions matter as much as the happy paths: the attempt
endpoints must not ship the reference solution or the correct choice, or the
whole exercise is decorative.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from studyloop.planning.exercises import store as exercise_store
from studyloop.web.app import create_app

REFERENCE = """def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment
"""

RUBRIC = [
    {
        "title": "Defines the factory function",
        "weight": 1,
        "check": r"def\s+make_counter",
        "ask": "What has to exist before anything can be returned",
    },
    {
        "title": "Keeps state in the enclosing scope",
        "weight": 3,
        "check": r"nonlocal\s+\w+",
        "ask": "Where does the count have to live to survive between calls",
    },
]

QUESTIONS = [
    {
        "prompt": "What keeps a closure's variable alive?",
        "choices": [
            {"text": "The global namespace", "why": "globals are shared between counters"},
            {"text": "A cell object referenced by the function", "correct": True},
            {"text": "Nothing, it is copied", "why": "values are rebound, not copied"},
        ],
    }
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App with an isolated exercises directory."""
    monkeypatch.setenv(exercise_store.EXERCISES_DIR_ENV, str(tmp_path / "exercises"))
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def created(client):
    """A complete exercise set, created through the API."""
    response = client.post(
        "/api/exercises",
        json={
            "topic": "closures",
            "plan_id": "python",
            "concepts": ["closures"],
            "requirements": ["`make_counter()` returns a callable"],
            "rubric": RUBRIC,
            "reference_solution": REFERENCE,
            "questions": QUESTIONS,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["set"]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_produces_all_three_formats(created) -> None:
    formats = created["formats"]
    assert formats["blank_slate"] is not None
    assert formats["completion"] is not None
    assert formats["multiple_choice"]["answerable_count"] == 1
    assert created["missing_formats"] == []
    assert created["complete"] is True


def test_completion_is_derived_with_a_partial_scaffold(created) -> None:
    """One authored task, two code formats — differing only by scaffold."""
    blank = created["formats"]["blank_slate"]
    completion = created["formats"]["completion"]
    assert blank["has_starter_code"] is False
    assert blank["scaffold_ratio"] == 0.0
    assert completion["has_starter_code"] is True
    assert 0.0 < completion["scaffold_ratio"] < 1.0


def test_create_requires_a_topic(client) -> None:
    assert client.post("/api/exercises", json={}).status_code == 400


def test_duplicate_id_is_a_conflict(client, created) -> None:
    response = client.post(
        "/api/exercises",
        json={"topic": "closures", "plan_id": "python", "requirements": ["r"]},
    )
    # unique_set_id sidesteps the clash rather than failing — the second set gets
    # its own id, so both survive.
    assert response.status_code == 201
    assert response.json()["set"]["set_id"] != created["set_id"]


def test_create_from_markdown_import(client) -> None:
    document = """---
id: sql--windows
plan_id: sql
topic: window functions
---

# Window functions

## Blank Slate

### Requirements

- Rank rows within each partition

### Rubric

- [2] Uses a window function `(check: over\\s*\\()`

## Multiple Choice

### Q1 — What does PARTITION BY change?

- [ ] The row count `(why: it confuses windows with GROUP BY)`
- [x] The frame each row sees
"""
    response = client.post("/api/exercises", json={"markdown": document})
    assert response.status_code == 201, response.text
    assert response.json()["set"]["set_id"] == "sql--windows"


def test_create_from_a_plan_milestone(client) -> None:
    response = client.post(
        "/api/exercises",
        json={"plan_id": "python", "milestone": "Closures", "concepts": ["cell variables"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["set"]["concepts"] == ["cell variables"]
    # Drafted rubric has no check patterns, so it is honestly reported unready.
    assert body["readiness"]["ready"] is False


def test_unparseable_markdown_is_rejected(client) -> None:
    response = client.post("/api/exercises", json={"markdown": 12345})
    assert response.status_code in {400, 422}


# ---------------------------------------------------------------------------
# Read — and what must NOT be readable
# ---------------------------------------------------------------------------


def test_get_returns_the_three_formats_for_attempting(client, created) -> None:
    body = client.get(f"/api/exercises/{created['set_id']}").json()
    assert body["blank_slate"]["requirements"]
    assert body["blank_slate"]["starter_code"] == ""
    assert body["completion"]["starter_code"].strip()
    assert "TODO" in body["completion"]["starter_code"]
    assert len(body["multiple_choice"][0]["choices"]) == 3
    assert body["markdown"].startswith("---")


def test_attempt_payload_withholds_the_answer(client, created) -> None:
    """The default read cannot hand over the solution or the correct option."""
    body = client.get(f"/api/exercises/{created['set_id']}").json()

    assert "reference_solution" not in body["blank_slate"]
    assert "reference_solution" not in body["completion"]
    for question in body["multiple_choice"]:
        assert "correct" not in question
        for choice in question["choices"]:
            assert "correct" not in choice
            assert "why" not in choice

    # Rubric titles are shown (they are the brief); check patterns are not.
    for criterion in body["blank_slate"]["rubric"]:
        assert set(criterion) == {"title", "weight"}

    # The completion scaffold must not contain the hidden stateful line.
    assert "nonlocal count" not in body["completion"]["starter_code"]

    # And the rendered document must be redacted too — it is the same payload.
    assert "nonlocal count" not in body["markdown"]
    assert "- [x]" not in body["markdown"]


def test_whole_response_body_is_free_of_the_answer_key(client, created) -> None:
    """Belt and braces: scan the raw response text, not just the parsed fields.

    A field added later that happens to carry the solution would slip past
    field-by-field assertions; this catches it wherever it lands.
    """
    text = client.get(f"/api/exercises/{created['set_id']}").text
    assert "nonlocal count" not in text
    assert "count += 1" not in text
    assert '"correct"' not in text


def test_markdown_endpoint_is_redacted_by_default(client, created) -> None:
    """The 'view raw Markdown' link must not be a one-click answer key."""
    document = client.get(f"/api/exercises/{created['set_id']}/markdown").text
    assert "## Multiple Choice" in document
    assert "What keeps a closure's variable alive?" in document
    assert "nonlocal count" not in document
    assert "- [x]" not in document
    assert "(check:" not in document


def test_markdown_endpoint_serves_answers_to_authors_on_request(client, created) -> None:
    document = client.get(
        f"/api/exercises/{created['set_id']}/markdown",
        params={"include_reference": "true"},
    ).text
    assert "nonlocal count" in document
    assert "- [x]" in document


def test_reference_is_available_to_authors_on_request(client, created) -> None:
    body = client.get(
        f"/api/exercises/{created['set_id']}", params={"include_reference": "true"}
    ).json()
    assert "nonlocal count" in body["blank_slate"]["reference_solution"]
    assert body["multiple_choice"][0]["correct"] == [1]


def test_list_filters_by_plan(client, created) -> None:
    client.post("/api/exercises", json={"topic": "joins", "plan_id": "sql", "requirements": ["r"]})
    assert client.get("/api/exercises").json()["count"] == 2
    scoped = client.get("/api/exercises", params={"plan_id": "python"}).json()
    assert scoped["count"] == 1
    assert scoped["sets"][0]["set_id"] == created["set_id"]


def test_missing_set_is_404(client) -> None:
    assert client.get("/api/exercises/nope").status_code == 404


def test_path_traversal_is_rejected(client) -> None:
    assert client.get("/api/exercises/..%2F..%2Fetc%2Fpasswd").status_code in {400, 404}


# ---------------------------------------------------------------------------
# Review — one endpoint, three formats
# ---------------------------------------------------------------------------


def test_blank_slate_review_scores_and_mentors(client, created) -> None:
    response = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "blank_slate", "submission": "def make_counter():\n    pass\n"},
    )
    assert response.status_code == 200, response.text
    review = response.json()["review"]

    assert review["kind"] == "blank_slate"
    assert review["score"] == 25  # 1 of 4 weight
    assert review["band"] == "struggling"
    assert review["mentoring"], "an unmet criterion must raise a question"
    assert all(q.endswith("?") for q in review["mentoring"])


def test_completion_review_gives_no_credit_for_starter_code(client, created) -> None:
    """The invariant the shared pipeline exists to enforce."""
    detail = client.get(f"/api/exercises/{created['set_id']}").json()
    starter = detail["completion"]["starter_code"]

    review = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "completion", "submission": starter},
    ).json()["review"]

    assert review["score"] == 0
    assert review["authored_line_count"] == 0
    assert review["given_count"] >= 1
    assert any("starter code" in w for w in review["warnings"])


def test_finished_completion_scores_on_the_learners_delta(client, created) -> None:
    review = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "completion", "submission": REFERENCE},
    ).json()["review"]
    assert review["score"] == 100
    assert review["authored_line_count"] > 0
    assert review["given_count"] >= 1


def test_review_never_returns_the_reference_solution(client, created) -> None:
    response = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "blank_slate", "submission": "def make_counter(): pass"},
    )
    assert "nonlocal count" not in response.text
    assert "count += 1" not in response.text


def test_multiple_choice_review_mentors_from_the_misconception(client, created) -> None:
    review = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "multiple_choice", "answers": {"0": [0]}},
    ).json()["review"]

    assert review["kind"] == "multiple_choice"
    assert review["score"] == 0
    result = review["results"][0]
    assert result["is_correct"] is False
    assert result["misconceptions"] == ["globals are shared between counters"]
    assert result["question"].endswith("?")
    # Never name the right answer.
    assert "A cell object referenced by the function" not in result["question"]


def test_correct_multiple_choice_scores_full(client, created) -> None:
    review = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "multiple_choice", "answers": {"0": [1]}},
    ).json()["review"]
    assert review["score"] == 100
    assert review["correct_count"] == 1


def test_review_markdown_is_agent_pasteable(client, created) -> None:
    body = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "blank_slate", "submission": REFERENCE},
    ).json()
    assert "### Exercise review" in body["markdown"]
    assert "Score 100/100" in body["markdown"]


def test_review_rejects_an_unknown_kind(client, created) -> None:
    response = client.post(f"/api/exercises/{created['set_id']}/review", json={"kind": "essay"})
    assert response.status_code == 400


def test_review_rejects_malformed_answers(client, created) -> None:
    response = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "multiple_choice", "answers": {"zero": [0]}},
    )
    assert response.status_code == 400


def test_review_can_record_progress_evidence(client, created, monkeypatch) -> None:
    """A score with no consequence is a score nobody acts on."""
    calls: list[tuple] = []

    def fake_record(topic, concept, confidence, notes=None, **kwargs):
        calls.append((topic, concept, confidence, notes))
        return True

    monkeypatch.setattr("studyloop.history.progress.record_progress", fake_record)
    body = client.post(
        f"/api/exercises/{created['set_id']}/review",
        json={"kind": "blank_slate", "submission": REFERENCE, "record": True},
    ).json()

    assert body["recorded"] is True
    assert calls == [
        ("closures", "closures", "mastered", "exercise:blank_slate score=100 band=strong")
    ]


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------


def test_patch_replaces_the_document(client, created) -> None:
    """The author round trip: fetch WITH answers, edit, write back."""
    document = client.get(
        f"/api/exercises/{created['set_id']}/markdown",
        params={"include_reference": "true"},
    ).text
    updated = document.replace("_No notes._", "Revisit after the Glue milestone.")
    response = client.patch(f"/api/exercises/{created['set_id']}", json={"markdown": updated})
    assert response.status_code == 200, response.text

    round_tripped = client.get(
        f"/api/exercises/{created['set_id']}/markdown",
        params={"include_reference": "true"},
    ).text
    assert "Revisit after the Glue milestone." in round_tripped
    # The answers survived the edit.
    assert "nonlocal count" in round_tripped
    assert "- [x]" in round_tripped


def test_patching_back_the_redacted_document_is_refused(client, created) -> None:
    """The data-loss trap: a redacted body must not silently wipe the answers."""
    redacted = client.get(f"/api/exercises/{created['set_id']}/markdown").text
    response = client.patch(f"/api/exercises/{created['set_id']}", json={"markdown": redacted})

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "reference solution" in detail
    assert "include_reference=true" in detail

    # Nothing was written: the authored document is intact.
    intact = client.get(
        f"/api/exercises/{created['set_id']}/markdown",
        params={"include_reference": "true"},
    ).text
    assert "nonlocal count" in intact
    assert "- [x]" in intact


def test_intentional_answer_removal_can_be_forced(client, created) -> None:
    redacted = client.get(f"/api/exercises/{created['set_id']}/markdown").text
    response = client.patch(
        f"/api/exercises/{created['set_id']}",
        json={"markdown": redacted, "allow_answer_loss": True},
    )
    assert response.status_code == 200, response.text
    after = client.get(
        f"/api/exercises/{created['set_id']}/markdown",
        params={"include_reference": "true"},
    ).text
    assert "nonlocal count" not in after


def test_patch_rejects_unparseable_markdown(client, created) -> None:
    response = client.patch(f"/api/exercises/{created['set_id']}", json={"markdown": None})
    assert response.status_code in {400, 422}


def test_patch_updates_a_rubric(client, created) -> None:
    response = client.patch(
        f"/api/exercises/{created['set_id']}",
        json={
            "blank_slate": {"rubric": [{"title": "Only one thing", "weight": 5, "check": "def"}]}
        },
    )
    assert response.status_code == 200
    assert response.json()["set"]["formats"]["blank_slate"]["total_weight"] == 5


def test_delete_removes_the_set(client, created) -> None:
    assert client.delete(f"/api/exercises/{created['set_id']}").status_code == 200
    assert client.get(f"/api/exercises/{created['set_id']}").status_code == 404
    assert client.delete(f"/api/exercises/{created['set_id']}").status_code == 404
