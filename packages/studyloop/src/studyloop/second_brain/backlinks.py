"""Wikilinks from a projection to the learner's own notes.

The matcher already exists: the session-memory export builds a term-to-note index
from the vault and turns topic strings into ``[[NoteTitle]]`` links. Reusing it is
the point — two matchers would produce two different sets of links from the same
vault, and a learner would see study notes linking to one place and session notes
to another.

It lives in ``agent_session_tools``, a separate package with its own import
boundary and its own wheel. The import is therefore lazy AND optional: StudyLoop's
wheel can be installed without it, and when it is, publishing continues without
backlinks rather than failing. Losing a convenience is not a reason to refuse to
write a note.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from studyloop.planning.models import StudyPlan

logger = logging.getLogger(__name__)

#: Warn at most once per process. The matcher's absence is a property of the
#: installation, not of this publish, so repeating it on every operation would be
#: noise about a condition that cannot change mid-run.
_warned_missing_matcher = False


def reset_warning_state() -> None:
    """Clear the warn-once latch. For tests only."""
    global _warned_missing_matcher
    _warned_missing_matcher = False


def link_candidates(plan: StudyPlan) -> list[str]:
    """Terms worth trying to link, most specific first.

    Plan topics come first because they are the learner's own vocabulary for the
    subject; milestone concepts follow. Case-insensitive de-duplication keeps the
    first spelling, so ``SQL`` beats a later ``sql``.
    """
    candidates: list[str] = [*plan.topics]
    for milestone in plan.milestones:
        candidates.extend(milestone.concepts)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        term = candidate.strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(term)
    return unique


def wikilinks_for(plan: StudyPlan, vault_root: Path, *, enabled: bool = True) -> list[str]:
    """``[[NoteTitle]]`` links from this plan's terms to notes in the vault.

    One vault scan per call. No cache: a stale index would link to notes the
    learner has since renamed, and a wrong link is worse than a missing one.
    """
    global _warned_missing_matcher

    if not enabled:
        return []

    candidates = link_candidates(plan)
    if not candidates:
        return []

    try:
        from agent_session_tools.obsidian_writer import build_topic_index, inject_backlinks
    except ImportError:
        if not _warned_missing_matcher:
            _warned_missing_matcher = True
            logger.warning(
                "Backlinks are enabled but the vault topic matcher is not installed; "
                "publishing without wikilinks."
            )
        return []

    try:
        index = build_topic_index(vault_root)
        return list(inject_backlinks(candidates, index))
    except OSError as exc:
        logger.debug("backlink scan failed: %s", exc)
        return []


__all__ = ["link_candidates", "reset_warning_state", "wikilinks_for"]
