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

2026-09-28: the Focus pane left Body Double entirely ("I should be able to run
a body double session for anything I'm doing, no restrictions or list of Focus
areas"), so committed focus is managed with ``studyloop focus`` again, and a
live session became the agent's screen (``TestTheAgentIsTheCentreOfALiveSession``).

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
        # The picker, not a panel: it is the one thing an idle Body Double view
        # must always show.
        page.wait_for_selector("#bd-activity-input", state="visible", timeout=15_000)
        yield page
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# The dismiss path — collapse, because nothing could reopen a closed pane
# ---------------------------------------------------------------------------


class TestPanesCanBeFoldedAway:
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
            bd_page.locator("#bd-capture-toggle").click()
            bd_page.wait_for_selector("#bd-capture-body", state="hidden", timeout=5_000)

            bd_page.reload()
            goto_view(bd_page, "body-double")
            bd_page.wait_for_selector("#bd-activity-input", state="visible", timeout=15_000)
            bd_page.wait_for_selector("#bd-capture-body", state="hidden", timeout=10_000)
        except Exception:
            diag(bd_page, "bd-collapse-persist", _watch_for(bd_page))
            raise


# ---------------------------------------------------------------------------
# The end control — findable, labelled, and it actually releases the workspace
# ---------------------------------------------------------------------------


def _start_session(page: Page, activity: str) -> None:
    """Start a real body-double session through the picker."""
    page.locator("#bd-activity-input").fill(activity)
    page.select_option("#bd-agent-select", value="codex")
    page.select_option("#bd-transport-select", value="pty")
    page.locator("#bd-start-session").click()
    page.wait_for_selector("#bd-end-session", state="visible", timeout=30_000)


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

    def test_ending_stops_the_pomodoro_and_clears_the_stale_activity(self, bd_page: Page) -> None:
        """Two things used to outlive the session that ended them.

        ``$store.pomodoro.stop()`` was wired only to the floating header widget,
        so the timer kept counting down a session that no longer existed; and the
        picker came back pre-filled, so the obvious next Start silently re-ran
        the last thing.
        """
        try:
            _start_session(bd_page, "Spark shuffle partitions")
            # While live, the Pomodoro is on the session strip (the timer block
            # steps aside so the console sits under the strip).
            bd_page.locator("#bd-live-pomodoro").click()
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

    def test_the_panes_are_still_usable_after_the_session_ends(self, bd_page: Page) -> None:
        """Post-end state, which nothing asserted before: the Capture pane stays
        (it is the workspace, not session chrome), and it stays operable."""
        try:
            _start_session(bd_page, "dbt test selectors")
            # Capture folds for a live session; the Note tab opens it.
            bd_page.locator("#bd-tab-note").click()
            bd_page.locator("#bd-note-body").fill("A draft that must outlive the session.")
            bd_page.locator("#bd-end-session").click()
            bd_page.locator("#bd-end-confirm-yes").click()
            bd_page.wait_for_selector("#bd-end-session", state="hidden", timeout=20_000)

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
# Body doubling is for anything — and a live session is the agent's screen
# ---------------------------------------------------------------------------


def _park_via_api(env, question: str) -> None:
    import requests

    response = requests.post(
        f"{env.base_url}/api/parking/item", json={"question": question, "notes": ""}, timeout=15
    )
    assert response.status_code in (200, 201), response.text


def _clear_parking(env) -> None:
    import requests

    with contextlib.suppress(Exception):
        requests.post(
            f"{env.base_url}/api/parking/clear", json={"all": True, "hard": True}, timeout=15
        )


def _end_any_session(env) -> None:
    with contextlib.suppress(Exception):
        urllib.request.urlopen(
            urllib.request.Request(f"{env.base_url}/api/session/end", data=b"", method="POST"),
            timeout=10,
        )


_STUDY_TOPICS = ("Spark shuffle", "SQL window functions", "dbt tests", "Glue bookmarks")

_LIVE_GEOMETRY_JS = """() => {
  const rect = (selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return null;
    return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height};
  };
  return {
    innerHeight: window.innerHeight,
    content: rect('.content-area'),
    strip: rect('.bd-live-strip'),
    console: rect('.bd-console-panel'),
    viewHeader: rect('.body-double-view .body-double-header'),
    timerBlock: rect('.body-double-view .body-double-timer'),
    capture: rect('#bd-capture'),
    fab: rect('.quick-park-btn'),
  };
}"""


def _overlaps(a: dict, b: dict, slack: float = 0.5) -> bool:
    return (
        a["left"] < b["right"] - slack
        and b["left"] < a["right"] - slack
        and a["top"] < b["bottom"] - slack
        and b["top"] < a["bottom"] - slack
    )


class TestBodyDoubleIsForAnything:
    """Reported 2026-09-28 with screenshots: "I should be able to run a body
    double session for anything I'm doing, no restrictions or list of Focus
    areas". The Focus card listed the three most recent pending STUDY topics
    with an "at capacity" chip, above the picker and above the live terminal.
    The activity field was always free text, so the card restricted nothing; it
    only looked as if it did, on a surface whose own spec says body doubling is
    not a new study thread (ADR-0003)."""

    def test_the_surface_lists_no_study_topics(self, bd_page: Page, env) -> None:
        try:
            # Fill every slot first, so a Focus card that still existed would have
            # to show topics and its at-capacity chip.
            for topic in _STUDY_TOPICS:
                _park_via_api(env, topic)
            bd_page.reload()
            goto_view(bd_page, "body-double")
            bd_page.wait_for_selector("#bd-activity-input", state="visible", timeout=15_000)
            bd_page.wait_for_function(
                "() => window.Alpine.$data(document.querySelector("
                "'[x-data=\"bodyDoubleSession()\"]'))._initDone === true",
                timeout=15_000,
            )
            view = bd_page.locator(".body-double-view")
            assert view.locator("#bd-focus").count() == 0, "the Focus card is still on Body Double"
            text = view.inner_text()
            for phrase in ("of 3 topics", "at capacity", *_STUDY_TOPICS):
                assert phrase not in text, f"Body Double still shows {phrase!r}"
            options = bd_page.eval_on_selector_all(
                "#bd-note-topic option", "(els) => els.map((e) => e.textContent.trim())"
            )
            assert options == ["No topic"], f"the note composer offers study topics: {options}"
        except Exception:
            diag(bd_page, "bd-no-focus-list", _watch_for(bd_page))
            raise
        finally:
            _clear_parking(env)


class TestTheAgentIsTheCentreOfALiveSession:
    """Same report: "I end up with a very 'busy' screen with the agent not being
    a clear central focus". Measured at 1440x900 before this change: the view's
    heading, the 25:00 timer block and the Focus card put the terminal 432px down
    the content area, its bottom fell below the window, the Capture card sat
    wholly below the fold, and the Park-a-thought button covered the terminal's
    bottom-right corner."""

    @pytest.fixture(autouse=True)
    def _no_orphan_session(self, env):
        yield
        _end_any_session(env)

    @pytest.mark.parametrize("size", [(1440, 900), (1024, 768)], ids=["laptop", "tablet"])
    def test_one_strip_then_a_console_that_fills_the_window(
        self, browser: Browser, env, size: tuple[int, int]
    ) -> None:
        width, height = size
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        watch = ConsoleWatch(page)
        try:
            page.goto(f"{env.base_url}/")
            goto_view(page, "body-double")
            page.wait_for_selector("#bd-activity-input", state="visible", timeout=15_000)
            _start_session(page, "Reconcile the March invoices")
            page.wait_for_selector(
                ".bd-console-panel .xterm-mount", state="visible", timeout=30_000
            )
            page.wait_for_timeout(600)
            g = page.evaluate(_LIVE_GEOMETRY_JS)

            assert g["viewHeader"] is None, "the view's heading still sits above a live session"
            assert g["timerBlock"] is None, "the 25:00 timer block still sits above a live session"
            content, strip, console = g["content"], g["strip"], g["console"]
            above = strip["top"] - content["top"]
            assert above <= 24, f"{above:.0f}px of other panels above the session strip"
            gap = console["top"] - strip["bottom"]
            assert gap <= 16, f"{gap:.0f}px between the session strip and the agent"
            below = console["bottom"] - g["innerHeight"]
            assert below <= 0.5, f"the agent's console runs {below:.0f}px below the window"
            share = console["height"] / content["height"]
            assert share >= 0.6, f"the agent's console gets {share:.0%} of the content area"
            for name in ("capture", "fab"):
                if g[name] is not None:
                    assert not _overlaps(console, g[name]), f"the {name} covers the agent's console"
        except Exception:
            diag(page, f"bd-live-fill-{width}", watch)
            raise
        finally:
            ctx.close()

    def test_the_strip_carries_the_timer_and_the_end_control(self, bd_page: Page) -> None:
        try:
            _start_session(bd_page, "Write the quarterly report")
            strip = bd_page.locator(".bd-live-strip")
            timer = strip.locator("#bd-live-timer")
            assert timer.is_visible(), "no timer on the session strip"
            assert timer.inner_text() == bd_page.evaluate(
                "() => window.Alpine.store('pomodoro').display"
            )
            strip.locator("#bd-live-pomodoro").click()
            bd_page.wait_for_function(
                "() => window.Alpine.store('pomodoro').running === true", timeout=5_000
            )
            assert strip.locator("#bd-end-session").is_visible()
            # A hit test, not visibility: starting the Pomodoro shows the floating
            # timer widget (fixed, top-right), which landed exactly on End once
            # the strip moved to the top of the view. Playwright's click only
            # reported "intercepts pointer events" after a 30s timeout.
            hit = bd_page.evaluate(
                """() => {
                    const end = document.querySelector('#bd-end-session');
                    const r = end.getBoundingClientRect();
                    const el = document.elementFromPoint(
                        r.left + r.width / 2, r.top + r.height / 2);
                    return el && el.closest('#bd-end-session') ? 'end' : (el ? el.className : null);
                }"""
            )
            assert hit == "end", f"End session is covered by {hit!r} while the Pomodoro runs"
        except Exception:
            diag(bd_page, "bd-live-strip-timer", _watch_for(bd_page))
            raise
        finally:
            with contextlib.suppress(Exception):
                bd_page.evaluate("() => window.Alpine.store('pomodoro').stop()")

    def test_capture_folds_for_the_session_and_opens_on_request(self, bd_page: Page) -> None:
        try:
            assert bd_page.locator("#bd-capture-body").is_visible(), "fixture: Capture starts open"
            _start_session(bd_page, "Tidy the garage inventory sheet")
            bd_page.wait_for_selector("#bd-capture-body", state="hidden", timeout=5_000)
            assert bd_page.locator("#bd-tab-note").is_visible(), (
                "the way to take a note must stay on screen while Capture is folded"
            )

            bd_page.locator("#bd-tab-note").click()
            bd_page.wait_for_selector("#bd-note-body", state="visible", timeout=5_000)
            bd_page.wait_for_timeout(300)
            g = bd_page.evaluate(_LIVE_GEOMETRY_JS)
            assert g["console"]["height"] >= 240, (
                f"opening Capture squeezed the agent to {g['console']['height']:.0f}px"
            )
            assert not _overlaps(g["console"], g["capture"]), "Capture covers the agent's console"

            bd_page.locator("#bd-end-session").click()
            bd_page.locator("#bd-end-confirm-yes").click()
            bd_page.wait_for_selector("#bd-end-session", state="hidden", timeout=20_000)
            assert bd_page.locator("#bd-capture-body").is_visible(), (
                "ending must give back the idle layout the learner chose"
            )
        except Exception:
            diag(bd_page, "bd-live-capture-fold", _watch_for(bd_page))
            raise

    @pytest.mark.parametrize("size", [(1440, 900), (1024, 768)], ids=["laptop", "tablet"])
    def test_opening_capture_never_covers_the_agent(
        self, browser: Browser, env, size: tuple[int, int]
    ) -> None:
        """Found by measuring the first version of this layout at 1024x768: with
        Capture open, the section holding the console shrank to 201px while the
        console kept its 240px floor, so the console spilled 90px under the note
        form. Short windows may scroll; they must never overlap."""
        width, height = size
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        watch = ConsoleWatch(page)
        try:
            page.goto(f"{env.base_url}/")
            goto_view(page, "body-double")
            page.wait_for_selector("#bd-activity-input", state="visible", timeout=15_000)
            _start_session(page, "Sort the photo archive")
            page.locator("#bd-tab-note").click()
            page.wait_for_selector("#bd-note-body", state="visible", timeout=5_000)
            page.wait_for_timeout(400)
            g = page.evaluate(_LIVE_GEOMETRY_JS)
            assert not _overlaps(g["console"], g["capture"]), (
                f"the note form covers the agent's console: console {g['console']}, "
                f"capture {g['capture']}"
            )
            assert g["console"]["height"] >= 220, (
                f"opening Capture squeezed the agent to {g['console']['height']:.0f}px"
            )
        except Exception:
            diag(page, f"bd-live-capture-{width}", watch)
            raise
        finally:
            ctx.close()

    def test_the_note_topic_is_what_you_are_working_on(self, bd_page: Page, env) -> None:
        import requests

        try:
            for topic in _STUDY_TOPICS[:3]:
                _park_via_api(env, topic)
            _start_session(bd_page, "Plan the allotment beds")
            bd_page.locator("#bd-tab-note").click()
            bd_page.wait_for_selector("#bd-note-topic", state="visible", timeout=5_000)
            options = bd_page.eval_on_selector_all(
                "#bd-note-topic option", "(els) => els.map((e) => e.textContent.trim())"
            )
            assert options == ["No topic", "Plan the allotment beds"], options
            assert bd_page.eval_on_selector("#bd-note-topic", "(el) => el.value") == (
                "Plan the allotment beds"
            )

            bd_page.locator("#bd-note-title").fill("Filed under the activity")
            bd_page.locator("#bd-save-note").click()
            bd_page.wait_for_selector("#bd-note-saved", state="visible", timeout=10_000)
            notes = requests.get(f"{env.base_url}/api/notes?limit=5", timeout=15).json()
            match = next(n for n in notes["notes"] if n["title"] == "Filed under the activity")
            assert match["topic"] == "Plan the allotment beds", match
        except Exception:
            diag(bd_page, "bd-note-topic-activity", _watch_for(bd_page))
            raise
        finally:
            _clear_parking(env)


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
        # ttyd is fully retired (ttyd retirement stages 2-5): the server
        # structurally rejects transport="ttyd"/STUDYLOOP_TRANSPORT=ttyd with
        # 422 rather than accepting it, and the browser never offered it
        # (the ttyd iframe needed a separately-installed binary and rendered
        # an empty, hang-indistinguishable frame without it). Only pty/acp
        # exist anywhere in the stack now.
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
    all — they were only ever asserted to exist. The topic select's behaviour
    is pinned by TestTheAgentIsTheCentreOfALiveSession's note-topic test."""

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
            page.wait_for_selector("#bd-activity-input", state="visible", timeout=15_000)
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
        # ttyd is fully retired (ttyd retirement stages 2-5): the server
        # structurally rejects transport="ttyd"/STUDYLOOP_TRANSPORT=ttyd with
        # 422 rather than accepting it, and the browser never offered it
        # (the ttyd iframe needed a separately-installed binary and rendered
        # an empty, hang-indistinguishable frame without it). Only pty/acp
        # exist anywhere in the stack now.
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
