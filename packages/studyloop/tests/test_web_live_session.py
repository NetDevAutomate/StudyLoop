"""Tests for web session-picker endpoints.

Prior to §1.5 wiring this file also held WS route tests exercising the
legacy ``{type: "start", ...}`` protocol and ``agent_session_manager``.
Those were removed when the WS route migrated to the
``active.acquire`` + ``PTYTransport`` flow; current WS coverage lives in
``test_web_session_ws.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from studyloop.web.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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

    monkeypatch.setattr("studyloop.settings.load_settings", Settings)

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
