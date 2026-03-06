"""Calendar time-blocking via ICS file generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

# Spaced repetition review types with suggested durations (minutes)
REVIEW_DURATIONS: dict[str, int] = {
    "5-min recall quiz": 10,
    "10-min Socratic review": 15,
    "15-min deep review": 20,
    "Apply to new problem": 30,
    "Teach-back session": 30,
}


def _ics_dt(dt: datetime) -> str:
    """Format datetime as ICS DTSTART/DTEND value."""
    return dt.strftime("%Y%m%dT%H%M%S")


def _escape(text: str) -> str:
    """Escape text for ICS fields."""
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def generate_event(
    topic: str,
    review_type: str,
    start: datetime,
    duration_min: int | None = None,
) -> str:
    """Generate a single VEVENT block."""
    dur = duration_min or REVIEW_DURATIONS.get(review_type, 20)
    end = start + timedelta(minutes=dur)
    uid = f"{uuid4()}@studyctl"
    now = datetime.now(UTC)

    return (
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{_ics_dt(now)}\r\n"
        f"DTSTART:{_ics_dt(start)}\r\n"
        f"DTEND:{_ics_dt(end)}\r\n"
        f"SUMMARY:{_escape(f'Study: {topic} ({review_type})')}\r\n"
        f"DESCRIPTION:{_escape(f'Spaced repetition: {review_type} for {topic}')}\r\n"
        "STATUS:CONFIRMED\r\n"
        "BEGIN:VALARM\r\n"
        "TRIGGER:-PT5M\r\n"
        "ACTION:DISPLAY\r\n"
        f"DESCRIPTION:{_escape(f'Study time: {topic}')}\r\n"
        "END:VALARM\r\n"
        "END:VEVENT\r\n"
    )


def generate_ics(events: list[dict]) -> str:
    """Generate a complete .ics file from a list of event dicts.

    Each dict: {topic, review_type, start, duration_min?}
    """
    lines = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//studyctl//Socratic Study Mentor//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
    )
    for evt in events:
        lines += generate_event(
            topic=evt["topic"],
            review_type=evt["review_type"],
            start=evt["start"],
            duration_min=evt.get("duration_min"),
        )
    lines += "END:VCALENDAR\r\n"
    return lines


def schedule_reviews(
    due_items: list[dict],
    start_time: datetime | None = None,
    gap_minutes: int = 10,
) -> list[dict]:
    """Convert spaced repetition due items into scheduled events.

    Args:
        due_items: From history.spaced_repetition_due() — [{topic, review_type, ...}]
        start_time: When to start scheduling (default: next hour)
        gap_minutes: Gap between sessions

    Returns:
        List of event dicts ready for generate_ics()
    """
    if not start_time:
        now = datetime.now()
        start_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    events = []
    current = start_time
    for item in due_items:
        review_type = item.get("review_type", "15-min deep review")
        duration = REVIEW_DURATIONS.get(review_type, 20)
        events.append(
            {
                "topic": item["topic"],
                "review_type": review_type,
                "start": current,
                "duration_min": duration,
            }
        )
        current += timedelta(minutes=duration + gap_minutes)
    return events


def write_ics(
    events: list[dict],
    output_dir: Path | None = None,
) -> Path:
    """Write events to an .ics file.

    Args:
        events: Event dicts from schedule_reviews()
        output_dir: Directory to write to (default: ~/Downloads)

    Returns:
        Path to the written .ics file
    """
    output_dir = output_dir or Path.home() / "Downloads"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    path = output_dir / f"study-blocks-{timestamp}.ics"
    path.write_text(generate_ics(events))
    return path
