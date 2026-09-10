"""Pure shared query planner for deterministic AND-to-OR FTS fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Pinned verbatim from SessionWeaver v0.2.0. Keep this string form so changes
# remain a literal diff against the released planner.
STOP = frozenset(
    "a an the is are was were be been being do does did to of in on for with"
    " and or not what which who why how when where whose that this these those"
    " it its during every any can cant can't could should would will shall"
    " about into from as at by we our your my i you they them he she his her".split()
)

_TERM = re.compile(r"[a-zA-Z0-9_./-]+")


def _terms(question: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _TERM.findall(question.lower())
        if token not in STOP and len(token) > 2
    )


def _quote_term(term: str) -> str:
    """Wrap one extracted token as an FTS5 double-quoted phrase."""
    return f'"{term}"'


@dataclass(frozen=True)
class QueryPlan:
    """The pure AND-to-OR plan for one question."""

    terms: tuple[str, ...]
    and_query: str
    or_query: str
    fallback_used: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "terms": list(self.terms),
            "and_query": self.and_query,
            "or_query": self.or_query,
            "fallback_used": self.fallback_used,
        }


def plan(question: str) -> QueryPlan:
    """Tokenize, drop stop words/short tokens, and build safe FTS5 queries."""
    terms = _terms(question)
    quoted = tuple(_quote_term(term) for term in terms)
    return QueryPlan(
        terms=terms,
        and_query=" AND ".join(quoted),
        or_query=" OR ".join(quoted),
    )
