import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from experiments.evidence_context.acceptance_gate.gate import Snapshot, accept
from experiments.evidence_context.acceptance_gate.probes import cases, live_cases, offline
from experiments.evidence_context.acceptance_gate.runner import prepare, run_live
from experiments.evidence_context.decision_contract.policy import derive


def test_offline_controls_and_challenges():
    rows = offline()
    assert len(rows) == 18
    assert all(r["expectation_met"] for r in rows)
    forged = next(r for r in rows if r["boundary"] == "prose")
    assert "FABRICATED" not in json.dumps(forged["result"]["released_answer"])
    blind = next(r for r in rows if r["boundary"] == "authenticity_not_checked")
    assert blind["result"]["status"] == "draft_agrees"  # Explicit unresolved trust boundary.


def test_snapshot_is_copied_and_bound_to_policy_and_contents():
    case = copy.deepcopy(cases()["matching_artifact"])
    snapshot = Snapshot.freeze(case)
    equivalent = Snapshot.freeze(dict(reversed(list(case.items()))))
    assert snapshot.identity == equivalent.identity
    case["sources"][-1]["scope"]["revision"] = "r99"
    assert snapshot.case()["sources"][-1]["scope"]["revision"] == "r2"
    changed = Snapshot.freeze(case)
    assert snapshot.identity != changed.identity
    with pytest.raises(FrozenInstanceError):
        snapshot.payload = "changed"
    result = accept(changed, {"snapshot_id": snapshot.identity, "answer": derive(snapshot.case())})
    assert result["reasons"] == ["stale_or_wrong_snapshot"]
    data = json.loads(snapshot.payload)
    data["policy_digest"] = "other policy"
    with pytest.raises(ValueError):
        accept(Snapshot(json.dumps(data)), {})


def test_gate_never_depends_on_case_names_or_expected_label_files():
    case = copy.deepcopy(cases()["unknown_revision"])
    original = Snapshot.freeze(case)
    answer = derive(case)
    first = accept(original, {"snapshot_id": original.identity, "answer": answer})
    case["id"] = "entirely-unseen-name"
    renamed = Snapshot.freeze(case)
    second = accept(renamed, {"snapshot_id": renamed.identity, "answer": answer})
    assert first["released_answer"] == second["released_answer"]
    assert first["status"] == second["status"] == "draft_agrees"


def test_all_model_free_text_is_isolated():
    case = cases()["matching_artifact"]
    snapshot = Snapshot.freeze(case)
    answer = derive(case)
    sentinel = "UNVERIFIED MODEL TEXT: universally proven"
    for row in answer["source_assessments"]:
        row["reason"] = sentinel
    for key in ("explanation", "limitation", "next_check"):
        answer["decision"][key] = sentinel
    result = accept(snapshot, {"snapshot_id": snapshot.identity, "answer": answer})
    assert result["status"] == "draft_agrees"
    assert sentinel not in json.dumps(result)
    assert result["released_answer"] == derive(case)


def test_correct_classification_cannot_hide_bad_decision_or_duplicates():
    case = cases()["matching_artifact"]
    snapshot = Snapshot.freeze(case)
    answer = derive(case)
    answer["decision"]["recommendation"] = "A"
    result = accept(snapshot, {"snapshot_id": snapshot.identity, "answer": answer})
    assert "decision_mismatch" in result["reasons"]
    answer = derive(case)
    answer["decision"]["basis_ids"] *= 2
    assert (
        accept(snapshot, {"snapshot_id": snapshot.identity, "answer": answer})["status"]
        == "draft_diverges"
    )


def test_empty_sources_and_invalid_target_fail_without_guessing():
    case = copy.deepcopy(cases()["reports_only"])
    case["sources"] = []
    snapshot = Snapshot.freeze(case)
    result = accept(snapshot, {"snapshot_id": snapshot.identity, "answer": derive(case)})
    assert result["status"] == "draft_agrees"
    assert result["released_answer"]["decision"]["recommendation"] == "none"
    case["target"].pop("revision")
    with pytest.raises(ValueError):
        Snapshot.freeze(case)


def test_reference_against_separately_written_pre_run_expectations():
    path = Path(__file__).parents[1] / "acceptance_gate/live-expectations.json"
    expected = json.loads(path.read_text())
    for case in live_cases():
        answer = derive(case)
        label = expected[case["id"]]
        for key in ("sufficiency", "recommendation"):
            assert answer["decision"][key] == label[key]
        for row in answer["source_assessments"]:
            if row["id"] in label:
                assert row["applicability"] == label[row["id"]]


def test_replay_and_bounded_transport_failures(tmp_path):
    output = tmp_path / "probe"
    frozen = prepare(output)
    replay = json.loads((output / "replay.json").read_text())
    unknown = next(r for r in replay if r["case"] == "unknown_revision")
    assert unknown["gate"]["status"] == "draft_diverges"
    assert unknown["gate"]["released_answer"]["decision"]["recommendation"] == "none"
    calls = []

    def fail(messages, model):
        calls.append(1)
        raise RuntimeError("sensitive transport detail")

    report = run_live(output, frozen, gateway=fail)
    assert len(calls) == 12
    assert all(r["gate"]["status"] == "draft_diverges" for r in report["rows"])
    assert "sensitive transport detail" not in (output / "results.json").read_text()
    with pytest.raises(FileExistsError):
        run_live(output, frozen, gateway=fail)
    with pytest.raises(FileExistsError):
        prepare(output)
