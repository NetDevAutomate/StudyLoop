"""Medication window checking for AuDHD-aware scheduling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def check_medication_window(medication_config: dict) -> dict | None:
    """Check current time against medication schedule.

    Args:
        medication_config: {dose_time: "08:00", onset_minutes: 30,
                           peak_hours: 4, duration_hours: 8}

    Returns {phase, recommendation, minutes_remaining} or None if not configured.
    """
    if not medication_config or "dose_time" not in medication_config:
        return None

    now = datetime.now(UTC)
    dose_h, dose_m = medication_config["dose_time"].split(":")
    dose_time = now.replace(hour=int(dose_h), minute=int(dose_m), second=0, microsecond=0)

    # If dose time is in the future, assume yesterday's dose
    if dose_time > now:
        dose_time -= timedelta(days=1)

    minutes_since_dose = (now - dose_time).total_seconds() / 60
    onset = medication_config.get("onset_minutes", 30)
    peak_hours = medication_config.get("peak_hours", 4)
    duration_hours = medication_config.get("duration_hours", 8)

    if minutes_since_dose < onset:
        return {
            "phase": "onset",
            "recommendation": "Meds ramping up. Light review or body doubling is a good fit.",
            "minutes_remaining": int(onset - minutes_since_dose),
        }
    elif minutes_since_dose < (peak_hours * 60):
        return {
            "phase": "peak",
            "recommendation": "Peak window. Best time for new material or hard problems.",
            "minutes_remaining": int(peak_hours * 60 - minutes_since_dose),
        }
    elif minutes_since_dose < (duration_hours * 60):
        return {
            "phase": "tapering",
            "recommendation": "Meds tapering. Switch to review or lighter material.",
            "minutes_remaining": int(duration_hours * 60 - minutes_since_dose),
        }
    else:
        return {
            "phase": "worn_off",
            "recommendation": "Meds have worn off. Review-only or body doubling recommended.",
            "minutes_remaining": 0,
        }
