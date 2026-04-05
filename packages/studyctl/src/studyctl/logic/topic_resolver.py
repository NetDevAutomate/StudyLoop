"""Topic resolution — pure functional core, no I/O.

Resolves a free-text query string (e.g., "Python Decorators") to a
configured TopicConfig via cascading match: exact name → name substring
→ tag match → fuzzy (difflib). The imperative shell (cli/_study.py)
handles interactive picking when the result is ambiguous.

Uses str.casefold() throughout for Unicode-correct case-insensitive
comparison (handles ß→ss, accented characters, etc.).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from studyctl.settings import TopicConfig


class MatchKind(Enum):
    """How the topic was resolved."""

    EXACT = auto()  # name == query (casefold)
    NAME = auto()  # name is substring of query (or reverse)
    TAG = auto()  # a tag appears in the query
    FUZZY = auto()  # difflib close match
    NONE = auto()  # no match at all


@dataclass(frozen=True)
class ResolveResult:
    """Typed result from topic resolution.

    - Single match: ``resolved`` returns the TopicConfig.
    - Multiple matches: ``resolved`` is None; ``matches`` has candidates.
    - No match: ``kind`` is NONE; ``matches`` is empty.
    """

    kind: MatchKind
    matches: list[TopicConfig]

    @property
    def resolved(self) -> TopicConfig | None:
        """Single unambiguous match, or None."""
        return self.matches[0] if len(self.matches) == 1 else None


def resolve_topic(query: str, topics: list[TopicConfig]) -> ResolveResult:
    """Resolve a free-text query to a TopicConfig.

    Pure function — no I/O, no side effects. The CLI shell handles
    interactive picking when multiple matches are returned.

    Cascade order (first match wins):
      1. Exact name (casefold)
      2. Name substring (topic.name in query, or query in topic.name)
      3. Tag match (any tag appears in query)
      4. Fuzzy fallback (difflib.get_close_matches, cutoff=0.5)

    Args:
        query: Free-text topic string from the user.
        topics: Configured TopicConfig list from settings.

    Returns:
        ResolveResult with kind and matches.
    """
    if not topics:
        return ResolveResult(MatchKind.NONE, [])

    q = query.casefold().strip()
    if not q:
        return ResolveResult(MatchKind.NONE, [])

    # 1. Exact name match
    exact = [t for t in topics if t.name.casefold() == q]
    if exact:
        return ResolveResult(MatchKind.EXACT, exact)

    # 2. Name substring match (either direction)
    name_hits = [t for t in topics if t.name.casefold() in q or q in t.name.casefold()]
    if name_hits:
        return ResolveResult(MatchKind.NAME, name_hits)

    # 3. Tag match — any configured tag appears in the query
    tag_hits = [t for t in topics if any(tag.casefold() in q for tag in t.tags)]
    if tag_hits:
        return ResolveResult(MatchKind.TAG, tag_hits)

    # 4. Fuzzy fallback — difflib catches typos
    all_names = {t.name.casefold(): t for t in topics}
    close = difflib.get_close_matches(q, list(all_names), n=5, cutoff=0.5)
    if close:
        fuzzy_hits = [all_names[c] for c in close]
        return ResolveResult(MatchKind.FUZZY, fuzzy_hits)

    return ResolveResult(MatchKind.NONE, [])
