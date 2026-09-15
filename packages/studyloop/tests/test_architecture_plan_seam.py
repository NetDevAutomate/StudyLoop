"""Architecture guard: adapters reach study plans only through the seam (D-6).

Design §6. Policy that lives in an adapter is policy that exists once per
adapter — issue #7's readiness gate lived on one Web route and missed two
other doors into ``active``. The seam fixes that by construction *only if
adapters cannot go round it*, so this test parses every module under the
three adapter packages and fails on any import that reaches the storage,
index, authoring or evaluation layer directly:

* ``import studyloop.planning.store`` / ``from studyloop.planning.store import …``
  (and ``.index``, ``.authoring``, ``.evaluation``), relative forms resolved;
* ``from studyloop.planning import <name>`` where ``<name>`` is one of the
  explicitly listed writers/readers those four modules contribute to the
  package namespace — ``save_plan``, ``load_plan``, ``evaluate_and_record``,
  ``readiness``… — or one of the submodules themselves;
* ``import studyloop.planning`` / ``from studyloop import planning`` — a
  whole-package handle defeats the name check;
* a string constant naming a forbidden module (``importlib.import_module``).

Allowed: ``studyloop.planning.application|views|intents|errors``, and from
``studyloop.planning`` itself the re-exported view/intent/error names,
``PlanApplication``, the read-only constants (``PLAN_STATUSES``,
``CHECKPOINT_PHASES``, ``INTERVIEW``) and ``plans_dir`` — a location
resolver with no plan read or write behind it, used by ``studyloop plan
path``.

A second test plants ``from studyloop.planning.store import save_plan`` into a
temp copy of a real adapter module and asserts the checker rejects it, so a
green run is evidence the checker sees what it claims to. A third asserts the
explicit name list cannot rot: every callable or class ``studyloop.planning``
re-exports from the four modules must be listed (or explicitly allowed).

Out of scope, by construction: attribute access on an already-imported
allowed name, and imports built from non-literal strings.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

import studyloop

SRC_ROOT = Path(studyloop.__file__).resolve().parent.parent  # …/src
ADAPTER_PACKAGES = ("studyloop.cli", "studyloop.web.routes", "studyloop.mcp")

FORBIDDEN_MODULES = (
    "studyloop.planning.store",
    "studyloop.planning.index",
    "studyloop.planning.authoring",
    "studyloop.planning.evaluation",
)
ALLOWED_MODULES = (
    "studyloop.planning.application",
    "studyloop.planning.views",
    "studyloop.planning.intents",
    "studyloop.planning.errors",
)

#: Names ``studyloop.planning`` re-exports from the four forbidden modules. An
#: adapter importing one of these from the package has reached round the seam
#: exactly as surely as importing the module. Listed explicitly (design §6);
#: ``test_forbidden_name_list_covers_every_reexport`` keeps it honest.
FORBIDDEN_PACKAGE_NAMES = frozenset(
    {
        # the submodules themselves, as names
        "store",
        "index",
        "authoring",
        "evaluation",
        # store — document reads and writes, id allocation, the store error family
        "append_learning_record",
        "create_plan",
        "delete_plan",
        "list_plan_ids",
        "list_plans",
        "load_plan",
        "load_plan_text",
        "plan_path",
        "record_learning",
        "save_plan",
        "unique_plan_id",
        "InvalidPlanIdError",
        "PlanExistsError",
        "PlanNotFoundError",
        # index — the derived cache and the checkpoint log
        "checkpoint_history",
        "indexed_plans",
        "reindex_all",
        # authoring — the readiness policy, drafting, the interview and the seed
        "draft_plan",
        "interview_spec",
        "readiness",
        "seed_from_history",
        "InterviewQuestion",
        # evaluation — the checkpoint writer and its mutable result models
        "evaluate_and_record",
        "evaluate_plan",
        "PlanEvaluation",
        "ConceptEvidence",
    }
)

#: Re-exports that live in a forbidden module but carry no plan read or write.
ALLOWED_PACKAGE_NAMES = frozenset({"plans_dir"})


@dataclass(frozen=True)
class Violation:
    path: str
    lineno: int
    statement: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: {self.statement}  — {self.reason}"


def _module_name_for(path: Path) -> str:
    relative = path.resolve().relative_to(SRC_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(module_name: str, is_package: bool, level: int, target: str | None) -> str:
    """Turn ``from ..x import y`` inside ``module_name`` into an absolute module."""
    base = module_name.split(".")
    if not is_package:
        base = base[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    prefix = ".".join(base)
    if not target:
        return prefix
    return f"{prefix}.{target}" if prefix else target


def _is_forbidden_module(name: str) -> bool:
    return any(name == root or name.startswith(root + ".") for root in FORBIDDEN_MODULES)


def _check_module(path: Path, *, module_name: str | None = None) -> list[Violation]:
    """Every seam-bypassing import in one file (see the module docstring)."""
    module_name = module_name or _module_name_for(path)
    is_package = path.name == "__init__.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    out: list[Violation] = []

    def flag(node: ast.AST, reason: str) -> None:
        lineno = getattr(node, "lineno", 0)
        statement = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ast.dump(node)
        out.append(Violation(str(path), lineno, statement, reason))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    flag(node, f"imports {alias.name!r} directly; go through PlanApplication")
                elif alias.name == "studyloop.planning":
                    flag(node, "a whole-package handle reaches every storage module")
        elif isinstance(node, ast.ImportFrom):
            target = (
                _resolve_relative(module_name, is_package, node.level, node.module)
                if node.level
                else (node.module or "")
            )
            if _is_forbidden_module(target):
                flag(node, f"imports from {target!r} directly; go through PlanApplication")
            elif target == "studyloop.planning":
                for alias in node.names:
                    if alias.name in FORBIDDEN_PACKAGE_NAMES:
                        flag(
                            node,
                            f"{alias.name!r} is a store/index/authoring/evaluation name "
                            "re-exported by the package; go through PlanApplication",
                        )
            elif target == "studyloop" and any(a.name == "planning" for a in node.names):
                flag(node, "a whole-package handle reaches every storage module")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _is_forbidden_module(node.value)
        ):
            flag(node, f"names {node.value!r} as a string (dynamic import)")
    return out


def _adapter_files() -> list[Path]:
    files: list[Path] = []
    for package in ADAPTER_PACKAGES:
        root = SRC_ROOT.joinpath(*package.split("."))
        assert root.is_dir(), root
        files.extend(sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts))
    return files


def check_adapters() -> tuple[list[Path], list[Violation]]:
    files = _adapter_files()
    violations = [violation for path in files for violation in _check_module(path)]
    return files, violations


# ---------------------------------------------------------------------------


def test_adapters_import_plans_only_through_the_seam() -> None:
    files, violations = check_adapters()

    scanned = {str(p.relative_to(SRC_ROOT)) for p in files}
    for must_see in (
        "studyloop/cli/_plan.py",
        "studyloop/web/routes/plans.py",
        "studyloop/mcp/tools.py",
    ):
        assert must_see in scanned, f"the guard did not scan {must_see}"
    assert len(files) > 30, "the guard scanned suspiciously few adapter modules"

    assert violations == [], "seam bypass:\n" + "\n".join(str(v) for v in violations)


@pytest.mark.parametrize(
    "planted",
    [
        "from studyloop.planning.store import save_plan",
        "from studyloop.planning.index import record_checkpoint",
        "from studyloop.planning.authoring import readiness",
        "from studyloop.planning.evaluation import evaluate_and_record",
        "import studyloop.planning.store as plan_store",
        "from studyloop.planning import load_plan",
        "from studyloop.planning import store",
        "from studyloop.planning import PlanApplication, save_plan",
        "from ...planning.store import save_plan",
        "from ...planning import readiness",
        "import studyloop.planning",
        "from studyloop import planning",
        'store_module = __import__("studyloop.planning.store")',
        "def later():\n    from studyloop.planning import create_plan\n    return create_plan",
    ],
    ids=[
        "store-module",
        "index-module",
        "authoring-module",
        "evaluation-module",
        "import-as",
        "package-name",
        "package-submodule",
        "mixed-allowed-and-forbidden",
        "relative-module",
        "relative-package-name",
        "whole-package",
        "from-studyloop-import-planning",
        "dynamic-string",
        "nested-in-function",
    ],
)
def test_planted_violation_is_rejected(tmp_path, planted: str) -> None:
    """Plant a bypass into a copy of a real adapter and prove the checker sees it."""
    original = SRC_ROOT / "studyloop" / "web" / "routes" / "plans.py"
    assert _check_module(original) == [], "the fixture module must itself be clean"

    copy = tmp_path / "plans.py"
    shutil.copy(original, copy)
    copy.write_text(copy.read_text(encoding="utf-8") + "\n" + planted + "\n", encoding="utf-8")

    violations = _check_module(copy, module_name="studyloop.web.routes.plans")

    assert violations, f"planted bypass not detected: {planted!r}"
    assert all(
        "PlanApplication" in v.reason or "package" in v.reason or "string" in v.reason
        for v in violations
    ), violations


@pytest.mark.parametrize(
    "allowed",
    [
        "from studyloop.planning import PlanApplication, RevisePlan, PlanError, PlanDetail",
        "from studyloop.planning import PLAN_STATUSES, CHECKPOINT_PHASES, INTERVIEW, plans_dir",
        "from studyloop.planning.views import ActiveGuidance",
        "from studyloop.planning.intents import SetMilestone",
        "from studyloop.planning.errors import PlanNotReady",
        "from studyloop.planning.application import PlanApplication",
        "from studyloop.planning.exercises import list_sets",
        "from studyloop.planning.exercises.store import ExerciseSetNotFoundError",
    ],
)
def test_allowed_imports_are_not_flagged(tmp_path, allowed: str) -> None:
    copy = tmp_path / "plans.py"
    shutil.copy(SRC_ROOT / "studyloop" / "web" / "routes" / "plans.py", copy)
    copy.write_text(copy.read_text(encoding="utf-8") + "\n" + allowed + "\n", encoding="utf-8")
    assert _check_module(copy, module_name="studyloop.web.routes.plans") == []


def test_forbidden_name_list_covers_every_reexport() -> None:
    """The explicit list must name every callable/class the package re-exports
    from the four forbidden modules — a new store writer added to
    ``planning/__init__.py`` cannot slip past the guard unlisted."""
    package = importlib.import_module("studyloop.planning")
    reexported: set[str] = set()
    for name in package.__all__:
        obj = getattr(package, name)
        module = getattr(obj, "__module__", None)
        if not (inspect.isfunction(obj) or inspect.isclass(obj)) or module is None:
            continue
        if module in FORBIDDEN_MODULES:
            reexported.add(name)

    unlisted = reexported - FORBIDDEN_PACKAGE_NAMES - ALLOWED_PACKAGE_NAMES
    assert not unlisted, f"re-exported from a forbidden module but not listed: {sorted(unlisted)}"
    assert not (FORBIDDEN_PACKAGE_NAMES & ALLOWED_PACKAGE_NAMES)
    assert not (ALLOWED_MODULES and set(ALLOWED_MODULES) & set(FORBIDDEN_MODULES))
