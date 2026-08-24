"""Provider-neutral wire contract for the confined planning model."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Literal, Protocol

import yaml

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

MODEL_WIRE_VERSION = 1
_PROMPT_RESOURCE = "architect.md"


@dataclass(frozen=True, slots=True)
class ArchitectPrompt:
    """Validated prompt text plus the bounded interview contract it declares."""

    version: str
    normal_question_limit: int
    absolute_question_limit: int
    provisional_plan_by_turn: int
    context_evidence_tier: int
    text: str


def load_architect_prompt() -> ArchitectPrompt:
    """Load and validate the prompt shipped inside the installed package."""
    text = resources.files("studyloop.planning.prompts").joinpath(_PROMPT_RESOURCE).read_text()
    if not text.startswith("---\n"):
        raise RuntimeError("packaged Architect prompt has no contract header")
    try:
        header_text, body = text[4:].split("\n---\n", 1)
        header = yaml.safe_load(header_text)
        prompt = ArchitectPrompt(
            version=str(header["prompt_version"]),
            normal_question_limit=int(header["normal_question_limit"]),
            absolute_question_limit=int(header["absolute_question_limit"]),
            provisional_plan_by_turn=int(header["provisional_plan_by_turn"]),
            context_evidence_tier=int(header["context_evidence_tier"]),
            text=body.strip(),
        )
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise RuntimeError("packaged Architect prompt contract is invalid") from exc
    if (
        prompt.version != "architect-v1"
        or prompt.normal_question_limit != 1
        or prompt.absolute_question_limit != 3
        or prompt.provisional_plan_by_turn != 3
        or prompt.context_evidence_tier != 4
    ):
        raise RuntimeError("packaged Architect prompt violates the release-one policy")
    return prompt


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One fixed-destination provider attempt."""

    schema_version: int
    conversation_id: str
    turn_id: str
    attempt_id: str
    messages: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_WIRE_VERSION:
            raise ValueError("unsupported planning model wire version")
        identities = (self.conversation_id, self.turn_id, self.attempt_id)
        if not all(value.strip() for value in identities):
            raise ValueError("conversation, turn, and attempt IDs are required")


@dataclass(frozen=True, slots=True)
class ModelTextDelta:
    schema_version: int
    turn_id: str
    attempt_id: str
    sequence: int
    text: str


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    schema_version: int
    turn_id: str
    attempt_id: str
    sequence: int
    tool_call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ModelTurnCompleted:
    schema_version: int
    turn_id: str
    attempt_id: str
    sequence: int
    finish_reason: Literal["stop", "tool_calls", "length", "error"]


type ModelEvent = ModelTextDelta | ModelToolCall | ModelTurnCompleted


class PlanningModelPort(Protocol):
    """The sole model seam used by the planning conversation runtime."""

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
