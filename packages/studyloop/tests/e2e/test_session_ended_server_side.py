"""A view whose session ended server-side must return to its picker.

Reported 2026-10-11: "when starting studyloop web, in the Body Double session
the option to start a session has disappeared, only a pomodoro timer".
Reproduced against the real server: a Body Double tab that was mid-session when
`studyloop web` was re-run kept its live strip (Pomodoro timer, End button) over
a console reading "Disconnected", with the picker hidden. The parent view only
ever left its live layout on its own End button; the console learned the
session was over (a ``stopped`` frame, or the socket dying with the server) and
told nobody. The Study view had the identical gap.

The fix is one event, ``study-session-ended``, dispatched by the console and
answered by whichever view owns that origin (ADR-0002). These journeys drive
the two ways a session ends under a live tab, against the REAL server and the
harness agent, and assert the picker is back with the activity still typed in,
so the next Start is one click.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_session_ended_server_side.py -m e2e
"""

from __future__ import annotations

import contextlib
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import start_web_server  # noqa: E402

if TYPE_CHECKING:
    import subprocess

    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

#: Keeps the agent alive until its stdin closes; EOF on stdin is the exit.
_AGENT_CMD = "echo agent-stub-ready; exec cat"

BD_ROOT = '[x-data="bodyDoubleSession()"]'
BD_CONSOLE = ".bd-console-panel .agent-console"
STUDY_ROOT = '[x-data="sessionTimer()"]'
STUDY_CONSOLE = ".session-active-layout .agent-console"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _World:
    """One hermetic server the test can stop and start again on the same port."""

    def __init__(self, root: Path) -> None:
        session_dir = root / "session-ipc"
        session_dir.mkdir(parents=True, exist_ok=True)
        config = root / "config.yaml"
        config.write_text(f"session_db: {root / 'sessions.db'}\n", encoding="utf-8")
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.env = {
            "STUDYLOOP_CONFIG": str(config),
            "STUDYLOOP_SESSION_DIR": str(session_dir),
            "STUDYLOOP_PLANS_DIR": str(root / "study-plans"),
            "STUDYLOOP_TEST_AGENT_CMD": _AGENT_CMD,
        }
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = start_web_server(self.port, extra_env=self.env)

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except Exception:  # pragma: no cover - defensive
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.proc = None

    def restart(self) -> None:
        """What a learner's re-run `studyloop web` does to an open tab."""
        self.stop()
        time.sleep(0.5)
        self.start()


@pytest.fixture()
def world(tmp_path: Path):
    w = _World(tmp_path)
    w.start()
    try:
        yield w
    finally:
        with contextlib.suppress(Exception):
            _post(w.base_url, "/api/session/end", {})
        w.stop()


@pytest.fixture()
def page(world: _World, browser):
    context = browser.new_context(viewport={"width": 1500, "height": 1000})
    pg = context.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    pg._studyloop_errors = errors
    yield pg
    context.close()


def _post(base_url: str, path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read().decode()
            return res.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        return exc.code, (json.loads(raw) if raw else {})


def _data(page: Page, root: str, *fields: str) -> dict:
    return page.evaluate(
        """([root, fields]) => {
          const d = window.Alpine.$data(document.querySelector(root));
          return Object.fromEntries(fields.map((f) => [f, d[f]]));
        }""",
        [root, list(fields)],
    )


def _wait_connected(page: Page, console: str) -> None:
    page.wait_for_function(
        """(sel) => {
          const el = document.querySelector(sel);
          return !!el && /^Connected/.test(window.Alpine.$data(el).status);
        }""",
        arg=console,
        timeout=20_000,
    )


def _exit_the_agent(page: Page, console: str) -> None:
    """EOF on the agent's stdin, through the console's own socket: `cat` exits,
    the PTY transport reports Stopped(exit, rc=0), the server sends the
    ``stopped`` frame. The real agent-exit path, minus a keyboard."""
    page.evaluate(
        """(sel) => {
          const c = window.Alpine.$data(document.querySelector(sel));
          c._ws.send(JSON.stringify({ type: 'input', data: '\\u0004' }));
        }""",
        console,
    )


def _wait_idle(page: Page, root: str) -> None:
    page.wait_for_function(
        "(root) => window.Alpine.$data(document.querySelector(root)).sessionActive === false",
        arg=root,
        timeout=30_000,
    )


# ---------------------------------------------------------------------------
# Body Double
# ---------------------------------------------------------------------------


def _start_body_double(page: Page, world: _World) -> None:
    page.goto(f"{world.base_url}/#body-double")
    page.wait_for_function(
        "() => !!window.Alpine && window.Alpine.$data("
        f"document.querySelector('{BD_ROOT}'))._initDone",
        timeout=15_000,
    )
    page.fill("#bd-activity-input", "Window functions")
    page.select_option("#bd-agent-select", "codex")
    page.click("#bd-start-session")
    _wait_connected(page, BD_CONSOLE)
    assert _data(page, BD_ROOT, "sessionActive")["sessionActive"] is True
    assert not page.locator(".bd-start-picker").is_visible()


class TestBodyDoubleEndedServerSide:
    def test_agent_exit_returns_the_picker_with_the_activity_kept(
        self, world: _World, page: Page
    ) -> None:
        _start_body_double(page, world)

        _exit_the_agent(page, BD_CONSOLE)
        _wait_idle(page, BD_ROOT)

        picker = page.locator(".bd-start-picker")
        picker.wait_for(state="visible", timeout=5_000)
        notice = page.locator("#bd-session-ended")
        notice.wait_for(state="visible", timeout=5_000)
        assert "Your session ended (exit, rc=0)" in (notice.text_content() or "")
        # The live layout is gone, not merely emptied.
        assert not page.locator(".bd-live-section").is_visible()
        assert not page.locator("#bd-end-confirm").is_visible()
        # One click from a new session: the activity and agent survive the end.
        assert page.input_value("#bd-activity-input") == "Window functions"
        assert page.input_value("#bd-agent-select") == "codex"
        assert page.locator("#bd-start-session").is_enabled()
        assert getattr(page, "_studyloop_errors", []) == []

    def test_server_restart_under_a_live_tab_returns_the_picker(
        self, world: _World, page: Page
    ) -> None:
        """The reported journey: `studyloop web` re-run with this tab open."""
        _start_body_double(page, world)

        world.restart()
        _wait_idle(page, BD_ROOT)

        page.locator(".bd-start-picker").wait_for(state="visible", timeout=5_000)
        notice = page.locator("#bd-session-ended")
        notice.wait_for(state="visible", timeout=5_000)
        text = notice.text_content() or ""
        assert "Your session ended" in text
        assert "was studyloop web restarted?" in text
        assert page.input_value("#bd-activity-input") == "Window functions"
        assert page.locator("#bd-start-session").is_enabled()
        assert getattr(page, "_studyloop_errors", []) == []

    def test_the_notice_clears_on_the_next_start(self, world: _World, page: Page) -> None:
        _start_body_double(page, world)
        _exit_the_agent(page, BD_CONSOLE)
        _wait_idle(page, BD_ROOT)
        page.locator("#bd-session-ended").wait_for(state="visible", timeout=5_000)

        page.click("#bd-start-session")
        _wait_connected(page, BD_CONSOLE)

        assert _data(page, BD_ROOT, "sessionActive", "endedNotice") == {
            "sessionActive": True,
            "endedNotice": "",
        }

    def test_a_learner_ending_the_session_sees_no_notice(self, world: _World, page: Page) -> None:
        """The learner's own End is not an ending to explain. The console closes
        its socket on the stop event; that close must not be read as a loss."""
        _start_body_double(page, world)

        page.click("#bd-end-session")
        page.click("#bd-end-confirm-yes")
        _wait_idle(page, BD_ROOT)
        page.locator(".bd-start-picker").wait_for(state="visible", timeout=5_000)
        # Give a wrongly-triggered probe every chance to land before asserting.
        page.wait_for_timeout(1_500)

        assert _data(page, BD_ROOT, "endedNotice")["endedNotice"] == ""
        assert not page.locator("#bd-session-ended").is_visible()


# ---------------------------------------------------------------------------
# Study Session — the twin
# ---------------------------------------------------------------------------


class TestStudyViewEndedServerSide:
    def test_agent_exit_returns_the_picker(self, world: _World, page: Page) -> None:
        status, body = _post(
            world.base_url,
            "/api/session/start",
            {
                "topic": "Decorators",
                "energy": 5,
                "agent": "codex",
                "transport": "pty",
                "origin": "study",
            },
        )
        assert status == 201, body
        page.goto(f"{world.base_url}/#study-session")
        page.wait_for_function(
            "() => !!window.Alpine && window.Alpine.$data("
            f"document.querySelector('{STUDY_ROOT}')).sessionActive === true",
            timeout=15_000,
        )
        _wait_connected(page, STUDY_CONSOLE)

        _exit_the_agent(page, STUDY_CONSOLE)
        _wait_idle(page, STUDY_ROOT)

        page.locator(".study-start-picker").wait_for(state="visible", timeout=5_000)
        notice = page.locator("#study-session-ended")
        notice.wait_for(state="visible", timeout=5_000)
        assert "Your session ended (exit, rc=0)" in (notice.text_content() or "")
        assert _data(page, STUDY_ROOT, "topic")["topic"] == "Session ended"
        assert getattr(page, "_studyloop_errors", []) == []
