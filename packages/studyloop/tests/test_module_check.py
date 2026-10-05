"""Red tests for ``studyloop module check`` (proposal §6, MC001-MC017).

Wave 0 (C1) of module-contract v1, lane C. Two groups, kept apart in the evidence:

- the 33 engine tests fail with ``NotImplementedError`` from the ``check_module`` stub
  until C2 lands the engine (``evidence/C/check-16-rules.red.txt``);
- the five fixture-integrity tests validate the fixtures against S2's schema --
  ``PracticeDeck`` with the §5.3 fields, ``SLUG_PATTERN``, ``ScaffoldingLevel``. They were
  red before ``feat/module-schema`` merged (``evidence/C/schema-fixture-integrity.red.txt``)
  and pass once it has; they guard the fixtures, not the engine.

Fixture layout: ``tests/fixtures/modules/valid-scaffold`` plus ``mcNNN/broken`` (breaks
exactly rule ``MCNNN``) and ``mcNNN/repaired`` (the minimal repair; a valid module). See the
README in that directory for the per-rule faults.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import ValidationError

from studyloop.content.schemas import SLUG_PATTERN, PracticeDeck, ScaffoldingLevel
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


def test_rule_ids_are_mc001_to_mc017_in_table_order() -> None:
    """The rule table has seventeen stable ids (proposal §6; MC017 added by the K0 review,
    finding 6 -- coordinator-granted, K0-review F6). Every id has a broken/repaired fixture pair."""
    assert tuple(f"MC{n:03d}" for n in range(1, 18)) == RULE_IDS
    for rule in RULE_IDS:
        assert _broken(rule).is_dir() and _repaired(rule).is_dir(), rule


def test_mc017_kubeconfig_context_task_without_cleanup_is_refused_naming_task_and_phase() -> None:
    """Spec scenario (optional-modules, K0-review F6): GIVEN a manifest whose ``target.kind`` is
    ``kubeconfig-context`` and a deck task with a ``setupCommand`` but no ``cleanupCommand``
    -- WHEN ``module check`` runs -- THEN it fails (rule MC017) naming the task and the missing
    phase command, pointing at the deck task."""
    report = check_module(FIXTURES / "mc017" / "broken")

    assert report.ok is False
    findings = [f for f in report.findings if f.rule_id == "MC017"]
    assert len(findings) == 1, report.findings
    (finding,) = findings
    assert "echo-01" in finding.message and "cleanupCommand" in finding.message
    assert finding.path == "decks/echo-basics.json"
    assert finding.line is not None


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
# C2: finding shape -- file, line, redaction, the --json dict
# ---------------------------------------------------------------------------


def test_finding_carries_the_line_of_an_in_file_fault() -> None:
    """MC001's unknown key sits on line 6 of ``mc001/broken/module.yaml``."""
    [finding] = check_module(_broken("MC001")).findings
    assert (finding.rule_id, finding.path, finding.line) == ("MC001", "module.yaml", 6)
    assert "homepage" in finding.message


def test_finding_line_is_none_for_a_file_level_fault() -> None:
    """MC003 names the file that is absent; there is no line to point at."""
    [finding] = check_module(_broken("MC003")).findings
    assert (finding.rule_id, finding.path, finding.line) == ("MC003", "CHANGELOG.md", None)


def test_mc002_names_the_contract_versions_core_speaks() -> None:
    [finding] = check_module(_broken("MC002")).findings
    assert (finding.path, finding.line) == ("module.yaml", 2)
    assert "99" in finding.message
    assert "1" in finding.message


def test_mc009_finding_points_at_the_line_without_echoing_the_value() -> None:
    """A caught secret must not leak through the checker's own output."""
    [finding] = check_module(_broken("MC009")).findings
    assert (finding.path, finding.line) == ("scripts/check.sh", 3)
    assert "0123456789abcdef" not in finding.message
    assert "PASSWORD" in finding.message


def test_deck_findings_point_at_the_offending_field_line() -> None:
    """mc015's shell operator is in ``verification.command`` on line 22 of the deck."""
    [finding] = check_module(_broken("MC015")).findings
    assert (finding.path, finding.line) == ("decks/echo-basics.json", 22)


def test_report_to_dict_is_the_json_contract() -> None:
    payload = check_module(_broken("MC002")).to_dict()
    assert payload["ok"] is False
    [finding] = payload["findings"]
    assert set(finding) == {"rule_id", "message", "path", "line"}
    assert finding["rule_id"] == "MC002"
    assert finding["path"] == "module.yaml"
    assert finding["line"] == 2
    assert check_module(VALID).to_dict() == {"ok": True, "findings": []}


# ---------------------------------------------------------------------------
# Fixture integrity against the §5.3 schema (S2)
# ---------------------------------------------------------------------------


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
    parsed = PracticeDeck.model_validate(_load_json(deck))
    assert parsed.id == "echo-basics"
    assert [task.id for task in parsed.tasks] == [None]


def test_valid_fixture_ids_are_slug_valid() -> None:
    pattern = re.compile(SLUG_PATTERN)
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
    levels = set(get_args(ScaffoldingLevel))
    assert levels == {"guided", "hinted", "unaided", "exam"}
    seen: set[Any] = set()
    for module in [*_VALID_MODULES, *(_broken(rule) for rule in RULE_IDS)]:
        for deck in _deck_files(module):
            for task in _load_json(deck)["tasks"]:
                if "scaffolding" in task:
                    seen.add(task["scaffolding"])
    assert seen and seen <= levels


# ---------------------------------------------------------------------------
# C-review 2 and 3: MC009 scans every assignment on a line; MC012 catches compiled,
# cached and shebang-python code, not just *.py and four filenames
# ---------------------------------------------------------------------------


def _variant(tmp_path: Path, name: str) -> Path:
    """A writable copy of the valid scaffold to break in exactly one way."""
    target = tmp_path / name
    shutil.copytree(VALID, target, symlinks=True)
    return target


def test_mc009_sees_a_secret_after_a_placeholder_on_the_same_line(tmp_path: Path) -> None:
    """``PASSWORD=true API_TOKEN=<value>``: the first match is a placeholder, the second is not."""
    module = _variant(tmp_path, "two-assignments")
    script = module / "scripts" / "check.sh"
    fake_value = "plainly-fake-value"
    line = "PASSWORD=true API_" + "TOKEN=" + fake_value
    script.write_text(f"#!/bin/sh\n{line}\necho ready\nexit 0\n", encoding="utf-8")

    report = check_module(module)

    assert _rule_ids(report) == {"MC009"}
    [finding] = report.findings
    assert (finding.path, finding.line) == ("scripts/check.sh", 2)
    assert "API_" + "TOKEN" in finding.message
    assert fake_value not in finding.message


def test_mc009_still_ignores_a_line_of_placeholders_only(tmp_path: Path) -> None:
    module = _variant(tmp_path, "placeholders")
    script = module / "scripts" / "check.sh"
    script.write_text("#!/bin/sh\nPASSWORD=true TOKEN=null\necho ready\nexit 0\n", encoding="utf-8")
    assert check_module(module).ok is True


_PYTHON_SHEBANG = "#!/usr/bin/env python3\nprint('hello')\n"
_PYTHON_SHEBANG_DIRECT = "#!/usr/bin/python\nprint('hello')\n"


@pytest.mark.parametrize(
    ("relative", "content", "executable"),
    [
        pytest.param(
            "__pycache__/helper.cpython-312.pyc", b"\x00\x00compiled", False, id="pycache"
        ),
        pytest.param("tools/helper.pyc", b"\x00\x00compiled", False, id="pyc"),
        pytest.param("tools/helper.pyo", b"\x00\x00compiled", False, id="pyo"),
        pytest.param("scripts/helper", _PYTHON_SHEBANG.encode(), True, id="env-python3-shebang"),
        pytest.param(
            "scripts/run", _PYTHON_SHEBANG_DIRECT.encode(), True, id="usr-bin-python-shebang"
        ),
    ],
)
def test_mc012_rejects_compiled_cached_and_shebang_python_and_the_repaired_twin_passes(
    tmp_path: Path, relative: str, content: bytes, executable: bool
) -> None:
    module = _variant(tmp_path, "code")
    offending = module / relative
    offending.parent.mkdir(parents=True, exist_ok=True)
    offending.write_bytes(content)
    if executable:
        offending.chmod(0o755)

    report = check_module(module)
    assert _rule_ids(report) == {"MC012"}, [(f.rule_id, f.path) for f in report.findings]
    # the finding names the file, or the __pycache__ directory that holds it
    assert all(relative == f.path or relative.startswith(f.path + "/") for f in report.findings)

    # the repaired twin: the same tree without the offending file (and its empty dir)
    offending.unlink()
    if offending.parent.name == "__pycache__":
        offending.parent.rmdir()
    assert check_module(module).ok is True


def test_mc012_flags_an_empty_pycache_directory(tmp_path: Path) -> None:
    module = _variant(tmp_path, "empty-pycache")
    (module / "__pycache__").mkdir()
    report = check_module(module)
    assert _rule_ids(report) == {"MC012"}
    assert [f.path for f in report.findings] == ["__pycache__"]


def test_mc012_does_not_flag_a_posix_shell_shebang(tmp_path: Path) -> None:
    """``scripts/check.sh`` starts with ``#!/bin/sh``: shell is the module's own language."""
    module = _variant(tmp_path, "sh-only")
    (module / "scripts" / "extra.sh").write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    (module / "scripts" / "extra.sh").chmod(0o755)
    assert check_module(module).ok is True
