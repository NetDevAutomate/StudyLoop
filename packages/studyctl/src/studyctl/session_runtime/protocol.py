"""Transport protocol for live interactive agent sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from pathlib import Path


@dataclass(frozen=True)
class SessionStartSpec:
    """Input needed to launch an interactive agent process."""

    session_id: str
    topic: str
    energy: int
    agent: str
    command: str | list[str]
    cwd: Path
    transport: str = "pty"
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionEvent:
    """Single event emitted by a live agent transport."""

    type: str
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable event payload."""
        return {
            "type": self.type,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class AgentSessionTransport(Protocol):
    """Bidirectional transport for one live agent session."""

    session_id: str

    async def start(self) -> None:
        """Start the underlying agent process."""

    async def send(self, text: str) -> None:
        """Send learner input to the agent."""

    def events(self) -> AsyncIterator[SessionEvent]: ...

    async def stop(self) -> None:
        """Stop the underlying process and release resources."""
