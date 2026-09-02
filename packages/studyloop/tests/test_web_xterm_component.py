"""Playwright smoke tests for the xterm.js agent terminal component (§1.7).

Exercises the Alpine ``liveAgentConsole()`` wiring end-to-end against a
live studyloop web server. We do NOT spawn a real PTY child — the test
uses Playwright's route interception to stub ``POST /api/session/start``
with a synthetic response and verifies the component's reaction:

- picker defaults to transport=pty
- start dispatches the correct POST payload
- xterm.js mount node appears in the DOM after session start
- WebSocket connection attempt uses the returned ``ws_url``

Real agent streams are out of scope; they need a real PTY, which the
``test_pty_transport.py`` unit tests cover at the transport layer.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md §1.7
"""

from __future__ import annotations

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


CONFIG_DIR = Path.home() / ".config" / "studyloop"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"

WEB_PORT = 18568


# ---------------------------------------------------------------------------
# Fixtures (adapted from test_web_terminal.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_ipc():
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
        f.unlink(missing_ok=True)
    yield
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
        f.unlink(missing_ok=True)


def _start_web_server(port: int = WEB_PORT) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "studyloop.cli", "web", "--port", str(port)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return proc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return proc
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    proc.kill()
    raise RuntimeError(f"Web server failed to start on port {port}")


def _get_effective_credentials() -> tuple[str, str]:
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        return (settings.lan_username or "study", settings.lan_password or "")
    except Exception:
        return ("study", "")


_USER, _PASS = _get_effective_credentials()


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
def _auth_context(browser):
    ctx_args = {}
    if _PASS:
        ctx_args["http_credentials"] = {"username": _USER, "password": _PASS}
    context = browser.new_context(**ctx_args)
    yield context
    context.close()


@pytest.fixture()
def web_page(web_server, _auth_context):
    page = _auth_context.new_page()
    yield page


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestXtermPickerDefaults:
    def test_transport_picker_defaults_to_pty(self, web_page) -> None:
        """The picker must default to PTY — since ADR-0005 retired the ttyd
        browser surface, PTY and ACP are the only two transports offered."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_selector("#transport-select", state="attached", timeout=5000)
        selected = web_page.eval_on_selector("#transport-select", "(el) => el.value")
        assert selected == "pty"

    def test_legacy_ttyd_option_is_gone(self, web_page) -> None:
        """The ttyd BROWSER surface was retired in ADR-0005, so the dropdown
        must no longer offer it.

        The server-side transport axis is gone too as of ttyd retirement
        stage 3: ``POST /api/session/start`` now structurally rejects
        ``transport=ttyd`` with 422 (see test_web_session.py and
        test_web_session_start_pty.py), so the UI and API surfaces agree.
        If this assertion ever fails because ``ttyd`` came back into the
        dropdown, check that a renderer came back with it; a selectable
        transport with no renderer is the silent-blank defect ADR-0005
        exists to prevent.
        """
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_selector("#transport-select", state="attached", timeout=5000)
        values = web_page.eval_on_selector_all(
            "#transport-select option", "(opts) => opts.map(o => o.value)"
        )
        assert "pty" in values
        assert "ttyd" not in values
        # PR-B re-enabled the ACP option gated by selectedAgentSupportsAcp();
        # it's present in the DOM but hidden via x-show when no ACP-capable
        # agent is selected. See test_web_session_lifecycle.py::TestTransportAcpOption
        # for the visibility coverage.
        assert "acp" in values


class TestCascadePicker:
    """Course → lesson cascade (§1.8).

    The /session/options endpoint already returns a parent-linked
    vendor/course/lesson hierarchy. These tests lock the Alpine
    cascade behaviour so future picker edits can't silently break it.
    """

    def test_course_dropdown_filters_by_selected_vendor(self, web_page) -> None:
        """Pick a vendor → course dropdown shows only that vendor's courses."""
        # Stub /session/options with a known hierarchy.
        web_page.route(
            "**/api/session/options",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"session_types":[],'
                    '"topics":[],'
                    '"vendors":['
                    '{"label":"Udemy","value":"Udemy","kind":"vendor","path":"/u"},'
                    '{"label":"Coursera","value":"Coursera","kind":"vendor","path":"/c"}'
                    "],"
                    '"courses":['
                    '{"label":"Python","value":"Udemy/Python","kind":"course","parent":"Udemy"},'
                    '{"label":"SQL","value":"Coursera/SQL","kind":"course","parent":"Coursera"}'
                    "],"
                    '"lessons":['
                    '{"label":"S01","value":"Udemy/Python/S01","kind":"lesson","parent":"Udemy/Python"}'
                    "],"
                    '"agents":[{"label":"Claude","value":"claude","available":true}]'
                    "}"
                ),
            ),
        )
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_selector("#vendor-select option", state="attached", timeout=5000)

        # Switch targetKind to 'vendor' so vendor/course picker fields are visible.
        web_page.eval_on_selector(
            "#target-kind-select",
            "(el) => { el.value = 'vendor'; el.dispatchEvent(new Event('change')); }",
        )
        # Select Udemy.
        web_page.eval_on_selector(
            "#vendor-select",
            "(el) => { el.value = 'Udemy'; el.dispatchEvent(new Event('change')); }",
        )
        # Poll until the course <select> has been filtered to exactly "Python".
        web_page.wait_for_function(
            """() => {
              const el = document.querySelector('#course-select');
              if (!el) return false;
              const values = [...el.options].map(o => o.value).filter(v => v);
              return values.length === 1 && values[0] === 'Udemy/Python';
            }""",
            timeout=5000,
        )

    def test_resolved_topic_uses_joined_cascade_path(self, web_page) -> None:
        """resolvedTopic() returns the full vendor/course/lesson path,
        not just the leaf label (plan §1.8: 'f"{vendor}/{course}/{lesson}"')."""
        web_page.route(
            "**/api/session/options",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"session_types":[],'
                    '"topics":[],'
                    '"vendors":[{"label":"Udemy","value":"Udemy","kind":"vendor","path":"/u"}],'
                    '"courses":[{"label":"Python","value":"Udemy/Python","kind":"course","parent":"Udemy"}],'
                    '"lessons":[{"label":"S01","value":"Udemy/Python/S01","kind":"lesson","parent":"Udemy/Python"}],'
                    '"agents":[{"label":"Claude","value":"claude","available":true}]}'
                ),
            ),
        )
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_selector("#lesson-select", state="attached", timeout=5000)

        # Drive the cascade through the underlying Alpine data so we
        # don't depend on x-show timing for each nested field.
        topic = web_page.evaluate(
            """
            (() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.targetKind = 'lesson';
              d.selectedVendor = 'Udemy';
              d.selectedCourse = 'Udemy/Python';
              d.selectedLesson = 'Udemy/Python/S01';
              return d.resolvedTopic();
            })()
            """
        )
        assert topic == "Udemy/Python/S01"


class TestXtermMount:
    def test_xterm_bundles_expose_globals(self, web_page) -> None:
        """xterm / fit / webgl / clipboard addons register window globals."""
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        # defer scripts run after DOMContentLoaded — wait for it.
        web_page.wait_for_load_state("domcontentloaded")
        # Poll until vendor globals attach (or timeout).
        web_page.wait_for_function(
            "() => typeof window.Terminal === 'function' "
            "&& typeof window.FitAddon === 'object' "
            "&& typeof window.WebglAddon === 'object' "
            "&& typeof window.ClipboardAddon === 'object'",
            timeout=5000,
        )

    def test_xterm_mount_appears_after_simulated_pty_start(self, web_page) -> None:
        """Fire the ``study-session-start`` event with a pty detail and
        confirm the xterm mount node becomes visible.

        Uses a custom event directly rather than going through POST
        /api/session/start because we don't want to spawn a real PTY
        child; the route-level path is covered by the §1.5b unit
        tests.
        """
        web_page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
        web_page.wait_for_load_state("domcontentloaded")
        web_page.wait_for_function("() => typeof window.Terminal === 'function'", timeout=5000)

        # The xterm mount lives inside the "active session" branch
        # (sessionActive === true). Flip that + fire the event so the
        # Alpine reactivity actually renders the terminal container.
        web_page.evaluate(
            """
            /* Reach the sessionTimer() root — it's the @data of the
               study-session view. Find by the x-init attribute. */
            const root = document.querySelector(
              '[x-data="sessionTimer()"]'
            );
            if (root && window.Alpine) {
              const data = window.Alpine.$data(root);
              data.sessionActive = true;
              data.topic = 'Smoke';
            }
            window.dispatchEvent(new CustomEvent('study-session-start', {
              detail: {
                topic: 'Smoke',
                energy: 5,
                sessionType: 'study',
                targetKind: 'topic',
                agent: 'claude',
                resolvedAgent: 'claude',
                studySessionId: 'smoke-1',
                transport: 'pty',
                wsUrl: '/api/session/ws?study_session_id=smoke-1',
              }
            }))
            """
        )

        # The .xterm-mount element lives under the xterm-panel (x-show=xterm).
        # Alpine uses x-cloak + x-show → the mount must become visible, not
        # just present, so the webGL/fit addons have a real container.
        mount = web_page.wait_for_selector(".xterm-mount", state="visible", timeout=5000)
        assert mount is not None

        # xterm.js lays down a .xterm container inside our mount node
        # once Terminal.open() runs.
        web_page.wait_for_selector(".xterm-mount .xterm", state="attached", timeout=5000)
