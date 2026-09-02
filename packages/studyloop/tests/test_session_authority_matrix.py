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
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop import session_state
from studyloop.session import active
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
    """Existing behaviour, documented rather than changed: the CLI's own
    is_session_active() check blocks a second CLI start unconditionally,
    regardless of whether the recorded owner is actually still alive (see
    docs/architecture/session-authority.md's open questions). This lane does
    not touch session/start.py's CLI control flow."""

    def test_a_live_cli_claim_reports_active(self) -> None:
        _write_fixture("cli-live")

        assert session_state.is_session_active() is True


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
    """Already correctly refused today: session/start.py's own
    is_session_active() check blocks unconditionally when the file says a
    session -- of any kind -- is live. Documented and pinned, not changed."""

    def test_a_live_web_claim_reports_active(self) -> None:
        _write_fixture("web-live")

        assert session_state.is_session_active() is True


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
