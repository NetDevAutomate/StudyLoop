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


@dataclass
class ScoringInput:
    """Pre-gathered data for a single backlog item."""

    item: BacklogItem
    frequency: int  # count of times this topic appears in parked_topics
    priority: int | None  # agent-assessed importance (1-5), None = unassessed


@dataclass
class TopicSuggestion:
    """A scored and ranked topic suggestion."""

    item: BacklogItem
    score: float  # 0.0 - 1.0, higher = study this next
    frequency: int
    priority: int  # effective priority (default 3 if unassessed)
    reasoning: str  # human-readable explanation


# Scoring weights: importance matters more than frequency
_FREQUENCY_WEIGHT = 0.4
_IMPORTANCE_WEIGHT = 0.6
_DEFAULT_PRIORITY = 3


def score_backlog_items(inputs: list[ScoringInput]) -> list[TopicSuggestion]:
    """Score and rank backlog items by frequency + agent-assessed importance.

    Pure logic — no I/O. Takes pre-gathered scoring inputs, returns
    sorted suggestions (highest score first).

    Score formula:
        effective_priority = priority or 3
        score = 0.4 * normalized_frequency + 0.6 * normalized_priority
    """
    if not inputs:
        return []

    max_frequency = max(inp.frequency for inp in inputs)
    if max_frequency == 0:
        max_frequency = 1  # avoid division by zero

    suggestions: list[TopicSuggestion] = []
    for inp in inputs:
        effective_priority = inp.priority if inp.priority is not None else _DEFAULT_PRIORITY
        norm_freq = inp.frequency / max_frequency
        norm_priority = effective_priority / 5.0

        score = (_FREQUENCY_WEIGHT * norm_freq) + (_IMPORTANCE_WEIGHT * norm_priority)

        # Build reasoning
        parts: list[str] = []
        if effective_priority >= 4:
            parts.append(f"high importance ({effective_priority}/5)")
        elif effective_priority <= 2:
            parts.append(f"low importance ({effective_priority}/5)")
        else:
            parts.append(f"moderate importance ({effective_priority}/5)")

        if inp.frequency >= 3:
            parts.append(f"frequently appears ({inp.frequency}x)")
        elif inp.frequency == 1:
            parts.append("appeared once")
        else:
            parts.append(f"appeared {inp.frequency}x")

        reasoning = ", ".join(parts)

        suggestions.append(
            TopicSuggestion(
                item=inp.item,
                score=round(score, 3),
                frequency=inp.frequency,
                priority=effective_priority,
                reasoning=reasoning,
            )
        )

    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions


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
