"""Tests for the doctor exit-code contract (W35).

docs/cli-reference.md's exit-code-1 row implied `--fix` always resolves a
doctor failure. It doesn't for checks with ``fix_auto=False`` -- e.g.
``check_review_db``'s corrupt-DB fail (doctor/database.py) -- so the doc must
say so, not gloss over it.
"""

from __future__ import annotations

from pathlib import Path

from studyloop.cli._doctor import _compute_exit_code
from studyloop.doctor.models import CheckResult

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_REFERENCE = REPO_ROOT / "docs" / "cli-reference.md"


def test_unresolvable_fail_still_exits_1() -> None:
    """A `fail` outside the `core` category with fix_auto=False -- exactly
    the case `--fix` cannot resolve -- still returns exit code 1, not a
    distinct "unfixable" code. The doc's exit-1 row must reflect that."""
    results = [
        CheckResult(
            category="database",
            name="review_db_integrity",
            status="fail",
            message="review.db failed a PRAGMA integrity_check",
            fix_hint="Restore review.db from a backup",
            fix_auto=False,
        )
    ]

    assert _compute_exit_code(results) == 1


def test_exit_code_1_row_does_not_claim_fix_always_resolves() -> None:
    """The doc's `studyloop doctor` exit-1 row must name the auto-fixable/
    manual split, not imply `--fix` clears every failure it reports."""
    text = CLI_REFERENCE.read_text()
    doctor_rows = [
        line for line in text.splitlines() if line.startswith("| `1` | Warnings or failures")
    ]
    assert len(doctor_rows) == 1, "expected exactly one doctor exit-1 row"
    row = doctor_rows[0]
    assert "auto-fixable" in row
    assert "can be fixed — run" not in row
