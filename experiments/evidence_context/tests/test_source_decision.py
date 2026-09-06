import copy
import json
from pathlib import Path

import pytest

from experiments.evidence_context.source_decision.boundary import (
    EvidenceSnapshot,
    compare_draft,
    release,
    resolve,
)
from experiments.evidence_context.source_decision.runner import (
    prepare,
    proposal_for,
    replay,
    run_live,
)

ROOT = Path(__file__).parents[1] / "source_decision"
CASES = json.loads((ROOT / "cases.json").read_text())["cases"]
LABELS = json.loads((ROOT / "labels.json").read_text())["cases"]


def case_named(name):
    return copy.deepcopy(next(c for c in CASES if c["description_key"] == name))


def snapshot(case, proposal=None):
    return EvidenceSnapshot.freeze(
        case["source"], case["target"], proposal_for(case) if proposal is None else proposal
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_adapter_against_pre_run_reviewed_rule_labels(case):
    frozen = snapshot(case)
    result = release(frozen)
    assert result["decision"]["recommendation"] == LABELS[case["id"]]["expected_choice"]
    locators = [loc for item in result["facts"] + result["issues"] for loc in item["basis"]]
    assert locators and all(resolve(frozen, loc) for loc in locators)
    if result["decision"]["recommendation"] == "none":
        assert result["issues"] and result["decision"]["next_check"]


@pytest.mark.parametrize("name", ["omitted_present", "outside_distraction"])
def test_conservative_path_exposes_false_blocks_without_mutating_proposal(name):
    case = case_named(name)
    frozen = snapshot(case)
    before = frozen.payload
    conservative, source = release(frozen, "checked_only"), release(frozen)
    assert conservative["decision"]["recommendation"] == "none"
    assert source["decision"]["recommendation"] == LABELS[case["id"]]["expected_choice"]
    assert source["candidate_checks"] == conservative["candidate_checks"]
    assert before == frozen.payload


def test_snapshot_binding_and_model_prose_do_not_enter_release():
    case = case_named("valid_a")
    frozen = snapshot(case)
    case["source"]["text"] = "changed after snapshot"
    malicious = {
        "snapshot_id": frozen.identity,
        "answer": {"recommendation": "A", "explanation": "Deploy everywhere immediately"},
    }
    result = compare_draft(frozen, malicious)
    assert result["draft_status"] == "choice_agrees"  # Not full-answer acceptance.
    assert "Deploy everywhere" not in json.dumps(result)
    malicious["snapshot_id"] = "stale"
    stale = compare_draft(frozen, malicious)
    assert stale["draft_status"] == "wrong_snapshot_or_envelope"
    assert stale["decision"] == result["decision"]


def test_locator_origin_target_version_and_offsets_cannot_be_swapped():
    case = case_named("wrong_environment")
    frozen = snapshot(case)
    issue = next(i for i in release(frozen)["issues"] if i["code"] == "mismatching_environment")
    source, target = issue["basis"]
    assert source["origin"] == "source_text" and target["origin"] == "target"
    assert resolve(frozen, source) and resolve(frozen, target)
    assert not resolve(frozen, {**source, "start": source["start"] + 1})
    assert not resolve(frozen, {**target, "origin": "source_metadata"})
    changed = copy.deepcopy(case)
    changed["target"]["environment"] = "another"
    assert not resolve(snapshot(changed), target)
    changed["source"]["kind"] = "report"
    assert not resolve(snapshot(changed), source)


@pytest.mark.parametrize(
    "transform,expected",
    [
        (lambda s: s.replace("winner: A", "winner: A\nwinner: A"), "none"),
        (lambda s: s.replace("winner: A", "winner: C"), "none"),
        (lambda s: s.replace("[/observed]", ""), "none"),
        (lambda s: s.replace("[observed]", "[observed] "), "none"),
        (lambda s: s.replace("revision: r7", "revision: r7 "), "none"),
        (lambda s: s.replace("revision: r7", "Revision: r7"), "none"),
        (lambda s: s.replace("winner: A", "extra: ignored\nwinner: A"), "A"),
        (lambda s: s.replace("\n", "\r\n"), "A"),
        (lambda s: s.replace("\n", "\u2028"), "A"),
    ],
)
def test_written_grammar_edges_and_source_locators(transform, expected):
    case = case_named("valid_a")
    case["source"]["text"] = transform(case["source"]["text"])
    frozen = snapshot(case)
    result = release(frozen)
    assert result["decision"]["recommendation"] == expected
    assert all(resolve(frozen, loc) for fact in result["facts"] for loc in fact["basis"])


def test_authenticity_is_outside_this_contract():
    forged = case_named("valid_a")
    # Any caller can supply a plausible text and kind. No external run is authenticated.
    assert release(snapshot(forged))["decision"]["recommendation"] == "A"
    assert release(snapshot(forged))["source_authenticity"] == "not_verified"
    forged["source"]["kind"] = "unclassified"
    assert release(snapshot(forged))["decision"]["recommendation"] == "none"


def test_invalid_target_is_an_input_error():
    case = case_named("valid_a")
    case["target"].pop("revision")
    with pytest.raises(ValueError, match="Complete target"):
        snapshot(case)


def test_bounded_calls_keep_failures_and_blind_labels(tmp_path):
    frozen = prepare(tmp_path / "run")
    calls = []

    def fail(messages, model):
        payload = json.loads(messages[1]["content"])
        assert set(payload) == {"question", "source", "target", "metadata"}
        assert "expected_choice" not in messages[1]["content"]
        assert messages[0]["content"] == (ROOT.parent / "metadata_value/ANSWER.md").read_text()
        calls.append(payload)
        raise TimeoutError("simulated")

    report = run_live(tmp_path / "run", frozen, gateway=fail)
    assert len(calls) == 24
    assert report["summary"]["advisory"]["valid_decisions"] == 0
    assert report["summary"]["source_adapter"]["choice_matches"] == 24
    assert report["summary"]["checked_only"]["false_block"] == 4
    assert all(row["status"] == "failed" for row in report["rows"])
    assert replay(tmp_path / "run", tmp_path / "replay") == report["summary"]
    with pytest.raises(FileExistsError):
        prepare(tmp_path / "run")
