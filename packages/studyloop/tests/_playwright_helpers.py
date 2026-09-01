"""Shared fixtures + utilities for Playwright UI tests (plan Test Strategy).

Not a pytest conftest — studyloop's ``tests/`` has no ``__init__.py`` so
plugin-level conftests collide with pluggy. Test files import the
helpers explicitly, following the precedent set in
``test_web_terminal.py`` and ``test_web_xterm_component.py``.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from playwright.sync_api import Browser, BrowserContext, Page


CONFIG_DIR = Path.home() / ".config" / "studyloop"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"


def start_web_server(
    port: int,
    extra_env: dict[str, str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | str | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.Popen:
    """Spin up ``studyloop web`` on the given port. Returns the proc.

    Blocks until the server responds on ``/`` (or returns 401 when
    password protection is configured — still "up").

    Two mutually exclusive ways to give the child an environment:

    ``extra_env`` is merged *over* the inherited environment — the original
    contract, used by the older ``test_web_*`` modules and by the journey to
    inject the source-test agent command while selecting a release adapter.

    ``env`` replaces the environment *verbatim*, inheriting nothing. The e2e
    harness (``e2e/_env.py``) builds a complete ``TestWorld`` environment this
    way so a run cannot read or clobber the developer's real HOME, config,
    session DB or study plans. Passing both is a caller error, because the
    merge semantics would silently defeat that isolation.

    ``cwd`` sets the child's working directory (the world root, so relative
    paths resolve inside the temp world rather than the repo).

    ``extra_args`` is appended to the ``studyloop web`` command line — used to
    select an experimental terminal renderer, e.g. ``["--dev"]`` or
    ``["--dev-engine", "ghostty"]``.
    """
    import os

    if env is not None and extra_env is not None:
        msg = (
            "start_web_server: pass either env (complete, hermetic) or "
            "extra_env (merged over os.environ), not both"
        )
        raise ValueError(msg)

    # Pre-flight: refuse to start if something is ALREADY serving this port.
    #
    # The readiness probe below cannot tell our child's response from another
    # process's. If a previous server leaked or two test files declare the same
    # port, the probe would accept the stranger's 200, hand back our (about to
    # die) child, and the test would drive the wrong server — passing or failing
    # for reasons that have nothing to do with it. Failing here names the real
    # problem instead.
    if not _port_is_free(port):
        msg = (
            f"port {port} is already being served before the child started. "
            "Either a previous server leaked, or two test modules declare this "
            "same port (see test_port_uniqueness). Refusing to continue: the "
            "readiness probe cannot distinguish that server from ours."
        )
        raise RuntimeError(msg)

    child_env = dict(env) if env is not None else {**os.environ, **(extra_env or {})}
    cmd = [sys.executable, "-m", "studyloop.cli", "web", "--port", str(port)]
    if extra_args:
        cmd.extend(extra_args)

    # Capture the child's output to a file rather than discarding it.
    #
    # This used to be stderr=DEVNULL, which threw away every server-side
    # traceback. Two separate defects in this repo were diagnosable only from
    # output that had already been destroyed here: an "Errno 48 address already
    # in use" bind failure, and an HTTP 500 on /api/backlog whose traceback was
    # unrecoverable. A file (not a PIPE) because nobody drains a PIPE and a
    # chatty server would deadlock on a full buffer.
    log_fd, log_path = tempfile.mkstemp(prefix=f"studyloop-web-{port}-", suffix=".log")
    log_file = os.fdopen(log_fd, "w")

    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=child_env,
        cwd=None if cwd is None else str(cwd),
    )
    # Discoverable by tests and by a failing teardown.
    proc.studyloop_log_path = log_path  # type: ignore[attr-defined]

    def _fail(reason: str) -> RuntimeError:
        tail = _read_log_tail(log_path)
        return RuntimeError(f"{reason}\n--- server output ---\n{tail}")

    for _ in range(40):
        # A dead child can never become ready, and continuing to poll would let
        # an unrelated server on this port answer for it.
        exit_code = proc.poll()
        if exit_code is not None:
            raise _fail(f"studyloop web exited with code {exit_code} before serving port {port}")
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
    raise _fail(f"Web server failed to start on port {port} within 12s")


def _port_is_free(port: int) -> bool:
    """True when no process is currently listening on ``port``.

    ``SO_REUSEADDR`` is set deliberately: a socket left in ``TIME_WAIT`` by a
    just-stopped server is not a problem (uvicorn can still bind it), so it must
    not be reported as occupied. An active listener still refuses the bind,
    which is the case worth catching.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _read_log_tail(log_path: str, limit: int = 4000) -> str:
    """Last ``limit`` characters of a captured server log, for error messages."""
    try:
        text = Path(log_path).read_text(errors="replace")
    except OSError as exc:  # pragma: no cover - defensive
        return f"<could not read {log_path}: {exc}>"
    if not text.strip():
        return "<server produced no output>"
    return text[-limit:]


def effective_credentials() -> tuple[str, str]:
    """Return (username, password) the CLI will use from config."""
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        return (settings.lan_username or "study", settings.lan_password or "")
    except Exception:
        return ("study", "")


def clean_ipc() -> None:
    """Wipe session-state IPC files (a no-op if they don't exist)."""
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Pytest fixtures — import and use via e.g. ``from _playwright_helpers import
# web_server_fixture_factory; web_server = web_server_fixture_factory(19000)``.
# ---------------------------------------------------------------------------


def web_server_fixture_factory(port: int):
    """Return a pytest fixture that brings up a studyloop server on ``port``.

    Each test file typically uses a unique port to avoid conflicts when
    ``pytest -n`` is used. Wraps the lifecycle: clean IPC, start, yield,
    terminate, clean IPC.
    """

    @pytest.fixture()
    def _fixture() -> Generator[subprocess.Popen, None, None]:
        clean_ipc()
        proc = start_web_server(port)
        try:
            yield proc
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)
            clean_ipc()

    return _fixture


def auth_context_fixture_factory():
    """Return a pytest fixture that wraps browser in an auth-aware context."""

    @pytest.fixture()
    def _fixture(browser: Browser) -> Generator[BrowserContext, None, None]:
        user, password = effective_credentials()
        ctx_args = {}
        if password:
            ctx_args["http_credentials"] = {"username": user, "password": password}
        context = browser.new_context(**ctx_args)
        try:
            yield context
        finally:
            context.close()

    return _fixture


def web_page_fixture_factory(web_server_fixture_name: str, auth_fixture_name: str):
    """Return a pytest fixture that yields a Page backed by the given server.

    Parametrised by fixture names so each test file can wire the
    server+context pair it needs.
    """

    @pytest.fixture()
    def _fixture(request: pytest.FixtureRequest) -> Generator[Page, None, None]:
        request.getfixturevalue(web_server_fixture_name)
        context: BrowserContext = request.getfixturevalue(auth_fixture_name)
        page = context.new_page()
        try:
            yield page
        finally:
            page.close()

    return _fixture
