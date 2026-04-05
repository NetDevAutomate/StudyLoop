"""Playwright E2E tests for the unified sidebar navigation.

Validates that clicking each sidebar tab shows the correct content panel
and that Alpine components initialise correctly in each view.

Run:
    uv run pytest tests/test_web_sidebar.py -v
    uv run pytest tests/test_web_sidebar.py -v --headed   # watch it run
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
    # Poll until server responds — a 401 (auth from config) is still "up"
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return proc  # server is up, just auth-protected
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    proc.kill()
    msg = f"Web server failed to start on port {port}"
    raise RuntimeError(msg)


AUTH_PORT = 18569  # Separate port for auth tests
AUTH_PASSWORD = "test-pass-123"  # pragma: allowlist secret


def _get_effective_credentials() -> tuple[str, str]:
    """Return (username, password) the CLI will use from config."""
    try:
        from studyctl.settings import load_settings

        settings = load_settings()
        username = settings.lan_username or "study"
        password = settings.lan_password or ""
        return username, password
    except Exception:
        return "study", ""


# Resolve once at module load so all tests use the same value.
_EFFECTIVE_USERNAME, _EFFECTIVE_PASSWORD = _get_effective_credentials()
AUTH_USERNAME = _EFFECTIVE_USERNAME


def _start_auth_web_server(
    port: int = AUTH_PORT,
    username: str = AUTH_USERNAME,
    password: str = AUTH_PASSWORD,
) -> subprocess.Popen:
    """Start web server with HTTP Basic Auth enabled."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "studyctl.cli",
            "web",
            "--port",
            str(port),
            "--password",
            password,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Poll until server is up — a 401 means the server is running (auth is active)
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc  # unlikely (no auth header), but handle it
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return proc  # server is up and enforcing auth
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    proc.kill()
    msg = f"Auth web server failed to start on port {port}"
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


@pytest.fixture()
def web_page(web_server, browser):
    """Playwright page with auth credentials from config (if any).

    The web server reads lan_password from the user's config. When set,
    tests need to authenticate. This fixture handles both cases.
    """
    ctx_args = {}
    if _EFFECTIVE_PASSWORD:
        ctx_args["http_credentials"] = {
            "username": _EFFECTIVE_USERNAME,
            "password": _EFFECTIVE_PASSWORD,
        }
    context = browser.new_context(**ctx_args)
    p = context.new_page()
    yield p
    context.close()


@pytest.fixture()
def auth_web_server(_clean_ipc):
    """Start web server with HTTP Basic Auth enabled (username=study, password=test-pass-123)."""
    proc = _start_auth_web_server()
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


def _make_auth_header(username: str, password: str) -> str:
    """Build a Base64-encoded HTTP Basic Auth header value."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def _get_status(url: str, auth_header: str | None = None) -> int:
    """Make a GET request and return the HTTP status code."""
    req = urllib.request.Request(url)
    if auth_header:
        req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


# ---------------------------------------------------------------------------
# LAN auth tests
# ---------------------------------------------------------------------------


class TestLANAuth:
    """Verify HTTP Basic Auth protects the dashboard when a password is set."""

    def test_401_without_credentials(self, auth_web_server):
        """Request without an Authorization header returns 401."""
        status = _get_status(f"http://127.0.0.1:{AUTH_PORT}/")
        assert status == 401

    def test_www_authenticate_header_present(self, auth_web_server):
        """401 response includes the WWW-Authenticate: Basic header."""
        req = urllib.request.Request(f"http://127.0.0.1:{AUTH_PORT}/")
        try:
            urllib.request.urlopen(req, timeout=5)
            pytest.fail("Expected 401, got 200")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            assert "WWW-Authenticate" in exc.headers
            assert "Basic" in exc.headers["WWW-Authenticate"]

    def test_401_wrong_username(self, auth_web_server):
        """Wrong username with correct password returns 401."""
        header = _make_auth_header("wrong-user", AUTH_PASSWORD)
        status = _get_status(f"http://127.0.0.1:{AUTH_PORT}/", auth_header=header)
        assert status == 401

    def test_401_wrong_password(self, auth_web_server):
        """Correct username with wrong password returns 401."""
        header = _make_auth_header(AUTH_USERNAME, "wrong-password")  # pragma: allowlist secret
        status = _get_status(f"http://127.0.0.1:{AUTH_PORT}/", auth_header=header)
        assert status == 401

    def test_200_correct_credentials(self, auth_web_server):
        """Correct username and password returns 200."""
        header = _make_auth_header(AUTH_USERNAME, AUTH_PASSWORD)
        status = _get_status(f"http://127.0.0.1:{AUTH_PORT}/", auth_header=header)
        assert status == 200

    def test_sidebar_loads_after_auth(self, auth_web_server, browser):
        """Playwright authenticates via http_credentials and sidebar tabs render."""
        context = browser.new_context(
            http_credentials={"username": AUTH_USERNAME, "password": AUTH_PASSWORD}
        )
        page = context.new_page()
        try:
            page.goto(f"http://127.0.0.1:{AUTH_PORT}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(1500)

            tabs = page.locator(".sidebar-btn")
            assert tabs.count() == 4

            labels = [tabs.nth(i).text_content().strip() for i in range(4)]
            assert "Flashcards" in labels
            assert "Quizzes" in labels
            assert "Body Double" in labels
            assert "Study Session" in labels
        finally:
            context.close()


# ---------------------------------------------------------------------------
# Sidebar navigation tests
# ---------------------------------------------------------------------------


class TestSidebarNavigation:
    """Verify sidebar tabs switch between content panels."""

    def test_default_view_is_flashcards(self, web_page):
        """Page loads with the Flashcards tab active."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        # Flashcards tab should have active class
        fc_btn = web_page.locator(".sidebar-btn", has_text="Flashcards")
        assert "active" in fc_btn.get_attribute("class")

    def test_click_quizzes_tab(self, web_page):
        """Clicking Quizzes tab activates it and shows quiz content."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        quiz_btn = web_page.locator(".sidebar-btn", has_text="Quizzes")
        quiz_btn.click()
        web_page.wait_for_timeout(500)

        assert "active" in quiz_btn.get_attribute("class")
        # Flashcards tab should no longer be active
        fc_btn = web_page.locator(".sidebar-btn", has_text="Flashcards")
        assert "active" not in fc_btn.get_attribute("class")

    def test_click_body_double_tab(self, web_page):
        """Clicking Body Double tab shows the timer + terminal layout."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        bd_btn = web_page.locator(".sidebar-btn", has_text="Body Double")
        bd_btn.click()
        web_page.wait_for_timeout(500)

        assert "active" in bd_btn.get_attribute("class")

        # Body double dashboard should be visible
        bd_header = web_page.locator(".body-double-header h2")
        assert bd_header.is_visible()
        assert "Body Double" in bd_header.text_content()

    def test_click_study_session_tab(self, web_page):
        """Clicking Study Session tab shows the session dashboard."""
        _write_state(
            {
                "study_session_id": "test-sidebar",
                "topic": "Sidebar Test",
                "energy": 7,
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        ss_btn = web_page.locator(".sidebar-btn", has_text="Study Session")
        ss_btn.click()
        web_page.wait_for_timeout(1000)

        assert "active" in ss_btn.get_attribute("class")

        # Session timer should be visible
        timer = web_page.locator(".session-timer")
        assert timer.is_visible()

        # Topic should appear in session meta
        meta = web_page.locator(".meta-topic")
        assert "Sidebar Test" in meta.text_content()

    def test_hash_routing_direct_navigation(self, web_page):
        """Navigating directly to a hash activates the correct tab."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#body-double")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        bd_btn = web_page.locator(".sidebar-btn", has_text="Body Double")
        assert "active" in bd_btn.get_attribute("class")

        bd_header = web_page.locator(".body-double-header h2")
        assert bd_header.is_visible()

    def test_session_route_hash_routing(self, web_page):
        """The /session route works with hash routing."""
        _write_state(
            {
                "study_session_id": "test-route",
                "topic": "Route Test",
                "energy": 5,
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/session#study-session")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        ss_btn = web_page.locator(".sidebar-btn", has_text="Study Session")
        assert "active" in ss_btn.get_attribute("class")

    def test_all_four_tabs_exist(self, web_page):
        """All four sidebar tabs are rendered."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")

        tabs = web_page.locator(".sidebar-btn")
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

    def test_course_grid_loads(self, web_page):
        """Flashcards view renders the Alpine course grid (or empty state)."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(2000)

        # With no review dirs configured, the "No courses found" message shows
        # The review-content div should be visible in the flashcards panel
        content = web_page.locator(".review-content").first
        assert content.is_visible()


class TestStudySessionPanel:
    """Verify the Study Session panel shows live session data."""

    def test_timer_shows_energy(self, web_page):
        """Session timer displays the energy level from state."""
        _write_state(
            {
                "study_session_id": "test-energy",
                "topic": "Energy Check",
                "energy": 8,
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1500)

        energy = web_page.locator(".meta-energy")
        assert "8/10" in energy.text_content()

    def test_counter_bar_visible(self, web_page):
        """Counter bar shows WINS/PARKED/REVIEW labels."""
        _write_state(
            {
                "study_session_id": "test-counters",
                "topic": "Counter Test",
                "energy": 5,
            }
        )

        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        wins = web_page.locator("#counter-wins")
        assert "WINS" in wins.text_content()


class TestBodyDoublePanel:
    """Verify the Body Double panel has timer controls."""

    def test_pomodoro_button_exists(self, web_page):
        """Body Double view has a Start Pomodoro button."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#body-double")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        btn = web_page.locator(".body-double-controls .toggle-btn")
        assert btn.is_visible()
        assert "Pomodoro" in btn.text_content()


class TestHeaderControls:
    """Verify header controls work with Alpine stores."""

    def test_theme_toggle(self, web_page):
        """Clicking theme toggle adds/removes light class."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        body_classes = web_page.locator("body").get_attribute("class") or ""
        was_light = "light" in body_classes

        # Click theme toggle (the sun icon button)
        theme_btn = web_page.locator("button[title='Toggle light/dark theme']")
        theme_btn.click()
        web_page.wait_for_timeout(300)

        body_classes = web_page.locator("body").get_attribute("class") or ""
        if was_light:
            assert "light" not in body_classes
        else:
            assert "light" in body_classes

    def test_dyslexic_toggle(self, web_page):
        """Clicking dyslexic toggle adds/removes dyslexic class."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        web_page.wait_for_load_state("load")
        web_page.wait_for_timeout(1000)

        body_classes = web_page.locator("body").get_attribute("class") or ""
        was_dyslexic = "dyslexic" in body_classes

        dys_btn = web_page.locator("button[title='Toggle OpenDyslexic font']")
        dys_btn.click()
        web_page.wait_for_timeout(300)

        body_classes = web_page.locator("body").get_attribute("class") or ""
        if was_dyslexic:
            assert "dyslexic" not in body_classes
        else:
            assert "dyslexic" in body_classes
