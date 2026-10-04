"""``practice_check`` delivery to the live mentor -- interface stub (lane T, wave 1).

Red-only commit: the public names the wave-1 tests need, every function body
``raise NotImplementedError``. The implementing commit replaces this file; the
field schema below is the cross-process contract lanes R6 and W code against
(ADR-0012, council M0 2026-10-04 §4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from studyloop.session import active

if TYPE_CHECKING:
    from collections.abc import Mapping

    from studyloop.session.transport import AgentSessionTransport, BlockFraming

ENVELOPE_BOUND_BYTES = 8192

DeliveryStatus = Literal[
    "delivered",
    "no_active_session",
    "transport_closed",
    "timed_out",
    "unsupported_framing",
    "error",
]


class EnvelopeValidationError(ValueError):
    """``validate_envelope`` rejected the fields; the message names the field."""


class SessionWithTransport(Protocol):
    """The one thing ``deliver`` needs from ``ActiveSession`` (active.py:50-54)."""

    @property
    def transport(self) -> AgentSessionTransport: ...


@dataclass(frozen=True)
class PracticeCheckEnvelope:
    """Typed fields of one check result (stub: no bounds yet)."""

    module_id: str
    module_digest: str
    deck_id: str
    task_id: str
    attempt_id: str
    phase: str
    exit_class: str
    exit_code: int
    duration_s: float
    stdout_tail: str
    stderr_tail: str
    triggered_by: str = "learner"


@dataclass(frozen=True)
class DeliveryOutcome:
    status: DeliveryStatus
    reason: str


def validate_envelope(fields: Mapping[str, object]) -> PracticeCheckEnvelope:
    raise NotImplementedError


def render_envelope(envelope: PracticeCheckEnvelope, *, framing: BlockFraming) -> bytes:
    raise NotImplementedError


async def deliver(
    session: SessionWithTransport | None, envelope: PracticeCheckEnvelope
) -> DeliveryOutcome:
    raise NotImplementedError


async def deliver_to_active_session(envelope: PracticeCheckEnvelope) -> DeliveryOutcome:
    session = await active.current()
    return await deliver(session, envelope)
