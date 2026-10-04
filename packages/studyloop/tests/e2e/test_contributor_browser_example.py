"""A complete isolated browser journey for the contributor testing cookbook.

Keep test basenames unique: the coverage collector also collects in prepend import mode.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("requests")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import ConsoleWatch, RunningServer, build_test_world, diag, start_server  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]
WEB_PORT = 18679  # Unique to this module; never use the developer's live port, 18611.


@pytest.fixture(scope="module")
def example_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[RunningServer, None, None]:
    world = build_test_world(tmp_path_factory.mktemp("contributor-browser"), port=WEB_PORT)
    server = start_server(world)
    try:
        yield server
    finally:
        server.stop()


def test_parked_thought_survives_fresh_visit(
    page: Page, browser: Browser, example_server: RunningServer
) -> None:
    watch = ConsoleWatch(page)
    question = "Why does this example persist?"
    try:
        page.goto(f"{example_server.base_url}/#today")
        page.wait_for_function("() => !!window.Alpine && !!window.Alpine.store('nav')")

        page.keyboard.press("p")
        page.locator(".quick-park-input").fill(question)
        page.get_by_role("button", name="Park it", exact=True).click()
        expect(page.locator(".quick-park-overlay")).to_be_hidden()
        page.locator("#parking-lot-toggle").click()
        panel = page.locator("#parking-panel")
        expect(panel).to_be_visible()
        expect(panel.get_by_text(question, exact=True)).to_be_visible()

        watch.assert_clean("parking a thought")
        watch.assert_no_csp_violations()

        # A fresh context proves persistence without reusing browser memory or local storage.
        # Keep the first page open: unloading its SSE stream logs an unrelated HTMX Event.
        with browser.new_context() as fresh_context:
            fresh_page = fresh_context.new_page()
            fresh_watch = ConsoleWatch(fresh_page)
            try:
                fresh_page.goto(f"{example_server.base_url}/#today")
                fresh_page.wait_for_function(
                    "() => !!window.Alpine && !!window.Alpine.store('nav')"
                )
                fresh_page.locator("#parking-lot-toggle").click()
                fresh_panel = fresh_page.locator("#parking-panel")
                expect(fresh_panel.get_by_text(question, exact=True)).to_be_visible()
                fresh_watch.assert_clean("reopening the parking board in a fresh context")
                fresh_watch.assert_no_csp_violations()
            except Exception:
                diag(fresh_page, "contributor-example-fresh-visit", fresh_watch)
                raise
    except Exception:
        diag(page, "contributor-example", watch)
        raise
