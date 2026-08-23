"""Is this string actually a concept, or is it debris?

Concepts are harvested from real notes, and real notes are messy. The mastery
graph for `python` was rendering nodes labelled ``Unsupported markdown: list``,
``'eat','tea','ate'``, ``(5+10) -> 15 -> (15*3) -> 45``, and
``(a) a function that accepts a function as an argument`` -- because every one of
those is a genuine markdown heading somewhere in the source notes. Headings are a
good signal for concepts and a terrible one for *only* concepts.

The same debris reaches the study-plan agent, which is handed
``seed_from_history()`` evidence including ``study-notes/introd`` (a truncated
path), ``quick topic``, and the single character ``x``. An agent asked to build a
plan around a concept called ``x`` will either invent a meaning for it or waste a
turn asking what it is.

So this module answers one question in one place. It is deliberately a REJECTION
filter rather than a classifier: the cost of dropping a real concept is one
missing node, while the cost of keeping debris is a graph the learner stops
trusting and an agent reasoning about nonsense.
"""

from __future__ import annotations

import re

#: Below this length a "concept" is an initial or a typo. Three, not four,
#: because `gil` is a real and load-bearing concept -- and in the live database
#: it is the ONLY struggle signal, so a floor of four would silently delete the
#: single piece of evidence the study-plan agent has to work from. Short genuine
#: concepts are common in this domain (gil, orm, api, dry), so length alone
#: cannot carry this rule; `_SHORT_STOPWORDS` does the rest.
MIN_CONCEPT_CHARS = 3

#: Short tokens that pass the length floor but are not concepts: language
#: keywords, metasyntactic variables, and filler. Kept deliberately small --
#: anything domain-meaningful (gil, orm, api, abc, dry, tdd) stays out of it.
_SHORT_STOPWORDS = frozenset(
    {
        "and",
        "any",
        "are",
        "bar",
        "baz",
        "def",
        "for",
        "foo",
        "has",
        "int",
        "let",
        "new",
        "not",
        "one",
        "str",
        "the",
        "try",
        "two",
        "use",
        "var",
        "was",
        "why",
        "yes",
    }
)

#: Above this it is a sentence, a quiz question, or a worked example.
MAX_CONCEPT_CHARS = 80

#: A concept is a short noun phrase. "composition over inheritance" is three
#: words; "single responsibility principle" is three. Anything past five is prose
#: about a concept rather than the concept -- which is how
#: "'this is terrible. any competent developer would use a decorator here.'"
#: ended up rendered as a graph node. Word count turned out to be the single
#: most discriminating rule, and character length alone was far too permissive.
MAX_CONCEPT_WORDS = 5

#: Artefacts of markdown conversion tools. These are not concepts in any note.
_TOOL_ARTEFACT_RE = re.compile(
    r"^\s*(unsupported\s+markdown|untitled|no\s+title|figure|table|image|listing)\b",
    re.IGNORECASE,
)

#: Placeholders people type when testing the tool on themselves.
_PLACEHOLDERS = frozenset(
    {
        "quick topic",
        "test",
        "test topic",
        "testing",
        "todo",
        "tbd",
        "misc",
        "notes",
        "note",
        "untitled",
        "example",
        "temp",
        "scratch",
    }
)

#: Enumerated answer markers: "(a) ...", "1. ...", "b) ...". A quiz option is a
#: sentence about a concept, not the concept.
_ENUMERATION_RE = re.compile(r"^\s*[(\[]?[a-z0-9][)\].]\s+", re.IGNORECASE)

#: Arrows and comparison operators mean a worked example or a derivation.
_DERIVATION_RE = re.compile(r"(->|=>|-->|\u2192|\u21d2|==|!=|>=|<=)")

#: A quoted token list, e.g. "'eat','tea','ate'" -- data, not a concept.
_QUOTED_LIST_RE = re.compile(r"""^['"].*['"]\s*,\s*['"]""")


def is_usable_concept(value: object) -> bool:
    """Return True when ``value`` looks like a concept a learner would recognise.

    Rejection order is cheapest-first. Every rule below exists because a real
    example of it was rendered as a node in a real mastery graph, or handed to
    the plan agent as evidence.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    # A backtick code span is usually the concept itself -- `typing.protocol`,
    # `asyncio.gather` -- so unwrap it and judge the identifier inside. This is
    # deliberately NOT done for single or double quotes: those wrap prose
    # fragments lifted out of notes ("'button'", "'append' creates a new array")
    # which are not concepts, and unwrapping them would readmit that debris.
    if len(text) > 2 and text[0] == "`" and text[-1] == "`":
        text = text[1:-1].strip()
    if not text:
        return False

    # Length. Single characters and initials carry no meaning; sentences are not
    # concepts even when they are about one.
    if len(text) < MIN_CONCEPT_CHARS or len(text) > MAX_CONCEPT_CHARS:
        return False

    lowered = text.lower()
    if lowered in _PLACEHOLDERS or lowered in _SHORT_STOPWORDS:
        return False
    if _TOOL_ARTEFACT_RE.match(text):
        return False

    # A path fragment, usually truncated: "study-notes/introd".
    if "/" in text or "\\" in text:
        return False

    # Leading quote means a fragment lifted out of prose or code, not a concept:
    # "'button'", "'append' creates a new array".
    if text[0] in "'\"`":
        return False

    # A leaked markdown or comment marker: "# with abstract methods get amount".
    # A leading dot is a filename: ".pre commit config.yaml".
    if text[0] in "#*>-+=|.":
        return False

    # A leading section number is document structure, not a concept:
    # "005 notification patterns", "2.8 two pointer technique". Written to match
    # a number followed by whitespace, so genuine concepts that begin with a
    # digit ("2-phase commit", "3-tier architecture") are untouched.
    if re.match(r"^\d+(\.\d+)*\s", text):
        return False

    # Sentence punctuation. A trailing colon is a heading fragment that continues
    # elsewhere; a trailing full stop is prose. Both were observed as nodes.
    if text.endswith((":", ".", "!", "?", ",", ";")):
        return False

    # An internal sentence break means at least two sentences, so prose.
    if re.search(r"[.!?]\s+\w", text):
        return False

    if _QUOTED_LIST_RE.match(text):
        return False
    if _ENUMERATION_RE.match(text):
        return False
    if _DERIVATION_RE.search(text):
        return False

    # Must be mostly letters. Catches arithmetic, code fragments and symbol
    # soup without needing a rule per shape.
    letters = sum(1 for ch in text if ch.isalpha())
    if letters < len(text) * 0.6:
        return False

    words = [w for w in re.split(r"[\s_-]+", text) if w]
    if len(words) > MAX_CONCEPT_WORDS:
        return False

    # A single short word is an initial or a keyword, not a concept.
    return not (len(words) == 1 and len(words[0]) < MIN_CONCEPT_CHARS)


def filter_concepts(values: object) -> list[str]:
    """Return only the usable concepts from an iterable, de-duplicated.

    Order is preserved so the strongest evidence stays first.
    """
    if not values or isinstance(values, str):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for value in values:  # type: ignore[union-attr]
        if not is_usable_concept(value):
            continue
        key = str(value).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(str(value).strip())
    return out
