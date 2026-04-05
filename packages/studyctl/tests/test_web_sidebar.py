"""Playwright E2E tests for the unified sidebar navigation.

Validates that clicking each sidebar tab shows the correct content panel
and that Alpine components initialise correctly in each view.

Run:
    uv run pytest tests/test_web_sidebar.py -v
    uv run pytest tests/test_web_sidebar.py -v --headed   # watch it run
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

pytestmark = [pytest.mark.e2e]

CONFIG_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"

WEB_PORT = 18568  # Unique port to avoid conflicts with other test suites


@pytest.fixture()
def _clean_ipc():
    for f in [STATE_FILE, TOPICS_FILE, PARKING_FILE]:
        f.unlink(missing_ok=True)
    yield
    for f in [STATE_FILE, TOPICS_FILE, PARKING_FILE]:
        f.unlink(missing_ok=True)


def _write_state(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2))


def _start_web_server(port: int = WEB_PORT) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "studyctl.cli", "web", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import urllib.request

    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except Exception:
            time.sleep(0.3)
    proc.kill()
    msg = f"Web server failed to start on port {port}"
    raise RuntimeError(msg)


@pytest.fixture()
def web_server(_clean_ipc):
    proc = _start_web_server()
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Sidebar navigation tests
# ---------------------------------------------------------------------------


class TestSidebarNavigation:
    """Verify sidebar tabs switch between content panels."""

    def test_default_view_is_flashcards(self, web_server, page):
        """Page loads with the Flashcards tab active."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        # Flashcards tab should have active class
        fc_btn = page.locator(".sidebar-btn", has_text="Flashcards")
        assert "active" in fc_btn.get_attribute("class")

    def test_click_quizzes_tab(self, web_server, page):
        """Clicking Quizzes tab activates it and shows quiz content."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        quiz_btn = page.locator(".sidebar-btn", has_text="Quizzes")
        quiz_btn.click()
        page.wait_for_timeout(500)

        assert "active" in quiz_btn.get_attribute("class")
        # Flashcards tab should no longer be active
        fc_btn = page.locator(".sidebar-btn", has_text="Flashcards")
        assert "active" not in fc_btn.get_attribute("class")

    def test_click_body_double_tab(self, web_server, page):
        """Clicking Body Double tab shows the timer + terminal layout."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        bd_btn = page.locator(".sidebar-btn", has_text="Body Double")
        bd_btn.click()
        page.wait_for_timeout(500)

        assert "active" in bd_btn.get_attribute("class")

        # Body double dashboard should be visible
        bd_header = page.locator(".body-double-header h2")
        assert bd_header.is_visible()
        assert "Body Double" in bd_header.text_content()

    def test_click_study_session_tab(self, web_server, page):
        """Clicking Study Session tab shows the session dashboard."""
        _write_state(
            {
                "study_session_id": "test-sidebar",
                "topic": "Sidebar Test",
                "energy": 7,
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        ss_btn = page.locator(".sidebar-btn", has_text="Study Session")
        ss_btn.click()
        page.wait_for_timeout(1000)

        assert "active" in ss_btn.get_attribute("class")

        # Session timer should be visible
        timer = page.locator(".session-timer")
        assert timer.is_visible()

        # Topic should appear in session meta
        meta = page.locator(".meta-topic")
        assert "Sidebar Test" in meta.text_content()

    def test_hash_routing_direct_navigation(self, web_server, page):
        """Navigating directly to a hash activates the correct tab."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#body-double")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        bd_btn = page.locator(".sidebar-btn", has_text="Body Double")
        assert "active" in bd_btn.get_attribute("class")

        bd_header = page.locator(".body-double-header h2")
        assert bd_header.is_visible()

    def test_session_route_hash_routing(self, web_server, page):
        """The /session route works with hash routing."""
        _write_state(
            {
                "study_session_id": "test-route",
                "topic": "Route Test",
                "energy": 5,
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/session#study-session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        ss_btn = page.locator(".sidebar-btn", has_text="Study Session")
        assert "active" in ss_btn.get_attribute("class")

    def test_all_four_tabs_exist(self, web_server, page):
        """All four sidebar tabs are rendered."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_load_state("load")

        tabs = page.locator(".sidebar-btn")
        assert tabs.count() == 4

        labels = [tabs.nth(i).text_content().strip() for i in range(4)]
        assert "Flashcards" in labels
        assert "Quizzes" in labels
        assert "Body Double" in labels
        assert "Study Session" in labels


# ---------------------------------------------------------------------------
# Panel content tests
# ---------------------------------------------------------------------------


class TestFlashcardsPanel:
    """Verify the Flashcards panel loads courses via Alpine."""

    def test_course_grid_loads(self, web_server, page):
        """Flashcards view renders the Alpine course grid (or empty state)."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)

        # With no review dirs configured, the "No courses found" message shows
        # The review-content div should be visible in the flashcards panel
        content = page.locator(".review-content").first
        assert content.is_visible()


class TestStudySessionPanel:
    """Verify the Study Session panel shows live session data."""

    def test_timer_shows_energy(self, web_server, page):
        """Session timer displays the energy level from state."""
        _write_state(
            {
                "study_session_id": "test-energy",
                "topic": "Energy Check",
                "energy": 8,
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1500)

        energy = page.locator(".meta-energy")
        assert "8/10" in energy.text_content()

    def test_counter_bar_visible(self, web_server, page):
        """Counter bar shows WINS/PARKED/REVIEW labels."""
        _write_state(
            {
                "study_session_id": "test-counters",
                "topic": "Counter Test",
                "energy": 5,
            }
        )

        page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        wins = page.locator("#counter-wins")
        assert "WINS" in wins.text_content()


class TestBodyDoublePanel:
    """Verify the Body Double panel has timer controls."""

    def test_pomodoro_button_exists(self, web_server, page):
        """Body Double view has a Start Pomodoro button."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/#body-double")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        btn = page.locator(".body-double-controls .toggle-btn")
        assert btn.is_visible()
        assert "Pomodoro" in btn.text_content()


class TestHeaderControls:
    """Verify header controls work with Alpine stores."""

    def test_theme_toggle(self, web_server, page):
        """Clicking theme toggle adds/removes light class."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        body_classes = page.locator("body").get_attribute("class") or ""
        was_light = "light" in body_classes

        # Click theme toggle (the sun icon button)
        theme_btn = page.locator("button[title='Toggle light/dark theme']")
        theme_btn.click()
        page.wait_for_timeout(300)

        body_classes = page.locator("body").get_attribute("class") or ""
        if was_light:
            assert "light" not in body_classes
        else:
            assert "light" in body_classes

    def test_dyslexic_toggle(self, web_server, page):
        """Clicking dyslexic toggle adds/removes dyslexic class."""
        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_load_state("load")
        page.wait_for_timeout(1000)

        body_classes = page.locator("body").get_attribute("class") or ""
        was_dyslexic = "dyslexic" in body_classes

        dys_btn = page.locator("button[title='Toggle OpenDyslexic font']")
        dys_btn.click()
        page.wait_for_timeout(300)

        body_classes = page.locator("body").get_attribute("class") or ""
        if was_dyslexic:
            assert "dyslexic" not in body_classes
        else:
            assert "dyslexic" in body_classes
