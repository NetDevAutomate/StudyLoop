"""Playwright UI tests for the Alpine ``nav`` store — tab switching,
hash routing, and initial-view resolution.

The nav store is the skeleton the rest of the UI hangs off; if this
regresses, every downstream view test fails for the same underlying
reason. Run these first in the e2e suite order.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md
      §Test Strategy — "navigation between tabs".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

# Sibling-module import: tests/ has no __init__.py.
_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import (  # noqa: E402
    auth_context_fixture_factory,
    web_page_fixture_factory,
    web_server_fixture_factory,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18570

web_server = web_server_fixture_factory(WEB_PORT)
auth_context = auth_context_fixture_factory()
web_page = web_page_fixture_factory("web_server", "auth_context")


def _goto(page: Page, hash_: str = "") -> None:
    url = f"http://127.0.0.1:{WEB_PORT}/"
    if hash_:
        url += f"#{hash_}"
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)


class TestNavStore:
    def test_default_view_is_today(self, web_page: Page) -> None:
        """No hash → the app lands on the Today (one-next-action) view."""
        _goto(web_page)
        current = web_page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "today"

    def test_hash_flashcards_sets_view(self, web_page: Page) -> None:
        """Existing #flashcards links keep working after the default change."""
        _goto(web_page, "flashcards")
        current = web_page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "flashcards"

    def test_hash_study_session_sets_view(self, web_page: Page) -> None:
        _goto(web_page, "study-session")
        current = web_page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "study-session"

    def test_hash_body_double_sets_view(self, web_page: Page) -> None:
        _goto(web_page, "body-double")
        current = web_page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "body-double"

    def test_hash_quizzes_sets_view(self, web_page: Page) -> None:
        _goto(web_page, "quizzes")
        current = web_page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "quizzes"

    def test_unknown_hash_falls_back_to_default(self, web_page: Page) -> None:
        """Unknown hash shouldn't crash — nav.init() keeps the default."""
        _goto(web_page, "not-a-real-view")
        current = web_page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "today"


class TestNavButtons:
    def test_clicking_study_session_nav_switches_view(self, web_page: Page) -> None:
        _goto(web_page)
        web_page.click('.sidebar-btn:has-text("Study Session")')
        web_page.wait_for_function(
            "() => window.Alpine.store('nav').current === 'study-session'",
            timeout=3000,
        )
        assert web_page.url.endswith("#study-session")

    def test_clicking_flashcards_nav_switches_view(self, web_page: Page) -> None:
        _goto(web_page, "study-session")
        web_page.click('.sidebar-btn:has-text("Flashcards")')
        web_page.wait_for_function(
            "() => window.Alpine.store('nav').current === 'flashcards'",
            timeout=3000,
        )

    def test_nav_go_is_scripted(self, web_page: Page) -> None:
        """The nav.go() API is callable from JS (agents can drive it)."""
        _goto(web_page)
        web_page.evaluate("() => window.Alpine.store('nav').go('quizzes')")
        current = web_page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "quizzes"


class TestActiveViewExclusivity:
    """Only one top-level view should be visible at a time. Checks x-show
    wiring across flashcards/quizzes/body-double/study-session."""

    @pytest.mark.parametrize(
        "view",
        ["flashcards", "quizzes", "body-double", "study-session"],
    )
    def test_one_view_visible_at_a_time(self, web_page: Page, view: str) -> None:
        _goto(web_page, view)
        visible_selectors = web_page.evaluate(
            """() => {
              const views = {
                flashcards: '[x-show*="flashcards"]',
                quizzes: '[x-show*="quizzes"]',
                'body-double': '[x-show*="body-double"]',
                'study-session': '[x-show*="study-session"]',
              };
              const out = {};
              for (const [k, sel] of Object.entries(views)) {
                const el = document.querySelector(`.content-area > div${sel}`);
                if (el) out[k] = getComputedStyle(el).display !== 'none';
              }
              return out;
            }"""
        )
        # The target view must be visible...
        assert visible_selectors.get(view) is True, (
            f"expected {view} visible, got {visible_selectors}"
        )
        # ...and at least one other view must be hidden. We don't
        # enforce "all others hidden" because some top-level shells
        # (e.g. timer bars) are shared chrome that span views.
        others = {k: v for k, v in visible_selectors.items() if k != view}
        assert any(v is False for v in others.values()), (
            f"no other view hidden; saw: {visible_selectors}"
        )


class TestHashUpdatesOnNav:
    def test_go_updates_location_hash(self, web_page: Page) -> None:
        _goto(web_page)
        web_page.evaluate("() => window.Alpine.store('nav').go('body-double')")
        assert web_page.url.endswith("#body-double")

    def test_direct_hash_change_is_ignored_by_default(self, web_page: Page) -> None:
        """The nav store only reads the hash at init. Changing location.hash
        after boot does NOT switch views — callers must use nav.go(). This
        lock prevents a brittle rely-on-hashchange assumption from creeping
        into the store.
        """
        _goto(web_page, "flashcards")
        web_page.evaluate("() => { window.location.hash = '#quizzes'; }")
        # Small tick — give any errant hashchange listener a chance to fire.
        web_page.wait_for_timeout(200)
        current = web_page.evaluate("() => window.Alpine.store('nav').current")
        assert current == "flashcards"
