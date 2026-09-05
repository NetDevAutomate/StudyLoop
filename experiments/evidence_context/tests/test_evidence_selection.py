"""Boundary and preservation tests for the controlled evidence replacement experiment."""

import json

import pytest

from experiments.evidence_context.evidence_selection.runner import (
    prepare,
    project_item,
    reference_pack,
    run_live,
)


class CharacterTokenizer:
    def encode(self, text, **kwargs):
        return list(text)


def record(rid, **changes):
    return {
        "id": rid,
        "text": "reported result",
        "role": "assistant",
        "at": "2026-01-01",
        "kind": "conversation_report",
        "project": "personal",
        **changes,
    }


def test_required_evidence_is_never_silently_truncated():
    catalog = {"result": record("result", text="x" * 2000), "noise": record("noise")}
    q = {"project": "personal", "asof": "2027"}
    with pytest.raises(ValueError, match="Required evidence"):
        reference_pack(["result"], ["noise"], catalog, q, CharacterTokenizer())
    catalog["result"]["text"] = "The cleanup was reported as passed."
    pack = reference_pack(["result"], ["noise", "result"], catalog, q, CharacterTokenizer(), cap=1)
    assert [r["id"] for r in pack] == ["result"]


@pytest.mark.parametrize("changes", [{"project": "work"}, {"at": "2027"}])
def test_reference_or_filler_cannot_bypass_scope_or_time(changes):
    catalog = {"safe": record("safe"), "bad": record("bad", **changes)}
    q = {"project": "personal", "asof": "2027"}
    with pytest.raises(ValueError, match="Ineligible"):
        reference_pack(["safe"], ["bad"], catalog, q, CharacterTokenizer())


def prepare_fixture(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    records = [record("plan", text="We plan to check cleanup."), record("result")]
    questions = [
        {"id": f"Q{i}", "query": "What was checked?", "project": "personal", "asof": "2027"}
        for i in range(1, 5)
    ]
    values = {
        "corpus.json": {"records": records, "questions": questions},
        "frozen-trial.json": {"prompt": "unchanged prompt", "model": "fake"},
        "config.json": {},
        "labels.json": {"groups": {q["id"]: [["result"]] for q in questions}},
        "retrieval.json": [
            {
                "question": q["id"],
                "arm": "combined",
                "ids": ["plan"],
                "pack": [project_item(records[0])],
            }
            for q in questions
        ],
    }
    for name, value in values.items():
        (source / name).write_text(json.dumps(value))
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {"reference_ids": {q["id"]: ["result"] if q["id"] != "Q4" else [] for q in questions}}
        )
    )
    output = tmp_path / "run"
    frozen = prepare(source, spec, output, CharacterTokenizer())
    return output, frozen


def test_original_is_exact_and_negative_filler_control_is_identical(tmp_path):
    _, frozen = prepare_fixture(tmp_path)
    assert frozen["prompt"] == "unchanged prompt"
    assert len(frozen["requests"]) == 24
    groups = {r["arm"]: r for r in frozen["requests"] if r["question"] == "Q4"}
    assert groups["reviewed_only"]["pack"] == []
    assert groups["original"]["pack"] == groups["reviewed_plus_original"]["pack"]


def test_bundle_tampering_blocks_before_any_gateway_call(tmp_path, monkeypatch):
    output, _ = prepare_fixture(tmp_path)
    monkeypatch.setattr(
        "experiments.evidence_context.evidence_selection.runner.call_gateway",
        lambda *args: pytest.fail("Gateway must not be invoked"),
    )
    p = output / "frozen.json"
    p.write_text(p.read_text() + " ")
    with pytest.raises(ValueError, match="bundle changed"):
        run_live(output)
    assert not (output / "answers.jsonl").exists()


def test_failed_answers_retained_and_paid_run_not_repeated(tmp_path, monkeypatch):
    output, _ = prepare_fixture(tmp_path)
    calls = []

    def gateway(messages, model):
        calls.append(model)
        assert messages[0]["content"] == "unchanged prompt"
        assert set(json.loads(messages[1]["content"])) == {"question", "evidence"}
        return {"text": "malformed response", "cost_usd": 0}

    monkeypatch.setattr(
        "experiments.evidence_context.evidence_selection.runner.call_gateway", gateway
    )
    rows = run_live(output)
    assert len(calls) == 24
    assert all(r["status"] == "failed" and r["text"] == "malformed response" for r in rows)
    with pytest.raises(FileExistsError):
        run_live(output)
    assert len(calls) == 24
