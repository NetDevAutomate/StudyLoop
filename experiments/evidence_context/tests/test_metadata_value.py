import copy
import json
from pathlib import Path

import pytest

from experiments.evidence_context.metadata_value.runner import inject, prepare, run_live
from experiments.evidence_context.metadata_value.verify import (
    FIELDS,
    assess_answer,
    declarations,
    reference_extraction,
    verify,
)

ROOT = Path(__file__).parents[1] / "metadata_value"
CASES = {c["id"]: c for c in json.loads((ROOT / "cases.json").read_text())["cases"]}


@pytest.mark.parametrize("name", list(CASES))
def test_reference_metadata_and_declared_faults(name):
    case = CASES[name]
    reference = reference_extraction(case["source"]["text"])
    candidate = inject(reference, case["injected_fault"])
    checked = verify(case["source"]["text"], candidate)
    assert set(checked) == set(FIELDS)
    if case["injected_fault"]:
        field = case["injected_fault"]["field"]
        assert checked[field]["status"] == "rejected"
        assert checked[field]["value"] is None
    else:
        assert all(v["status"] == "matched" for v in checked.values())
    assert reference == reference_extraction(case["source"]["text"])


def test_quote_presence_is_not_field_support():
    text = CASES["clean_matching"]["source"]["text"]
    candidate = reference_extraction(text)
    candidate["revision"] = {"value": "r2", "quote": "winner: B"}
    assert candidate["revision"]["quote"] in text
    assert verify(text, candidate)["revision"]["status"] == "rejected"
    candidate["revision"] = {"value": "r3", "quote": "revision: r2"}
    assert verify(text, candidate)["revision"]["status"] == "rejected"


def test_outside_block_and_duplicate_declarations_are_not_proof():
    text = CASES["missing_revision"]["source"]["text"] + "\nrevision: r2"
    candidate = reference_extraction(text)
    candidate["revision"] = {"value": "r2", "quote": "revision: r2"}
    assert verify(text, candidate)["revision"]["status"] == "rejected"
    text = CASES["duplicate_revision"]["source"]["text"]
    assert reference_extraction(text)["revision"]["value"] is None
    for malformed in ("", "[/observed]\n[observed]", text + "\n[observed]"):
        with pytest.raises(ValueError):
            declarations(malformed)
        assert all(v["status"] == "rejected" for v in verify(malformed, candidate).values())


def test_omission_is_not_silently_filled_and_malformed_proposal_rejected():
    text = CASES["clean_matching"]["source"]["text"]
    candidate = reference_extraction(text)
    candidate["revision"] = {"value": None, "quote": None}
    assert verify(text, candidate)["revision"]["reason"] == "extractor_omitted_present_field"
    assert verify(text, candidate)["revision"]["value"] is None
    candidate["revision"] = {"value": "r2", "quote": None}
    assert all(v["status"] == "rejected" for v in verify(text, candidate).values())


def test_authenticity_and_answer_entailment_remain_unmeasured():
    case = copy.deepcopy(CASES["clean_matching"])
    # Same text could have been fabricated; string correspondence cannot detect that.
    assert all(
        v["status"] == "matched"
        for v in verify(
            case["source"]["text"], reference_extraction(case["source"]["text"])
        ).values()
    )
    answer = {
        "recommendation": "B",
        "explanation": "Proven universally on real production systems.",
        "citations": [{"quote": "winner: B", "supports": "Universal superiority"}],
        "next_check": "None",
    }
    checks = assess_answer(answer, case)
    assert checks["choice_matches"] and checks["citations_locatable"]
    assert checks["explanation_entailment"] == "not_automatically_measured"


def test_bounded_failures_and_extractor_target_isolation(tmp_path):
    output = tmp_path / "probe"
    frozen = prepare(output)
    requests = []

    def fail(messages, model):
        requests.append(messages)
        raise RuntimeError("sensitive detail")

    report = run_live(output, frozen, gateway=fail)
    assert len(requests) == 64
    extracts = [r for r in report["rows"] if r["phase"] == "extract"]
    assert len(extracts) == 8
    for row in extracts:
        payload = json.loads(row["messages"][1]["content"])
        assert set(payload) == {"id", "kind", "text"}
    assert "sensitive detail" not in (output / "results.json").read_text()
    for case in frozen["cases"]:
        rows = [r for r in report["rows"] if r["case"] == case["id"] and r["phase"] == "answer"]
        assert len(rows) == (8 if case["injected_fault"] else 6)
        payloads = [json.loads(r["messages"][1]["content"]) for r in rows]
        assert all(
            p["source"] == case["source"] and p["target"] == case["target"] for p in payloads
        )
        assert len({r["messages"][0]["content"] for r in rows}) == 1
    with pytest.raises(FileExistsError):
        run_live(output, frozen, gateway=fail)


def test_matched_metadata_is_not_target_applicability_or_artifact_authenticity():
    case = CASES["wrong_revision"]
    checked = verify(case["source"]["text"], reference_extraction(case["source"]["text"]))
    assert checked["revision"]["status"] == "matched"
    assert checked["revision"]["value"] != case["target"]["revision"]
    report = CASES["report_only"]
    assert all(
        v["status"] == "matched"
        for v in verify(
            report["source"]["text"], reference_extraction(report["source"]["text"])
        ).values()
    )
    assert report["source"]["kind"] == "report" and report["expected_choice"] == "none"
