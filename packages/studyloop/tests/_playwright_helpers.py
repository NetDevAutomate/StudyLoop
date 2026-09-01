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
    # Every start path funnels through here, so registering the log at this one
    # point is what makes the per-test server-error check unbypassable.
    _register_server_log(log_path)

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


# ---------------------------------------------------------------------------
# Server-side failure detection
# ---------------------------------------------------------------------------

#: Captured log of every studyloop server started during this pytest run, mapped
#: to the offset already scanned. Registered by ``start_web_server`` itself,
#: which every start path funnels through: the fixture factories here, the e2e
#: world builder, the journey tests, and test classes that roll their own server
#: wrapper. Registering at the chokepoint rather than in each teardown means a
#: test cannot opt out of the check by bringing its own client or its own
#: process -- which is the point. The failure that motivated this scanned clean
#: through the browser-attached watcher because it drove the server with urllib.
_SERVER_LOGS: dict[str, int] = {}

#: uvicorn logs an unhandled route exception under this banner at ERROR level.
#: The servers run with log_level="warning", so access-log lines are absent and
#: a response status cannot be recovered from the log at all; ConsoleWatch
#: covers status codes for browser traffic, and the two are complementary
#: rather than redundant.
_ASGI_EXCEPTION_BANNER = "Exception in ASGI application"


def _register_server_log(path: str) -> None:
    _SERVER_LOGS.setdefault(path, 0)


def _summarise_asgi_failure(block: str, log_path: str) -> str:
    """One line naming the exception and the deepest studyloop frame."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    exception = "<no exception line found>"
    for line in lines:
        stripped = line.strip()
        # The traceback's final line is the exception; it is the only
        # non-indented, non-"File"/"Traceback" line in the block.
        if (
            stripped
            and not line.startswith((" ", "\t"))
            and not stripped.startswith(("File ", "Traceback"))
        ):
            exception = stripped
    frame = ""
    for line in lines:
        if 'File "' in line and "/studyloop/" in line and "site-packages" not in line:
            frame = line.strip()
    where = f" at {frame}" if frame else ""
    return f"server raised {exception}{where} (log: {log_path})"


def new_server_log_failures() -> list[str]:
    """Server-side failures logged since the previous call.

    Reads each log incrementally so a module- or session-scoped server is
    attributed to the test during which it actually failed, rather than to the
    first test that happened to touch it.
    """
    found: list[str] = []
    for path, offset in list(_SERVER_LOGS.items()):
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:  # pragma: no cover - log removed under us
            continue
        _SERVER_LOGS[path] = len(text)
        fresh = text[offset:]
        if _ASGI_EXCEPTION_BANNER not in fresh:
            continue
        found.extend(
            _summarise_asgi_failure(block, path)
            for block in fresh.split(_ASGI_EXCEPTION_BANNER)[1:]
        )
    return found


def reset_server_log_tracking() -> None:
    """Forget every registered log. For tests of this mechanism itself."""
    _SERVER_LOGS.clear()


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
