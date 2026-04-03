"""Backlog logic — pure functional core, no I/O.

Decides how to format, summarise, and persist study backlog items.
The imperative shells (_topics.py, _study.py) handle all side effects.

See docs/mentoring/functional-core-imperative-shell.md for the pattern.
See docs/architecture/study-backlog-phase1.md for the full design.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from studyctl.session_state import TopicEntry


@dataclass
class BacklogItem:
    """A single backlog entry — pre-fetched from DB."""

    id: int
    question: str
    topic_tag: str | None
    tech_area: str | None
    source: str  # parked | struggled | manual
    context: str | None
    parked_at: str
    session_topic: str | None  # from study_sessions.topic via join


@dataclass
class FormattedBacklog:
    """Result of format_backlog_list() — ready for display."""

    items: list[BacklogItem] = field(default_factory=list)
    total: int = 0
    by_tech: dict[str, list[BacklogItem]] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)


@dataclass
class PersistAction:
    """A struggled topic to persist to parked_topics."""

    question: str
    topic_tag: str | None
    context: str | None
    study_session_id: str
    source: str = "struggled"


def format_backlog_list(
    items: list[BacklogItem],
    *,
    tech_filter: str | None = None,
    source_filter: str | None = None,
) -> FormattedBacklog:
    """Filter and group backlog items for display. Pure logic."""
    filtered = items
    if tech_filter:
        filtered = [i for i in filtered if i.tech_area == tech_filter]
    if source_filter:
        filtered = [i for i in filtered if i.source == source_filter]

    by_tech: dict[str, list[BacklogItem]] = defaultdict(list)
    by_source: dict[str, int] = defaultdict(int)
    for item in filtered:
        tech_key = item.tech_area or "Uncategorized"
        by_tech[tech_key].append(item)
        by_source[item.source] += 1

    return FormattedBacklog(
        items=filtered,
        total=len(filtered),
        by_tech=dict(by_tech),
        by_source=dict(by_source),
    )


def build_backlog_summary(
    pending_items: list[BacklogItem],
    current_topic: str,
) -> str | None:
    """Build markdown snippet for agent persona injection.

    Returns None if no pending items. Prioritises items matching
    the current topic's tech area (simple substring match).
    """
    if not pending_items:
        return None

    # Sort: items matching current topic first, then the rest
    topic_lower = current_topic.lower()

    def relevance(item: BacklogItem) -> int:
        if item.tech_area and item.tech_area.lower() in topic_lower:
            return 0
        if item.topic_tag and item.topic_tag.lower() in topic_lower:
            return 0
        return 1

    sorted_items = sorted(pending_items, key=relevance)

    lines = [f"You have {len(sorted_items)} outstanding study topics:\n"]
    for item in sorted_items:
        tech = f" [{item.tech_area}]" if item.tech_area else ""
        source = f" ({item.source})" if item.source != "parked" else ""
        lines.append(f"- {item.question}{tech}{source}")

    return "\n".join(lines)


def plan_auto_persist(
    topic_entries: list[TopicEntry],
    existing_questions: set[str],
    study_session_id: str,
) -> list[PersistAction]:
    """Decide which struggled topics to persist to parked_topics.

    Filters for status='struggling', deduplicates against
    existing_questions (already in parked_topics for this session).
    """
    actions: list[PersistAction] = []
    for entry in topic_entries:
        if entry.status != "struggling":
            continue
        if entry.topic in existing_questions:
            continue
        actions.append(
            PersistAction(
                question=entry.topic,
                topic_tag=entry.topic,
                context=entry.note or None,
                study_session_id=study_session_id,
            )
        )
    return actions
