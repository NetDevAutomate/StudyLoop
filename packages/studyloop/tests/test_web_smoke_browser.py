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
from e2e._env import ConsoleWatch  # noqa: E402

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


def test_app_loads_with_today_nav_default(web_page: Page) -> None:
    _goto(web_page)

    current = web_page.evaluate("() => window.Alpine.store('nav').current")
    assert current == "today"
    assert web_page.locator(".brand").is_visible()
    assert web_page.locator('.sidebar-btn:has-text("Today")').is_visible()
    assert web_page.locator('.sidebar-btn:has-text("Flashcards")').is_visible()


def test_no_csp_violations_on_default_load(web_page: Page) -> None:
    """R-13c smoke coverage: the default-mode CSP (no --dev, no data:
    exception) must ship on the document response with zero violations.

    This is the fast (~seconds, not the ~8 min full e2e suite) proof that
    R-13c's new object-src/base-uri/frame-ancestors/form-action directives
    and the dev_mode-gated connect-src don't break first render. The
    dev_mode=True case (ghostty WASM bootstrap) is covered by
    test_ghostty_dev_terminal.py in the full suite, not here — this file's
    server never passes --dev.
    """
    watch = ConsoleWatch(web_page)
    _goto(web_page)
    watch.assert_no_csp_violations()


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
    # Session Type dropdown deliberately absent: Body Double is its own view,
    # not a mode of this picker (body-double-own-agent-picker / ADR-0002), and
    # test_body_double_journey asserts its count is 0. This suite used to assert
    # the opposite, which is a straight contradiction — the redesign is the
    # newer contract.
    assert web_page.locator("#session-type-select").count() == 0
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

    web_page.get_by_role("button", name="Generate", exact=True).click()
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
        "Today",
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
    assert not web_page.locator(".generate-form .form-error").is_visible()


# ---------------------------------------------------------------------------
# Today landing view + quick-park + park-first friction (learner-first UX)
# ---------------------------------------------------------------------------

_NOW_PLAN = {
    "energy": "medium",
    "time_minutes": 25,
    "modality": "recall",
    "interleave": "off",
    "generated_at": "2026-07-12T20:00:00Z",
    "starter": False,
    "interleave_ratio": {},
    "primary": {
        "concept": "Python closures",
        "topic": "python",
        "reason": "6 cards due today",
        "action_type": "review",
        "estimated_minutes": 15,
        "source": "srs",
        "evidence_command": "",
        "score": 0.9,
        "course": None,
        "metadata": {},
    },
    "alternates": [
        {
            "concept": "SQL window functions",
            "topic": "sql",
            "reason": "struggled last week",
            "action_type": "quiz",
            "estimated_minutes": 10,
            "source": "struggles",
            "evidence_command": "",
            "score": 0.7,
            "course": None,
            "metadata": {},
        }
    ],
}


def _stub_today_routes(
    page: Page,
    *,
    backlog: dict | None = None,
    last_session: dict | None = None,
) -> None:
    page.route("**/api/now**", lambda route: route.fulfill(json=_NOW_PLAN))
    page.route(
        "**/api/backlog",
        lambda route: route.fulfill(
            json=backlog
            or {
                "active": [],
                "parking_lot": [{"id": 9, "question": "What is MVCC?"}],
                "active_count": 0,
                "parking_lot_count": 1,
                "max_active": 3,
            }
        ),
    )
    page.route(
        "**/api/session/last",
        lambda route: route.fulfill(json=last_session or {}),
    )


def test_today_view_shows_one_next_action(web_page: Page) -> None:
    _stub_today_routes(web_page)

    _goto(web_page)
    card = web_page.locator(".today-card:not(.today-starter)")
    card.wait_for(state="visible", timeout=5000)
    assert web_page.locator(".today-concept").inner_text() == "Python closures"
    assert "6 cards due today" in web_page.locator(".today-reason").inner_text()
    # Alternates collapsed by default; toggle reveals them.
    assert not web_page.locator(".today-alt-list").is_visible()
    web_page.locator(".today-alt-toggle").click()
    web_page.locator(".today-alt-list").wait_for(state="visible", timeout=3000)
    # Parked chip is offered for one-tap pickup.
    assert web_page.locator(".today-chip", has_text="What is MVCC?").is_visible()


def test_today_start_navigates_to_action_view(web_page: Page) -> None:
    _stub_today_routes(web_page)

    _goto(web_page)
    web_page.locator(".today-start-btn").click()
    web_page.wait_for_function(
        "() => window.Alpine.store('nav').current === 'flashcards'", timeout=3000
    )


def test_today_resume_last_session(web_page: Page) -> None:
    """A past study session surfaces as 'Resume: <topic>' and pre-fills the form."""
    _stub_today_routes(
        web_page,
        last_session={
            "topic": "Python decorators",
            "topic_slug": "python",
            "energy_level": "high",
            "started_at": "2026-07-12T10:00:00",
            "ended_at": "2026-07-12T10:45:00",
        },
    )

    _goto(web_page)
    resume = web_page.locator(".today-resume-btn")
    resume.wait_for(state="visible", timeout=5000)
    assert "Python decorators" in resume.inner_text()
    resume.click()
    web_page.wait_for_function(
        "() => window.Alpine.store('nav').current === 'study-session'", timeout=3000
    )
    web_page.wait_for_function(
        "() => document.querySelector('#topic-input') && "
        "document.querySelector('#topic-input').value === 'Python decorators'",
        timeout=3000,
    )


def test_quick_park_saves_without_leaving_view(web_page: Page) -> None:
    """Quick-park posts the thought and does NOT change the current view."""
    _stub_today_routes(web_page)
    parked: list[dict[str, object]] = []

    def _park(route: Route) -> None:
        parked.append(cast("dict[str, object]", route.request.post_data_json or {}))
        route.fulfill(json={"ok": True, "id": 1})

    web_page.route("**/api/backlog/park", _park)

    _goto(web_page)
    web_page.locator(".quick-park-btn").click()
    web_page.locator(".quick-park-input").fill("tangent: how do generators pause?")
    web_page.locator(".quick-park-dialog button", has_text="Park it").click()

    web_page.locator(".toast", has_text="Parked").wait_for(state="visible", timeout=5000)
    assert parked and parked[0]["question"] == "tangent: how do generators pause?"
    # Flow protection: still on the Today view.
    assert web_page.evaluate("() => window.Alpine.store('nav').current") == "today"


def test_park_first_modal_blocks_fourth_topic(web_page: Page) -> None:
    """3 active topics + starting a NEW one → in-page park-first overlay."""
    full_backlog = {
        "active": [
            {"id": 1, "question": "Topic A"},
            {"id": 2, "question": "Topic B"},
            {"id": 3, "question": "Topic C"},
        ],
        "parking_lot": [],
        "active_count": 3,
        "parking_lot_count": 0,
        "max_active": 3,
    }
    _stub_today_routes(web_page, backlog=full_backlog)
    web_page.route(
        "**/api/session/options",
        lambda route: route.fulfill(
            json={
                "session_types": [],
                "topics": [],
                "vendors": [],
                "courses": [],
                "lessons": [],
                # An available agent so the Start button enables.
                "agents": [{"label": "Claude", "value": "claude", "available": True}],
            }
        ),
    )

    _goto(web_page, "study-session")
    web_page.locator("#topic-input").fill("Brand new fourth topic")
    web_page.wait_for_function(
        "() => !document.querySelector('.start-session-btn').disabled", timeout=3000
    )
    web_page.get_by_role("button", name="Start Session").click()

    overlay = web_page.locator(".park-first-overlay")
    overlay.wait_for(state="visible", timeout=5000)
    # It's an in-page overlay (native dialogs are banned) listing the 3 topics.
    assert web_page.locator(".park-first-item").count() == 3
    # Escape cancels without starting.
    web_page.keyboard.press("Escape")
    overlay.wait_for(state="hidden", timeout=3000)


def test_course_list_no_false_empty_flash(web_page: Page) -> None:
    """While /api/courses is in flight the UI says 'Checking…', never 'No courses found'."""
    _stub_today_routes(web_page)

    def _slow_courses(route: Route) -> None:
        web_page.wait_for_timeout(1500)
        route.fulfill(json=[])

    web_page.route("**/api/courses", _slow_courses)

    _goto(web_page, "flashcards")
    # Scope to the flashcards view: the (hidden) Today panel carries the same
    # loading copy, and an unscoped text locator resolves to that first.
    fc_view = web_page.locator('.content-area > div[x-show*="flashcards"]')
    fc_view.locator("text=Checking your content").wait_for(state="visible", timeout=3000)
    assert not fc_view.locator("h2", has_text="No courses found").is_visible()
    # After the fetch resolves empty, the true empty state appears.
    fc_view.locator("h2", has_text="No courses found").wait_for(state="visible", timeout=5000)


def test_terminal_flex_chain_allows_shrink(web_page: Page) -> None:
    """The xterm mount must shrink with its container (min-width regression).

    Flex items default to ``min-width: auto`` and refuse to shrink below
    their content's intrinsic width. xterm.js renders its screen at a fixed
    pixel width, so without an explicit ``min-width: 0`` down the terminal
    flex chain the browser could grow the terminal but never shrink it —
    the ResizeObserver never fired on narrow. Verify against the real
    stylesheet by mounting the production class chain with an over-wide
    child and shrinking the outer container.
    """
    _goto(web_page)
    result = web_page.evaluate(
        """
        () => {
          const outer = document.createElement('div');
          outer.style.cssText =
            'position:fixed;left:0;top:0;width:800px;height:400px;display:flex;';
          outer.innerHTML = `
            <div class="session-terminal-area agent-console"
                 style="display:flex;flex-direction:column;">
              <div class="embedded-terminal-panel xterm-panel">
                <div class="embedded-terminal-content xterm-content">
                  <div class="xterm-mount">
                    <div style="width:1200px;height:10px;"></div>
                  </div>
                </div>
              </div>
            </div>`;
          document.body.appendChild(outer);
          const mount = outer.querySelector('.xterm-mount');
          const wide = mount.clientWidth;
          outer.style.width = '400px';
          // Force layout
          const narrow = mount.getBoundingClientRect().width;
          const styles = getComputedStyle(mount);
          const overflow = styles.overflow;
          outer.remove();
          return { wide, narrow, overflow };
        }
        """
    )
    # The mount tracked the container down, despite the 1200px-wide child.
    assert result["wide"] > 700, result
    assert result["narrow"] <= 400, result
    assert result["overflow"] == "hidden", result


# ---------------------------------------------------------------------------
# Flashcards / quiz / voice journeys (route-stubbed)
# ---------------------------------------------------------------------------

_REVIEW_COURSES = [
    {
        "name": "python-basics",
        "publisher": "TestPub",
        "flashcard_count": 2,
        "quiz_count": 1,
        "due_count": 0,
        "mastered": 0,
    }
]

_FLASHCARDS = [
    {
        "type": "flashcard",
        "front": "What does a decorator return?",
        "back": "A callable wrapping the decorated function",
        "hash": "fc-1",
        "source": "ch1",
    },
    {
        "type": "flashcard",
        "front": "What is a generator?",
        "back": "An iterator produced by a function with yield",
        "hash": "fc-2",
        "source": "ch1",
    },
]

_QUIZ_CARDS = [
    {
        "type": "quiz",
        "question": "Which keyword defines a generator?",
        "options": [
            {"text": "return", "is_correct": False, "rationale": ""},
            {
                "text": "yield",
                "is_correct": True,
                "rationale": "yield makes a generator.",
            },
        ],
        "hash": "qz-1",
        "source": "ch1",
    },
    {
        # Second card so the 1.5s auto-advance cannot end the session while
        # the rationale assertion below is still reading the first card.
        "type": "quiz",
        "question": "Which module provides fixtures?",
        "options": [
            {"text": "pytest", "is_correct": True, "rationale": "pytest fixtures."},
            {"text": "unittest", "is_correct": False, "rationale": ""},
        ],
        "hash": "qz-2",
        "source": "ch1",
    },
]


def _stub_review_routes(page: Page, mode: str, cards: list[dict]) -> None:
    """Stub every endpoint the reviewApp() course->config->study flow hits."""
    page.route("**/api/courses", lambda r: r.fulfill(json=_REVIEW_COURSES))
    page.route("**/api/session/state", lambda r: r.fulfill(json={}))
    page.route("**/api/stats/**", lambda r: r.fulfill(json={}))
    page.route("**/api/history**", lambda r: r.fulfill(json=[]))
    page.route(
        "**/api/sources/python-basics**",
        lambda r: r.fulfill(json=["ch1"]),
    )
    page.route(
        f"**/api/cards/python-basics?mode={mode}",
        lambda r: r.fulfill(json=cards),
    )
    page.route("**/api/due/python-basics", lambda r: r.fulfill(json=[]))
    page.route("**/api/wrong/python-basics", lambda r: r.fulfill(json=[]))
    page.route("**/api/review", lambda r: r.fulfill(json={"ok": True}))


def _open_deck(page: Page, view: str, action_class: str, mode: str) -> None:
    """Navigate to the review view, open the course's config, start a session."""
    _goto(page, view)
    fc_view = page.locator(f'.content-area > div[x-show*="{view}"]')
    row_btn = fc_view.locator(f".course-row-action.{action_class}").first
    row_btn.wait_for(state="visible", timeout=5000)
    row_btn.click()
    start = fc_view.get_by_role("button", name="Start Session")
    start.wait_for(state="visible", timeout=5000)
    start.click()
    fc_view.locator(".card .card-content").wait_for(state="visible", timeout=5000)


# Installed as an init script. The accessor property swallows the real
# /tts-engine.js module's later `window.ttsEngine = ...` assignment (a
# plain data-property stub would be overwritten at an arbitrary point in
# the module's async init, making assertions racy).
_TTS_STUB = """
window.__spoken = [];
const __ttsStub = {
  speak(text) {
    window.__spoken.push(text);
    window.dispatchEvent(new CustomEvent('tts:state-change',
        {detail: {state: 'speaking'}}));
    return Promise.resolve();
  },
  stop() {
    window.dispatchEvent(new CustomEvent('tts:state-change',
        {detail: {state: 'idle'}}));
  },
  init() { return Promise.resolve(); },
};
Object.defineProperty(window, 'ttsEngine', {
  get: () => __ttsStub,
  set: () => {},
  configurable: false,
});
"""


def test_flashcard_deck_opens_and_flips(web_page: Page) -> None:
    """Journey: Flashcards tab -> open deck -> question shows -> flip -> answer.

    Session decks are shuffled (_shuffleCards), so assertions map whichever
    card is showing to its expected back rather than assuming an order.
    """
    fronts_to_backs = {c["front"]: c["back"] for c in _FLASHCARDS}
    _stub_review_routes(web_page, "flashcards", _FLASHCARDS)
    _open_deck(web_page, "flashcards", "flashcard", "flashcards")

    fc_view = web_page.locator('.content-area > div[x-show*="flashcards"]')
    card = fc_view.locator(".card:visible").first
    content = card.locator(".card-content")

    front = content.inner_text().strip()
    assert front in fronts_to_backs, f"unexpected card front: {front!r}"

    card.dispatch_event("click")  # flip
    fc_view.locator(".card.revealed:visible").wait_for(state="visible", timeout=3000)
    assert fronts_to_backs[front] in content.inner_text()

    # Answering advances to the other card in the (shuffled) deck.
    other_front = next(f for f in fronts_to_backs if f != front)
    fc_view.get_by_role("button", name="I knew it").click()
    web_page.wait_for_function(
        """(expected) => {
          const el = document.querySelector('.content-area .card.revealed')
            ? null
            : [...document.querySelectorAll('.content-area .card-content')]
                .find(e => e.offsetParent !== null);
          return el && el.textContent.includes(expected);
        }""",
        arg=other_front,
        timeout=3000,
    )


def test_quiz_opens_and_answers(web_page: Page) -> None:
    """Journey: Quizzes tab -> open quiz -> answer correctly -> rationale."""
    _stub_review_routes(web_page, "quiz", _QUIZ_CARDS)
    _open_deck(web_page, "quizzes", "quiz", "quiz")

    qz_view = web_page.locator('.content-area > div[x-show*="quizzes"]')
    question = qz_view.locator(".card:visible .card-content").first.inner_text().strip()
    quiz = next(c for c in _QUIZ_CARDS if c["question"] == question)
    correct = next(o for o in quiz["options"] if o["is_correct"])

    qz_view.locator(".quiz-option", has_text=correct["text"]).click()
    # Atomic read: the card auto-advances 1.5s after answering, so wait on
    # the rationale text itself rather than visibility-then-read.
    web_page.wait_for_function(
        """(expected) => [...document.querySelectorAll('.rationale')].some(
             e => e.offsetParent !== null && e.textContent.includes(expected))""",
        arg=correct["rationale"].rstrip("."),
        timeout=3000,
    )


def test_voice_reads_flashcard_aloud(web_page: Page) -> None:
    """Voice wiring: toggle voice, read a card via the speak button and 'T'.

    Headless Chromium has no audio and the neural TTS model download is far
    too heavy for a smoke test, so window.ttsEngine is stubbed — the test
    verifies the app-side wiring: toggle announcement, per-card speak,
    keyboard shortcut, and the isSpeaking -> stop-button state loop.
    Decks are shuffled, so spoken text is matched against whichever card
    is actually showing.
    """
    fronts_to_backs = {c["front"]: c["back"] for c in _FLASHCARDS}
    web_page.add_init_script(_TTS_STUB)
    _stub_review_routes(web_page, "flashcards", _FLASHCARDS)
    _open_deck(web_page, "flashcards", "flashcard", "flashcards")

    fc_view = web_page.locator('.content-area > div[x-show*="flashcards"]')
    front = fc_view.locator(".card:visible .card-content").inner_text().strip()
    assert front in fronts_to_backs, f"unexpected card front: {front!r}"

    # Toggle voice on — announces "Voice enabled" through the engine.
    web_page.locator('button[title*="Toggle voice"]').click()
    web_page.wait_for_function("() => window.__spoken.includes('Voice enabled')", timeout=5000)

    # The announcement flips isSpeaking -> stop button pops into the
    # toolbar. Assert the state loop and settle it before continuing.
    stop_btn = web_page.locator(".stop-tts-btn")
    stop_btn.wait_for(state="visible", timeout=5000)
    stop_btn.click()
    stop_btn.wait_for(state="hidden", timeout=5000)

    # Speak button reads the visible side (the question). dispatch_event
    # targets the handler directly — this test verifies voice wiring, not
    # pointer hit-testing (the flashcard journey test covers real clicks).
    fc_view.locator(".card:visible .speak-btn").first.dispatch_event("click")
    web_page.wait_for_function("(f) => window.__spoken.includes(f)", arg=front, timeout=5000)

    # Keyboard shortcut 'T' reads the revealed side after a flip.
    web_page.evaluate("() => window.ttsEngine.stop()")
    fc_view.locator(".card:visible").first.dispatch_event("click")
    fc_view.locator(".card.revealed:visible").wait_for(state="visible", timeout=5000)
    web_page.keyboard.press("t")
    web_page.wait_for_function(
        "(b) => window.__spoken.includes(b)",
        arg=fronts_to_backs[front],
        timeout=5000,
    )
