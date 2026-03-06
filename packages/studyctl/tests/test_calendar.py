"""Tests for calendar time-blocking."""

from datetime import datetime, timedelta
from pathlib import Path

from studyctl.calendar import (
    REVIEW_DURATIONS,
    generate_event,
    generate_ics,
    schedule_reviews,
    write_ics,
)


class TestGenerateEvent:
    def test_basic_event(self):
        start = datetime(2026, 3, 7, 10, 0)
        result = generate_event("Python", "5-min recall quiz", start)
        assert "BEGIN:VEVENT" in result
        assert "END:VEVENT" in result
        assert "Study: Python (5-min recall quiz)" in result
        assert "DTSTART:20260307T100000" in result
        assert "DTEND:20260307T101000" in result  # 10 min duration

    def test_custom_duration(self):
        start = datetime(2026, 3, 7, 14, 0)
        result = generate_event("SQL", "custom review", start, duration_min=45)
        assert "DTEND:20260307T144500" in result

    def test_alarm_included(self):
        start = datetime(2026, 3, 7, 10, 0)
        result = generate_event("Python", "quiz", start)
        assert "BEGIN:VALARM" in result
        assert "TRIGGER:-PT5M" in result

    def test_escapes_special_chars(self):
        start = datetime(2026, 3, 7, 10, 0)
        result = generate_event("C++; Advanced", "review, deep", start)
        assert "C++\\; Advanced" in result


class TestGenerateIcs:
    def test_valid_ics_structure(self):
        events = [
            {
                "topic": "Python",
                "review_type": "5-min recall quiz",
                "start": datetime(2026, 3, 7, 10, 0),
            }
        ]
        result = generate_ics(events)
        assert result.startswith("BEGIN:VCALENDAR")
        assert result.endswith("END:VCALENDAR\r\n")
        assert "VERSION:2.0" in result
        assert "PRODID:-//studyctl" in result
        assert "BEGIN:VEVENT" in result

    def test_multiple_events(self):
        events = [
            {"topic": "Python", "review_type": "quiz", "start": datetime(2026, 3, 7, 10, 0)},
            {"topic": "SQL", "review_type": "review", "start": datetime(2026, 3, 7, 11, 0)},
        ]
        result = generate_ics(events)
        assert result.count("BEGIN:VEVENT") == 2

    def test_empty_events(self):
        result = generate_ics([])
        assert "BEGIN:VCALENDAR" in result
        assert "BEGIN:VEVENT" not in result


class TestScheduleReviews:
    def test_schedules_from_due_items(self):
        due = [
            {"topic": "Python", "review_type": "5-min recall quiz"},
            {"topic": "SQL", "review_type": "15-min deep review"},
        ]
        start = datetime(2026, 3, 7, 9, 0)
        events = schedule_reviews(due, start_time=start, gap_minutes=10)

        assert len(events) == 2
        assert events[0]["topic"] == "Python"
        assert events[0]["start"] == start
        assert events[0]["duration_min"] == 10  # from REVIEW_DURATIONS

        # Second event starts after first duration + gap
        expected_second = start + timedelta(minutes=10 + 10)
        assert events[1]["start"] == expected_second
        assert events[1]["duration_min"] == 20  # 15-min deep review = 20 min

    def test_empty_due_items(self):
        assert schedule_reviews([]) == []

    def test_default_start_is_next_hour(self):
        due = [{"topic": "Python", "review_type": "quiz"}]
        events = schedule_reviews(due)
        now = datetime.now()
        # Should be within the next 2 hours
        assert events[0]["start"] > now
        assert events[0]["start"] < now + timedelta(hours=2)
        assert events[0]["start"].minute == 0

    def test_unknown_review_type_gets_default_duration(self):
        due = [{"topic": "Python", "review_type": "unknown type"}]
        events = schedule_reviews(due, start_time=datetime(2026, 3, 7, 9, 0))
        assert events[0]["duration_min"] == 20  # default

    def test_custom_gap(self):
        due = [
            {"topic": "A", "review_type": "5-min recall quiz"},
            {"topic": "B", "review_type": "5-min recall quiz"},
        ]
        start = datetime(2026, 3, 7, 9, 0)
        events = schedule_reviews(due, start_time=start, gap_minutes=5)
        # First: 10 min duration + 5 min gap = 15 min later
        assert events[1]["start"] == start + timedelta(minutes=15)


class TestWriteIcs:
    def test_writes_file(self, tmp_path: Path):
        events = [
            {
                "topic": "Python",
                "review_type": "quiz",
                "start": datetime(2026, 3, 7, 10, 0),
            }
        ]
        path = write_ics(events, output_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".ics"
        content = path.read_text()
        assert "BEGIN:VCALENDAR" in content
        assert "Study: Python" in content

    def test_filename_contains_timestamp(self, tmp_path: Path):
        events = [{"topic": "X", "review_type": "Y", "start": datetime(2026, 1, 1, 10, 0)}]
        path = write_ics(events, output_dir=tmp_path)
        assert path.name.startswith("study-blocks-")
        assert path.name.endswith(".ics")

    def test_creates_output_dir(self, tmp_path: Path):
        out = tmp_path / "nested" / "dir"
        events = [{"topic": "X", "review_type": "Y", "start": datetime(2026, 1, 1, 10, 0)}]
        path = write_ics(events, output_dir=out)
        assert path.exists()


class TestReviewDurations:
    def test_all_review_types_have_durations(self):
        expected_types = [
            "5-min recall quiz",
            "10-min Socratic review",
            "15-min deep review",
            "Apply to new problem",
            "Teach-back session",
        ]
        for rt in expected_types:
            assert rt in REVIEW_DURATIONS
            assert REVIEW_DURATIONS[rt] > 0
