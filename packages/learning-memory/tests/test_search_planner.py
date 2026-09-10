"""D1: natural-language input must never reach FTS5 as syntax.

Council reproduction D1: ``search_prose("Which ADR path did the DoD and WP-9
require?")`` — a query from the DEV baseline — died with ``OperationalError: no such
column: 9``, the identical defect the shipped keyword path throws on for 46 % of
natural questions.

Every token is phrase-quoted and OR-joined, so ``AND``, ``NOT``, ``(``, ``*`` and a
bare number are words rather than operators. Deliberate FTS5 syntax goes through
``search_prose_raw``, which is allowed to raise.
"""

from __future__ import annotations

import sqlite3

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from learning_memory import Event, ParsedSession, Session, Store, plan_prose_query

# The DEV baseline query from the reproduction, plus the adversarial set.
D1_QUERY = "Which ADR path did the DoD and WP-9 require?"
TOOL_TOKEN = "zzqqtoolonly"
ADVERSARIAL = [
    D1_QUERY,
    'what "quoted" AND NOT (x)',
    "9",
    "",
    "   ",
    "?",
    "--- !!",
    "NEAR(a b, 2)",
    "col:value AND *",
    "recall^2 OR (gold v2)",
    "don't stop",
    "日本語 と WP-9",
    "a" * 300,
    # A NUL ends FTS5's C-string parse, so the closing quote of a phrase is never
    # seen: this exact string raised OperationalError('unterminated string') and was
    # found by the property test below, not by hand.
    "0\x00",
    "tok\x00en and \x01\x02 control",
]


def _seeded(store: Store) -> None:
    store.ingest(
        ParsedSession(
            session=Session(id="s-fts", harness="kiro"),
            events=[
                Event(
                    turn_id=0,
                    seq=0,
                    kind="user",
                    text="Which ADR path did the DoD and WP-9 require?",
                    actor="user",
                ),
                Event(
                    turn_id=0,
                    seq=1,
                    kind="assistant_prose",
                    text="The DoD required the ADR path under WP-9.",
                    actor="agent",
                ),
                Event(turn_id=0, seq=2, kind="tool_result", text=f"{TOOL_TOKEN} output"),
            ],
            adapter_version="kiro@1",
        )
    )


def test_the_reproduced_query_no_longer_raises(store: Store) -> None:
    """D1 flip: this exact string raised OperationalError('no such column: 9')."""
    _seeded(store)
    hits = store.search_prose(D1_QUERY)
    assert [hit["kind"] for hit in hits], "the question should match its own transcript"
    assert all(hit["kind"] in ("user", "assistant_prose") for hit in hits)


def test_the_reproduced_query_still_raises_through_the_raw_api(store: Store) -> None:
    """The defect is not "fixed everywhere" -- it is confined to an explicit API."""
    _seeded(store)
    with pytest.raises(sqlite3.OperationalError):
        store.search_prose_raw(D1_QUERY)


@pytest.mark.parametrize("query", ADVERSARIAL)
def test_no_adversarial_query_raises(store: Store, query: str) -> None:
    _seeded(store)
    assert isinstance(store.search_prose(query), list)


@settings(max_examples=500)
@given(
    query=st.text(alphabet=st.characters(codec="utf-8", exclude_categories=("Cs",)), max_size=80)
)
def test_no_text_at_all_can_make_the_planner_produce_invalid_fts(query: str) -> None:
    """Property form: arbitrary text either plans to nothing or to a legal expression.

    Deliberately wide (500 examples over the whole encodable alphabet): this is the
    fuzz surface that found the NUL defect, so it earns the extra examples.
    """
    from learning_memory import Store as _Store

    store = _Store.connect(":memory:")
    store.install()
    try:
        _seeded(store)
        store.search_prose(query)
    finally:
        store.close()


def test_empty_and_wordless_queries_return_nothing_without_touching_fts(store: Store) -> None:
    _seeded(store)
    for query in ("", "   ", "?", "-- ---", "\n\t"):
        assert plan_prose_query(query) == ""
        assert store.search_prose(query) == []


def test_a_lone_surrogate_does_not_reach_sqlite(store: Store) -> None:
    """A lone surrogate cannot be encoded as TEXT; the planner drops it instead."""
    _seeded(store)
    assert plan_prose_query("\ud800") == ""
    assert store.search_prose("\ud800") == []
    assert store.search_prose("recall \ud800 path") == store.search_prose("recall path")


def test_planner_strips_characters_fts5_cannot_parse() -> None:
    assert plan_prose_query("0\x00") == '"0"'
    assert plan_prose_query("\x00\x01") == ""
    assert plan_prose_query("WP\x00-9") == '"WP-9"'


def test_planner_shape() -> None:
    assert plan_prose_query("DoD WP-9") == '"DoD" OR "WP-9"'
    assert plan_prose_query('a "b" c') == '"a" OR """b""" OR "c"'
    assert plan_prose_query("9") == '"9"'
    assert plan_prose_query("AND NOT OR") == '"AND" OR "NOT" OR "OR"', "operators become words"


def test_hyphenated_token_matches_adjacently(store: Store) -> None:
    """`WP-9` is one phrase, so it matches the adjacent pair rather than 9 anywhere."""
    store.ingest(
        ParsedSession(
            session=Session(id="s-hyphen", harness="kiro"),
            events=[
                Event(turn_id=0, seq=0, kind="user", text="WP-9 is the work package", actor="user"),
                Event(turn_id=1, seq=1, kind="user", text="9 alone, and WP alone", actor="user"),
            ],
            adapter_version="kiro@1",
        )
    )
    hits = store.search_prose_raw(plan_prose_query("WP-9"))
    assert [hit["text"] for hit in hits] == ["WP-9 is the work package"]


def test_search_still_excludes_tool_text(store: Store) -> None:
    """The planner must not become a way around the prose-only index.

    Note the planner is OR-joined, so a sentence *containing* a tool-only token can
    still match prose through its other words -- what must never happen is a
    tool-kind row coming back, or the tool token matching on its own.
    """
    _seeded(store)
    assert store.search_prose(TOOL_TOKEN) == []
    assert store.search_prose_raw(f'"{TOOL_TOKEN}"') == []
    hits = store.search_prose(f"what did {TOOL_TOKEN} output say?")
    assert all(hit["kind"] in ("user", "assistant_prose") for hit in hits)
    assert all(TOOL_TOKEN not in hit["text"] for hit in hits)
