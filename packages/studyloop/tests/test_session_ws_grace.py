"""WS detach grace period + single-attach policy.

Covers the fix for "a browser refresh destroys the live study session"
(``docs/handoffs/2026-08-04-ws-refresh-destroys-session-handoff.md``): a WS
close used to run ``active.release()`` unconditionally, which called
``transport.end()`` (killing the agent child) and wiped the IPC state.

Two layers here, deliberately:

* ``TestGraceModule`` — the lifecycle logic in ``_grace.py`` on its own,
  async and fast, with a fake transport. This is where the crux is proven:
  *client went away* holds the session, *agent exited* releases at once.
* ``TestWsGraceThroughRoute`` — the same behaviour through the real WS route
  with ``TestClient``, so the wiring in ``_ws.py``'s ``finally`` is covered,
  not just the helper it calls.

Two of the plan's cases cannot live here, because ``TestClient`` gives every
``websocket_connect`` its own blocking portal and tears that loop down when
the with-block exits:

* **reattach streams live output** — the second socket runs on a different
  loop, so a queue-backed double raises "bound to a different event loop".
* **grace expiry releases the session** — the grace timer is a task on the
  first socket's portal loop, which no longer exists to run it.

Both are real behaviours worth testing, so they run against a real uvicorn
process with a real PTY agent in ``tests/e2e/test_ws_grace_real_server.py``,
alongside the orphaned-process and server-shutdown assertions that also need
a real process to be meaningful.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import deque
from pathlib import Path

import pytest
from _helpers import run_async

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]
from starlette.websockets import WebSocketDisconnect

from studyloop.session import active
from studyloop.session.transport import (
    OutputBytes,
    SessionConfig,
    Started,
    Stopped,
)
from studyloop.web.app import create_app
from studyloop.web.routes.session import _grace

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]

# ---------------------------------------------------------------------------
# Fixtures & doubles
# ---------------------------------------------------------------------------


class HoldingTransport(StubTransport):
    """Buffer-backed fake that stays open like a real live PTY.

    Mirrors ``PTYTransport``'s shape on purpose: ``events()`` *drains* a buffer
    that something else fills, and the stream ends only on a ``None`` sentinel.
    That shape is exactly what makes reattach possible in production, so a
    double whose stream ends as soon as its preloaded events run out
    (``StubTransport``) cannot exercise the grace path at all — the route would
    correctly read the exhausted stream as "session over".

    The buffer is a polled ``deque``, not an ``asyncio.Queue``, and that is
    load-bearing rather than incidental: ``TestClient`` gives every
    ``websocket_connect`` its own blocking portal and therefore its own event
    loop, while an ``asyncio.Queue`` binds to the first loop that awaits it and
    then raises "bound to a different event loop" on the second socket — which
    is every test with two sockets on one session. Production has a single loop
    and a real queue; the double only needs the same *semantics*.

    ``is_running()`` is the duck-typed liveness probe the grace timer polls;
    set ``alive = False`` to simulate the agent exiting while detached.
    """

    #: Poll interval for the drain. Small enough to be invisible in tests.
    DRAIN_POLL_S = 0.01

    def __init__(self, events=()) -> None:
        super().__init__(events)
        self.alive = True
        self._buffer: deque = deque(events)

    def emit(self, event) -> None:
        """Append one event (or ``None`` to end the stream)."""
        self._buffer.append(event)

    async def events(self):
        while True:
            try:
                event = self._buffer.popleft()
            except IndexError:
                await asyncio.sleep(self.DRAIN_POLL_S)
                continue
            if event is None:
                return
            yield event

    def is_running(self) -> bool:
        return self.alive

    async def cancel(self) -> None:
        # Real PTY: SIGTERM → SIGCHLD → one Stopped, then the sentinel.
        await super().cancel()
        self.alive = False
        self.emit(Stopped(returncode=-15, reason="cancel"))
        self.emit(None)

    async def end(self) -> None:
        await super().end()
        self.alive = False
        self.emit(None)


@pytest.fixture(autouse=True)
def _reset_active_state():
    run_async(active.release())
    _grace.reset_for_tests()
    yield
    run_async(active.release())
    _grace.reset_for_tests()


@pytest.fixture(autouse=True)
def _isolate_session_dir(tmp_path, monkeypatch):
    from studyloop import session_state as ss

    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "STATE_FILE", tmp_path / "session-state.json")
    monkeypatch.setattr(ss, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(ss, "PARKING_FILE", tmp_path / "session-parking.md")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def config(tmp_path) -> SessionConfig:
    return SessionConfig(
        study_session_id="study-grace-1",
        agent="claude",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )


def _install_active(transport, config: SessionConfig) -> None:
    run_async(active.acquire(config, lambda: transport))


_WS_HEADERS = {"Host": "testserver", "Origin": "http://testserver"}


def _settle(predicate, what: str, timeout: float = 5.0) -> None:
    """Block until ``predicate()`` is true, else fail with ``what``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def _disconnect(ws, predicate, what: str) -> None:
    """Close ``ws`` from the client side and wait for the route to finish.

    Starlette's ``WebSocketTestSession.__exit__`` cancels the ASGI task
    (``stack.callback(portal.call, cs.cancel)``) immediately after queueing the
    disconnect. If the route is still mid-flight that cancellation escapes as a
    bare ``CancelledError`` from the with-block — and a route pumping a live,
    open event stream always *is* mid-flight, unlike the finite-stream
    ``StubTransport`` the existing WS tests use.

    Closing explicitly and waiting for the observable effect of the route's
    ``finally`` block avoids that, and has the better property besides:
    assertions then run against a settled lifecycle instead of racing it.
    """
    ws.close(1000)
    _settle(predicate, what)


# ---------------------------------------------------------------------------
# The lifecycle logic on its own
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGraceModule:
    """``_grace.py`` in isolation — fast, and where the crux is pinned."""

    async def _acquire(self, config: SessionConfig, transport) -> None:
        await active.acquire(config, lambda: transport)

    async def test_scheduled_release_holds_the_session_for_the_window(
        self, config: SessionConfig
    ) -> None:
        """Case 1: WS close must NOT end the session."""
        transport = HoldingTransport()
        await self._acquire(config, transport)

        _grace.schedule_release(config.study_session_id, grace=5.0)
        await asyncio.sleep(0.2)

        assert await active.current() is not None, "session released inside the grace window"
        assert transport.end_calls == 0, "agent was torn down inside the grace window"
        assert _grace.has_pending_release(config.study_session_id)

    async def test_reattach_inside_the_window_cancels_the_release(
        self, config: SessionConfig
    ) -> None:
        """Case 2 (server half): a reconnect stands the timer down."""
        transport = HoldingTransport()
        await self._acquire(config, transport)

        _grace.schedule_release(config.study_session_id, grace=0.4)
        assert _grace.cancel_pending_release(config.study_session_id) is True

        await asyncio.sleep(0.8)  # past what the window would have been
        assert await active.current() is not None
        assert transport.end_calls == 0
        assert not _grace.has_pending_release(config.study_session_id)

    async def test_no_reattach_releases_after_the_window(self, config: SessionConfig) -> None:
        """Case 3: the session is torn down once the window expires."""
        transport = HoldingTransport()
        await self._acquire(config, transport)

        _grace.schedule_release(config.study_session_id, grace=0.3)
        await asyncio.sleep(1.0)

        assert await active.current() is None
        assert transport.end_calls == 1
        assert not _grace.has_pending_release(config.study_session_id), "orphan timer left behind"

    async def test_agent_exit_while_detached_releases_immediately(
        self, config: SessionConfig
    ) -> None:
        """Case 4 — the crux.

        A detached session has no consumer draining ``events()``, so a
        ``Stopped`` event cannot be observed. The grace timer polls
        ``is_running()`` instead; without that, a dead agent would pin the
        single-session slot for the whole window and 409 the next start.
        """
        transport = HoldingTransport()
        await self._acquire(config, transport)

        _grace.schedule_release(config.study_session_id, grace=30.0)
        transport.alive = False  # agent exits while nobody is watching

        for _ in range(40):
            await asyncio.sleep(0.1)
            if await active.current() is None:
                break

        assert await active.current() is None, (
            "dead agent pinned the session slot — is_running() poll not working"
        )
        assert transport.end_calls == 1
        assert not _grace.has_pending_release(config.study_session_id)

    async def test_release_now_cancels_the_timer_and_releases(self, config: SessionConfig) -> None:
        """Case 5 (unit half): explicit end during the window, no orphan timer."""
        transport = HoldingTransport()
        await self._acquire(config, transport)

        _grace.schedule_release(config.study_session_id, grace=30.0)
        await _grace.release_now(config.study_session_id, reason="explicit_end")

        assert await active.current() is None
        assert transport.end_calls == 1
        assert _grace.pending_release_ids() == frozenset()

    async def test_timer_never_releases_a_session_it_does_not_own(
        self, config: SessionConfig, tmp_path
    ) -> None:
        """A stale timer must not tear down whatever started after it.

        Guards the race in the risks table: grace timer for session A still
        pending when session B is live.
        """
        first = HoldingTransport()
        await self._acquire(config, first)
        _grace.schedule_release(config.study_session_id, grace=0.3)

        # Session A ends and B takes the slot before A's timer fires.
        await active.release()
        second_config = SessionConfig(
            study_session_id="study-grace-2",
            agent="claude",
            persona_file=str(tmp_path / "persona.md"),
            cwd=str(tmp_path),
            env={},
            cols=80,
            rows=24,
        )
        second = HoldingTransport()
        await self._acquire(second_config, second)

        await asyncio.sleep(0.9)

        current = await active.current()
        assert current is not None, "stale timer released the wrong session"
        assert current.study_session_id == "study-grace-2"
        assert second.end_calls == 0

    async def test_shutdown_releases_a_detached_session(self, config: SessionConfig) -> None:
        """Case 8 (unit half): no agent survives a server stop mid-window."""
        transport = HoldingTransport()
        await self._acquire(config, transport)
        _grace.schedule_release(config.study_session_id, grace=300.0)

        await _grace.shutdown()

        assert await active.current() is None
        assert transport.end_calls == 1
        assert _grace.pending_release_ids() == frozenset()

    async def test_grace_expiry_is_recorded_for_the_learner(self, config: SessionConfig) -> None:
        """Decision 4: a vanished session must be explainable afterwards."""
        transport = HoldingTransport()
        await self._acquire(config, transport)

        _grace.schedule_release(config.study_session_id, grace=0.2)
        await asyncio.sleep(0.9)

        last = _grace.last_release()
        assert last is not None
        assert last["reason"] == "grace_expired"
        assert last["study_session_id"] == config.study_session_id

    async def test_consumer_slot_is_single_entry_and_newest_wins(self) -> None:
        """One consumer at a time, and a newcomer displaces the incumbent.

        Refusing the newcomer instead was measured to lock a learner out of
        their own live session — see the Consumer slot notes in ``_grace.py``.
        """
        first, displaced = await _grace.acquire_consumer("a")
        assert displaced is None
        assert _grace.attached_session_id() == "a"

        first.released = True  # stand in for the holder's finally
        second, displaced = await _grace.acquire_consumer("a")
        assert displaced is first
        assert first.superseded is True, "incumbent was not told it lost the stream"
        assert _grace.attached_session_id() == "a"

        # A superseded holder must never clear its successor's claim — this is
        # the "next session refused with a 403" race.
        _grace.release_consumer(first)
        assert _grace.attached_session_id() == "a"

        _grace.release_consumer(second)
        assert _grace.attached_session_id() is None

    async def test_takeover_waits_for_the_incumbent_to_stop_draining(self) -> None:
        """Bounded wait, so output can never be split between two sockets."""
        first, _ = await _grace.acquire_consumer("a")

        async def _release_soon() -> None:
            await asyncio.sleep(0.15)
            _grace.release_consumer(first)

        task = asyncio.create_task(_release_soon())
        started = time.monotonic()
        _, displaced = await _grace.acquire_consumer("a", timeout=3.0)
        waited = time.monotonic() - started
        await task

        assert displaced is first
        assert waited >= 0.1, "takeover did not wait for the incumbent to release"

    async def test_takeover_gives_up_waiting_on_a_wedged_incumbent(self) -> None:
        """A half-open socket must not lock the learner out of their session."""
        first, _ = await _grace.acquire_consumer("a")  # never releases

        started = time.monotonic()
        mine, displaced = await _grace.acquire_consumer("a", timeout=0.3)
        waited = time.monotonic() - started

        assert displaced is first
        assert 0.25 <= waited < 2.0, f"unbounded or skipped wait: {waited:.2f}s"
        assert _grace.attached_session_id() == "a"
        assert mine.superseded is False

    async def test_releasing_a_session_frees_its_consumer_slot(self, config: SessionConfig) -> None:
        """Slot lifetime follows the session, not a socket handler's finally.

        Without this, "refresh -> End -> Start" left the next session's first
        WebSocket refused by a claim belonging to a session already gone.
        """
        transport = HoldingTransport()
        await self._acquire(config, transport)
        await _grace.acquire_consumer(config.study_session_id)

        await _grace.release_now(config.study_session_id, reason="explicit_end")

        assert _grace.attached_session_id() is None, "consumer slot leaked past the session"

    async def test_transport_without_a_liveness_probe_is_assumed_alive(
        self, config: SessionConfig
    ) -> None:
        """Duck-typing must degrade to plain sleep, not crash or release early."""
        transport = StubTransport(events=[Started(agent="claude")])
        assert not hasattr(transport, "is_running")
        await self._acquire(config, transport)

        _grace.schedule_release(config.study_session_id, grace=1.5)
        await asyncio.sleep(0.4)

        assert await active.current() is not None
        assert transport.end_calls == 0


# ---------------------------------------------------------------------------
# The same behaviour through the real route
# ---------------------------------------------------------------------------


class TestWsGraceThroughRoute:
    """``_ws.py``'s finally block — the wiring, not just the helper it calls."""

    def test_client_disconnect_schedules_instead_of_releasing(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """The headline defect: a page reload is a plain disconnect. Hold on."""
        transport = HoldingTransport(events=[Started(agent="claude")])
        _install_active(transport, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws:
            assert ws.receive_json() == {"type": "started", "agent": "claude"}
            _disconnect(
                ws,
                lambda: _grace.has_pending_release("study-grace-1"),
                "the grace timer to be scheduled",
            )

        assert run_async(active.current()) is not None, "WS close destroyed the session"
        assert transport.end_calls == 0, "agent was torn down by a mere disconnect"

        state = client.get("/api/session/state").json()
        assert state.get("study_session_id") == "study-grace-1", "IPC state was wiped"

    def test_reattach_after_disconnect_streams_live_output(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """Case 2: a second WS on the same session gets live agent output.

        This is why the fix is small — ``events()`` is a drain, so a second
        call is just a new generator over the same buffer. No transport API.
        """
        transport = HoldingTransport(events=[Started(agent="claude")])
        _install_active(transport, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws:
            ws.receive_json()
            _disconnect(
                ws,
                lambda: _grace.has_pending_release("study-grace-1"),
                "the grace timer to be scheduled",
            )

        assert run_async(active.current()) is not None

        # Output produced while nobody was attached survives — the bounded ring
        # buffer keeps the newest bytes, which is what a reattaching terminal
        # wants (decision 3: no scrollback replay, but nothing lost mid-flight).
        transport.emit(OutputBytes(data=b"emitted while detached"))

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws2:
            assert ws2.receive_bytes() == b"emitted while detached"
            assert not _grace.has_pending_release("study-grace-1"), (
                "reattach did not stand the release timer down"
            )
            ws2.send_json({"type": "input", "data": "still alive?\n"})
            _settle(
                lambda: transport.sent_input[-1:] == [b"still alive?\n"],
                "reattached input to reach the agent",
            )
            _disconnect(
                ws2,
                lambda: _grace.has_pending_release("study-grace-1"),
                "the second grace timer to be scheduled",
            )

        assert run_async(active.current()) is not None
        assert transport.end_calls == 0

    def test_stopped_event_releases_immediately(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """Case 4 through the route: agent exit must not wait out the window."""
        transport = HoldingTransport(
            events=[Started(agent="claude"), Stopped(returncode=0, reason="exit")]
        )
        _install_active(transport, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws:
            ws.receive_json()
            assert ws.receive_json() == {"type": "stopped", "returncode": 0, "reason": "exit"}
            _disconnect(
                ws,
                lambda: run_async(active.current()) is None,
                "the dead session to be released at once",
            )

        assert transport.end_calls == 1
        assert not _grace.has_pending_release("study-grace-1"), (
            "a dead agent was given the full grace window, pinning the slot"
        )

    def test_stop_frame_releases_immediately(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """The learner pressing Stop is explicit intent, not a disconnect."""
        transport = HoldingTransport(events=[Started(agent="claude")])
        _install_active(transport, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws:
            ws.receive_json()
            ws.send_json({"type": "stop"})
            _settle(lambda: transport.cancel_calls == 1, "cancel() to reach the transport")
            _disconnect(
                ws,
                lambda: run_async(active.current()) is None,
                "the stopped session to be released at once",
            )

        assert not _grace.has_pending_release("study-grace-1")

    def test_exhausted_event_stream_releases_immediately(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """A stream that ends without Stopped still means the session is over.

        ``transport.end()`` pushes the queue sentinel, so ``events()`` can
        return with no terminal event ever observed. Treating that as "client
        went away" would hold a dead session for the whole window — and it is
        also the shape every pre-existing ``StubTransport`` WS test relies on.
        """
        transport = StubTransport(events=[Started(agent="claude")])
        _install_active(transport, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws:
            ws.receive_json()
            _disconnect(
                ws,
                lambda: run_async(active.current()) is None,
                "the finished session to be released",
            )

        assert transport.end_calls == 1

    def test_second_attach_takes_over_and_output_is_never_split(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """Case 7. Pre-existing defect: two sockets used to SPLIT the output.

        ``events()`` is a drain, so each event went to exactly one consumer —
        opening the dashboard in two tabs left both terminals showing a random
        partial half and neither correct. Now the newer socket takes the stream
        over and the displaced one is told where its session went.
        """
        transport = HoldingTransport(events=[Started(agent="claude")])
        _install_active(transport, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws_a:
            assert ws_a.receive_json() == {"type": "started", "agent": "claude"}

            with client.websocket_connect(
                "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
            ) as ws_b:
                # A is told where its session went, on its own connection.
                assert ws_a.receive_json() == {
                    "type": "attach_superseded",
                    "reason": "taken_over",
                    "message": (
                        "This study session was opened in another tab or window, "
                        "which now has the live terminal."
                    ),
                }
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws_a.receive_json()  # server closed A
                assert exc_info.value.code == 1008

                # B owns the stream — whole, not a random half of it.
                assert _grace.attached_session_id() == "study-grace-1"
                transport.emit(OutputBytes(data=b"only B sees this"))
                assert ws_b.receive_bytes() == b"only B sees this"

                _disconnect(
                    ws_b,
                    lambda: _grace.has_pending_release("study-grace-1"),
                    "B's grace timer to be scheduled",
                )

        # Displacing a consumer must not end the session or start a death clock
        # the new consumer never asked for.
        assert run_async(active.current()) is not None
        assert transport.end_calls == 0

    def test_end_route_during_the_window_releases_at_once(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """Case 5: ``POST /api/session/end`` beats the timer, no orphan left."""
        transport = HoldingTransport(events=[Started(agent="claude")])
        _install_active(transport, config)

        from studyloop import session_state

        session_state.write_session_state(
            {"study_session_id": "study-grace-1", "agent": "claude", "topic": "Decorators"}
        )

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws:
            ws.receive_json()
            _disconnect(
                ws,
                lambda: _grace.has_pending_release("study-grace-1"),
                "the grace timer to be scheduled",
            )

        resp = client.post("/api/session/end")
        assert resp.status_code == 200, resp.text
        assert run_async(active.current()) is None
        assert transport.end_calls == 1
        assert _grace.pending_release_ids() == frozenset(), "orphan grace timer survived end"

    def test_start_during_the_window_409s_with_a_reattach_hint(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """Case 6: refuse clearly rather than silently pre-empt a live agent."""
        transport = HoldingTransport(events=[Started(agent="claude")])
        _install_active(transport, config)

        from studyloop import session_state

        session_state.write_session_state(
            {"study_session_id": "study-grace-1", "agent": "claude", "topic": "Decorators"}
        )

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-grace-1", headers=_WS_HEADERS
        ) as ws:
            ws.receive_json()
            _disconnect(
                ws,
                lambda: _grace.has_pending_release("study-grace-1"),
                "the grace timer to be scheduled",
            )

        resp = client.post(
            "/api/session/start",
            json={"topic": "Something else", "energy": 5, "transport": "pty"},
        )
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert "Decorators" in body["error"], body
        assert body["detached"] is True
        assert body["study_session_id"] == "study-grace-1"
        assert body["reattach_url"] == "/api/session/ws?study_session_id=study-grace-1"
