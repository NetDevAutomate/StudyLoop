"""Adversarial contract tests for the confined three-capability dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from studyloop.planning.contracts import PlanningRequest


@dataclass(frozen=True)
class _Brief:
    run_id: str
    brief_context_digest: str = "sha256:v1:" + "b" * 64


@dataclass(frozen=True)
class _Review:
    run_id: str
    proposal_id: str = "proposal-1"


class _Lifecycle:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def prepare(self, request: PlanningRequest, actor: object) -> _Brief:
        self.calls.append(("prepare", (request, actor)))
        return _Brief("run-bound")

    def handle(self, command: object) -> _Review:
        self.calls.append(("handle", command))
        return _Review("run-bound")

    def inspect(self, ref: object) -> _Review:
        self.calls.append(("inspect", ref))
        return _Review("run-bound")


def _dispatcher(lifecycle: _Lifecycle | None = None):
    from studyloop.planning.capabilities import PlanningCapabilityDispatcher

    target = lifecycle or _Lifecycle()
    return (
        PlanningCapabilityDispatcher(
            target,
            PlanningRequest("create", "A vague dump", "request-1"),
            expected_run_id="run-bound",
        ),
        target,
    )


def _draft(*, resource_url: str = "https://example.test/course") -> dict[str, object]:
    return {
        "title": "Understand protocols",
        "mission": {
            "why": "Trace behavior rather than collect notes",
            "success": ["Explain one exchange"],
            "constraints": ["Three goals maximum"],
            "out_of_scope": ["Collecting more notes"],
        },
        "goals": [
            {
                "alias": "trace",
                "title": "Trace protocols",
                "reason": "This is the learner's gap",
                "alignment_rationale": "It supports the mission",
            }
        ],
        "milestones": [
            {
                "alias": "trace-one",
                "goal_alias": "trace",
                "title": "Trace one exchange",
                "concept_aliases": ["protocol"],
            }
        ],
        "concepts": [{"alias": "protocol", "display_label": "protocol flow"}],
        "resources": [{"label": "Course", "url": resource_url, "note": "Context only"}],
        "unknowns": [
            {"unknown_id": "unknown-1", "question": "Which protocol first?", "impact": "scope"}
        ],
        "next_action": "Trace one request and response",
    }


def test_catalogue_is_deeply_immutable_and_exactly_three_safe_schemas() -> None:
    """Adding a fourth name or mutable destination/header field must fail this test."""
    from studyloop.planning.capabilities import (
        PLANNING_CAPABILITY_SCHEMAS,
        PlanningCapabilityName,
    )

    assert isinstance(PLANNING_CAPABILITY_SCHEMAS, tuple)
    assert tuple(item.name for item in PLANNING_CAPABILITY_SCHEMAS) == tuple(PlanningCapabilityName)
    assert [item.name.value for item in PLANNING_CAPABILITY_SCHEMAS] == [
        "prepare_plan",
        "submit_plan_proposal",
        "get_plan_proposal",
    ]
    wire_items = tuple(item.to_wire() for item in PLANNING_CAPABILITY_SCHEMAS)

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {str(key).casefold() for key in value} | {
                nested for item in value.values() for nested in keys(item)
            }
        if isinstance(value, (list, tuple)):
            return {nested for item in value for nested in keys(item)}
        return set()

    schema_keys = keys(wire_items)
    for forbidden in (
        "destination",
        "headers",
        "fetch",
        "browser",
        "shell",
        "actor_kind",
        "decision",
        "record_evidence",
        "mark_progress",
    ):
        assert forbidden not in schema_keys
    assert "url" in schema_keys

    with pytest.raises(TypeError):
        PLANNING_CAPABILITY_SCHEMAS[1].input_schema["properties"] = {}  # type: ignore[index]


def test_planning_package_exports_only_the_confined_model_contract() -> None:
    """Callers need one stable seam without importing a dynamic tool registry."""
    import studyloop.planning as planning

    assert planning.PlanningCapabilityName.PREPARE_PLAN == "prepare_plan"
    assert planning.PlanningModelProfile.__name__ == "PlanningModelProfile"
    assert planning.PlanningModelPort.__name__ == "PlanningModelPort"
    assert planning.ScriptedPlanningModel.__name__ == "ScriptedPlanningModel"


def test_dispatcher_prepares_submits_and_inspects_only_the_bound_run() -> None:
    """The allowed path proves the negatives are guarding a usable interface."""
    from studyloop.planning.capabilities import PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()

    prepared = dispatcher.execute(PlanningCapabilityCall("call-1", "prepare_plan", {}))
    submitted = dispatcher.execute(
        PlanningCapabilityCall(
            "call-2",
            "submit_plan_proposal",
            {
                "run_id": "run-bound",
                "brief_context_digest": "sha256:v1:" + "b" * 64,
                "draft": _draft(),
            },
        )
    )
    inspected = dispatcher.execute(
        PlanningCapabilityCall(
            "call-3",
            "get_plan_proposal",
            {"run_id": "run-bound", "proposal_id": "proposal-1"},
        )
    )

    assert (prepared.status, submitted.status, inspected.status) == ("ok", "ok", "ok")
    assert [name for name, _ in lifecycle.calls] == ["prepare", "handle", "inspect"]


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("decide_plan_proposal", {"decision": "approve"}),
        ("import_plan", {"markdown": "# Foreign"}),
        ("transition_plan_status", {"status": "complete"}),
        ("record_trusted_evidence", {"evidence_ids": ["e-1"]}),
        ("mark_progress", {"confidence": 9}),
        ("complete_milestone", {"milestone_id": "m-1"}),
        ("shell", {"command": "touch /tmp/pwned"}),
        ("read_file", {"path": "/etc/passwd"}),
        ("browser", {"url": "https://example.test"}),
        ("http_request", {"destination": "http://127.0.0.1:8567"}),
        ("__import__", {"module": "studyloop.mcp.tools"}),
        ("registry.execute", {"tool": "decide_plan_proposal"}),
        ("unknown", {}),
        ("prepare_plan", {"actor": {"actor_kind": "learner"}}),
        ("prepare_plan", {"credential": "secret"}),
        ("prepare_plan", {"registry": "studyloop.mcp.tools"}),
        ("get_plan_proposal", {"run_id": "run-foreign", "proposal_id": "proposal-1"}),
        (
            "submit_plan_proposal",
            {
                "run_id": "run-foreign",
                "brief_context_digest": "sha256:v1:" + "b" * 64,
                "draft": _draft(),
            },
        ),
    ],
)
def test_forbidden_authority_and_ambient_calls_create_zero_lifecycle_calls(
    name: str,
    arguments: dict[str, Any],
) -> None:
    """Every plausible authority escape must fail before domain dispatch."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(PlanningCapabilityCall("attack", name, arguments))

    assert lifecycle.calls == []


def test_nested_actor_or_http_fields_are_rejected_but_inert_resource_url_is_allowed() -> None:
    """Resource.url is citation data; similarly named control fields remain forbidden."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()
    hostile = _draft()
    hostile["mission"] = {**hostile["mission"], "actor_id": "learner"}  # type: ignore[arg-type]
    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "nested-actor",
                "submit_plan_proposal",
                {
                    "run_id": "run-bound",
                    "brief_context_digest": "sha256:v1:" + "b" * 64,
                    "draft": hostile,
                },
            )
        )
    assert lifecycle.calls == []

    allowed = _draft(resource_url="https://example.test/course?q=protocols")
    result = dispatcher.execute(
        PlanningCapabilityCall(
            "citation",
            "submit_plan_proposal",
            {
                "run_id": "run-bound",
                "brief_context_digest": "sha256:v1:" + "b" * 64,
                "draft": allowed,
            },
        )
    )
    assert result.status == "ok"
    assert [name for name, _ in lifecycle.calls] == ["handle"]

    dispatcher, lifecycle = _dispatcher()
    with pytest.raises(CapabilityRefusedError, match="citation URL"):
        dispatcher.execute(
            PlanningCapabilityCall(
                "bad-citation",
                "submit_plan_proposal",
                {
                    "run_id": "run-bound",
                    "brief_context_digest": "sha256:v1:" + "b" * 64,
                    "draft": _draft(resource_url="file:///etc/passwd"),
                },
            )
        )
    assert lifecycle.calls == []


def test_credential_fd_material_cannot_become_learner_authority() -> None:
    """The inherited verifier is transport data and cannot widen the model catalogue."""
    import json
    import os

    from studyloop.cli._web import _read_inherited_credentials
    from studyloop.learner_credentials import hash_password
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    read_fd, write_fd = os.pipe()
    with os.fdopen(write_fd, "wb") as stream:
        stream.write(
            json.dumps(
                {"username": "learner", "password_verifier": hash_password("chosen-password")}
            ).encode()
        )
    username, verifier = _read_inherited_credentials(read_fd)
    dispatcher, lifecycle = _dispatcher()

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "fd-attack",
                "decide_plan_proposal",
                {"actor": username, "credential": verifier, "decision": "approve"},
            )
        )
    assert lifecycle.calls == []
