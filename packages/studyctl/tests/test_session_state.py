"""Tests for session_state.py — IPC file read/write/parse."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_read_session_state_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns {} when state file doesn't exist."""
    monkeypatch.setattr("studyctl.session_state.STATE_FILE", tmp_path / "missing.json")
    from studyctl.session_state import read_session_state

    assert read_session_state() == {}


def test_read_session_state_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns parsed JSON when state file exists."""
    state_file = tmp_path / "session-state.json"
    state_file.write_text(json.dumps({"energy": 7, "topic": "python"}))
    monkeypatch.setattr("studyctl.session_state.STATE_FILE", state_file)
    from studyctl.session_state import read_session_state

    result = read_session_state()
    assert result["energy"] == 7
    assert result["topic"] == "python"


def test_read_session_state_corrupt_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns {} on corrupt JSON (never raises)."""
    state_file = tmp_path / "session-state.json"
    state_file.write_text("{invalid json")
    monkeypatch.setattr("studyctl.session_state.STATE_FILE", state_file)
    from studyctl.session_state import read_session_state

    assert read_session_state() == {}


def test_write_session_state_creates_and_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write_session_state creates file and merges updates."""
    state_file = tmp_path / "session-state.json"
    monkeypatch.setattr("studyctl.session_state.STATE_FILE", state_file)
    monkeypatch.setattr("studyctl.session_state.SESSION_DIR", tmp_path)
    from studyctl.session_state import write_session_state

    write_session_state({"energy": 5, "topic": "sql"})
    data = json.loads(state_file.read_text())
    assert data["energy"] == 5

    write_session_state({"energy": 8})
    data = json.loads(state_file.read_text())
    assert data["energy"] == 8
    assert data["topic"] == "sql"  # preserved from first write


def test_parse_topics_file_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns [] when topics file doesn't exist."""
    monkeypatch.setattr("studyctl.session_state.TOPICS_FILE", tmp_path / "missing.md")
    from studyctl.session_state import parse_topics_file

    assert parse_topics_file() == []


def test_parse_topics_file_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parses well-formed topic entries."""
    topics_file = tmp_path / "session-topics.md"
    topics_file.write_text(
        "- [09:14] Spark partitioning | status:learning | Basic concepts clicked\n"
        "- [09:31] SQL window functions | status:struggling | Re-explained twice\n"
        "- [09:45] ECMP bridge | status:insight | Student-generated bridge\n"
    )
    monkeypatch.setattr("studyctl.session_state.TOPICS_FILE", topics_file)
    from studyctl.session_state import parse_topics_file

    entries = parse_topics_file()
    assert len(entries) == 3
    assert entries[0].time == "09:14"
    assert entries[0].topic == "Spark partitioning"
    assert entries[0].status == "learning"
    assert entries[0].note == "Basic concepts clicked"
    assert entries[1].status == "struggling"
    assert entries[2].status == "insight"


def test_parse_topics_file_skips_malformed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Skips malformed lines without crashing."""
    topics_file = tmp_path / "session-topics.md"
    topics_file.write_text(
        "- [09:14] Good line | status:learning | Note\n"
        "This is not a valid line\n"
        "\n"
        "- bad format no brackets\n"
        "- [09:30] Also good | status:win | Got it\n"
    )
    monkeypatch.setattr("studyctl.session_state.TOPICS_FILE", topics_file)
    from studyctl.session_state import parse_topics_file

    entries = parse_topics_file()
    assert len(entries) == 2
    assert entries[0].topic == "Good line"
    assert entries[1].status == "win"


def test_parse_parking_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parses parking lot entries."""
    parking_file = tmp_path / "session-parking.md"
    parking_file.write_text(
        "- How does the GIL affect multiprocessing?\n- VPC peering vs Transit Gateway\n"
    )
    monkeypatch.setattr("studyctl.session_state.PARKING_FILE", parking_file)
    from studyctl.session_state import parse_parking_file

    entries = parse_parking_file()
    assert len(entries) == 2
    assert entries[0].question == "How does the GIL affect multiprocessing?"


def test_append_topic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """append_topic adds a line to the topics file."""
    topics_file = tmp_path / "session-topics.md"
    monkeypatch.setattr("studyctl.session_state.TOPICS_FILE", topics_file)
    monkeypatch.setattr("studyctl.session_state.SESSION_DIR", tmp_path)
    from studyctl.session_state import append_topic

    append_topic("10:00", "Spark DAGs", "learning", "Getting the concept")
    content = topics_file.read_text()
    assert "- [10:00] Spark DAGs | status:learning | Getting the concept" in content


def test_append_parking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """append_parking adds a line to the parking file."""
    parking_file = tmp_path / "session-parking.md"
    monkeypatch.setattr("studyctl.session_state.PARKING_FILE", parking_file)
    monkeypatch.setattr("studyctl.session_state.SESSION_DIR", tmp_path)
    from studyctl.session_state import append_parking

    append_parking("How does asyncio.gather work?")
    content = parking_file.read_text()
    assert "- How does asyncio.gather work?" in content


def test_clear_session_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """clear_session_files removes all IPC files."""
    state = tmp_path / "session-state.json"
    topics = tmp_path / "session-topics.md"
    parking = tmp_path / "session-parking.md"
    for f in (state, topics, parking):
        f.write_text("content")

    monkeypatch.setattr("studyctl.session_state.STATE_FILE", state)
    monkeypatch.setattr("studyctl.session_state.TOPICS_FILE", topics)
    monkeypatch.setattr("studyctl.session_state.PARKING_FILE", parking)
    from studyctl.session_state import clear_session_files

    clear_session_files()
    assert not state.exists()
    assert not topics.exists()
    assert not parking.exists()


def test_is_session_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """is_session_active returns True only when study_session_id is set."""
    state_file = tmp_path / "session-state.json"
    monkeypatch.setattr("studyctl.session_state.STATE_FILE", state_file)
    from studyctl.session_state import is_session_active

    assert not is_session_active()

    state_file.write_text(json.dumps({"energy": 5}))
    assert not is_session_active()

    state_file.write_text(json.dumps({"study_session_id": "abc-123"}))
    assert is_session_active()
