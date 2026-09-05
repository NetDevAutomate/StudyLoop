"""Origin capture, corruption boundaries and explicitly surviving semantic gaps."""

import copy
import json

import pytest

from experiments.evidence_context.source_annotations.annotation import accept, integrity_ok, sealed
from experiments.evidence_context.source_annotations.capture import resolve
from experiments.evidence_context.source_annotations.fixtures import build
from experiments.evidence_context.source_annotations.probes import reference, run
from experiments.evidence_context.source_annotations.runner import live, payload, prepare


@pytest.fixture
def captured(tmp_path):
    return build(tmp_path / "capture")


def test_real_subprocess_capture_distinguishes_exit_from_success(captured):
    assert captured["receipts"]["R01"]["returncode"] == 0
    assert captured["receipts"]["R03"]["returncode"] == 3
    for i in (0, 2):
        c = captured["cases"][i]
        result = accept(reference(c), c, captured["receipts"], captured["manifest"])
        assert result["released"]
        assert "completed" in result["text"]
        assert "passed" not in result["text"]


def test_same_text_is_not_the_same_origin_and_raw_never_leaks_labels(captured):
    first, second = captured["cases"][:2]
    assert payload(first, "text", captured) == payload(second, "text", captured)
    a, b = (payload(c, "capture", captured) for c in (first, second))
    assert a["capture_envelope"]["origin"] == "process_exit"
    assert b["capture_envelope"]["origin"] == "conversation_message"
    for key in ("expected", "basis", "state"):
        assert key not in a["capture_envelope"]


@pytest.mark.parametrize("index,reason", [(4, "missing_receipt"), (7, "body_changed")])
def test_missing_or_changed_capture_is_withheld_by_adapter(captured, index, reason):
    c = captured["cases"][index]
    record, error = resolve(c["record"], captured["receipts"], captured["manifest"])
    assert record is None and error == reason
    value = payload(c, "capture", captured)
    assert "capture_envelope" not in value
    assert value["capture_verification"]["reason"] == reason


def test_swapping_receipts_with_identical_body_is_detected(captured):
    c = copy.deepcopy(captured["cases"][0])
    c["record"]["receipt_id"] = "R02"
    _, reason = resolve(c["record"], captured["receipts"], captured["manifest"])
    assert reason == "receipt_binding_mismatch"


def test_preseal_misinterpretation_differs_from_postseal_corruption():
    envelope = sealed({"state": "completed"})
    assert integrity_ok(envelope)
    envelope["annotation"]["state"] = "planned"
    assert not integrity_ok(envelope)


def test_probes_keep_semantic_failures_visible(captured):
    rows = run(captured)
    assert len(rows) == 14
    assert sum(r["integrity_only_accepts"] for r in rows) == 10
    assert sum(r["source_gate_accepts"] for r in rows) == 6
    assert all(r["matches"] for r in rows if not r["known_gap"])
    gaps = [r for r in rows if r["known_gap"]]
    assert len(gaps) == 2
    assert all(r["source_gate_accepts"] and not r["matches"] for r in gaps)


@pytest.mark.parametrize("index", [5, 6, 9])
def test_revision_scope_and_missing_identity_prevent_release(captured, index):
    c = captured["cases"][index]
    assert not accept(reference(c), c, captured["receipts"], captured["manifest"])["released"]


def test_arbitrary_quote_and_advisory_prose_cannot_be_released(captured):
    c = captured["cases"][0]
    a = reference(c)
    a["quote"] = "invented supporting quote"
    assert (
        accept(a, c, captured["receipts"], captured["manifest"])["reason"] == "quote_not_in_source"
    )
    a = reference(c)
    a["rationale"] = "EVERYTHING SUCCEEDED"
    assert "EVERYTHING" not in accept(a, c, captured["receipts"], captured["manifest"])["text"]


def test_fixed_trial_and_per_arm_expected_fields(tmp_path):
    f = prepare(tmp_path / "trial")
    assert len(f["requests"]) == 40
    assert len(f["expectations"]) == 20
    assert all(
        e["fields"]["basis"] == "unknown" and e["fields"]["scope"] is None
        for e in f["expectations"]
        if e["arm"] == "text"
    )
    assert all("expected" not in r["payload"] for r in f["requests"])


def test_bundle_corruption_stops_before_any_model_call(tmp_path, monkeypatch):
    out = tmp_path / "trial"
    prepare(out)
    monkeypatch.setattr(
        "experiments.evidence_context.source_annotations.runner.call_gateway",
        lambda *args: pytest.fail("Must not call provider"),
    )
    file = out / "frozen.json"
    file.write_text(file.read_text() + " ")
    with pytest.raises(ValueError, match="bundle changed"):
        live(out)


def test_failed_outputs_retained_and_paid_calls_cannot_repeat(tmp_path, monkeypatch):
    out = tmp_path / "trial"
    prepare(out)
    calls = []

    def gateway(*args):
        calls.append(True)
        return {"text": "invalid json"}

    monkeypatch.setattr(
        "experiments.evidence_context.source_annotations.runner.call_gateway", gateway
    )
    rows = live(out)
    assert len(rows) == len(calls) == 40
    assert all(r["text"] == "invalid json" and r["status"] == "failed" for r in rows)
    with pytest.raises(FileExistsError):
        live(out)
    assert len(calls) == 40
    assert len(json.loads((out / "answers.json").read_text())) == 40


def test_replay_distinguishes_reference_from_live_and_escapes_text(tmp_path):
    from experiments.evidence_context.source_annotations.viewer import render

    out = tmp_path / "trial"
    f = prepare(out)
    f["cases"][0]["record"]["text"] = "<script>alert(1)</script>"
    (out / "frozen.json").write_text(json.dumps(f))
    html_file = out / "walkthrough.html"
    summary = render(out, html_file)
    text = html_file.read_text()
    assert "Offline reference demo" in text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert text.count('class="case"') == 10
    assert text.count('class="control"') == 14
    assert summary["calls"] == 0
