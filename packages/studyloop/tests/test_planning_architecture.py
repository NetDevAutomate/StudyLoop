"""Architecture guardrails for the sole planning mutation seam."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from studyloop.planning.compat import proposal_draft_from_plan
from studyloop.planning.contracts import LifecycleValidationError
from studyloop.planning.models import (
    ConceptRef,
    ConceptRelation,
    Goal,
    Milestone,
    Mission,
    StudyPlan,
)
from studyloop.planning.runtime import planning_lifecycle, planning_paths, planning_repository
from studyloop.planning.store import PLANS_DIR_ENV

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "studyloop"
NORMAL_PRODUCT_AREAS = (
    PACKAGE_ROOT / "cli",
    PACKAGE_ROOT / "web",
    PACKAGE_ROOT / "mcp",
    PACKAGE_ROOT / "session",
    PACKAGE_ROOT / "session_runtime",
    PACKAGE_ROOT / "session_state.py",
    PACKAGE_ROOT / "agent_launcher.py",
    PACKAGE_ROOT / "adapters",
    PACKAGE_ROOT / "planning" / "evaluation.py",
)
RAW_WRITERS = {
    "create_plan",
    "save_plan",
    "delete_plan",
    "_create_plan",
    "_save_plan",
    "_delete_plan",
}


def _source_files() -> list[Path]:
    files: list[Path] = []
    for area in NORMAL_PRODUCT_AREAS:
        if area.is_file():
            files.append(area)
        elif area.is_dir():
            files.extend(area.rglob("*.py"))
    files.append(PACKAGE_ROOT / "planning" / "__init__.py")
    return sorted(set(files))


def _raw_writer_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases: set[str] = set()
    import_module_aliases = {"__import__"}
    importlib_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name == "importlib":
                    importlib_aliases.add(imported.asname or imported.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for imported in node.names:
                if imported.name == "import_module":
                    import_module_aliases.add(imported.asname or imported.name)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                if imported.name in RAW_WRITERS:
                    aliases.add(imported.asname or imported.name)
                    violations.append(f"line {node.lineno}: imports {imported.name}")
                if path.name == "__init__.py" and imported.name in RAW_WRITERS:
                    violations.append(f"line {node.lineno}: publicly re-exports {imported.name}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in aliases | RAW_WRITERS:
                violations.append(f"line {node.lineno}: calls {node.func.id}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in RAW_WRITERS:
                violations.append(f"line {node.lineno}: qualified call {node.func.attr}")
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in RAW_WRITERS
            ):
                violations.append(f"line {node.lineno}: dynamic writer lookup {node.args[1].value}")
            elif (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                module_name = node.args[0].value
                dynamic_import = (
                    isinstance(node.func, ast.Name) and node.func.id in import_module_aliases
                ) or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in importlib_aliases
                )
                if dynamic_import and module_name == "studyloop.planning.store":
                    violations.append(f"line {node.lineno}: dynamically imports planning.store")
        elif isinstance(node, ast.Attribute) and node.attr in RAW_WRITERS:
            violations.append(f"line {node.lineno}: references qualified {node.attr}")
        elif (
            path.name == "__init__.py"
            and isinstance(node, (ast.List, ast.Tuple, ast.Set))
            and any(
                isinstance(item, ast.Constant) and item.value in RAW_WRITERS for item in node.elts
            )
        ):
            violations.append(f"line {node.lineno}: raw writer listed as public API")
    return violations


def test_normal_product_code_cannot_bypass_the_planning_lifecycle() -> None:
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): found
        for path in _source_files()
        if (found := _raw_writer_violations(path))
    }
    assert violations == {}


def test_architecture_gate_scans_the_actual_session_and_agent_roots() -> None:
    relative = {path.relative_to(PACKAGE_ROOT).as_posix() for path in _source_files()}
    assert "session/__init__.py" in relative
    assert "session_runtime/__init__.py" in relative
    assert "session_state.py" in relative
    assert "agent_launcher.py" in relative
    assert "adapters/__init__.py" in relative
    assert "mcp/__init__.py" in relative


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            (
                'import importlib\nstore = importlib.import_module("studyloop.planning.store")\n'
                "store.save_plan(plan)\n"
            ),
            "dynamically imports planning.store",
        ),
        (
            (
                "from importlib import import_module as load\n"
                'store = load("studyloop.planning.store")\n'
                'getattr(store, "save_plan")(plan)\n'
            ),
            "dynamic writer lookup save_plan",
        ),
        (
            (
                'store = __import__("studyloop.planning.store", fromlist=["save_plan"])\n'
                'getattr(store, "save_plan")(plan)\n'
            ),
            "dynamically imports planning.store",
        ),
    ],
)
def test_architecture_gate_detects_dynamic_writer_bypasses(
    tmp_path: Path, source: str, expected: str
) -> None:
    module = tmp_path / "bypass.py"
    module.write_text(source, encoding="utf-8")
    assert any(expected in violation for violation in _raw_writer_violations(module))


@pytest.mark.parametrize("relative", ["study-plans", "nested/custom-plans"])
def test_runtime_paths_keep_the_configured_directory_as_the_document_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    documents = tmp_path / relative
    monkeypatch.setenv(PLANS_DIR_ENV, str(documents))

    paths = planning_paths()

    assert paths.plans == documents
    assert paths.root == documents.parent
    assert paths.lock_file == documents.parent / ".planning.lock"
    assert paths.journal == documents.parent / "planning-journal.jsonl"
    assert paths.private_runs == documents.parent / "private-runs"
    assert paths.plans != documents / "plans"


def test_runtime_repository_and_lifecycle_share_the_exact_same_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents = tmp_path / "overridden-plans"
    monkeypatch.setenv(PLANS_DIR_ENV, str(documents))
    expected = planning_paths()
    assert planning_repository().paths == expected
    assert planning_lifecycle().repository.paths == expected


def test_runtime_default_derives_from_settings_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    import studyloop.settings

    monkeypatch.delenv(PLANS_DIR_ENV, raising=False)
    monkeypatch.setattr(
        studyloop.settings,
        "load_settings",
        lambda: SimpleNamespace(state_dir=tmp_path / "state"),
    )
    paths = planning_paths()
    assert paths.plans == tmp_path / "state" / "study-plans"
    assert paths.root == tmp_path / "state"
    assert paths.lock_file.parent == paths.journal.parent == paths.private_runs.parent == paths.root


def test_revision_translation_refuses_more_than_three_goals_without_truncating() -> None:
    plan = StudyPlan(
        "legacy",
        "Legacy",
        mission=Mission(why="Learn", success=["Show it"]),
        goals=[Goal(f"g-{index}", f"Goal {index}", "Why", "Aligned") for index in range(4)],
    )
    with pytest.raises(LifecycleValidationError, match=r"four goals|more than three"):
        proposal_draft_from_plan(plan, revise=True)
    assert len(plan.goals) == 4


def test_revision_translation_preserves_multiple_blank_entity_ids() -> None:
    plan = StudyPlan(
        "legacy",
        "Legacy",
        mission=Mission(why="Learn", success=["Show it"]),
        goals=[Goal("", "First", "Why", "Aligned")],
        concepts=[ConceptRef("", "Alpha"), ConceptRef("", "Beta")],
        milestones=[
            Milestone("One", concepts=["Alpha"], milestone_id="", goal_id=""),
            Milestone("Two", concepts=["Beta"], milestone_id="", goal_id=""),
        ],
    )
    draft = proposal_draft_from_plan(plan, revise=True)
    assert [item.title for item in draft.goals] == ["First"]
    assert [item.title for item in draft.milestones] == ["One", "Two"]
    assert len({item.alias for item in draft.milestones}) == 2
    assert [item.display_label for item in draft.concepts] == ["Alpha", "Beta"]
    assert len({item.alias for item in draft.concepts}) == 2


@pytest.mark.parametrize("identity", ["goal", "concept", "milestone"])
def test_revision_translation_refuses_duplicate_ids_without_cross_linking(identity: str) -> None:
    goal_ids = ("g-1", "g-2")
    concept_ids = ("c-1", "c-2")
    milestone_ids = ("m-1", "m-2")
    if identity == "goal":
        goal_ids = ("duplicate", "duplicate")
    elif identity == "concept":
        concept_ids = ("duplicate", "duplicate")
    else:
        milestone_ids = ("duplicate", "duplicate")
    plan = StudyPlan(
        "legacy",
        "Legacy",
        mission=Mission(why="Learn", success=["Show it"]),
        goals=[
            Goal(goal_ids[0], "First", "Why", "Aligned"),
            Goal(goal_ids[1], "Second", "Why", "Aligned"),
        ],
        concepts=[ConceptRef(concept_ids[0], "Alpha"), ConceptRef(concept_ids[1], "Beta")],
        milestones=[
            Milestone(
                "One", concepts=["Alpha"], milestone_id=milestone_ids[0], goal_id=goal_ids[0]
            ),
            Milestone("Two", concepts=["Beta"], milestone_id=milestone_ids[1], goal_id=goal_ids[1]),
        ],
    )
    with pytest.raises(LifecycleValidationError, match=rf"duplicate {identity} ids"):
        proposal_draft_from_plan(plan, revise=True)
    assert len(plan.goals) == len(plan.concepts) == len(plan.milestones) == 2


def test_revision_translation_preserves_explicit_concept_relations() -> None:
    plan = StudyPlan(
        "relations",
        "Relations",
        mission=Mission(why="Keep meaning", success=["Explain both"]),
        goals=[Goal("g-1", "Explain", "Needed", "Aligned")],
        concepts=[ConceptRef("c-1", "ABC"), ConceptRef("c-2", "Protocol")],
        concept_relations=[
            ConceptRelation("c-1", "c-2", "distinct", "Different abstractions", "learner")
        ],
    )
    draft = proposal_draft_from_plan(plan, revise=True)
    assert len(draft.concept_relations) == 1
    relation = draft.concept_relations[0]
    assert relation.source_alias != relation.target_alias
    assert relation.relation == "distinct"
    assert relation.reason == "Different abstractions"


def test_revision_translation_refuses_duplicate_normalised_concept_labels() -> None:
    plan = StudyPlan(
        "duplicate-labels",
        "Duplicate labels",
        mission=Mission(why="Keep identity", success=["Explain both"]),
        goals=[Goal("g-1", "Explain", "Needed", "Aligned")],
        concepts=[ConceptRef("c-1", "Window Function"), ConceptRef("c-2", " window   function ")],
        milestones=[
            Milestone(
                "Ambiguous",
                concepts=["Window Function"],
                milestone_id="m-1",
                goal_id="g-1",
            )
        ],
    )
    with pytest.raises(LifecycleValidationError, match="duplicate concept labels"):
        proposal_draft_from_plan(plan, revise=True)
    assert len(plan.concepts) == 2


def test_revision_translation_refuses_ambiguous_milestone_goal_link() -> None:
    plan = StudyPlan(
        "ambiguous",
        "Ambiguous",
        mission=Mission(why="Keep links", success=["Explain them"]),
        goals=[
            Goal("g-1", "First", "Needed", "Aligned"),
            Goal("g-2", "Second", "Needed", "Aligned"),
        ],
        milestones=[Milestone("Unlinked", milestone_id="m-1", goal_id="")],
    )
    with pytest.raises(LifecycleValidationError, match="blank goal id"):
        proposal_draft_from_plan(plan, revise=True)
