"""Study briefing logic — pure functional core, no I/O.

Assembles a structured study briefing from review stats and content inventory,
then formats it as markdown for injection into the agent persona.

The imperative shell (_study.py) gathers raw data and populates BriefingData.
This module only does pure transformation: data -> formatted string.

See docs/plans/2026-04-05-feat-study-briefing-cohesive-loop-plan.md for design.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewContext:
    """Review statistics for a course gathered at session start."""

    due_count: int = 0
    struggling_count: int = 0  # derived from get_due(), NOT get_wrong()
    flashcard_count: int = 0
    quiz_count: int = 0
    mastered_count: int = 0
    total_reviews: int = 0


@dataclass
class ContentContext:
    """Content inventory for a topic gathered at session start."""

    chapter_count: int = 0
    obsidian_path: str = ""
    content_base: str = ""


@dataclass
class BriefingData:
    """Assembled briefing data for a study session.

    Populated by the imperative shell (_study.py gatherers).
    Consumed by format_study_briefing() to produce markdown.
    """

    topic_name: str
    review: ReviewContext | None = None
    content: ContentContext | None = None
    backlog_items: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    assembly_warnings: list[str] = field(default_factory=list)

    @property
    def is_degraded(self) -> bool:
        """True if any data gatherer failed — partial data only."""
        return bool(self.assembly_warnings)


def format_study_briefing(data: BriefingData) -> str:
    """Pure function: BriefingData -> markdown string for persona injection.

    Returns empty string if topic_name is empty. Each section is only
    included when the relevant context is present — missing data sections
    show a graceful degradation message instead of being omitted entirely.
    """
    if not data.topic_name:
        return ""

    lines: list[str] = [
        f"## Study Briefing: {data.topic_name}",
        "",
    ]

    # --- Review section ---
    if data.review is not None:
        rv = data.review
        lines.append("### Review Status")
        lines.append(f"- Due for review: **{rv.due_count}** cards")
        if rv.struggling_count:
            lines.append(f"- Struggling: **{rv.struggling_count}** cards (prioritise these)")
        lines.append(f"- Mastered (interval > 30d): {rv.mastered_count}")
        lines.append(f"- Total reviews so far: {rv.total_reviews}")
        if rv.flashcard_count:
            lines.append(f"- Flashcards loaded: {rv.flashcard_count}")
        if rv.quiz_count:
            lines.append(f"- Quiz questions loaded: {rv.quiz_count}")
        lines.append("")
    else:
        lines.append("### Review Status")
        lines.append("- Review data unavailable (DB may be missing or empty)")
        lines.append("")

    # --- Content section ---
    if data.content is not None:
        ct = data.content
        lines.append("### Content Inventory")
        if ct.chapter_count:
            lines.append(f"- Chapters: {ct.chapter_count}")
        else:
            lines.append("- No chapters yet — run `studyctl content split` to add material")
        if ct.obsidian_path:
            lines.append(f"- Obsidian notes: {ct.obsidian_path}")
        lines.append("")
    else:
        lines.append("### Content Inventory")
        lines.append("- No content directory found")
        lines.append("  Hint: `studyctl content split <pdf> --course <slug>` to add material")
        lines.append("")

    # --- Content gaps ---
    if data.gaps:
        lines.append("### Content Gaps")
        for gap in data.gaps:
            lines.append(f"- {gap}")
        lines.append("")

    # --- Backlog items ---
    if data.backlog_items:
        lines.append("### Study Backlog")
        for item in data.backlog_items[:10]:  # cap at 10 to stay within token budget
            lines.append(f"- {item}")
        if len(data.backlog_items) > 10:
            lines.append(f"- … and {len(data.backlog_items) - 10} more")
        lines.append("")

    # --- Degradation warnings (at bottom so they don't dominate) ---
    if data.assembly_warnings:
        lines.append("### ⚠ Partial Briefing")
        for warning in data.assembly_warnings:
            lines.append(f"- {warning}")
        lines.append("")

    return "\n".join(lines)
