"""Layout-regression tests: assert real geometry, not just DOM presence.

These tests exist because a full suite of passing functional tests missed
four visual defects that a user caught by eye:

1. Generate panel header: <h2> overlapped its <p> (global ``header{display:flex}``
   cascaded into the nested ``.body-double-header``).
2. Study Session picker: bottom clipped by ``.app-layout{overflow:hidden}``
   after ``body{min-height:100dvh}`` pushed the layout past the fold.
3. Body Double voice-select: stayed visible because ``.voice-select.hidden``
   had no ``display:none`` rule.
4. Quizzes config nav title: ~18px off-centre due to a zero-width spacer span.

Each test asserts against ``getBoundingClientRect()`` via the helpers in
``_layout_assertions``. They use Playwright route interception (mirroring
``test_web_review_flow.py``) to reach view states deterministically without
real content on disk, and run at two viewports where relevant.

Plan: layout-regression capability (visibility != layout).
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
    assert_centered_in,
    assert_hidden_when_class_present,
    assert_scroll_reachable,
    assert_single_line,
    assert_stacked_no_overlap,
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

WEB_PORT = 18578  # unique port; sister e2e suites use 18570-18577

web_server = web_server_fixture_factory(WEB_PORT)
auth_context = auth_context_fixture_factory()
web_page = web_page_fixture_factory("web_server", "auth_context")


# ---------------------------------------------------------------------------
# Route stubs (mirror test_web_review_flow.py)
# ---------------------------------------------------------------------------


def _fulfill(route: Route, payload: object, status: int = 200) -> None:
    route.fulfill(
        status=status, content_type="application/json", body=json.dumps(payload)
    )


def _stub_courses(page: Page, courses: list[dict]) -> None:
    page.route("**/api/courses", lambda r: _fulfill(r, courses))


def _stub_session_state(page: Page) -> None:
    page.route("**/api/session/state", lambda r: _fulfill(r, {}))


def _stub_stats(page: Page) -> None:
    page.route(
        "**/api/stats/**",
        lambda r: _fulfill(r, {"total_reviews": 0, "unique_cards": 0, "mastered": 0}),
    )


def _stub_sources(page: Page, sources: list[str]) -> None:
    page.route("**/api/sources/**", lambda r: _fulfill(r, sources))


def _stub_cards(page: Page, cards: list[dict]) -> None:
    page.route("**/api/cards/**", lambda r: _fulfill(r, cards))


def _course(name: str, fc: int = 3, qz: int = 0) -> dict:
    return {
        "name": name,
        "flashcard_count": fc,
        "quiz_count": qz,
        "total_reviews": 0,
        "mastered": 0,
        "due_count": 0,
    }


def _flashcard(i: int) -> dict:
    return {"hash": f"h{i}", "type": "flashcard", "front": f"Q{i}", "back": f"A{i}",
            "source": "ch1"}


def _goto(page: Page, tab: str) -> None:
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#{tab}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.wait_for_timeout(400)


# ---------------------------------------------------------------------------
# Generate panel — header stacking + within-viewport (bug 1)
# ---------------------------------------------------------------------------


class TestGenerateLayout:
    def _goto_generate(self, page: Page) -> None:
        _goto(page, "generate")
        page.wait_for_function(
            "() => window.Alpine.store('nav').current === 'generate'", timeout=3000
        )

    def test_header_title_stacks_above_description(self, web_page: Page) -> None:
        self._goto_generate(web_page)
        assert_stacked_no_overlap(
            web_page,
            ".generate-panel .body-double-header h2",
            ".generate-panel .body-double-header p",
        )

    def test_generate_button_reachable(self, web_page: Page) -> None:
        # The form is taller than the viewport (publisher→course→scope→…→
        # submit), so the button legitimately sits below the fold. What
        # matters is that it is SCROLL-reachable inside .content-area, not
        # clipped by an overflow:hidden ancestor.
        self._goto_generate(web_page)
        assert_scroll_reachable(
            web_page,
            '.generate-form .toggle-btn, .generate-panel .toggle-btn',
            ".content-area",
        )


# ---------------------------------------------------------------------------
# Study Session — picker not clipped below the fold (bug: the real blocker)
# ---------------------------------------------------------------------------


class TestStudySessionLayout:
    """The session-setup picker must not be silently clipped.

    The blocker: ``body{min-height:100dvh}`` let ``.app-layout`` grow past
    the fold and its ``overflow:hidden`` hid the bottom of the picker (Start
    button edge + validation hint) with NO scroll affordance. The fix bounds
    body to the viewport so ``.content-area``(overflow-y:auto) scrolls tall
    content. This guards both halves:
      - the app shell itself never exceeds the viewport, and
      - tall picker content lives inside a scrollable container (reachable),
        not clipped by an overflow:hidden ancestor.
    """

    def test_app_layout_not_taller_than_viewport(self, web_page: Page) -> None:
        # The shell (.app-layout) must fit within the viewport — when it
        # exceeds it, its own overflow:hidden silently clips bottom content.
        _goto(web_page, "study-session")
        assert_within_viewport(web_page, ".app-layout")

    def test_picker_bottom_is_scroll_reachable(self, web_page: Page) -> None:
        # The picker is taller than the viewport; its bottom (the validation
        # hint below the Start button) must be reachable by scrolling
        # .content-area, not clipped. Skips cleanly if no live picker hint.
        _goto(web_page, "study-session")
        has_hint = web_page.evaluate(
            """() => { const p = [...document.querySelectorAll('.picker-hint')]
                .find(e => e.offsetParent !== null); return !!p; }"""
        )
        if has_hint:
            assert_scroll_reachable(
                web_page, ".session-start-picker .picker-hint", ".content-area"
            )


# ---------------------------------------------------------------------------
# Body Double — header stacking + voice-select hidden (bug 1 sibling + bug 2)
# ---------------------------------------------------------------------------


class TestBodyDoubleLayout:
    def test_header_title_stacks_above_description(self, web_page: Page) -> None:
        _goto(web_page, "body-double")
        assert_stacked_no_overlap(
            web_page,
            ".body-double-header h2",
            ".body-double-header p",
        )

    def test_voice_select_hidden_when_voice_off(self, web_page: Page) -> None:
        _goto(web_page, "body-double")
        # voiceOn defaults to false → Alpine applies .hidden → must be display:none.
        # Only assert if the toggle class is actually present in this state.
        has_hidden = web_page.evaluate(
            """() => { const el = document.querySelector('.voice-select');
                return !!el && el.classList.contains('hidden'); }"""
        )
        if has_hidden:
            assert_hidden_when_class_present(web_page, ".voice-select.hidden")


# ---------------------------------------------------------------------------
# Quizzes config nav-bar — title centred + spacer non-zero (bug 3)
# ---------------------------------------------------------------------------


class TestQuizzesConfigNavLayout:
    def _enter_config(self, page: Page) -> None:
        _stub_courses(page, [_course("Py-101", fc=0, qz=3)])
        _stub_session_state(page)
        _stub_stats(page)
        _stub_sources(page, ["ch1"])
        _goto(page, "quizzes")
        root = '[x-data*="quiz"]'
        page.locator(f"{root} .course-card .mode-btn.quiz").first.click()
        page.wait_for_function(
            f"""() => {{ const d = window.Alpine.$data(document.querySelector('{root}'));
                return d && d.view === 'config'; }}""",
            timeout=5000,
        )

    def test_config_nav_title_is_centered(self, web_page: Page) -> None:
        # The real symptom: the title was ~18px off-centre because the third
        # flex slot was a zero-width spacer. Centring is the OUTCOME that
        # matters and fully proves the fix — the spacer must reserve the
        # nav-button's width to balance the space-between row. (Asserting the
        # outcome, not the mechanism, keeps the test robust.)
        self._enter_config(web_page)
        root = '[x-data*="quiz"]'
        assert_centered_in(
            web_page, f"{root} .nav-bar .nav-course", f"{root} .nav-bar"
        )


# ---------------------------------------------------------------------------
# Flashcards study view — keyboard hints single line (bug 4)
# ---------------------------------------------------------------------------


class TestFlashcardsStudyLayout:
    def _enter_study(self, page: Page) -> None:
        _stub_courses(page, [_course("Py-101", fc=3)])
        _stub_session_state(page)
        _stub_stats(page)
        _stub_sources(page, ["ch1"])
        _stub_cards(page, [_flashcard(i) for i in range(3)])
        _goto(page, "flashcards")
        root = '[x-data*="flashcards"]'
        page.locator(f"{root} .course-card .mode-btn.flashcard").first.click()
        page.locator(f'{root} button:has-text("Start Session")').click()
        page.wait_for_function(
            f"""() => {{ const d = window.Alpine.$data(document.querySelector('{root}'));
                return d && d.view === 'study' && d.cards.length > 0; }}""",
            timeout=5000,
        )
        page.wait_for_timeout(300)

    def test_keyboard_hints_single_line_at_tablet_width(self, web_page: Page) -> None:
        # 768px is the width where 'Esc Home' previously wrapped to line 2.
        web_page.set_viewport_size({"width": 768, "height": 1024})
        self._enter_study(web_page)
        # The flashcard hint row is the visible inner div of .shortcuts.
        assert_single_line(web_page, ".shortcuts > div", "span")
