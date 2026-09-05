"""Scorer correctness is deliberately tested separately from real efficacy."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from experiments.evidence_context.retrieval_eval.evaluate import build, run, score, validate


@pytest.fixture
def data():
    return json.loads((Path(__file__).parents[1] / "retrieval_eval/synthetic.json").read_text())


def test_demo_measures_engineered_gain_and_shuffled_control(data, tmp_path):
    report = run(data, tmp_path / "run")
    by_arm = {r["arm"]: r for r in report["results"] if r["case_id"] == "needs-counterevidence"}
    assert by_arm["keyword"]["required_span_recall"] == 0.5
    assert by_arm["relationships"]["required_span_recall"] == 1
    assert by_arm["shuffled"]["required_span_recall"] == 0.5
    assert by_arm["shuffled"]["passage_precision"] == 0.5
    assert all(
        r["invalid_citations"] == 0 and r["scope_or_time_violations"] == 0
        for r in report["results"]
    )
    assert all(r["bytes"] <= 8000 for r in report["results"])
    assert report["conclusion"] == "Scoring demonstration only"


def test_unanswerable_has_no_fabricated_recall_or_abstention_score(data, tmp_path):
    results = run(data, tmp_path / "run")["results"]
    empty = [r for r in results if r["case_id"] == "no-evidence"]
    assert all(r["required_span_recall"] is None for r in empty)
    assert all(r["all_required_evidence_present"] is None for r in empty)
    assert all(r["abstention_quality"] == "not_measured" for r in empty)


def test_source_found_but_required_sentence_not_returned_does_not_count(data, tmp_path):
    store, versions, _ = build(tmp_path / "store.db", data, False, 42)
    try:
        case = data["cases"][0]
        pack = store.retrieve(case["query"], project="demo", scope="personal", excerpt_chars=10)
        texts = {r["key"]: r["record"]["content"] for r in data["records"]}
        metrics = score(store, pack, case, versions, texts)
        assert metrics["passage_recall"] == 0.5
        assert metrics["required_span_recall"] == 0
    finally:
        store.close()


def test_corrupt_citation_counted(data, tmp_path):
    store, versions, _ = build(tmp_path / "store.db", data, False, 42)
    try:
        pack = store.retrieve("deploypolicy", project="demo", scope="personal")
        item = pack.evidence[0]
        corrupted = replace(item, citation=replace(item.citation, text="fabricated"))
        metrics = score(
            store,
            replace(pack, evidence=(corrupted,)),
            data["cases"][0],
            versions,
            {r["key"]: r["record"]["content"] for r in data["records"]},
        )
        assert metrics["invalid_citations"] == 1
    finally:
        store.close()


@pytest.mark.parametrize("mutation", ["scope", "span", "duplicate", "future"])
def test_invalid_labels_rejected(data, mutation):
    if mutation == "scope":
        data["cases"][0]["relevant"].append("work")
    elif mutation == "span":
        data["cases"][0]["required"][0]["text"] = "not in source"
    elif mutation == "duplicate":
        data["records"].append(data["records"][0])
    else:
        data["cases"][0]["as_of"] = "2025-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        validate(data)


def test_holdout_overlap_rejected(data):
    data.update(
        kind="holdout_candidate",
        label_reviewer="fixture",
        split_note="test",
        development_lineages=["synthetic-demo"],
    )
    with pytest.raises(ValueError, match="overlap"):
        validate(data)


def test_unjudged_precision_is_not_reported(data, tmp_path):
    data["cases"][0]["labels_complete"] = False
    rows = run(data, tmp_path / "run")["results"]
    assert all(
        r["passage_precision"] is None for r in rows if r["case_id"] == "needs-counterevidence"
    )


def test_replay_preserves_scores_and_inputs_but_does_not_fake_timing(data, tmp_path):
    one, two = run(data, tmp_path / "one"), run(data, tmp_path / "two")
    assert one["manifest"] == two["manifest"]
    assert one["paired_differences"] == two["paired_differences"]
    assert json.loads((tmp_path / "one/frozen-input.json").read_text()) == data
    with pytest.raises(FileExistsError):
        run(data, tmp_path / "one")


def test_future_edge_cannot_raise_recall(data, tmp_path):
    data["edges"][0]["at"] = "2026-02-01T00:00:00Z"
    report = run(data, tmp_path / "run")
    row = next(
        r
        for r in report["results"]
        if r["case_id"] == "needs-counterevidence" and r["arm"] == "relationships"
    )
    assert row["required_span_recall"] == 0.5
    assert row["integrity_pass"]


def test_scorer_rejects_forged_future_edge_even_with_valid_old_passages(data, tmp_path):
    store, versions, _ = build(tmp_path / "store.db", data, False, 42)
    try:
        pack = store.retrieve(
            "deploypolicy", project="demo", scope="personal", use_relationships=True
        )
        edge = {**pack.relationships[0], "asserted_at": "2026-02-01T00:00:00Z"}
        metrics = score(
            store,
            replace(pack, relationships=(edge,)),
            data["cases"][0],
            versions,
            {r["key"]: r["record"]["content"] for r in data["records"]},
        )
        assert metrics["edge_violations"] == 1
        assert not metrics["integrity_pass"]
    finally:
        store.close()


def test_unanswerable_with_irrelevant_matches_is_not_empty_context(data, tmp_path):
    data["cases"][2]["query"] = "holiday"
    rows = run(data, tmp_path / "run")["results"]
    row = next(r for r in rows if r["case_id"] == "no-evidence" and r["arm"] == "keyword")
    assert row["unanswerable_retrieval_outcome"] == "contains_labelled_irrelevant_evidence"
    assert row["abstention_quality"] == "not_measured"


def test_control_differences_are_explicit(data, tmp_path):
    row = run(data, tmp_path / "run")["paired_differences"][0]
    assert row["shuffled_vs_keyword_span_recall_delta"] == 0
    assert row["relationships_vs_shuffled_span_recall_delta"] == 0.5
