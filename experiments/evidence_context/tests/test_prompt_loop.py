import json

import pytest

from experiments.evidence_context.prompt_loop.runner import run, score


def test_offline_loop_is_bounded_and_audit_cannot_select(tmp_path):
    output = tmp_path / "demo"
    report = run(output)
    ledger = json.loads((output / "ledger.json").read_text())
    assert report["calls"] == 18
    assert report["winner"]["id"] == "candidate-1"
    assert report["manifest"]["independent_holdout"] is None
    assert report["manifest"]["mode"] == "scripted_offline_demo"
    assert report["calls_without_cost"] == 18
    assert [r["phase"] for r in ledger][-4:] == ["audit"] * 4
    for row in ledger:
        if row["phase"] == "propose":
            payload = json.loads(row["messages"][1]["content"])
            assert set(payload["development_rules"]) == {"queue", "retry"}
            assert {f["case"] for f in payload["feedback"]} == {"queue", "retry"}
            assert "reopen" not in row["messages"][1]["content"]
    with pytest.raises(FileExistsError):
        run(output)


def test_failures_are_counted_and_do_not_retry_or_expose_error(tmp_path):
    calls = []

    def unavailable(messages, model):
        calls.append(messages)
        raise RuntimeError("sensitive response text")

    output = tmp_path / "failed"
    report = run(output, live=True, gateway=unavailable)
    assert len(calls) == report["calls"] == 8
    assert report["winner"]["id"] == "baseline"
    assert "sensitive response text" not in (output / "ledger.json").read_text()


def test_proxy_deliberately_does_not_claim_semantic_entailment(tmp_path):
    output = tmp_path / "demo"
    run(output)
    frozen = json.loads((output / "inputs" / "frozen.json").read_text())
    request = next(
        r for r in frozen["requests"] if r["case"] == "retry" and r["arm"] == "reference"
    )
    ledger = json.loads((output / "ledger.json").read_text())
    answer = next(r["parsed"] for r in ledger if r["case"] == "retry")
    answer["rationale"] = "Invented: B has been verified on a million production machines."
    result = score(answer, request)
    assert result["development_proxy"]  # Exhibit the proxy's blind spot, do not hide it.
    assert result["semantic_support"] == "not_automatically_measured"
    answer["citations"][0]["id"] = "unknown"
    assert not score(answer, request)["integrity"]


def test_audit_regression_is_reported_without_retuning(tmp_path):
    source = tmp_path / "source"
    run(source)
    recorded = iter(json.loads((source / "ledger.json").read_text()))

    def replay(messages, model):
        row = next(recorded)
        answer = row["parsed"]
        if row["phase"] == "audit" and row["candidate"] == "candidate-1":
            answer["recommendation"] = "A"
        return {"text": json.dumps(answer)}

    report = run(tmp_path / "replay", live=True, gateway=replay)
    assert report["winner"]["id"] == "candidate-1"
    assert report["audit"]["candidate-1"]["proxy_passes"] == 0
    assert report["calls"] == 18
    assert report["promotion"] == "not_authorized_by_this_development_experiment"


def test_malformed_proposals_are_rejected(tmp_path):
    def bad_proposal(messages, model):
        return {"text": json.dumps({"amendment": ["invalid type"]})}

    output = tmp_path / "bad"
    report = run(output, live=True, gateway=bad_proposal)
    assert report["calls"] == 8
    assert len(report["candidates"]) == 1
    ledger = json.loads((output / "ledger.json").read_text())
    assert all(r["proposal_status"] == "rejected" for r in ledger if r["phase"] == "propose")
