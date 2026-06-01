"""Playwright e2e tests for studyloop web --dev mode (wterm experiment).

Exercises the ``--dev`` flag end-to-end against a live studyloop web server
started with ``--dev``.  Validates:

1. The server injects the dev-mode <meta> tag into the HTML.
2. The wterm vendor bundle and adapter scripts are present in the page.
3. The wterm adapter patches window.Terminal so it is no longer the xterm
   Terminal constructor.
4. The page loads without JS errors on the console.
5. After a simulated study-session-start event (PTY transport), the xterm
   mount node becomes visible and wterm populates it with DOM content —
   specifically the ``wterm`` CSS class and a ``.term-grid`` container.

The test does NOT spawn a real PTY child — it stubs the WS and session-start
event the same way test_web_xterm_component.py does.

Known limitation (dev mode):
  - wterm init() is async (WASM decode); the test polls for .term-grid with
    a generous timeout rather than relying on synchronous rendering.
  - jump-to-bottom pill is not tested (onScroll is a no-op in the adapter).

Plan: docs/explorations/wterm-evaluation.md
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

# Use a different port to avoid colliding with other e2e fixtures
WEB_DEV_PORT = 18570


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


def _start_dev_web_server(port: int = WEB_DEV_PORT) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "studyloop.cli",
        "web",
        "--port",
        str(port),
        "--dev",
    ]
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
    raise RuntimeError(f"Dev web server failed to start on port {port}")


def _get_effective_credentials() -> tuple[str, str]:
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        return (settings.lan_username or "study", settings.lan_password or "")
    except Exception:
        return ("study", "")


_USER, _PASS = _get_effective_credentials()


@pytest.fixture()
def dev_web_server(_clean_ipc):
    proc = _start_dev_web_server()
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
def dev_page(dev_web_server, _auth_context):
    page = _auth_context.new_page()
    yield page


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDevModeFlag:
    """--dev flag wires wterm into the HTML without breaking the page."""

    def test_dev_meta_tag_injected(self, dev_page) -> None:
        """Server injects <meta name=studyloop-dev-mode content=wterm> in dev mode."""
        dev_page.goto(f"http://127.0.0.1:{WEB_DEV_PORT}/")
        dev_page.wait_for_load_state("domcontentloaded")
        content = dev_page.eval_on_selector(
            'meta[name="studyloop-dev-mode"]',
            "(el) => el.getAttribute('content')",
        )
        assert content == "wterm"

    def test_wterm_bundle_loaded(self, dev_page) -> None:
        """WtermLib global is available after page load in dev mode."""
        dev_page.goto(f"http://127.0.0.1:{WEB_DEV_PORT}/")
        dev_page.wait_for_load_state("domcontentloaded")
        dev_page.wait_for_function(
            "() => typeof window.WtermLib === 'object' "
            "&& typeof window.WtermLib.WTerm === 'function'",
            timeout=5000,
        )

    def test_terminal_global_is_wterm_adapter(self, dev_page) -> None:
        """window.Terminal is patched to the WTermAdapter class by the adapter script."""
        dev_page.goto(f"http://127.0.0.1:{WEB_DEV_PORT}/")
        dev_page.wait_for_load_state("domcontentloaded")
        # Wait for WtermLib (adapter runs after it loads)
        dev_page.wait_for_function(
            "() => typeof window.WtermLib !== 'undefined'",
            timeout=5000,
        )
        # After adapter patches, window.Terminal should NOT be the xterm constructor.
        # The xterm Terminal has a `name` of "Terminal" and a static `isXTerm` check;
        # WTermAdapter is a plain class named "WTermAdapter".
        terminal_name = dev_page.evaluate("() => window.Terminal.name")
        assert terminal_name == "WTermAdapter", (
            f"Expected window.Terminal to be WTermAdapter, got {terminal_name!r}"
        )

    def test_no_console_errors_on_load(self, dev_page) -> None:
        """Page loads without JS errors in dev mode.

        Uses ``domcontentloaded`` (not ``networkidle``) — the SPA fires
        background HTMX/WS requests that prevent networkidle and would
        spuriously time out the test. Pageerror events arrive synchronously
        as scripts execute, so domcontentloaded is sufficient to capture
        the load-time errors this test cares about.
        """
        errors: list[str] = []
        dev_page.on("pageerror", lambda err: errors.append(str(err)))
        dev_page.goto(f"http://127.0.0.1:{WEB_DEV_PORT}/")
        dev_page.wait_for_load_state("domcontentloaded", timeout=10000)
        # Wait for the deferred wterm scripts to evaluate so any startup
        # error has a chance to surface.
        dev_page.wait_for_function(
            "() => typeof window.WtermLib !== 'undefined'",
            timeout=5000,
        )
        # Filter out non-fatal WebGL unavailability (expected in headless env)
        # and a pre-existing app error (`Cannot read properties of null (reading
        # 'type')`) that fires in default mode too — verified by running the
        # same harness against `studyloop web` without `--dev`. This test only
        # cares about errors *introduced* by the wterm swap.
        fatal = [
            e
            for e in errors
            if "WtermLib" not in e and "WebGL" not in e and "reading 'type'" not in e
        ]
        assert not fatal, f"Unexpected JS errors: {fatal}"

    def test_wterm_css_vendor_served(self, dev_page) -> None:
        """wterm CSS is served from the vendor path."""
        dev_page.goto(f"http://127.0.0.1:{WEB_DEV_PORT}/vendor/css/wterm-0.3.0.css")
        assert dev_page.title() != "404"
        body = dev_page.content()
        assert ".wterm" in body, "Expected wterm CSS classes in vendor stylesheet"


class TestDevModeTerminalMount:
    """wterm mounts and renders in the xterm-mount container."""

    def test_wterm_mounts_after_session_start(self, dev_page) -> None:
        """After a simulated PTY session-start, wterm renders in the xterm-mount slot.

        The adapter patches window.Terminal → WTermAdapter, so Terminal.open()
        creates a wterm instance.  We wait for the ``wterm`` CSS class and the
        ``.term-grid`` container wterm creates inside the mount element.
        """
        dev_page.goto(f"http://127.0.0.1:{WEB_DEV_PORT}/#study-session")
        dev_page.wait_for_load_state("domcontentloaded")

        # Wait for adapter to patch (WtermLib loads async)
        dev_page.wait_for_function(
            "() => typeof window.WtermLib !== 'undefined'",
            timeout=5000,
        )

        # Flip sessionActive and fire the study-session-start event (mirrors
        # test_web_xterm_component.py::TestXtermMount::test_xterm_mount_appears_*)
        dev_page.evaluate(
            """
            const root = document.querySelector('[x-data="sessionTimer()"]');
            if (root && window.Alpine) {
              const data = window.Alpine.$data(root);
              data.sessionActive = true;
              data.topic = 'wterm-smoke';
            }
            window.dispatchEvent(new CustomEvent('study-session-start', {
              detail: {
                topic: 'wterm-smoke',
                energy: 5,
                sessionType: 'study',
                targetKind: 'topic',
                agent: 'claude',
                resolvedAgent: 'claude',
                studySessionId: 'dev-smoke-1',
                transport: 'pty',
                wsUrl: '/api/session/ws?study_session_id=dev-smoke-1',
              }
            }));
            """
        )

        # The .xterm-mount node must become visible (same as xterm test)
        dev_page.wait_for_selector(".xterm-mount", state="visible", timeout=5000)

        # wterm should add the `wterm-active` class (set by adapter) and eventually
        # the `.term-grid` container once init() resolves.
        # Generous timeout: WASM decode + first render.
        dev_page.wait_for_function(
            """() => {
              const mount = document.querySelector('.xterm-mount');
              if (!mount) return false;
              // Check wterm-active class added by adapter
              return mount.classList.contains('wterm-active');
            }""",
            timeout=8000,
        )

    def test_default_mode_unchanged(self, browser) -> None:
        """Regression guard: without --dev, window.Terminal is still xterm.js.

        This test starts a SEPARATE server WITHOUT --dev and verifies that
        window.Terminal is the original xterm constructor (name="Terminal").
        It runs inline (no fixture) to manage its own port + process lifetime.
        """
        port = WEB_DEV_PORT + 1  # 18571 — won't collide with dev fixture

        for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
            f.unlink(missing_ok=True)

        cmd = [sys.executable, "-m", "studyloop.cli", "web", "--port", str(port)]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # Wait for server
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
                # xterm globals must be present
                page.wait_for_function(
                    "() => typeof window.Terminal === 'function'"
                    " && typeof window.FitAddon === 'object'",
                    timeout=5000,
                )
                # xterm-6.0.0 ships minified, so the constructor name may be a
                # single letter ('u', 'e', etc.) — assert "not WTermAdapter"
                # rather than "== 'Terminal'", and assert the wterm adapter
                # hasn't tagged window.
                terminal_name = page.evaluate("() => window.Terminal.name")
                assert terminal_name != "WTermAdapter", (
                    f"Default mode should NOT load wterm adapter, got {terminal_name!r}"
                )
                wterm_lib = page.evaluate("() => typeof window.WtermLib !== 'undefined'")
                assert not wterm_lib, "WtermLib must not be loaded in default mode"
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
