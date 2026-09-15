"""Strict sign-off semantics (council D-13): a sign-off can never pass
through skips.

The deliverable 4 contract: "which journeys must pass + the rubric floor +
the no-skipped-required-cells rule, written as the checkable contract the
release process references." This module is the checkable part -- a pure
function over an already-collected set of per-cell outcomes, with no
opinion on HOW those outcomes were produced (pytest, a CI job, a manual
run log all produce the same shape).

Two hard failure rules, both from council D-13, apply BEFORE anything about
a rubric floor is even considered:

1. Zero cells selected -- nothing ran, so nothing was proven -- is a FAIL,
   never treated as vacuously passing.
2. Any REQUIRED cell whose outcome is ``"skipped"`` is a FAIL, by name --
   "the STRICT sign-off runner FAILS on skipped required cells ... a
   sign-off can never pass through skips."

A required cell that is present and ``"failed"`` is, unsurprisingly, also a
FAIL -- the strictness this module adds on top of an ordinary pass/fail
gate is specifically about skips and about the zero-selected case, not a
relaxation of the ordinary "failed means failed" rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class CellOutcome(StrEnum):
    """The three outcomes one sign-off cell (a journey, a validator) can have."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class SignOffResult:
    """The strict runner's verdict, with every reason it failed (if any)."""

    passed: bool
    reasons: tuple[str, ...]


def evaluate_signoff(
    *,
    required_cells: Sequence[str],
    results: Mapping[str, CellOutcome],
) -> SignOffResult:
    """Apply the strict sign-off rule (council D-13) to a collected result set.

    ``required_cells`` names every cell that MUST have a recorded, passing
    outcome. ``results`` maps a cell name to whatever outcome it actually
    got; a required cell absent from ``results`` entirely is treated the
    same as an explicit ``SKIPPED`` -- both mean "this required cell never
    ran to completion."
    """
    reasons: list[str] = []

    if not results:
        reasons.append("zero cells selected: nothing ran, so nothing was proven")

    for cell in required_cells:
        outcome = results.get(cell)
        if outcome is None:
            reasons.append(f"required cell {cell!r} has no recorded result (never ran)")
        elif outcome is CellOutcome.SKIPPED:
            reasons.append(
                f"required cell {cell!r} was skipped: a sign-off cannot pass through skips"
            )
        elif outcome is CellOutcome.FAILED:
            reasons.append(f"required cell {cell!r} failed")

    return SignOffResult(passed=not reasons, reasons=tuple(reasons))


__all__ = ["CellOutcome", "SignOffResult", "evaluate_signoff"]
