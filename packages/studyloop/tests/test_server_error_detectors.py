"""Tests for the two server-error detectors.

The suite once reported "500 passed" while GET /api/session/state was returning
HTTP 500. Nothing failed a run on a server error: the browser watcher collected
5xx responses and then asserted only on JS errors, and the test that was
actually failing drove the server with urllib and had no page at all.

Two complementary channels now exist, and these tests prove each one fires:

* ConsoleWatch sees response status codes, for browser traffic only.
* The server-log scan sees unhandled exceptions from ANY client, because the
  servers run at log_level="warning" where uvicorn logs an ASGI exception but
  no access lines -- so a status code cannot be recovered from the log.

Neither subsumes the other, which is why both exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from _playwright_helpers import (
    _register_server_log,
    _summarise_asgi_failure,
    new_server_log_failures,
    reset_server_log_tracking,
)
from e2e._env import ConsoleWatch

# --------------------------------------------------------------------------
# Channel 1 — ConsoleWatch, response status codes
# --------------------------------------------------------------------------


class _StubPage:
    """Captures the handlers ConsoleWatch registers, so they can be fired."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on(self, event: str, handler: object) -> None:
        self.handlers[event] = handler


class _StubResponse:
    def __init__(self, status: int, url: str) -> None:
        self.status = status
        self.url = url


class _StubConsoleMessage:
    def __init__(self, type_: str, text: str) -> None:
        self.type = type_
        self.text = text


def _watch_with_page() -> tuple[ConsoleWatch, _StubPage]:
    page = _StubPage()
    watch = ConsoleWatch(page)  # type: ignore[arg-type]
    return watch, page


def test_console_watch_fails_on_a_500_with_no_js_error() -> None:
    """A 5xx alone must fail. This is the exact hole that hid the defect."""
    watch, page = _watch_with_page()
    page.handlers["response"](_StubResponse(500, "http://127.0.0.1:1/api/session/state"))  # type: ignore[operator]

    with pytest.raises(AssertionError, match="HTTP 500"):
        watch.assert_clean("loading the dashboard")


def test_console_watch_reports_both_kinds_together() -> None:
    watch, page = _watch_with_page()
    page.handlers["response"](_StubResponse(503, "http://127.0.0.1:1/api/backlog"))  # type: ignore[operator]
    page.handlers["console"](_StubConsoleMessage("error", "TypeError: x is not a function"))  # type: ignore[operator]

    with pytest.raises(AssertionError) as exc:
        watch.assert_clean("rendering")

    assert "HTTP 503" in str(exc.value)
    assert "TypeError" in str(exc.value)


def test_console_watch_stays_quiet_when_clean() -> None:
    watch, page = _watch_with_page()
    page.handlers["response"](_StubResponse(200, "http://127.0.0.1:1/api/session/state"))  # type: ignore[operator]
    page.handlers["console"](_StubConsoleMessage("log", "just chatter"))  # type: ignore[operator]

    watch.assert_clean("doing nothing interesting")


def test_console_watch_still_ignores_known_noise() -> None:
    """The existing IGNORE list must keep working -- 404s on favicon etc."""
    watch, page = _watch_with_page()
    page.handlers["console"](_StubConsoleMessage("error", "favicon.ico failed"))  # type: ignore[operator]

    watch.assert_clean("loading a page without a favicon")


# --------------------------------------------------------------------------
# Channel 2 — server-log scan, transport independent
# --------------------------------------------------------------------------

_REAL_TRACEBACK = """INFO:     Started server process [1]
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "/x/.venv/lib/python3.13/site-packages/uvicorn/h11_impl.py", line 403, in run_asgi
    result = await app(self.scope, self.receive, self.send)
  File "/x/packages/studyloop/src/studyloop/web/routes/session/_ipc.py", line 63, in _get_full_state
    topics = session_pkg.parse_topics_file()
FileNotFoundError: [Errno 2] No such file or directory: 'session-topics.md'
"""


@pytest.fixture(autouse=True)
def _isolated_log_registry():
    reset_server_log_tracking()
    yield
    reset_server_log_tracking()


def test_log_scan_detects_an_asgi_exception(tmp_path: Path) -> None:
    log = tmp_path / "studyloop-web-1234-.log"
    log.write_text(_REAL_TRACEBACK)
    _register_server_log(str(log))

    failures = new_server_log_failures()

    assert len(failures) == 1
    assert "FileNotFoundError" in failures[0]


def test_log_scan_names_the_studyloop_frame_not_the_uvicorn_one(tmp_path: Path) -> None:
    """The useful location is our code, not the ASGI plumbing above it."""
    log = tmp_path / "studyloop-web-1234-.log"
    log.write_text(_REAL_TRACEBACK)
    _register_server_log(str(log))

    (failure,) = new_server_log_failures()

    assert "_ipc.py" in failure
    assert "site-packages" not in failure


def test_log_scan_is_quiet_for_a_healthy_server(tmp_path: Path) -> None:
    log = tmp_path / "studyloop-web-1234-.log"
    log.write_text("Study PWA\n  Local: http://127.0.0.1:1234\nShutting down\n")
    _register_server_log(str(log))

    assert new_server_log_failures() == []


def test_log_scan_reads_incrementally(tmp_path: Path) -> None:
    """A module-scoped server must be attributed to the test that broke it.

    Without an offset the first test to touch a long-lived server would absorb
    every later failure, and the test that actually caused one would pass.
    """
    log = tmp_path / "studyloop-web-1234-.log"
    log.write_text("Study PWA\n")
    _register_server_log(str(log))
    assert new_server_log_failures() == []

    with log.open("a") as fh:
        fh.write(_REAL_TRACEBACK)
    assert len(new_server_log_failures()) == 1

    # Already reported once; it must not be reported again.
    assert new_server_log_failures() == []


def test_log_scan_counts_each_exception(tmp_path: Path) -> None:
    log = tmp_path / "studyloop-web-1234-.log"
    log.write_text(_REAL_TRACEBACK + _REAL_TRACEBACK)
    _register_server_log(str(log))

    assert len(new_server_log_failures()) == 2


def test_log_scan_tolerates_a_deleted_log(tmp_path: Path) -> None:
    _register_server_log(str(tmp_path / "never-existed.log"))

    assert new_server_log_failures() == []


def test_summariser_handles_a_block_without_an_exception_line() -> None:
    """Never raise out of the summariser: it runs while reporting a failure."""
    assert "no exception line" in _summarise_asgi_failure("\n", "/tmp/x.log")
