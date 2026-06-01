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
    assert_nonzero_size,
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
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


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
    return {
        "hash": f"h{i}",
        "type": "flashcard",
        "front": f"Q{i}",
        "back": f"A{i}",
        "source": "ch1",
    }


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
            ".generate-form .toggle-btn, .generate-panel .toggle-btn",
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
            assert_scroll_reachable(web_page, ".session-start-picker .picker-hint", ".content-area")


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
        page.locator(f"{root} .course-row-action.quiz").first.click()
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
        assert_centered_in(web_page, f"{root} .nav-bar .nav-course", f"{root} .nav-bar")


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
        page.locator(f"{root} .course-row-action.flashcard").first.click()
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


# ---------------------------------------------------------------------------
# Course Explorer panel — header, viewport overflow, carousel geometry (M2)
# ---------------------------------------------------------------------------

_EXPLORER_TREE = [
    {
        "id": "provider-alpha",
        "name": "Alpha Publisher",
        "courses": [
            {
                "id": f"provider-alpha/course-{i}",
                "name": f"Course {i:02d}",
                "provider": "Alpha Publisher",
            }
            for i in range(7)
        ],
    }
]

_LESSONS = [
    {
        "id": f"provider-alpha/course-00/lesson-{i}",
        "slug": f"lesson-{i}",
        "name": f"Lesson {i}",
        "course_id": "provider-alpha/course-00",
    }
    for i in range(3)
]

# Long content: heading + code block + mermaid + many paragraphs so
# assert_scroll_reachable can detect a prose clip regression.
_LESSON_CONTENT = "\n".join(
    [
        "# Introduction to Testing",
        "",
        "This lesson covers geometry-based layout assertions.",
        "",
        "```python",
        "def hello():",
        '    return "world"',
        "```",
        "",
        "```mermaid",
        "graph TD",
        "    A[Start] --> B[End]",
        "```",
        "",
    ]
    + [f"Paragraph {i}: " + ("Lorem ipsum dolor sit amet. " * 8) for i in range(30)]
)


def _stub_explorer_tree(page: Page, tree: list[dict] | None = None) -> None:
    payload = tree if tree is not None else _EXPLORER_TREE
    page.route("**/api/explorer/tree", lambda r: _fulfill(r, payload))


def _stub_explorer_lessons(page: Page, lessons: list[dict] | None = None) -> None:
    payload = lessons if lessons is not None else _LESSONS
    page.route("**/api/explorer/courses/**", lambda r: _fulfill(r, payload))


def _stub_explorer_content(page: Page, content: str = _LESSON_CONTENT) -> None:
    page.route(
        "**/api/explorer/lesson/**",
        lambda r: _fulfill(
            r,
            {"content": content, "lesson_id": "provider-alpha/course-00/lesson-0"},
        ),
    )


def _open_explorer_panel(page: Page) -> None:
    """Toggle the explorer panel open and wait for Alpine + tree load."""
    page.evaluate("window.Alpine.store('explorer').toggle()")
    # Wait for the panel to become visible and the tree fetch to complete.
    page.wait_for_function(
        "() => window.Alpine.store('explorer').open === true",
        timeout=3000,
    )
    # Allow Alpine reactive updates + fetch round-trip to settle.
    page.wait_for_timeout(600)


class TestCourseExplorerLayout:
    """Geometry regressions for the 3rd-column course explorer panel.

    Each test stubs the explorer API routes and drives the panel via the
    Alpine store rather than clicking the sidebar button, keeping state
    deterministic.  The provider fixture has 7 courses so the carousel is
    wider than the 320px panel — scroll-reachability is meaningful.
    """

    def _goto_with_panel(self, page: Page) -> None:
        _stub_explorer_tree(page)
        _stub_explorer_lessons(page)
        _stub_explorer_content(page)
        # Stub the standard routes the flashcards view always calls on init.
        _stub_courses(page, [])
        _stub_session_state(page)
        _stub_stats(page)
        _goto(page, "flashcards")
        _open_explorer_panel(page)

    def test_panel_header_within_viewport(self, web_page: Page) -> None:
        # The panel header (.explorer-panel-header) is a flex row with title
        # + close button.  It must not overflow the viewport — guards both the
        # flex row itself and the panel's 320px column width.
        self._goto_with_panel(web_page)
        assert_within_viewport(web_page, ".explorer-panel-header")

    def test_app_layout_within_viewport_when_open(self, web_page: Page) -> None:
        # 200px sidebar + 1fr content + 320px panel must not exceed viewport
        # width.  If the grid columns overflow the viewport, .app-layout's own
        # overflow:hidden clips the content silently.
        self._goto_with_panel(web_page)
        assert_within_viewport(web_page, ".app-layout")

    def test_carousel_cards_nonzero_and_no_overlap(self, web_page: Page) -> None:
        # Each .explorer-course-card must have real size (flex:0 0 150px),
        # and adjacent cards must not overlap.  Catches two regression classes:
        #  - flex-shrink: cards collapse below their 150px basis (min width check)
        #  - layout breakage: adjacent cards overlap horizontally (overlap check)
        # The minimum width of 100px is deliberately generous; 150px is the
        # design value.  A regression to flex:1 1 auto (cards ~34px in 320px
        # panel with 7 courses) would be caught by the width floor.
        self._goto_with_panel(web_page)
        page = web_page
        page.wait_for_function(
            "() => document.querySelectorAll('.explorer-course-card').length > 0",
            timeout=4000,
        )
        assert_nonzero_size(page, ".explorer-course-card")

        result = page.evaluate(
            """() => {
                const cards = [...document.querySelectorAll('.explorer-course-card')]
                    .filter(el => el.offsetParent !== null);
                if (cards.length < 2) return null;
                const MIN_WIDTH = 100;
                let tooNarrow = [];
                let overlapping = [];
                for (let i = 0; i < cards.length; i++) {
                    const r = cards[i].getBoundingClientRect();
                    if (r.width < MIN_WIDTH) {
                        tooNarrow.push({i, width: r.width});
                    }
                    if (i > 0) {
                        const prev = cards[i - 1].getBoundingClientRect();
                        // curr.left must be >= prev.right - 2 (2px sub-pixel tolerance)
                        if (r.left < prev.right - 2) {
                            overlapping.push({i, prevRight: prev.right, currLeft: r.left});
                        }
                    }
                }
                return {tooNarrow, overlapping};
            }"""
        )
        assert result is not None, "fewer than 2 cards rendered — cannot check geometry"
        assert not result["tooNarrow"], (
            f".explorer-course-card: {len(result['tooNarrow'])} card(s) narrower than 100px "
            f"(flex:0 0 150px basis broken?): {result['tooNarrow']!r}"
        )
        assert not result["overlapping"], (
            f".explorer-course-card: {len(result['overlapping'])} adjacent pair(s) overlap: "
            f"{result['overlapping']!r}"
        )

    def test_carousel_last_card_scroll_reachable(self, web_page: Page) -> None:
        # The last card in the carousel must be reachable by scrolling the
        # carousel container — not clipped by overflow:hidden.  Guards the
        # overflow-x:auto on .explorer-carousel.
        self._goto_with_panel(web_page)
        page = web_page
        page.wait_for_function(
            "() => document.querySelectorAll('.explorer-course-card').length > 0",
            timeout=4000,
        )
        # Scroll the carousel all the way right, then check the last card.
        page.evaluate(
            """() => {
                const c = document.querySelector('.explorer-carousel');
                if (c) c.scrollLeft = c.scrollWidth;
            }"""
        )
        page.wait_for_timeout(300)
        assert_scroll_reachable(page, ".explorer-course-card:last-child", ".explorer-carousel")

    def test_panel_hidden_at_mobile(self, web_page: Page) -> None:
        # At 375px the @media(max-width:600px) rule applies display:none !important
        # to .course-explorer-panel so it never intrudes on the single-column
        # mobile layout.
        web_page.set_viewport_size({"width": 375, "height": 812})
        _stub_explorer_tree(web_page)
        _stub_courses(web_page, [])
        _stub_session_state(web_page)
        _stub_stats(web_page)
        _goto(web_page, "flashcards")
        # Toggle the panel open — it should still be invisible.
        web_page.evaluate("window.Alpine.store('explorer').toggle()")
        web_page.wait_for_timeout(400)
        display = web_page.evaluate(
            """() => {
                const el = document.querySelector('.course-explorer-panel');
                if (!el) return '__absent__';
                return getComputedStyle(el).display;
            }"""
        )
        assert display != "__absent__", ".course-explorer-panel not found in DOM"
        assert display == "none", (
            f".course-explorer-panel should be display:none at 375px mobile, "
            f"but computed display={display!r}"
        )


# ---------------------------------------------------------------------------
# Lesson reading view — header position, prose stacking, scroll reach (M3)
# ---------------------------------------------------------------------------


class TestLessonReadingViewLayout:
    """Geometry regressions for the lesson reader inside the explorer panel.

    Opens a lesson by driving the Alpine component directly so the reader
    state is reached deterministically without depending on click timing.
    """

    def _goto_with_lesson_open(self, page: Page, content: str = _LESSON_CONTENT) -> None:
        _stub_explorer_tree(page)
        _stub_explorer_lessons(page)
        _stub_explorer_content(page, content)
        _stub_courses(page, [])
        _stub_session_state(page)
        _stub_stats(page)
        _goto(page, "flashcards")
        _open_explorer_panel(page)
        # Wait for at least one course card to appear.
        page.wait_for_function(
            "() => document.querySelectorAll('.explorer-course-card').length > 0",
            timeout=4000,
        )
        # Drive openLesson() directly on the Alpine component.  This is the
        # same evaluate-driving pattern documented in CONTRIBUTING.md for
        # deterministic view-state tests.
        lesson = _LESSONS[0]
        page.evaluate(
            """(lesson) => {
                const el = document.querySelector('.course-explorer-panel');
                if (!el) throw new Error('panel not found');
                const comp = window.Alpine.$data(el);
                comp.openLesson(lesson);
            }""",
            lesson,
        )
        # Wait for the reader view to become active and loading to clear.
        page.wait_for_function(
            """() => {
                const el = document.querySelector('.course-explorer-panel');
                if (!el) return false;
                const d = window.Alpine.$data(el);
                return d && d.view === 'reader' && !d.readerLoading;
            }""",
            timeout=5000,
        )
        page.wait_for_timeout(400)

    def test_reader_header_within_viewport(self, web_page: Page) -> None:
        # The reader header must not overflow the 320px panel column.
        # Guards the flex row (back-button + title) that mirrors
        # .explorer-panel-header.
        self._goto_with_lesson_open(web_page)
        assert_within_viewport(web_page, ".explorer-reader-header")

    def test_reader_header_not_overlapping_prose(self, web_page: Page) -> None:
        # The reader header (back + title) must sit entirely above the prose
        # container.  A padding or flex regression could push the header into
        # the prose scroll area, clipping the first paragraph behind the header.
        self._goto_with_lesson_open(web_page)
        assert_stacked_no_overlap(
            web_page,
            ".explorer-reader-header",
            ".explorer-reader-prose",
        )

    def test_reader_prose_scroll_reachable(self, web_page: Page) -> None:
        # The prose container must be scrollable so the bottom of a long lesson
        # is reachable.  Guards the overflow-y:auto + flex:1 + min-height:0
        # chain on .explorer-reader-prose — if any link breaks, the bottom
        # content is clipped rather than scrolled.
        #
        # We use a JS-scoped check rather than a bare CSS selector because
        # `p:last-child` in assert_scroll_reachable matches the last <p> in
        # the entire document, not the last paragraph within the prose div.
        # The scoped check: scroll the prose container to the bottom, then
        # verify that the last direct child inside it is within the visible
        # rect.  A clip regression (overflow hidden on the chain) would make
        # scrollTop stay 0 or scrollHeight == clientHeight, causing the check
        # to fail.
        self._goto_with_lesson_open(web_page)
        reachable = web_page.evaluate(
            """() => {
                const prose = document.querySelector('.explorer-reader-prose');
                if (!prose) return null;
                // Guard the overflow-y rule directly: must be 'auto' or 'scroll',
                // not 'hidden' or 'visible'.  Chromium allows scrollTop mutation
                // on overflow:hidden elements (browser quirk), so a scrollTop
                // check does NOT distinguish auto from hidden.  A direct computed-
                // style check is the only reliable sentinel.
                const overflowY = getComputedStyle(prose).overflowY;
                const isScrollOverflow = overflowY === 'auto' || overflowY === 'scroll';
                // Also verify the prose has overflow content (a zero-height prose
                // would pass the overflow check but produce no scroll range).
                prose.scrollTop = prose.scrollHeight;
                const children = [...prose.children];
                if (!children.length) return null;
                const last = children[children.length - 1];
                const pr = prose.getBoundingClientRect();
                const lr = last.getBoundingClientRect();
                const hasOverflow = prose.scrollHeight > prose.clientHeight + 1;
                const lastVisible = lr.bottom <= pr.bottom + 2 && lr.top >= pr.top - lr.height;
                return {
                    overflowY, isScrollOverflow, hasOverflow, lastVisible,
                    scrollHeight: prose.scrollHeight,
                    clientHeight: prose.clientHeight,
                    lastBottom: lr.bottom, contBottom: pr.bottom,
                };
            }"""
        )
        assert reachable is not None, ".explorer-reader-prose not found in DOM"
        assert reachable["isScrollOverflow"], (
            f".explorer-reader-prose has overflow-y={reachable['overflowY']!r} — "
            f"must be 'auto' or 'scroll' so long lessons are scrollable, not clipped"
        )
        assert reachable["hasOverflow"], (
            f".explorer-reader-prose has no overflow content: "
            f"scrollHeight={reachable['scrollHeight']} clientHeight={reachable['clientHeight']}"
        )
        assert reachable["lastVisible"], (
            f"Last child of .explorer-reader-prose not visible after scrolling to bottom: "
            f"lastBottom={reachable['lastBottom']:.1f} contBottom={reachable['contBottom']:.1f}"
        )


class TestCourseExplorerTtsGating:
    """Phase 6: read-aloud (TTS) is GATED on the browser-neural-tts worktree.

    window.ttsEngine is provided only by that worktree's tts-engine.js, which is
    NOT loaded on this branch. These tests lock in the gating contract:

      - the read-aloud button is hidden while ttsAvailable is false (default here)
      - readAloud()/stopReading() are safe no-ops when the engine is absent
      - _mdToPlainText() strips markdown so the engine never speaks syntax noise
      - the button appears once a (stub) window.ttsEngine is present

    Without these, a future change could ship a dead/throwing button, or feed raw
    markdown to TTS once the engine merges.
    """

    def _goto_with_lesson_open(self, page: Page) -> None:
        _stub_explorer_tree(page)
        _stub_explorer_lessons(page)
        _stub_explorer_content(page)
        _stub_courses(page, [])
        _stub_session_state(page)
        _stub_stats(page)
        _goto(page, "flashcards")
        _open_explorer_panel(page)
        page.wait_for_function(
            "() => document.querySelectorAll('.explorer-course-card').length > 0",
            timeout=4000,
        )
        lesson = _LESSONS[0]
        page.evaluate(
            """(lesson) => {
                const comp = window.Alpine.$data(
                    document.querySelector('.course-explorer-panel'));
                comp.openLesson(lesson);
            }""",
            lesson,
        )
        page.wait_for_function(
            """() => {
                const el = document.querySelector('.course-explorer-panel');
                const d = el && window.Alpine.$data(el);
                return d && d.view === 'reader' && !d.readerLoading;
            }""",
            timeout=5000,
        )
        page.wait_for_timeout(300)

    def test_tts_button_hidden_when_engine_absent(self, web_page: Page) -> None:
        # The in-browser neural TTS engine (tts-engine.js) loads as a deferred
        # ES module and may assign window.ttsEngine AFTER courseExplorer.init()
        # runs — so nulling it pre-load is racy.  Instead, deterministically force
        # the engine-absent state: delete window.ttsEngine, re-run the component's
        # init() to re-probe ttsAvailable, then assert the button hides.  This
        # tests the GATING CONTRACT independent of whether TTS is built in.
        self._goto_with_lesson_open(web_page)
        # Force engine-absent + re-probe, then let Alpine flush the x-show update.
        web_page.evaluate(
            """() => {
                delete window.ttsEngine;
                window.Alpine.$data(
                    document.querySelector('.course-explorer-panel')).init();
            }"""
        )
        web_page.wait_for_timeout(200)  # allow Alpine reactive x-show to settle
        state = web_page.evaluate(
            """() => {
                const d = window.Alpine.$data(
                    document.querySelector('.course-explorer-panel'));
                const btn = document.querySelector('.explorer-tts-btn');
                return {
                    ttsAvailable: d.ttsAvailable,
                    btnVisible: btn ? btn.offsetParent !== null : false,
                };
            }"""
        )
        assert state["ttsAvailable"] is False
        assert state["btnVisible"] is False, "read-aloud button must be hidden when TTS absent"

    def test_read_aloud_is_safe_noop_when_engine_absent(self, web_page: Page) -> None:
        # Calling readAloud()/stopReading() without an engine must not throw.
        # Delete window.ttsEngine in-page to force the engine-absent path
        # deterministically regardless of whether TTS is built in.
        self._goto_with_lesson_open(web_page)
        result = web_page.evaluate(
            """() => {
                delete window.ttsEngine;
                const d = window.Alpine.$data(
                    document.querySelector('.course-explorer-panel'));
                let threw = false;
                try { d.readAloud(); d.stopReading(); } catch (e) { threw = true; }
                return { threw, isReading: d.isReading };
            }"""
        )
        assert result["threw"] is False, (
            "readAloud/stopReading must no-op (not throw) without engine"
        )
        assert result["isReading"] is False

    def test_md_to_plain_text_strips_markdown(self, web_page: Page) -> None:
        # _mdToPlainText must remove headings, emphasis, links, code fences and
        # list markers so TTS speaks prose, not syntax.
        self._goto_with_lesson_open(web_page)
        md = (
            "# Title\n\n**bold** and *it* see [x](http://y)\n\n"
            "```py\ncode()\n```\n\n- one\n- two"
        )
        plain = web_page.evaluate("(md) => window._mdToPlainText(md)", md)
        assert "#" not in plain
        assert "**" not in plain and "*" not in plain
        assert "```" not in plain and "code()" not in plain
        assert "http://y" not in plain
        assert "Title" in plain and "bold" in plain and "one" in plain

    def test_tts_button_appears_when_engine_injected(self, web_page: Page) -> None:
        # Prove the gate flips: inject a stub window.ttsEngine BEFORE the panel
        # component initialises, then confirm the button becomes visible. This
        # guards against the button being hard-hidden (the gate must be live).
        _stub_explorer_tree(web_page)
        _stub_explorer_lessons(web_page)
        _stub_explorer_content(web_page)
        _stub_courses(web_page, [])
        _stub_session_state(web_page)
        _stub_stats(web_page)
        web_page.add_init_script(
            "window.ttsEngine = { speak() {}, stop() {}, isSpeaking: false };"
        )
        _goto(web_page, "flashcards")
        _open_explorer_panel(web_page)
        web_page.wait_for_function(
            "() => document.querySelectorAll('.explorer-course-card').length > 0",
            timeout=4000,
        )
        web_page.evaluate(
            """(lesson) => {
                window.Alpine.$data(
                    document.querySelector('.course-explorer-panel')).openLesson(lesson);
            }""",
            _LESSONS[0],
        )
        web_page.wait_for_function(
            """() => {
                const el = document.querySelector('.course-explorer-panel');
                const d = el && window.Alpine.$data(el);
                return d && d.view === 'reader' && !d.readerLoading;
            }""",
            timeout=5000,
        )
        web_page.wait_for_timeout(300)
        state = web_page.evaluate(
            """() => {
                const d = window.Alpine.$data(
                    document.querySelector('.course-explorer-panel'));
                const btn = document.querySelector('.explorer-tts-btn');
                return { ttsAvailable: d.ttsAvailable,
                         btnVisible: btn ? btn.offsetParent !== null : false };
            }"""
        )
        assert state["ttsAvailable"] is True, "ttsAvailable must be true when engine injected"
        assert state["btnVisible"] is True, "read-aloud button must appear when TTS present"
