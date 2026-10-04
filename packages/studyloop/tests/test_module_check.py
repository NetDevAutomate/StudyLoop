"""Red tests for ``studyloop module check`` (proposal §6, MC001-MC016).

Wave 0 (C1) of module-contract v1, lane C. Everything here is expected to fail at this
commit, for two different reasons that the evidence transcript keeps apart:

- the 33 engine tests fail with ``NotImplementedError`` from the ``check_module`` stub
  until C2 lands the engine;
- the fixture-integrity tests fail until S2 (``feat/module-schema``) reaches this branch:
  they validate the fixture decks against ``PracticeDeck`` *with* the §5.3 fields and read
  ``SLUG_PATTERN`` / ``ScaffoldingLevel`` from ``studyloop.content.schemas``, none of which
  exist at the base of this branch.

Fixture layout: ``tests/fixtures/modules/valid-scaffold`` plus ``mcNNN/broken`` (breaks
exactly rule ``MCNNN``) and ``mcNNN/repaired`` (the minimal repair; a valid module). See the
README in that directory for the per-rule faults.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import ValidationError

from studyloop.content.schemas import PracticeDeck
from studyloop.modules.check import RULE_IDS, CheckReport, check_module

FIXTURES = Path(__file__).parent / "fixtures" / "modules"
VALID = FIXTURES / "valid-scaffold"


def _broken(rule: str) -> Path:
    return FIXTURES / rule.lower() / "broken"


def _repaired(rule: str) -> Path:
    return FIXTURES / rule.lower() / "repaired"


def _rule_ids(report: CheckReport) -> set[str]:
    return {finding.rule_id for finding in report.findings}


# ---------------------------------------------------------------------------
# Engine: 1 + 16 + 16 = 33 tests, red on NotImplementedError until C2
# ---------------------------------------------------------------------------


def test_valid_scaffold_passes_every_rule() -> None:
    report = check_module(VALID)
    assert report.ok is True
    assert report.findings == []


@pytest.mark.parametrize("rule", RULE_IDS)
def test_broken_fixture_fails_naming_exactly_one_rule(rule: str) -> None:
    report = check_module(_broken(rule))
    assert report.ok is False
    assert _rule_ids(report) == {rule}


@pytest.mark.parametrize("rule", RULE_IDS)
def test_repaired_twin_passes_every_rule(rule: str) -> None:
    report = check_module(_repaired(rule))
    assert report.ok is True
    assert report.findings == []


# ---------------------------------------------------------------------------
# Fixture integrity against the §5.3 schema (S2) -- red until S has merged
# ---------------------------------------------------------------------------
#
# ``SLUG_PATTERN`` and ``ScaffoldingLevel`` do not exist in ``studyloop.content.schemas``
# at this branch's base; they land with S2. They are read through ``importlib`` so this
# file type-checks at the commit stage (pyright runs there) while the tests still fail on
# the missing name at runtime -- that failure is this wave's red for them. Once S has
# merged these become plain imports.


def _schemas() -> Any:
    return importlib.import_module("studyloop.content.schemas")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _deck_files(module: Path) -> list[Path]:
    decks = sorted((module / "decks").glob("*.json"))
    assert decks, f"{module.relative_to(FIXTURES)} has no decks"
    return decks


def _manifest_id(module: Path) -> Any:
    return yaml.safe_load((module / "module.yaml").read_text(encoding="utf-8"))["id"]


_VALID_MODULES: list[Path] = [VALID, *(_repaired(rule) for rule in RULE_IDS)]
_SCHEMA_VALID_DECK_MODULES: list[Path] = [
    *_VALID_MODULES,
    *(_broken(rule) for rule in RULE_IDS if rule != "MC004"),
]


def test_every_deck_except_mc004_validates_against_practice_deck() -> None:
    """Only mc004/broken may fail MC004: every other fixture's fault lies elsewhere."""
    failures: list[str] = []
    for module in _SCHEMA_VALID_DECK_MODULES:
        for deck in _deck_files(module):
            try:
                PracticeDeck.model_validate(_load_json(deck))
            except ValidationError as exc:
                failures.append(f"{deck.relative_to(FIXTURES)}: {exc.error_count()} error(s)")
    assert failures == []


def test_mc004_deck_is_rejected_for_exactly_its_one_extra_key() -> None:
    [deck] = _deck_files(_broken("MC004"))
    with pytest.raises(ValidationError) as excinfo:
        PracticeDeck.model_validate(_load_json(deck))
    assert [error["loc"] for error in excinfo.value.errors()] == [("tasks", 0, "difficulty")]


def test_mc014_deck_validates_but_lacks_its_task_id() -> None:
    """MC014 must be attributable on its own.

    Under S2's schema a *missing* id is the one identity fault ``PracticeDeck`` accepts
    (``id: SlugId | None``); duplicate and malformed ids are schema rejections.
    """
    [deck] = _deck_files(_broken("MC014"))
    dumped = PracticeDeck.model_validate(_load_json(deck)).model_dump(by_alias=True)
    assert dumped.get("id") == "echo-basics"
    assert [task.get("id") for task in dumped["tasks"]] == [None]


def test_valid_fixture_ids_are_slug_valid() -> None:
    pattern = re.compile(_schemas().SLUG_PATTERN)
    bad: list[str] = []
    for module in _VALID_MODULES:
        ids: list[tuple[str, Any]] = [("module.yaml", _manifest_id(module))]
        for deck in _deck_files(module):
            data = _load_json(deck)
            ids.append((deck.name, data.get("id")))
            ids.extend((deck.name, task.get("id")) for task in data["tasks"])
        bad.extend(
            f"{module.relative_to(FIXTURES)}/{where}: {value!r}"
            for where, value in ids
            if not (isinstance(value, str) and pattern.fullmatch(value))
        )
    assert bad == []


def test_fixture_scaffolding_levels_are_in_the_enum() -> None:
    levels = set(get_args(_schemas().ScaffoldingLevel))
    assert levels == {"guided", "hinted", "unaided", "exam"}
    seen: set[Any] = set()
    for module in [*_VALID_MODULES, *(_broken(rule) for rule in RULE_IDS)]:
        for deck in _deck_files(module):
            for task in _load_json(deck)["tasks"]:
                if "scaffolding" in task:
                    seen.add(task["scaffolding"])
    assert seen and seen <= levels
