"""One test per derivation rule, on hand-built events.

Hand-built rather than sampled: a rule test has to name the shape it is deciding,
and the corpus shapes that matter here are small enough to write down. The real
corpus is exercised by the receipt and by the orchestrator-labelled fixture.
"""

from __future__ import annotations

import json

import pytest

from learning_memory.derive import (
    DERIVATION_VERSION,
    FAILURE_LEXICON,
    INTERROGATIVES,
    NEAR_REPEAT_RATIO,
    StoredEvent,
    ends_with_prose,
    exchange_flags,
    had_error,
    intent_of,
    is_near_repeat,
    is_question,
    load_vocabulary,
    outcome_of,
    retried,
    split_exchanges,
    strip_user_wrapper,
)

SEQ = iter(range(10_000))


def ev(kind: str, text: str, *, turn: int = 1, tool: str | None = None, ts: str | None = None):
    """One event, with a fresh id/seq so ordering is unambiguous."""
    index = next(SEQ)
    return StoredEvent(
        id=index, turn_id=turn, seq=index, kind=kind, text=text, tool_name=tool, ts=ts
    )


# ------------------------------------------------------------------ wrappers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<task>\nplease review the repo\n</task>", "please review the repo"),
        (
            "<task>\nfix the gate\n</task>\n<environment_details>noise</environment_details>",
            "fix the gate",
        ),
        ("<user_query>\nwhat model is used?\n</user_query>", "what model is used?"),
        ("<USER_QUERY>\nupper case tag\n</USER_QUERY>", "upper case tag"),
        ("plain prose, no wrapper", "plain prose, no wrapper"),
        (
            "<system-reminder>not a learner wrapper</system-reminder>",
            "<system-reminder>not a learner wrapper</system-reminder>",
        ),
        ("  leading and trailing  ", "leading and trailing"),
    ],
)
def test_strip_user_wrapper(raw: str, expected: str) -> None:
    assert strip_user_wrapper(raw) == expected


# ------------------------------------------------------------------ is_question


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("why did the gate fail?", True),
        ("why did the gate fail", True),  # interrogative first word, no mark
        ("How do I run this", True),
        ("WHICH one wins", True),
        ("do the tests pass", True),
        ("is that right", True),
        ("fix the failing test", False),
        ("please review the repo", False),
        ("4", False),
        ("", False),
        ("run it -- does it work?", True),  # '?' anywhere
        ("<task>\nhow do I wire this up\n</task>", True),  # wrapper stripped first
        ("<user_query>\nwhat model is used?\n</user_query>", True),
        ("<task>\nrefactor the parser\n</task>", False),
        ("whatever happens, ship it", False),  # 'whatever' is not 'what'
        ("'why' quoted first word", True),
    ],
)
def test_is_question(text: str, expected: bool) -> None:
    assert is_question(text) is expected


def test_interrogatives_are_versioned_and_lowercase() -> None:
    assert {
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "can",
        "could",
        "should",
        "would",
        "does",
        "do",
        "is",
        "are",
        "will",
    } == INTERROGATIVES


# -------------------------------------------------------------------- had_error


def test_had_error_on_an_error_event() -> None:
    assert had_error([ev("user", "go"), ev("error", "[API Error: nope]")]) is True


@pytest.mark.parametrize(
    "text",
    [
        "Traceback (most recent call last):",
        "raised an Exception during the run",
        "error: could not compile",
        "the build failed",
        "cannot open the file",
        "module not found",
        "permission denied on /etc",
        "no such file or directory",
        "syntax error near line 3",
        "the request timed out",
        "exit code 1",
        "exit code 127",
    ],
)
def test_had_error_lexicon_hits(text: str) -> None:
    assert had_error([ev("user", "go"), ev("tool_result", text)]) is True
    assert had_error([ev("user", "go"), ev("assistant_prose", text)]) is True


@pytest.mark.parametrize(
    "text",
    [
        "everything passed cleanly",
        "exit code 0",  # only 1-9 count as failure
        "the errorless path",  # word-bounded: 'error:' needs the colon
        "errors are interesting in general",
        "it cannot-be-hyphenated",  # still a word boundary hit
    ],
)
def test_had_error_lexicon_misses_and_edges(text: str) -> None:
    result = had_error([ev("user", "go"), ev("assistant_prose", text)])
    assert result is (text == "it cannot-be-hyphenated")


def test_had_error_ignores_tool_call_and_user_text() -> None:
    """The lexicon reads OUTPUT, not the request: 'fix the failed test' is not an error."""
    assert had_error([ev("user", "fix the failed test")]) is False
    assert had_error([ev("user", "go"), ev("tool_call", "failed", tool="Bash")]) is False


def test_failure_lexicon_is_versioned() -> None:
    assert len(FAILURE_LEXICON) == 11
    assert all(pattern.startswith("\\b") for pattern in FAILURE_LEXICON)


# ---------------------------------------------------------------------- retried


def test_retried_on_repeated_bare_tool_name() -> None:
    """The archive path: 39,620 of 39,796 tool_calls have no arguments at all."""
    events = [
        ev("user", "run the tests"),
        ev("tool_call", "", tool="Bash"),
        ev("tool_result", "exit 1"),
        ev("tool_call", "", tool="Bash"),
    ]
    assert retried(events) is True


def test_not_retried_for_two_different_tools() -> None:
    events = [
        ev("user", "look around"),
        ev("tool_call", "", tool="Bash"),
        ev("tool_call", "", tool="Read"),
    ]
    assert retried(events) is False


def test_retried_uses_arguments_when_the_archive_kept_them() -> None:
    same = [
        ev("user", "go"),
        ev("tool_call", "ls -la", tool="Bash"),
        ev("tool_call", "ls  -la ", tool="Bash"),  # whitespace-normalised match
    ]
    different = [
        ev("user", "go"),
        ev("tool_call", "ls -la", tool="Bash"),
        ev("tool_call", "pwd", tool="Bash"),
    ]
    assert retried(same) is True
    assert retried(different) is False


def test_a_bare_call_and_an_argument_call_are_different_signatures() -> None:
    """Documented consequence of "normalised-args form only if text"."""
    events = [
        ev("user", "go"),
        ev("tool_call", "", tool="Bash"),
        ev("tool_call", "ls", tool="Bash"),
    ]
    assert retried(events) is False


def test_retried_ignores_non_tool_events() -> None:
    events = [ev("user", "go"), ev("assistant_prose", "same"), ev("assistant_prose", "same")]
    assert retried(events) is False


# --------------------------------------------------------------------- resolved


def test_resolved_when_closed_by_prose_and_the_next_turn_moves_on() -> None:
    question = ev("user", "why did it fail?", turn=1)
    answers = [ev("tool_call", "", tool="Bash"), ev("assistant_prose", "because of X")]
    exchange = exchange_flags(question, answers, next_user_text="now fix the other thing")
    assert exchange.resolved is True


def test_not_resolved_when_the_next_turn_is_a_near_repeat() -> None:
    question = ev("user", "why did the gate fail?", turn=1)
    answers = [ev("assistant_prose", "unclear")]
    exchange = exchange_flags(question, answers, next_user_text="why did the gate fail??")
    assert exchange.resolved is False


def test_not_resolved_when_the_exchange_ends_on_a_tool_call() -> None:
    question = ev("user", "run it", turn=1)
    answers = [ev("assistant_prose", "running"), ev("tool_call", "", tool="Bash")]
    assert exchange_flags(question, answers, next_user_text=None).resolved is False


def test_last_exchange_is_resolved_purely_on_ending_in_prose() -> None:
    question = ev("user", "and finally?", turn=3)
    assert exchange_flags(question, [ev("assistant_prose", "done")], next_user_text=None).resolved


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("why did the gate fail?", "why did the gate fail?", True),
        ("why did the gate fail?", "  WHY did the   gate fail? ", True),
        ("why did the gate fail?", "why did the gate fail??", True),
        ("why did the gate fail?", "what about the tokenizer?", False),
        ("<task>\nfix the gate\n</task>", "fix the gate", True),  # wrapper-insensitive
        ("", "anything", False),
        ("anything", "", False),
    ],
)
def test_is_near_repeat(first: str, second: str, expected: bool) -> None:
    assert is_near_repeat(first, second) is expected


def test_near_repeat_threshold_is_the_documented_one() -> None:
    assert NEAR_REPEAT_RATIO == 0.9


def test_ends_with_prose_on_empty() -> None:
    assert ends_with_prose([]) is False


# ------------------------------------------------------------------- threading


def test_pre_first_user_events_are_quarantined() -> None:
    events = [
        ev("system", "You are Claude Code...", turn=0),
        ev("assistant_prose", "orphan prose", turn=0),
        ev("user", "the first real turn?", turn=1),
        ev("assistant_prose", "an answer", turn=1),
    ]
    exchanges = split_exchanges(events)
    assert len(exchanges) == 2
    preamble, real = exchanges
    assert preamble.quarantine_reason == "pre_first_user"
    assert preamble.resolved is None
    assert preamble.turn_id == 0
    assert preamble.question_event_id is None, "the DB marker for pre_first_user"
    assert len(preamble.answer_event_ids) == 2
    assert real.quarantine_reason is None
    assert real.resolved is True


def test_an_empty_user_turn_is_quarantined_with_its_followers() -> None:
    events = [
        ev("user", "   \n\t ", turn=1),
        ev("assistant_prose", "answering nothing", turn=1),
        ev("user", "a real question?", turn=2),
        ev("assistant_prose", "a real answer", turn=2),
    ]
    exchanges = split_exchanges(events)
    assert exchanges[0].quarantine_reason == "empty_user_text"
    assert exchanges[0].resolved is None
    assert exchanges[0].question_event_id is not None, "the DB marker for empty_user_text"
    assert exchanges[0].is_question is False
    assert exchanges[1].quarantine_reason is None


def test_a_tool_only_exchange_threads_but_does_not_resolve() -> None:
    events = [
        ev("user", "run the suite", turn=1),
        ev("tool_call", "", tool="Bash", turn=1),
        ev("tool_result", "exit code 1", turn=1),
        ev("tool_call", "", tool="Bash", turn=1),
    ]
    (exchange,) = split_exchanges(events)
    assert exchange.quarantine_reason is None
    assert (exchange.is_question, exchange.had_error, exchange.retried) == (False, True, True)
    assert exchange.resolved is False


def test_threading_is_ordered_by_seq_not_insertion() -> None:
    """Events arrive in any order; seq decides. events.seq is the ADR's order."""
    later = StoredEvent(id=900, turn_id=1, seq=2, kind="assistant_prose", text="second")
    earlier = StoredEvent(id=901, turn_id=1, seq=1, kind="user", text="first?")
    (exchange,) = split_exchanges([later, earlier])
    assert exchange.question_event_id == 901
    assert exchange.answer_event_ids == (900,)


def test_no_user_events_at_all_is_one_quarantine_row() -> None:
    events = [ev("tool_call", "", tool="Bash", turn=0), ev("tool_result", "ok", turn=0)]
    (exchange,) = split_exchanges(events)
    assert exchange.quarantine_reason == "pre_first_user"


def test_empty_event_list_derives_nothing() -> None:
    assert split_exchanges([]) == []


# -------------------------------------------------------------- intent/outcome


def test_intent_is_the_first_real_user_turn_wrapper_stripped() -> None:
    events = [
        ev("system", "preamble", turn=0),
        ev("user", "   ", turn=1),
        ev("user", "<task>\nthe real intent\n</task>", turn=2),
        ev("assistant_prose", "ok", turn=2),
    ]
    exchanges = split_exchanges(events)
    assert intent_of(exchanges) == "the real intent"


def test_intent_is_capped_at_200_characters() -> None:
    events = [ev("user", "x" * 500, turn=1), ev("assistant_prose", "ok", turn=1)]
    assert len(intent_of(split_exchanges(events)) or "") == 200


def test_outcome_is_the_last_prose_of_the_last_resolved_exchange() -> None:
    events = [
        ev("user", "first?", turn=1),
        ev("assistant_prose", "first answer", turn=1),
        ev("user", "second?", turn=2),
        ev("assistant_prose", "second answer", turn=2),
        ev("tool_call", "", tool="Bash", turn=2),
    ]
    exchanges = split_exchanges(events)
    assert exchanges[1].resolved is False, "turn 2 ends on a tool call"
    assert outcome_of(exchanges) == "first answer"


def test_outcome_is_none_when_nothing_resolved() -> None:
    events = [ev("user", "go", turn=1), ev("tool_call", "", tool="Bash", turn=1)]
    assert outcome_of(split_exchanges(events)) is None


# --------------------------------------------------------------------- concepts


def test_vocabulary_shape_matches_the_copied_file() -> None:
    vocab = load_vocabulary()
    assert vocab.sha256 == "203020fa870a5c4e07164e27654b2fea0bec097f416a8d26ffb0679369c82ebb"
    assert len(vocab.areas) == 7
    # 108 term entries -> 103 distinct terms; + 7 areas, of which 'graphrag' is also
    # a term in its own area, so 103 + 7 - 1 = 109 canonical concepts.
    assert len(vocab.concepts) == 109
    assert len(vocab.alias_to_concept) == 185


@pytest.mark.parametrize(
    ("text", "canonical", "source"),
    [
        ("we used spark for this", "spark", "vocab"),
        ("the pre-commit hook", "pre-commit", "vocab"),
        ("the pre commit hook", "pre-commit", "alias"),
        ("the precommit hook", "pre-commit", "alias"),
        ("SPARK in caps", "spark", "vocab"),
        ("data-engineering as an area", "data-engineering", "vocab"),
        ("data engineering as an area", "data-engineering", "alias"),
    ],
)
def test_concept_tagging_forms(text: str, canonical: str, source: str) -> None:
    assert (canonical, source) in load_vocabulary().tag([text])


def test_concept_tagging_is_whole_word_only() -> None:
    vocab = load_vocabulary()
    assert vocab.tag(["sparkle plenty"]) == set()
    assert vocab.tag(["nonoop"]) == set()
    assert ("oop", "vocab") in vocab.tag(["about oop, generally"])


def test_alias_collisions_are_recorded_not_silently_dropped() -> None:
    """First writer wins, and the loser is named on the receipt."""
    vocab = load_vocabulary()
    for alias, kept, dropped in vocab.alias_collisions:
        assert kept != dropped
        assert vocab.alias_to_concept[alias] == kept


def test_derivation_version_is_named() -> None:
    assert DERIVATION_VERSION == "derive-v1"


# ---------------------------------------------------------------- gold-blindness


DERIVATION_MODULES = ("derive.py", "run_derive.py")


def test_the_derivation_surface_never_references_the_gold_set() -> None:
    """Derivation must not be tunable against DEV gold (council finding 13).

    Scoped to the derivation modules and the data it loads, not the whole package:
    Stage C's ``ingest_archive.py`` DOES name the gold, because its receipt records
    the ruler's own ``corpus_digest`` over the gold's sessions. That is a receipt
    input, never a derivation input, and the next test pins it as the only one.
    """
    import learning_memory

    root = __import__("pathlib").Path(learning_memory.__file__).parent
    offenders: list[str] = []
    for name in DERIVATION_MODULES:
        body = (root / name).read_text(encoding="utf-8")
        for needle in ("gold-v2", "gold_v2", "receipts/", "sealed", "--gold"):
            if needle in body:
                offenders.append(f"{name}: {needle}")
    for path in (root / "data").rglob("*"):
        if path.is_file():
            offenders.extend(
                f"data/{path.name}: {needle}"
                for needle in ("gold", "sealed")
                if needle in path.read_text(encoding="utf-8", errors="replace").casefold()
            )
    assert offenders == [], f"gold/receipt references on the derivation path: {offenders}"


def test_only_two_modules_may_even_name_the_gold() -> None:
    """Pin the permitted references, so a new one has to be argued for.

    ``ingest_archive.py`` READS the gold, to compute the ruler's corpus digest for
    the Stage C receipt. ``adapters/archive.py`` only mentions it in one docstring
    sentence (ADR §6: unchanged session ids let existing gold questions score this
    store). Neither is on the derivation path, which the test above holds at zero.
    """
    import learning_memory

    root = __import__("pathlib").Path(learning_memory.__file__).parent
    naming = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "gold" in path.read_text(encoding="utf-8")
    )
    assert naming == ["adapters/archive.py", "ingest_archive.py"]


def test_the_vocab_file_is_data_not_gold() -> None:
    from learning_memory.derive import VOCAB_PATH

    payload = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    assert set(payload) == {
        "python",
        "aws",
        "data-engineering",
        "graphrag",
        "software-development",
        "obsidian",
        "devops",
    }
