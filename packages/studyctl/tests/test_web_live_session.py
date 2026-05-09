"""Tests for web live-session WebSocket and picker endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from studyctl.session_runtime import SessionEvent
from studyctl.web.app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    import pytest


class FakeManager:
    """Minimal manager used by the WebSocket route tests."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.stopped: list[str] = []

    async def start_session(
        self,
        *,
        topic: str,
        energy: int,
        agent: str | None = None,
        transport: str = "pty",
    ) -> tuple[str, AsyncIterator[SessionEvent]]:
        async def events() -> AsyncIterator[SessionEvent]:
            yield SessionEvent(
                "started",
                "fake-session",
                {
                    "topic": topic,
                    "energy": energy,
                    "agent": agent or "shell",
                    "transport": transport,
                },
            )
            yield SessionEvent("output", "fake-session", {"text": "ready"})

        return "fake-session", events()

    async def send(self, session_id: str, text: str) -> None:
        self.sent.append(f"{session_id}:{text}")

    async def stop(self, session_id: str) -> None:
        self.stopped.append(session_id)


def test_session_options_returns_course_hierarchy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study_root = tmp_path / "Study"
    lesson = study_root / "Courses" / "Udemy" / "Python_101" / "Section_01"
    lesson.mkdir(parents=True)
    (study_root / "SQL").mkdir()

    class Content:
        def __init__(self) -> None:
            self.study_paths = [study_root]

    class Settings:
        def __init__(self) -> None:
            self.content = Content()

    monkeypatch.setattr("studyctl.settings.load_settings", Settings)

    client = TestClient(create_app())
    response = client.get("/api/session/options")

    assert response.status_code == 200
    body = response.json()
    assert any(topic["label"] == "SQL" for topic in body["topics"])
    assert body["vendors"][0]["label"] == "Udemy"
    assert body["courses"][0]["label"] == "Python 101"
    assert body["lessons"][0]["label"] == "Section 01"
    assert "agents" in body
    assert all(agent["recommended_transport"] == "ttyd" for agent in body["agents"])
    assert all(agent["acp_ready"] is False for agent in body["agents"])


def test_live_session_websocket_streams_events_and_accepts_input() -> None:
    app = create_app()
    manager = FakeManager()
    app.state.agent_session_manager = manager
    client = TestClient(app)

    with client.websocket_connect("/api/session/ws") as websocket:
        websocket.send_json({"type": "start", "topic": "Python", "energy": 6, "transport": "pty"})
        assert websocket.receive_json()["type"] == "started"
        assert websocket.receive_json()["type"] == "output"
        websocket.send_json({"type": "input", "text": "what is a decorator?"})
        websocket.send_json({"type": "stop"})

    assert manager.sent == ["fake-session:what is a decorator?"]
    assert manager.stopped == ["fake-session"]


def test_live_session_websocket_rejects_acp_until_handshake_is_implemented() -> None:
    app = create_app()
    manager = FakeManager()
    app.state.agent_session_manager = manager
    client = TestClient(app)

    with client.websocket_connect("/api/session/ws") as websocket:
        websocket.send_json({"type": "start", "topic": "Python", "energy": 6, "transport": "acp"})
        payload = websocket.receive_json()
        websocket.close()

    assert payload["type"] == "error"
    assert "ACP transport is scaffolded" in payload["data"]["message"]
    assert manager.sent == []
