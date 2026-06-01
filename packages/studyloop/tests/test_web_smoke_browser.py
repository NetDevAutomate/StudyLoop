"""Fast browser-level smoke tests for the StudyLoop web UI.

These cover the first-render paths most likely to break when static assets,
Alpine initialisation, or top-level navigation regress. Keep them shallow:
deeper behaviour belongs in the focused Playwright suites.
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

WEB_PORT = 18590

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


def test_app_loads_with_flashcards_nav_default(web_page: Page) -> None:
    _goto(web_page)

    current = web_page.evaluate("() => window.Alpine.store('nav').current")
    assert current == "flashcards"
    assert web_page.locator(".brand").is_visible()
    assert web_page.locator('.sidebar-btn:has-text("Flashcards")').is_visible()


def test_generate_panel_renders_provider_controls(web_page: Page) -> None:
    _goto(web_page, "generate")

    assert web_page.evaluate("() => window.Alpine.store('nav').current") == "generate"
    assert web_page.locator(".generate-panel h2").filter(has_text="Generate").is_visible()
    assert web_page.locator(".generate-form select").first.is_visible()
    provider_row = web_page.locator(".generate-form label.form-row").filter(has_text="Provider")
    assert provider_row.locator("select").is_visible()
    assert web_page.locator('.generate-form button[type="submit"]').is_visible()


def test_study_session_form_renders(web_page: Page) -> None:
    _goto(web_page, "study-session")

    assert web_page.evaluate("() => window.Alpine.store('nav').current") == "study-session"
    assert (
        web_page.locator(".session-start-picker h2")
        .filter(has_text="Start a Study Session")
        .is_visible()
    )
    assert web_page.locator("#session-type-select").is_visible()
    assert web_page.locator("#target-kind-select").is_visible()
    assert web_page.locator(".start-session-btn").is_visible()


def test_navigating_to_quizzes_works(web_page: Page) -> None:
    _goto(web_page)

    web_page.click('.sidebar-btn:has-text("Quizzes")')
    web_page.wait_for_function(
        "() => window.Alpine.store('nav').current === 'quizzes'",
        timeout=3000,
    )
    web_page.wait_for_function(
        """() => {
            const view = document.querySelector('.content-area > div[x-show*="quizzes"]');
            return view && getComputedStyle(view).display !== 'none';
        }""",
        timeout=3000,
    )

    assert web_page.url.endswith("#quizzes")
    assert web_page.locator('.content-area > div[x-show*="quizzes"]').is_visible()
