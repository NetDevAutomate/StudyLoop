"""Conformance checks for optional modules: ``studyloop module check <path>``.

Interface stub (module-contract v1, lane C, wave 0 / C1). The shapes below are fixed so
the red tests in ``tests/test_module_check.py`` import real names and fail on behaviour;
``check_module`` raises ``NotImplementedError`` until C2 lands the engine. No logic lives
here yet.

Report contract, pinned by ``tests/fixtures/modules/`` (see its README for the per-rule
faults and the rule-overlap decisions they imply):

- ``CheckReport.ok`` is ``True`` exactly when ``findings`` is empty.
- Every ``Finding.rule_id`` is one of ``RULE_IDS`` (``MC001``..``MC016``, proposal §6).
- A module that breaks exactly one rule yields findings carrying exactly one distinct
  ``rule_id``; several findings may share it (e.g. two tasks each missing an ``id``).
- ``Finding.path`` is the module-root-relative path of the offending file, or ``""`` when
  the finding concerns the module as a whole (e.g. MC003, a missing required file names
  the file that is absent).
- ``Finding.message`` is one quotable sentence suitable for a PR comment.
- ``check_module`` never executes module content and never follows a symlink out of the
  module directory; it reads files only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

RULE_IDS: tuple[str, ...] = tuple(f"MC{n:03d}" for n in range(1, 17))
"""The sixteen conformance rule ids of proposal §6, in table order."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation: which rule, where, and a quotable sentence saying what."""

    rule_id: str
    message: str
    path: str


@dataclass(frozen=True, slots=True)
class CheckReport:
    """The outcome of checking one module directory."""

    ok: bool
    findings: list[Finding]


def check_module(path: Path) -> CheckReport:
    """Check the module at ``path`` against MC001-MC016 and report every violation.

    Wave 0 stub: the engine lands in C2.
    """
    raise NotImplementedError("module check engine is not implemented yet (lands in C2)")
