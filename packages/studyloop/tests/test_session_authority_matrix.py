"""The session-authority contract's start/end matrix, plus the crash cell.

See docs/architecture/session-authority.md for the clauses these tests are
written against, and ADR-0009 for why the shape was chosen.

R-01: the web PTY/ACP start path checked only the in-process singleton
(``session/active.py``), never the CLI's file-based claim
(``session-state.json``). ``cli-then-web`` below is the reproduction from
``reviews/2026-09-02-full-repo-review/agents/01-session-lifecycle.md`` turned
into a test: at the pre-fix head it returns 201 and clobbers the state file
instead of 409.

R-02: ending any session called ``kill_all_study_sessions()``, which kills
every ``study-*`` multiplexer session on the machine, not just the caller's.
The two end-matrix cells below pin that only the ending session's own name is
ever killed.

Fixtures: ``tests/fixtures/session-state/{cli-live,web-live,ended,
crashed-web-still-live}.json`` are realistic ``session-state.json`` snapshots
for each owner shape. They are loaded as plain dicts (not read from
``STATE_FILE`` on disk) except where a test specifically needs the file
present, since ``is_claim_owner_alive``-style checks and ``write_session_state``
both operate on the same JSON shape either way.

Never touches the real ``~/.config/studyloop`` — ``_isolate_session_dir``
below monkeypatches every module's view of the session dir to ``tmp_path``,
matching ``test_session_slot_reconcile.py``'s established pattern.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop import session_state
from studyloop.session import active
from studyloop.session.start import SessionStartError, start_session
from studyloop.session.transport import SessionConfig, Started
from studyloop.web.app import create_app
from studyloop.web.routes.session import _grace

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "session-state"


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# Shared fixtures (mirrors test_session_slot_reconcile.py's isolation pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_active_state():
    run_async(active.release())
    _grace.reset_for_tests()
    yield
    run_async(active.release())
    _grace.reset_for_tests()


@pytest.fixture(autouse=True)
def _isolate_session_dir(tmp_path, monkeypatch):
    """Point every module's view of the IPC files at tmp_path.

    Never the real ~/.config/studyloop — see module docstring and the
    lane brief's rule against running this suite against a developer's live
    session state.
    """
    from studyloop.web.routes.session import _ipc, _start

    for module in (session_state, _ipc, _start):
        for name, filename in (
            ("STATE_FILE", "session-state.json"),
            ("TOPICS_FILE", "session-topics.md"),
            ("PARKING_FILE", "session-parking.md"),
        ):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, tmp_path / filename)
    monkeypatch.setattr(session_state, "SESSION_DIR", tmp_path)
    if hasattr(_start, "SESSION_DIR"):
        monkeypatch.setattr(_start, "SESSION_DIR", tmp_path)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(study_dirs=[]))


def _write_fixture(name: str) -> dict:
    """Load a fixture and write it to (patched) STATE_FILE. Returns the dict."""
    state = _fixture(name)
    session_state.write_session_state(state)
    return state


@pytest.fixture()
def _mock_agent_available(monkeypatch):
    """Pretend the 'claude' agent binary is installed (mirrors
    test_web_session_start_pty.py's fixture of the same name)."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    from studyloop.adapters._protocol import AgentAdapter
    from studyloop.agent_launcher import AGENTS

    real_claude = AGENTS["claude"]
    fake_claude = AgentAdapter(
        name=real_claude.name,
        binary=real_claude.binary,
        setup=lambda canonical, session_dir: session_dir / "persona.md",
        launch_cmd=lambda persona, resume: f"claude {persona}",
        teardown=None,
        mcp_setup=None,
    )
    monkeypatch.setitem(AGENTS, "claude", fake_claude)


@pytest.fixture()
def _stub_db(monkeypatch):
    monkeypatch.setattr(
        "studyloop.history.start_study_session",
        lambda topic, energy_label, topic_slug=None: "study-reclaim-1",
    )
    monkeypatch.setattr(
        "studyloop.history.sessions.update_persona_hash",
        lambda study_id, persona_hash: None,
    )


@pytest.fixture()
def _stub_pty_factory(monkeypatch):
    """Swap the route's PTYTransport factory for a StubTransport builder,
    exactly like test_web_session_start_pty.py's fixture of the same shape."""
    stubs: list[StubTransport] = []

    def factory():
        stub = StubTransport(events=[Started(agent="claude")])
        stubs.append(stub)
        return stub

    monkeypatch.setattr(
        "studyloop.web.routes.session._build_pty_transport",
        lambda config: factory,
        raising=False,
    )
    return stubs


# ---------------------------------------------------------------------------
# Start matrix
# ---------------------------------------------------------------------------


class TestWebThenWeb:
    """Existing behaviour: the in-process singleton blocks a second web
    start. Unchanged by this lane — pinned so a future edit cannot silently
    reopen it."""

    def test_second_web_start_is_refused(self, client: TestClient) -> None:
        run_async(
            active.acquire(
                SessionConfig(
                    study_session_id="web-sess-1",
                    agent="claude",
                    persona_file="",
                    cwd="/tmp",
                    env={},
                    cols=80,
                    rows=24,
                ),
                lambda: StubTransport(events=[Started(agent="claude")]),
            )
        )

        resp = client.post(
            "/api/session/start",
            json={"topic": "Async IO", "energy": 5, "agent": "claude", "transport": "pty"},
        )

        assert resp.status_code == 409
        assert "already active" in resp.json()["error"]


class TestCliThenCli:
    """R-01b, the fix. session/start.py's CLI guard used to block a second
    CLI start unconditionally, regardless of whether the recorded owner was
    actually still alive. It now consults claim_blocks_cli_start: a live CLI
    claim (its recorded multiplexer session still exists) still blocks, but
    a stale one is reclaimed, logged, and never blocks forever -- the same
    rule the web start path already applied (see
    docs/architecture/session-authority.md clause 2). is_session_active()
    itself is unchanged and still reports True for either shape."""

    def test_a_live_cli_claim_reports_active(self) -> None:
        _write_fixture("cli-live")

        assert session_state.is_session_active() is True

    def test_a_live_cli_claim_still_blocks_a_cli_start(self, caplog) -> None:
        """A CLI claim whose tmux session still exists blocks a new CLI
        start with the existing message, and logs no reclaim warning. C2:
        a claim that is never reclaimed must never have its topics/parking
        cleared either -- clearing is a reclaim-only side effect."""
        state = _fixture("cli-live")
        session_state.TOPICS_FILE.write_text(
            "- [09:00] Live topic | status:learning | still in progress\n"
        )
        session_state.PARKING_FILE.write_text("- Still-relevant parked question\n")

        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch(
                "studyloop.multiplexer.get_backend",
                return_value=MagicMock(session_exists=lambda name: True),
            ),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Async IO", "claude", "study", "elapsed", 5, False)

        assert "already active" in exc_info.value.message
        assert not any("reclaim" in rec.message.lower() for rec in caplog.records)
        assert len(session_state.parse_topics_file()) == 1
        assert len(session_state.parse_parking_file()) == 1

    def test_a_dead_cli_claim_is_reclaimed_by_a_cli_start(self, caplog) -> None:
        """A CLI claim whose tmux session no longer exists (the user's
        machine rebooted, or the tmux server was killed outside StudyLoop)
        must not block a new CLI start forever -- the CLI-then-CLI twin of
        the web path's crash-then-restart cell."""
        state = _fixture("cli-live")

        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch(
                "studyloop.multiplexer.get_backend",
                return_value=MagicMock(session_exists=lambda name: False),
            ),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch("studyloop.history.start_study_session", return_value=None),
            pytest.raises(SessionStartError) as exc_info,
        ):
            # start_study_session returning None gets past the reclaimed
            # guard and ends the test at the next SessionStartError
            # ("Failed to create session in DB") -- proof the guard let the
            # start proceed instead of raising "already active".
            start_session("Async IO", "claude", "study", "elapsed", 5, False)

        assert "already active" not in exc_info.value.message
        warnings = [rec for rec in caplog.records if "reclaim" in rec.message.lower()]
        assert len(warnings) == 1
        assert "cli-sess-1" in warnings[0].message

    def test_a_dead_cli_claim_reclaimed_by_a_cli_start_clears_topics_and_parking(
        self,
    ) -> None:
        """C2, CLI side: a CLI reclaim must not inherit the crashed
        session's topics/parking either -- the same defect the web path
        had, just reached from studyloop study instead of the web start
        route."""
        from studyloop.session.start import start_session

        state = _fixture("cli-live")
        session_state.TOPICS_FILE.write_text(
            "- [09:00] Dead topic | status:learning | leftover from the crash\n"
        )
        session_state.PARKING_FILE.write_text("- Leftover parked question\n")

        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch(
                "studyloop.multiplexer.get_backend",
                return_value=MagicMock(session_exists=lambda name: False),
            ),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch("studyloop.history.start_study_session", return_value=None),
            pytest.raises(SessionStartError),
        ):
            start_session("Async IO", "claude", "study", "elapsed", 5, False)

        assert session_state.parse_topics_file() == []
        assert session_state.parse_parking_file() == []


class TestCliThenWeb:
    """R-01, the fix. The reproduction from agents/01-session-lifecycle.md:
    a CLI-style claim is live (no in-process slot held) and a web PTY start
    must now be refused with the same 409 shape as the in-process conflict,
    instead of returning 201 and clobbering the shared state file."""

    def test_web_start_is_refused_when_cli_claim_is_live(self, client: TestClient) -> None:
        written = _write_fixture("cli-live")

        with patch(
            "studyloop.multiplexer.get_backend",
            return_value=MagicMock(session_exists=lambda name: True),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Async IO", "energy": 5, "agent": "claude", "transport": "pty"},
            )

        # The repro's own bar: must be 409, not 201.
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert "already active" in body["error"]
        assert body["study_session_id"] == "cli-sess-1"
        assert body["topic"] == "Decorators"

        # The state file must be untouched -- not clobbered by the would-be
        # new session (this was the actual damage in the live repro: the
        # CLI's tmux_session pointer was overwritten with None).
        on_disk = json.loads(session_state.STATE_FILE.read_text())
        assert on_disk == written
        assert run_async(active.current()) is None, "must not acquire the slot on a 409"

    def test_web_acp_start_is_also_refused(self, client: TestClient) -> None:
        """_start_acp_session must check the same file claim as PTY (R-01
        named both _start_pty_session and _start_acp_session)."""
        _write_fixture("cli-live")

        with patch(
            "studyloop.multiplexer.get_backend",
            return_value=MagicMock(session_exists=lambda name: True),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Async IO", "energy": 5, "agent": "kiro", "transport": "acp"},
            )

        assert resp.status_code == 409, resp.text
        assert "already active" in resp.json()["error"]

    def test_a_dead_cli_claim_is_reclaimed_not_blocked(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
        _stub_pty_factory,
        caplog,
    ) -> None:
        """A CLI claim whose tmux session no longer exists (the user's
        machine rebooted, or the tmux server was killed outside StudyLoop)
        must not block a new web start forever."""
        _write_fixture("cli-live")

        with patch(
            "studyloop.multiplexer.get_backend",
            return_value=MagicMock(session_exists=lambda name: False),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Async IO", "energy": 5, "agent": "claude", "transport": "pty"},
            )

        assert resp.status_code == 201, resp.text
        assert any("reclaim" in rec.message.lower() for rec in caplog.records)


class TestWebThenCli:
    """R-01b, the fix. session/start.py's CLI guard used to block
    unconditionally when the file said ANY session was live. It now checks
    a web-owned claim's recorded pid cross-process: live (blocks) iff
    os.kill(pid, 0) doesn't raise ProcessLookupError; a PermissionError
    (pid reused by a process the CLI doesn't own) also counts as live. No
    pid recorded (a claim written by a build before this fix) blocks
    conservatively -- see docs/architecture/session-authority.md clause 2.
    is_session_active() itself is unchanged and still reports True for any
    of these shapes."""

    def test_a_live_web_claim_reports_active(self) -> None:
        _write_fixture("web-live")

        assert session_state.is_session_active() is True

    def test_a_live_web_claim_still_blocks_a_cli_start(self, caplog) -> None:
        """A web claim whose recorded pid is this (very much alive) test
        process still blocks a new CLI start, and logs no reclaim
        warning."""
        state = _fixture("web-live")
        state["pid"] = os.getpid()

        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Async IO", "claude", "study", "elapsed", 5, False)

        assert "already active" in exc_info.value.message
        assert not any("reclaim" in rec.message.lower() for rec in caplog.records)

    def test_a_dead_web_claim_is_reclaimed_by_a_cli_start(self, caplog) -> None:
        """crashed-web-still-live's recorded pid cannot be alive on any real
        machine -- the crash-then-restart cell, checked from the CLI side."""
        state = _fixture("crashed-web-still-live")

        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            patch("studyloop.history.start_study_session", return_value=None),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Fresh topic", "claude", "study", "elapsed", 5, False)

        assert "already active" not in exc_info.value.message
        warnings = [rec for rec in caplog.records if "reclaim" in rec.message.lower()]
        assert len(warnings) == 1
        assert "web-sess-crashed" in warnings[0].message

    def test_a_web_claim_without_a_pid_blocks_conservatively(self) -> None:
        """A web-owned claim with no `pid` key (written by a build before
        this fix) blocks rather than silently reclaiming a claim whose
        owner it cannot verify."""
        state = _fixture("web-live")
        assert "pid" not in state

        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch("studyloop.session.cleanup.auto_clean_zombies"),
            pytest.raises(SessionStartError) as exc_info,
        ):
            start_session("Async IO", "claude", "study", "elapsed", 5, False)

        assert "already active" in exc_info.value.message


# ---------------------------------------------------------------------------
# Crash-then-restart
# ---------------------------------------------------------------------------


class TestCrashThenRestart:
    """The file says a web PTY/ACP session is live, but nothing in this
    process holds it (a crashed-and-restarted server, or a session that
    ended without the file being cleared). Per
    docs/architecture/session-authority.md clause 2, a pty/acp claim can
    only be genuinely live via the in-process singleton -- reaching the file
    check with that singleton empty proves the claim is stale. It must be
    reclaimed, logged, and must not block forever."""

    def test_stale_web_claim_is_reclaimed(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
        _stub_pty_factory,
        caplog,
    ) -> None:
        _write_fixture("crashed-web-still-live")

        resp = client.post(
            "/api/session/start",
            json={"topic": "Fresh topic", "energy": 5, "agent": "claude", "transport": "pty"},
        )

        assert resp.status_code == 201, resp.text
        assert resp.json()["study_session_id"] == "study-reclaim-1"
        assert any("reclaim" in rec.message.lower() for rec in caplog.records), (
            "a reclaimed stale claim must be logged, not silently dropped"
        )

    def test_reclaim_clears_inherited_topics_and_parking(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
        _stub_pty_factory,
    ) -> None:
        """C2: a reclaimed session must not show the dead session's topics
        and parking-lot. Before this fix, _start.py only touch()ed these
        files after a reclaim, so a crashed session's leftover content
        stayed visible to the new session."""
        _write_fixture("crashed-web-still-live")
        session_state.TOPICS_FILE.write_text(
            "- [09:00] Dead topic | status:learning | leftover from the crash\n"
        )
        session_state.PARKING_FILE.write_text("- Leftover parked question\n")

        resp = client.post(
            "/api/session/start",
            json={"topic": "Fresh topic", "energy": 5, "agent": "claude", "transport": "pty"},
        )

        assert resp.status_code == 201, resp.text
        assert session_state.parse_topics_file() == []
        assert session_state.parse_parking_file() == []

    def test_reclaim_never_kills_a_recorded_live_child_pid(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
        _stub_pty_factory,
        caplog,
        monkeypatch,
    ) -> None:
        """C4: reclaim never acts on a recorded child_pid -- it only logs
        it, so `clean`/`doctor` (R-01g, 0.2.0) can report the orphan later.
        Killing here would risk pid reuse, and it may be the user's own
        still-useful agent."""
        state = _fixture("crashed-web-still-live")
        state["child_pid"] = os.getpid()
        session_state.write_session_state(state)

        kill_calls: list[tuple[int, int]] = []
        real_kill = os.kill

        def _tracking_kill(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))
            real_kill(pid, sig)

        monkeypatch.setattr(os, "kill", _tracking_kill)

        resp = client.post(
            "/api/session/start",
            json={"topic": "Fresh topic", "energy": 5, "agent": "claude", "transport": "pty"},
        )

        assert resp.status_code == 201, resp.text
        # os.kill(pid, 0) is a liveness PROBE, not a termination signal --
        # only a real signal (SIGTERM=15, SIGKILL=9, ...) against this
        # process's own pid would mean "reclaim tried to kill it".
        assert not any(pid == os.getpid() and sig != 0 for pid, sig in kill_calls)
        reclaim_records = [rec for rec in caplog.records if "reclaim" in rec.message.lower()]
        assert len(reclaim_records) == 1
        assert f"child_pid={os.getpid()}" in reclaim_records[0].message


class TestForeignWebServerPid:
    """C3: claim_blocks_web_start now distinguishes "this process holds a
    stale claim from an earlier run" (always reclaimed, unchanged) from "a
    DIFFERENT, still-alive web server process holds a live pty/acp claim"
    (now blocks -- R-01b started recording pid on every web claim, so the
    check is cheap and cross-process)."""

    def test_a_foreign_live_web_server_pid_blocks_a_second_web_start(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
        _stub_pty_factory,
    ) -> None:
        state = _fixture("web-live")
        # pid 1 (init/launchd) always exists and is always foreign to the
        # test process -- portable stand-in for "a second, real web server".
        # _mock_agent_available/_stub_db/_stub_pty_factory keep a WRONGLY
        # unblocked request from reaching the real PTY spawn path (which
        # fails outside the main thread here) -- if the fix regresses, this
        # test must fail on a clean status-code assertion, not a spawn crash.
        state["pid"] = 1
        session_state.write_session_state(state)

        resp = client.post(
            "/api/session/start",
            json={"topic": "Async IO", "energy": 5, "agent": "claude", "transport": "pty"},
        )

        assert resp.status_code == 409, resp.text
        assert "already active" in resp.json()["error"]


class TestNoClaim:
    """Baseline: an ended (or absent) claim never blocks a start."""

    def test_an_ended_claim_never_blocks(
        self,
        client: TestClient,
        _mock_agent_available,
        _stub_db,
        _stub_pty_factory,
    ) -> None:
        _write_fixture("ended")

        resp = client.post(
            "/api/session/start",
            json={"topic": "Fresh topic", "energy": 5, "agent": "claude", "transport": "pty"},
        )

        assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# End matrix
# ---------------------------------------------------------------------------


class TestEndMatrix:
    """R-02, the fix. Ending a session must kill only that session's own
    multiplexer name -- never every study-* session on the machine."""

    def test_ending_a_pty_session_kills_no_multiplexer_session(self) -> None:
        """Web PTY/ACP sessions own no tmux/herdr session (session_name is
        None). Ending one must not fall back to killing everything -- that
        was the exact shape of the bug: a hypothetical concurrently-running
        CLI tmux session must survive untouched."""
        from studyloop.session.cleanup import _cleanup_tmux_and_files

        mock_mux = MagicMock()
        with patch("studyloop.multiplexer.get_backend", return_value=mock_mux):
            _cleanup_tmux_and_files(session_name=None, persona_file=None)

        mock_mux.kill_all_study_sessions.assert_not_called()
        mock_mux.kill_session.assert_not_called()

    def test_ending_a_cli_session_kills_only_its_own_tmux_name(self) -> None:
        """CLI end (`studyloop study --end`) must kill only its own tmux
        session -- a second, unrelated study-* session (CLI or web) must
        never be touched by this call."""
        from studyloop.session.cleanup import _cleanup_tmux_and_files

        mock_mux = MagicMock()
        with patch("studyloop.multiplexer.get_backend", return_value=mock_mux):
            _cleanup_tmux_and_files(session_name="study-cli-A", persona_file=None)

        mock_mux.kill_all_study_sessions.assert_not_called()
        mock_mux.kill_session.assert_called_once_with("study-cli-A")

    def test_web_end_common_never_reaches_for_kill_all(self, tmp_path) -> None:
        """end_session_common (the shared path both /session/end and
        `studyloop study --end` call) must never call kill_all_study_sessions,
        end to end, for a PTY-owned state dict."""
        from studyloop.session.cleanup import end_session_common

        state = _fixture("web-live")
        mock_mux = MagicMock()
        with (
            patch("studyloop.multiplexer.get_backend", return_value=mock_mux),
            patch("studyloop.history.end_study_session"),
            patch("studyloop.services.backlog.auto_persist_struggled"),
        ):
            end_session_common(state, auto_persist=False)

        mock_mux.kill_all_study_sessions.assert_not_called()
