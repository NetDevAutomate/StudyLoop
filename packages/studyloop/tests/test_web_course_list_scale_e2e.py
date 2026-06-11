"""E2E for the scalable course list (mode-split + grouping + search + compact rows).

The Flashcards and Quizzes panels used to render the identical flat grid of tall
cards, each with BOTH a Flashcards and a Quiz button — redundant and unscalable.
This suite locks in the rework:

- **Mode-split**: the Flashcards panel shows only decks with flashcards and a
  single Flashcards action; the Quizzes panel mirrors with quiz decks only.
- **Grouping**: courses group under collapsible publisher headers.
- **Search**: a box filters by course name; empty-state when nothing matches.
- **Compact rows**: one-line rows that don't overflow or wrap.

Geometry is asserted via the shared ``_layout_assertions`` helpers (per the
repo's visibility != layout discipline). Routes are stubbed so the suite is
deterministic and needs no content on disk.

Port 18584 (sisters: 18578 layout-regression, 18583 settings-panel).
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

from _layout_assertions import (  # noqa: E402
    assert_nonzero_size,
    assert_single_line,
    assert_within_viewport,
)
from _playwright_helpers import (  # noqa: E402
    auth_context_fixture_factory,
    web_page_fixture_factory,
    web_server_fixture_factory,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18584

web_server = web_server_fixture_factory(WEB_PORT)
auth_context = auth_context_fixture_factory()
web_page = web_page_fixture_factory("web_server", "auth_context")


# ---------------------------------------------------------------------------
# Route stubs
# ---------------------------------------------------------------------------


def _fulfill(route: Route, payload: object, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def _course(name: str, publisher: str, fc: int, qz: int) -> dict:
    return {
        "name": name,
        "publisher": publisher,
        "flashcard_count": fc,
        "quiz_count": qz,
        "total_reviews": 0,
        "mastered": 0,
        "due_count": 0,
    }


# Two publishers; a mix of flashcard-only, quiz-only, and mixed decks so the
# mode split is exercised in both directions.
_COURSES = [
    _course("Mosh_SQL_Basics", "CodeWithMosh", fc=5, qz=5),  # mixed
    _course("Mosh_SQL_FcOnly", "CodeWithMosh", fc=5, qz=0),  # flashcards only
    _course("Mosh_SQL_QzOnly", "CodeWithMosh", fc=0, qz=5),  # quiz only
    _course("Arjan_Patterns", "ArjanCodes", fc=4, qz=4),  # mixed, other publisher
]


def _stub_courses(page: Page, courses: list[dict] | None = None) -> None:
    page.route("**/api/courses", lambda r: _fulfill(r, courses or _COURSES))


def _stub_misc(page: Page) -> None:
    page.route("**/api/session/state", lambda r: _fulfill(r, {}))
    page.route(
        "**/api/stats/**",
        lambda r: _fulfill(r, {"total_reviews": 0, "unique_cards": 0, "mastered": 0}),
    )
    page.route("**/api/sources/**", lambda r: _fulfill(r, ["ch1"]))


def _goto(page: Page, tab: str) -> None:
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#{tab}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.wait_for_timeout(400)


def _panel(tab: str) -> str:
    # The Flashcards panel's reviewApp has mode 'flashcards'; Quizzes 'quiz'.
    return '[x-data*="flashcards"]' if tab == "flashcards" else '[x-data*="quiz"]'


def _visible_row_names(page: Page, tab: str) -> list[str]:
    root = _panel(tab)
    return page.evaluate(
        """(root) => {
          const panel = document.querySelector(root);
          return [...panel.querySelectorAll('.course-row-name')]
            .filter(n => n.offsetParent !== null)
            .map(n => n.textContent.trim());
        }""",
        root,
    )


# ---------------------------------------------------------------------------
# Mode split
# ---------------------------------------------------------------------------


class TestModeSplit:
    def test_flashcards_panel_lists_only_flashcard_decks(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        names = _visible_row_names(web_page, "flashcards")
        assert "Mosh_SQL_Basics" in names  # mixed → shown
        assert "Mosh_SQL_FcOnly" in names  # fc-only → shown
        assert "Arjan_Patterns" in names  # mixed → shown
        assert "Mosh_SQL_QzOnly" not in names  # quiz-only → hidden

    def test_flashcards_panel_has_no_quiz_buttons(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        root = _panel("flashcards")
        assert web_page.locator(f"{root} .course-row-action.flashcard").count() == 3
        assert web_page.locator(f"{root} .course-row-action.quiz").count() == 0

    def test_quizzes_panel_lists_only_quiz_decks(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "quizzes")
        names = _visible_row_names(web_page, "quizzes")
        assert "Mosh_SQL_Basics" in names
        assert "Mosh_SQL_QzOnly" in names
        assert "Arjan_Patterns" in names
        assert "Mosh_SQL_FcOnly" not in names  # flashcard-only → hidden

    def test_quizzes_panel_has_no_flashcard_buttons(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "quizzes")
        root = _panel("quizzes")
        assert web_page.locator(f"{root} .course-row-action.quiz").count() == 3
        assert web_page.locator(f"{root} .course-row-action.flashcard").count() == 0


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


class TestGrouping:
    def test_publisher_group_headers_render(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        root = _panel("flashcards")
        headers = web_page.evaluate(
            """(root) => [...document.querySelector(root)
                 .querySelectorAll('.course-group-header')]
                 .filter(h => h.offsetParent !== null)
                 .map(h => h.textContent.replace(/\\s+/g,' ').trim())""",
            root,
        )
        # ArjanCodes (1 fc deck) and CodeWithMosh (2 fc decks) groups, sorted.
        assert any("ArjanCodes" in h and "(1)" in h for h in headers)
        assert any("CodeWithMosh" in h and "(2)" in h for h in headers)

    def test_collapsing_a_group_hides_only_its_rows(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        root = _panel("flashcards")
        # Collapse CodeWithMosh via the component, then assert visibility.
        web_page.evaluate(
            """(root) => window.Alpine.$data(document.querySelector(root))
                 .toggleGroup('CodeWithMosh')""",
            root,
        )
        web_page.wait_for_timeout(150)
        names = _visible_row_names(web_page, "flashcards")
        assert "Arjan_Patterns" in names  # other group stays visible
        assert "Mosh_SQL_Basics" not in names  # collapsed group hidden
        assert "Mosh_SQL_FcOnly" not in names

    def test_expanding_restores_rows(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        root = _panel("flashcards")
        web_page.evaluate(
            """(root) => {
              const d = window.Alpine.$data(document.querySelector(root));
              d.toggleGroup('CodeWithMosh');
              d.toggleGroup('CodeWithMosh');
            }""",
            root,
        )
        web_page.wait_for_timeout(150)
        names = _visible_row_names(web_page, "flashcards")
        assert "Mosh_SQL_Basics" in names


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_filters_by_course_name(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        root = _panel("flashcards")
        web_page.locator(f"{root} .course-search-input").fill("FcOnly")
        web_page.wait_for_timeout(150)
        names = _visible_row_names(web_page, "flashcards")
        assert names == ["Mosh_SQL_FcOnly"]

    def test_search_with_no_match_shows_empty_message(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        root = _panel("flashcards")
        web_page.locator(f"{root} .course-search-input").fill("zzzznope")
        web_page.wait_for_timeout(150)
        assert web_page.locator(f"{root} .course-empty-search").is_visible()
        assert _visible_row_names(web_page, "flashcards") == []

    def test_clearing_search_restores_all(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        root = _panel("flashcards")
        box = web_page.locator(f"{root} .course-search-input")
        box.fill("FcOnly")
        web_page.wait_for_timeout(120)
        box.fill("")
        web_page.wait_for_timeout(150)
        # All 3 flashcard decks visible again.
        assert len(_visible_row_names(web_page, "flashcards")) == 3

    def test_search_hides_publisher_group_with_no_matches(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        root = _panel("flashcards")
        # "Arjan" matches only the ArjanCodes deck → CodeWithMosh group vanishes.
        web_page.locator(f"{root} .course-search-input").fill("Arjan")
        web_page.wait_for_timeout(150)
        headers = web_page.evaluate(
            """(root) => [...document.querySelector(root)
                 .querySelectorAll('.course-group-header')]
                 .filter(h => h.offsetParent !== null)
                 .map(h => h.textContent)""",
            root,
        )
        assert any("ArjanCodes" in h for h in headers)
        assert not any("CodeWithMosh" in h for h in headers)


# ---------------------------------------------------------------------------
# Compact-row geometry (visibility != layout)
# ---------------------------------------------------------------------------


class TestCompactRowLayout:
    def test_rows_do_not_overflow_viewport(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        # assert_within_viewport checks the right/bottom edges stay on-screen.
        assert_within_viewport(web_page, '[x-data*="flashcards"] .course-row')

    def test_action_button_has_nonzero_size(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        assert_nonzero_size(web_page, '[x-data*="flashcards"] .course-row-action.flashcard')

    def test_row_name_is_single_line_at_tablet_width(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        web_page.set_viewport_size({"width": 768, "height": 1024})
        _goto(web_page, "flashcards")
        # Each row's name must not wrap to a second line (ellipsis truncation ok).
        assert_single_line(web_page, '[x-data*="flashcards"] .course-row', ".course-row-name")


# ---------------------------------------------------------------------------
# Heatmap section is Flashcards-only (must survive the courses-view rework)
# ---------------------------------------------------------------------------


class TestHeatmapPlacement:
    def test_heatmap_present_in_flashcards_panel(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "flashcards")
        assert web_page.locator('[x-data*="flashcards"] .heatmap-section').count() == 1

    def test_heatmap_absent_from_quizzes_panel(self, web_page: Page) -> None:
        _stub_courses(web_page)
        _stub_misc(web_page)
        _goto(web_page, "quizzes")
        assert web_page.locator('[x-data*="quiz"] .heatmap-section').count() == 0
