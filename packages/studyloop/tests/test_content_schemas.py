"""Unit tests for the flashcard/quiz JSON contract schemas (D1).

Coverage:
- Happy path: valid decks round-trip through pydantic and through the
  existing ``review_loader`` unchanged.
- Validation: missing fields, empty fields, and quiz-level invariants
  (min 2 options, exactly one correct) are rejected.
- On-disk: ``write_json`` produces files that match the ``*-flashcards.json``
  / ``*-quiz.json`` glob and are consumable by ``review_loader``.
- JSON-schema helpers: ``*_json_schema()`` return schemas the LLM can use.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pydantic = pytest.importorskip("pydantic")
from pydantic import ValidationError  # noqa: E402

from studyloop.content.schemas import (  # noqa: E402
    FlashcardDeck,
    FlashcardItem,
    PracticeDeck,
    PracticeTask,
    QuizDeck,
    QuizOption,
    QuizQuestion,
    flashcard_deck_json_schema,
    practice_deck_json_schema,
    quiz_deck_json_schema,
)
from studyloop.review_loader import load_flashcards, load_quizzes  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures — minimal, hand-rolled, match the reference repo's JSON shape.
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_flashcard_payload() -> dict:
    return {
        "title": "Python Collections",
        "cards": [
            {"front": "What does Counter do?", "back": "Counts hashable objects."},
            {"front": "When to use deque?", "back": "For fast appends/pops at both ends."},
        ],
    }


@pytest.fixture
def valid_quiz_payload() -> dict:
    return {
        "title": "Python Collections",
        "questions": [
            {
                "question": "Which collection is O(1) for left-append?",
                "hint": "Think about double-ended queues.",
                "answerOptions": [
                    {"text": "list", "isCorrect": False, "rationale": "list.insert(0, x) is O(n)."},
                    {"text": "deque", "isCorrect": True, "rationale": "appendleft is O(1)."},
                    {"text": "tuple", "isCorrect": False, "rationale": "tuples are immutable."},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_flashcard_deck_valid_payload_parses(valid_flashcard_payload: dict) -> None:
    deck = FlashcardDeck.model_validate(valid_flashcard_payload)
    assert deck.title == "Python Collections"
    assert len(deck.cards) == 2
    assert deck.cards[0].front == "What does Counter do?"


def test_quiz_deck_valid_payload_parses(valid_quiz_payload: dict) -> None:
    deck = QuizDeck.model_validate(valid_quiz_payload)
    assert deck.title == "Python Collections"
    assert len(deck.questions) == 1
    q = deck.questions[0]
    assert len(q.answer_options) == 3
    correct = [o for o in q.answer_options if o.is_correct]
    assert len(correct) == 1
    assert correct[0].text == "deque"


def test_practice_deck_valid_payload_parses() -> None:
    deck = PracticeDeck.model_validate(
        {
            "title": "SQL Joins",
            "tasks": [
                {
                    "taskType": "debug",
                    "prompt": "Fix the LEFT JOIN that accidentally filters null matches.",
                    "setup": (
                        "SELECT * FROM orders LEFT JOIN customers "
                        "... WHERE customers.region = 'EU'"
                    ),
                    "successCriteria": ["Unmatched orders remain in the result"],
                    "hint": "Move the right-table filter into the join condition.",
                    "expectedLearningOutcome": "Preserve outer join semantics under filtering.",
                }
            ],
        }
    )

    assert deck.title == "SQL Joins"
    assert deck.tasks[0].task_type == "debug"
    assert deck.tasks[0].success_criteria == ["Unmatched orders remain in the result"]


def test_flashcard_roundtrip_through_json(valid_flashcard_payload: dict) -> None:
    deck = FlashcardDeck.model_validate(valid_flashcard_payload)
    serialised = deck.model_dump(mode="json")
    reparsed = FlashcardDeck.model_validate(serialised)
    assert deck == reparsed


def test_quiz_roundtrip_through_json(valid_quiz_payload: dict) -> None:
    deck = QuizDeck.model_validate(valid_quiz_payload)
    serialised = deck.model_dump(mode="json")
    reparsed = QuizDeck.model_validate(serialised)
    assert deck == reparsed


# ---------------------------------------------------------------------------
# Write-side validation failures
# ---------------------------------------------------------------------------


def test_flashcard_rejects_missing_front() -> None:
    with pytest.raises(ValidationError):
        FlashcardItem.model_validate({"back": "answer only"})


def test_flashcard_rejects_empty_front() -> None:
    with pytest.raises(ValidationError):
        FlashcardItem.model_validate({"front": "", "back": "answer"})


def test_flashcard_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        FlashcardItem.model_validate({"front": "q", "back": "a", "rogue": "x"})


def test_flashcard_deck_rejects_empty_cards() -> None:
    with pytest.raises(ValidationError):
        FlashcardDeck.model_validate({"title": "Empty", "cards": []})


def test_quiz_rejects_fewer_than_two_options() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate(
            {
                "question": "Only one option?",
                "answerOptions": [{"text": "A", "isCorrect": True}],
            }
        )


def test_quiz_rejects_zero_correct_options() -> None:
    with pytest.raises(ValidationError, match="exactly one correct"):
        QuizQuestion.model_validate(
            {
                "question": "No right answer?",
                "answerOptions": [
                    {"text": "A", "isCorrect": False},
                    {"text": "B", "isCorrect": False},
                ],
            }
        )


def test_quiz_rejects_multiple_correct_options() -> None:
    with pytest.raises(ValidationError, match="exactly one correct"):
        QuizQuestion.model_validate(
            {
                "question": "Too many right answers?",
                "answerOptions": [
                    {"text": "A", "isCorrect": True},
                    {"text": "B", "isCorrect": True},
                ],
            }
        )


def test_quiz_deck_rejects_empty_questions() -> None:
    with pytest.raises(ValidationError):
        QuizDeck.model_validate({"title": "Empty", "questions": []})


def test_practice_task_rejects_invalid_task_type() -> None:
    with pytest.raises(ValidationError):
        PracticeTask.model_validate(
            {
                "taskType": "essay",
                "prompt": "Reflect on joins.",
                "successCriteria": ["A concrete answer exists"],
                "expectedLearningOutcome": "Know joins.",
            }
        )


def test_practice_deck_rejects_empty_tasks() -> None:
    with pytest.raises(ValidationError):
        PracticeDeck.model_validate({"title": "Empty", "tasks": []})


# ---------------------------------------------------------------------------
# On-disk output + review_loader compat
# ---------------------------------------------------------------------------


def test_flashcard_write_json_glob_friendly(tmp_path: Path, valid_flashcard_payload: dict) -> None:
    deck = FlashcardDeck.model_validate(valid_flashcard_payload)
    written = deck.write_json(tmp_path, slug="python-collections")
    assert written.name == "python-collections-flashcards.json"
    assert written.exists()

    # Matches both the reference repo's strict glob and studyloop's looser glob
    matches_strict = list(tmp_path.glob("*-flashcards.json"))
    matches_loose = list(tmp_path.glob("*flashcards.json"))
    assert [p.name for p in matches_strict] == ["python-collections-flashcards.json"]
    assert [p.name for p in matches_loose] == ["python-collections-flashcards.json"]


def test_quiz_write_json_glob_friendly(tmp_path: Path, valid_quiz_payload: dict) -> None:
    deck = QuizDeck.model_validate(valid_quiz_payload)
    written = deck.write_json(tmp_path, slug="python-collections")
    assert written.name == "python-collections-quiz.json"

    matches_strict = list(tmp_path.glob("*-quiz.json"))
    matches_loose = list(tmp_path.glob("*quiz.json"))
    assert [p.name for p in matches_strict] == ["python-collections-quiz.json"]
    assert [p.name for p in matches_loose] == ["python-collections-quiz.json"]


def test_practice_write_json_glob_friendly(tmp_path: Path) -> None:
    deck = PracticeDeck.model_validate(
        {
            "title": "Spark Partitioning",
            "tasks": [
                {
                    "taskType": "trace",
                    "prompt": "Trace which partition each key lands in.",
                    "setup": "keys = [1, 2, 3]",
                    "successCriteria": ["Each key has a partition assignment"],
                    "expectedLearningOutcome": "Understand hash partition distribution.",
                }
            ],
        }
    )
    written = deck.write_json(tmp_path, slug="spark-partitioning")
    assert written.name == "spark-partitioning-practice.json"
    assert written.exists()

    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["tasks"][0]["taskType"] == "trace"
    assert payload["tasks"][0]["successCriteria"] == ["Each key has a partition assignment"]


def test_flashcard_written_file_loads_via_review_loader(
    tmp_path: Path, valid_flashcard_payload: dict
) -> None:
    """Files we write must be consumable by the existing loader unchanged.

    This is the critical contract test: write-side and read-side agree.
    """
    deck = FlashcardDeck.model_validate(valid_flashcard_payload)
    deck.write_json(tmp_path, slug="python-collections")

    loaded = load_flashcards(tmp_path)
    assert len(loaded) == 2
    assert loaded[0].front == "What does Counter do?"
    assert loaded[0].back == "Counts hashable objects."
    assert loaded[0].source == "Python Collections"  # loader uses deck title as source


def test_quiz_written_file_loads_via_review_loader(
    tmp_path: Path, valid_quiz_payload: dict
) -> None:
    deck = QuizDeck.model_validate(valid_quiz_payload)
    deck.write_json(tmp_path, slug="python-collections")

    loaded = load_quizzes(tmp_path)
    assert len(loaded) == 1
    q = loaded[0]
    assert q.question == "Which collection is O(1) for left-append?"
    assert len(q.options) == 3
    correct = [o for o in q.options if o.is_correct]
    assert len(correct) == 1
    assert correct[0].text == "deque"


def test_write_json_creates_parent_directory(tmp_path: Path, valid_flashcard_payload: dict) -> None:
    deep = tmp_path / "nested" / "flashcards"
    assert not deep.exists()
    deck = FlashcardDeck.model_validate(valid_flashcard_payload)
    deck.write_json(deep, slug="test")
    assert deep.is_dir()
    assert (deep / "test-flashcards.json").is_file()


def test_write_json_emits_utf8_unicode(tmp_path: Path) -> None:
    """Unicode in card content round-trips correctly (not escaped to \\u…)."""
    deck = FlashcardDeck.model_validate(
        {
            "title": "Unicode — straight quotes vs curly",
            "cards": [{"front": "What is π?", "back": "≈ 3.14159"}],
        }
    )
    path = deck.write_json(tmp_path, slug="unicode")
    text = path.read_text(encoding="utf-8")
    # ensure_ascii=False means literal unicode, not \u escapes
    assert "π" in text
    assert "≈" in text
    assert "\\u" not in text


def test_practice_deck_json_schema_contains_hands_on_fields() -> None:
    schema = practice_deck_json_schema()
    task_props = schema["$defs"]["PracticeTask"]["properties"]
    assert "taskType" in task_props
    assert "successCriteria" in task_props
    assert "expectedLearningOutcome" in task_props


# ---------------------------------------------------------------------------
# JSON-schema helpers (used by D2 for LLM JSON-mode prompting)
# ---------------------------------------------------------------------------


def test_flashcard_json_schema_is_valid_json() -> None:
    schema = flashcard_deck_json_schema()
    # Must be JSON-serialisable (Ollama takes this as a dict, but Ollama's
    # HTTP client serialises it).
    json.dumps(schema)

    assert schema["type"] == "object"
    props = schema["properties"]
    assert "title" in props
    assert "cards" in props
    # cards is an array of FlashcardItem (via $ref)
    assert props["cards"]["type"] == "array"


def test_quiz_json_schema_is_valid_json() -> None:
    schema = quiz_deck_json_schema()
    json.dumps(schema)

    props = schema["properties"]
    assert "title" in props
    assert "questions" in props
    assert props["questions"]["type"] == "array"


def test_quiz_option_default_iscorrect_is_false() -> None:
    """Producer can omit ``isCorrect`` on incorrect options. Cleaner prompting."""
    opt = QuizOption.model_validate({"text": "B"})
    assert opt.is_correct is False
    assert opt.rationale == ""


def test_quiz_on_disk_uses_camelcase_aliases(tmp_path, valid_quiz_payload: dict) -> None:
    """Critical contract: JSON on disk must use camelCase (isCorrect, answerOptions).

    Python attributes are snake_case for PEP 8 compliance, but the wire format
    is camelCase to match NotebookLM and the reference notebooklm_pdf_by_chapters
    repo. An alias failure here would break loader compatibility silently.
    """
    deck = QuizDeck.model_validate(valid_quiz_payload)
    path = deck.write_json(tmp_path, slug="camelcase-check")
    raw = path.read_text(encoding="utf-8")

    assert "answerOptions" in raw
    assert "isCorrect" in raw
    assert "answer_options" not in raw  # snake_case must not leak to disk
    assert "is_correct" not in raw
