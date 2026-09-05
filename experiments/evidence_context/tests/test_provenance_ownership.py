"""Boundary regression checks, including the intentionally unsolved semantics."""

import json

import pytest

from experiments.evidence_context.provenance_ownership.runner import (
    controls,
    fresh_cases,
    repair,
    run,
)
from experiments.evidence_context.source_annotations.probes import reference
from experiments.evidence_context.source_annotations.runner import prepare


def test_repair_preserves_original_and_does_not_fill_missing_invocation(tmp_path):
    data = prepare(tmp_path / "sources")
    case = next(c for c in data["cases"] if c["id"] == "missing_target")
    annotation = {**reference(case), "target": "parser.smoke@r7"}
    result = repair(annotation, case, data)
    assert annotation["target"] == "parser.smoke@r7"
    assert result["candidate"]["target"] is None
    assert not result["released"]


def test_semantic_errors_remain_visible_despite_metadata_repairs(tmp_path):
    rows = controls(prepare(tmp_path / "sources"))
    assert {r["name"] for r in rows if r["false_semantic_release"]} == {
        "wrong_narrative_state",
        "wrong_narrative_target",
    }
    by_name = {r["name"]: r for r in rows}
    assert by_name["wrong_basis"]["after"]["candidate"]["basis"] == "reported"
    assert by_name["wrong_scope"]["after"]["candidate"]["scope"] == "personal"
    assert not by_name["post_seal_corruption"]["after"]["released"]


def test_fresh_cases_separate_claims_from_captured_execution():
    rows = {r["source"]["id"]: r for r in fresh_cases()}
    for name in ("negated_report", "conditional_report", "quoted_receipt"):
        assert rows[name]["captured_facts"]["basis"] == "reported"
        assert rows[name]["captured_facts"]["execution_state"] == "unknown"
        assert rows[name]["unverified_proposal"]["state"] == "completed"
        assert rows[name]["semantic_status"] == "unverified_interpretation"
    conflict = rows["body_identity_conflict"]
    assert conflict["captured_facts"]["invocation_target"] == "parser.smoke@r9"
    assert conflict["unverified_proposal"]["target"] == "parser.smoke@r8"
    assert not rows["unclassified_process"]["personal_context_eligible"]
    assert rows["generic_tool_progress"]["captured_facts"]["execution_state"] == "unknown"
    assert rows["failed_exit_pass_text"]["captured_facts"]["execution_state"] == "completed"
    assert all(r["application_success"] == "not established" for r in rows.values())


def test_offline_walkthrough_and_no_overwrite(tmp_path):
    out = tmp_path / "demo"
    rows = run(out)
    summary = json.loads((out / "summary.json").read_text())
    assert len(rows) == 10
    assert summary["arms"]["offline-reference"]["after_released"] == 5
    assert summary["controls"]["incorrect_semantic_releases"] == 2
    html = (out / "walkthrough.html").read_text()
    assert html.count('class="case"') == 10
    assert html.count('class="fresh"') == 8
    assert "SEMANTIC ERROR REMAINS" in html
    with pytest.raises(FileExistsError):
        run(out)
