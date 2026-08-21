"""Tests for web session-picker endpoints.

Prior to §1.5 wiring this file also held WS route tests exercising the
legacy ``{type: "start", ...}`` protocol and ``agent_session_manager``.
Those were removed when the WS route migrated to the
``active.acquire`` + ``PTYTransport`` flow; current WS coverage lives in
``test_web_session_ws.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

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
    # recommended_transport was deliberately dropped from the agent payload:
    # it had zero consumers and named the retired ttyd path. See
    # test_web_dev_engines.py::test_agents_no_longer_recommend_the_legacy_transport,
    # which asserts it stays gone.
    assert all(agent["acp_ready"] is False for agent in body["agents"])


def test_session_options_caps_topic_choices_to_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study_root = tmp_path / "Study"
    for name in ["Python", "SQL", "Data_Engineering", "AWS_Analytics"]:
        (study_root / name).mkdir(parents=True)

    class Content:
        def __init__(self) -> None:
            self.study_paths = [study_root]

    class Settings:
        def __init__(self) -> None:
            self.content = Content()
            self.topics = []

    monkeypatch.setattr("studyloop.settings.load_settings", Settings)

    client = TestClient(create_app())
    body = client.get("/api/session/options").json()

    assert [topic["label"] for topic in body["topics"]] == [
        "AWS Analytics",
        "Data Engineering",
        "Python",
    ]


def test_session_options_lists_vendors_directly_under_study_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Course vendors live directly under the study root (no ``Courses/`` level).

    Regression: ``_courses_roots()`` required an intermediate ``Courses/``
    directory that does not exist in the real vault — vendor dirs
    (ArjanCodes, CodeWithMosh, …) sit directly under ``Study/``. The missing
    level left the Course Vendor picker empty, which cascaded to empty
    Course and Lesson pickers.
    """
    study_root = tmp_path / "Study"
    lesson = study_root / "ArjanCodes" / "The_Software_Designer_Mindset" / "Module_01"
    lesson.mkdir(parents=True)
    (study_root / "CodeWithMosh").mkdir()

    class Content:
        def __init__(self) -> None:
            self.study_paths = [study_root]

    class Settings:
        def __init__(self) -> None:
            self.content = Content()

    monkeypatch.setattr("studyloop.settings.load_settings", Settings)

    client = TestClient(create_app())
    body = client.get("/api/session/options").json()

    vendor_labels = {v["label"] for v in body["vendors"]}
    assert "ArjanCodes" in vendor_labels
    assert "CodeWithMosh" in vendor_labels
    assert any(c["label"] == "The Software Designer Mindset" for c in body["courses"])
    assert any(lesson_["label"] == "Module 01" for lesson_ in body["lessons"])


def test_session_options_excludes_topic_dirs_and_dedupes_vendors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured topic dirs are not vendors; same-name vendors render once.

    Regression (user report 2026-07-12): the Course Vendor picker listed
    every configured topic (Python, DevOps, …) because topic obsidian_paths
    join ``_study_roots()`` and each study root doubles as a courses root.
    It also listed ArjanCodes/Udemy twice — once per courses root — because
    dedup was by resolved path, not name. Courses from BOTH same-name vendor
    dirs must still be discovered.
    """
    study_root = tmp_path / "Study"
    (study_root / "Udemy" / "Course_A").mkdir(parents=True)
    (study_root / "Python").mkdir()  # configured topic dir at vendor level
    second_root = tmp_path / "2-Areas" / "Study" / "Courses"
    (second_root / "Udemy" / "Course_B").mkdir(parents=True)

    class Topic:
        name = "Python"
        slug = "python"
        obsidian_path = study_root / "Python"

    class Content:
        def __init__(self) -> None:
            self.study_paths = [study_root, tmp_path / "2-Areas" / "Study"]

    class Settings:
        def __init__(self) -> None:
            self.content = Content()
            self.topics = [Topic()]
            # Without obsidian_base, _study_roots() raises and falls back to
            # scanning the REAL ~/Obsidian vault, breaking test isolation.
            self.obsidian_base = tmp_path

    monkeypatch.setattr("studyloop.settings.load_settings", Settings)

    client = TestClient(create_app())
    body = client.get("/api/session/options").json()

    vendor_values = [v["value"] for v in body["vendors"]]
    assert vendor_values.count("Udemy") == 1
    assert "Python" not in vendor_values
    course_values = {c["value"] for c in body["courses"]}
    assert {"Udemy/Course_A", "Udemy/Course_B"} <= course_values


def test_session_options_uses_index_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from studyloop.web.routes.session import _options

    state = SimpleNamespace()
    calls = 0

    def build_snapshot() -> dict:
        nonlocal calls
        calls += 1
        return {
            "session_types": [],
            "topics": [{"label": "Python", "value": "python", "kind": "topic"}],
            "vendors": [],
            "courses": [],
            "lessons": [],
        }

    monkeypatch.setattr(_options, "_target_fingerprint", lambda: {"same": True})
    monkeypatch.setattr(_options, "_read_target_index", lambda _fingerprint: None)
    monkeypatch.setattr(_options, "_write_target_index", lambda _fingerprint, _targets: None)
    monkeypatch.setattr(_options, "_target_options_snapshot", build_snapshot)

    first = _options._get_indexed_target_options(state)
    second = _options._get_indexed_target_options(state)

    assert first == second
    assert calls == 1


def test_session_options_refreshes_index_when_fingerprint_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from studyloop.web.routes.session import _options

    state = SimpleNamespace()
    fingerprints = iter([{"version": 1}, {"version": 2}])
    calls = 0

    def build_snapshot() -> dict:
        nonlocal calls
        calls += 1
        return {
            "session_types": [],
            "topics": [{"label": f"Topic {calls}", "value": str(calls), "kind": "topic"}],
            "vendors": [],
            "courses": [],
            "lessons": [],
        }

    monkeypatch.setattr(_options, "_target_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(_options, "_read_target_index", lambda _fingerprint: None)
    monkeypatch.setattr(_options, "_write_target_index", lambda _fingerprint, _targets: None)
    monkeypatch.setattr(_options, "_target_options_snapshot", build_snapshot)

    first = _options._get_indexed_target_options(state)
    second = _options._get_indexed_target_options(state)

    assert first["topics"][0]["label"] == "Topic 1"
    assert second["topics"][0]["label"] == "Topic 2"


def test_agent_options_fall_back_when_detection_fails() -> None:
    from studyloop.web.routes.session._options import _agent_options

    with patch("studyloop.agent_launcher.detect_agents", side_effect=RuntimeError("boom")):
        agents = _agent_options()

    assert {agent["value"] for agent in agents} == {
        "claude",
        "codex",
        "gemini",
        "grok",
        "kiro",
        "opencode",
    }
    assert all(agent["available"] is False for agent in agents)
