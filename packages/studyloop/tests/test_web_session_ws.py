"""Tests for the /api/session/ws WebSocket route (§1.5 FastAPI wiring).

Exercises the new transport-based WS route against a ``StubTransport``
installed through ``active.acquire`` — no real ``pty.fork()``. Real-PTY
coverage stays in ``test_pty_transport.py``.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md §1.5

Tests are synchronous so FastAPI's ``TestClient.websocket_connect()``
(which runs its own portal) doesn't collide with ``pytest-asyncio``'s
loop. The active-session singleton is seeded from sync code via
``asyncio.run`` before the WS handshake.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

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

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from conftest import StubTransport  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_active_state():
    """Clear the active-session singleton around every test."""
    asyncio.run(active.release())
    yield
    asyncio.run(active.release())


@pytest.fixture(autouse=True)
def _isolate_session_dir(tmp_path, monkeypatch):
    """Redirect session_state writes into tmp_path so tests don't leak."""
    from studyloop import session_state as ss

    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "STATE_FILE", tmp_path / "session-state.json")
    monkeypatch.setattr(ss, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(ss, "PARKING_FILE", tmp_path / "session-parking.md")


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


@pytest.fixture()
def config(tmp_path) -> SessionConfig:
    return SessionConfig(
        study_session_id="study-1",
        agent="claude",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )


def _install_active(stub: StubTransport, config: SessionConfig) -> None:
    """Seed the module-level singleton with ``stub`` under ``config``.

    ``active.acquire`` is async; the test body runs synchronously so we
    pump it through ``asyncio.run``. A fresh loop is fine — acquire only
    needs a running loop for session_state writes via run_in_executor.
    """
    asyncio.run(active.acquire(config, lambda: stub))


# ---------------------------------------------------------------------------
# Origin guard (plan Blocker B1)
# ---------------------------------------------------------------------------


class TestOriginGuard:
    def test_rejects_ws_with_disallowed_origin(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """Cross-origin WS upgrade must be refused before accept()."""
        stub = StubTransport(events=[Started(agent="claude")])
        _install_active(stub, config)

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/api/session/ws?study_session_id=study-1",
                headers={"Origin": "https://evil.example.com"},
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008


# ---------------------------------------------------------------------------
# Session-id query param check (pattern from terminal_proxy.py:134)
# ---------------------------------------------------------------------------


class TestSessionIdGuard:
    def test_rejects_mismatched_session_id(self, client: TestClient, config: SessionConfig) -> None:
        stub = StubTransport(events=[Started(agent="claude")])
        _install_active(stub, config)

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/api/session/ws?study_session_id=other-id",
                headers={"Origin": "http://127.0.0.1:8788"},
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008


# ---------------------------------------------------------------------------
# No active session — connecting without acquire returns 1008
# ---------------------------------------------------------------------------


class TestNoActiveSession:
    def test_rejects_ws_when_no_active_session(self, client: TestClient) -> None:
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect(
                "/api/session/ws?study_session_id=whatever",
                headers={"Origin": "http://127.0.0.1:8788"},
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008


# ---------------------------------------------------------------------------
# Happy path — pump transport events to WS, accept JSON control frames
# ---------------------------------------------------------------------------


class TestTransportPump:
    def test_streams_started_then_output_then_stopped(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """Started/OutputBytes/Stopped land as the correct frame shapes."""
        stub = StubTransport(
            events=[
                Started(agent="claude"),
                OutputBytes(data=b"hello\n"),
                Stopped(returncode=0, reason="exit"),
            ]
        )
        _install_active(stub, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers={"Origin": "http://127.0.0.1:8788"},
        ) as ws:
            first = ws.receive_json()
            assert first == {"type": "started", "agent": "claude"}

            out = ws.receive_bytes()
            assert out == b"hello\n"

            last = ws.receive_json()
            assert last == {"type": "stopped", "returncode": 0, "reason": "exit"}

    def test_inbound_input_frame_sends_to_transport(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        stub = StubTransport(events=[Started(agent="claude")])
        _install_active(stub, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers={"Origin": "http://127.0.0.1:8788"},
        ) as ws:
            ws.receive_json()  # drain Started
            ws.send_json({"type": "input", "data": "ls\n"})
            # Briefly wait for the server's ws_to_pty task to consume it.
            time.sleep(0.1)
            ws.close()

        assert stub.sent_input == [b"ls\n"]

    def test_inbound_resize_frame_calls_transport(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        stub = StubTransport(events=[Started(agent="claude")])
        _install_active(stub, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers={"Origin": "http://127.0.0.1:8788"},
        ) as ws:
            ws.receive_json()
            ws.send_json({"type": "resize", "cols": 120, "rows": 40})
            time.sleep(0.1)
            ws.close()

        assert stub.resize_calls == [(120, 40)]

    def test_inbound_stop_frame_cancels_transport(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        stub = StubTransport(events=[Started(agent="claude")])
        _install_active(stub, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers={"Origin": "http://127.0.0.1:8788"},
        ) as ws:
            ws.receive_json()
            ws.send_json({"type": "stop"})
            time.sleep(0.1)
            ws.close()

        assert stub.cancel_calls == 1


# ---------------------------------------------------------------------------
# permission_response frame — U6 duck-typed forwarding
# ---------------------------------------------------------------------------


class TestPermissionResponseForwarding:
    def test_permission_response_forwarded_when_transport_has_send_permission(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """When the transport has send_permission (ACP path), a
        permission_response WS frame must call it with the right args."""
        stub = StubTransport(events=[Started(agent="kiro")])
        _install_active(stub, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers={"Origin": "http://127.0.0.1:8788"},
        ) as ws:
            ws.receive_json()  # drain Started
            ws.send_json(
                {
                    "type": "permission_response",
                    "toolCallId": "tc-99",
                    "optionId": "opt-allow",
                }
            )
            # Allow the server's ws_to_pty task to consume the frame.
            time.sleep(0.1)
            ws.close()

        assert stub.permission_calls == [("tc-99", "opt-allow")]

    def test_permission_response_is_silent_noop_when_transport_lacks_send_permission(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        """PTYTransport has no send_permission — frame must be silently
        dropped without any error or exception."""
        import types

        # Build a stub that deliberately does NOT have send_permission.
        stub = StubTransport(events=[Started(agent="claude")])

        class _NoPerm:
            """Mirrors StubTransport but omits send_permission — models PTYTransport."""

            def __init__(self) -> None:
                self._inner = stub

            async def start(self, config):  # type: ignore[override]
                return await self._inner.start(config)

            async def send_input(self, data: bytes) -> None:
                return await self._inner.send_input(data)

            async def resize(self, cols: int, rows: int) -> None:
                return await self._inner.resize(cols, rows)

            async def events(self):  # type: ignore[override]
                async for ev in self._inner.events():
                    yield ev

            async def cancel(self) -> None:
                return await self._inner.cancel()

            async def end(self) -> None:
                return await self._inner.end()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info: object) -> None:
                await self.end()

        pty_like = _NoPerm()
        asyncio.run(active.release())
        asyncio.run(active.acquire(config, lambda: pty_like))

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers={"Origin": "http://127.0.0.1:8788"},
        ) as ws:
            ws.receive_json()  # drain Started
            # Should not raise or produce any error frame.
            ws.send_json(
                {
                    "type": "permission_response",
                    "toolCallId": "tc-1",
                    "optionId": "opt-deny",
                }
            )
            time.sleep(0.1)
            ws.close()

        # No exception → test passes. The hasattr guard silently dropped the frame.
        assert not hasattr(pty_like, "send_permission")


# ---------------------------------------------------------------------------
# Cleanup — WS disconnect releases the active session
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_ws_disconnect_releases_active_session(
        self, client: TestClient, config: SessionConfig
    ) -> None:
        stub = StubTransport(events=[Started(agent="claude")])
        _install_active(stub, config)

        with client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers={"Origin": "http://127.0.0.1:8788"},
        ) as ws:
            ws.receive_json()
            ws.close()

        # Give the route's finally-block time to run release().
        time.sleep(0.15)

        assert asyncio.run(active.current()) is None
        assert stub.end_calls == 1
