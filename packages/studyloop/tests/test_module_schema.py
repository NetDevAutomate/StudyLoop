"""Module-contract v1, DoD item 1: the six §5.3 fields on the practice schemas.

Spec: ``openspec/changes/module-contract-v1/proposal.md`` §5.3 (the example
deck and the field table) and §6 MC014 (ids slug-valid and unique within
their scope). The schema stays permissive beyond the id rules: whether
``solution`` requires ``scaffolding`` is the conformance checker's business
(MC010), not the schema's.

Coverage:

- The proposal's §5.3 example deck, verbatim, loads through
  ``studyloop.learning.practice.load_practice_deck`` (the first test; red
  against the pre-change schema with ``Extra inputs are not permitted``).
- Each new field round-trips through ``model_dump(by_alias=True)`` under its
  proposal JSON name (``mentorNotes``, ``cleanupCommand``).
- ``id`` is optional on deck and task so every existing deck still validates.
- Task ids, when present, are unique within the deck; the error names the
  duplicate.
- A malformed id (space + capitals, leading hyphen, 64+ characters) is
  rejected on deck and task alike.
- A pre-existing deck shape (title + one task with a ``command``
  verification) still validates.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pydantic = pytest.importorskip("pydantic")
from pydantic import ValidationError  # noqa: E402

from studyloop.content.schemas import (  # noqa: E402
    PracticeDeck,
    PracticeTask,
    PracticeVerification,
    practice_deck_json_schema,
)
from studyloop.learning.practice import load_practice_deck  # noqa: E402

# ---------------------------------------------------------------------------
# The §5.3 example deck, copied literally from proposal.md
# ---------------------------------------------------------------------------

EXAMPLE_DECK_JSON = """\
{
  "id": "pods-and-namespaces",
  "title": "Pods and namespaces",
  "tasks": [
    {
      "id": "pods-01",
      "taskType": "apply",
      "prompt": "Create a namespace `drill` and run an nginx:1.27 pod named `web` in it.",
      "successCriteria": [
        "Namespace `drill` exists",
        "Pod `web` in `drill` is Running with image nginx:1.27"
      ],
      "expectedLearningOutcome": "Distinguish namespace scope from cluster scope when creating workloads.",
      "hint": "Which flag tells kubectl where to put the pod?",
      "solution": "kubectl create ns drill && kubectl run web --image=nginx:1.27 -n drill",
      "scaffolding": "guided",
      "mentorNotes": "Common slip: creating the pod in `default` and not noticing. Ask them where it landed before saying anything.",
      "verification": {
        "kind": "command",
        "successCriteria": ["Check script exits 0"],
        "setupCommand": "scripts/setup-pods-01.sh",
        "command": "scripts/check-pods-01.sh",
        "cleanupCommand": "scripts/cleanup-pods-01.sh",
        "timeoutSeconds": 30
      }
    }
  ]
}
"""  # noqa: E501 -- verbatim from proposal.md §5.3; the literal is the contract

NEW_TASK_FIELDS = ("id", "solution", "scaffolding", "mentorNotes")
NEW_VERIFICATION_FIELDS = ("cleanupCommand",)


def _example_deck() -> dict[str, Any]:
    return json.loads(EXAMPLE_DECK_JSON)


def _legacy_task(**overrides: Any) -> dict[str, Any]:
    """The pre-§5.3 task shape: no id, no solution, no scaffolding, no notes."""
    task: dict[str, Any] = {
        "taskType": "build",
        "prompt": "Write a function that reverses a list.",
        "successCriteria": ["Returns the reversed list"],
        "expectedLearningOutcome": "Use slicing for reversal.",
        "verification": {
            "kind": "command",
            "successCriteria": ["pytest exits 0"],
            "command": "pytest -q",
        },
    }
    task.update(overrides)
    return task


# ---------------------------------------------------------------------------
# 1. The example deck loads through the real loader
# ---------------------------------------------------------------------------


def test_proposal_example_deck_loads_through_load_practice_deck(tmp_path: Path) -> None:
    """The §5.3 example is the contract; it must validate as written.

    Red against the pre-change schema: ``extra: forbid`` rejects ``id``,
    ``solution``, ``scaffolding``, ``mentorNotes`` and ``cleanupCommand``
    with ``Extra inputs are not permitted``.
    """
    path = tmp_path / "pods-and-namespaces.json"
    path.write_text(EXAMPLE_DECK_JSON, encoding="utf-8")

    deck = load_practice_deck(path)

    assert deck.id == "pods-and-namespaces"
    assert deck.title == "Pods and namespaces"
    task = deck.tasks[0]
    assert task.id == "pods-01"
    assert task.solution == "kubectl create ns drill && kubectl run web --image=nginx:1.27 -n drill"
    assert task.scaffolding == "guided"
    assert task.mentor_notes.startswith("Common slip:")
    assert task.verification is not None
    assert task.verification.cleanup_command == "scripts/cleanup-pods-01.sh"
    assert task.verification.timeout_seconds == 30


# ---------------------------------------------------------------------------
# 2. Round-trip under the proposal's JSON names
# ---------------------------------------------------------------------------


def test_six_fields_round_trip_by_alias() -> None:
    raw = _example_deck()
    deck = PracticeDeck.model_validate(raw)

    dumped = deck.model_dump(mode="json", by_alias=True)

    assert dumped["id"] == raw["id"]
    task_out, task_in = dumped["tasks"][0], raw["tasks"][0]
    for name in NEW_TASK_FIELDS:
        assert task_out[name] == task_in[name], name
    for name in NEW_VERIFICATION_FIELDS:
        assert task_out["verification"][name] == task_in["verification"][name], name
    # The dump must use the camelCase alias, never the Python attribute.
    assert "mentor_notes" not in task_out
    assert "cleanup_command" not in task_out["verification"]


def test_round_trip_is_stable_through_write_json(tmp_path: Path) -> None:
    deck = PracticeDeck.model_validate(_example_deck())

    path = deck.write_json(tmp_path, slug="pods")
    reloaded = load_practice_deck(path)

    assert reloaded == deck
    assert path.name == "pods-practice.json"


def test_json_schema_exposes_new_fields_under_their_aliases() -> None:
    schema = practice_deck_json_schema()

    assert "id" in schema["properties"]
    task_props = schema["$defs"]["PracticeTask"]["properties"]
    for name in NEW_TASK_FIELDS:
        assert name in task_props, name
    verification_props = schema["$defs"]["PracticeVerification"]["properties"]
    for name in NEW_VERIFICATION_FIELDS:
        assert name in verification_props, name


# ---------------------------------------------------------------------------
# 3. Optional id; defaults for the other new fields
# ---------------------------------------------------------------------------


def test_missing_id_is_accepted_on_deck_and_task() -> None:
    deck = PracticeDeck.model_validate({"title": "Legacy", "tasks": [_legacy_task()]})

    assert deck.id is None
    assert deck.tasks[0].id is None


def test_new_task_fields_default_to_empty_or_none() -> None:
    task = PracticeTask.model_validate(_legacy_task())

    assert task.solution == ""
    assert task.mentor_notes == ""
    assert task.scaffolding is None
    assert task.verification is not None
    assert task.verification.cleanup_command == ""


def test_populate_by_name_still_accepts_snake_case_attributes() -> None:
    """``populate_by_name`` is kept as it was: Python callers may use the attribute name."""
    task = PracticeTask.model_validate(
        _legacy_task(mentor_notes="never shown to the learner"),
    )
    verification = PracticeVerification.model_validate(
        {
            "kind": "command",
            "successCriteria": ["ok"],
            "cleanup_command": "scripts/cleanup.sh",
        }
    )

    assert task.mentor_notes == "never shown to the learner"
    assert verification.cleanup_command == "scripts/cleanup.sh"


def test_pre_existing_deck_shape_still_validates() -> None:
    """A deck written before §5.3 (title + one command-verified task) is unchanged."""
    raw = {"title": "Reversal", "tasks": [_legacy_task()]}

    deck = PracticeDeck.model_validate(raw)

    assert deck.title == "Reversal"
    assert deck.tasks[0].verification is not None
    assert deck.tasks[0].verification.kind == "command"
    # Nothing was added to the on-disk shape that an old reader would trip on
    # beyond the new keys with their defaults.
    dumped = deck.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    assert dumped == raw


def test_extra_fields_are_still_forbidden() -> None:
    """``extra: forbid`` is unchanged: a seventh, unknown field is still rejected."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PracticeTask.model_validate(_legacy_task(level="L2"))
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PracticeDeck.model_validate(
            {"title": "x", "tasks": [_legacy_task()], "module": "kdrill"},
        )


# ---------------------------------------------------------------------------
# 4. Id rules (MC014): slug-valid, unique within the deck
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        pytest.param("Pods Basics", id="space-and-capitals"),
        pytest.param("-x", id="leading-hyphen"),
        pytest.param("a" * 64, id="64-chars"),
        pytest.param("", id="empty"),
        pytest.param("pods_01", id="underscore"),
    ],
)
def test_malformed_task_id_is_rejected(bad_id: str) -> None:
    with pytest.raises(ValidationError, match="id"):
        PracticeTask.model_validate(_legacy_task(id=bad_id))


@pytest.mark.parametrize(
    "bad_id",
    [
        pytest.param("Pods Basics", id="space-and-capitals"),
        pytest.param("-x", id="leading-hyphen"),
        pytest.param("a" * 64, id="64-chars"),
    ],
)
def test_malformed_deck_id_is_rejected(bad_id: str) -> None:
    with pytest.raises(ValidationError, match="id"):
        PracticeDeck.model_validate({"id": bad_id, "title": "x", "tasks": [_legacy_task()]})


@pytest.mark.parametrize(
    "good_id",
    [
        pytest.param("a", id="single-char"),
        pytest.param("7up", id="leading-digit"),
        pytest.param("pods-01", id="hyphenated"),
        pytest.param("a" * 63, id="63-chars"),
    ],
)
def test_well_formed_id_is_accepted(good_id: str) -> None:
    deck = PracticeDeck.model_validate(
        {"id": good_id, "title": "x", "tasks": [_legacy_task(id=good_id)]},
    )

    assert deck.id == good_id
    assert deck.tasks[0].id == good_id


def test_duplicate_task_ids_are_rejected_and_the_error_names_the_duplicate() -> None:
    raw = {
        "title": "Dup",
        "tasks": [
            _legacy_task(id="pods-01"),
            _legacy_task(id="pods-02"),
            _legacy_task(id="pods-01"),
        ],
    }

    with pytest.raises(ValidationError, match="pods-01") as excinfo:
        PracticeDeck.model_validate(raw)

    message = str(excinfo.value)
    assert "duplicate" in message.lower()
    assert "pods-02" not in message


def test_tasks_without_ids_do_not_count_as_duplicates() -> None:
    """Two id-less tasks are legal: uniqueness applies only to ids that are present."""
    deck = PracticeDeck.model_validate(
        {"title": "No ids", "tasks": [_legacy_task(), _legacy_task(), _legacy_task(id="only-one")]},
    )

    assert [t.id for t in deck.tasks] == [None, None, "only-one"]


# ---------------------------------------------------------------------------
# 5. scaffolding is a closed enum
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", ["guided", "hinted", "unaided", "exam"])
def test_scaffolding_accepts_the_four_levels(level: str) -> None:
    task = PracticeTask.model_validate(_legacy_task(scaffolding=level))

    assert task.scaffolding == level


def test_scaffolding_rejects_kdrill_level_names() -> None:
    """kdrill's L0-L3 are mapped at conversion time, not accepted by the schema."""
    with pytest.raises(ValidationError, match="scaffolding"):
        PracticeTask.model_validate(_legacy_task(scaffolding="L0"))


def test_solution_without_scaffolding_is_accepted_by_the_schema() -> None:
    """Whether ``solution`` requires ``scaffolding`` is MC010 (conformance), not the schema."""
    task = PracticeTask.model_validate(_legacy_task(solution="print(1)"))

    assert task.solution == "print(1)"
    assert task.scaffolding is None
