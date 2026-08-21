"""Representative user workflow against a **real PTY** on the libghostty terminal.

Companion to ``test_ghostty_dev_terminal.py``, which validates the engine with
synthetic writes. This module removes that stub: it clicks through the real UI
to spawn a real agent process over a real PTY and a real WebSocket, then runs
the five workflow validations against that live session.

Why both exist
--------------
The synthetic suite is fast and precise — it can drive any byte sequence into
the emulator. But it proves nothing about the transport, and a terminal that
renders perfectly from ``adapter.write()`` can still be broken end to end
(StudyLoop has shipped exactly that bug before: the wterm adapter rendered
fine and then dropped the agent mid-session).

This module is the counterpart: fewer, slower tests, but every byte asserted
here travelled

    fake agent process → PTY → WebSocket → adapter → libghostty → canvas

and every keystroke travelled back the other way.

Notably it can assert **agent output text**, which the equivalent xterm.js test
cannot: xterm paints to a WebGL canvas with no DOM text, so
``test_representative_user_journey.py`` can only check that the header flips to
"Connected". The ghostty adapter exposes the VT buffer, so the actual banner and
replies are assertable.

The agent is ``studyloop-fake-agent`` (``STUDYLOOP_TEST_AGENT=1``), which emits
stable line-oriented markers — ``FAKE-AGENT READY``, ``FAKE-AGENT VERDICT:`` — so
the transcript is parseable without an LLM.

Plan/analysis: docs/explorations/ghostty-web-evaluation.md
"""

from __future__ import annotations

import contextlib
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, _tests_dir)

from _playwright_paths import PLAYWRIGHT_ARTIFACTS as RESULTS  # noqa: E402
from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402

pytestmark = [pytest.mark.e2e]


WASM_TIMEOUT_MS = 30_000
CONNECT_TIMEOUT_MS = 30_000
AGENT_TIMEOUT_MS = 20_000

# Empty backlog: this module's subject is the terminal, and the 3-active-topic
# park-first rule (covered elsewhere) would otherwise intercept the start when
# the real vault already has three live topics.
_EMPTY_BACKLOG = {
    "active": [],
    "parking_lot": [],
    "active_count": 0,
    "parking_lot_count": 0,
    "max_active": 3,
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_env(tmp_path_factory: pytest.TempPathFactory) -> RunningServer:
    """Dev-mode server with the fake agent inside a disposable test world."""
    root = tmp_path_factory.mktemp("ghostty-live")
    world = build_test_world(root, _free_port(), fake_agent=True)
    if not shutil.which("studyloop-fake-agent", path=world.env["PATH"]):
        pytest.skip("studyloop-fake-agent not installed (editable install needed)")

    server = start_server(world, extra_args=["--dev"])
    try:
        yield server
    finally:
        # Best-effort session teardown before the server goes away, so a
        # failed test cannot leave an orphaned agent process behind.
        try:
            req = urllib.request.Request(
                f"{server.base_url}/api/session/end", data=b"", method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
        _await_no_session(server.base_url)
        server.stop()


@pytest.fixture()
def live_page(live_env: RunningServer, browser):
    """Page with the backlog stubbed empty and a wide viewport."""
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()
    page.route("**/api/backlog", lambda route: route.fulfill(json=_EMPTY_BACKLOG))
    yield page
    context.close()
    # End the session out-of-band, not through the page: ending it through the
    # page is fragile precisely because the page is the thing under test, and a
    # test that fails mid-render can leave the evaluate() unable to run. It
    # matters more since the detach-grace change landed — a leftover session no
    # longer self-destructs when the browser goes away, so a missed teardown
    # 409s every subsequent start in the module instead of healing itself.
    with contextlib.suppress(Exception):
        req = urllib.request.Request(
            f"{live_env.base_url}/api/session/end", data=b"", method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
    _await_no_session(live_env.base_url)


def _await_no_session(base_url: str, timeout: float = 15.0) -> None:
    """Block until the server reports no active session."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/session/state", timeout=5) as resp:
                import json as _json

                if not _json.loads(resp.read()).get("study_session_id"):
                    return
        except Exception:
            return
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# Workflow helpers — these ARE the representative user actions
# ---------------------------------------------------------------------------


def _await_engine(page) -> None:
    page.wait_for_function(
        "() => typeof window.__studyloopGhostty !== 'undefined'"
        " && window.__studyloopGhostty.ready === true",
        timeout=WASM_TIMEOUT_MS,
    )
    error = page.evaluate("() => window.__studyloopGhostty.error")
    assert error is None, f"ghostty WASM init failed: {error}"


def _start_session_through_ui(page, server: RunningServer, topic: str) -> None:
    """Do what the learner does: open the tab, type a topic, pick the agent, Start.

    No API shortcut and no synthetic ``study-session-start`` event — this is the
    real picker driving the real spawn.
    """
    page.goto(f"{server.base_url}/#study-session")
    page.wait_for_function("() => !!window.Alpine", timeout=10_000)
    _await_engine(page)

    page.locator("#topic-input").fill(topic)

    # Generous timeout: a cold server builds the picker's vault index on the
    # first /api/session/options call.
    page.wait_for_function(
        """() => {
            const sel = document.querySelector('#agent-select');
            return sel && [...sel.options].some((o) => o.value === 'fake');
        }""",
        timeout=45_000,
    )
    page.select_option("#agent-select", value="fake")
    page.wait_for_function(
        "() => !document.querySelector('.study-start-picker .start-session-btn').disabled",
        timeout=10_000,
    )
    page.locator(".study-start-picker .start-session-btn").click()

    # WebSocket established and the transport reported Started.
    page.wait_for_function(
        "() => document.body.innerText.includes('Connected')",
        timeout=CONNECT_TIMEOUT_MS,
    )
    # The real terminal mounted (not the ttyd iframe or the ACP chat surface).
    page.wait_for_selector(
        ".xterm-mount.ghostty-active", state="visible", timeout=CONNECT_TIMEOUT_MS
    )
    page.wait_for_function(
        "() => { const g = window.__studyloopGhostty;"
        " return g.adapter && g.adapter._term && g.adapter._term.renderer; }",
        timeout=CONNECT_TIMEOUT_MS,
    )


def _await_agent_text(page, needle: str, timeout: int = AGENT_TIMEOUT_MS) -> None:
    """Wait for text emitted by the real agent to reach the terminal buffer."""
    page.wait_for_function(
        """(needle) => {
            const g = window.__studyloopGhostty;
            const lines = g.readBuffer() || [];
            return lines.join('\\n').includes(needle);
        }""",
        arg=needle,
        timeout=timeout,
    )


def _buffer_text(page) -> str:
    lines = page.evaluate("() => window.__studyloopGhostty.readBuffer()")
    assert lines is not None, "terminal buffer unavailable"
    return "\n".join(lines)


def _grapheme_text(page) -> str:
    lines = page.evaluate("() => window.__studyloopGhostty.readBufferGraphemes()")
    assert lines is not None, "grapheme buffer unavailable"
    return "\n".join(lines)


def _type_into_terminal(page, text: str) -> None:
    """Send keystrokes the way a learner does — focus the terminal and type.

    Goes through the real input path: DOM key events → InputHandler →
    adapter.onData → WebSocket → PTY → agent stdin.
    """
    page.click(".xterm-mount")
    page.keyboard.type(text)
    page.keyboard.press("Enter")


def _paste_into_terminal(page, text: str) -> None:
    """Paste text into the terminal, then press Enter — as a learner would.

    Paste, not keystrokes, is the correct path for emoji and other non-BMP
    characters. ghostty's key handler only forwards keys whose
    ``key.length === 1``, so a surrogate pair never reaches the terminal as a
    keydown event; typing "🎯" drops it silently and leaves a gap. Real users
    paste emoji or use an IME, and paste still travels the full outbound path
    (onData → WebSocket → PTY → agent stdin).
    """
    page.click(".xterm-mount")
    page.evaluate("(t) => window.__studyloopGhostty.adapter.paste(t)", text)
    page.keyboard.press("Enter")


def _dims(page) -> tuple[int, int]:
    return tuple(  # type: ignore[return-value]
        page.evaluate(
            "() => { const t = window.__studyloopGhostty.adapter._term; return [t.cols, t.rows]; }"
        )
    )


_CANVAS_BG_JS = """
() => {
  const c = document.querySelector('.xterm-mount canvas');
  if (!c) return null;
  const d = c.getContext('2d').getImageData(0, 0, 400, 200).data;
  const counts = new Map();
  for (let i = 0; i < d.length; i += 4) {
    const k = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2];
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  let best = 0, bestN = -1;
  for (const [k, n] of counts) { if (n > bestN) { bestN = n; best = k; } }
  const hex = (n) => n.toString(16).padStart(2, '0');
  return '#' + hex((best >> 16) & 255) + hex((best >> 8) & 255) + hex(best & 255);
}
"""


def _diag(page, label: str) -> None:
    """Screenshot + buffer dump on failure — a headless failure with no
    artifact is unactionable."""
    try:
        RESULTS.mkdir(exist_ok=True)
        page.screenshot(path=str(RESULTS / f"{label}.png"))
        buf = page.evaluate("() => window.__studyloopGhostty.readBuffer()")
        (RESULTS / f"{label}-buffer.txt").write_text(
            "\n".join(buf or ["<no buffer>"]), encoding="utf-8"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The workflow
# ---------------------------------------------------------------------------


class TestLiveAgentSession:
    """The transport actually works: real bytes both ways, rendered."""

    def test_agent_banner_renders_from_a_real_pty(self, live_page, live_env) -> None:
        """Start via the UI and see the real agent's banner in the terminal.

        This is the assertion the xterm.js equivalent cannot make — it can only
        check the header text, because its canvas holds no DOM text.
        """
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live Banner")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            text = _buffer_text(live_page)
            assert "FAKE-AGENT READY" in text, f"agent banner not rendered; buffer was:\n{text}"
            RESULTS.mkdir(exist_ok=True)
            live_page.screenshot(path=str(RESULTS / "ghostty-live-banner.png"))
        except Exception:
            _diag(live_page, "ghostty-live-banner-fail")
            raise

    def test_keystrokes_reach_the_agent_and_the_reply_renders(self, live_page, live_env) -> None:
        """Round-trip: type in the terminal, agent replies, reply renders.

        Exercises the full input path (DOM key events → InputHandler →
        onData → WS → PTY → agent stdin) and the output path back.
        """
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live Echo")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            _type_into_terminal(live_page, "decorators wrap functions")
            _await_agent_text(live_page, "FAKE-AGENT VERDICT:")

            text = _buffer_text(live_page)
            assert "FAKE-AGENT VERDICT:" in text, (
                f"agent did not echo the typed line; buffer was:\n{text}"
            )
        except Exception:
            _diag(live_page, "ghostty-live-echo-fail")
            raise


class TestLiveResize:
    """Requirement 1 — resize keeps the live agent transcript."""

    def test_resize_preserves_live_agent_output(self, live_page, live_env) -> None:
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live Resize")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            wide_cols, wide_rows = _dims(live_page)

            live_page.set_viewport_size({"width": 820, "height": 560})
            live_page.wait_for_function(
                "([c, r]) => { const t = window.__studyloopGhostty.adapter._term;"
                " return t.cols !== c || t.rows !== r; }",
                arg=[wide_cols, wide_rows],
                timeout=20_000,
            )
            narrow_cols, _ = _dims(live_page)
            assert narrow_cols < wide_cols, (
                f"expected fewer columns after shrink: {wide_cols} -> {narrow_cols}"
            )
            # The real agent's banner must survive the reflow.
            assert "FAKE-AGENT READY" in _buffer_text(live_page), (
                "live agent output lost when the window shrank"
            )

            # And the resized session is still usable — the PTY got the new
            # winsize and the agent still answers.
            _type_into_terminal(live_page, "still alive")
            _await_agent_text(live_page, "FAKE-AGENT VERDICT:")
        except Exception:
            _diag(live_page, "ghostty-live-resize-fail")
            raise


class TestLiveThemePropagation:
    """Requirement 2 — theme reaches terminal and panes, without dropping the agent.

    The strongest test of the rebuild design: a palette change disposes and
    recreates the underlying ghostty Terminal, so if the adapter did not hold
    the PTY link and replay buffer correctly, the live session would visibly
    break here.
    """

    DRACULA_BG = "#282a36"
    TOKYO_BG = "#1a1b26"

    def test_theme_change_keeps_the_live_session_alive(self, live_page, live_env) -> None:
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live Theme")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            assert live_page.evaluate(_CANVAS_BG_JS).lower() == self.TOKYO_BG
            rebuilds_before = live_page.evaluate("() => window.__studyloopGhostty.rebuildCount")

            live_page.evaluate("() => window.Alpine.store('settings').setPalette('dracula')")

            # Terminal theme, painted canvas, and pane variable all converge.
            live_page.wait_for_function(
                "(bg) => window.__studyloopGhostty.appliedTheme.background.toLowerCase() === bg",
                arg=self.DRACULA_BG,
                timeout=15_000,
            )
            live_page.wait_for_function(
                "(bg) => getComputedStyle(document.body)"
                ".getPropertyValue('--bg').trim().toLowerCase() === bg",
                arg=self.DRACULA_BG,
                timeout=10_000,
            )
            live_page.wait_for_function(
                """(bg) => {
                  const c = document.querySelector('.xterm-mount canvas');
                  if (!c) return false;
                  const d = c.getContext('2d').getImageData(0, 0, 40, 20).data;
                  const counts = new Map();
                  for (let i = 0; i < d.length; i += 4) {
                    const k = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2];
                    counts.set(k, (counts.get(k) || 0) + 1);
                  }
                  let best = 0, bestN = -1;
                  for (const [k, n] of counts) {
                    if (n > bestN) { bestN = n; best = k; }
                  }
                  const hex = (n) => n.toString(16).padStart(2, '0');
                  return '#' + hex((best >> 16) & 255) + hex((best >> 8) & 255)
                         + hex(best & 255) === bg;
                }""",
                arg=self.DRACULA_BG,
                timeout=15_000,
            )

            # A rebuild happened (that is the mechanism), ...
            rebuilds_after = live_page.evaluate("() => window.__studyloopGhostty.rebuildCount")
            assert rebuilds_after > rebuilds_before, (
                "expected a terminal rebuild to apply the theme"
            )
            # ... the transcript was replayed into the new terminal, ...
            assert "FAKE-AGENT READY" in _buffer_text(live_page), (
                "agent transcript lost across the theme rebuild"
            )
            # ... and the PTY is still attached and answering.
            _type_into_terminal(live_page, "after theme change")
            _await_agent_text(live_page, "FAKE-AGENT VERDICT:")

            # Session was never torn down server-side.
            state = live_page.evaluate(
                "async () => (await fetch('/api/session/state', { cache: 'no-store' })).json()"
            )
            assert state.get("study_session_id"), f"session lost after theme change: {state!r}"

            RESULTS.mkdir(exist_ok=True)
            live_page.screenshot(path=str(RESULTS / "ghostty-live-theme-dracula.png"))
        except Exception:
            _diag(live_page, "ghostty-live-theme-fail")
            raise


class TestLiveFontPropagation:
    """Requirement 3 — font reaches terminal and web frames mid-session."""

    def test_font_change_applies_without_dropping_the_agent(self, live_page, live_env) -> None:
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live Font")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            font_before = live_page.evaluate("() => window.__studyloopGhostty.appliedFont")
            prose_before = live_page.evaluate(
                "() => getComputedStyle(document.body).getPropertyValue('--font').trim()"
            )
            cols_before, _ = _dims(live_page)

            live_page.evaluate("() => window.Alpine.store('settings').setFont('atkinson')")
            live_page.wait_for_function(
                "() => window.__studyloopGhostty.appliedFont.fontFamily.includes('Atkinson')",
                timeout=15_000,
            )

            font_after = live_page.evaluate("() => window.__studyloopGhostty.appliedFont")
            prose_after = live_page.evaluate(
                "() => getComputedStyle(document.body).getPropertyValue('--font').trim()"
            )
            # Terminal side.
            assert "Atkinson" in font_after["fontFamily"]
            assert font_after["fontSize"] > font_before["fontSize"]
            # Web-frame side.
            assert "Atkinson" in prose_after
            assert prose_before != prose_after

            # Larger cells => fewer columns, and the PTY is told about it.
            live_page.wait_for_function(
                "(c) => window.__studyloopGhostty.adapter._term.cols < c",
                arg=cols_before,
                timeout=20_000,
            )

            # Live session survived the re-measure and re-fit.
            assert "FAKE-AGENT READY" in _buffer_text(live_page)
            _type_into_terminal(live_page, "after font change")
            _await_agent_text(live_page, "FAKE-AGENT VERDICT:")
        except Exception:
            _diag(live_page, "ghostty-live-font-fail")
            raise

    def test_dyslexic_toggle_applies_mid_session(self, live_page, live_env) -> None:
        """The accessibility toggle reaches the terminal during a live session."""
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live Dyslexic")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            live_page.evaluate("() => window.Alpine.store('settings').toggleDyslexic()")
            live_page.wait_for_function(
                "() => window.__studyloopGhostty.appliedFont.fontFamily.includes('OpenDyslexic')",
                timeout=15_000,
            )
            assert live_page.evaluate("() => document.body.classList.contains('dyslexic')")
            assert "FAKE-AGENT READY" in _buffer_text(live_page)
        except Exception:
            _diag(live_page, "ghostty-live-dyslexic-fail")
            raise


class TestLiveRefresh:
    """Requirement 4 — a browser refresh keeps the live session.

    **Met as of 2026-08-04.** ``web/routes/session/_ws.py`` no longer releases
    the session in a ``finally``; a client disconnect now schedules a *deferred*
    release through ``web/routes/session/_grace.py``, so a reconnect inside the
    grace window keeps the same agent, and ``sessionTimer()`` re-dispatches
    ``study-session-start`` on restore so the console reattaches on its own.

    Four tests, in the order a learner meets them:

    * :meth:`test_refresh_keeps_the_live_session` — the session object survives.
    * :meth:`test_refresh_reattaches_the_terminal_and_the_agent_still_answers` —
      the *conversation* survives: the console reconnects unaided and a freshly
      typed line is answered by the same process.
    * :meth:`test_refresh_shows_a_reattached_state_not_starting` — the resume is
      visible rather than silent.
    * :meth:`test_refresh_recovers_the_engine_and_allows_a_fresh_session` — the
      dev terminal comes back cleanly, and ending then starting again works.
      That last part is not incidental: the WS consumer slot used to be freed
      only by the route's ``finally``, so "refresh → End → Start" could refuse
      the next session's first WebSocket with a handshake 403.

    Historical note (pre-fix): a browser refresh closed the session WebSocket,
    and ``_ws.py`` released the session in a ``finally``:

        finally:
            await session_active.release()

    ``session/active.py::release()`` then called ``transport.end()`` — killing
    the agent process — and cleared the IPC state files, so refreshing the page
    terminated the study session. It was verified engine-independent (a default
    xterm.js server with no ``--dev`` died the same way within half a second),
    so it never had anything to do with libghostty. Full diagnosis:
    ``docs/handoffs/2026-08-04-ws-refresh-destroys-session-handoff.md``.

    Note the synthetic counterparts in ``test_ghostty_dev_terminal.py`` passed
    throughout, because they write session state to disk with no live WebSocket
    attached. They validate state restore, engine re-init and palette
    persistence across a reload — not live-session survival.
    """

    def test_refresh_keeps_the_live_session(self, live_page, live_env) -> None:
        """Refresh, and the same session is still live.

        Was ``xfail(strict=True)`` until the detach-grace work landed. It asserts
        session *survival* only — not console reattachment, which is still
        broken (403 on the second attach) and tracked in the handoff doc.
        """
        _start_session_through_ui(live_page, live_env, "Ghostty Refresh Wanted")
        _await_agent_text(live_page, "FAKE-AGENT READY")

        before = live_page.evaluate(
            "async () => (await fetch('/api/session/state', { cache: 'no-store' })).json()"
        )
        session_id = before.get("study_session_id")
        assert session_id, f"no active session before reload: {before!r}"

        live_page.reload()
        live_page.wait_for_load_state("domcontentloaded")

        after = live_page.evaluate(
            "async () => (await fetch('/api/session/state', { cache: 'no-store' })).json()"
        )
        assert after.get("study_session_id") == session_id, (
            f"session did not survive the reload: {before!r} -> {after!r}"
        )

    def test_refresh_reattaches_the_terminal_and_the_agent_still_answers(
        self, live_page, live_env
    ) -> None:
        """Case 9: reload, then type — the same agent answers.

        Session survival is only half the fix. This is the half the learner
        actually experiences: after ⌘R the console must reconnect on its own and
        the conversation must continue. Typing a *fresh* line and getting a
        reply is the strongest available proof that the reattached socket is
        wired to the same live process, not to a new one or to nothing.
        """
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Refresh Reattach")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            live_page.reload()
            live_page.wait_for_load_state("domcontentloaded")
            _await_engine(live_page)

            # The console reconnects with no user action — nothing here clicks.
            live_page.wait_for_function(
                "() => { const el = document.querySelector"
                "('[x-data=\"liveAgentConsole(\\'study\\')\"]');"
                " if (!el) return false; const d = Alpine.$data(el);"
                " return d && d.connected === true; }",
                timeout=AGENT_TIMEOUT_MS,
            )

            _type_into_terminal(live_page, "are you still there after the reload")
            _await_agent_text(live_page, "FAKE-AGENT VERDICT:")
        except Exception:
            _diag(live_page, "ghostty-live-refresh-reattach-fail")
            raise

    def test_refresh_shows_a_reattached_state_not_starting(self, live_page, live_env) -> None:
        """Case 10: the console says it reattached.

        Silently resuming mid-conversation with no marker is disorienting, and
        this audience is exactly the one for whom that matters. The reattach
        path must not present itself as a fresh "Starting", and — because
        decision 3 shipped without scrollback replay — the empty terminal must
        say why it is empty rather than looking broken.
        """
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Refresh Marker")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            live_page.reload()
            live_page.wait_for_load_state("domcontentloaded")
            _await_engine(live_page)
            _await_agent_text(live_page, "reattached to your running session")

            status = live_page.evaluate(
                "() => { const el = document.querySelector"
                "('[x-data=\"liveAgentConsole(\\'study\\')\"]');"
                " return el ? Alpine.$data(el).status : null; }"
            )
            assert status is not None, "study console not found on the reloaded page"
            assert "Starting" not in status, (
                f"reattach presented itself as a fresh start: {status!r}"
            )
        except Exception:
            _diag(live_page, "ghostty-live-refresh-marker-fail")
            raise

    def test_refresh_recovers_the_engine_and_allows_a_fresh_session(
        self, live_page, live_env
    ) -> None:
        """After a refresh the terminal engine comes back and can run again.

        This was ``test_refresh_drops_the_live_session_and_engine_recovers``,
        whose first assertion pinned the pre-grace behaviour ("the reload
        released the session"). That assertion is now false by design and has
        been removed, as the test itself instructed. Its other two halves are
        the durable ones and are kept: whatever the session lifecycle does, the
        dev terminal must come back cleanly on the refreshed page, and the
        learner must be able to start another session.

        Because the session now *survives* the refresh, it is ended explicitly
        before starting the next one — otherwise the single-session slot is
        still held and the second start is correctly refused with a 409.
        """
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Refresh Real")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            before = live_page.evaluate(
                "async () => (await fetch('/api/session/state', { cache: 'no-store' })).json()"
            )
            assert before.get("study_session_id"), f"no active session before reload: {before!r}"

            live_page.reload()
            live_page.wait_for_load_state("domcontentloaded")

            # 1. Release the surviving session so the slot is free again —
            #    through the UI, not a bare fetch. A fetch ends it server-side
            #    but leaves the reloaded page's `sessionActive` true, so the
            #    start picker stays hidden and the next start cannot be clicked.
            #    Ending it the way the learner does keeps both sides honest.
            live_page.locator(".session-status-bar .end-btn").click()
            live_page.locator("#end-confirm .end-confirm-yes").click()
            deadline = time.time() + 10
            after: dict = {}
            while time.time() < deadline:
                after = live_page.evaluate(
                    "async () => (await fetch('/api/session/state', { cache: 'no-store' })).json()"
                )
                if not after.get("study_session_id"):
                    break
                time.sleep(0.3)
            assert not after.get("study_session_id"), (
                f"explicit end did not release the session: {after!r}"
            )

            # 2. The dev engine recovered on the fresh page — a new WASM
            #    instance, adapter installed, no residual error.
            _await_engine(live_page)
            assert live_page.evaluate("() => window.Terminal.name") == "GhosttyAdapter"

            # 3. And the learner can start a fresh session immediately, with a
            #    real agent on a real PTY, in the refreshed page.
            _start_session_through_ui(live_page, live_env, "Ghostty Refresh Restart")
            _await_agent_text(live_page, "FAKE-AGENT READY")
            _type_into_terminal(live_page, "new session works")
            _await_agent_text(live_page, "FAKE-AGENT VERDICT:")
        except Exception:
            _diag(live_page, "ghostty-live-refresh-recovery-fail")
            raise


class TestLiveGlyphs:
    """Requirement 5 — glyphs and emoji survive the real transport.

    Distinct from the synthetic glyph tests: here the bytes are UTF-8 encoded
    by the browser, sent over the WebSocket, written to a PTY, echoed by a
    separate process, read back and only then decoded and rendered. Any
    encoding defect anywhere on that path shows up as mojibake.

    Input arrives by paste rather than keystrokes — see
    :func:`_paste_into_terminal` for why that is the correct path (and the only
    one that works) for non-BMP characters.
    """

    def test_emoji_round_trip_through_the_real_pty(self, live_page, live_env) -> None:
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live Glyphs")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            # The agent echoes what it is sent, so a successful round trip
            # proves the whole path preserved the bytes.
            _paste_into_terminal(live_page, "emoji 🎯 🧠 ✅ ok")
            live_page.wait_for_function(
                "() => (window.__studyloopGhostty.readBuffer() || []).join('\\n').includes('🎯')",
                timeout=AGENT_TIMEOUT_MS,
            )

            text = _buffer_text(live_page)
            for glyph in ("🎯", "🧠", "✅"):
                assert glyph in text, (
                    f"emoji {glyph} did not survive the PTY round trip; buffer was:\n{text}"
                )
            # And it came back from the agent, not just from local echo.
            _await_agent_text(live_page, "FAKE-AGENT VERDICT:")
        except Exception:
            _diag(live_page, "ghostty-live-emoji-fail")
            raise

    def test_cjk_round_trip_through_the_real_pty(self, live_page, live_env) -> None:
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live CJK")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            _paste_into_terminal(live_page, "cjk 日本語 한국어 done")
            live_page.wait_for_function(
                "() => (window.__studyloopGhostty.readBuffer() || [])"
                ".join('\\n').includes('日本語')",
                timeout=AGENT_TIMEOUT_MS,
            )
            text = _buffer_text(live_page)
            assert "日本語" in text, f"CJK lost on the wire; buffer:\n{text}"
            assert "한국어" in text, f"Hangul lost on the wire; buffer:\n{text}"
        except Exception:
            _diag(live_page, "ghostty-live-cjk-fail")
            raise

    def test_grapheme_clusters_survive_the_real_pty(self, live_page, live_env) -> None:
        """Combining marks survive encode → PTY → decode → render.

        The synthetic suite proves libghostty *stores* clusters; this proves
        they also survive a real transport, where a naive byte split or a
        latin-1 decode would corrupt them.
        """
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live Graphemes")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            _paste_into_terminal(live_page, "namaste नमस्ते end")
            live_page.wait_for_function(
                "() => (window.__studyloopGhostty.readBufferGraphemes() || [])"
                ".join('\\n').includes('नम')",
                timeout=AGENT_TIMEOUT_MS,
            )
            accurate = _grapheme_text(live_page)
            assert "नमस्ते" in accurate, (
                f"grapheme cluster corrupted by the transport; buffer:\n{accurate}"
            )
        except Exception:
            _diag(live_page, "ghostty-live-grapheme-fail")
            raise


class TestLiveSessionEnd:
    """Closing the loop — the session ends cleanly from the UI."""

    def test_session_ends_and_state_clears(self, live_page, live_env) -> None:
        try:
            _start_session_through_ui(live_page, live_env, "Ghostty Live End")
            _await_agent_text(live_page, "FAKE-AGENT READY")

            ended = live_page.evaluate(
                """async () => {
                  const res = await fetch('/api/session/end', { method: 'POST' });
                  return { status: res.status, body: await res.json() };
                }"""
            )
            assert ended["status"] == 200, f"end failed: {ended!r}"
            assert ended["body"].get("ended") is True

            # State is cleared, so a fresh session could start.
            deadline = time.time() + 10
            state: dict = {}
            while time.time() < deadline:
                state = live_page.evaluate(
                    "async () => (await fetch('/api/session/state', { cache: 'no-store' })).json()"
                )
                if not state.get("study_session_id") or state.get("mode") == "ended":
                    break
                time.sleep(0.3)
            assert not state.get("study_session_id") or state.get("mode") == "ended", (
                f"session state not cleared after end: {state!r}"
            )
        except Exception:
            _diag(live_page, "ghostty-live-end-fail")
            raise
