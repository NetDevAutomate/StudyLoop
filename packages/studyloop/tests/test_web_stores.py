"""Playwright UI tests for the Alpine ``pomodoro`` and ``settings`` stores.

These stores are user-facing preferences — theme, voice, dyslexic-friendly
font, pomodoro timer — and sit at the root of the app so a regression
ripples everywhere. The test covers the store methods directly (no
reliance on timer-driven real time).

Plan: private-docs/2026-05-09-refactor-agent-session-transport-plan.md
      §Test Strategy — "theme/voice toggles", "pomodoro timer controls".
"""

from __future__ import annotations

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
    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18573

web_server = web_server_fixture_factory(WEB_PORT)
auth_context = auth_context_fixture_factory()
web_page = web_page_fixture_factory("web_server", "auth_context")


def _goto(page: Page) -> None:
    page.goto(f"http://127.0.0.1:{WEB_PORT}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)


# ---------------------------------------------------------------------------
# Settings store — theme, dyslexic, voice
# ---------------------------------------------------------------------------


class TestSettingsStore:
    def test_toggle_theme_flips_body_class(self, web_page: Page) -> None:
        _goto(web_page)
        # Start dark (the default). toggleTheme → light.
        initial = web_page.evaluate("() => document.body.classList.contains('light')")
        web_page.evaluate("() => window.Alpine.store('settings').toggleTheme()")
        flipped = web_page.evaluate("() => document.body.classList.contains('light')")
        assert flipped != initial

        # Toggle back.
        web_page.evaluate("() => window.Alpine.store('settings').toggleTheme()")
        back = web_page.evaluate("() => document.body.classList.contains('light')")
        assert back == initial

    def test_toggle_theme_persists_to_localstorage(self, web_page: Page) -> None:
        _goto(web_page)
        web_page.evaluate(
            """() => {
              localStorage.removeItem('theme');
              window.Alpine.store('settings').toggleTheme();
            }"""
        )
        stored = web_page.evaluate("() => localStorage.getItem('theme')")
        assert stored in {"light", "dark"}

    def test_set_font_opendyslexic_applies_to_body(self, web_page: Page) -> None:
        """OpenDyslexic is one option in the single font mechanism, not a toggle.

        It used to be a separate `body.dyslexic` class that set font-family
        directly, competing with the `body[data-font]` variable the picker drives
        — two systems with different line metrics, which is what made switching
        fonts leave the sidebar overlapping. Asserting a *flip* here would be
        wrong now: setFont is idempotent, so it is the resulting state that
        matters, not that it changed.
        """
        _goto(web_page)
        web_page.evaluate("() => window.Alpine.store('settings').setFont('opendyslexic')")
        assert web_page.evaluate("() => document.body.getAttribute('data-font')") == "opendyslexic"
        web_page.evaluate("() => window.Alpine.store('settings').setFont('inter')")
        assert web_page.evaluate("() => document.body.getAttribute('data-font')") != "opendyslexic"

    def test_toggle_voice_updates_store(self, web_page: Page) -> None:
        _goto(web_page)
        before = web_page.evaluate("() => window.Alpine.store('settings').voiceOn")
        web_page.evaluate("() => window.Alpine.store('settings').toggleVoice()")
        after = web_page.evaluate("() => window.Alpine.store('settings').voiceOn")
        assert before != after

    def test_stop_speaking_is_idempotent(self, web_page: Page) -> None:
        """stopSpeaking() must not crash when no utterance is in flight."""
        _goto(web_page)
        err = web_page.evaluate(
            """() => {
              try { window.Alpine.store('settings').stopSpeaking(); return null; }
              catch (e) { return String(e); }
            }"""
        )
        assert err is None


class TestSettingsToggleButtons:
    def test_voice_button_flips_store(self, web_page: Page) -> None:
        _goto(web_page)
        before = web_page.evaluate("() => window.Alpine.store('settings').voiceOn")
        # Voice button has title="Toggle voice...".
        web_page.click('header .toggle-btn[title*="Toggle voice"]')
        after = web_page.evaluate("() => window.Alpine.store('settings').voiceOn")
        assert before != after


# ---------------------------------------------------------------------------
# Pomodoro store — timer + control surface
# ---------------------------------------------------------------------------


class TestPomodoroStore:
    def test_config_loads_with_defaults(self, web_page: Page) -> None:
        _goto(web_page)
        cfg = web_page.evaluate(
            """() => {
              const p = window.Alpine.store('pomodoro');
              return {
                focus: p.focusMin,
                short: p.shortBreakMin,
                long: p.longBreakMin,
                cycles: p.cycles,
              };
            }"""
        )
        assert cfg["focus"] > 0
        assert cfg["short"] > 0
        assert cfg["long"] > cfg["short"]
        assert cfg["cycles"] >= 1

    def test_toggle_visible_flips_visibility(self, web_page: Page) -> None:
        _goto(web_page)
        before = web_page.evaluate("() => window.Alpine.store('pomodoro').visible")
        web_page.evaluate("() => window.Alpine.store('pomodoro').toggle()")
        after = web_page.evaluate("() => window.Alpine.store('pomodoro').visible")
        assert before != after

    def test_start_puts_store_into_running_state(self, web_page: Page) -> None:
        _goto(web_page)
        # Disable voice first so the start() call doesn't try to speak.
        web_page.evaluate(
            """() => {
              const s = window.Alpine.store('settings');
              if (s.voiceOn) s.toggleVoice();
              window.Alpine.store('pomodoro').start();
            }"""
        )
        state = web_page.evaluate(
            """() => {
              const p = window.Alpine.store('pomodoro');
              return {running: p.running, paused: p.paused, isBreak: p.isBreak};
            }"""
        )
        assert state == {"running": True, "paused": False, "isBreak": False}

        # Stop to avoid leaking timers into the next test.
        web_page.evaluate("() => window.Alpine.store('pomodoro').stop()")

    def test_toggle_pause_flips_paused(self, web_page: Page) -> None:
        _goto(web_page)
        web_page.evaluate(
            """() => {
              const s = window.Alpine.store('settings');
              if (s.voiceOn) s.toggleVoice();
              window.Alpine.store('pomodoro').start();
              window.Alpine.store('pomodoro').togglePause();
            }"""
        )
        paused = web_page.evaluate("() => window.Alpine.store('pomodoro').paused")
        assert paused is True

        web_page.evaluate("() => window.Alpine.store('pomodoro').stop()")

    def test_stop_clears_running_state(self, web_page: Page) -> None:
        _goto(web_page)
        web_page.evaluate(
            """() => {
              const s = window.Alpine.store('settings');
              if (s.voiceOn) s.toggleVoice();
              const p = window.Alpine.store('pomodoro');
              p.start();
              p.stop();
            }"""
        )
        state = web_page.evaluate(
            """() => {
              const p = window.Alpine.store('pomodoro');
              return {running: p.running, paused: p.paused, visible: p.visible};
            }"""
        )
        assert state == {"running": False, "paused": False, "visible": False}

    def test_save_durations_persists_and_recomputes(self, web_page: Page) -> None:
        _goto(web_page)
        web_page.evaluate(
            """() => {
              const p = window.Alpine.store('pomodoro');
              p.focusMin = 30;
              p.shortBreakMin = 7;
              p.longBreakMin = 20;
              p.cycles = 3;
              p.saveDurations();
            }"""
        )
        state = web_page.evaluate(
            """() => {
              const p = window.Alpine.store('pomodoro');
              return {STUDY: p.STUDY, BREAK: p.BREAK, LONG_BREAK: p.LONG_BREAK, CYCLES: p.CYCLES};
            }"""
        )
        assert state == {
            "STUDY": 30 * 60,
            "BREAK": 7 * 60,
            "LONG_BREAK": 20 * 60,
            "CYCLES": 3,
        }
        stored = web_page.evaluate(
            """() => ({
              focus: localStorage.getItem('pomoFocus'),
              short: localStorage.getItem('pomoShortBreak'),
              long: localStorage.getItem('pomoLongBreak'),
              cycles: localStorage.getItem('pomoCycles'),
            })"""
        )
        assert stored == {"focus": "30", "short": "7", "long": "20", "cycles": "3"}


class TestPomodoroButton:
    def test_header_pomodoro_button_toggles_visibility(self, web_page: Page) -> None:
        _goto(web_page)
        before = web_page.evaluate("() => window.Alpine.store('pomodoro').visible")
        web_page.click('header .toggle-btn[title*="Pomodoro"]')
        after = web_page.evaluate("() => window.Alpine.store('pomodoro').visible")
        assert before != after
