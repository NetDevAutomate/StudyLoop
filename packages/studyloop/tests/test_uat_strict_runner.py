"""Unit tests for tests/acceptance/uat/strict_runner.py -- UNGATED (D-19/D-26).

Mechanism only: the strict sign-off semantics (council D-13), never a live
run, so this runs under the default ``just test`` gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.uat.strict_runner import CellOutcome, evaluate_signoff  # noqa: E402


class TestZeroSelectedFails:
    def test_empty_results_fails_even_with_no_required_cells(self) -> None:
        result = evaluate_signoff(required_cells=[], results={})
        assert result.passed is False
        assert any("zero cells selected" in reason for reason in result.reasons)


class TestSkippedRequiredCellFails:
    def test_a_skipped_required_cell_fails_the_whole_signoff(self) -> None:
        result = evaluate_signoff(
            required_cells=["session_lifecycle", "wind_down_resume"],
            results={
                "session_lifecycle": CellOutcome.PASSED,
                "wind_down_resume": CellOutcome.SKIPPED,
            },
        )
        assert result.passed is False
        assert any(
            "wind_down_resume" in reason and "skipped" in reason for reason in result.reasons
        )

    def test_a_required_cell_missing_entirely_fails_like_a_skip(self) -> None:
        result = evaluate_signoff(
            required_cells=["session_lifecycle", "embeddings_check"],
            results={"session_lifecycle": CellOutcome.PASSED},
        )
        assert result.passed is False
        assert any("embeddings_check" in reason for reason in result.reasons)

    def test_a_failed_required_cell_also_fails(self) -> None:
        result = evaluate_signoff(
            required_cells=["session_lifecycle"],
            results={"session_lifecycle": CellOutcome.FAILED},
        )
        assert result.passed is False


class TestAllRequiredCellsPassing:
    def test_every_required_cell_passing_is_a_pass(self) -> None:
        result = evaluate_signoff(
            required_cells=["session_lifecycle", "wind_down_resume"],
            results={
                "session_lifecycle": CellOutcome.PASSED,
                "wind_down_resume": CellOutcome.PASSED,
            },
        )
        assert result.passed is True
        assert result.reasons == ()

    def test_an_extra_non_required_cell_present_does_not_affect_the_verdict(self) -> None:
        result = evaluate_signoff(
            required_cells=["session_lifecycle"],
            results={
                "session_lifecycle": CellOutcome.PASSED,
                "optional_fault_journey": CellOutcome.SKIPPED,
            },
        )
        assert result.passed is True
