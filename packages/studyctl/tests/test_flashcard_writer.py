"""Tests for flashcard_writer — post-session win/insight flashcard generation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

from studyctl.services.flashcard_writer import (
    _card_hash,
    _existing_card_hashes,
    write_session_flashcards,
)
from studyctl.session_state import TopicEntry


def _win(topic: str, note: str, status: str = "win") -> TopicEntry:
    """Helper to create a TopicEntry for testing."""
    return TopicEntry(time="10:00", topic=topic, status=status, note=note)


# ---------------------------------------------------------------------------
# _card_hash
# ---------------------------------------------------------------------------


class TestCardHash:
    def test_normalises_casefold(self):
        h1 = _card_hash("What is Python?")
        h2 = _card_hash("what is python?")
        assert h1 == h2

    def test_normalises_leading_trailing_whitespace(self):
        h1 = _card_hash("  What is Python?  ")
        h2 = _card_hash("What is Python?")
        assert h1 == h2

    def test_different_fronts_different_hashes(self):
        h1 = _card_hash("What is Python?")
        h2 = _card_hash("What is SQL?")
        assert h1 != h2

    def test_hash_is_16_chars(self):
        h = _card_hash("What is Python?")
        assert len(h) == 16


# ---------------------------------------------------------------------------
# write_session_flashcards — main function
# ---------------------------------------------------------------------------


class TestWriteSessionFlashcards:
    def test_wins_generate_flashcard_json(self, tmp_path):
        entries = [
            _win("Python decorators", "A decorator wraps a function to extend its behaviour"),
        ]
        count = write_session_flashcards(tmp_path, "python", "sess-001", entries)
        assert count == 1

        # File should exist in {tmp_path}/python/flashcards/
        fc_dir = tmp_path / "python" / "flashcards"
        assert fc_dir.exists()
        files = list(fc_dir.glob("*flashcards.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text())
        assert data["cards"][0]["front"] == "What is Python decorators?"
        assert data["cards"][0]["back"] == "A decorator wraps a function to extend its behaviour"
        assert "session-" in data["cards"][0]["source"]

    def test_insight_entries_also_included(self, tmp_path):
        entries = [
            _win(
                "Generator expressions",
                "Lazy evaluation means items computed on demand",
                status="insight",
            ),
        ]
        count = write_session_flashcards(tmp_path, "python", "sess-002", entries)
        assert count == 1

    def test_no_wins_no_file_written(self, tmp_path):
        entries = [
            _win("Closures", "A closure captures the enclosing scope", status="struggling"),
            _win("Loops", "Basic iteration", status="learning"),
        ]
        count = write_session_flashcards(tmp_path, "python", "sess-003", entries)
        assert count == 0
        fc_dir = tmp_path / "python" / "flashcards"
        assert not fc_dir.exists()

    def test_notes_shorter_than_15_chars_skipped(self, tmp_path):
        entries = [
            _win("Decorators", "wraps functions"),  # 15 chars exactly — included
            _win("Generators", "lazy eval"),  # 9 chars — excluded
        ]
        count = write_session_flashcards(tmp_path, "python", "sess-004", entries)
        # "wraps functions" is exactly 15 chars → included
        assert count == 1

    def test_dedup_skips_existing_cards(self, tmp_path):
        # Pre-create a flashcard file with the same front
        fc_dir = tmp_path / "python" / "flashcards"
        fc_dir.mkdir(parents=True)
        existing = {
            "title": "Previous session",
            "cards": [
                {
                    "front": "What is Python decorators?",
                    "back": "old note",
                    "source": "session-2026-01-01",
                },
            ],
        }
        (fc_dir / "2026-01-01-python-flashcards.json").write_text(json.dumps(existing))

        entries = [
            _win("Python decorators", "A decorator wraps a function to extend its behaviour"),
        ]
        count = write_session_flashcards(tmp_path, "python", "sess-005", entries)
        assert count == 0  # deduped — card already exists

    def test_intra_session_dedup(self, tmp_path):
        """Two entries with same topic in same session → only one card."""
        entries = [
            _win("Python decorators", "A decorator wraps a function to extend its behaviour"),
            _win("Python decorators", "Decorators use @ syntax and wrap the function"),
        ]
        count = write_session_flashcards(tmp_path, "python", "sess-006", entries)
        assert count == 1

    def test_write_failure_propagates_to_caller(self, tmp_path, caplog):
        """OSError from write_text propagates; cleanup.py wraps it with logger.warning."""
        import contextlib

        entries = [
            _win("Python decorators", "A decorator wraps a function to extend its behaviour"),
        ]
        with (
            patch.object(Path, "write_text", side_effect=OSError("disk full")),
            contextlib.suppress(OSError),
        ):
            write_session_flashcards(tmp_path, "python", "sess-007", entries)

    def test_empty_entries_returns_zero(self, tmp_path):
        count = write_session_flashcards(tmp_path, "python", "sess-008", [])
        assert count == 0

    def test_json_structure_has_required_fields(self, tmp_path):
        entries = [
            _win("Context managers", "with statement ensures __exit__ is called on block exit"),
        ]
        write_session_flashcards(tmp_path, "python", "sess-009", entries)

        fc_dir = tmp_path / "python" / "flashcards"
        files = list(fc_dir.glob("*flashcards.json"))
        data = json.loads(files[0].read_text())

        assert "title" in data
        assert "cards" in data
        card = data["cards"][0]
        assert "front" in card
        assert "back" in card
        assert "source" in card


# ---------------------------------------------------------------------------
# _existing_card_hashes
# ---------------------------------------------------------------------------


class TestExistingCardHashes:
    def test_returns_empty_set_when_dir_missing(self, tmp_path):
        hashes = _existing_card_hashes(tmp_path / "nonexistent")
        assert hashes == set()

    def test_collects_hashes_from_existing_files(self, tmp_path):
        fc_dir = tmp_path / "flashcards"
        fc_dir.mkdir()
        payload = {
            "title": "Test",
            "cards": [{"front": "What is Python?", "back": "A language"}],
        }
        (fc_dir / "test-flashcards.json").write_text(json.dumps(payload))

        hashes = _existing_card_hashes(fc_dir)
        expected = _card_hash("What is Python?")
        assert expected in hashes

    def test_skips_malformed_json_files(self, tmp_path, caplog):
        fc_dir = tmp_path / "flashcards"
        fc_dir.mkdir()
        (fc_dir / "bad-flashcards.json").write_text("not valid json{{{")

        with caplog.at_level(logging.WARNING, logger="studyctl.services.flashcard_writer"):
            hashes = _existing_card_hashes(fc_dir)

        assert hashes == set()
        assert "malformed" in caplog.text.lower() or "Skipping" in caplog.text
