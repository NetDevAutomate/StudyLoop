"""Energy streaks logic — functional core for session energy analysis.

Pure functions that analyze energy patterns, trends, and duration
correlations from study session data. No I/O, no side effects.

The imperative shell (cli/_review.py) gathers session data from
history.py and passes it here for analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

# ─── Data Structures ──────────────────────────────────────────────

# Numeric mapping for trend calculation (low=1, medium=2, high=3)
_ENERGY_VALUES = {"low": 1, "medium": 2, "high": 3}

# Minimum difference in average duration (minutes) to generate
# a correlation note. Below this, differences are noise.
_CORRELATION_THRESHOLD_MINUTES = 10


@dataclass(frozen=True)
class SessionSummary:
    """Minimal session data needed for energy analysis.

    The imperative shell maps DB rows to this before calling
    analyze_energy_streaks(). Keeps the core DB-free.
    """

    energy_level: str  # "low" | "medium" | "high"
    duration_minutes: int
    days_ago: int  # 0 = today, 1 = yesterday, etc.


@dataclass(frozen=True)
class EnergyStreakReport:
    """Result of energy streak analysis.

    Attributes:
        distribution: count of sessions per energy level
        trend: "improving", "stable", or "declining"
        avg_duration_by_energy: average session minutes per energy level
        correlation_note: human-readable insight, or None if no pattern
    """

    distribution: dict[str, int]
    trend: str
    avg_duration_by_energy: dict[str, float]
    correlation_note: str | None


# ─── Core Logic ───────────────────────────────────────────────────


def analyze_energy_streaks(
    sessions: list[SessionSummary],
    days: int = 30,
) -> EnergyStreakReport:
    """Analyze energy patterns across study sessions.

    Pure function — takes session summaries, returns a report.

    Args:
        sessions: session data (energy, duration, recency)
        days: window to consider (filters by days_ago)
    """
    # Filter to the requested window
    window = [s for s in sessions if s.days_ago <= days]

    if not window:
        return EnergyStreakReport(
            distribution={},
            trend="stable",
            avg_duration_by_energy={},
            correlation_note=None,
        )

    distribution = _compute_distribution(window)
    avg_durations = _compute_avg_durations(window)
    trend = _detect_trend(window)
    correlation = _build_correlation_note(avg_durations)

    return EnergyStreakReport(
        distribution=distribution,
        trend=trend,
        avg_duration_by_energy=avg_durations,
        correlation_note=correlation,
    )


# ─── Internal Helpers ─────────────────────────────────────────────


def _compute_distribution(sessions: list[SessionSummary]) -> dict[str, int]:
    """Count sessions per energy level."""
    counts: dict[str, int] = {}
    for s in sessions:
        counts[s.energy_level] = counts.get(s.energy_level, 0) + 1
    return counts


def _compute_avg_durations(
    sessions: list[SessionSummary],
) -> dict[str, float]:
    """Average session duration per energy level."""
    totals: dict[str, list[int]] = {}
    for s in sessions:
        totals.setdefault(s.energy_level, []).append(s.duration_minutes)
    return {level: round(sum(durations) / len(durations), 1) for level, durations in totals.items()}


def _detect_trend(sessions: list[SessionSummary]) -> str:
    """Detect energy trend from session chronology.

    Compares the average energy of the older half vs the newer half.
    Needs at least 3 sessions for a meaningful comparison.

    Sessions are sorted by days_ago descending (oldest first), then
    split into two halves. If the newer half's average energy is
    meaningfully higher, trend is "improving"; lower = "declining".
    """
    if len(sessions) < 3:
        return "stable"

    # Sort oldest first (highest days_ago first)
    ordered = sorted(sessions, key=lambda s: s.days_ago, reverse=True)
    mid = len(ordered) // 2
    older_half = ordered[:mid]
    newer_half = ordered[mid:]

    def avg_energy(group: list[SessionSummary]) -> float:
        values = [_ENERGY_VALUES.get(s.energy_level, 2) for s in group]
        return sum(values) / len(values)

    older_avg = avg_energy(older_half)
    newer_avg = avg_energy(newer_half)
    diff = newer_avg - older_avg

    # Threshold: 0.5 on a 1-3 scale is a meaningful shift
    if diff >= 0.5:
        return "improving"
    if diff <= -0.5:
        return "declining"
    return "stable"


def _build_correlation_note(
    avg_durations: dict[str, float],
) -> str | None:
    """Build a human-readable correlation note if energy affects duration.

    Only generates a note when the difference between the longest
    and shortest average durations exceeds the threshold.
    """
    if len(avg_durations) < 2:
        return None

    longest_level = max(avg_durations, key=avg_durations.get)  # type: ignore[arg-type]
    shortest_level = min(avg_durations, key=avg_durations.get)  # type: ignore[arg-type]

    diff = avg_durations[longest_level] - avg_durations[shortest_level]
    if diff < _CORRELATION_THRESHOLD_MINUTES:
        return None

    return (
        f"{longest_level.capitalize()}-energy sessions average "
        f"{avg_durations[longest_level]:.0f}min vs "
        f"{avg_durations[shortest_level]:.0f}min at {shortest_level}"
    )
