"""Break suggestion logic — functional core for the Active Break Protocol.

Pure functions that determine when to suggest breaks based on elapsed time,
energy level, and break history. No I/O, no side effects.

Thresholds from agents/shared/break-science.md:
    High (7-10):   micro=25, short=50, long=90
    Medium (4-6):  micro=20, short=40, long=75
    Low (1-3):     micro=15, short=30, long=60
"""

from __future__ import annotations

from dataclasses import dataclass

# ─── Data Structures ──────────────────────────────────────────────


@dataclass(frozen=True)
class BreakThresholds:
    """Minutes-since-last-break thresholds for each break tier."""

    micro: int
    short: int
    long: int


@dataclass(frozen=True)
class BreakSuggestion:
    """A break suggestion returned by check_break_needed().

    Attributes:
        break_type: "micro", "short", or "long"
        elapsed_minutes: total session minutes at time of suggestion
        message: human-readable nudge (tone varies by break type)
        energy_adapted: True if thresholds differ from medium defaults
    """

    break_type: str
    elapsed_minutes: int
    message: str
    energy_adapted: bool


# ─── Threshold Lookup ─────────────────────────────────────────────

# Medium is the default — used when energy is 0 or not declared.
THRESHOLDS = {
    "low": BreakThresholds(micro=15, short=30, long=60),
    "medium": BreakThresholds(micro=20, short=40, long=75),
    "high": BreakThresholds(micro=25, short=50, long=90),
}


def energy_band(energy: int) -> str:
    """Map a 1-10 energy score to a threshold band.

    The mapping follows break-science.md:
        7-10 → high (longer intervals, brain is fresh)
        4-6  → medium (default)
        1-3  → low (shorter intervals, executive function depletes faster)
        0    → medium (no energy declared, use safe default)
    """
    if energy >= 7:
        return "high"
    if energy >= 4:
        return "medium"
    if energy >= 1:
        return "low"
    # 0 or negative = not declared → default to medium
    return "medium"


def get_thresholds(energy: int) -> tuple[BreakThresholds, bool]:
    """Get break thresholds for an energy level.

    Returns:
        (thresholds, energy_adapted) — adapted is True when thresholds
        differ from the medium defaults.
    """
    band = energy_band(energy)
    return THRESHOLDS[band], band != "medium"


# ─── Messages ─────────────────────────────────────────────────────

_MESSAGES = {
    "micro": (
        "You've been going for {minutes} minutes — "
        "finish your current thought, then stand up and stretch. "
        "Back in 2."
    ),
    "short": (
        "Good time for a proper break — {minutes} minutes in. "
        "Walk to another room, refill your water. "
        "We'll pick up right where we left off."
    ),
    "long": (
        "You've been at this for {minutes} minutes. "
        "Diminishing returns are real past this point. "
        "Take 15-20 minutes — walk outside if you can."
    ),
}


# ─── Core Logic ───────────────────────────────────────────────────


def check_break_needed(
    elapsed_minutes: int,
    energy: int,
    last_break_at: int | None,
    breaks_taken: int,
) -> BreakSuggestion | None:
    """Determine whether a break should be suggested right now.

    Pure function — takes session state, returns a suggestion or None.

    The check uses minutes_since_last_break (not total elapsed) so that
    taking a break resets the clock. Break types escalate: if you skip
    a micro-break and keep going, you'll eventually hit the short
    threshold, then long. This escalation is intentional — it's the
    cost of skipping breaks.

    Priority is long > short > micro: if multiple thresholds are
    crossed, the highest-priority (longest interval) wins.

    Args:
        elapsed_minutes: total minutes since session started
        energy: energy level declared at session start (1-10, 0=default)
        last_break_at: minute mark when the last break was taken (None if none)
        breaks_taken: total breaks taken this session (for future use)
    """
    thresholds, adapted = get_thresholds(energy)
    minutes_since_break = elapsed_minutes - (last_break_at or 0)

    # Check from longest interval to shortest — highest priority wins
    if minutes_since_break >= thresholds.long:
        break_type = "long"
    elif minutes_since_break >= thresholds.short:
        break_type = "short"
    elif minutes_since_break >= thresholds.micro:
        break_type = "micro"
    else:
        return None

    message = _MESSAGES[break_type].format(minutes=elapsed_minutes)

    return BreakSuggestion(
        break_type=break_type,
        elapsed_minutes=elapsed_minutes,
        message=message,
        energy_adapted=adapted,
    )
