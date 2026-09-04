"""Due-card aggregation, independent of any transport.

Extracted from ``mcp/tools.py``'s ``get_due_cards`` because two callers now need
it and only one of them can afford the import: that module imports ``fastmcp``,
an optional extra, so a second-brain backend that reached for it would make the
whole feature depend on the MCP extra being installed. The MCP tool delegates
here rather than the other way round, so there is still one implementation of
"which cards are due".

Returns plain dictionaries. The MCP tool serialises them straight to JSON and the
Obsidian projection renders them as list items, so a dataclass would only add a
conversion step at both call sites.
"""

from __future__ import annotations

import dataclasses
from typing import Any

#: Cap used when a caller does not name one. Matches the MCP tool's own default
#: so the two surfaces cannot report different "due" sets for the same day.
DEFAULT_DUE_LIMIT = 20


def due_cards(course: str | None = None, limit: int = DEFAULT_DUE_LIMIT) -> list[dict[str, Any]]:
    """Cards due for spaced-repetition review, newest-due first within a course.

    ``course=None`` aggregates across every discovered course, which is what a
    "what should I review today?" surface wants: a learner does not think in
    courses when deciding whether to sit down.

    Each entry carries its ``course`` alongside the card fields, because once
    courses are aggregated the card alone no longer says where it came from.
    """
    from studyloop.services.review import get_due, list_course_summaries
    from studyloop.settings import resolve_study_dirs

    if course is not None:
        cards = [{"course": course, **dataclasses.asdict(card)} for card in get_due(course)]
    else:
        cards = []
        for summary in list_course_summaries(resolve_study_dirs()):
            name = summary["name"]
            cards.extend({"course": name, **dataclasses.asdict(c)} for c in get_due(name))

    return cards[: max(0, int(limit))]


__all__ = ["DEFAULT_DUE_LIMIT", "due_cards"]
