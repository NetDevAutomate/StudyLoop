"""Body Double as a workspace you can actually get out of.

Reported as *"a focus and note pane with the terminal underneath, with no
obvious way to stop/kill the focus/note pane"*. The screen reading was right and
the code reading was wrong, which is what made it a defect worth a suite:

* ``#bd-focus`` and ``#bd-capture`` have no visibility binding at all — they are
  permanent furniture, stacked ABOVE the terminal in one scrolling column, so
  they *look* like panes covering it with no dismiss control;
* the only control that stops a session was a bare ``■`` with no accessible
  name, inside a strip that scrolls off the moment you look at the terminal;
* ending a session left the Pomodoro counting down and the picker pre-filled
  with the activity that had just finished;
* a focus topic committed with ``studyloop focus set`` could not be removed from
  the web UI at all — ``POST /api/body-double/focus`` had zero callers.

The `#bd-transport-select` coverage lives here too: it was actuated by no test
anywhere, and its ``pty`` label is the one that lies under ``studyloop web
--dev`` (see ``TestDevEngineIsVisible``).

Every test runs against an isolated vault + config + session DB via
``e2e/_env.py``; nothing here reads or writes the developer's real
``~/.config/studyloop``.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_body_double_workspace.py -m e2e
"""

from __future__ import annotations

import contextlib
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

import pytest

pytest.importorskip("playwright")
pytest.importorskip("requests")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import ConsoleWatch, diag, goto_view, launch_env, shutdown  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]

PORT = 18631
DEV_PORT = 18632

# Each page fixture pairs its Page with a ConsoleWatch, and every test needs the
# watch again in its `except` block to attach console output to the failure
# artefact. Stashing it as `page._watch` is the obvious move and a typing error:
# Page has no such attribute, so pyright rejects every read of it. A side table
# keyed on the page keeps the pairing without lying about Playwright's API, and
# the weak keys mean a closed context's watch is collectable rather than pinned
# for the life of the module.
_WATCHES: WeakKeyDictionary[Page, ConsoleWatch] = WeakKeyDictionary()


def _watch_for(page: Page) -> ConsoleWatch:
    """The ConsoleWatch bound to this page by its fixture."""
    return _WATCHES[page]


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """Stock server (no --dev), with the deterministic harness agent available."""
    root = tmp_path_factory.mktemp("bd-workspace")
    e = launch_env(root, PORT, fake_agent=True)
    try:
        yield e
    finally:
        with contextlib.suppress(Exception):
            urllib.request.urlopen(
                urllib.request.Request(f"{e.base_url}/api/session/end", data=b"", method="POST"),
                timeout=10,
            )
        shutdown(e)


@pytest.fixture(scope="module")
def dev_env(tmp_path_factory):
    """The same server started with ``--dev`` (libghostty replaces xterm.js)."""
    root = tmp_path_factory.mktemp("bd-workspace-dev")
    e = launch_env(root, DEV_PORT, extra_args=["--dev"])
    try:
        yield e
    finally:
        shutdown(e)


@pytest.fixture()
def bd_page(browser: Browser, env):
    """A fresh context per test — localStorage carries the collapse state."""
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    _WATCHES[page] = ConsoleWatch(page)
    try:
        page.goto(f"{env.base_url}/")
        goto_view(page, "body-double")
        page.wait_for_selector("#bd-focus", state="visible", timeout=15_000)
        yield page
    finally:
        ctx.close()


def _post_focus(env, topics: list[str]) -> None:
    import requests

    response = requests.post(
        f"{env.base_url}/api/body-double/focus", json={"topics": topics}, timeout=15
    )
    assert response.status_code == 200, response.text


def _focus_payload(env) -> dict:
    import requests

    return requests.get(f"{env.base_url}/api/body-double/focus", timeout=15).json()


# ---------------------------------------------------------------------------
# The dismiss path — collapse, because nothing could reopen a closed pane
# ---------------------------------------------------------------------------


class TestPanesCanBeFoldedAway:
    def test_focus_pane_collapses_and_the_way_back_stays_on_screen(self, bd_page: Page) -> None:
        """Collapsing hides the body but never the toggle.

        A close button would be the wrong pattern here: this surface has no
        sidebar entry, no store flag and no other affordance that could bring a
        closed pane back, so "dismiss" would swap one dead end for another.
        """
        try:
            body = bd_page.locator("#bd-focus-body")
            toggle = bd_page.locator("#bd-focus-toggle")
            assert body.is_visible(), "the focus panel should start expanded"
            assert toggle.get_attribute("aria-expanded") == "true"

            toggle.click()
            bd_page.wait_for_selector("#bd-focus-body", state="hidden", timeout=5_000)
            assert toggle.is_visible(), "collapsing must not hide its own toggle"
            assert toggle.get_attribute("aria-expanded") == "false"
            # The header row survives, so the state is legible while folded.
            assert bd_page.locator("#bd-focus-count").is_visible()

            toggle.click()
            bd_page.wait_for_selector("#bd-focus-body", state="visible", timeout=5_000)
            assert toggle.get_attribute("aria-expanded") == "true"
            _watch_for(bd_page).assert_clean("collapsing the focus panel")
        except Exception:
            diag(bd_page, "bd-focus-collapse", _watch_for(bd_page))
            raise

    def test_capture_pane_collapses_without_losing_the_draft(self, bd_page: Page) -> None:
        """A half-written note survives the fold — collapse is not discard."""
        try:
            bd_page.locator("#bd-note-title").fill("Half-written thought")
            bd_page.locator("#bd-note-body").fill("Only the first half of this.")

            bd_page.locator("#bd-capture-toggle").click()
            bd_page.wait_for_selector("#bd-capture-body", state="hidden", timeout=5_000)
            assert bd_page.locator("#bd-capture-toggle").is_visible()

            bd_page.locator("#bd-capture-toggle").click()
            bd_page.wait_for_selector("#bd-capture-body", state="visible", timeout=5_000)
            assert bd_page.locator("#bd-note-title").input_value() == "Half-written thought"
            assert bd_page.locator("#bd-note-body").input_value() == "Only the first half of this."
        except Exception:
            diag(bd_page, "bd-capture-collapse", _watch_for(bd_page))
            raise

    def test_choosing_a_tab_reopens_a_collapsed_capture_pane(self, bd_page: Page) -> None:
        """A tab that highlights but shows nothing reads as broken."""
        try:
            bd_page.locator("#bd-capture-toggle").click()
            bd_page.wait_for_selector("#bd-capture-body", state="hidden", timeout=5_000)

            bd_page.locator("#bd-tab-park").click()
            bd_page.wait_for_selector("#bd-park-form", state="visible", timeout=5_000)
            assert bd_page.locator("#bd-capture-toggle").get_attribute("aria-expanded") == "true"
        except Exception:
            diag(bd_page, "bd-capture-tab-reopen", _watch_for(bd_page))
            raise

    def test_collapsed_state_survives_a_reload(self, bd_page: Page) -> None:
        """ "Get this out of my way" that undoes itself every reload is not an answer."""
        try:
            bd_page.locator("#bd-focus-toggle").click()
            bd_page.locator("#bd-capture-toggle").click()
            bd_page.wait_for_selector("#bd-focus-body", state="hidden", timeout=5_000)
            bd_page.wait_for_selector("#bd-capture-body", state="hidden", timeout=5_000)

            bd_page.reload()
            goto_view(bd_page, "body-double")
            bd_page.wait_for_selector("#bd-focus", state="visible", timeout=15_000)
            bd_page.wait_for_selector("#bd-focus-body", state="hidden", timeout=10_000)
            bd_page.wait_for_selector("#bd-capture-body", state="hidden", timeout=10_000)
        except Exception:
            diag(bd_page, "bd-collapse-persist", _watch_for(bd_page))
            raise


# ---------------------------------------------------------------------------
# Removing a committed focus topic — POST /api/body-double/focus had no caller
# ---------------------------------------------------------------------------


class TestCommittedFocusIsRemovable:
    def test_a_config_committed_topic_can_be_dropped_from_the_web_ui(
        self, bd_page: Page, env
    ) -> None:
        """The per-slot Park button is hidden for config-sourced slots (no row
        id to demote), so before this there was no removal path at all."""
        try:
            _post_focus(env, ["Committed alpha", "Committed beta"])
            bd_page.locator("#bd-focus-refresh").click()
            bd_page.wait_for_function(
                "() => document.querySelectorAll('.bd-focus-drop').length === 2",
                timeout=10_000,
            )

            bd_page.locator('.bd-focus-drop[data-topic="Committed alpha"]').click()
            bd_page.wait_for_function(
                "() => document.querySelectorAll('.bd-focus-drop').length === 1",
                timeout=10_000,
            )
            # The server agrees, not just the DOM.
            topics = _focus_payload(env)["focus"]["topics"]
            assert topics == ["Committed beta"], topics
        finally:
            with contextlib.suppress(Exception):
                _post_focus(env, [])

    def test_clear_focus_removes_every_committed_topic(self, bd_page: Page, env) -> None:
        try:
            _post_focus(env, ["Committed alpha", "Committed beta"])
            bd_page.locator("#bd-focus-refresh").click()
            bd_page.wait_for_selector("#bd-focus-clear", state="visible", timeout=10_000)

            bd_page.locator("#bd-focus-clear").click()
            bd_page.wait_for_selector("#bd-focus-clear", state="hidden", timeout=10_000)
            payload = _focus_payload(env)
            assert payload["focus"]["topics"] == []
            assert payload["focus"]["is_set"] is False
        finally:
            with contextlib.suppress(Exception):
                _post_focus(env, [])

    def test_clear_focus_is_hidden_when_nothing_is_committed(self, bd_page: Page) -> None:
        """It must not offer to clear a focus that only came from the parking lot."""
        assert not bd_page.locator("#bd-focus-clear").is_visible()

    def test_stale_focus_is_surfaced(self, browser: Browser, env) -> None:
        """``is_stale`` shipped in the API payload and was rendered nowhere, so a
        focus committed months ago looked identical to one chosen this morning."""
        original = env.config.read_text(encoding="utf-8")
        env.config.write_text(
            original + "focus:\n  topics:\n    - Ancient commitment\n  updated: '2024-01-01'\n",
            encoding="utf-8",
        )
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        watch = ConsoleWatch(page)
        try:
            assert _focus_payload(env)["focus"]["is_stale"] is True, "fixture is not stale"
            page.goto(f"{env.base_url}/")
            goto_view(page, "body-double")
            page.wait_for_selector("#bd-focus-stale", state="visible", timeout=15_000)
            assert "30 days" in (page.locator("#bd-focus-stale").get_attribute("title") or "")
        except Exception:
            diag(page, "bd-focus-stale", watch)
            raise
        finally:
            ctx.close()
            env.config.write_text(original, encoding="utf-8")


# ---------------------------------------------------------------------------
# The end control — findable, labelled, and it actually releases the workspace
# ---------------------------------------------------------------------------


def _start_session(page: Page, activity: str) -> None:
    """Start a real body-double session through the picker."""
    page.locator("#bd-activity-input").fill(activity)
    page.select_option("#bd-agent-select", value="fake")
    page.select_option("#bd-transport-select", value="pty")
    page.locator("#bd-start-session").click()
    page.wait_for_selector("#bd-end-session", state="visible", timeout=30_000)


needs_fake_agent = pytest.mark.skipif(
    not shutil.which("studyloop-fake-agent"),
    reason="studyloop-fake-agent not installed (uv sync installs it)",
)


class TestEndingASessionIsFindableAndComplete:
    @pytest.fixture(autouse=True)
    def _no_orphan_session(self, env):
        """Only one session can be live at a time, so a test that leaves one
        running turns the next test's picker into an invisible element and the
        failure into a 30s timeout that names the wrong thing."""
        yield
        with contextlib.suppress(Exception):
            urllib.request.urlopen(
                urllib.request.Request(f"{env.base_url}/api/session/end", data=b"", method="POST"),
                timeout=10,
            )

    @needs_fake_agent
    def test_end_control_is_labelled_and_stays_on_screen_over_the_terminal(
        self, bd_page: Page
    ) -> None:
        """The reported defect, precisely: scrolled down to the terminal, the
        stop control used to be somewhere above the fold."""
        try:
            _start_session(bd_page, "Refactor the ingest DAG")
            end = bd_page.locator("#bd-end-session")
            assert end.get_attribute("aria-label") == "End body double session"
            assert "End session" in end.inner_text()

            # Scroll the real scroll container to the terminal.
            bd_page.wait_for_selector(".bd-console-panel", state="visible", timeout=30_000)
            bd_page.eval_on_selector(".content-area", "(el) => { el.scrollTop = el.scrollHeight; }")
            bd_page.wait_for_timeout(400)

            console_box = bd_page.locator(".bd-console-panel").bounding_box()
            end_box = end.bounding_box()
            viewport = bd_page.viewport_size
            assert console_box is not None and end_box is not None and viewport is not None
            assert console_box["y"] < viewport["height"], "the terminal is not in view"
            assert 0 <= end_box["y"] <= viewport["height"] - end_box["height"], (
                f"the end control scrolled off screen: {end_box} vs viewport {viewport}"
            )
        except Exception:
            diag(bd_page, "bd-end-pinned", _watch_for(bd_page))
            raise

    @needs_fake_agent
    def test_ending_asks_first_and_can_be_cancelled(self, bd_page: Page) -> None:
        """Ending kills a live agent and its PTY. Study Session has always
        confirmed; the Body Double twin ended instantly, and its control is now
        pinned and prominent enough to hit by accident."""
        try:
            _start_session(bd_page, "Trace the decorator call order")
            bd_page.locator("#bd-end-session").click()
            bd_page.wait_for_selector("#bd-end-confirm", state="visible", timeout=5_000)

            bd_page.locator("#bd-end-cancel").click()
            bd_page.wait_for_selector("#bd-end-confirm", state="hidden", timeout=5_000)
            assert bd_page.locator("#bd-end-session").is_visible(), (
                "cancelling the confirm must leave the session running"
            )
            assert bd_page.locator("#bd-live-activity").inner_text() == (
                "Trace the decorator call order"
            )
        finally:
            with contextlib.suppress(Exception):
                bd_page.evaluate(
                    "async () => { await fetch('/api/session/end', {method:'POST'}); }"
                )

    @needs_fake_agent
    def test_ending_stops_the_pomodoro_and_clears_the_stale_activity(self, bd_page: Page) -> None:
        """Two things used to outlive the session that ended them.

        ``$store.pomodoro.stop()`` was wired only to the floating header widget,
        so the timer kept counting down a session that no longer existed; and the
        picker came back pre-filled, so the obvious next Start silently re-ran
        the last thing.
        """
        try:
            _start_session(bd_page, "Spark shuffle partitions")
            bd_page.locator('.body-double-controls button:has-text("Start Pomodoro")').click()
            bd_page.wait_for_function(
                "() => window.Alpine.store('pomodoro').running === true", timeout=5_000
            )

            bd_page.locator("#bd-end-session").click()
            bd_page.locator("#bd-end-confirm-yes").click()
            bd_page.wait_for_selector("#bd-end-session", state="hidden", timeout=20_000)

            bd_page.wait_for_function(
                "() => window.Alpine.store('pomodoro').running === false", timeout=10_000
            )
            assert bd_page.evaluate("() => window.Alpine.store('pomodoro').visible") is False
            assert bd_page.locator("#bd-activity-input").input_value() == "", (
                "the picker still holds the activity of the session that just ended"
            )
            assert bd_page.locator("#bd-start-session").is_visible()
        except Exception:
            diag(bd_page, "bd-end-releases", _watch_for(bd_page))
            raise

    @needs_fake_agent
    def test_the_panes_are_still_usable_after_the_session_ends(self, bd_page: Page) -> None:
        """Post-end state, which nothing asserted before: the panes stay (they
        are the workspace, not session chrome), and they stay operable."""
        try:
            _start_session(bd_page, "dbt test selectors")
            bd_page.locator("#bd-note-body").fill("A draft that must outlive the session.")
            bd_page.locator("#bd-end-session").click()
            bd_page.locator("#bd-end-confirm-yes").click()
            bd_page.wait_for_selector("#bd-end-session", state="hidden", timeout=20_000)

            assert bd_page.locator("#bd-focus").is_visible()
            assert bd_page.locator("#bd-capture").is_visible()
            assert bd_page.locator("#bd-note-body").input_value() == (
                "A draft that must outlive the session."
            ), "an unsaved note must not be destroyed by ending the session"
            # And they can still be folded away, which is the whole point.
            bd_page.locator("#bd-capture-toggle").click()
            bd_page.wait_for_selector("#bd-capture-body", state="hidden", timeout=5_000)
        except Exception:
            diag(bd_page, "bd-post-end", _watch_for(bd_page))
            raise


# ---------------------------------------------------------------------------
# The transport picker and the renderer it names
# ---------------------------------------------------------------------------


class TestTransportPickerNamesTheRealRenderer:
    def test_values_are_the_api_contract_and_default_to_pty(self, bd_page: Page) -> None:
        """``#bd-transport-select`` was actuated by no test anywhere. The values
        are what POST /api/session/start reads, so they are pinned."""
        values = bd_page.eval_on_selector_all(
            "#bd-transport-select option", "(opts) => opts.map((o) => o.value)"
        )
        # The UI surface is now deliberately NARROWER than the API surface: the
        # server still honours transport="ttyd" (STUDYLOOP_TRANSPORT=ttyd, one
        # deprecation window), but the browser no longer OFFERS it, because the
        # ttyd iframe needs a separately-installed binary and renders an empty
        # frame without it - indistinguishable from a hang. Offering a option
        # that usually looks broken is worse than not offering it.
        assert values == ["pty", "acp"], values
        assert bd_page.eval_on_selector("#bd-transport-select", "(el) => el.value") == "pty"

    def test_selecting_a_transport_swaps_the_hint(self, bd_page: Page) -> None:
        # Drives acp rather than the retired ttyd option; what is under test is
        # that CHANGING transport swaps the hint, not which value does it.
        bd_page.select_option("#bd-transport-select", value="acp")
        bd_page.wait_for_selector("#bd-transport-hint-pty", state="hidden", timeout=5_000)
        assert bd_page.eval_on_selector("#bd-transport-select", "(el) => el.value") == "acp"
        bd_page.select_option("#bd-transport-select", value="pty")
        bd_page.wait_for_selector("#bd-transport-hint-pty", state="visible", timeout=5_000)

    def test_stock_build_names_xterm_and_shows_no_experiment_badge(self, bd_page: Page) -> None:
        label = bd_page.eval_on_selector(
            "#bd-transport-select option[value='pty']", "(o) => o.textContent.trim()"
        )
        assert label == "Browser terminal (xterm.js)", label
        assert "xterm.js" in bd_page.locator("#bd-transport-hint-pty").inner_text()
        assert not bd_page.locator("#dev-engine-badge").is_visible(), (
            "the stock build has no experiment to warn about"
        )


class TestNoteComposerControls:
    """``#bd-note-topic`` and ``#bd-note-diagram`` were actuated by no test at
    all — they were only ever asserted to exist."""

    def test_the_topic_select_offers_the_live_focus_slots(self, bd_page: Page, env) -> None:
        import requests

        try:
            _post_focus(env, ["Committed alpha"])
            bd_page.locator("#bd-focus-refresh").click()
            bd_page.wait_for_function(
                "() => [...document.querySelectorAll('#bd-note-topic option')]"
                ".some((o) => o.value === 'Committed alpha')",
                timeout=10_000,
            )
            bd_page.select_option("#bd-note-topic", value="Committed alpha")
            assert bd_page.eval_on_selector("#bd-note-topic", "(el) => el.value") == (
                "Committed alpha"
            )

            # And it is what the saved note is filed under.
            bd_page.locator("#bd-note-title").fill("Filed under the chosen topic")
            bd_page.locator("#bd-save-note").click()
            bd_page.wait_for_selector("#bd-note-saved", state="visible", timeout=10_000)
            notes = requests.get(f"{env.base_url}/api/notes?limit=5", timeout=15).json()
            match = next(n for n in notes["notes"] if n["title"] == "Filed under the chosen topic")
            assert match["topic"] == "Committed alpha", match
        except Exception:
            diag(bd_page, "bd-note-topic", _watch_for(bd_page))
            raise
        finally:
            with contextlib.suppress(Exception):
                _post_focus(env, [])

    def test_the_diagram_button_inserts_a_mermaid_block_and_renders_it(self, bd_page: Page) -> None:
        try:
            bd_page.locator("#bd-note-body").fill("## Call order\n")
            bd_page.locator("#bd-note-diagram").click()
            bd_page.wait_for_selector("#bd-note-preview", state="visible", timeout=10_000)

            body = bd_page.locator("#bd-note-body").input_value()
            assert "```mermaid" in body, body
            assert body.startswith("## Call order"), "the existing draft was overwritten"
            # Rendered, not merely inserted: mermaid's second pass produces SVG.
            bd_page.wait_for_selector("#bd-note-preview svg", state="attached", timeout=20_000)
            _watch_for(bd_page).assert_clean("inserting a mermaid diagram")
        except Exception:
            diag(bd_page, "bd-note-diagram", _watch_for(bd_page))
            raise


class TestDevEngineIsVisible:
    """``studyloop web --dev`` replaces ``window.Terminal`` globally.

    So under ``--dev`` the ``pty`` transport renders through libghostty while
    the option read "Browser terminal (xterm.js)" and nothing anywhere said an
    experimental engine was live. ``--dev`` and ``--lan`` do not change the
    transport list, and should not: the list is how the agent PROCESS is driven,
    which is a different axis entirely.
    """

    @pytest.fixture()
    def dev_page(self, browser: Browser, dev_env):
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        _WATCHES[page] = ConsoleWatch(page)
        try:
            page.goto(f"{dev_env.base_url}/")
            goto_view(page, "body-double")
            page.wait_for_selector("#bd-focus", state="visible", timeout=15_000)
            yield page
        finally:
            ctx.close()

    def test_the_page_really_is_running_the_dev_engine(self, dev_page: Page) -> None:
        """Guard against the whole class passing because --dev silently no-op'd."""
        marker = dev_page.eval_on_selector("meta[name='studyloop-dev-mode']", "(el) => el.content")
        assert marker == "ghostty", marker

    def test_the_pty_option_names_libghostty_not_xterm(self, dev_page: Page) -> None:
        dev_page.wait_for_function(
            "() => window.Alpine.store('terminalEngine').experimental === true",
            timeout=15_000,
        )
        label = dev_page.eval_on_selector(
            "#bd-transport-select option[value='pty']", "(o) => o.textContent.trim()"
        )
        assert label == "Browser terminal (libghostty)", label
        assert "xterm.js" not in label

    def test_the_pty_hint_says_the_engine_is_experimental(self, dev_page: Page) -> None:
        dev_page.wait_for_function(
            "() => window.Alpine.store('terminalEngine').experimental === true",
            timeout=15_000,
        )
        hint = dev_page.locator("#bd-transport-hint-pty").inner_text()
        assert "libghostty" in hint
        assert "experimental" in hint.lower()

    def test_the_transport_values_are_unchanged_by_dev_mode(self, dev_page: Page) -> None:
        """--dev swaps the RENDERER. It must not touch the transport contract."""
        values = dev_page.eval_on_selector_all(
            "#bd-transport-select option", "(opts) => opts.map((o) => o.value)"
        )
        # The UI surface is now deliberately NARROWER than the API surface: the
        # server still honours transport="ttyd" (STUDYLOOP_TRANSPORT=ttyd, one
        # deprecation window), but the browser no longer OFFERS it, because the
        # ttyd iframe needs a separately-installed binary and renders an empty
        # frame without it - indistinguishable from a hang. Offering a option
        # that usually looks broken is worse than not offering it.
        assert values == ["pty", "acp"], values

    def test_a_badge_announces_the_experiment_and_lists_its_gaps(self, dev_page: Page) -> None:
        badge = dev_page.locator("#dev-engine-badge")
        badge.wait_for(state="visible", timeout=15_000)
        assert "libghostty" in badge.inner_text()
        title = badge.get_attribute("title") or ""
        assert "--dev" in title
        # The documented reasons this is still behind a flag.
        assert "Clipboard" in title
        assert "Scrollback" in title

    def test_the_study_session_picker_is_labelled_too(self, dev_page: Page) -> None:
        """Both surfaces hard-coded the same wrong label."""
        goto_view(dev_page, "study-session")
        dev_page.wait_for_selector("#transport-select", state="attached", timeout=15_000)
        label = dev_page.eval_on_selector(
            "#transport-select option[value='pty']", "(o) => o.textContent.trim()"
        )
        assert label == "Browser terminal (libghostty)", label
