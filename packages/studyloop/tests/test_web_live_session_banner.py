"""Playwright tests for the 'Live session' banner stale-state bug.

Scenario: user starts a session, stops it, then navigates to Flashcards.
The 'Live session: <topic>' banner must NOT be visible — neither immediately
nor after a page refresh (state is cleared, not just hidden).

Root cause fixed: reviewApp.init() now listens for 'study-session-stop'
and clears this.liveSession; _loadLiveSession() also ignores mode='ended'.

Plan: packages/studyloop/src/studyloop/web/static/components.js
      packages/studyloop/src/studyloop/web/static/index.html
"""

from __future__ import annotations

import json
import sys
import time
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

WEB_PORT = 18585

web_server = web_server_fixture_factory(WEB_PORT)
auth_context = auth_context_fixture_factory()
web_page = web_page_fixture_factory("web_server", "auth_context")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fulfill(route: Route, payload: object, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _stub_session_state(page: Page, state: dict | None = None) -> None:
    page.route("**/api/session/state", lambda route: _fulfill(route, state or {}))


def _stub_session_end(page: Page) -> None:
    page.route(
        "**/api/session/end",
        lambda route: (
            _fulfill(route, {"ended": True, "topic": "SQL"}, status=200)
            if route.request.method == "POST"
            else route.continue_()
        ),
    )


def _goto(page: Page, hash_: str = "flashcards") -> None:
    url = f"http://127.0.0.1:{WEB_PORT}/#{hash_}"
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)


def _wait_flashcards_init(page: Page) -> None:
    """Wait for reviewApp('flashcards').init() to complete."""
    page.wait_for_function(
        """() => {
          // Find the flashcards component by its OWN identity rather than by
          // document position. The old form took the first '.content-area
          // [x-data]', which silently became the hidden todayPanel() when the
          // Today panel was added - so this helper waited forever for a
          // component that has no .mode. Searching by mode survives any future
          // panel being inserted ahead of flashcards.
          const roots = [...document.querySelectorAll('.content-area [x-data]')];
          const el = roots.find((node) => {
            const data = window.Alpine && window.Alpine.$data(node);
            return data && data.mode === 'flashcards';
          });
          if (!el) return false;
          const d = window.Alpine.$data(el);
          // Wait for init()'s OWN completion flag. Every proxy signal tried here
          // was wrong: `courses` is an array from its initial `[]` (true before
          // init runs at all), and `coursesLoading === false` fires in
          // _loadCourses()'s finally — measured ~250ms BEFORE liveSession is
          // populated — so tests reading liveSession raced the fetch.
          return d._initDone === true;
        }""",
        timeout=6000,
    )


def _live_session_banner_visible(page: Page) -> bool:
    """Return True if the 'Live session' banner is rendered and visible."""
    return page.evaluate(
        """() => {
          const banner = document.querySelector('.session-indicator');
          if (!banner) return false;
          return window.getComputedStyle(banner).display !== 'none';
        }"""
    )


def _wait_banner_visible(page: Page, timeout: int = 5000) -> None:
    """Wait for the banner to be visible, rather than reading it once.

    The single read this replaces asserted not just the product's contract --
    'while a session is live, the banner is shown' -- but the instant at which
    the paint lands, which the contract says nothing about. It failed in CI
    while passing locally and under every reproduction attempted here: an
    injected Alpine reveal delay (measured at 0ms), a check of whether the
    banner belongs to a different component (it is inside
    reviewApp('flashcards'), the same one the test waits on), and injected
    endpoint latency up to 1500ms, which kept the banner visible throughout.

    A bounded wait cannot hide a real regression: if the banner never appears
    the wait still fails, and _banner_diag records what the page actually
    showed. What it does remove is a failure mode that says nothing about the
    product.
    """
    page.wait_for_function(
        """() => {
          const b = document.querySelector('.session-indicator');
          return !!b && window.getComputedStyle(b).display !== 'none';
        }""",
        timeout=timeout,
    )


def _banner_diag(page: Page, name: str) -> None:
    """Record why a banner assertion failed.

    Added because this file produced a CI failure that could not be diagnosed
    from its traceback: 'assert False' says only that the banner was not
    visible, never whether it was missing from the DOM, hidden by x-show, or
    holding a liveSession the test did not expect. The uploaded artifacts are
    what finally explained the sibling terminal failure.
    """
    results = Path("test-results")
    results.mkdir(exist_ok=True)
    stamp = int(time.time())
    try:
        page.screenshot(path=str(results / f"{name}-{stamp}.png"), full_page=True)
        (results / f"{name}-{stamp}.html").write_text(page.content())
        state = page.evaluate(
            """() => {
                const b = document.querySelector('.session-indicator');
                const el = [...document.querySelectorAll('.content-area [x-data]')]
                    .find((n) => {
                        const p = window.Alpine && window.Alpine.$data(n);
                        return p && p.mode === 'flashcards';
                    });
                const d = el ? window.Alpine.$data(el) : null;
                return {
                    banner_in_dom: !!b,
                    computed_display: b ? getComputedStyle(b).display : '(absent)',
                    inline_style: b ? b.getAttribute('style') : '(absent)',
                    component_found: !!d,
                    init_done: d ? d._initDone : '(none)',
                    live_session: d ? JSON.stringify(d.liveSession) : '(none)',
                    live_epoch: d ? d._liveSessionEpoch : '(none)',
                };
            }"""
        )
        (results / f"{name}-{stamp}-state.json").write_text(json.dumps(state, indent=2))
    except Exception:
        # Diagnostics must never mask the real failure they are describing.
        pass


def _get_alpine_live_session(page: Page) -> object:
    """Return the liveSession value from the flashcards reviewApp component."""
    return page.evaluate(
        """() => {
          // Identity lookup, not document position - see _wait_flashcards_init.
          const el = [...document.querySelectorAll('.content-area [x-data]')]
            .find((node) => {
              const probe = window.Alpine && window.Alpine.$data(node);
              return probe && probe.mode === 'flashcards';
            });
          if (!el) return 'NO_ELEMENT';
          const d = window.Alpine.$data(el);
          if (!d || d.mode !== 'flashcards') return 'NO_DATA';
          return d.liveSession;
        }"""
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLiveSessionBannerClearedOnStop:
    """The 'Live session' banner must disappear when the session is stopped."""

    def test_banner_appears_when_session_active(self, web_page: Page) -> None:
        """Sanity check: banner IS shown when API returns an active session.

        The positive control for this whole class. The four tests after it
        assert the banner is ABSENT, and each of those would pass just as
        happily if the banner were broken and never rendered at all -- so if
        this one is unsound, the class as a whole proves nothing.
        """
        _stub_session_state(
            web_page,
            {
                "study_session_id": "ss-sql-001",
                "topic": "SQL",
                "mode": "focus",
            },
        )
        _goto(web_page, "flashcards")
        _wait_flashcards_init(web_page)

        try:
            web_page.wait_for_function(
                """() => {
                  // Identity lookup, not document position - see _wait_flashcards_init.
                  const el = [...document.querySelectorAll('.content-area [x-data]')]
                    .find((node) => {
                      const probe = window.Alpine && window.Alpine.$data(node);
                      return probe && probe.mode === 'flashcards';
                    });
                  if (!el) return false;
                  const d = window.Alpine.$data(el);
                  return d && d.mode === 'flashcards' && d.liveSession !== null;
                }""",
                timeout=5000,
            )
            # Waited for, not read once: see _wait_banner_visible.
            _wait_banner_visible(web_page)
            assert _live_session_banner_visible(web_page), (
                "Banner should be visible when a session is active"
            )
        except Exception:
            _banner_diag(web_page, "banner-appears-when-active")
            raise

    def test_banner_absent_after_stop_event(self, web_page: Page) -> None:
        """After 'study-session-stop' is dispatched, liveSession clears
        and the banner is hidden — without a page reload."""
        _stub_session_state(
            web_page,
            {
                "study_session_id": "ss-sql-002",
                "topic": "SQL",
                "mode": "focus",
            },
        )
        _stub_session_end(web_page)
        _goto(web_page, "flashcards")
        _wait_flashcards_init(web_page)

        # Confirm banner starts visible.
        web_page.wait_for_function(
            """() => {
              // Identity lookup, not document position - see _wait_flashcards_init.
              const el = [...document.querySelectorAll('.content-area [x-data]')]
                .find((node) => {
                  const probe = window.Alpine && window.Alpine.$data(node);
                  return probe && probe.mode === 'flashcards';
                });
              if (!el) return false;
              const d = window.Alpine.$data(el);
              return d && d.mode === 'flashcards' && d.liveSession !== null;
            }""",
            timeout=5000,
        )

        # Fire the stop event (mirrors what endSession() does in sessionTimer).
        web_page.evaluate("() => window.dispatchEvent(new CustomEvent('study-session-stop'))")

        # Wait until both: Alpine data is null AND DOM reflects it (x-show hides the element).
        web_page.wait_for_function(
            """() => {
              // Identity lookup, not document position - see _wait_flashcards_init.
              const el = [...document.querySelectorAll('.content-area [x-data]')]
                .find((node) => {
                  const probe = window.Alpine && window.Alpine.$data(node);
                  return probe && probe.mode === 'flashcards';
                });
              if (!el) return false;
              const d = window.Alpine.$data(el);
              if (!d || d.mode !== 'flashcards' || d.liveSession !== null) return false;
              const banner = document.querySelector('.session-indicator');
              if (!banner) return true;  // no banner element at all — definitely hidden
              return window.getComputedStyle(banner).display === 'none';
            }""",
            timeout=5000,
        )
        assert not _live_session_banner_visible(web_page), (
            "Banner must be hidden after study-session-stop event"
        )

    def test_banner_absent_on_flashcards_after_stop_then_navigate(self, web_page: Page) -> None:
        """Full user journey: active session → stop → navigate to Flashcards.

        This is the exact bug report scenario. The banner must not appear
        when the user clicks the Flashcards tab after stopping a session.

        Real-world sequence:
        1. Page loads on flashcards (reviewApp init runs, liveSession set).
        2. User navigates to Study Session tab.
        3. User clicks Stop (dispatches study-session-stop).
        4. User clicks Flashcards tab.
        5. Banner must be gone.
        """
        page = web_page

        # Step 1: Load on flashcards — reviewApp init() registers listener and
        # fetches session state (returns active session).
        _stub_session_state(
            page,
            {
                "study_session_id": "ss-sql-003",
                "topic": "SQL",
                "mode": "focus",
            },
        )
        _stub_session_end(page)
        _goto(page, "flashcards")
        _wait_flashcards_init(page)

        # Wait for liveSession to be populated (init() async fetch complete).
        page.wait_for_function(
            """() => {
              // Identity lookup, not document position - see _wait_flashcards_init.
              const el = [...document.querySelectorAll('.content-area [x-data]')]
                .find((node) => {
                  const probe = window.Alpine && window.Alpine.$data(node);
                  return probe && probe.mode === 'flashcards';
                });
              if (!el) return false;
              const d = window.Alpine.$data(el);
              return d && d.mode === 'flashcards' && d.liveSession !== null;
            }""",
            timeout=5000,
        )

        # Step 2: Navigate to Study Session (user clicks that tab).
        page.evaluate("() => window.Alpine.store('nav').go('study-session')")
        page.wait_for_function(
            "() => window.Alpine.store('nav').current === 'study-session'",
            timeout=5000,
        )

        # Step 3: Stop the session (user clicks Stop button).
        page.evaluate("() => window.dispatchEvent(new CustomEvent('study-session-stop'))")

        # Step 4: Navigate back to Flashcards.
        page.evaluate("() => window.Alpine.store('nav').go('flashcards')")
        page.wait_for_function(
            "() => window.Alpine.store('nav').current === 'flashcards'",
            timeout=5000,
        )

        # Step 5: Banner must be gone — liveSession cleared by the stop listener.
        #
        # R-55a: this used to be a page.wait_for_function polling the banner's
        # computed style. That poll runs INSIDE the page's own JS context via
        # requestAnimationFrame, which is exactly what starves under the "machine
        # load" this flaked on (dozens of other browser tests' renderers
        # contending for the same CPU) -- the condition can already be true while
        # the poll itself is not scheduled often enough to observe it before its
        # deadline. Locator.wait_for() polls at the Playwright/CDP layer instead,
        # independent of whether THIS page's render loop gets scheduled, and it
        # is one of this suite's readiness-budget calls (_readiness.SCALED_CALLS),
        # so STUDYLOOP_E2E_TIMEOUT_SCALE still widens it for diagnosis without
        # this call's normal timeout being touched. No x-transition is involved:
        # `.session-indicator` uses a plain x-show (confirmed in index.html), and
        # Alpine's x-show without x-transition toggles `display` synchronously --
        # there is no animation timer to disable here, unlike the sibling
        # x-transition.opacity fade _readiness.py documents as already fixed
        # elsewhere. Do not widen this timeout; the mechanism change is the fix.
        page.locator(".session-indicator").wait_for(state="hidden", timeout=5000)

        live = _get_alpine_live_session(page)
        assert live is None, f"liveSession must be null after stop, got: {live!r}"
        assert not _live_session_banner_visible(page), (
            "Banner must NOT be visible when navigating to Flashcards after stopping"
        )

    def test_banner_absent_after_reload_when_session_ended(self, web_page: Page) -> None:
        """State is durable: after a full page reload, the banner is still gone.

        The server-side session-state.json has mode='ended' after end_session_common()
        writes _signal_dashboard_ended(). _loadLiveSession() must ignore it.
        """
        # Stub the server to return mode=ended (post-stop state).
        _stub_session_state(
            web_page,
            {
                "study_session_id": "ss-sql-004",
                "topic": "SQL",
                "mode": "ended",
            },
        )
        _goto(web_page, "flashcards")
        _wait_flashcards_init(web_page)

        live = _get_alpine_live_session(web_page)
        assert live is None, f"liveSession must be null when mode=ended on page load, got: {live!r}"
        assert not _live_session_banner_visible(web_page), (
            "Banner must NOT be visible when server returns mode=ended"
        )

    def test_banner_absent_after_no_session(self, web_page: Page) -> None:
        """Baseline: no session state → banner is not shown."""
        _stub_session_state(web_page, {})
        _goto(web_page, "flashcards")
        _wait_flashcards_init(web_page)

        assert not _live_session_banner_visible(web_page), (
            "Banner must not be visible with no session state"
        )
