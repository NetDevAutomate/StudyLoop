"""Arbitration runner contracts; these tests do not judge model reasoning."""

import json

import pytest

from experiments.evidence_context.arbitration_lab.runner import assess, prepare


def answer(**changes):
    return {
        "conflict_kind": "unresolved",
        "recommendation": "insufficient",
        "evidence_basis": "insufficient",
        "rationale": "Reports disagree without a discriminating test.",
        "alternative": "Neither supported.",
        "citations": [{"id": "E1", "supports": "Unmeasured advice"}],
        "uncertainty": "No measurements.",
        "next_check": "Benchmark both under the same workload.",
        **changes,
    }


def test_prepared_conditions_are_balanced_and_labels_not_sent(tmp_path):
    frozen = prepare(tmp_path / "run")
    assert len(frozen["requests"]) == 12
    assert {r["arm"] for r in frozen["requests"]} == {"keyword", "relationships", "reference"}
    assert len({r["messages"][0]["content"] for r in frozen["requests"]}) == 1
    for r in frozen["requests"]:
        payload = json.loads(r["messages"][1]["content"])
        assert set(payload) == {"question", "constraints", "evidence"}
        assert len(r["messages"][1]["content"].encode()) <= 8000
        assert len(r["context"]) == (
            1 if r["arm"] == "keyword" else 3 if r["case"] == "storage" else 2
        )
    blind = json.loads((tmp_path / "run/blind-review-input.json").read_text())
    assert all(set(r) == {"id", "messages"} for r in blind)


def test_unknown_citations_are_flagged():
    result = assess(answer(), [], {"recommendation": "insufficient"})
    assert result["unknown_citations"] == ["E1"]
    assert result["semantic_support"] == "human_review_required"


def test_agent_report_cannot_satisfy_artifact_gate():
    result = assess(
        answer(evidence_basis="artifact_supported"), [{"id": "E1", "kind": "agent_report"}], {}
    )
    assert result["artifact_basis_without_artifact_citation"]


def test_artifact_citation_is_not_automatically_semantic_validation():
    result = assess(
        answer(evidence_basis="artifact_supported"), [{"id": "E1", "kind": "test_artifact"}], {}
    )
    assert not result["artifact_basis_without_artifact_citation"]
    assert result["semantic_support"] == "human_review_required"


@pytest.mark.parametrize(
    "changes", [{"recommendation": "C"}, {"citations": "E1"}, {"uncertainty": ""}]
)
def test_invalid_schema_rejected(changes):
    with pytest.raises(ValueError):
        assess(answer(**changes), [], {})


def test_demo_refuses_overwrite(tmp_path):
    output = tmp_path / "run"
    prepare(output)
    before = (output / "frozen.json").read_bytes()
    with pytest.raises(FileExistsError):
        prepare(output)
    assert (output / "frozen.json").read_bytes() == before


def test_too_small_reference_budget_is_not_silently_truncated(tmp_path):
    with pytest.raises(ValueError, match=r"budget|ceiling"):
        prepare(tmp_path / "run", budget=20)


def test_prompt_revision_changes_only_system_steer_not_context_or_labels(tmp_path):
    first = prepare(tmp_path / "v1", prompt_version="v1")
    second = prepare(tmp_path / "v2", prompt_version="v2")
    assert first["dataset_sha256"] == second["dataset_sha256"]
    assert first["prompt_sha256"] != second["prompt_sha256"]
    for a, b in zip(first["requests"], second["requests"], strict=True):
        assert a["messages"][1] == b["messages"][1]
        assert a["expected"] == b["expected"]
        assert a["id"] == b["id"]


def test_unknown_prompt_version_refused_before_output_creation(tmp_path):
    with pytest.raises(ValueError, match="prompt version"):
        prepare(tmp_path / "bad", prompt_version="unknown")
    assert not (tmp_path / "bad").exists()
