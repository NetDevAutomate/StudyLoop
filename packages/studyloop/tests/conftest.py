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
import subprocess
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


# ---------------------------------------------------------------------------
# Session-dir isolation (C8 / R-49d): the real ~/.config/studyloop must be
# unreachable from the unit suite.
# ---------------------------------------------------------------------------
#
# Root cause of the incident this fixture closes (evidence/M2/step-8/00-dod.md,
# "Safety incident during implementation"): ``session_state.py``'s
# ``SESSION_DIR``/``STATE_FILE``/``TOPICS_FILE``/``PARKING_FILE`` are resolved
# ONCE, at that module's own import time, from ``STUDYLOOP_SESSION_DIR``
# (defaulting to the real ``~/.config/studyloop``) -- setting the env var
# later, or patching ``_isolate_state_dir`` above, does nothing for them:
# that fixture covers a DIFFERENT subsystem (``load_settings().state_dir``,
# the DB/settings root) and never touches these names. Several other
# modules additionally bind their OWN copies of the same names at their OWN
# import time (``from studyloop.session_state import STATE_FILE``), so
# patching only ``studyloop.session_state``'s attributes does not retarget
# those modules' bound copies -- each needs patching individually. Two
# pre-existing tests fell through this exact gap and created 5 real tmux
# sessions plus 5 real directories under ``~/.config/studyloop/sessions/``
# before being caught by hand.

_SESSION_DIR_CONSTANT_MODULES = (
    "studyloop.session_state",
    "studyloop.web.routes.session",
    "studyloop.web.routes.session._ipc",
    "studyloop.web.routes.session._start",
    "studyloop.web.routes.session._dashboard",
    "studyloop.tui.sidebar",
)

_SESSION_DIR_CONSTANT_FILENAMES = (
    ("SESSION_DIR", None),
    ("STATE_FILE", "session-state.json"),
    ("TOPICS_FILE", "session-topics.md"),
    ("PARKING_FILE", "session-parking.md"),
)


@pytest.fixture(autouse=True)
def _isolate_real_studyloop_config_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point every session-dir constant, in every module that binds its own
    copy, at a throwaway directory -- for every test in the suite, whether
    or not the test itself opts in.

    A test that wants its own tmp_path for this (most of
    test_session_authority_matrix.py, test_web_session_start_pty.py, etc.)
    is unaffected: its own later monkeypatch/patch calls simply override
    this fixture's default for the duration of that test, then both unwind
    together at teardown (same monkeypatch stack). ``tmp_path_factory``,
    not ``tmp_path``, so this fixture's directory never coincides with a
    test's own ``tmp_path`` and cannot contaminate an assertion the test
    makes about its own tmp_path's contents (same reasoning as
    ``_isolate_state_dir`` above).
    """
    import importlib

    isolated = tmp_path_factory.mktemp("studyloop-suite-session-dir")
    monkeypatch.setenv("STUDYLOOP_SESSION_DIR", str(isolated))

    for module_name in _SESSION_DIR_CONSTANT_MODULES:
        module = importlib.import_module(module_name)
        for attr, filename in _SESSION_DIR_CONSTANT_FILENAMES:
            if not hasattr(module, attr):
                continue
            target = isolated if filename is None else isolated / filename
            monkeypatch.setattr(module, attr, target)


# The session-runtime surface the fixture above targets and the guard below
# watches -- deliberately NOT the whole ~/.config/studyloop tree. That
# directory also holds sessions.db (the real learner's history database,
# governed by STUDYLOOP_DB/agent_session_tools and already isolated by the
# env vars set at the top of this file), config.yaml, secrets, and backups,
# none of which any code path this incident touched can reach. Watching
# those too would make the guard fail on unrelated traffic from other
# processes sharing this machine (a live studyloop web server, another
# agent session, session-export) -- a false positive that would teach
# developers to ignore the guard, exactly what it must never do.
_SESSION_RUNTIME_NAMES = (
    "session-state.json",
    "session-topics.md",
    "session-parking.md",
    ".session-state.lock",
    "studyloop-tmux.lock",
    "session-oneline.txt",
    "sessions",
)


def _snapshot_studyloop_session_runtime() -> dict[str, float]:
    """List every path under the session-runtime surface with its mtime.

    A missing root, or a missing individual entry, contributes nothing --
    there is nothing to violate yet.
    """
    root = Path.home() / ".config" / "studyloop"
    snapshot: dict[str, float] = {}
    for name in _SESSION_RUNTIME_NAMES:
        entry = root / name
        if not entry.exists():
            continue
        paths = [entry] if entry.is_file() else [entry, *entry.rglob("*")]
        for p in paths:
            try:
                snapshot[str(p)] = p.stat().st_mtime
            except OSError:
                continue
    return snapshot


_studyloop_session_runtime_snapshot: dict[str, float] = {}


# ---------------------------------------------------------------------------
# tmux socket isolation (C11 / R-49e): the real tmux server must be
# unreachable from the unit suite, the same way C8/R-49d made the real
# ~/.config/studyloop unreachable.
# ---------------------------------------------------------------------------
#
# tmux resolves its socket directory from TMUX_TMPDIR (falling back to
# TMPDIR, then /tmp/tmux-<uid>/) for the default `-L <name>` addressing
# EVERY tmux call site in this codebase uses -- confirmed by inspection:
# studyloop.tmux._tmux() passes no -L/-S at all, and the harness
# (test_harness_matrix.py) shells out to the bare `tmux` binary the same
# way. The one `-S` anywhere in the source tree
# (multiplexer.py's `capture-pane -t ... -S -{lines}`) is capture-pane's
# unrelated "start line" flag, not a socket path -- no code path in this
# repository bypasses TMUX_TMPDIR with an explicit socket path.
#
# Set here, in pytest_sessionstart, before any test imports studyloop.tmux
# or spawns a tmux subprocess: every tmux invocation reads os.environ
# fresh at call time (none of them capture it at import time), including
# subprocess children spawned by the harness (they build their env from
# `**os.environ`), so this redirects the WHOLE suite's tmux traffic to a
# private, throwaway socket directory. TMUX is also unset, so a test
# process run from inside a real tmux session on this machine is never
# treated as "already inside" one (studyloop.tmux.is_in_tmux()).
_TMUX_TMPDIR_ROOT = Path(tempfile.mkdtemp(prefix="studyloop-test-tmux-"))


def pytest_sessionstart(session) -> None:
    """Snapshot the real session-runtime surface (C8) and isolate tmux's
    own socket directory (C11) before any test runs."""
    global _studyloop_session_runtime_snapshot
    _studyloop_session_runtime_snapshot = _snapshot_studyloop_session_runtime()

    os.environ["TMUX_TMPDIR"] = str(_TMUX_TMPDIR_ROOT)
    os.environ.pop("TMUX", None)


def test_session_dir_is_isolated_from_the_real_config_dir() -> None:
    """Guard: every session-dir constant the autouse fixture above patches
    must actually point away from ~/.config/studyloop, in every module that
    binds its own copy.

    Companion to test_no_test_writes_to_real_user_state below -- same shape,
    different subsystem (session_state.py's SESSION_DIR family rather than
    load_settings().state_dir). Assertion-only: never itself writes
    anywhere, so it cannot trip the session-runtime snapshot guard.
    """
    import importlib

    real = str(Path.home() / ".config" / "studyloop")
    for module_name in _SESSION_DIR_CONSTANT_MODULES:
        module = importlib.import_module(module_name)
        for attr, _filename in _SESSION_DIR_CONSTANT_FILENAMES:
            if not hasattr(module, attr):
                continue
            value = str(getattr(module, attr))
            assert not value.startswith(real), (
                f"{module_name}.{attr} == {value!r} still resolves under the real "
                "config dir -- the autouse isolation fixture did not retarget it"
            )


def test_tmux_socket_is_isolated_from_the_real_tmux_server() -> None:
    """Guard (C11/R-49e): TMUX_TMPDIR must actually point at the private
    directory pytest_sessionstart created, and TMUX must be unset.

    Assertion-only: never itself starts a tmux session, so it cannot trip
    the private-socket guard in pytest_sessionfinish.
    """
    assert os.environ.get("TMUX_TMPDIR") == str(_TMUX_TMPDIR_ROOT)
    assert "TMUX" not in os.environ


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
def mux_harness(request: pytest.FixtureRequest, tmp_path):
    """Parameterised multiplexer harness — yields one instance per backend.

    Tests using this fixture run TWICE: once for tmux, once for herdr.
    Skips gracefully if the backend binary is not available (CI without herdr).

    R-49: session_dir is redirected to tmp_path/session-ipc so the harness
    reads/writes/deletes there instead of the developer's real
    ~/.config/studyloop.
    """
    import shutil

    from harness.multiplexer import MultiplexerHarness

    backend_name: str = request.param

    if backend_name == "tmux" and not shutil.which("tmux"):
        pytest.skip("tmux not available")
    if backend_name == "herdr" and not shutil.which("herdr"):
        pytest.skip("herdr not available")

    session_dir = tmp_path / "session-ipc"
    session_dir.mkdir(parents=True, exist_ok=True)
    with MultiplexerHarness.from_backend_name(backend_name, session_dir) as harness:
        yield harness


@pytest.fixture()
def tmux_mux_harness(tmp_path):
    """tmux-only multiplexer harness (for tmux-specific journey tests)."""
    import shutil

    from harness.multiplexer import MultiplexerHarness

    if not shutil.which("tmux"):
        pytest.skip("tmux not available")
    session_dir = tmp_path / "session-ipc"
    session_dir.mkdir(parents=True, exist_ok=True)
    with MultiplexerHarness.from_backend_name("tmux", session_dir) as harness:
        yield harness


@pytest.fixture()
def herdr_mux_harness(tmp_path):
    """herdr-only multiplexer harness (for herdr-specific journey tests)."""
    import shutil

    from harness.multiplexer import MultiplexerHarness

    if not shutil.which("herdr"):
        pytest.skip("herdr not available")
    session_dir = tmp_path / "session-ipc"
    session_dir.mkdir(parents=True, exist_ok=True)
    with MultiplexerHarness.from_backend_name("herdr", session_dir) as harness:
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


# ---------------------------------------------------------------------------
# Hollow-run guard
# ---------------------------------------------------------------------------
#
# A gate can go green while testing almost nothing. If a dependency is missing
# the browser suite does not fail, it SKIPS -- so "0 failed" survives a run that
# executed no tests at all, which is this repo's recurring defect rather than a
# hypothetical: a 500-pass report once concealed two real bugs, and the
# browser-side unit tests sat in no gate while looking covered.
#
# Enforcing "these binaries are installed" would only cover the dependencies
# somebody thought of. Enforcing "this run actually passed N tests" covers every
# way a run can quietly become hollow, including reasons nobody has met yet.
#
# Opt-in via STUDYLOOP_MIN_PASSED so a developer running one file is unaffected.

MIN_PASSED_ENV = "STUDYLOOP_MIN_PASSED"


def _passed_count(terminalreporter) -> int:
    return len(terminalreporter.stats.get("passed", []))


def pytest_sessionfinish(session, exitstatus) -> None:
    """Fail a run that passed fewer tests than the caller demanded, OR that
    touched the real ~/.config/studyloop session-runtime surface (C8/R-49d).
    """
    required = os.environ.get(MIN_PASSED_ENV)
    if required:
        try:
            minimum = int(required)
        except ValueError:
            minimum = None
        if minimum is not None:
            reporter = session.config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:  # pragma: no cover - no terminal plugin
                passed = _passed_count(reporter)
                if passed < minimum:
                    skipped = len(reporter.stats.get("skipped", []))
                    reporter.write_sep(
                        "!",
                        f"HOLLOW RUN: {passed} passed, {minimum} required "
                        f"({MIN_PASSED_ENV}), {skipped} skipped — a dependency is "
                        "probably missing, so this green is not evidence",
                        red=True,
                        bold=True,
                    )
                    session.exitstatus = 1

    _check_real_studyloop_config_dir_untouched(session)
    _kill_and_report_private_tmux_socket(session)


def _kill_and_report_private_tmux_socket(session) -> None:
    """C11/R-49e backstop: kill any tmux server left running in the
    private socket directory, and fail the run if one existed.

    Guarded against a synthetic ``session`` for the same reason
    ``_check_real_studyloop_config_dir_untouched`` is (see its own
    docstring): a direct call from a unit test exercising unrelated
    hook logic must not run this.

    A server here means some test created a real tmux session without
    going through the stubbed multiplexer backend -- exactly the failure
    mode that leaked 3 real tmux sessions during R-01b/C9's own RED
    verification (caught and cleaned up by hand both times; this backstop
    is what makes the NEXT one loud instead of a manual `tmux
    list-sessions` check after the fact).
    """
    if not isinstance(session, pytest.Session):
        return
    env = {**os.environ, "TMUX_TMPDIR": str(_TMUX_TMPDIR_ROOT)}
    listing = subprocess.run(
        ["tmux", "list-sessions"],
        capture_output=True,
        text=True,
        env=env,
    )
    had_sessions = listing.returncode == 0 and bool(listing.stdout.strip())
    # kill-server exits non-zero with "no server running on <socket>" when
    # there is nothing to kill -- ignored either way, per the item's own
    # instruction; there is nothing further to clean up once this returns.
    subprocess.run(
        ["tmux", "kill-server"],
        capture_output=True,
        text=True,
        env=env,
    )
    if not had_sessions:
        return
    message = (
        "R-49e: a real tmux session was left running in the unit suite's "
        "private socket directory at session finish -- a test fell "
        f"through tmux isolation (now killed):\n{listing.stdout}"
    )
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:  # pragma: no cover - no terminal plugin
        reporter.write_sep("!", message, red=True, bold=True)
    session.exitstatus = 1


def _check_real_studyloop_config_dir_untouched(session) -> None:
    """C8/R-49d backstop: fail the whole run if anything under the real
    ``~/.config/studyloop`` session-runtime surface changed during it.

    The per-test isolation fixture above is the primary defence; this is
    the loud failure for the day it has a gap (a module not on its list, a
    new code path that resolves the path some other way) instead of silent
    damage to the developer's real config directory -- exactly how the two
    tests fixed in R-01b were found.

    Guarded against a synthetic ``session`` (not a real ``pytest.Session``):
    ``test_readiness_scaling.py::TestHollowRunGuard`` calls
    ``conftest.pytest_sessionfinish(fake_session, 0)`` DIRECTLY, with a
    hand-built stand-in object, to unit-test the hollow-run-guard logic
    above in isolation -- without this guard, that call would ALSO run
    the check below against this REAL machine's REAL config dir (nothing
    about a direct function call tells Python "this session is fake"),
    and any real, unrelated activity on a shared dev machine during a
    long suite run (a live `studyloop web` session, another agent's own
    test run) would fail those tests for a reason that has nothing to do
    with what they test.
    """
    if not isinstance(session, pytest.Session):
        return
    after = _snapshot_studyloop_session_runtime()
    if after == _studyloop_session_runtime_snapshot:
        return
    before = _studyloop_session_runtime_snapshot
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in (set(after) & set(before)) if after[p] != before[p])
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    detail_lines = []
    if added:
        detail_lines.append(f"  created: {added}")
    if removed:
        detail_lines.append(f"  removed: {removed}")
    if changed:
        detail_lines.append(f"  modified: {changed}")
    message = (
        "R-49d: the real ~/.config/studyloop session-runtime surface changed "
        "during this run -- a test fell through session-dir isolation (or "
        "something else on this machine wrote there while the suite ran):\n"
        + "\n".join(detail_lines)
    )
    if reporter is not None:  # pragma: no cover - no terminal plugin
        reporter.write_sep("!", message, red=True, bold=True)
    session.exitstatus = 1
