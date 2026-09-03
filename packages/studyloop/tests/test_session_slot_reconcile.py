"""One source of truth for "is a study session live?", and a way back out.

The reported bug: starting a Study Session fails forever with

    A session for 'your last topic' is still active — its browser tab closed
    but the agent is still running. Reattach to it, or end it first.

with no way out. That message is only reachable when the in-process
single-session slot (``session/active.py::_active``) and the IPC state file
(``session-state.json``) disagree: the slot says "live" so ``POST
/api/session/start`` refuses, while the file says "nothing here" so the UI
shows the start picker and the 409's topic lookup falls back to the literal
string ``'your last topic'``. That fallback firing at all is *proof* of
desync, because a healthy session always writes ``topic``.

Four defects made that state reachable and unescapable. One class each:

* ``TestStateAndStartAgree`` — the two endpoints read different sources.
* ``TestZombieClearingCannotOrphanTheSlot`` — legacy tmux zombie detection
  deletes the state file without touching the slot.
* ``TestReaperReleasesSessionsNothingElseCan`` — a session whose WebSocket
  never attaches gets no grace timer and no liveness poll at all, so the slot
  is pinned until the server restarts.
* ``TestOutOfProcessEnds`` — ``studyloop session end`` / ``studyloop clean``
  run in another process and cannot reach the slot.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop import session_state
from studyloop.session import active
from studyloop.session.transport import SessionConfig
from studyloop.web.app import create_app
from studyloop.web.routes.session import _grace, _ipc

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

SESSION_ID = "study-slot-1"


class FakeTransport(StubTransport):
    """StubTransport plus the duck-typed liveness probe the reaper polls.

    ``alive = False`` stands in for "the agent child exited while nothing was
    watching" — the case a detached session cannot observe for itself, because
    ``events()`` is a drain with no consumer.
    """

    def __init__(self, events=()) -> None:
        super().__init__(events)
        self.alive = True

    def is_running(self) -> bool:
        return self.alive

    async def end(self) -> None:
        await super().end()
        self.alive = False


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

    ``_ipc.py`` binds ``STATE_FILE`` at import time and *unlinks* it on the
    zombie path, so patching ``session_state`` alone would leave a red run
    deleting the developer's real ``~/.config/studyloop/session-state.json``.
    """
    for module in (session_state, _ipc):
        for name, filename in (
            ("STATE_FILE", "session-state.json"),
            ("TOPICS_FILE", "session-topics.md"),
            ("PARKING_FILE", "session-parking.md"),
        ):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, tmp_path / filename)
    monkeypatch.setattr(session_state, "SESSION_DIR", tmp_path)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def config(tmp_path) -> SessionConfig:
    return SessionConfig(
        study_session_id=SESSION_ID,
        agent="claude",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )


def _install_active(transport, config: SessionConfig) -> None:
    run_async(active.acquire(config, lambda: transport))


def _write_healthy_state(topic: str = "Decorators") -> None:
    session_state.write_session_state(
        {
            "study_session_id": SESSION_ID,
            "agent": "claude",
            "topic": topic,
            "mode": "focus",
            "transport": "pty",
        }
    )


# ---------------------------------------------------------------------------
# Defect 1 — two sources of truth
# ---------------------------------------------------------------------------


class TestStateAndStartAgree:
    """``/session/state`` and ``/session/start`` must never disagree.

    When they do, the UI shows the start picker *and* the backend 409s every
    click on it. There is no button that resolves that, which is exactly the
    "no way out" in the report.
    """

    def test_state_reports_the_slot_when_the_ipc_file_is_gone(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        transport = FakeTransport()
        _install_active(transport, config)
        session_state.STATE_FILE.unlink(missing_ok=True)

        state = client.get("/api/session/state").json()

        assert state.get("study_session_id") == SESSION_ID, (
            "the live slot was invisible to /session/state — the picker would show"
        )
        assert state.get("mode") != "ended"
        assert state.get("agent") == "claude"

    def test_state_reports_the_slot_when_the_file_says_ended(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """An out-of-process ``session end`` leaves ``mode=ended`` behind."""
        transport = FakeTransport()
        _install_active(transport, config)
        session_state.write_session_state({"study_session_id": SESSION_ID, "mode": "ended"})

        state = client.get("/api/session/state").json()

        assert state.get("study_session_id") == SESSION_ID
        assert state.get("mode") != "ended", "a live slot was reported as an ended session"

    def test_state_carries_the_reattach_hint_the_409_carries(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """Same affordance from both endpoints, so the UI never needs a 409."""
        transport = FakeTransport()
        _install_active(transport, config)
        _write_healthy_state()

        async def _detach() -> None:
            # schedule_release creates a task, so it needs a running loop.
            _grace.schedule_release(SESSION_ID, grace=30.0)

        run_async(_detach())

        state = client.get("/api/session/state").json()

        assert state["detached"] is True
        assert state["reattach_url"] == f"/api/session/ws?study_session_id={SESSION_ID}"

    def test_an_empty_slot_still_falls_back_to_the_file(self, client: TestClient) -> None:
        """Legacy ttyd sessions never touch the slot — don't erase them."""
        session_state.write_session_state(
            {"study_session_id": "legacy-1", "topic": "tmux things", "mode": "focus"}
        )

        state = client.get("/api/session/state").json()

        assert state.get("study_session_id") == "legacy-1"


# ---------------------------------------------------------------------------
# Defect 2 — zombie clearing wipes state without releasing the singleton
# ---------------------------------------------------------------------------


class TestZombieClearingCannotOrphanTheSlot:
    """The cleanest explanation of the reported bug, reproduced end to end.

    ``write_session_state`` is a read-merge-write, so a PTY session started
    after a legacy ttyd session inherits that session's dead ``tmux_session``
    key. ``_get_full_state`` then classifies the *live* PTY session as a tmux
    zombie and deletes its state file — leaving the slot occupied and the file
    gone, which is precisely the desync.
    """

    def test_a_stale_tmux_key_does_not_wipe_a_live_slot(self, config: SessionConfig) -> None:
        transport = FakeTransport()
        _install_active(transport, config)
        session_state.write_session_state(
            {
                "study_session_id": SESSION_ID,
                "topic": "Decorators",
                "mode": "focus",
                "transport": "pty",
                "tmux_session": "study-dead-12345678",  # inherited from a legacy session
            }
        )

        state = _ipc._get_full_state()

        assert state.get("study_session_id") == SESSION_ID, (
            "a live PTY session was mistaken for a dead tmux session and wiped"
        )
        assert session_state.STATE_FILE.exists(), "the live session's state file was deleted"

    def test_a_pty_start_payload_clears_inherited_tmux_keys(self) -> None:
        """Fix the leak at the source: a PTY/ACP start owns no tmux session."""
        from datetime import UTC, datetime

        from studyloop.web.services.session_start import build_session_state_payload

        payload = build_session_state_payload(
            study_id="x",
            topic="Decorators",
            energy=5,
            energy_label="medium",
            agent="claude",
            session_dir="/tmp/x",
            persona_hash="abc",
            transport="pty",
            now=datetime.now(UTC),
        )

        assert payload["tmux_session"] is None, (
            "a PTY start leaves the previous session's tmux_session in place"
        )

    def test_a_genuine_legacy_zombie_is_still_cleared(self, monkeypatch) -> None:
        """Don't regress the behaviour this branch exists for."""
        monkeypatch.setattr(_ipc, "_is_tmux_session_alive", lambda _name: False)
        session_state.write_session_state(
            {"study_session_id": "legacy-1", "mode": "focus", "tmux_session": "study-dead"}
        )

        state = _ipc._get_full_state()

        assert state.get("study_session_id") is None
        assert not session_state.STATE_FILE.exists()

    def test_zombie_clearing_survives_a_stale_ttyd_pid_in_state(self, monkeypatch) -> None:
        """Characterisation test, written before ttyd retirement stage 5 removes
        `_kill_stale_ttyd()`: the zombie-clearing reconcile above (`_ipc.py:44-64`)
        must keep clearing dead-tmux state even when the stale state dict still
        carries a leftover `ttyd_pid` key from before ttyd was retired — only the
        ttyd-kill call goes, never the clearing itself. Fixture data mirrors a
        config.yaml written before ttyd retirement stage 2, whose session-state.json
        still names a ttyd_pid nothing will ever kill again.
        """
        monkeypatch.setattr(_ipc, "_is_tmux_session_alive", lambda _name: False)
        session_state.write_session_state(
            {
                "study_session_id": "legacy-ttyd-1",
                "mode": "focus",
                "tmux_session": "study-dead-ttyd",
                "ttyd_pid": 999999,  # leftover from a pre-retirement session; unkillable
                "ttyd_port": 7681,
            }
        )

        state = _ipc._get_full_state()

        assert state.get("study_session_id") is None, "zombie state was not cleared"
        assert not session_state.STATE_FILE.exists()

    def test_the_reported_bug_is_escapable(self, client: TestClient, config: SessionConfig) -> None:
        """The whole loop: picker shown, every start 409s, 'your last topic'."""
        transport = FakeTransport()
        _install_active(transport, config)
        session_state.write_session_state(
            {
                "study_session_id": SESSION_ID,
                "topic": "Decorators",
                "mode": "focus",
                "transport": "pty",
                "tmux_session": "study-dead-12345678",
            }
        )

        state = client.get("/api/session/state").json()
        assert state.get("study_session_id") == SESSION_ID, "picker would be shown"

        resp = client.post(
            "/api/session/start",
            json={"topic": "Something else", "energy": 5, "transport": "pty"},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert "your last topic" not in body["error"], (
            "the desync fallback fired — state and slot still disagree"
        )
        assert body["topic"] == "Decorators"
        assert body["reattach_url"] == f"/api/session/ws?study_session_id={SESSION_ID}"

    def test_the_409_never_borrows_another_sessions_topic(self, config: SessionConfig) -> None:
        """A mismatched id in the file must not be presented as this session."""
        transport = FakeTransport()
        _install_active(transport, config)
        session_state.write_session_state(
            {"study_session_id": "some-other-session", "topic": "Not mine", "mode": "focus"}
        )

        from studyloop.web.routes.session._start import _session_conflict

        # The in-process singleton (_install_active above) is checked
        # first and returns before this reservation would ever be used --
        # C1 (council) made _session_conflict take one, so any call site
        # needs one, even a path that never reaches the file-claim branch.
        reservation = {"study_session_id": "unused", "mode": "starting"}
        response = run_async(_session_conflict(reservation))
        assert response is not None
        import json

        body = json.loads(bytes(response.body))
        assert body["topic"] != "Not mine"


# ---------------------------------------------------------------------------
# Defect 3 — no liveness reaper outside the grace window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReaperReleasesSessionsNothingElseCan:
    """``schedule_release`` only ever runs on WS *disconnect*.

    A session whose WebSocket never attaches — origin check refused, proxy ate
    the upgrade, JS error before mount — therefore has no grace timer and no
    liveness poll of any kind. Its slot is pinned until the process restarts.
    """

    async def _acquire(self, config: SessionConfig, transport) -> None:
        await active.acquire(config, lambda: transport)

    async def test_a_session_that_never_attached_is_released(self, config: SessionConfig) -> None:
        transport = FakeTransport()
        await self._acquire(config, transport)
        _write_healthy_state()

        reason = await _grace.reap_once(unattached_grace=0.0, min_age=0.0)

        assert reason == "never_attached"
        assert await active.current() is None, "the slot stayed pinned forever"
        assert transport.end_calls == 1

    async def test_an_attached_session_is_left_alone(self, config: SessionConfig) -> None:
        transport = FakeTransport()
        await self._acquire(config, transport)
        _write_healthy_state()
        await _grace.acquire_consumer(SESSION_ID)

        assert await _grace.reap_once(unattached_grace=0.0, min_age=0.0) is None
        assert await active.current() is not None

    async def test_a_session_that_has_attached_before_is_left_alone(
        self, config: SessionConfig
    ) -> None:
        """Detach is the grace timer's job, not the reaper's."""
        transport = FakeTransport()
        await self._acquire(config, transport)
        _write_healthy_state()
        attachment, _ = await _grace.acquire_consumer(SESSION_ID)
        _grace.release_consumer(attachment)

        assert await _grace.reap_once(unattached_grace=0.0, min_age=0.0) is None
        assert await active.current() is not None

    async def test_a_dead_agent_is_released_even_though_nothing_ever_attached(
        self, config: SessionConfig
    ) -> None:
        transport = FakeTransport()
        await self._acquire(config, transport)
        _write_healthy_state()
        transport.alive = False

        reason = await _grace.reap_once()

        assert reason == "agent_exited"
        assert await active.current() is None

    async def test_the_grace_timer_owns_a_detached_session(self, config: SessionConfig) -> None:
        """Two clocks on one session would race over the release reason."""
        transport = FakeTransport()
        await self._acquire(config, transport)
        _write_healthy_state()
        _grace.schedule_release(SESSION_ID, grace=30.0)

        assert await _grace.reap_once(unattached_grace=0.0, min_age=0.0) is None
        assert await active.current() is not None

        _grace.cancel_pending_release(SESSION_ID)

    async def test_a_release_is_explained_to_the_learner(self, config: SessionConfig) -> None:
        transport = FakeTransport()
        await self._acquire(config, transport)
        _write_healthy_state()

        await _grace.reap_once(unattached_grace=0.0, min_age=0.0)

        last = _grace.last_release()
        assert last is not None
        assert last["reason"] == "never_attached"
        assert last["study_session_id"] == SESSION_ID

    async def test_the_reaper_survives_a_failing_tick(
        self, config: SessionConfig, monkeypatch
    ) -> None:
        """One bad tick must not kill the loop and re-pin the slot forever."""
        transport = FakeTransport()
        await self._acquire(config, transport)

        def _boom(_transport) -> bool:
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(_grace, "_transport_alive", _boom)
        _grace.start_reaper(interval=0.01)
        await asyncio.sleep(0.1)

        assert _grace.reaper_running(), "a single failing tick killed the reaper"
        await _grace.stop_reaper()

    async def test_the_reaper_stops_cleanly(self, config: SessionConfig) -> None:
        _grace.start_reaper(interval=0.01)
        assert _grace.reaper_running()
        await _grace.stop_reaper()
        assert not _grace.reaper_running()


def test_the_reaper_runs_for_the_life_of_the_app() -> None:
    """Wired into the lifespan, or it protects nothing in production."""
    with TestClient(create_app()):
        assert _grace.reaper_running(), "no reaper task was started with the app"
    assert not _grace.reaper_running(), "the reaper outlived the app"


# ---------------------------------------------------------------------------
# Defect 4 — out-of-process ends cannot clear the in-process singleton
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOutOfProcessEnds:
    """``studyloop session end`` and ``studyloop clean`` run elsewhere.

    Neither can reach the web server's ``_active``; the server has to notice
    for itself or the slot stays occupied by a session the learner has already
    ended from a terminal.
    """

    async def _acquire(self, config: SessionConfig, transport) -> None:
        await active.acquire(config, lambda: transport)

    async def test_a_cli_session_end_releases_the_slot(self, config: SessionConfig) -> None:
        """``cli/_session.py`` keeps the file and marks ``mode=ended``."""
        transport = FakeTransport()
        await self._acquire(config, transport)
        _write_healthy_state()
        session_state.write_session_state({"mode": "ended"})

        reason = await _grace.reap_once(min_age=0.0)

        assert reason == "ended_out_of_process"
        assert await active.current() is None
        assert transport.end_calls == 1

    async def test_studyloop_clean_releases_the_slot(self, config: SessionConfig) -> None:
        """``studyloop clean`` deletes the state file outright."""
        transport = FakeTransport()
        await self._acquire(config, transport)
        _write_healthy_state()
        session_state.STATE_FILE.unlink()

        reason = await _grace.reap_once(min_age=0.0)

        assert reason == "state_file_cleared"
        assert await active.current() is None

    async def test_a_different_session_in_the_file_releases_the_slot(
        self, config: SessionConfig
    ) -> None:
        transport = FakeTransport()
        await self._acquire(config, transport)
        session_state.write_session_state(
            {"study_session_id": "someone-else", "mode": "focus", "topic": "Other"}
        )

        assert await _grace.reap_once(min_age=0.0) == "state_file_replaced"
        assert await active.current() is None

    async def test_a_just_started_session_is_never_reaped(self, config: SessionConfig) -> None:
        """``acquire`` writes the state file *after* filling the slot.

        Reaping inside that window would kill sessions a fraction of a second
        after the learner started them — worse than the bug being fixed.
        """
        transport = FakeTransport()
        await self._acquire(config, transport)
        session_state.STATE_FILE.unlink(missing_ok=True)

        assert await _grace.reap_once() is None, "reaped a session younger than the min age"
        assert await active.current() is not None

    async def test_an_ended_session_state_is_not_resurrected(self, config: SessionConfig) -> None:
        """``/session/end`` deletes the file, then cleanup used to re-create it.

        The resurrected file held only ``{"mode": "ended"}`` — no id, no topic,
        nothing the dashboard summary needs. Litter that outlives the session
        and confuses the next desync diagnosis.
        """
        from studyloop.session.cleanup import _signal_dashboard_ended

        session_state.STATE_FILE.unlink(missing_ok=True)
        _signal_dashboard_ended()

        assert not session_state.STATE_FILE.exists(), "a deleted state file was re-created"

    async def test_an_existing_session_state_is_still_marked_ended(self) -> None:
        _write_healthy_state()

        from studyloop.session.cleanup import _signal_dashboard_ended

        _signal_dashboard_ended()

        assert session_state.read_session_state()["mode"] == "ended"
