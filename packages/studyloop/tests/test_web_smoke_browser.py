"""Fast browser-level smoke tests for the StudyLoop web UI.

These cover the first-render paths most likely to break when static assets,
Alpine initialisation, or top-level navigation regress. Keep them shallow:
deeper behaviour belongs in the focused Playwright suites.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

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
    from playwright.sync_api import Page, Route

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


_TREE = [
    {
        "id": "CodeWithMosh",
        "name": "Codewithmosh",
        "courses": [
            {
                "id": "CodeWithMosh/Python_Pro",
                "name": "Python Pro",
                "provider": "CodeWithMosh",
            }
        ],
    }
]

_LESSONS = [
    {
        "id": "CodeWithMosh/Python_Pro/intro",
        "course_id": "CodeWithMosh/Python_Pro",
        "slug": "intro",
        "name": "Intro",
    }
]

_STRUGGLING_TOPICS = [
    {
        "topic": "intro",
        "concept_count": 1,
        "session_count": 1,
        "last_seen": "2026-06-02T12:00:00Z",
    }
]


def _stub_explorer_routes(
    page: Page,
    *,
    struggle_post_status: int = 200,
    struggle_posts: list[dict[str, object]] | None = None,
) -> None:
    page.route("**/api/explorer/tree", lambda route: route.fulfill(json=_TREE))
    page.route(
        "**/api/explorer/courses/**/lessons",
        lambda route: route.fulfill(json=_LESSONS),
    )
    page.route(
        "**/api/explorer/lesson/**/content",
        lambda route: route.fulfill(
            json={
                "lesson_id": "CodeWithMosh/Python_Pro/intro",
                "title": "Intro",
                "content": "# Intro\n\nA closure captures state for later use.",
            }
        ),
    )

    def _history(route: Route) -> None:
        if route.request.method == "POST":
            if struggle_posts is not None:
                struggle_posts.append(cast("dict[str, object]", route.request.post_data_json or {}))
            route.fulfill(
                status=struggle_post_status,
                json={"ok": struggle_post_status < 400},
            )
            return
        route.fulfill(json=_STRUGGLING_TOPICS)

    page.route("**/api/history/struggling-topics**", _history)


def _stub_generate_lookup_routes(page: Page, *, generate_status: int = 202) -> None:
    page.route(
        "**/api/content/publishers",
        lambda route: route.fulfill(json=[{"name": "CodeWithMosh"}]),
    )
    page.route(
        "**/api/content/courses**",
        lambda route: route.fulfill(json=[{"name": "Python_Pro"}]),
    )
    page.route(
        "**/api/courses/**/sections**",
        lambda route: route.fulfill(json=[{"slug": "intro", "name": "Intro"}]),
    )
    page.route(
        "**/api/content/providers",
        lambda route: route.fulfill(
            json=[
                {
                    "slug": "stub",
                    "label": "Stub",
                    "adapter": "stub",
                    "available": True,
                    "models": [],
                }
            ]
        ),
    )

    def _generate(route: Route) -> None:
        if generate_status == 409:
            route.fulfill(
                status=409,
                json={"detail": "Another generation job is already running."},
            )
            return
        route.fulfill(
            status=202,
            json={"job_id": "job-smoke", "plan": {"task_count": 1, "sources": []}},
        )

    page.route("**/api/content/generate", _generate)


def _open_stubbed_lesson(page: Page) -> None:
    page.get_by_role("button", name="Courses").click()
    page.locator(".explorer-course-card").filter(has_text="Python Pro").click()
    page.locator(".explorer-lesson-item").filter(has_text="Intro").click()
    page.locator(".explorer-reader-view").filter(
        has_text="A closure captures state for later use."
    ).wait_for(state="visible", timeout=5000)


def _select_stubbed_generate_course(page: Page) -> None:
    page.select_option('select[x-model="form.publisher"]', value="CodeWithMosh")
    page.wait_for_function(
        """() => {
            const sel = document.querySelector('select[x-model="form.course"]');
            return sel && !sel.disabled && [...sel.options].some(o => o.value === 'Python_Pro');
        }""",
        timeout=5000,
    )
    page.select_option('select[x-model="form.course"]', value="Python_Pro")


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


def test_route_stubbed_learner_flow_marks_struggle_and_reaches_generate(
    web_page: Page,
) -> None:
    posts: list[dict[str, object]] = []
    _stub_explorer_routes(web_page, struggle_posts=posts)
    _stub_generate_lookup_routes(web_page)

    _goto(web_page)
    assert web_page.locator(".brand").is_visible()

    _open_stubbed_lesson(web_page)
    web_page.get_by_role("button", name="Mark as struggling").click()
    web_page.locator(".explorer-struggle-btn").filter(has_text="Marked").wait_for(
        state="visible",
        timeout=5000,
    )

    assert posts == [
        {
            "course": "CodeWithMosh/Python_Pro",
            "section": "intro",
            "publisher": "CodeWithMosh",
            "note": None,
        }
    ]

    web_page.get_by_role("button", name="Generate").click()
    web_page.wait_for_function(
        "() => window.Alpine.store('nav').current === 'generate'",
        timeout=3000,
    )
    _select_stubbed_generate_course(web_page)
    web_page.get_by_label("Topic I'm struggling on").check()
    web_page.locator('select[x-model="form.topic_slug"] option[value="intro"]').wait_for(
        state="attached",
        timeout=5000,
    )


def test_course_explorer_closes_with_escape(web_page: Page) -> None:
    _stub_explorer_routes(web_page)

    _goto(web_page)
    web_page.get_by_role("button", name="Courses").click()
    web_page.locator(".course-explorer-panel").wait_for(state="visible", timeout=5000)

    web_page.keyboard.press("Escape")
    web_page.wait_for_function("() => window.Alpine.store('explorer').open === false")
    web_page.locator(".course-explorer-panel").wait_for(state="hidden", timeout=5000)
    assert not web_page.locator(".course-explorer-panel").is_visible()


def test_main_controls_have_accessible_button_names(web_page: Page) -> None:
    _goto(web_page)

    for name in (
        "Flashcards",
        "Quizzes",
        "Generate",
        "Body Double",
        "Study Session",
        "Courses",
        "Settings",
    ):
        assert web_page.get_by_role("button", name=name).is_visible()


def test_failed_struggling_post_shows_error_without_success(web_page: Page) -> None:
    _stub_explorer_routes(web_page, struggle_post_status=500)

    _goto(web_page)
    _open_stubbed_lesson(web_page)
    web_page.get_by_role("button", name="Mark as struggling").click()

    error = web_page.locator(".explorer-reader-view .explorer-error").filter(
        has_text="Failed to mark struggle (500)"
    )
    error.wait_for(state="visible", timeout=5000)
    assert not web_page.locator(".explorer-struggle-btn").filter(has_text="Marked").is_visible()
    assert (
        web_page.get_by_role("button", name="Mark as struggling").get_attribute("aria-pressed")
        == "false"
    )


def test_generate_busy_response_shows_visible_conflict_state(web_page: Page) -> None:
    _stub_generate_lookup_routes(web_page, generate_status=409)
    _stub_explorer_routes(web_page)

    _goto(web_page, "generate")
    _select_stubbed_generate_course(web_page)
    web_page.locator('.generate-form button[type="submit"]').click()

    banner = web_page.locator(".generate-banner-warn").filter(
        has_text="Another generation job is already running."
    )
    banner.wait_for(state="visible", timeout=5000)
    assert not web_page.locator(".form-error").is_visible()
