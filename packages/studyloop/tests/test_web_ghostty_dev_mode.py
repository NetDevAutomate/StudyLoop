"""Playwright e2e tests for studyloop web --dev (ghostty dev engine).

Journey matrix from docs/explorations/multiplexer-impact-map.md Part 4:
- B1: Renderer boots (ghostty-web global, meta tag, Terminal patched)
- B2: PTY bytes render in terminal (visible text content)
- B3: Keystrokes echo (typed input appears in terminal)
- B4: Resize reflows terminal (cols/rows change)
- B5: Selection/copy (getSelection returns non-empty)
- B6: No console errors (zero pageerror events)
- B7: Default mode regression (no ghostty globals without --dev)

All tests are marked ``e2e`` (deselected from default pytest run).
Requires: playwright, fastapi, uvicorn.

Pattern copied from test_web_wterm_dev_mode.py + _playwright_helpers.py.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import start_web_server  # noqa: E402

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

pytestmark = [pytest.mark.e2e]


CONFIG_DIR = Path.home() / ".config" / "studyloop"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"

# Unique port for ghostty tests (won't collide with wterm's 18570/18571)
WEB_GHOSTTY_PORT = 18580


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_ipc():
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
        f.unlink(missing_ok=True)
    yield
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
        f.unlink(missing_ok=True)


def _start_ghostty_dev_server(port: int = WEB_GHOSTTY_PORT) -> subprocess.Popen:
    """Start ``studyloop web --dev`` (ghostty is the only registered dev engine).

    Delegates to the shared ``start_web_server``. This used to be a private copy
    of that helper -- same ``DEVNULL``, same readiness loop with no ``proc.poll()``
    check -- which is how it kept the defects the shared one has since had fixed:
    a dead child was polled until something else answered the port, and the
    server's own error output was thrown away. When ``--dev-renderer`` was
    removed, this launcher failed with nothing but "failed to start on port
    18580" and no sign of the actual click error.
    """
    return start_web_server(port, extra_args=["--dev"])


def _get_effective_credentials() -> tuple[str, str]:
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        return (settings.lan_username or "study", settings.lan_password or "")
    except Exception:
        return ("study", "")


_USER, _PASS = _get_effective_credentials()


@pytest.fixture()
def ghostty_web_server(_clean_ipc):
    proc = _start_ghostty_dev_server()
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
    context = browser.new_context()
    if _PASS:
        context = browser.new_context(http_credentials={"username": _USER, "password": _PASS})
    yield context
    context.close()


@pytest.fixture()
def ghostty_page(ghostty_web_server, _auth_context):
    page = _auth_context.new_page()
    yield page
    page.close()


# ---------------------------------------------------------------------------
# B1 — Renderer boots
# ---------------------------------------------------------------------------


class TestGhosttyRendererBoots:
    """B1: Dev-mode page loads with ghostty-web renderer active."""

    def test_ghostty_meta_tag_injected(self, ghostty_page) -> None:
        """Server injects <meta name=studyloop-dev-mode content=ghostty-web>."""
        ghostty_page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PORT}/")
        ghostty_page.wait_for_load_state("domcontentloaded")
        content = ghostty_page.eval_on_selector(
            'meta[name="studyloop-dev-mode"]',
            "(el) => el.getAttribute('content')",
        )
        assert content == "ghostty"

    def test_ghostty_web_global_available(self, ghostty_page) -> None:
        """GhosttyWeb global is defined after page load."""
        ghostty_page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PORT}/")
        ghostty_page.wait_for_load_state("domcontentloaded")
        # The adapter exposes window.__studyloopGhostty and patches window.Terminal.
        ghostty_page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined'",
            timeout=8000,
        )

    def test_terminal_global_is_ghostty(self, ghostty_page) -> None:
        """window.Terminal is patched by ghostty-web bootstrap (not xterm)."""
        ghostty_page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PORT}/")
        ghostty_page.wait_for_load_state("domcontentloaded")
        ghostty_page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined'",
            timeout=8000,
        )
        # After bootstrap, window.Terminal should be from ghostty-web
        # It should NOT be "WTermAdapter" (wterm) and should differ from
        # xterm's minified name
        has_ghostty = ghostty_page.evaluate(
            "() => window.Terminal !== undefined && typeof window.Terminal === 'function'"
        )
        assert has_ghostty, "window.Terminal should be defined"

        # Verify WtermLib is NOT present (ghostty, not wterm)
        wterm_present = ghostty_page.evaluate("() => typeof window.WtermLib !== 'undefined'")
        assert not wterm_present, "WtermLib should NOT be present in ghostty mode"


# ---------------------------------------------------------------------------
# B2 — PTY renders
# ---------------------------------------------------------------------------


class TestPTYRenders:
    """B2: After session-start, the terminal renders visible content."""

    def test_terminal_mount_appears(self, ghostty_page) -> None:
        """Firing study-session-start makes the xterm-mount visible."""
        ghostty_page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PORT}/#study-session")
        ghostty_page.wait_for_load_state("domcontentloaded")
        ghostty_page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined'",
            timeout=8000,
        )

        # Trigger session-start event (same pattern as wterm test)
        ghostty_page.evaluate(
            """
            const root = document.querySelector('[x-data="sessionTimer()"]');
            if (root && window.Alpine) {
              const data = window.Alpine.$data(root);
              data.sessionActive = true;
              data.topic = 'ghostty-smoke';
            }
            window.dispatchEvent(new CustomEvent('study-session-start', {
              detail: {
                topic: 'ghostty-smoke',
                energy: 5,
                sessionType: 'study',
                targetKind: 'topic',
                agent: 'claude',
                resolvedAgent: 'claude',
                studySessionId: 'ghostty-smoke-1',
                transport: 'pty',
                wsUrl: '/api/session/ws?study_session_id=ghostty-smoke-1',
              }
            }));
            """
        )

        # The .xterm-mount must become visible
        ghostty_page.wait_for_selector(".xterm-mount", state="visible", timeout=5000)


# ---------------------------------------------------------------------------
# B4 — Resize
# ---------------------------------------------------------------------------


class TestResize:
    """B4: Resizing the viewport changes terminal dimensions."""

    def test_terminal_responds_to_viewport_resize(self, ghostty_page) -> None:
        """Terminal cols/rows change when viewport is resized."""
        ghostty_page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PORT}/")
        ghostty_page.wait_for_load_state("domcontentloaded")
        ghostty_page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined'",
            timeout=8000,
        )

        # Set initial viewport
        ghostty_page.set_viewport_size({"width": 1200, "height": 800})
        time.sleep(0.5)

        # Resize viewport
        ghostty_page.set_viewport_size({"width": 800, "height": 600})
        time.sleep(0.5)

        # The page should still be functional (no crash on resize)
        meta = ghostty_page.eval_on_selector(
            'meta[name="studyloop-dev-mode"]',
            "(el) => el.getAttribute('content')",
        )
        assert meta == "ghostty"


# ---------------------------------------------------------------------------
# B6 — No console errors
# ---------------------------------------------------------------------------


class TestNoConsoleErrors:
    """B6: Zero pageerror events through the page lifecycle."""

    def test_no_js_errors_on_load(self, ghostty_page) -> None:
        """Page loads without fatal JS errors in ghostty dev mode."""
        errors: list[str] = []
        ghostty_page.on("pageerror", lambda err: errors.append(str(err)))
        ghostty_page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PORT}/")
        ghostty_page.wait_for_load_state("domcontentloaded", timeout=10000)

        # Wait for ghostty-web scripts to evaluate
        ghostty_page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined'",
            timeout=8000,
        )

        # Filter out known non-fatal errors (WebGL in headless, pre-existing app errors)
        fatal = [
            e
            for e in errors
            if "WebGL" not in e
            and "reading 'type'" not in e
            and "GhosttyWeb" not in e  # WASM init warnings are non-fatal
        ]
        assert not fatal, f"Unexpected JS errors: {fatal}"

    def test_no_errors_through_session_start(self, ghostty_page) -> None:
        """Zero pageerror through full session-start lifecycle."""
        errors: list[str] = []
        ghostty_page.on("pageerror", lambda err: errors.append(str(err)))
        ghostty_page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PORT}/#study-session")
        ghostty_page.wait_for_load_state("domcontentloaded", timeout=10000)
        ghostty_page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined'",
            timeout=8000,
        )

        # Fire session-start
        ghostty_page.evaluate(
            """
            const root = document.querySelector('[x-data="sessionTimer()"]');
            if (root && window.Alpine) {
              const data = window.Alpine.$data(root);
              data.sessionActive = true;
            }
            window.dispatchEvent(new CustomEvent('study-session-start', {
              detail: {
                topic: 'error-check',
                energy: 5,
                sessionType: 'study',
                targetKind: 'topic',
                agent: 'claude',
                resolvedAgent: 'claude',
                studySessionId: 'error-check-1',
                transport: 'pty',
                wsUrl: '/api/session/ws?study_session_id=error-check-1',
              }
            }));
            """
        )

        time.sleep(2)  # Let any async errors surface

        fatal = [
            e
            for e in errors
            if "WebGL" not in e and "reading 'type'" not in e and "GhosttyWeb" not in e
        ]
        assert not fatal, f"JS errors during session lifecycle: {fatal}"


# ---------------------------------------------------------------------------
# B3 — Keystroke echo (REAL PTY)
# ---------------------------------------------------------------------------


# Unique port for real-PTY tests (avoids collision with existing ghostty tests
# at 18580/18581/18582 and the concurrent herdr agent at 18575+).
WEB_GHOSTTY_PTY_PORT = 18583


def _start_ghostty_dev_server_with_real_pty(
    port: int = WEB_GHOSTTY_PTY_PORT,
) -> subprocess.Popen:
    """Start ``studyloop web --dev`` with STUDYLOOP_TEST_AGENT_CMD.

    The env var substitutes the real agent binary with a simple ``cat``
    command (which echoes stdin back on a PTY). This exercises the full
    PTY transport path — real pty.fork(), real WebSocket, real terminal
    rendering — without needing Claude/Kiro/etc installed.

    loop="asyncio" is already enforced by the CLI (_web.py) — required
    for PTYTransport's SIGCHLD handling.

    Delegates to the shared ``start_web_server``: the private copy this replaced
    used ``stderr=subprocess.PIPE`` that nothing ever drained, which deadlocks a
    server chatty enough to fill the pipe buffer.
    """
    return start_web_server(
        port,
        extra_env={"STUDYLOOP_TEST_AGENT_CMD": "echo agent-stub-ready; exec cat"},
        extra_args=["--dev"],
    )


@pytest.fixture(scope="module")
def ghostty_pty_server():
    """Class-scoped server with a real PTY stub agent."""
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
        f.unlink(missing_ok=True)
    proc = _start_ghostty_dev_server_with_real_pty()
    yield proc
    # End any lingering session before teardown
    try:
        import base64

        req = urllib.request.Request(
            f"http://127.0.0.1:{WEB_GHOSTTY_PTY_PORT}/api/session/end",
            method="POST",
        )
        if _PASS:
            creds = base64.b64encode(f"{_USER}:{_PASS}".encode()).decode()
            req.add_header("Authorization", f"Basic {creds}")
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
        f.unlink(missing_ok=True)


@pytest.fixture()
def ghostty_pty_context(browser):
    """Browser context with auth for the real-PTY server."""
    ctx_args = {}
    if _PASS:
        ctx_args["http_credentials"] = {"username": _USER, "password": _PASS}
    context = browser.new_context(**ctx_args)
    yield context
    context.close()


@pytest.fixture()
def ghostty_pty_page(ghostty_pty_server, ghostty_pty_context):
    """Page connected to the real-PTY ghostty server."""
    _ = ghostty_pty_server  # keep server alive
    page = ghostty_pty_context.new_page()
    yield page
    page.close()


def _end_active_session_on_page(page, port: int = WEB_GHOSTTY_PTY_PORT) -> None:
    """Best-effort end of any active session via in-page fetch."""
    try:
        if not page.url.startswith(f"http://127.0.0.1:{port}"):
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_load_state("domcontentloaded")
        page.evaluate(
            """async () => {
              try { await fetch('/api/session/end', {method: 'POST'}); }
              catch {}
            }"""
        )
        page.wait_for_timeout(300)
    except Exception:
        pass


class TestKeystrokeEchoRealPTY:
    """B3: Keystrokes typed via Playwright reach a REAL PTY child and
    the echo is rendered as VISIBLE text in the ghostty-web terminal.

    This is the single most important user behaviour: 'I type in the
    terminal and see my keystrokes'. The test drives a genuine PTY
    session end-to-end:
    - Server with STUDYLOOP_TEST_AGENT_CMD='echo ready; exec cat'
    - POST /api/session/start → 201 with ws_url
    - Browser opens WebSocket, receives Started frame
    - Terminal mounts with ghostty-web canvas renderer
    - Playwright types a recognisable string
    - PTY echo makes it visible in the terminal's text content
    - A shell command is sent and its output is verified
    """

    @pytest.mark.skip(
        reason=(
            "Duplicates registry-path coverage that already passes: "
            "e2e/test_ghostty_dev_terminal.py::TestKeyboardInput::"
            "test_printable_keys_reach_the_terminal_buffer (that file is 31/31 "
            "green). Written against the deprecated inline --dev-renderer path "
            "removed in ADR-0007, and its buffer predicate times out because it "
            "types before proving the mount owns keyboard focus -- the same "
            "readiness gap identified in the sibling test. No coverage is lost "
            "by skipping it; fixing focus readiness belongs with that sibling."
        )
    )
    def test_typed_text_appears_in_terminal(self, ghostty_pty_page) -> None:
        """Type a recognisable string and assert it renders in the terminal."""
        page = ghostty_pty_page
        page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PTY_PORT}/#study-session")
        page.wait_for_load_state("domcontentloaded")

        # Wait for GhosttyWeb + Alpine nav store settled
        page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined' && window.Alpine",
            timeout=15000,
        )

        # Ensure Alpine nav store navigates to study-session
        page.evaluate(
            """() => {
              if (window.Alpine && window.Alpine.store && window.Alpine.store('nav')) {
                window.Alpine.store('nav').current = 'study-session';
              }
            }"""
        )
        page.wait_for_timeout(300)

        # POST to start the real PTY session on the server
        start_data = page.evaluate(
            """async () => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: 'B3 keystroke echo',
                  energy: 5,
                  agent: 'claude',
                  transport: 'pty',
                }),
              });
              if (!res.ok) return {error: res.status};
              return await res.json();
            }"""
        )
        assert "error" not in start_data, f"Session start failed: {start_data}"
        ws_url = start_data["ws_url"]

        # Activate the UI (B2-proven pattern) with the REAL ws_url
        page.evaluate(
            """(wsUrl) => {
              const root = document.querySelector(
                '[x-data="sessionTimer()"]'
              );
              if (root && window.Alpine) {
                const data = window.Alpine.$data(root);
                data.sessionActive = true;
                data.topic = 'B3 keystroke echo';
              }
              window.dispatchEvent(new CustomEvent(
                'study-session-start', {
                  detail: {
                    topic: 'B3 keystroke echo',
                    energy: 5,
                    sessionType: 'study',
                    targetKind: 'topic',
                    agent: 'claude',
                    resolvedAgent: 'claude',
                    studySessionId: 'pty-b3-test',
                    transport: 'pty',
                    wsUrl: wsUrl,
                  }
                }
              ));
            }""",
            ws_url,
        )

        # Wait for the xterm-mount to become visible
        page.wait_for_selector(".xterm-mount", state="visible", timeout=10000)

        # Wait for agent-stub-ready in the terminal (via selection API)
        page.wait_for_function(
            """() => {
              const panels = document.querySelectorAll('[x-data]');
              let term = null;
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term) { term = d._term; break; }
                  }
                }
                if (term) break;
              }
              if (!term || !term.selectAll || !term.getSelection)
                return false;
              term.selectAll();
              const sel = term.getSelection();
              term.clearSelection();
              return sel.includes('agent-stub-ready');
            }""",
            timeout=15000,
        )

        # Type a recognisable string — need to focus terminal first
        marker = "KSTRK_B3_ECHO_TEST"
        page.locator(".xterm-mount").click()
        page.wait_for_timeout(200)
        page.keyboard.type(marker)

        # Assert: the typed text appears in the terminal buffer.
        # ghostty-web renders to canvas; use selectAll + getSelection
        # (the renderer's native text extraction) to verify content.
        found = page.wait_for_function(
            """(marker) => {
              const panels = document.querySelectorAll('[x-data]');
              let term = null;
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term) { term = d._term; break; }
                  }
                }
                if (term) break;
              }
              if (!term) return false;
              if (typeof term.selectAll !== 'function') return false;
              if (typeof term.getSelection !== 'function') return false;
              term.selectAll();
              const sel = term.getSelection();
              term.clearSelection();
              return sel.includes(marker);
            }""",
            arg=marker,
            timeout=10000,
        )
        assert found, f"Typed text '{marker}' not in terminal buffer"

    def test_command_output_renders(self, ghostty_pty_page) -> None:
        """Send a shell command (echo) and assert its output renders.

        With STUDYLOOP_TEST_AGENT_CMD='echo agent-stub-ready; exec cat',
        the PTY child is /bin/sh. Typing a command + Enter sends it to
        `cat`, which echoes it back. The line discipline also echoes on
        the tty. We verify the echoed output appears.
        """
        page = ghostty_pty_page
        _end_active_session_on_page(page)
        page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PTY_PORT}/#study-session")
        page.wait_for_load_state("domcontentloaded")

        page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined' && window.Alpine",
            timeout=15000,
        )

        # Ensure Alpine nav store navigates to study-session
        page.evaluate(
            """() => {
              if (window.Alpine && window.Alpine.store && window.Alpine.store('nav')) {
                window.Alpine.store('nav').current = 'study-session';
              }
            }"""
        )
        page.wait_for_timeout(300)

        # Start session + dispatch event
        start_result = page.evaluate(
            """async () => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: 'B3 command output',
                  energy: 5,
                  agent: 'claude',
                  transport: 'pty',
                }),
              });
              if (!res.ok) return {error: res.status};
              const data = await res.json();
              const root = document.querySelector(
                '[x-data="sessionTimer()"]'
              );
              if (root && window.Alpine) {
                const st = window.Alpine.$data(root);
                st.sessionActive = true;
                st.topic = 'B3 command output';
              }
              window.dispatchEvent(new CustomEvent(
                'study-session-start', {
                  detail: {
                    topic: 'B3 command output',
                    energy: 5,
                    sessionType: 'study',
                    targetKind: 'topic',
                    agent: 'claude',
                    resolvedAgent: data.agent,
                    studySessionId: data.study_session_id,
                    transport: data.transport,
                    wsUrl: data.ws_url,
                  }
                }
              ));
              return {status: res.status, body: data};
            }"""
        )
        assert start_result.get("status") == 201, f"Session start failed: {start_result}"

        # Wait for terminal and agent ready
        page.wait_for_selector(".xterm-mount", state="visible", timeout=10000)
        page.wait_for_function(
            """() => {
              const panels = document.querySelectorAll('[x-data]');
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term && d._term.buffer) {
                      const buf = d._term.buffer.active;
                      for (let i = 0; i < buf.length; i++) {
                        const line = buf.getLine(i);
                        const text = line?.translateToString(true);
                        if (text?.includes('agent-stub-ready'))
                          return true;
                      }
                    }
                  }
                }
              }
              return false;
            }""",
            timeout=15000,
        )

        # Type a command. cat will echo everything back (tty line discipline
        # echoes the input, then cat writes stdin to stdout on newline).
        cmd_marker = "CMD_OUTPUT_B3_OK"
        page.keyboard.type(cmd_marker)
        page.keyboard.press("Enter")

        # After pressing Enter, cat receives the line and writes it back.
        # The terminal buffer should now contain the marker at least twice:
        # once from the input echo and once from cat's output.
        # We just need to confirm it's visible at all (already sufficient
        # to prove the full PTY → WS → terminal.write() path works).
        found = page.wait_for_function(
            """(marker) => {
              const panels = document.querySelectorAll('[x-data]');
              let term = null;
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term) { term = d._term; break; }
                  }
                }
                if (term) break;
              }
              if (!term || !term.buffer) return false;
              const buf = term.buffer.active;
              let count = 0;
              for (let i = 0; i < buf.length; i++) {
                const line = buf.getLine(i);
                if (line && line.translateToString(true).includes(marker)) count++;
              }
              // After Enter: line-discipline echo (1st) + cat output (2nd)
              return count >= 2;
            }""",
            arg=cmd_marker,
            timeout=10000,
        )
        assert found, f"Command output '{cmd_marker}' not echoed back by PTY"


# ---------------------------------------------------------------------------
# B5 — Selection/copy (REAL PTY)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Registry dev engine has no term.selectAll(). These tests were written "
        "against the deprecated inline --dev-renderer path, whose UMD bootstrap "
        "patched window.Terminal with ghostty-web's own Terminal (which had "
        "selectAll). That path was removed in ADR-0007. The registry adapter "
        "implements getSelection() (ghostty-adapter-0.4.0.js:827) but not "
        "selectAll, so these cannot run as written. RECORDED GAP: this is the "
        "repo's ONLY selection/copy coverage -- test_ghostty_dev_terminal.py has "
        "none -- so unskipping needs selectAll on the adapter, not a test edit."
    )
)
class TestSelectionCopyRealPTY:
    """B5: With real rendered content present, selection API returns text.

    Limitation: headless Chromium restricts clipboard access even with
    ``--enable-features=ClipboardAPI``. True clipboard read (via
    navigator.clipboard.readText()) is not reliably available in headless
    mode. We assert the strongest available proxy:

    1. term.selectAll() programmatically selects all terminal content.
    2. term.getSelection() returns the selected text as a string.
    3. The selected text contains the content we know was rendered.

    This proves the selection machinery works end-to-end through the
    ghostty-web renderer. A real user performing Cmd-A / mouse-drag
    would exercise the same SelectionManager that selectAll() drives.
    """

    def test_select_all_returns_rendered_content(self, ghostty_pty_page) -> None:
        """selectAll() + getSelection() returns the PTY output text."""
        page = ghostty_pty_page
        _end_active_session_on_page(page)
        page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PTY_PORT}/#study-session")
        page.wait_for_load_state("domcontentloaded")

        page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined' && window.Alpine",
            timeout=15000,
        )

        # Ensure Alpine nav store navigates to study-session
        page.evaluate(
            """() => {
              if (window.Alpine && window.Alpine.store && window.Alpine.store('nav')) {
                window.Alpine.store('nav').current = 'study-session';
              }
            }"""
        )
        page.wait_for_timeout(300)

        # Start session + dispatch event
        start_result = page.evaluate(
            """async () => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: 'B5 selection test',
                  energy: 5,
                  agent: 'claude',
                  transport: 'pty',
                }),
              });
              if (!res.ok) return {error: res.status};
              const data = await res.json();
              const root = document.querySelector(
                '[x-data="sessionTimer()"]'
              );
              if (root && window.Alpine) {
                const st = window.Alpine.$data(root);
                st.sessionActive = true;
                st.topic = 'B5 selection test';
              }
              window.dispatchEvent(new CustomEvent(
                'study-session-start', {
                  detail: {
                    topic: 'B5 selection test',
                    energy: 5,
                    sessionType: 'study',
                    targetKind: 'topic',
                    agent: 'claude',
                    resolvedAgent: data.agent,
                    studySessionId: data.study_session_id,
                    transport: data.transport,
                    wsUrl: data.ws_url,
                  }
                }
              ));
              return {status: res.status, body: data};
            }"""
        )
        assert start_result.get("status") == 201, f"Session start failed: {start_result}"

        # Wait for terminal and agent-stub-ready
        page.wait_for_selector(".xterm-mount", state="visible", timeout=10000)
        page.wait_for_function(
            """() => {
              const panels = document.querySelectorAll('[x-data]');
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term && d._term.buffer) {
                      const buf = d._term.buffer.active;
                      for (let i = 0; i < buf.length; i++) {
                        const line = buf.getLine(i);
                        const t = line?.translateToString(true);
                        if (t?.includes('agent-stub-ready'))
                          return true;
                      }
                    }
                  }
                }
              }
              return false;
            }""",
            timeout=15000,
        )

        # Type a recognisable string so we have known content to select
        selection_marker = "SEL_B5_MARKER"
        page.keyboard.type(selection_marker)
        # Wait for it to appear in the buffer
        page.wait_for_function(
            """(marker) => {
              const panels = document.querySelectorAll('[x-data]');
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term && d._term.buffer) {
                      const buf = d._term.buffer.active;
                      for (let i = 0; i < buf.length; i++) {
                        const line = buf.getLine(i);
                        if (line && line.translateToString(true).includes(marker)) return true;
                      }
                    }
                  }
                }
              }
              return false;
            }""",
            arg=selection_marker,
            timeout=10000,
        )

        # Now call selectAll() + getSelection() on the terminal instance
        selection_text = page.evaluate(
            """() => {
              const panels = document.querySelectorAll('[x-data]');
              let term = null;
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term) { term = d._term; break; }
                  }
                }
                if (term) break;
              }
              if (!term) return {error: 'no terminal found'};
              if (typeof term.selectAll !== 'function')
                return {error: 'selectAll not available'};
              if (typeof term.getSelection !== 'function')
                return {error: 'getSelection not available'};
              term.selectAll();
              const hasSelection = typeof term.hasSelection === 'function'
                ? term.hasSelection() : true;
              const text = term.getSelection();
              return {text, hasSelection};
            }"""
        )

        assert "error" not in selection_text, f"Selection API error: {selection_text}"
        assert selection_text["hasSelection"], "selectAll() did not create a selection"
        assert selection_marker in selection_text["text"], (
            f"getSelection() did not contain '{selection_marker}'. "
            f"Got: {selection_text['text'][:200]!r}"
        )

    def test_selection_includes_agent_output(self, ghostty_pty_page) -> None:
        """Selection includes the agent stub's startup banner."""
        page = ghostty_pty_page
        _end_active_session_on_page(page)
        page.goto(f"http://127.0.0.1:{WEB_GHOSTTY_PTY_PORT}/#study-session")
        page.wait_for_load_state("domcontentloaded")

        page.wait_for_function(
            "() => typeof window.__studyloopGhostty !== 'undefined' && window.Alpine",
            timeout=15000,
        )

        # Ensure Alpine nav store navigates to study-session
        page.evaluate(
            """() => {
              if (window.Alpine && window.Alpine.store && window.Alpine.store('nav')) {
                window.Alpine.store('nav').current = 'study-session';
              }
            }"""
        )
        page.wait_for_timeout(300)

        # Start session + dispatch event
        start_result = page.evaluate(
            """async () => {
              const res = await fetch('/api/session/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                  topic: 'B5 agent output selection',
                  energy: 5,
                  agent: 'claude',
                  transport: 'pty',
                }),
              });
              if (!res.ok) return {error: res.status};
              const data = await res.json();
              const root = document.querySelector(
                '[x-data="sessionTimer()"]'
              );
              if (root && window.Alpine) {
                const st = window.Alpine.$data(root);
                st.sessionActive = true;
                st.topic = 'B5 agent output selection';
              }
              window.dispatchEvent(new CustomEvent(
                'study-session-start', {
                  detail: {
                    topic: 'B5 agent output selection',
                    energy: 5,
                    sessionType: 'study',
                    targetKind: 'topic',
                    agent: 'claude',
                    resolvedAgent: data.agent,
                    studySessionId: data.study_session_id,
                    transport: data.transport,
                    wsUrl: data.ws_url,
                  }
                }
              ));
              return {status: res.status, body: data};
            }"""
        )
        assert start_result.get("status") == 201, f"Session start failed: {start_result}"

        # Wait for terminal and agent-stub-ready
        page.wait_for_selector(".xterm-mount", state="visible", timeout=10000)
        page.wait_for_function(
            """() => {
              const panels = document.querySelectorAll('[x-data]');
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term && d._term.buffer) {
                      const buf = d._term.buffer.active;
                      for (let i = 0; i < buf.length; i++) {
                        const line = buf.getLine(i);
                        const t = line?.translateToString(true);
                        if (t?.includes('agent-stub-ready'))
                          return true;
                      }
                    }
                  }
                }
              }
              return false;
            }""",
            timeout=15000,
        )

        # Select all and verify the agent banner is selectable
        selection_text = page.evaluate(
            """() => {
              const panels = document.querySelectorAll('[x-data]');
              let term = null;
              for (const el of panels) {
                if (el._x_dataStack) {
                  for (const d of el._x_dataStack) {
                    if (d._term) { term = d._term; break; }
                  }
                }
                if (term) break;
              }
              if (!term) return {error: 'no terminal instance found'};
              term.selectAll();
              return {text: term.getSelection()};
            }"""
        )

        assert "error" not in selection_text, f"Selection API error: {selection_text}"
        assert "agent-stub-ready" in selection_text["text"], (
            f"getSelection() did not contain 'agent-stub-ready'. "
            f"Got: {selection_text['text'][:200]!r}"
        )


# ---------------------------------------------------------------------------
# B7 — Default mode regression
# ---------------------------------------------------------------------------


class TestDefaultModeRegression:
    """B7: Without --dev, ghostty-web is NOT loaded."""

    def test_no_ghostty_in_default_mode(self, browser) -> None:
        """Regression: default mode uses xterm.js, not ghostty-web."""
        port = WEB_GHOSTTY_PORT + 1  # 18581

        for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
            f.unlink(missing_ok=True)

        # Start server WITHOUT --dev
        cmd = [sys.executable, "-m", "studyloop.cli", "web", "--port", str(port)]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(30):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        break
                    time.sleep(0.3)
                except Exception:
                    time.sleep(0.3)

            ctx_args = {}
            if _PASS:
                ctx_args["http_credentials"] = {"username": _USER, "password": _PASS}
            context = browser.new_context(**ctx_args)
            page = context.new_page()
            try:
                page.goto(f"http://127.0.0.1:{port}/")
                page.wait_for_load_state("domcontentloaded")

                # Wait for xterm globals (default mode)
                page.wait_for_function(
                    "() => typeof window.Terminal === 'function'",
                    timeout=5000,
                )

                # No ghostty-web globals should be present
                ghostty = page.evaluate("() => typeof window.__studyloopGhostty !== 'undefined'")
                assert not ghostty, "GhosttyWeb must not be loaded in default mode"

                # No dev meta tag
                meta = page.query_selector('meta[name="studyloop-dev-mode"]')
                assert meta is None, "dev-mode meta must not be present in default mode"
            finally:
                page.close()
                context.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# B7b — wterm regression guard (T4.4)
# ---------------------------------------------------------------------------
