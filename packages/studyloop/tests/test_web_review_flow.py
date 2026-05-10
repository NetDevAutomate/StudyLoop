"""Playwright UI tests for the flashcards + quiz review flow (reviewApp).

Exercises the reviewApp() Alpine component across its full state
machine: courses → config → study → summary, for both the flashcards
and quiz modes. Each test stubs ``/api/courses``, ``/api/sources``,
``/api/cards`` with Playwright route interception so the tests run
without real content on disk.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md
      §Test Strategy — "ALL web UI functions".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import (  # noqa: E402
    auth_context_fixture_factory,
    web_page_fixture_factory,
    web_server_fixture_factory,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18571

web_server = web_server_fixture_factory(WEB_PORT)
auth_context = auth_context_fixture_factory()
web_page = web_page_fixture_factory("web_server", "auth_context")


# ---------------------------------------------------------------------------
# Route stub helpers
# ---------------------------------------------------------------------------


def _fulfill(route: Route, payload: object, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _stub_courses(page: Page, courses: list[dict]) -> None:
    page.route("**/api/courses", lambda route: _fulfill(route, courses))


def _stub_session_state(page: Page, state: dict | None = None) -> None:
    """Stub /api/session/state so ``_loadLiveSession`` doesn't leak real state."""
    page.route("**/api/session/state", lambda route: _fulfill(route, state or {}))


def _stub_stats(page: Page, stats: dict) -> None:
    page.route("**/api/stats/**", lambda route: _fulfill(route, stats))


def _stub_sources(page: Page, sources: list[str]) -> None:
    page.route("**/api/sources/**", lambda route: _fulfill(route, sources))


def _stub_cards(page: Page, cards: list[dict]) -> None:
    page.route("**/api/cards/**", lambda route: _fulfill(route, cards))


def _stub_post_review(page: Page) -> None:
    """Accept POST /api/review with no side effects."""

    def handler(route: Route) -> None:
        if route.request.method == "POST":
            _fulfill(route, {"ok": True})
        else:
            route.continue_()

    page.route("**/api/review", handler)


def _flashcard(hash_: str, front: str, back: str, source: str = "ch1") -> dict:
    return {
        "hash": hash_,
        "type": "flashcard",
        "front": front,
        "back": back,
        "source": source,
    }


def _quiz_card(hash_: str, question: str, correct_idx: int, source: str = "ch1") -> dict:
    options = [{"text": f"Option {i}", "is_correct": i == correct_idx} for i in range(4)]
    return {
        "hash": hash_,
        "type": "quiz",
        "question": question,
        "options": options,
        "source": source,
    }


def _goto_review(page: Page, tab: str = "flashcards") -> None:
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#{tab}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)


# ---------------------------------------------------------------------------
# Courses view
# ---------------------------------------------------------------------------


class TestCoursesView:
    def test_empty_state_renders_when_no_courses(self, web_page: Page) -> None:
        _stub_courses(web_page, [])
        _stub_session_state(web_page)
        _goto_review(web_page, "flashcards")

        empty = web_page.locator('[x-show*="flashcards"] >> text=No courses found')
        empty.wait_for(state="visible", timeout=5000)

    def test_course_card_renders_with_counts(self, web_page: Page) -> None:
        _stub_courses(
            web_page,
            [
                {
                    "name": "Python-101",
                    "flashcard_count": 10,
                    "quiz_count": 5,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 3,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})

        _goto_review(web_page, "flashcards")
        card = web_page.locator('[x-show*="flashcards"] .course-card', has_text="Python-101")
        card.wait_for(state="visible", timeout=5000)

        # Due-count badge appears when due_count > 0.
        badge = card.locator(".due-badge")
        assert badge.is_visible()
        assert "3 due" in (badge.text_content() or "")

    def test_flashcards_mode_button_navigates_to_config(self, web_page: Page) -> None:
        _stub_courses(
            web_page,
            [
                {
                    "name": "Python-101",
                    "flashcard_count": 10,
                    "quiz_count": 5,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, ["ch1", "ch2"])
        _goto_review(web_page, "flashcards")

        card = web_page.locator('[x-show*="flashcards"] .course-card', has_text="Python-101")
        card.locator(".mode-btn.flashcard").click()

        # Alpine switches reviewApp.view to 'config'.
        web_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data*="flashcards"]');
              const data = window.Alpine.$data(root);
              return data && data.view === 'config';
            }""",
            timeout=5000,
        )


# ---------------------------------------------------------------------------
# Flashcards study flow
# ---------------------------------------------------------------------------


class TestFlashcardsStudyFlow:
    def test_start_session_enters_study_view(self, web_page: Page) -> None:
        cards = [_flashcard(f"h{i}", f"Q{i}", f"A{i}") for i in range(3)]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Python-101",
                    "flashcard_count": 3,
                    "quiz_count": 0,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, ["ch1"])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "flashcards")

        root = '[x-data*="flashcards"]'
        web_page.locator(f"{root} .course-card .mode-btn.flashcard").first.click()
        # Click Start inside the config view.
        web_page.locator(f'{root} button:has-text("Start Session")').click()

        # The study view renders the first card's question.
        web_page.wait_for_function(
            f"""() => {{
              const root = document.querySelector('{root}');
              const data = window.Alpine.$data(root);
              return data && data.view === 'study' && data.cards.length > 0;
            }}""",
            timeout=5000,
        )

    def test_flip_card_reveals_answer(self, web_page: Page) -> None:
        cards = [_flashcard("h1", "What is 2+2?", "Four")]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 1,
                    "quiz_count": 0,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "flashcards")

        root = '[x-data*="flashcards"]'
        web_page.locator(f"{root} .course-card .mode-btn.flashcard").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()

        # Drive flipCard() directly to avoid brittle card-click targeting.
        web_page.wait_for_function(
            f"""() => !!window.Alpine
              && window.Alpine.$data(document.querySelector('{root}')).currentCard""",
            timeout=5000,
        )
        revealed_before = web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).revealed"
        )
        assert revealed_before is False

        web_page.evaluate(f"() => window.Alpine.$data(document.querySelector('{root}')).flipCard()")
        revealed_after = web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).revealed"
        )
        assert revealed_after is True

    def test_correct_answer_increments_counter(self, web_page: Page) -> None:
        cards = [_flashcard("h1", "Q", "A"), _flashcard("h2", "Q2", "A2")]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 2,
                    "quiz_count": 0,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "flashcards")

        root = '[x-data*="flashcards"]'
        web_page.locator(f"{root} .course-card .mode-btn.flashcard").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()
        web_page.wait_for_function(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view === 'study'",
            timeout=5000,
        )

        web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).answerFlashcard(true)"
        )
        correct = web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).correct"
        )
        assert correct == 1

    def test_incorrect_answer_tracks_wrong_hash(self, web_page: Page) -> None:
        cards = [_flashcard("wrong-1", "Q", "A"), _flashcard("good-2", "Q2", "A2")]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 2,
                    "quiz_count": 0,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "flashcards")

        root = '[x-data*="flashcards"]'
        web_page.locator(f"{root} .course-card .mode-btn.flashcard").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()
        web_page.wait_for_function(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view === 'study'",
            timeout=5000,
        )

        # Pick the wrong card first (shuffle may reorder; force index).
        web_page.evaluate(
            f"""() => {{
              const data = window.Alpine.$data(document.querySelector('{root}'));
              const i = data.cards.findIndex(c => c.hash === 'wrong-1');
              if (i >= 0) data.index = i;
              data.answerFlashcard(false);
            }}"""
        )
        wrong = web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).wrongHashes"
        )
        assert "wrong-1" in wrong

    def test_retry_wrong_restarts_session_with_wrong_cards_only(self, web_page: Page) -> None:
        cards = [_flashcard(f"h{i}", f"Q{i}", f"A{i}") for i in range(3)]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 3,
                    "quiz_count": 0,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "flashcards")

        root = '[x-data*="flashcards"]'
        web_page.locator(f"{root} .course-card .mode-btn.flashcard").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()
        web_page.wait_for_function(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view === 'study'",
            timeout=5000,
        )

        # Inject two wrong hashes, then retry.
        web_page.evaluate(
            f"""() => {{
              const data = window.Alpine.$data(document.querySelector('{root}'));
              data.wrongHashes = ['h0', 'h1'];
              data.retryWrong();
            }}"""
        )
        state = web_page.evaluate(
            f"""() => {{
              const d = window.Alpine.$data(document.querySelector('{root}'));
              return {{view: d.view, n: d.cards.length, isRetry: d.isRetry}};
            }}"""
        )
        assert state["view"] == "study"
        assert state["n"] == 2
        assert state["isRetry"] is True


# ---------------------------------------------------------------------------
# Quiz study flow
# ---------------------------------------------------------------------------


class TestQuizStudyFlow:
    def test_quiz_select_correct_answer_increments_counter(self, web_page: Page) -> None:
        cards = [_quiz_card("q1", "Which is prime?", correct_idx=2)]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 0,
                    "quiz_count": 1,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "quizzes")

        root = '[x-data*="quiz"]'
        web_page.locator(f"{root} .course-card .mode-btn.quiz").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()
        web_page.wait_for_function(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view === 'study'",
            timeout=5000,
        )

        web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).answerQuiz(2)"
        )
        state = web_page.evaluate(
            f"""() => {{
              const d = window.Alpine.$data(document.querySelector('{root}'));
              return {{correct: d.correct, incorrect: d.incorrect, answered: d.quizAnswered}};
            }}"""
        )
        assert state["correct"] == 1
        assert state["incorrect"] == 0
        assert state["answered"] is True

    def test_quiz_select_wrong_answer_increments_incorrect(self, web_page: Page) -> None:
        cards = [_quiz_card("q1", "Which is prime?", correct_idx=2)]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 0,
                    "quiz_count": 1,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "quizzes")

        root = '[x-data*="quiz"]'
        web_page.locator(f"{root} .course-card .mode-btn.quiz").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()
        web_page.wait_for_function(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view === 'study'",
            timeout=5000,
        )

        web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).answerQuiz(0)"
        )
        state = web_page.evaluate(
            f"""() => {{
              const d = window.Alpine.$data(document.querySelector('{root}'));
              return {{correct: d.correct, incorrect: d.incorrect, wrong: d.wrongHashes}};
            }}"""
        )
        assert state["correct"] == 0
        assert state["incorrect"] == 1
        assert "q1" in state["wrong"]

    def test_quiz_second_selection_is_ignored_once_answered(self, web_page: Page) -> None:
        """Locking: answerQuiz short-circuits when quizAnswered is true."""
        cards = [_quiz_card("q1", "Q", correct_idx=1)]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 0,
                    "quiz_count": 1,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "quizzes")

        root = '[x-data*="quiz"]'
        web_page.locator(f"{root} .course-card .mode-btn.quiz").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()
        web_page.wait_for_function(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view === 'study'",
            timeout=5000,
        )

        web_page.evaluate(
            f"""() => {{
              const d = window.Alpine.$data(document.querySelector('{root}'));
              d.answerQuiz(0);  // wrong
              d.answerQuiz(1);  // would be correct, but blocked
            }}"""
        )
        state = web_page.evaluate(
            f"""() => {{
              const d = window.Alpine.$data(document.querySelector('{root}'));
              return {{correct: d.correct, incorrect: d.incorrect}};
            }}"""
        )
        assert state["correct"] == 0
        assert state["incorrect"] == 1


# ---------------------------------------------------------------------------
# Summary view (session complete)
# ---------------------------------------------------------------------------


class TestSummaryView:
    def test_summary_renders_after_all_cards_answered(self, web_page: Page) -> None:
        cards = [_flashcard(f"h{i}", f"Q{i}", f"A{i}") for i in range(2)]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 2,
                    "quiz_count": 0,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "flashcards")

        root = '[x-data*="flashcards"]'
        web_page.locator(f"{root} .course-card .mode-btn.flashcard").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()
        web_page.wait_for_function(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view === 'study'",
            timeout=5000,
        )

        # Answer both cards correct; _advance() should flip view to summary.
        web_page.evaluate(
            f"""async () => {{
              const d = window.Alpine.$data(document.querySelector('{root}'));
              await d.answerFlashcard(true);
              await d.answerFlashcard(true);
            }}"""
        )
        view = web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view"
        )
        assert view == "summary"

    def test_summary_pct_reflects_score(self, web_page: Page) -> None:
        cards = [_flashcard(f"h{i}", f"Q{i}", f"A{i}") for i in range(4)]
        _stub_courses(
            web_page,
            [
                {
                    "name": "Math",
                    "flashcard_count": 4,
                    "quiz_count": 0,
                    "total_reviews": 0,
                    "mastered": 0,
                    "due_count": 0,
                }
            ],
        )
        _stub_session_state(web_page)
        _stub_stats(web_page, {"total_reviews": 0, "unique_cards": 0, "mastered": 0})
        _stub_sources(web_page, [])
        _stub_cards(web_page, cards)
        _stub_post_review(web_page)
        _goto_review(web_page, "flashcards")

        root = '[x-data*="flashcards"]'
        web_page.locator(f"{root} .course-card .mode-btn.flashcard").first.click()
        web_page.locator(f'{root} button:has-text("Start Session")').click()
        web_page.wait_for_function(
            f"() => window.Alpine.$data(document.querySelector('{root}')).view === 'study'",
            timeout=5000,
        )

        # 3 correct, 1 wrong → 75%.
        web_page.evaluate(
            f"""async () => {{
              const d = window.Alpine.$data(document.querySelector('{root}'));
              await d.answerFlashcard(true);
              await d.answerFlashcard(true);
              await d.answerFlashcard(true);
              await d.answerFlashcard(false);
            }}"""
        )
        pct = web_page.evaluate(
            f"() => window.Alpine.$data(document.querySelector('{root}')).summaryPct"
        )
        assert pct == 75
