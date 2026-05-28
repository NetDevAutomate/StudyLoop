"""Tests for the on-existing-file helpers (U6).

Two surfaces:

1. ``storage.next_unique_path`` -- filesystem helper for the
   ``on_existing="suffix"`` policy.
2. ``FlashcardDeck.merge_dedupe`` / ``QuizDeck.merge_dedupe`` -- pure
   pydantic helpers for the ``on_existing="merge"`` policy.

Pydantic merges have no I/O so they're fast unit tests; the path
helper writes/touches under tmp_path.
"""

from __future__ import annotations

from pathlib import Path

from studyloop.content.schemas import (
    FlashcardDeck,
    FlashcardItem,
    QuizDeck,
    QuizOption,
    QuizQuestion,
)
from studyloop.content.storage import next_unique_path


# ---------------------------------------------------------------------------
# next_unique_path
# ---------------------------------------------------------------------------


class TestNextUniquePath:
    def test_returns_base_when_unused(self, tmp_path: Path) -> None:
        path = next_unique_path(tmp_path, "deck", ".json")
        assert path == tmp_path / "deck.json"

    def test_appends_suffix_when_base_exists(self, tmp_path: Path) -> None:
        (tmp_path / "deck.json").write_text("existing")
        path = next_unique_path(tmp_path, "deck", ".json")
        assert path == tmp_path / "deck-1.json"

    def test_increments_until_free(self, tmp_path: Path) -> None:
        (tmp_path / "deck.json").write_text("0")
        (tmp_path / "deck-1.json").write_text("1")
        (tmp_path / "deck-2.json").write_text("2")
        path = next_unique_path(tmp_path, "deck", ".json")
        assert path == tmp_path / "deck-3.json"

    def test_dotted_suffix_normalised(self, tmp_path: Path) -> None:
        # Caller passing ``json`` instead of ``.json`` shouldn't break.
        path = next_unique_path(tmp_path, "deck", "json")
        assert path == tmp_path / "deck.json"


# ---------------------------------------------------------------------------
# FlashcardDeck.merge_dedupe
# ---------------------------------------------------------------------------


def _flashcard(front: str, back: str) -> FlashcardItem:
    return FlashcardItem(front=front, back=back)


class TestFlashcardMerge:
    def test_merging_disjoint_decks_concatenates(self) -> None:
        a = FlashcardDeck(
            title="Deck A",
            cards=[_flashcard("Q1", "A1"), _flashcard("Q2", "A2")],
        )
        b = FlashcardDeck(title="Deck B", cards=[_flashcard("Q3", "A3")])
        merged = a.merge_dedupe(b)
        assert len(merged.cards) == 3
        # Self's title wins.
        assert merged.title == "Deck A"

    def test_merging_with_full_overlap_halves(self) -> None:
        cards = [_flashcard("same Q", "A")]
        a = FlashcardDeck(title="A", cards=cards)
        b = FlashcardDeck(title="B", cards=cards)
        merged = a.merge_dedupe(b)
        assert len(merged.cards) == 1

    def test_dedupe_normalises_case_and_whitespace(self) -> None:
        a = FlashcardDeck(title="A", cards=[_flashcard("WHAT IS X?", "first answer")])
        b = FlashcardDeck(title="B", cards=[_flashcard("  what is x?  ", "second answer")])
        merged = a.merge_dedupe(b)
        # Self wins -- second answer should NOT survive.
        assert len(merged.cards) == 1
        assert merged.cards[0].back == "first answer"

    def test_inputs_unmodified(self) -> None:
        a = FlashcardDeck(title="A", cards=[_flashcard("Q", "A")])
        b = FlashcardDeck(title="B", cards=[_flashcard("Q", "Z")])
        original_a_len = len(a.cards)
        original_b_len = len(b.cards)
        a.merge_dedupe(b)
        assert len(a.cards) == original_a_len
        assert len(b.cards) == original_b_len


# ---------------------------------------------------------------------------
# QuizDeck.merge_dedupe
# ---------------------------------------------------------------------------


def _quiz_q(question: str, correct_text: str = "yes") -> QuizQuestion:
    return QuizQuestion(
        question=question,
        answer_options=[
            QuizOption(text=correct_text, is_correct=True, rationale="ok"),
            QuizOption(text="wrong", is_correct=False, rationale="no"),
        ],
    )


class TestQuizMerge:
    def test_merging_disjoint_decks_concatenates(self) -> None:
        a = QuizDeck(title="A", questions=[_quiz_q("Q1?")])
        b = QuizDeck(title="B", questions=[_quiz_q("Q2?")])
        merged = a.merge_dedupe(b)
        assert len(merged.questions) == 2

    def test_dedupe_by_question_text(self) -> None:
        a = QuizDeck(title="A", questions=[_quiz_q("Same Q?", correct_text="apple")])
        b = QuizDeck(title="B", questions=[_quiz_q("same q?", correct_text="banana")])
        merged = a.merge_dedupe(b)
        assert len(merged.questions) == 1
        # Self wins -- "apple" survives.
        correct = next(o for o in merged.questions[0].answer_options if o.is_correct)
        assert correct.text == "apple"

    def test_merge_preserves_exactly_one_correct_invariant(self) -> None:
        # The merge re-validates via model_validate; if the invariant
        # were broken (e.g. by accidentally splatting options) this
        # would raise. Smoke test that it doesn't.
        a = QuizDeck(title="A", questions=[_quiz_q("Q1?"), _quiz_q("Q2?")])
        b = QuizDeck(title="B", questions=[_quiz_q("Q3?")])
        merged = a.merge_dedupe(b)
        for q in merged.questions:
            correct = sum(1 for opt in q.answer_options if opt.is_correct)
            assert correct == 1
