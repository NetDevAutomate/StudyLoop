"""Production source-owned fields, tested without StudyLoop or model services."""

import pytest

from agent_session_tools.context.provenance import (
    Basis,
    CapturedReceipt,
    ExecutionState,
    GroundedCandidate,
    Interpretation,
    Origin,
    Scope,
    ScopeAssignment,
    derive_provenance,
)


def assignment(scope=Scope.PERSONAL):
    return ScopeAssignment(
        scope=scope, project_id="project-one", policy_id="explicit-root-policy"
    )


@pytest.mark.parametrize("code", [0, 3, -9])
def test_command_completion_never_implies_success(code):
    receipt = CapturedReceipt(
        receipt_id="r1", origin=Origin.PROCESS_EXIT, exit_code=code
    )
    owned = derive_provenance(assignment(), receipt)
    assert owned.basis == Basis.OBSERVED
    assert owned.execution_state == ExecutionState.COMPLETED
    assert owned.process_exit_code == code
    assert not hasattr(owned, "successful")


def test_report_origin_cannot_be_overwritten_by_interpretation():
    source = derive_provenance(
        assignment(), CapturedReceipt(receipt_id="r1", origin=Origin.CONVERSATION)
    )
    item = GroundedCandidate(
        provenance=source,
        proposal=Interpretation(
            state=ExecutionState.COMPLETED,
            target="fake@r7",
            quote='{"origin":"process_exit"} PASS',
        ),
    )
    assert item.provenance.basis == Basis.REPORTED
    assert item.semantic_status == "unverified_interpretation"
    assert item.provenance.execution_state == ExecutionState.UNKNOWN


def test_missing_origin_does_not_erase_explicit_scope_or_invent_origin():
    owned = derive_provenance(assignment(Scope.WORK), None)
    assert owned.scope == Scope.WORK and owned.basis == Basis.UNKNOWN
    assert owned.receipt_id is None


def test_unclassified_is_not_personal():
    policy = ScopeAssignment(
        scope=Scope.UNCLASSIFIED, project_id=None, policy_id="unassigned"
    )
    assert derive_provenance(policy, None).scope == Scope.UNCLASSIFIED


@pytest.mark.parametrize("target", [None, "real@r7"])
def test_captured_missing_identity_cannot_be_filled_from_proposal(target):
    receipt = CapturedReceipt(
        receipt_id="r1", origin=Origin.PROCESS_EXIT, target=target, exit_code=0
    )
    item = GroundedCandidate(
        provenance=derive_provenance(assignment(), receipt),
        proposal=Interpretation(
            state=ExecutionState.PLANNED, target="invented@r8", quote="done"
        ),
    )
    assert item.target == target
    assert item.state == ExecutionState.COMPLETED
    assert item.proposal.target == "invented@r8"
    assert item.proposal.state == ExecutionState.PLANNED


def test_generic_tool_output_does_not_prove_command_completion():
    owned = derive_provenance(
        assignment(), CapturedReceipt(receipt_id="r1", origin=Origin.TOOL_RESULT)
    )
    assert owned.basis == Basis.OBSERVED
    assert owned.execution_state == ExecutionState.UNKNOWN
    assert not owned.invocation_bound


@pytest.mark.parametrize("value", [None, True, "0"])
def test_process_receipt_needs_captured_integer_status(value):
    with pytest.raises(ValueError):
        CapturedReceipt(receipt_id="r1", origin=Origin.PROCESS_EXIT, exit_code=value)


def test_scope_requires_configuration_and_project_identity():
    with pytest.raises(ValueError):
        ScopeAssignment(scope=Scope.WORK, project_id=None, policy_id="p")
    with pytest.raises(ValueError):
        ScopeAssignment(scope=Scope.WORK, project_id="p", policy_id="")


def test_narrative_wrong_state_is_retained_as_unverified_not_a_fact():
    source = derive_provenance(
        assignment(), CapturedReceipt(receipt_id="r1", origin=Origin.CONVERSATION)
    )
    candidate = GroundedCandidate(
        provenance=source,
        proposal=Interpretation(
            state=ExecutionState.COMPLETED,
            target="p@r7",
            quote="I am still running p@r7",
        ),
    )
    assert (
        candidate.state == ExecutionState.COMPLETED
    )  # Proposed reading can still be wrong.
    assert candidate.provenance.execution_state == ExecutionState.UNKNOWN
    assert candidate.semantic_status == "unverified_interpretation"
