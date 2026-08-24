"""Adversarial contract tests for the confined three-capability dispatcher."""

from __future__ import annotations

from copy import deepcopy
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
    from studyloop.planning.capabilities import (
        PlanningCapabilityDispatcher,
        PlanningCapabilityScope,
    )

    target = lifecycle or _Lifecycle()
    return (
        PlanningCapabilityDispatcher(
            target,
            PlanningRequest("create", "A vague dump", "request-1"),
            scope=PlanningCapabilityScope("conversation-1", "turn-1", "attempt-1"),
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
        "evidence_dispositions": [],
        "resources": [{"label": "Course", "url": resource_url, "note": "Context only"}],
        "unknowns": [
            {"unknown_id": "unknown-1", "question": "Which protocol first?", "impact": "scope"}
        ],
        "next_action": "Trace one request and response",
    }


def _malformed_schema_draft(case: str) -> dict[str, object]:
    draft = _draft()
    if case == "unknown_status":
        draft["unknowns"][0]["status"] = "forged"  # type: ignore[index]
    elif case == "goal_status":
        draft["goals"][0]["status"] = "forged"  # type: ignore[index]
    elif case == "energy_floor_zero":
        draft["energy_floor"] = 0
    elif case == "energy_floor_eleven":
        draft["energy_floor"] = 11
    elif case == "review_cadence_zero":
        draft["review_cadence_days"] = 0
    elif case == "relation_enum":
        draft["concept_relations"] = [
            {
                "source_alias": "protocol",
                "target_alias": "protocol",
                "relation": "forged",
                "reason": "Invalid enum",
                "provenance": "preflight",
            }
        ]
    elif case == "evidence_disposition_enum":
        draft["evidence_dispositions"] = [
            {"evidence_id": "evidence-1", "disposition": "forged", "reason": ""}
        ]
    elif case == "unresolved_evidence_without_reason":
        draft["evidence_dispositions"] = [
            {"evidence_id": "evidence-1", "disposition": "unresolved", "reason": ""}
        ]
    elif case == "requested_status_enum":
        draft["requested_status"] = "active"
    elif case == "goal_max_items":
        draft["goals"] = [
            {
                "alias": f"goal-{index}",
                "title": f"Goal {index}",
                "reason": "Audit maxItems",
                "alignment_rationale": "Supports the mission",
            }
            for index in range(4)
        ]
    elif case == "resource_url_max_length":
        draft["resources"] = [{"label": "Too long", "url": "https://example.test/" + "a" * 2048}]
    else:  # pragma: no cover - table is closed below
        raise AssertionError(f"unsupported test case {case}")
    return draft


def _draft_with_every_required_shape() -> dict[str, object]:
    draft = _draft()
    draft["concept_relations"] = [
        {
            "source_alias": "protocol",
            "target_alias": "protocol",
            "relation": "related",
            "reason": "Exercise the required relation shape",
            "provenance": "learner conversation",
        }
    ]
    draft["evidence_dispositions"] = [
        {"evidence_id": "evidence-1", "disposition": "selected", "reason": ""}
    ]
    return draft


def _draft_with_every_schema_property() -> dict[str, object]:
    draft = _draft_with_every_required_shape()
    goal: dict[str, object] = draft["goals"][0]  # type: ignore[assignment,index]
    goal.update({"status": "active", "existing_goal_id": ""})
    milestone: dict[str, object] = draft["milestones"][0]  # type: ignore[assignment,index]
    milestone.update({"notes": "", "existing_milestone_id": ""})
    concept: dict[str, object] = draft["concepts"][0]  # type: ignore[assignment,index]
    concept["existing_concept_id"] = ""
    unknown: dict[str, object] = draft["unknowns"][0]  # type: ignore[assignment,index]
    unknown["status"] = "open"
    draft.update(
        {
            "topics": ["networking"],
            "requested_status": "draft",
            "target_date": "",
            "energy_floor": 3,
            "review_cadence_days": 3,
            "goal_limit_override_requested": False,
            "goal_limit_override_reason": "",
        }
    )
    return draft


def _delete_path(value: dict[str, object], path: tuple[str | int, ...]) -> None:
    target: Any = value
    for segment in path[:-1]:
        target = target[segment]
    del target[path[-1]]


def _set_path(value: dict[str, object], path: tuple[str | int, ...], replacement: object) -> None:
    target: Any = value
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = replacement


def _value_at_path(value: dict[str, object], path: tuple[str | int, ...]) -> object:
    target: Any = value
    for segment in path:
        target = target[segment]
    return target


_SCHEMA_PROPERTY_TYPE_PATHS: tuple[tuple[str, tuple[str | int, ...], object], ...] = (
    ("draft.title", ("title",), 7),
    ("draft.mission", ("mission",), []),
    ("draft.goals", ("goals",), {}),
    ("draft.milestones", ("milestones",), {}),
    ("draft.topics", ("topics",), {}),
    ("draft.concepts", ("concepts",), {}),
    ("draft.concept_relations", ("concept_relations",), {}),
    ("draft.evidence_dispositions", ("evidence_dispositions",), {}),
    ("draft.resources", ("resources",), {}),
    ("draft.unknowns", ("unknowns",), {}),
    ("draft.next_action", ("next_action",), 7),
    ("draft.requested_status", ("requested_status",), 7),
    ("draft.target_date", ("target_date",), 7),
    ("draft.energy_floor", ("energy_floor",), 3.0),
    ("draft.review_cadence_days", ("review_cadence_days",), 3.0),
    ("draft.goal_limit_override_requested", ("goal_limit_override_requested",), 0),
    ("draft.goal_limit_override_reason", ("goal_limit_override_reason",), 7),
    ("mission.why", ("mission", "why"), 7),
    ("mission.success", ("mission", "success"), {}),
    ("mission.constraints", ("mission", "constraints"), {}),
    ("mission.out_of_scope", ("mission", "out_of_scope"), {}),
    ("goal.alias", ("goals", 0, "alias"), 7),
    ("goal.title", ("goals", 0, "title"), 7),
    ("goal.reason", ("goals", 0, "reason"), 7),
    ("goal.alignment_rationale", ("goals", 0, "alignment_rationale"), 7),
    ("goal.status", ("goals", 0, "status"), 7),
    ("goal.existing_goal_id", ("goals", 0, "existing_goal_id"), 7),
    ("milestone.alias", ("milestones", 0, "alias"), 7),
    ("milestone.goal_alias", ("milestones", 0, "goal_alias"), 7),
    ("milestone.title", ("milestones", 0, "title"), 7),
    ("milestone.notes", ("milestones", 0, "notes"), 7),
    ("milestone.concept_aliases", ("milestones", 0, "concept_aliases"), {}),
    ("milestone.existing_milestone_id", ("milestones", 0, "existing_milestone_id"), 7),
    ("concept.alias", ("concepts", 0, "alias"), 7),
    ("concept.display_label", ("concepts", 0, "display_label"), 7),
    ("concept.existing_concept_id", ("concepts", 0, "existing_concept_id"), 7),
    ("relation.source_alias", ("concept_relations", 0, "source_alias"), 7),
    ("relation.target_alias", ("concept_relations", 0, "target_alias"), 7),
    ("relation.relation", ("concept_relations", 0, "relation"), 7),
    ("relation.reason", ("concept_relations", 0, "reason"), 7),
    ("relation.provenance", ("concept_relations", 0, "provenance"), 7),
    ("evidence.evidence_id", ("evidence_dispositions", 0, "evidence_id"), 7),
    ("evidence.disposition", ("evidence_dispositions", 0, "disposition"), 7),
    ("evidence.reason", ("evidence_dispositions", 0, "reason"), 7),
    ("resource.label", ("resources", 0, "label"), 7),
    ("resource.url", ("resources", 0, "url"), 7),
    ("resource.note", ("resources", 0, "note"), 7),
    ("unknown.unknown_id", ("unknowns", 0, "unknown_id"), 7),
    ("unknown.question", ("unknowns", 0, "question"), 7),
    ("unknown.impact", ("unknowns", 0, "impact"), 7),
    ("unknown.status", ("unknowns", 0, "status"), 7),
)

_SCHEMA_ARRAY_ITEM_TYPE_PATHS: tuple[tuple[str, tuple[str | int, ...], object], ...] = (
    ("mission.success.item", ("mission", "success", 0), {}),
    ("mission.constraints.item", ("mission", "constraints", 0), {}),
    ("mission.out_of_scope.item", ("mission", "out_of_scope", 0), {}),
    ("goals.item", ("goals", 0), "not-an-object"),
    ("milestones.item", ("milestones", 0), "not-an-object"),
    ("topics.item", ("topics", 0), {}),
    ("concepts.item", ("concepts", 0), "not-an-object"),
    ("concept_relations.item", ("concept_relations", 0), "not-an-object"),
    ("evidence_dispositions.item", ("evidence_dispositions", 0), "not-an-object"),
    ("resources.item", ("resources", 0), "not-an-object"),
    ("unknowns.item", ("unknowns", 0), "not-an-object"),
    ("milestone.concept_aliases.item", ("milestones", 0, "concept_aliases", 0), {}),
)

_SCHEMA_ARRAY_PROPERTY_PATHS: tuple[tuple[str, tuple[str | int, ...]], ...] = (
    ("draft.goals", ("goals",)),
    ("draft.milestones", ("milestones",)),
    ("draft.topics", ("topics",)),
    ("draft.concepts", ("concepts",)),
    ("draft.concept_relations", ("concept_relations",)),
    ("draft.evidence_dispositions", ("evidence_dispositions",)),
    ("draft.resources", ("resources",)),
    ("draft.unknowns", ("unknowns",)),
    ("mission.success", ("mission", "success")),
    ("mission.constraints", ("mission", "constraints")),
    ("mission.out_of_scope", ("mission", "out_of_scope")),
    ("milestone.concept_aliases", ("milestones", 0, "concept_aliases")),
)

_SCHEMA_TYPE_CASES = tuple(
    pytest.param(path, invalid, id=f"{label}-{variant}")
    for label, path, wrong_type in (
        *_SCHEMA_PROPERTY_TYPE_PATHS,
        *_SCHEMA_ARRAY_ITEM_TYPE_PATHS,
    )
    for variant, invalid in (("null", None), ("wrong-type", wrong_type))
)

_TOP_LEVEL_SCHEMA_TYPE_CASES = tuple(
    pytest.param(name, path, invalid, id=f"{label}-{variant}")
    for label, name, path, wrong_type in (
        ("submit.run_id", "submit_plan_proposal", ("run_id",), 7),
        (
            "submit.brief_context_digest",
            "submit_plan_proposal",
            ("brief_context_digest",),
            7,
        ),
        ("submit.draft", "submit_plan_proposal", ("draft",), []),
        ("get.run_id", "get_plan_proposal", ("run_id",), 7),
        ("get.proposal_id", "get_plan_proposal", ("proposal_id",), 7),
    )
    for variant, invalid in (("null", None), ("wrong-type", wrong_type))
)


def _durable_planning_state(root) -> tuple[bytes, dict[str, bytes]]:
    journal = root / "planning-journal.jsonl"
    private_runs = root / "private-runs"
    artifacts = (
        {
            str(path.relative_to(root)): path.read_bytes()
            for path in private_runs.rglob("*")
            if path.is_file()
        }
        if private_runs.exists()
        else {}
    )
    return (journal.read_bytes() if journal.exists() else b"", artifacts)


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
        "idempotency_key",
        "scope",
        "conversation_id",
        "turn_id",
        "attempt_id",
    ):
        assert forbidden not in schema_keys
    assert "url" in schema_keys
    function = wire_items[1]["function"]
    assert isinstance(function, dict)
    parameters = function["parameters"]
    assert isinstance(parameters, dict)
    properties = parameters["properties"]
    assert isinstance(properties, dict)
    submit_draft = properties["draft"]
    assert isinstance(submit_draft, dict)
    assert "evidence_dispositions" in submit_draft["properties"]
    assert "evidence_dispositions" in submit_draft["required"]

    with pytest.raises(TypeError):
        PLANNING_CAPABILITY_SCHEMAS[1].input_schema["properties"] = {}  # type: ignore[index]


def test_planning_package_exports_only_the_confined_model_contract() -> None:
    """Callers need one stable seam without importing a dynamic tool registry."""
    import studyloop.planning as planning

    assert planning.PlanningCapabilityName.PREPARE_PLAN == "prepare_plan"
    assert planning.PlanningCapabilityScope.__name__ == "PlanningCapabilityScope"
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


def test_absent_optional_properties_keep_only_the_documented_decoder_defaults() -> None:
    """The null fix must preserve omission defaults for genuinely optional schema keys."""
    from studyloop.planning.capabilities import PlanningCapabilityCall
    from studyloop.planning.contracts import PlanningCommand, SubmitProposalDraft

    dispatcher, lifecycle = _dispatcher()
    minimal_draft = {
        "title": "Minimal plan",
        "mission": {"why": "Test omission", "success": ["Defaults remain stable"]},
        "goals": [
            {
                "alias": "minimal",
                "title": "Minimal goal",
                "reason": "Exercise the smallest wire shape",
                "alignment_rationale": "Supports the mission",
            }
        ],
        "milestones": [{"alias": "first", "goal_alias": "minimal", "title": "First milestone"}],
        "evidence_dispositions": [],
        "next_action": "Begin",
    }

    result = dispatcher.execute(
        PlanningCapabilityCall(
            "minimal-optional-omission",
            "submit_plan_proposal",
            {
                "run_id": "run-bound",
                "brief_context_digest": "sha256:v1:" + "b" * 64,
                "draft": minimal_draft,
            },
        )
    )

    assert result.status == "ok"
    _, command = lifecycle.calls[0]
    assert isinstance(command, PlanningCommand)
    assert isinstance(command.payload, SubmitProposalDraft)
    draft = command.payload.draft
    assert draft.mission.constraints == []
    assert draft.mission.out_of_scope == []
    assert draft.goals[0].status == "active"
    assert draft.goals[0].existing_goal_id == ""
    assert draft.milestones[0].notes == ""
    assert draft.milestones[0].concept_aliases == ()
    assert draft.milestones[0].existing_milestone_id == ""
    assert draft.topics == ()
    assert draft.concepts == ()
    assert draft.concept_relations == ()
    assert draft.resources == ()
    assert draft.unknowns == ()
    assert draft.requested_status == "draft"
    assert draft.target_date == ""
    assert draft.energy_floor == 3
    assert draft.review_cadence_days == 3
    assert draft.goal_limit_override_requested is False
    assert draft.goal_limit_override_reason == ""


def test_submit_requires_explicit_evidence_dispositions_before_lifecycle() -> None:
    """Omitting coverage must fail even when the offered evidence set may later be empty."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()
    draft = _draft()
    del draft["evidence_dispositions"]

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "missing-evidence-coverage",
                "submit_plan_proposal",
                {
                    "run_id": "run-bound",
                    "brief_context_digest": "sha256:v1:" + "b" * 64,
                    "draft": draft,
                },
            )
        )

    assert lifecycle.calls == []


@pytest.mark.parametrize(
    "path",
    [
        ("title",),
        ("mission",),
        ("goals",),
        ("milestones",),
        ("evidence_dispositions",),
        ("next_action",),
        ("mission", "why"),
        ("mission", "success"),
        ("goals", 0, "alias"),
        ("goals", 0, "title"),
        ("goals", 0, "reason"),
        ("goals", 0, "alignment_rationale"),
        ("milestones", 0, "alias"),
        ("milestones", 0, "goal_alias"),
        ("milestones", 0, "title"),
        ("concepts", 0, "alias"),
        ("concepts", 0, "display_label"),
        ("concept_relations", 0, "source_alias"),
        ("concept_relations", 0, "target_alias"),
        ("concept_relations", 0, "relation"),
        ("concept_relations", 0, "reason"),
        ("concept_relations", 0, "provenance"),
        ("evidence_dispositions", 0, "evidence_id"),
        ("evidence_dispositions", 0, "disposition"),
        ("evidence_dispositions", 0, "reason"),
        ("resources", 0, "label"),
        ("unknowns", 0, "unknown_id"),
        ("unknowns", 0, "question"),
        ("unknowns", 0, "impact"),
    ],
)
def test_every_nested_required_wire_field_is_refused_before_lifecycle(
    path: tuple[str | int, ...],
) -> None:
    """The manual decoder must stay authoritative for every advertised required field."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()
    draft = deepcopy(_draft_with_every_required_shape())
    _delete_path(draft, path)

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "missing-required-field",
                "submit_plan_proposal",
                {
                    "run_id": "run-bound",
                    "brief_context_digest": "sha256:v1:" + "b" * 64,
                    "draft": draft,
                },
            )
        )

    assert lifecycle.calls == []


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        (
            "submit_plan_proposal",
            {"brief_context_digest": "sha256:v1:" + "b" * 64, "draft": _draft()},
        ),
        ("submit_plan_proposal", {"run_id": "run-bound", "draft": _draft()}),
        (
            "submit_plan_proposal",
            {"run_id": "run-bound", "brief_context_digest": "sha256:v1:" + "b" * 64},
        ),
        ("get_plan_proposal", {"proposal_id": "proposal-1"}),
        ("get_plan_proposal", {"run_id": "run-bound"}),
    ],
)
def test_every_top_level_required_wire_field_is_refused_before_lifecycle(
    name: str,
    arguments: dict[str, object],
) -> None:
    """Top-level required arrays must remain synchronized with dispatcher validation."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(PlanningCapabilityCall("missing-required-field", name, arguments))

    assert lifecycle.calls == []


@pytest.mark.parametrize(("path", "invalid"), _SCHEMA_TYPE_CASES)
def test_every_schema_property_rejects_null_and_wrong_type_before_lifecycle(
    path: tuple[str | int, ...],
    invalid: object,
) -> None:
    """Changing any schema type guard must expose malformed JSON before handle()."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()
    draft = deepcopy(_draft_with_every_schema_property())
    _set_path(draft, path, invalid)

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "wrong-schema-type",
                "submit_plan_proposal",
                {
                    "run_id": "run-bound",
                    "brief_context_digest": "sha256:v1:" + "b" * 64,
                    "draft": draft,
                },
            )
        )

    assert lifecycle.calls == []


@pytest.mark.parametrize(
    "path",
    [pytest.param(path, id=label) for label, path in _SCHEMA_ARRAY_PROPERTY_PATHS],
)
def test_every_wire_array_property_rejects_python_tuple_before_lifecycle(
    path: tuple[str | int, ...],
) -> None:
    """Native/scripted adapters must not widen a JSON array into another sequence type."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()
    draft = deepcopy(_draft_with_every_schema_property())
    array_value = _value_at_path(draft, path)
    assert isinstance(array_value, list)
    _set_path(draft, path, tuple(array_value))

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "tuple-array",
                "submit_plan_proposal",
                {
                    "run_id": "run-bound",
                    "brief_context_digest": "sha256:v1:" + "b" * 64,
                    "draft": draft,
                },
            )
        )

    assert lifecycle.calls == []


@pytest.mark.parametrize(("name", "path", "invalid"), _TOP_LEVEL_SCHEMA_TYPE_CASES)
def test_every_top_level_schema_property_rejects_null_and_wrong_type_before_lifecycle(
    name: str,
    path: tuple[str | int, ...],
    invalid: object,
) -> None:
    """The dispatcher must enforce the outer tool schema before any domain call."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    arguments: dict[str, object]
    if name == "submit_plan_proposal":
        arguments = {
            "run_id": "run-bound",
            "brief_context_digest": "sha256:v1:" + "b" * 64,
            "draft": _draft(),
        }
    else:
        arguments = {"run_id": "run-bound", "proposal_id": "proposal-1"}
    _set_path(arguments, path, invalid)
    dispatcher, lifecycle = _dispatcher()

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(PlanningCapabilityCall("wrong-outer-type", name, arguments))

    assert lifecycle.calls == []


@pytest.mark.parametrize("arguments", [None, [], (), "not-an-object", 7])
def test_capability_argument_root_rejects_every_non_object_json_type(arguments: object) -> None:
    """A tool argument root must be an object before even prepare can touch lifecycle state."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall("wrong-root-type", "prepare_plan", arguments)  # type: ignore[arg-type]
        )

    assert lifecycle.calls == []


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
        ("prepare_plan", {"idempotency_key": "model-key"}),
        ("prepare_plan", {"scope": {"conversation_id": "model-choice"}}),
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


@pytest.mark.parametrize(
    "case",
    [
        "unknown_status",
        "goal_status",
        "energy_floor_zero",
        "energy_floor_eleven",
        "review_cadence_zero",
        "relation_enum",
        "evidence_disposition_enum",
        "unresolved_evidence_without_reason",
        "requested_status_enum",
        "goal_max_items",
        "resource_url_max_length",
    ],
)
def test_advertised_wire_constraints_are_enforced_before_lifecycle(case: str) -> None:
    """Removing enum/min/max validation must never let malformed wire data reach handle()."""
    from studyloop.planning.capabilities import CapabilityRefusedError, PlanningCapabilityCall

    dispatcher, lifecycle = _dispatcher()

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "malformed-scalar",
                "submit_plan_proposal",
                {
                    "run_id": "run-bound",
                    "brief_context_digest": "sha256:v1:" + "b" * 64,
                    "draft": _malformed_schema_draft(case),
                },
            )
        )

    assert lifecycle.calls == []


@pytest.mark.parametrize(
    "case",
    [
        "unknown_status",
        "goal_status",
        "energy_floor_zero",
        "energy_floor_eleven",
        "review_cadence_zero",
        "relation_enum",
        "evidence_disposition_enum",
        "unresolved_evidence_without_reason",
        "requested_status_enum",
        "goal_max_items",
        "resource_url_max_length",
    ],
)
def test_malformed_wire_data_creates_no_real_lifecycle_journal_or_private_artifact(
    tmp_path, case: str
) -> None:
    """Decoder refusal must happen before the real lifecycle can persist a proposal."""
    from planning_lifecycle_support import lifecycle

    from studyloop.planning.capabilities import (
        CapabilityRefusedError,
        PlanningCapabilityCall,
        PlanningCapabilityDispatcher,
        PlanningCapabilityScope,
    )

    service = lifecycle(tmp_path)
    dispatcher = PlanningCapabilityDispatcher(
        service,
        PlanningRequest("create", "A vague dump", f"request-{case}"),
        scope=PlanningCapabilityScope(f"conversation-{case}", f"turn-{case}", f"attempt-{case}"),
    )
    prepared = dispatcher.execute(PlanningCapabilityCall("prepare", "prepare_plan", {}))
    run_id = prepared.payload["run_id"]
    assert isinstance(run_id, str)
    before = _durable_planning_state(tmp_path)

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "malformed-scalar",
                "submit_plan_proposal",
                {
                    "run_id": run_id,
                    "brief_context_digest": prepared.payload["brief_context_digest"],
                    "draft": _malformed_schema_draft(case),
                },
            )
        )

    assert _durable_planning_state(tmp_path) == before


@pytest.mark.parametrize(
    ("case", "path"),
    [
        ("required-milestones-null", ("milestones",)),
        ("required-evidence-null", ("evidence_dispositions",)),
        ("optional-unknowns-null", ("unknowns",)),
        ("optional-energy-null", ("energy_floor",)),
        ("nested-optional-constraints-null", ("mission", "constraints")),
    ],
)
def test_explicit_null_creates_no_real_lifecycle_journal_or_private_artifact(
    tmp_path,
    case: str,
    path: tuple[str | int, ...],
) -> None:
    """Required and optional nulls must be refused before durable proposal effects."""
    from planning_lifecycle_support import lifecycle

    from studyloop.planning.capabilities import (
        CapabilityRefusedError,
        PlanningCapabilityCall,
        PlanningCapabilityDispatcher,
        PlanningCapabilityScope,
    )

    service = lifecycle(tmp_path)
    dispatcher = PlanningCapabilityDispatcher(
        service,
        PlanningRequest("create", "A vague dump", f"request-{case}"),
        scope=PlanningCapabilityScope(f"conversation-{case}", f"turn-{case}", f"attempt-{case}"),
    )
    prepared = dispatcher.execute(PlanningCapabilityCall("prepare", "prepare_plan", {}))
    run_id = prepared.payload["run_id"]
    assert isinstance(run_id, str)
    draft = _draft()
    _set_path(draft, path, None)
    before = _durable_planning_state(tmp_path)

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "explicit-null",
                "submit_plan_proposal",
                {
                    "run_id": run_id,
                    "brief_context_digest": prepared.payload["brief_context_digest"],
                    "draft": draft,
                },
            )
        )

    assert _durable_planning_state(tmp_path) == before


@pytest.mark.parametrize(
    ("case", "path"),
    [
        ("required-milestones-tuple", ("milestones",)),
        ("required-evidence-tuple", ("evidence_dispositions",)),
        ("optional-unknowns-tuple", ("unknowns",)),
        ("nested-required-success-tuple", ("mission", "success")),
        ("nested-optional-concept-aliases-tuple", ("milestones", 0, "concept_aliases")),
    ],
)
def test_tuple_array_creates_no_real_lifecycle_journal_or_private_artifact(
    tmp_path,
    case: str,
    path: tuple[str | int, ...],
) -> None:
    """Non-JSON sequences must be refused before durable proposal effects."""
    from planning_lifecycle_support import lifecycle

    from studyloop.planning.capabilities import (
        CapabilityRefusedError,
        PlanningCapabilityCall,
        PlanningCapabilityDispatcher,
        PlanningCapabilityScope,
    )

    service = lifecycle(tmp_path)
    dispatcher = PlanningCapabilityDispatcher(
        service,
        PlanningRequest("create", "A vague dump", f"request-{case}"),
        scope=PlanningCapabilityScope(f"conversation-{case}", f"turn-{case}", f"attempt-{case}"),
    )
    prepared = dispatcher.execute(PlanningCapabilityCall("prepare", "prepare_plan", {}))
    run_id = prepared.payload["run_id"]
    assert isinstance(run_id, str)
    draft = _draft()
    array_value = _value_at_path(draft, path)
    assert isinstance(array_value, list)
    _set_path(draft, path, tuple(array_value))
    before = _durable_planning_state(tmp_path)

    with pytest.raises(CapabilityRefusedError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "tuple-array",
                "submit_plan_proposal",
                {
                    "run_id": run_id,
                    "brief_context_digest": prepared.payload["brief_context_digest"],
                    "draft": draft,
                },
            )
        )

    assert _durable_planning_state(tmp_path) == before


def test_same_provider_call_id_is_isolated_by_server_owned_conversation_scope(tmp_path) -> None:
    """A provider repeating one call ID must not collide across independent conversations."""
    from planning_lifecycle_support import lifecycle

    from studyloop.planning.capabilities import (
        PlanningCapabilityCall,
        PlanningCapabilityDispatcher,
        PlanningCapabilityScope,
    )

    service = lifecycle(tmp_path)
    proposal_ids: list[str] = []
    for suffix in ("a", "b"):
        dispatcher = PlanningCapabilityDispatcher(
            service,
            PlanningRequest("create", f"Dump {suffix}", f"request-{suffix}"),
            scope=PlanningCapabilityScope(
                conversation_id=f"conversation-{suffix}",
                turn_id=f"turn-{suffix}",
                attempt_id=f"attempt-{suffix}",
            ),
        )
        prepared = dispatcher.execute(
            PlanningCapabilityCall(f"prepare-{suffix}", "prepare_plan", {})
        )
        submitted = dispatcher.execute(
            PlanningCapabilityCall(
                "provider-call-1",
                "submit_plan_proposal",
                {
                    "run_id": prepared.payload["run_id"],
                    "brief_context_digest": prepared.payload["brief_context_digest"],
                    "draft": _draft(),
                },
            )
        )
        proposal_id = submitted.payload["proposal_id"]
        assert isinstance(proposal_id, str)
        proposal_ids.append(proposal_id)

    assert len(set(proposal_ids)) == 2


def test_scope_bound_key_replays_exact_payload_and_conflicts_on_changed_payload(tmp_path) -> None:
    """Durable retries need one stable key, while changed input under that key must conflict."""
    from planning_lifecycle_support import lifecycle

    from studyloop.planning import IdempotencyConflictError
    from studyloop.planning.capabilities import (
        PlanningCapabilityCall,
        PlanningCapabilityDispatcher,
        PlanningCapabilityScope,
    )

    service = lifecycle(tmp_path)
    dispatcher = PlanningCapabilityDispatcher(
        service,
        PlanningRequest("create", "One dump", "request-replay"),
        scope=PlanningCapabilityScope("conversation-1", "turn-1", "attempt-1"),
    )
    prepared = dispatcher.execute(PlanningCapabilityCall("prepare", "prepare_plan", {}))
    arguments = {
        "run_id": prepared.payload["run_id"],
        "brief_context_digest": prepared.payload["brief_context_digest"],
        "draft": _draft(),
    }
    call = PlanningCapabilityCall("provider-call-replayed", "submit_plan_proposal", arguments)

    first = dispatcher.execute(call)
    replay = dispatcher.execute(call)
    changed_arguments = {**arguments, "draft": {**_draft(), "title": "Changed payload"}}

    assert replay.payload["proposal_id"] == first.payload["proposal_id"]
    with pytest.raises(IdempotencyConflictError):
        dispatcher.execute(
            PlanningCapabilityCall(
                "provider-call-replayed",
                "submit_plan_proposal",
                changed_arguments,
            )
        )


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
