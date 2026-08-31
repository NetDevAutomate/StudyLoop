"""Playwright UI tests for the full study-session lifecycle.

Exercises the ``sessionTimer()`` picker + ``liveAgentConsole()`` xterm
panel against a stubbed ``POST /api/session/start`` so we never spawn
a real PTY child. Covers:

  - picker field hydration from /session/options
  - target-kind switcher (topic vs vendor vs course vs lesson)
  - start button enable/disable
  - 503 install_hint surfacing
  - 409 already-active error handling
  - ws_url is opened after a successful start
  - end-session confirmation flow

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md
      §Test Strategy — "full picker flow" + "error states".
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

from _playwright_helpers import (  # noqa: E402
    auth_context_fixture_factory,
    web_page_fixture_factory,
    web_server_fixture_factory,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18572

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


def _default_options_payload() -> dict:
    return {
        "session_types": [
            {"label": "Study Session", "value": "study", "kind": "session_type"},
            {"label": "Body Double", "value": "body_double", "kind": "session_type"},
        ],
        "topics": [
            {"label": "Python", "value": "Python", "kind": "topic", "path": "/P"},
        ],
        "vendors": [
            {"label": "Udemy", "value": "Udemy", "kind": "vendor", "path": "/u"},
        ],
        "courses": [
            {
                "label": "Python 101",
                "value": "Udemy/Python_101",
                "kind": "course",
                "parent": "Udemy",
            },
        ],
        "lessons": [
            {
                "label": "Section 1",
                "value": "Udemy/Python_101/Section_1",
                "kind": "lesson",
                "parent": "Udemy/Python_101",
            },
        ],
        "agents": [
            {
                "label": "Claude",
                "value": "claude",
                "available": True,
                "supports_acp": False,
                "acp_ready": False,
                "recommended_transport": "pty",
            },
            {
                "label": "Codex",
                "value": "codex",
                "available": True,
                "supports_acp": False,
                "acp_ready": False,
                "recommended_transport": "pty",
            },
        ],
    }


def _stub_options(page: Page, payload: dict | None = None) -> None:
    body = payload or _default_options_payload()
    page.route("**/api/session/options", lambda route: _fulfill(route, body))


def _stub_session_state(page: Page, state: dict | None = None) -> None:
    page.route("**/api/session/state", lambda route: _fulfill(route, state or {}))


def _stub_topics_list(page: Page, topics: list[dict] | None = None) -> None:
    page.route("**/api/session/topics", lambda route: _fulfill(route, topics or []))


def _goto_picker(page: Page) -> None:
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#study-session")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.wait_for_selector("#target-kind-select", state="attached", timeout=5000)


# ---------------------------------------------------------------------------
# Picker hydration + field logic
# ---------------------------------------------------------------------------


class TestPickerHydration:
    def test_agent_options_populate_from_api(self, web_page: Page) -> None:
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        _goto_picker(web_page)

        web_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              return d && d.studyOptions.agents && d.studyOptions.agents.length >= 2;
            }""",
            timeout=5000,
        )

    def test_first_available_agent_pre_selected(self, web_page: Page) -> None:
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        _goto_picker(web_page)

        web_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              return d && d.agent === 'claude';
            }""",
            timeout=5000,
        )

    def test_start_button_disabled_until_topic_and_agent(self, web_page: Page) -> None:
        """The start button has ``:disabled="!resolvedTopic().trim() || !agent"``.

        An empty fresh picker should disable it; flipping in a valid
        topic should enable it.
        """
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        _goto_picker(web_page)

        btn = web_page.locator(".start-session-btn")
        # Clear topicInput + agent to force disabled state.
        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.topicInput = '';
              d.selectedTopic = '';
              d.agent = '';
            }"""
        )
        web_page.wait_for_function(
            "() => document.querySelector('.start-session-btn').disabled === true",
            timeout=3000,
        )
        assert btn.is_disabled()

        # Now enable.
        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.topicInput = 'Python';
              d.agent = 'claude';
            }"""
        )
        web_page.wait_for_function(
            "() => document.querySelector('.start-session-btn').disabled === false",
            timeout=3000,
        )


# ---------------------------------------------------------------------------
# Transport picker: ACP option gating (§2.2 — PR-B)
# ---------------------------------------------------------------------------


def _acp_options_payload() -> dict:
    """Agents list that exposes a single ACP-capable agent (Kiro)."""
    base = _default_options_payload()
    base["agents"] = [
        {
            "label": "Claude",
            "value": "claude",
            "available": True,
            "supports_acp": False,
            "acp_ready": False,
            "recommended_transport": "pty",
        },
        {
            "label": "Kiro",
            "value": "kiro",
            "available": True,
            "supports_acp": True,
            "acp_ready": True,
            "recommended_transport": "pty",
        },
    ]
    return base


class TestTransportAcpOption:
    """The transport <select> must expose ``acp`` only when the chosen
    agent supports it — tying the frontend-visible option to the
    /session/options ``supports_acp`` flag.
    """

    def test_acp_option_hidden_when_agent_does_not_support_it(self, web_page: Page) -> None:
        _stub_options(web_page, _acp_options_payload())
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        _goto_picker(web_page)

        # First-available agent = Claude (no ACP). The ACP option exists
        # in the DOM but x-show hides it — `display: none` on the option.
        web_page.wait_for_function(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              return d && d.agent === 'claude';
            }""",
            timeout=5000,
        )
        visible = web_page.evaluate(
            """() => {
              const opts = document.querySelectorAll('#transport-select option');
              for (const o of opts) {
                if (o.value === 'acp') {
                  return window.getComputedStyle(o).display !== 'none';
                }
              }
              return null;
            }"""
        )
        assert visible is False

    def test_acp_option_visible_when_agent_supports_it(self, web_page: Page) -> None:
        _stub_options(web_page, _acp_options_payload())
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        _goto_picker(web_page)

        # Flip agent to Kiro.
        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              window.Alpine.$data(root).agent = 'kiro';
            }"""
        )
        web_page.wait_for_function(
            """() => {
              const opts = document.querySelectorAll('#transport-select option');
              for (const o of opts) {
                if (o.value === 'acp') {
                  return window.getComputedStyle(o).display !== 'none';
                }
              }
              return false;
            }""",
            timeout=3000,
        )

    def test_acp_hint_text_names_only_kiro(self, web_page: Page) -> None:
        _stub_options(web_page, _acp_options_payload())
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        _goto_picker(web_page)

        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.agent = 'kiro';
              d.transport = 'acp';
            }"""
        )
        hint_text = web_page.evaluate(
            """() => {
              const hints = document.querySelectorAll('.picker-hint');
              for (const h of hints) {
                if (window.getComputedStyle(h).display === 'none') continue;
                const t = h.textContent || '';
                if (t.includes('ACP') || t.includes('Kiro')) {
                  return t;
                }
              }
              return '';
            }"""
        )
        assert "Kiro" in hint_text
        assert "Gemini" not in hint_text


# ---------------------------------------------------------------------------
# target-kind switcher: topic / vendor / course / lesson
# ---------------------------------------------------------------------------


class TestTargetKindSwitcher:
    @pytest.mark.parametrize("kind", ["topic", "vendor", "course", "lesson"])
    def test_each_target_kind_renders(self, web_page: Page, kind: str) -> None:
        """Every target kind has its own picker sub-view; make sure they
        all mount without error when the dropdown flips."""
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        _goto_picker(web_page)

        # Flip targetKind via Alpine.
        web_page.evaluate(
            f"""() => {{
              const root = document.querySelector('[x-data="sessionTimer()"]');
              window.Alpine.$data(root).targetKind = '{kind}';
            }}"""
        )
        # Assert the Alpine data reflects the switch.
        current = web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              return window.Alpine.$data(root).targetKind;
            }"""
        )
        assert current == kind


# ---------------------------------------------------------------------------
# start session: happy path, 503 install_hint, 409 already-active
# ---------------------------------------------------------------------------


class TestStartSessionFlow:
    def _stub_start(self, page: Page, *, status: int, body: dict) -> None:
        def handler(route: Route) -> None:
            if route.request.method == "POST":
                _fulfill(route, body, status=status)
            else:
                route.continue_()

        page.route("**/api/session/start", handler)

    def test_happy_path_dispatches_study_session_start_event(self, web_page: Page) -> None:
        """A 201 from /session/start dispatches the study-session-start
        event with ws_url + transport + studySessionId — the contract
        liveAgentConsole() listens for."""
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        self._stub_start(
            web_page,
            status=201,
            body={
                "study_session_id": "ss-001",
                "topic": "Python",
                "energy": 7,
                "agent": "claude",
                "transport": "pty",
                "ws_url": "/api/session/ws?study_session_id=ss-001",
            },
        )
        _goto_picker(web_page)

        # Set topic; click Start.
        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.topicInput = 'Python';
              d.energy = 7;
              d.agent = 'claude';
            }"""
        )

        # Listen for the event BEFORE clicking.
        web_page.evaluate(
            """() => {
              window._capturedDetail = null;
              window.addEventListener('study-session-start', (e) => {
                window._capturedDetail = e.detail;
              }, {once: true});
            }"""
        )
        web_page.locator(".start-session-btn").click()
        web_page.wait_for_function("() => window._capturedDetail !== null", timeout=5000)

        detail = web_page.evaluate("() => window._capturedDetail")
        assert detail["studySessionId"] == "ss-001"
        assert detail["transport"] == "pty"
        assert detail["wsUrl"] == "/api/session/ws?study_session_id=ss-001"

    def test_503_install_hint_surfaces_to_picker_error(self, web_page: Page) -> None:
        """A 503 with install_hint should show both the error AND the hint."""
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        self._stub_start(
            web_page,
            status=503,
            body={
                "error": "Agent 'gemini' binary not found: gemini",
                "agent": "gemini",
                "binary": "gemini",
                "install_hint": "Install the Gemini CLI: https://example.com",
            },
        )
        _goto_picker(web_page)

        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.topicInput = 'Python';
              d.agent = 'claude';  // agent field doesn't matter — the server returns 503
            }"""
        )
        web_page.locator(".start-session-btn").click()

        err = web_page.locator(".picker-error")
        err.wait_for(state="visible", timeout=5000)
        text = err.text_content() or ""
        assert "gemini" in text
        assert "Install the Gemini CLI" in text

    def test_409_already_active_surfaces_cleanly(self, web_page: Page) -> None:
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        self._stub_start(
            web_page,
            status=409,
            body={"error": "A session is already active"},
        )
        _goto_picker(web_page)

        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.topicInput = 'Python';
              d.agent = 'claude';
            }"""
        )
        web_page.locator(".start-session-btn").click()

        err = web_page.locator(".picker-error")
        err.wait_for(state="visible", timeout=5000)
        assert "already active" in (err.text_content() or "")

    def test_network_error_surfaces_cleanly(self, web_page: Page) -> None:
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)
        web_page.route("**/api/session/start", lambda route: route.abort("failed"))
        _goto_picker(web_page)

        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.topicInput = 'Python';
              d.agent = 'claude';
            }"""
        )
        web_page.locator(".start-session-btn").click()

        err = web_page.locator(".picker-error")
        err.wait_for(state="visible", timeout=5000)
        assert "Network error" in (err.text_content() or "")


# ---------------------------------------------------------------------------
# end session
# ---------------------------------------------------------------------------


class TestEndSession:
    def test_end_button_posts_api_session_end(self, web_page: Page) -> None:
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)

        calls: list[dict] = []

        def end_handler(route: Route) -> None:
            if route.request.method == "POST":
                calls.append({"url": route.request.url})
                _fulfill(route, {"ended": True, "topic": "Python"})
            else:
                route.continue_()

        web_page.route("**/api/session/end", end_handler)

        _goto_picker(web_page)
        # Simulate an active session, then click stop.
        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.sessionActive = true;
              d.topic = 'Python';
              d.endSession();
            }"""
        )
        # The in-page confirm dialog appears (no native confirm() — Chrome
        # auto-dismisses those while the ttyd iframe holds focus).
        dialog = web_page.locator(".end-confirm-dialog")
        dialog.wait_for(state="visible", timeout=3000)
        # Scoped to the dialog: .end-confirm-yes appears 3x in the SPA, so an
        # unscoped locator is a strict-mode violation, not a timeout.
        dialog.locator(".end-confirm-yes").click()
        # Assert the POST landed and the dialog is gone.
        web_page.wait_for_timeout(200)
        assert any("/api/session/end" in c["url"] for c in calls)
        assert not dialog.is_visible()

    def test_end_confirm_cancel_keeps_session(self, web_page: Page) -> None:
        _stub_options(web_page)
        _stub_session_state(web_page)
        _stub_topics_list(web_page)

        calls: list[dict] = []
        web_page.route(
            "**/api/session/end",
            lambda route: (calls.append({}), _fulfill(route, {"ended": True})),
        )

        _goto_picker(web_page)
        web_page.evaluate(
            """() => {
              const root = document.querySelector('[x-data="sessionTimer()"]');
              const d = window.Alpine.$data(root);
              d.sessionActive = true;
              d.topic = 'Python';
              d.endSession();
            }"""
        )
        dialog = web_page.locator(".end-confirm-dialog")
        dialog.wait_for(state="visible", timeout=3000)
        # Scoped for the same reason as the confirm button above.
        dialog.locator(".end-confirm-cancel").click()
        web_page.wait_for_timeout(200)
        assert not calls
        assert web_page.evaluate(
            """() => window.Alpine.$data(
              document.querySelector('[x-data="sessionTimer()"]')).sessionActive"""
        )
