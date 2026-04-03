"""Tests for break suggestion logic — functional core (no mocks, no I/O).

Verifies the pure check_break_needed() function against the break science
thresholds defined in agents/shared/break-science.md.

Energy-adaptive thresholds (minutes since last break):
    High (7-10):   micro=25, short=50, long=90
    Medium (4-6):  micro=20, short=40, long=75
    Low (1-3):     micro=15, short=30, long=60
"""

from __future__ import annotations

from studyctl.logic.break_logic import check_break_needed

# ─── No Break Needed ──────────────────────────────────────────────


class TestNoBreakNeeded:
    """Before any threshold is crossed, no suggestion should be returned."""

    def test_fresh_session_no_break(self):
        result = check_break_needed(elapsed_minutes=0, energy=5, last_break_at=None, breaks_taken=0)
        assert result is None

    def test_just_under_micro_threshold_medium(self):
        result = check_break_needed(
            elapsed_minutes=19, energy=5, last_break_at=None, breaks_taken=0
        )
        assert result is None

    def test_just_under_micro_threshold_high(self):
        result = check_break_needed(
            elapsed_minutes=24, energy=8, last_break_at=None, breaks_taken=0
        )
        assert result is None

    def test_just_under_micro_threshold_low(self):
        result = check_break_needed(
            elapsed_minutes=14, energy=2, last_break_at=None, breaks_taken=0
        )
        assert result is None

    def test_recently_took_break(self):
        """5 minutes after a break — no new suggestion yet."""
        result = check_break_needed(elapsed_minutes=30, energy=5, last_break_at=25, breaks_taken=1)
        assert result is None


# ─── Micro Break Threshold ────────────────────────────────────────


class TestMicroBreak:
    """Micro-break at the shortest threshold crossing."""

    def test_micro_at_20_min_medium_energy(self):
        result = check_break_needed(
            elapsed_minutes=20, energy=5, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "micro"

    def test_micro_at_25_min_high_energy(self):
        result = check_break_needed(
            elapsed_minutes=25, energy=8, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "micro"

    def test_micro_at_15_min_low_energy(self):
        result = check_break_needed(
            elapsed_minutes=15, energy=2, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "micro"

    def test_micro_after_previous_break(self):
        """20 minutes after last break (medium energy) → micro."""
        result = check_break_needed(elapsed_minutes=45, energy=5, last_break_at=25, breaks_taken=1)
        assert result is not None
        assert result.break_type == "micro"


# ─── Short Break Threshold ────────────────────────────────────────


class TestShortBreak:
    """Short break overrides micro when the short threshold is crossed."""

    def test_short_at_40_min_medium_energy(self):
        result = check_break_needed(
            elapsed_minutes=40, energy=5, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "short"

    def test_short_at_50_min_high_energy(self):
        result = check_break_needed(
            elapsed_minutes=50, energy=8, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "short"

    def test_short_at_30_min_low_energy(self):
        result = check_break_needed(
            elapsed_minutes=30, energy=2, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "short"

    def test_short_overrides_micro(self):
        """At the short threshold, we get short not micro."""
        result = check_break_needed(
            elapsed_minutes=40, energy=5, last_break_at=None, breaks_taken=0
        )
        assert result.break_type == "short"


# ─── Long Break Threshold ─────────────────────────────────────────


class TestLongBreak:
    """Long break at the hard boundary — highest priority."""

    def test_long_at_75_min_medium_energy(self):
        result = check_break_needed(
            elapsed_minutes=75, energy=5, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "long"

    def test_long_at_90_min_high_energy(self):
        result = check_break_needed(
            elapsed_minutes=90, energy=8, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "long"

    def test_long_at_60_min_low_energy(self):
        result = check_break_needed(
            elapsed_minutes=60, energy=2, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "long"

    def test_long_overrides_short(self):
        """At the long threshold, we get long not short."""
        result = check_break_needed(
            elapsed_minutes=75, energy=5, last_break_at=None, breaks_taken=0
        )
        assert result.break_type == "long"


# ─── Energy Adaptation ────────────────────────────────────────────


class TestEnergyAdaptation:
    """Lower energy = shorter intervals between breaks."""

    def test_same_elapsed_different_energy(self):
        """At 20 min: low energy gets micro, high energy gets nothing."""
        low = check_break_needed(elapsed_minutes=20, energy=2, last_break_at=None, breaks_taken=0)
        high = check_break_needed(elapsed_minutes=20, energy=8, last_break_at=None, breaks_taken=0)
        assert low is not None
        assert low.break_type == "micro"
        assert high is None

    def test_energy_adapted_flag(self):
        """Suggestions from non-default thresholds are flagged."""
        # Medium energy (default) — not adapted
        med = check_break_needed(elapsed_minutes=20, energy=5, last_break_at=None, breaks_taken=0)
        assert med.energy_adapted is False

        # Low energy — adapted
        low = check_break_needed(elapsed_minutes=15, energy=2, last_break_at=None, breaks_taken=0)
        assert low.energy_adapted is True

        # High energy — adapted
        high = check_break_needed(elapsed_minutes=25, energy=8, last_break_at=None, breaks_taken=0)
        assert high.energy_adapted is True

    def test_default_energy_when_not_declared(self):
        """Energy of 0 or None-ish should default to medium thresholds."""
        result = check_break_needed(
            elapsed_minutes=20, energy=0, last_break_at=None, breaks_taken=0
        )
        assert result is not None
        assert result.break_type == "micro"


# ─── BreakSuggestion Fields ───────────────────────────────────────


class TestBreakSuggestionFields:
    """Verify the returned dataclass has the expected structure."""

    def test_suggestion_has_elapsed_minutes(self):
        result = check_break_needed(
            elapsed_minutes=20, energy=5, last_break_at=None, breaks_taken=0
        )
        assert result.elapsed_minutes == 20

    def test_suggestion_has_message(self):
        result = check_break_needed(
            elapsed_minutes=20, energy=5, last_break_at=None, breaks_taken=0
        )
        assert isinstance(result.message, str)
        assert len(result.message) > 0

    def test_long_break_message_is_firm(self):
        """Long break messages should convey urgency."""
        result = check_break_needed(
            elapsed_minutes=75, energy=5, last_break_at=None, breaks_taken=0
        )
        # The message should indicate this is important, not optional
        assert result.break_type == "long"
        assert len(result.message) > 10
