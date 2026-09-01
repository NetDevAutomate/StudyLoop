"""Global pytest configuration for the studyloop test suite.

Sets environment variables BEFORE any test modules import studyloop.

The critical setup here: forcing Rich to emit plain text instead of
ANSI escape codes so CLI-output assertions (``"#42" in result.output``)
work under ``click.testing.CliRunner``, which captures stdout into a
StringIO that Rich still treats as terminal-capable.

``NO_COLOR=1`` tells Rich to drop colors. ``TERM=dumb`` is required on
top of that -- Rich keeps emitting bold/underline escape codes until
it sees a non-ANSI terminal type.

These env vars affect only the test process, never user runtime.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# conftest.py is loaded BEFORE its own directory is on sys.path -- pytest adds the
# rootdir while collecting test modules, not while importing the conftest itself --
# so a sibling import needs this first. Same pattern the test modules already use
# for _playwright_helpers.
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import _readiness  # noqa: E402

# These MUST be set before any `from studyloop...` import, because
# ``studyloop.output`` (and CLI submodules) construct a module-level
# ``Console()`` whose behaviour is fixed at construction time.
#
# Hard-assign, not ``setdefault`` -- the shell typically exports
# ``TERM=xterm-256color`` which Rich treats as ANSI-capable and will
# keep emitting bold/underline escape codes even under ``NO_COLOR``.
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"

# Writable-state isolation. These MUST be set here, at import time, and via
# the environment rather than a fixture:
#
#  * ``load_settings()`` / ``get_db_path()`` read them at call time, so every
#    in-process caller is covered without monkeypatching each one.
#  * a test that shells out to the CLI inherits only the environment — a
#    monkeypatched function does not cross the process boundary. That gap is
#    how the suite previously migrated the learner's real ``sessions.db`` and
#    wrote a poisoned picker cache into their real state dir. See
#    ``docs/issues/0005-vendor-picker-lists-repo-directories.md``.
#
# Individual tests may still point these at their own tmp_path; the default
# below only guarantees that *nothing* lands in the real user directories.
_TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="studyloop-test-state-"))
os.environ.setdefault("STUDYLOOP_STATE_DIR", str(_TEST_STATE_ROOT / "state"))
os.environ.setdefault("STUDYLOOP_DB", str(_TEST_STATE_ROOT / "sessions.db"))

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from studyloop.session.transport import SessionConfig, TransportEventT


# ---------------------------------------------------------------------------
# Test isolation: redirect state_dir to a temp directory so no test leaks
# into ~/.local/share/studyloop. The env vars set at import time above are
# the primary mechanism (they survive subprocess boundaries); this autouse
# fixture is the belt-and-braces layer for any test that builds a Settings
# object directly and bypasses the environment.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_state_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep ``load_settings().state_dir`` out of the learner's real state dir.

    Prevents any test from reading or writing the user's real
    ~/.local/share/studyloop — the root cause of issue 0005.

    Uses tmp_path_factory (not tmp_path) so the isolated dir lives in a
    separate temp tree that won't pollute tests using tmp_path as their
    own working directory.
    """
    isolated_state = tmp_path_factory.mktemp("studyloop-isolated-state")

    from studyloop import settings as _settings_mod

    _original_load = _settings_mod.load_settings

    def _patched_load_settings():
        s = _original_load()
        # Only override when the test has not already chosen a state_dir
        # (detected by it still pointing at the production default).
        if s.state_dir == _settings_mod.DEFAULT_STATE_DIR:
            s.state_dir = isolated_state
        return s

    monkeypatch.setattr(_settings_mod, "load_settings", _patched_load_settings)


def test_no_test_writes_to_real_user_state() -> None:
    """Guard: the suite must never resolve writable state to the real dirs.

    Asserted as a test, not just a fixture, so the invariant fails loudly in
    CI if the env-var wiring above is ever removed or reordered.

    Both resolvers are checked. ``studyloop.settings`` and
    ``agent_session_tools.config_loader`` compute the session DB path
    independently, and covering only one of them left the real database being
    migrated by test runs.
    """
    from agent_session_tools.config_loader import DEFAULT_CONFIG
    from agent_session_tools.config_loader import get_db_path as ast_get_db_path
    from studyloop.settings import (
        DEFAULT_DB,
        DEFAULT_STATE_DIR,
        get_db_path,
        get_state_dir,
        load_settings,
    )

    assert get_state_dir() != DEFAULT_STATE_DIR, "state_dir escaped test isolation"
    assert get_db_path() != DEFAULT_DB, "studyloop session DB escaped test isolation"
    assert load_settings().session_db != DEFAULT_DB, (
        "Settings.session_db escaped test isolation (history/_connection.py reads this one)"
    )
    assert str(ast_get_db_path()) != DEFAULT_CONFIG["database"]["path"], (
        "agent_session_tools session DB escaped test isolation"
    )


class StubTransport:
    """In-memory ``AgentSessionTransport`` for unit tests.

    Satisfies the Protocol without spawning a real PTY. Preloaded events
    are yielded from ``events()``; method calls are recorded on public
    attributes for assertions.

    Usage::

        stub = StubTransport(events=[Started(agent="claude")])
        await stub.start(config)
        async for event in stub.events(): ...
        assert stub.start_calls == [config]
    """

    def __init__(self, events: Sequence[TransportEventT] = ()) -> None:
        self._events: list[TransportEventT] = list(events)
        self.start_calls: list[SessionConfig] = []
        self.sent_input: list[bytes] = []
        self.resize_calls: list[tuple[int, int]] = []
        self.cancel_calls: int = 0
        self.end_calls: int = 0
        # Recorded send_permission_response calls.
        # Each entry: (request_id, outcome_dict)
        self.permission_calls: list[tuple[str | int, dict]] = []

    async def start(self, config: SessionConfig) -> None:
        self.start_calls.append(config)

    async def send_input(self, data: bytes) -> None:
        self.sent_input.append(data)

    async def resize(self, cols: int, rows: int) -> None:
        self.resize_calls.append((cols, rows))

    async def events(self) -> AsyncIterator[TransportEventT]:
        for event in self._events:
            yield event

    async def send_permission_response(self, request_id: str | int, outcome: dict) -> None:
        self.permission_calls.append((request_id, outcome))

    async def cancel(self) -> None:
        self.cancel_calls += 1

    async def end(self) -> None:
        self.end_calls += 1

    async def __aenter__(self) -> StubTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.end()


# ---------------------------------------------------------------------------
# Multiplexer harness fixture (T4 — journey tests)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["tmux", "herdr"])
def mux_harness(request: pytest.FixtureRequest):
    """Parameterised multiplexer harness — yields one instance per backend.

    Tests using this fixture run TWICE: once for tmux, once for herdr.
    Skips gracefully if the backend binary is not available (CI without herdr).
    """
    import shutil

    from harness.multiplexer import MultiplexerHarness

    backend_name: str = request.param

    if backend_name == "tmux" and not shutil.which("tmux"):
        pytest.skip("tmux not available")
    if backend_name == "herdr" and not shutil.which("herdr"):
        pytest.skip("herdr not available")

    with MultiplexerHarness.from_backend_name(backend_name) as harness:
        yield harness


@pytest.fixture()
def tmux_mux_harness():
    """tmux-only multiplexer harness (for tmux-specific journey tests)."""
    import shutil

    from harness.multiplexer import MultiplexerHarness

    if not shutil.which("tmux"):
        pytest.skip("tmux not available")
    with MultiplexerHarness.from_backend_name("tmux") as harness:
        yield harness


@pytest.fixture()
def herdr_mux_harness():
    """herdr-only multiplexer harness (for herdr-specific journey tests)."""
    import shutil

    from harness.multiplexer import MultiplexerHarness

    if not shutil.which("herdr"):
        pytest.skip("herdr not available")
    with MultiplexerHarness.from_backend_name("herdr") as harness:
        yield harness


# ---------------------------------------------------------------------------
# e2e tests get a longer per-test timeout than the 60s unit ceiling.
#
# The pytest-timeout ceiling in pyproject.toml exists to stop one hanging test
# eating the whole run (an unbounded TestClient WebSocket receive did exactly
# that). 60s is right for unit tests -- the slowest is ~13s -- but far too tight
# for e2e, which drives a real browser against a subprocess-hosted server and
# has individual waits already allowing 60-180s. test_journey_generate_review's
# generate walk alone measures ~61s, so a flat 60s kills it before its own
# deadline and reports a timeout that looks like a product bug.
#
# Applied as a collection hook rather than a `pytest.mark.timeout` on each of
# the 20 e2e modules: one rule, no per-module drift, and it covers modules added
# later. An explicit timeout mark on a test or module still wins.
# ---------------------------------------------------------------------------

E2E_TIMEOUT_SECONDS = 300


def pytest_collection_modifyitems(items) -> None:
    """Grant every e2e test its own timeout.

    Kept as one hook deliberately: pytest calls a conftest's
    ``pytest_collection_modifyitems`` by name, so a second definition does not
    run alongside the first, it REPLACES it. Splitting this once silently
    dropped the per-test timeout below, which would have turned a hanging test
    from a 300s failure into a run that never ends.
    """
    for item in items:
        if item.get_closest_marker("e2e") and not item.get_closest_marker("timeout"):
            item.add_marker(pytest.mark.timeout(E2E_TIMEOUT_SECONDS))


def pytest_report_header() -> str:
    """State the readiness multiplier in every run's header.

    Unconditional, including at 1.0. A pass count is only meaningful alongside
    the sensitivity that produced it, and this suite once reported "500 passed"
    without recording that its budgets had been widened.
    """
    scale = _readiness.configure_scale()
    if scale == 1.0:
        return "readiness budgets: unscaled (1.0x) — release configuration"
    return (
        f"readiness budgets: SCALED {scale}x via {_readiness.ENV_OVERRIDE} "
        "— diagnostic only, NOT a release-pass configuration"
    )


def pytest_terminal_summary(terminalreporter) -> None:
    """Repeat the multiplier beside the pass count, where -q cannot hide it.

    ``-q`` suppresses the header above, so the first full unscaled run after
    this check was added printed its counts with no statement of its
    sensitivity -- the original defect rebuilt in a new place. A summary line
    survives ``-q``, so the number and the configuration that produced it are
    always reported together.

    Reads the scale recorded when the session installed it, NOT the live global:
    tests in this repo legitimately set the env var and call
    ``configure_scale()``, and the first version of this hook read the global
    afterwards and warned on an unscaled run. A signal that cries wolf gets
    ignored, which would cost more than having no signal.
    """
    if _SESSION_SCALE is None or _SESSION_SCALE == 1.0:
        return
    terminalreporter.write_sep(
        "!",
        f"readiness budgets SCALED {_SESSION_SCALE}x "
        f"({_readiness.ENV_OVERRIDE}) — these counts are NOT a release result",
        red=True,
        bold=True,
    )


# ---------------------------------------------------------------------------
# Readiness-budget scaling — see _readiness.py for the reasoning
# ---------------------------------------------------------------------------


#: The multiplier this session actually installed, recorded once so the terminal
#: summary reports the run's real configuration rather than a global that tests
#: of the scaling mechanism legitimately mutate.
_SESSION_SCALE: float | None = None


@pytest.fixture(autouse=True, scope="session")
def _scale_playwright_readiness_budgets():
    """Apply the readiness multiplier, if one was explicitly requested.

    Calls ``configure_scale()`` itself rather than trusting
    ``pytest_report_header`` to have run: that hook's output is suppressed under
    ``-q``, and configuration must not depend on whether a header was printed.
    Idempotent -- both call sites read the same environment variable.
    """
    global _SESSION_SCALE
    _SESSION_SCALE = _readiness.configure_scale()
    patched = _readiness.install_scaling()
    try:
        yield
    finally:
        _readiness.remove_scaling(patched)


# ---------------------------------------------------------------------------
# Server-side failure detection — every test, every transport
# ---------------------------------------------------------------------------
#
# The suite reported "500 passed" while GET /api/session/state was returning
# HTTP 500, because nothing in the harness failed a run on a server error. The
# browser-attached ConsoleWatch records 5xx responses, but only 6 of 40 e2e
# files construct one, and the test that was actually failing drove the server
# with urllib and had no Playwright page at all.
#
# So the check lives here, as an autouse fixture keyed off logs registered by
# start_web_server itself. Any test that starts a server is covered without
# opting in, including one that brings its own client or its own server wrapper.


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Record each phase's report on the item so fixtures can read the outcome.

    Needed so the server-error check below can stay quiet when the test has
    already failed: appending a teardown error to a real failure buries the
    thing the developer needs to read.
    """
    outcome = yield
    setattr(item, f"_report_{outcome.get_result().when}", outcome.get_result())


@pytest.fixture(autouse=True)
def _fail_on_server_side_errors(request: pytest.FixtureRequest):
    """Fail a test whose server logged an unhandled exception.

    Runs last: autouse function-scoped fixtures are set up first and finalized
    last, so by the time this teardown runs the server fixtures have already
    terminated their children and flushed the captured logs.

    A test that legitimately drives the server into an unhandled exception can
    opt out with ``@pytest.mark.allow_server_errors``.
    """
    from _playwright_helpers import new_server_log_failures

    # Drain anything logged before this test so it is not misattributed.
    new_server_log_failures()
    yield
    failures = new_server_log_failures()
    if not failures:
        return
    if request.node.get_closest_marker("allow_server_errors"):
        return
    report = getattr(request.node, "_report_call", None)
    if report is not None and report.failed:
        # The test already failed; that failure is the more useful signal.
        return
    detail = "\n".join(f"  - {f}" for f in failures)
    pytest.fail(
        f"the server logged {len(failures)} unhandled exception(s) during this "
        f"test, so it passed only because nothing asserted on them:\n{detail}",
        pytrace=False,
    )
