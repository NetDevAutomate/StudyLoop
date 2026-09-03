"""Smoke tests for studyloop.session.transport — Protocol + event types.

No behaviour lives in transport.py; it's pure contract. These tests guard the
contract from silent breakage: symbol presence, dataclass frozenness, event
union composition, and the error-hierarchy decision.

Plan: private-docs/2026-05-09-refactor-agent-session-transport-plan.md §1.1
"""

from __future__ import annotations

import dataclasses
from typing import get_args

import pytest

from studyloop.session.transport import (
    AgentMessage,
    AgentSessionTransport,
    OutputBytes,
    SessionAlreadyActiveError,
    SessionConfig,
    Started,
    Stopped,
    TransportError,
    TransportEvent,
    TransportEventT,
)

# ---------------------------------------------------------------------------
# Event types — frozen dataclasses, correct fields, TransportEvent base
# ---------------------------------------------------------------------------


class TestTransportEvents:
    """Each event type is a frozen dataclass descended from TransportEvent."""

    def test_output_bytes_holds_raw_data(self) -> None:
        event = OutputBytes(data=b"hello\n")
        assert event.data == b"hello\n"
        assert isinstance(event, TransportEvent)

    def test_started_names_the_agent(self) -> None:
        event = Started(agent="claude")
        assert event.agent == "claude"
        assert isinstance(event, TransportEvent)

    def test_stopped_carries_returncode_and_reason(self) -> None:
        event = Stopped(returncode=0, reason="exit")
        assert event.returncode == 0
        assert event.reason == "exit"

    def test_stopped_returncode_may_be_none(self) -> None:
        """Killed-before-exit case — plan requires None to be valid."""
        event = Stopped(returncode=None, reason="cancel")
        assert event.returncode is None

    def test_transport_error_carries_message(self) -> None:
        event = TransportError(message="queue overflow")
        assert event.message == "queue overflow"

    def test_agent_message_carries_kind_and_payload(self) -> None:
        event = AgentMessage(kind="tool_call", payload={"name": "Read"})
        assert event.kind == "tool_call"
        assert event.payload == {"name": "Read"}

    @pytest.mark.parametrize(
        "event",
        [
            OutputBytes(data=b""),
            Started(agent="x"),
            Stopped(returncode=0, reason="exit"),
            TransportError(message="x"),
            AgentMessage(kind="x", payload={}),
        ],
    )
    def test_events_are_frozen(self, event: TransportEvent) -> None:
        """Frozen so event objects can be safely shared across tasks/queues."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            # Every event has at least one field; pick any and mutate.
            field = dataclasses.fields(event)[0].name
            object.__setattr__(event, "__dataclass_params__", None)  # no-op probe
            setattr(event, field, "mutated")


# ---------------------------------------------------------------------------
# TransportEventT — discriminated union of the five event types
# ---------------------------------------------------------------------------


class TestTransportEventUnion:
    def test_union_covers_exactly_the_five_event_types(self) -> None:
        """Guards against accidental addition/removal from the union.

        Plan §Decisions reconciled: the union is five elements, not four
        (Stopped merged Exited+Cancelled) and not six.
        """
        assert set(get_args(TransportEventT)) == {
            OutputBytes,
            Started,
            Stopped,
            TransportError,
            AgentMessage,
        }


# ---------------------------------------------------------------------------
# SessionConfig — dataclass contract
# ---------------------------------------------------------------------------


class TestSessionConfig:
    def test_is_frozen(self) -> None:
        config = SessionConfig(
            study_session_id="s1",
            agent="claude",
            persona_file="/tmp/persona.md",
            cwd="/tmp",
            env={},
            cols=80,
            rows=24,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.cols = 100  # type: ignore[misc]

    def test_exposes_expected_fields(self) -> None:
        """Field list is part of the contract — callers build these by name."""
        names = {f.name for f in dataclasses.fields(SessionConfig)}
        assert names == {
            "study_session_id",
            "agent",
            "persona_file",
            "cwd",
            "env",
            "cols",
            "rows",
        }


# ---------------------------------------------------------------------------
# SessionAlreadyActiveError — distinct exception type
# ---------------------------------------------------------------------------


class TestSessionAlreadyActiveError:
    def test_is_a_runtime_error(self) -> None:
        """Inherits RuntimeError so generic `except RuntimeError` still works,
        but has its own class so route handlers can map it to HTTP 409
        without swallowing unrelated RuntimeErrors."""
        assert issubclass(SessionAlreadyActiveError, RuntimeError)

    def test_carries_a_message(self) -> None:
        exc = SessionAlreadyActiveError("session foo already active")
        assert "foo" in str(exc)


# ---------------------------------------------------------------------------
# AgentSessionTransport Protocol — structural smoke check
# ---------------------------------------------------------------------------


class TestAgentSessionTransportProtocol:
    def test_protocol_advertises_expected_methods(self) -> None:
        """Method set is the public API — callers rely on this shape."""
        expected = {
            "start",
            "send_input",
            "resize",
            "events",
            "cancel",
            "end",
            "__aenter__",
            "__aexit__",
        }
        assert expected.issubset(set(dir(AgentSessionTransport)))
