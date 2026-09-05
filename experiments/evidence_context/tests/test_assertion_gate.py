"""Typed evidence release, declared trust gaps, and frozen trial boundaries."""

import copy
import json

import pytest

from experiments.evidence_context.assertion_gate.fixtures import assertion, cases
from experiments.evidence_context.assertion_gate.gate import release
from experiments.evidence_context.assertion_gate.probes import claim, run
from experiments.evidence_context.assertion_gate.runner import live, payload, prepare


def draft(*claims):
    return {"claims": list(claims), "answer": "COMPLETE AND VERIFIED<script>oops</script>"}


def test_controls_and_deliberate_annotation_failures_are_visible():
    rows = run()
    assert len(rows) == 20
    assert all(r["matches"] for r in rows if not r["trust_gap"])
    gaps = [r for r in rows if r["trust_gap"]]
    assert len(gaps) == 2 and all(not r["matches"] and r["actual"] for r in gaps)
    assert not any(r["advisory_prose_leaked"] for r in rows)


def test_mixed_claims_preserve_useful_report_and_block_overclaim():
    case = cases()[0]
    result = release(
        draft(claim(case["assertions"][0]), claim(case["assertions"][1], state="completed")), case
    )
    assert [r["assertion_id"] for r in result["accepted"]] == ["E1"]
    assert result["blocked"][0]["reason"] == "state_mismatch"
    assert "conversation report" in result["text"]
    assert "VERIFIED" not in result["text"]
    assert "does not verify" in result["qualification"]


@pytest.mark.parametrize("state", ["planned", "in_progress", "completed", "unknown"])
def test_each_state_retains_attribution_without_promoting_certainty(state):
    case = cases()[0]
    case["assertions"] = [assertion("E1", "Fixture evidence", "parking.cleanup", state)]
    result = release(draft(claim(case["assertions"][0])), case)
    assert result["accepted"][0]["state"] == state
    assert "conversation report" in result["text"]
    assert "COMPLETE AND VERIFIED" not in result["text"]


@pytest.mark.parametrize("pointer", ["E404", "E1", [], False])
def test_malformed_correction_is_not_silently_treated_as_valid(pointer):
    case = cases()[0]
    case["assertions"][0]["superseded_by"] = pointer
    result = release(draft(claim(case["assertions"][0])), case)
    assert not result["accepted"]
    assert result["blocked"][0]["reason"] == "invalid_supersession"


def test_duplicate_assertion_identity_is_ambiguous():
    case = cases()[0]
    case["assertions"].append(copy.deepcopy(case["assertions"][0]))
    result = release(draft(claim(case["assertions"][0])), case)
    assert result["blocked"][0]["reason"] == "unknown_or_ambiguous_assertion"


@pytest.mark.parametrize("value", [True, -1, 999, "0"])
def test_source_span_must_be_exact_integer_in_bounds(value):
    case = cases()[0]
    case["assertions"][0]["start"] = value
    result = release(draft(claim(case["assertions"][0])), case)
    assert result["blocked"][0]["reason"] == "source_binding_failed"


def test_identical_text_control_really_omits_the_distinguishing_information():
    observed, reported = cases()[2:4]
    assert payload(observed, "raw") == payload(reported, "raw")
    assert payload(observed, "annotated") != payload(reported, "annotated")
    assert "expected_ids" not in json.dumps(payload(observed, "annotated"))


def test_unknown_and_superseding_correction_can_be_useful():
    case = cases()[7]
    result = release(draft(*(claim(r) for r in case["assertions"])), case)
    assert [r["assertion_id"] for r in result["accepted"]] == ["E2"]
    assert result["blocked"][0]["reason"] == "superseded"
    assert "unknown execution state" in result["text"]


def test_bundle_change_prevents_gateway_calls(tmp_path, monkeypatch):
    output = tmp_path / "run"
    prepare(output)
    monkeypatch.setattr(
        "experiments.evidence_context.assertion_gate.runner.call_gateway",
        lambda *args: pytest.fail("Gateway must not be called"),
    )
    frozen = output / "frozen.json"
    frozen.write_text(frozen.read_text() + " ")
    with pytest.raises(ValueError, match="bundle changed"):
        live(output)


def test_failures_retained_and_paid_run_cannot_repeat(tmp_path, monkeypatch):
    output = tmp_path / "run"
    frozen = prepare(output)
    assert len(frozen["requests"]) == 32
    calls = []

    def gateway(messages, model):
        calls.append(model)
        return {"text": "invalid draft", "cost_usd": 0}

    monkeypatch.setattr("experiments.evidence_context.assertion_gate.runner.call_gateway", gateway)
    rows = live(output)
    assert len(calls) == 32
    assert all(r["status"] == "failed" and r["text"] == "invalid draft" for r in rows)
    with pytest.raises(FileExistsError):
        live(output)
    assert len(calls) == 32


def test_replay_escapes_source_content_and_labels_offline_reference(tmp_path):
    from experiments.evidence_context.assertion_gate.viewer import render

    output = tmp_path / "demo"
    data = cases()
    data[0]["assertions"][0] = assertion(
        "E1", "<script>window.shouldNeverRun = true</script>", "parking.cleanup", "completed"
    )
    prepare(output, data)
    html_file = tmp_path / "replay.html"
    summary = render(output, html_file)
    text = html_file.read_text()
    assert "Offline reference demo" in text
    assert "<script>window.shouldNeverRun" not in text
    assert "&lt;script&gt;window.shouldNeverRun" in text
    assert text.count('class="case"') == 8
    assert text.count('class="probe"') == 20
    assert summary["calls"] == 0
    assert summary["controls"]["declared_semantic_gaps"] == 2
