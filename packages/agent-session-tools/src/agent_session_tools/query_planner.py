"""Pure shared query planner for deterministic AND-to-OR FTS fallback."""

from __future__ import annotations

import re
import unicodedata
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

# Unicode general categories dropped from a raw token before it is quoted:
# control characters (Cc) and surrogates (Cs). Everything else -- punctuation,
# symbols, other scripts -- is left for the FTS5 tokenizer, which is what makes
# the quoted form parse-safe without a whitelist of characters.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cs"})


def _terms(question: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _TERM.findall(question.lower())
        if token not in STOP and len(token) > 2
    )


def _quote_term(term: str) -> str:
    """Wrap one extracted token as an FTS5 double-quoted phrase."""
    return f'"{term}"'


def prose_tokens(question: str) -> tuple[str, ...]:
    """Every whitespace-separated token of ``question`` that carries an alphanumeric.

    The §5 candidate's tokenisation (council D-12), ported from the archived
    ``feat/knowledge-proof`` branch's ``plan_prose_query``: no stop list, no
    length filter, case preserved. Control and surrogate characters are
    stripped from each token first; a token left with no alphanumeric at all
    (``---``, ``???``) is dropped because FTS5 could match nothing in it.
    """
    tokens: list[str] = []
    for raw in question.split():
        token = "".join(
            char for char in raw if unicodedata.category(char) not in _UNSAFE_CATEGORIES
        )
        if any(char.isalnum() for char in token):
            tokens.append(token)
    return tuple(tokens)


def _quote_prose_token(token: str) -> str:
    """Quote a raw token as one FTS5 string; an embedded ``"`` is doubled, per FTS5."""
    return '"' + token.replace('"', '""') + '"'


def prose_or_query(question: str) -> str:
    """The §5 candidate widen string: every raw token quoted and joined with ``OR``.

    Nothing this returns can fail to parse: each token is a double-quoted FTS5
    string, so operators, columns, prefixes and punctuation inside it are
    plain text for the tokenizer. Returns ``""`` when no token survives.
    """
    return " OR ".join(_quote_prose_token(token) for token in prose_tokens(question))


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
