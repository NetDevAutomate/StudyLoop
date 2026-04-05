"""Post-session flashcard generation from session wins and insights.

Converts 'win' and 'insight' topic entries from a study session into
flashcard JSON files that SM-2 review picks up automatically on next load.

Rules enforced by design:
- NO framework imports (no click, no fastapi).
- Pure data transformation — reads session entries, writes one JSON file.
- Dedup via normalised SHA-256 hash prevents duplicate cards across sessions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from studyctl.session_state import TopicEntry

logger = logging.getLogger(__name__)


def _topic_to_question(topic: str) -> str:
    """Turn a topic name into a question-form flashcard front.

    Question form primes retrieval better than plain topic labels.
    """
    return f"What is {topic}?"


def _card_hash(front: str) -> str:
    """Normalised hash for dedup — casefold + strip before hashing."""
    normalised = front.strip().casefold()
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def _existing_card_hashes(flashcards_dir: Path) -> set[str]:
    """Collect all card hashes already present in the flashcards directory.

    Scans all *flashcards.json files and returns a set of front-text hashes
    for O(1) dedup checks. Returns empty set if directory doesn't exist.
    """
    hashes: set[str] = set()
    if not flashcards_dir.exists():
        return hashes

    for json_file in flashcards_dir.glob("*flashcards.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            for card in data.get("cards", []):
                front = card.get("front", "")
                if front:
                    hashes.add(_card_hash(front))
        except Exception:
            logger.warning("Skipping malformed flashcard file: %s", json_file)

    return hashes


def write_session_flashcards(
    content_base: Path,
    topic_slug: str,
    session_id: str,
    topic_entries: list[TopicEntry],
) -> int:
    """Generate flashcards from session wins/insights. Returns count written.

    Filters to entries with status 'win' or 'insight' that have substantive
    notes (>= 15 chars). Deduplicates against existing cards in the flashcards
    directory. Writes a dated JSON file if any new cards remain.

    Args:
        content_base: Root directory for course content (settings.content.base_path).
        topic_slug: Course slug — used to locate the flashcards subdirectory.
        session_id: Study session UUID — used in source attribution.
        topic_entries: Parsed entries from session-topics.md.

    Returns:
        Number of new flashcards written. 0 if nothing to write.
    """
    wins = [
        t for t in topic_entries if t.status in ("win", "insight") and t.note and len(t.note) >= 15
    ]
    if not wins:
        return 0

    flashcards_dir = content_base / topic_slug / "flashcards"
    existing_hashes = _existing_card_hashes(flashcards_dir)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    session_date = today  # derive date from now; session_id is the UUID

    candidates = []
    for entry in wins:
        front = _topic_to_question(entry.topic)
        h = _card_hash(front)
        if h in existing_hashes:
            continue  # dedup — skip if front already exists
        candidates.append(
            {
                "front": front,
                "back": entry.note,
                "source": f"session-{session_date}",
            }
        )
        existing_hashes.add(h)  # prevent intra-session duplication

    if not candidates:
        return 0

    flashcards_dir.mkdir(parents=True, exist_ok=True)

    filename = flashcards_dir / f"{today}-{topic_slug}-flashcards.json"
    # If the file already exists (same day, same slug), merge rather than overwrite
    existing_cards: list[dict] = []
    if filename.exists():
        try:
            existing_data = json.loads(filename.read_text(encoding="utf-8"))
            existing_cards = existing_data.get("cards", [])
        except Exception:
            logger.warning("Could not read existing flashcard file %s — will overwrite", filename)

    all_cards = existing_cards + candidates

    payload = {
        "title": f"Session: {topic_slug} — {today}",
        "cards": all_cards,
    }

    filename.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %d new flashcards to %s", len(candidates), filename)
    return len(candidates)
