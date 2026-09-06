"""Assign evidence authority from captured metadata, never model-generated labels.

The caller is a trusted storage/import layer. CLI/MCP clients must select a stored
source by ID, not submit arbitrary CapturedReceipt or ScopeAssignment values.
A source receipt is local provenance, not remote attestation or semantic truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Scope(StrEnum):
    PERSONAL = "personal"
    WORK = "work"
    UNCLASSIFIED = "unclassified"


class Origin(StrEnum):
    CONVERSATION = "conversation_message"
    PROCESS_EXIT = "process_exit"
    TOOL_RESULT = "tool_result"
    UNKNOWN = "unknown"


class Basis(StrEnum):
    REPORTED = "reported"
    OBSERVED = "observed"
    UNKNOWN = "unknown"


class ExecutionState(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class ScopeAssignment:
    """Explicit project policy; no harness, hostname or language inference."""

    scope: Scope
    project_id: str | None
    policy_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, Scope):
            raise ValueError("Scope must be an explicit Scope value")
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("Scope assignment needs a policy identifier")
        if self.project_id is not None and (
            not isinstance(self.project_id, str) or not self.project_id.strip()
        ):
            raise ValueError("Invalid project identity")
        if self.scope != Scope.UNCLASSIFIED and not self.project_id:
            raise ValueError("Classified evidence needs an explicit project identity")


@dataclass(frozen=True, kw_only=True)
class CapturedReceipt:
    """Already bound to stored source bytes by the caller, not derived from body text."""

    receipt_id: str
    origin: Origin
    target: str | None = None
    exit_code: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.receipt_id, str)
            or not self.receipt_id.strip()
            or not isinstance(self.origin, Origin)
        ):
            raise ValueError("Invalid captured receipt")
        if self.target is not None and (
            not isinstance(self.target, str) or not self.target.strip()
        ):
            raise ValueError("Invalid captured target")
        if self.origin == Origin.PROCESS_EXIT and type(self.exit_code) is not int:
            raise ValueError(
                "A process-exit receipt requires a captured integer exit code"
            )
        if self.origin != Origin.PROCESS_EXIT and self.exit_code is not None:
            raise ValueError("Exit status requires process-exit origin")


@dataclass(frozen=True, kw_only=True)
class OwnedProvenance:
    basis: Basis
    scope: Scope
    project_id: str | None
    policy_id: str
    receipt_id: str | None
    execution_state: ExecutionState
    invocation_target: str | None
    invocation_bound: bool
    process_exit_code: int | None


def derive_provenance(
    assignment: ScopeAssignment, receipt: CapturedReceipt | None
) -> OwnedProvenance:
    """Only process completion is derived; neither exit zero nor text proves success."""
    basis = Basis.UNKNOWN
    if receipt is not None:
        if receipt.origin == Origin.CONVERSATION:
            basis = Basis.REPORTED
        elif receipt.origin in (Origin.PROCESS_EXIT, Origin.TOOL_RESULT):
            basis = Basis.OBSERVED
    process = receipt is not None and receipt.origin == Origin.PROCESS_EXIT
    return OwnedProvenance(
        basis=basis,
        scope=assignment.scope,
        project_id=assignment.project_id,
        policy_id=assignment.policy_id,
        receipt_id=receipt.receipt_id if receipt else None,
        execution_state=ExecutionState.COMPLETED if process else ExecutionState.UNKNOWN,
        invocation_target=receipt.target if process and receipt is not None else None,
        invocation_bound=process,
        process_exit_code=receipt.exit_code
        if process and receipt is not None
        else None,
    )


@dataclass(frozen=True, kw_only=True)
class Interpretation:
    """A proposed reading. Exact source-quote binding belongs to the storage boundary."""

    state: ExecutionState
    target: str | None
    quote: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.state, ExecutionState)
            or not isinstance(self.quote, str)
            or not self.quote.strip()
            or (
                self.target is not None
                and (not isinstance(self.target, str) or not self.target.strip())
            )
        ):
            raise ValueError(
                "Interpretation requires a state and nonempty supporting quote"
            )


@dataclass(frozen=True, kw_only=True)
class GroundedCandidate:
    """Separate source-owned facts from the original narrative proposal.

    No caller may treat narrative state/target as verified merely because this
    object exists. Semantic review and decision applicability are separate checks.
    """

    provenance: OwnedProvenance
    proposal: Interpretation

    @property
    def state(self) -> ExecutionState:
        if self.provenance.invocation_bound:
            return self.provenance.execution_state
        return self.proposal.state

    @property
    def target(self) -> str | None:
        if self.provenance.invocation_bound:
            # A captured missing target stays missing; never borrow the requested one.
            return self.provenance.invocation_target
        return self.proposal.target

    @property
    def semantic_status(self) -> str:
        return (
            "captured_execution_only"
            if self.provenance.invocation_bound
            else "unverified_interpretation"
        )
