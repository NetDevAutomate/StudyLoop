"""Unit tests for tests/acceptance/actors/budget.py's BudgetGuard.

Outside tests/acceptance/ and unmarked, same rationale as
test_acceptance_turn_script.py -- this tests the guard's own bookkeeping,
not a live product session.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.actors.budget import BudgetGuard  # noqa: E402


class TestConstruction:
    def test_rejects_zero_max_turns(self) -> None:
        with pytest.raises(ValueError, match="max_turns"):
            BudgetGuard(max_turns=0)

    def test_rejects_negative_max_turns(self) -> None:
        with pytest.raises(ValueError, match="max_turns"):
            BudgetGuard(max_turns=-1)

    def test_rejects_negative_max_output_tokens(self) -> None:
        with pytest.raises(ValueError, match="max_output_tokens"):
            BudgetGuard(max_turns=1, max_output_tokens=-1)

    def test_none_max_output_tokens_is_allowed(self) -> None:
        guard = BudgetGuard(max_turns=1, max_output_tokens=None)
        assert guard.has_budget_for_next_turn()


class TestTurnCap:
    def test_has_budget_true_until_max_turns_reached(self) -> None:
        guard = BudgetGuard(max_turns=2)
        assert guard.has_budget_for_next_turn()
        guard.record_turn(output_tokens=None)
        assert guard.has_budget_for_next_turn()
        guard.record_turn(output_tokens=None)
        assert not guard.has_budget_for_next_turn()

    def test_turns_taken_tracks_record_calls(self) -> None:
        guard = BudgetGuard(max_turns=5)
        guard.record_turn(output_tokens=None)
        guard.record_turn(output_tokens=None)
        assert guard.turns_taken == 2


class TestOutputTokenCap:
    def test_has_budget_false_once_cumulative_tokens_reach_cap(self) -> None:
        guard = BudgetGuard(max_turns=100, max_output_tokens=100)
        guard.record_turn(output_tokens=60)
        assert guard.has_budget_for_next_turn()
        guard.record_turn(output_tokens=60)
        assert not guard.has_budget_for_next_turn()
        assert guard.output_tokens_spent == 120

    def test_unknown_output_tokens_never_counted_against_the_cap(self) -> None:
        """A backend that cannot observe usage (harness) reports None -- an
        unknown spend is never assumed to be zero, but it is also never
        treated as a cap violation on its own."""
        guard = BudgetGuard(max_turns=100, max_output_tokens=10)
        for _ in range(50):
            guard.record_turn(output_tokens=None)
        assert guard.has_budget_for_next_turn()
        assert guard.output_tokens_spent == 0

    def test_no_token_cap_means_only_turn_count_matters(self) -> None:
        guard = BudgetGuard(max_turns=3, max_output_tokens=None)
        guard.record_turn(output_tokens=10_000_000)
        assert guard.has_budget_for_next_turn()


class TestNeverRaises:
    def test_record_turn_never_raises_even_past_the_cap(self) -> None:
        guard = BudgetGuard(max_turns=1)
        guard.record_turn(output_tokens=None)
        # Calling record_turn again (a caller bug) still must not raise --
        # has_budget_for_next_turn() is the sole authority a caller checks.
        guard.record_turn(output_tokens=None)
        assert guard.turns_taken == 2
        assert not guard.has_budget_for_next_turn()
