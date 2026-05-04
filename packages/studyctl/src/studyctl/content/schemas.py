"""Pydantic schemas for the flashcard/quiz JSON contract.

This module defines the **write-side validation layer** for content generators
(Ollama, NotebookLM, MCP tools, session cleanup). Any generator that produces
output validated by these schemas writes JSON that ``review_loader`` can
consume.

The on-disk JSON shape is the *interface*. These pydantic models exist to
guarantee that the write side produces conformant output. The read side
(``studyctl.review_loader``) uses lenient dataclasses and skips malformed
records with a warning -- correct behaviour for resilience against partial
or in-progress content.

File layout expected by ``review_loader``:

- ``<course>/flashcards/<slug>-flashcards.json`` -- matches ``*-flashcards.json``
- ``<course>/quizzes/<slug>-quiz.json`` -- matches ``*-quiz.json``

Both studyctl's loader and the reference ``notebooklm_pdf_by_chapters`` loader
accept these globs. Writing with the hyphen-prefixed suffix keeps output
portable to both.

JSON contract (authoritative -- mirrors ``studyctl/review_loader.py`` docstring):

Flashcard deck::

    {
        "title": "Chapter Name",
        "cards": [
            {"front": "Question?", "back": "Answer."},
            ...
        ]
    }

Quiz deck::

    {
        "title": "Chapter Name",
        "questions": [
            {
                "question": "What is X?",
                "hint": "optional hint",
                "answerOptions": [
                    {"text": "A", "isCorrect": true,  "rationale": "because..."},
                    {"text": "B", "isCorrect": false, "rationale": "not quite"},
                    ...
                ]
            },
            ...
        ]
    }

Field names are **camelCase** on disk (``isCorrect``, ``answerOptions``) to
match the existing NotebookLM-generated JSON and the reference repo. The
loader dataclasses use snake_case internally -- the loader does the
translation when parsing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Flashcard schemas
# ---------------------------------------------------------------------------

NonEmptyStr = Annotated[str, Field(min_length=1)]


class FlashcardItem(BaseModel):
    """A single flashcard with a front (prompt) and back (answer).

    The ``front`` is used to compute the card's stable hash for spaced
    repetition tracking (see ``review_loader.Flashcard.card_hash``), so
    duplicate fronts within a deck produce duplicate hashes. The schema
    does not enforce uniqueness -- that's a generator-level concern if
    it matters for a given use case.
    """

    front: NonEmptyStr
    back: NonEmptyStr

    model_config = {"extra": "forbid"}


class FlashcardDeck(BaseModel):
    """A deck of flashcards for a single chapter / study note.

    One deck produces one ``*-flashcards.json`` file on disk.
    """

    title: NonEmptyStr
    cards: list[FlashcardItem] = Field(min_length=1)

    model_config = {"extra": "forbid"}

    def write_json(self, directory: Path, slug: str) -> Path:
        """Write this deck to ``directory/<slug>-flashcards.json``.

        Creates ``directory`` if it doesn't exist. The slug should be
        filesystem-safe; callers are responsible for slugification.

        Returns the path written.
        """
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{slug}-flashcards.json"
        path.write_text(
            json.dumps(
                self.model_dump(mode="json", by_alias=True),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path


# ---------------------------------------------------------------------------
# Quiz schemas
# ---------------------------------------------------------------------------


class QuizOption(BaseModel):
    """A single answer option within a quiz question.

    ``is_correct`` defaults to False so that the producer only has to mark
    the correct option explicitly. ``rationale`` is optional but strongly
    encouraged -- the web UI shows it as feedback after the user answers.

    On-disk JSON field is ``isCorrect`` (camelCase) to match the existing
    NotebookLM-generated format and the reference ``notebooklm_pdf_by_chapters``
    repo. The Python attribute is snake_case; the alias bridges the two.
    """

    text: NonEmptyStr
    is_correct: bool = Field(default=False, alias="isCorrect")
    rationale: str = ""

    model_config = {"extra": "forbid", "populate_by_name": True}


class QuizQuestion(BaseModel):
    """A multiple-choice quiz question.

    On-disk JSON field is ``answerOptions`` (camelCase) to match the
    existing contract. The Python attribute is ``answer_options``
    (snake_case); the alias bridges the two.

    Invariants (enforced by ``_check_exactly_one_correct``):
    - ``answer_options`` has at least 2 entries (a single-option question is
      degenerate; the web UI expects multiple choice).
    - Exactly one option has ``is_correct=True``. Zero-correct and
      multiple-correct are both rejected. This matches the existing loader
      and web-UI assumption that each question has a unique correct answer.
    """

    question: NonEmptyStr
    hint: str = ""
    answer_options: list[QuizOption] = Field(min_length=2, alias="answerOptions")

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def _check_exactly_one_correct(self) -> QuizQuestion:
        correct_count = sum(1 for opt in self.answer_options if opt.is_correct)
        if correct_count != 1:
            raise ValueError(
                f"Quiz question must have exactly one correct answer, "
                f"got {correct_count} (question: {self.question[:60]!r})"
            )
        return self


class QuizDeck(BaseModel):
    """A deck of quiz questions for a single chapter / study note.

    One deck produces one ``*-quiz.json`` file on disk.
    """

    title: NonEmptyStr
    questions: list[QuizQuestion] = Field(min_length=1)

    model_config = {"extra": "forbid"}

    def write_json(self, directory: Path, slug: str) -> Path:
        """Write this deck to ``directory/<slug>-quiz.json``.

        Creates ``directory`` if it doesn't exist. Returns the path written.
        """
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{slug}-quiz.json"
        path.write_text(
            json.dumps(
                self.model_dump(mode="json", by_alias=True),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path


# ---------------------------------------------------------------------------
# JSON-schema helpers for LLM prompting (used by D2)
# ---------------------------------------------------------------------------


def flashcard_deck_json_schema() -> dict:
    """Return the JSON schema for ``FlashcardDeck``.

    D2's ``OllamaGenerator`` passes this to Ollama's ``/api/chat`` endpoint
    via the ``format`` parameter so the model is constrained to produce
    schema-conformant output. Extracting it here keeps D2 generator code
    small and centralises the schema logic in D1.
    """
    return FlashcardDeck.model_json_schema()


def quiz_deck_json_schema() -> dict:
    """Return the JSON schema for ``QuizDeck``. See ``flashcard_deck_json_schema``."""
    return QuizDeck.model_json_schema()
