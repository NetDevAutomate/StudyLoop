"""Strict parsing and validation for A3a wind-down documents."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from agent_session_tools.context.winddown import _parse_bind_document, _parse_winddown


def _concept(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "Decision",
        "title": "Keep exact evidence",
        "description": "Bind each concept to the stored source text.",
        "tags": ["evidence", "session-weaver"],
        "confidence": 0.9,
        "quotes": [{"quote": "stored source text"}],
    }
    value.update(changes)
    return value


def _document(concepts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"concepts": [_concept()] if concepts is None else concepts}


def _codes(document: object) -> set[tuple[str, str]]:
    _, issues = _parse_winddown(document)
    return {(issue.path, issue.code) for issue in issues}


def test_empty_and_eight_concept_batches_are_valid_but_nine_is_rejected() -> None:
    empty, empty_issues = _parse_winddown(_document([]))
    eight, eight_issues = _parse_winddown(
        _document([_concept(title=f"Decision {index}") for index in range(8)])
    )

    assert empty == ()
    assert empty_issues == ()
    assert len(eight) == 8
    assert eight_issues == ()
    assert ("/concepts", "too_many_items") in _codes(
        _document([_concept(title=f"Decision {index}") for index in range(9)])
    )


def test_json_parser_rejects_duplicate_keys_at_every_object_depth() -> None:
    top = '{"concepts":[],"concepts":[]}'
    concept = json.dumps(_document()).replace(
        '"type": "Decision"', '"type": "Decision", "type": "Finding"'
    )
    quote = json.dumps(_document()).replace(
        '"quote": "stored source text"',
        '"quote": "stored source text", "quote": "other"',
    )

    for value in (top, concept, quote):
        assert any(issue.code == "duplicate_key" for issue in _parse_winddown(value)[1])


def test_request_must_be_json_with_exact_top_level_and_size_bound() -> None:
    assert ("/", "invalid_document") in _codes(object())
    assert ("/", "invalid_json") in _codes("{")
    assert ("/extra", "extra_field") in _codes({"concepts": [], "extra": True})
    assert ("/concepts", "missing_field") in _codes({})
    oversized = '{"concepts":[],"padding":"' + ("x" * (256 * 1024)) + '"}'
    assert ("/", "request_too_large") in _codes(oversized)


@pytest.mark.parametrize(
    ("change", "path", "code"),
    [
        ({"type": "Unknown"}, "/concepts/0/type", "invalid_choice"),
        ({"title": "   "}, "/concepts/0/title", "blank"),
        ({"title": "x" * 121}, "/concepts/0/title", "too_long"),
        (
            {
                "title": "one two three four five six seven eight nine ten eleven twelve thirteen"
            },
            "/concepts/0/title",
            "too_many_words",
        ),
        ({"description": "\n"}, "/concepts/0/description", "blank"),
        ({"description": "x" * 4001}, "/concepts/0/description", "too_long"),
        ({"tags": ["one"]}, "/concepts/0/tags", "too_few_items"),
        (
            {"tags": ["one", "two", "three", "four", "five", "six"]},
            "/concepts/0/tags",
            "too_many_items",
        ),
        ({"tags": ["one", "one"]}, "/concepts/0/tags/1", "duplicate_item"),
        ({"tags": ["valid", "UPPER"]}, "/concepts/0/tags/1", "invalid_format"),
        ({"confidence": True}, "/concepts/0/confidence", "invalid_type"),
        ({"confidence": "0.9"}, "/concepts/0/confidence", "invalid_type"),
        ({"confidence": 0.49}, "/concepts/0/confidence", "out_of_range"),
        ({"confidence": 1.01}, "/concepts/0/confidence", "out_of_range"),
        ({"quotes": []}, "/concepts/0/quotes", "too_few_items"),
        (
            {"quotes": [{"quote": str(index)} for index in range(9)]},
            "/concepts/0/quotes",
            "too_many_items",
        ),
        ({"quotes": [{"quote": "  "}]}, "/concepts/0/quotes/0/quote", "blank"),
        (
            {"quotes": [{"quote": "x" * 2001}]},
            "/concepts/0/quotes/0/quote",
            "too_long",
        ),
        (
            {"quotes": [{"quote": "x", "evidence_id": "ev"}]},
            "/concepts/0/quotes/0",
            "incomplete_locator",
        ),
        (
            {"quotes": [{"quote": "x", "evidence_id": "ev", "start": False, "end": 1}]},
            "/concepts/0/quotes/0/start",
            "invalid_type",
        ),
        (
            {"quotes": [{"quote": "x", "evidence_id": "ev", "start": 1, "end": 1}]},
            "/concepts/0/quotes/0",
            "invalid_range",
        ),
    ],
)
def test_every_field_type_range_and_shape_boundary_is_rejected(
    change: dict[str, Any], path: str, code: str
) -> None:
    assert (path, code) in _codes(_document([_concept(**change)]))


def test_exact_keys_are_required_for_concepts_and_quotes() -> None:
    missing = _concept()
    del missing["title"]
    extra = _concept(extra="no")
    quote_extra = _concept(quotes=[{"quote": "x", "extra": "no"}])

    assert ("/concepts/0/title", "missing_field") in _codes(_document([missing]))
    assert ("/concepts/0/extra", "extra_field") in _codes(_document([extra]))
    assert ("/concepts/0/quotes/0/extra", "extra_field") in _codes(
        _document([quote_extra])
    )


def test_valid_boundaries_are_trimmed_and_tags_are_canonical() -> None:
    parsed, issues = _parse_winddown(
        _document(
            [
                _concept(
                    title="  Twelve word title stays inside the exact word and character bounds  ",
                    description="  preserved statement  ",
                    tags=["z-last", "a-first", "topic/sub-topic", "x.y", "under_score"],
                    confidence=1,
                    quotes=[
                        {
                            "quote": "🙂e\u0301",
                            "evidence_id": "ev",
                            "start": 1,
                            "end": 4,
                        }
                    ],
                )
            ]
        )
    )

    assert issues == ()
    assert (
        parsed[0].title
        == "Twelve word title stays inside the exact word and character bounds"
    )
    assert parsed[0].description == "preserved statement"
    assert parsed[0].tags == (
        "a-first",
        "topic/sub-topic",
        "under_score",
        "x.y",
        "z-last",
    )
    assert parsed[0].confidence == 1.0
    assert parsed[0].quotes[0].start == 1
    assert parsed[0].quotes[0].end == 4


def test_duplicate_tags_quotes_and_canonical_concepts_are_errors() -> None:
    duplicate_quote = _concept(quotes=[{"quote": "same"}, {"quote": "same"}])
    first = _concept(tags=["z", "a"])
    second = deepcopy(first)
    second["tags"] = ["a", "z"]
    second["quotes"] = [{"quote": "different support"}]

    assert ("/concepts/0/quotes/1", "duplicate_item") in _codes(
        _document([duplicate_quote])
    )
    assert ("/concepts/1", "duplicate_concept") in _codes(_document([first, second]))


def test_one_and_eight_quotes_are_valid_and_nine_is_rejected() -> None:
    one, one_issues = _parse_winddown(_document([_concept()]))
    eight, eight_issues = _parse_winddown(
        _document(
            [_concept(quotes=[{"quote": f"quote-{index}"} for index in range(8)])]
        )
    )

    assert len(one[0].quotes) == 1
    assert one_issues == ()
    assert len(eight[0].quotes) == 8
    assert eight_issues == ()


def test_bind_document_accepts_only_one_to_eight_quote_locators() -> None:
    parsed, issues = _parse_bind_document(
        {
            "quotes": [
                {"quote": "exact"},
                {"quote": "🙂", "evidence_id": "ev", "start": 1, "end": 2},
            ]
        }
    )
    _, metadata_issues = _parse_bind_document(
        {"quotes": [{"quote": "exact"}], "title": "rewrite attempt"}
    )
    _, empty_issues = _parse_bind_document({"quotes": []})

    assert len(parsed) == 2
    assert issues == ()
    assert [(issue.path, issue.code) for issue in metadata_issues] == [
        ("/title", "extra_field")
    ]
    assert ("/quotes", "too_few_items") in {
        (issue.path, issue.code) for issue in empty_issues
    }
