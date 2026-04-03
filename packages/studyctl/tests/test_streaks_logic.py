"""Tests for energy streaks logic — functional core (no mocks, no DB).

Verifies the pure analyze_energy_streaks() function that computes
energy distribution, trend detection, and duration correlation
from session summary data.
"""

from __future__ import annotations

from studyctl.logic.streaks_logic import (
    EnergyStreakReport,
    SessionSummary,
    analyze_energy_streaks,
)


def _session(
    energy: str = "medium",
    duration_minutes: int = 30,
    days_ago: int = 0,
) -> SessionSummary:
    """Helper to create test sessions with minimal boilerplate."""
    return SessionSummary(
        energy_level=energy,
        duration_minutes=duration_minutes,
        days_ago=days_ago,
    )


# ─── Empty Data ───────────────────────────────────────────────────


class TestEmptyData:
    def test_no_sessions_returns_empty_report(self):
        result = analyze_energy_streaks([])
        assert result.distribution == {}
        assert result.trend == "stable"
        assert result.avg_duration_by_energy == {}
        assert result.correlation_note is None

    def test_single_session(self):
        result = analyze_energy_streaks([_session("high", 45)])
        assert result.distribution == {"high": 1}
        assert result.trend == "stable"
        assert result.avg_duration_by_energy == {"high": 45.0}


# ─── Distribution ─────────────────────────────────────────────────


class TestDistribution:
    def test_counts_each_energy_level(self):
        sessions = [
            _session("high"),
            _session("high"),
            _session("medium"),
            _session("low"),
            _session("low"),
            _session("low"),
        ]
        result = analyze_energy_streaks(sessions)
        assert result.distribution == {"high": 2, "medium": 1, "low": 3}

    def test_all_same_energy(self):
        sessions = [_session("medium") for _ in range(5)]
        result = analyze_energy_streaks(sessions)
        assert result.distribution == {"medium": 5}


# ─── Trend Detection ─────────────────────────────────────────────


class TestTrend:
    def test_improving_trend(self):
        """Recent sessions are higher energy than older ones."""
        sessions = [
            _session("low", days_ago=20),
            _session("low", days_ago=15),
            _session("medium", days_ago=10),
            _session("high", days_ago=5),
            _session("high", days_ago=1),
        ]
        result = analyze_energy_streaks(sessions)
        assert result.trend == "improving"

    def test_declining_trend(self):
        """Recent sessions are lower energy than older ones."""
        sessions = [
            _session("high", days_ago=20),
            _session("high", days_ago=15),
            _session("medium", days_ago=10),
            _session("low", days_ago=5),
            _session("low", days_ago=1),
        ]
        result = analyze_energy_streaks(sessions)
        assert result.trend == "declining"

    def test_stable_trend(self):
        """Energy levels are consistent."""
        sessions = [
            _session("medium", days_ago=20),
            _session("medium", days_ago=10),
            _session("medium", days_ago=1),
        ]
        result = analyze_energy_streaks(sessions)
        assert result.trend == "stable"

    def test_two_sessions_stable(self):
        """Too few sessions for a meaningful trend."""
        sessions = [
            _session("low", days_ago=5),
            _session("high", days_ago=1),
        ]
        result = analyze_energy_streaks(sessions)
        assert result.trend == "stable"


# ─── Duration Correlation ─────────────────────────────────────────


class TestDurationCorrelation:
    def test_average_duration_per_energy(self):
        sessions = [
            _session("high", duration_minutes=60),
            _session("high", duration_minutes=40),
            _session("low", duration_minutes=20),
            _session("low", duration_minutes=30),
        ]
        result = analyze_energy_streaks(sessions)
        assert result.avg_duration_by_energy["high"] == 50.0
        assert result.avg_duration_by_energy["low"] == 25.0

    def test_correlation_note_when_significant_difference(self):
        """When high-energy sessions are notably longer, note it."""
        sessions = [
            _session("high", duration_minutes=60),
            _session("high", duration_minutes=50),
            _session("low", duration_minutes=20),
            _session("low", duration_minutes=15),
        ]
        result = analyze_energy_streaks(sessions)
        assert result.correlation_note is not None
        assert "high" in result.correlation_note.lower()

    def test_no_correlation_note_when_similar(self):
        """When durations are similar across energy levels, no note."""
        sessions = [
            _session("high", duration_minutes=30),
            _session("low", duration_minutes=28),
        ]
        result = analyze_energy_streaks(sessions)
        assert result.correlation_note is None


# ─── Report Structure ─────────────────────────────────────────────


class TestReportStructure:
    def test_report_is_frozen(self):
        result = analyze_energy_streaks([_session()])
        assert isinstance(result, EnergyStreakReport)
