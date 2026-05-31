"""Unit tests for the fuzzy concept matcher in eval_runner (pure Python, zero API).

The P6 hill-climber Goodharted because the scorer used exact (topic, concept)
string equality: 'graphrag/embedding' did not match the human label
'graphrag/lightrag-embedding-pipeline', pinning recall at a floor. These tests
lock in the fuzzy matcher that fixes it, using the ACTUAL mismatch pairs
observed in the overnight run.
"""

from __future__ import annotations

from studyloop.extractors import ExtractorResult
from studyloop.extractors.eval_runner import (
    _concepts_match,
    _match_pairs,
    score_session,
)


# --- _concepts_match: real mismatch pairs from the overnight run -------------


def test_containment_match_embedding() -> None:
    # extractor said 'embedding'; human labelled 'lightrag-embedding-pipeline'
    assert _concepts_match("embedding", "lightrag-embedding-pipeline")


def test_containment_match_abc() -> None:
    # extractor said 'abc'; human labelled 'abc-vs-protocol'
    assert _concepts_match("abc", "abc-vs-protocol")


def test_stopword_vs_ignored() -> None:
    # 'vs' is a stopword — 'abc-vs-protocol' tokens are {abc, protocol}
    assert _concepts_match("abc-protocol", "abc-vs-protocol")


def test_unrelated_concepts_do_not_match() -> None:
    assert not _concepts_match("outer-join", "decorators")
    assert not _concepts_match("type-hint-syntax", "lakeformation-service-linked-role")


def test_partial_overlap_below_threshold_rejected() -> None:
    # one shared token out of many on each side → below both thresholds
    assert not _concepts_match("python-async-await-coroutines", "java-threads-async")


# --- _match_pairs: greedy bipartite, no double-counting ----------------------


def test_match_pairs_counts_fuzzy_hits() -> None:
    expected = [("graphrag", "lightrag-embedding-pipeline"), ("python", "decorators")]
    predicted = [("graphrag", "embedding"), ("python", "decorators")]
    matched, unmatched_exp, unmatched_pred = _match_pairs(expected, predicted)
    assert matched == 2
    assert unmatched_exp == []
    assert unmatched_pred == []


def test_match_pairs_topic_must_agree() -> None:
    # same concept token but different topic → no match
    expected = [("python", "embedding")]
    predicted = [("graphrag", "embedding")]
    matched, ue, up = _match_pairs(expected, predicted)
    assert matched == 0
    assert ue == [("python", "embedding")]
    assert up == [("graphrag", "embedding")]


def test_match_pairs_no_double_count() -> None:
    # two predictions fuzzily match one expected → only one TP, one leftover FP
    expected = [("graphrag", "embedding-pipeline")]
    predicted = [("graphrag", "embedding"), ("graphrag", "embedding-dimension")]
    matched, ue, up = _match_pairs(expected, predicted)
    assert matched == 1
    assert ue == []
    assert len(up) == 1  # the second prediction is an unmatched FP


# --- score_session: recall now moves on fuzzy hits ---------------------------


def test_score_session_fuzzy_recall() -> None:
    entry = {
        "session_id": "s1",
        "is_negative": False,
        "expected_topics": [
            {"topic": "graphrag", "concept": "lightrag-embedding-pipeline", "confidence": "struggling"},
        ],
    }
    results = [ExtractorResult("graphrag", "embedding", "struggling")]
    s = score_session(entry, results)
    assert s.tp == 1  # would have been 0 under exact matching
    assert s.fn == 0
    assert s.fp == 0


def test_score_session_negative_unchanged() -> None:
    entry = {"session_id": "n1", "is_negative": True, "expected_topics": []}
    # any output on a negative is a false positive
    s = score_session(entry, [ExtractorResult("python", "abc", "struggling")])
    assert s.fp_on_negative == 1
    assert s.jaccard == 0.0
