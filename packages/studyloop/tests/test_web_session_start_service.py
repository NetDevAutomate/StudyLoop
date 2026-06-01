"""Tests for session-start service helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from studyloop.web.services.session_start import build_session_state_payload, session_dir_name


def test_session_dir_name_is_short_and_stable() -> None:
    assert session_dir_name("Python Decorators", "abc123456789") == (
        "pty-python-decorators-abc12345"
    )


def test_session_dir_name_accepts_transport_prefix() -> None:
    assert session_dir_name("Python Decorators", "abc123456789", prefix="acp") == (
        "acp-python-decorators-abc12345"
    )


def test_build_session_state_payload_has_transport_and_timestamps() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    payload = build_session_state_payload(
        study_id="study-1",
        topic="Python",
        energy=6,
        energy_label="medium",
        agent="codex",
        persona_file="/tmp/persona.md",
        session_dir="/tmp/session",
        persona_hash="abcdef",
        transport="pty",
        now=now,
    )
    assert payload["study_session_id"] == "study-1"
    assert payload["transport"] == "pty"
    assert payload["started_at"] == "2026-06-01T12:00:00+00:00"
    assert payload["start_time"] == payload["started_at"]
    assert payload["persona_file"] == "/tmp/persona.md"


def test_build_session_state_payload_omits_persona_file_for_acp() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    payload = build_session_state_payload(
        study_id="study-1",
        topic="Python",
        energy=6,
        energy_label="medium",
        agent="kiro",
        session_dir="/tmp/session",
        persona_hash="abcdef",
        transport="acp",
        now=now,
    )
    assert payload["transport"] == "acp"
    assert "persona_file" not in payload
