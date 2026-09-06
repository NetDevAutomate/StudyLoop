"""Offline replay and fresh controls; no provider calls or production database writes."""

import argparse
import copy
import json
from dataclasses import asdict
from pathlib import Path

from agent_session_tools.context.provenance import (
    CapturedReceipt,
    ExecutionState,
    GroundedCandidate,
    Interpretation,
    Origin,
    Scope,
    ScopeAssignment,
    derive_provenance,
)

from ..source_annotations.annotation import accept, integrity_ok, sealed
from ..source_annotations.capture import digest, resolve, write
from ..source_annotations.probes import reference
from ..source_annotations.runner import prepare as prepare_previous


def repair(annotation, case, data):
    receipt, error = resolve(case["record"], data["receipts"], data["manifest"])
    if error:
        return {"released": False, "reason": error, "candidate": None}
    assignment = ScopeAssignment(
        scope=Scope(receipt["context"]["scope"]),
        project_id=receipt["context"]["project"],
        policy_id="fixture-policy",
    )
    captured = CapturedReceipt(
        receipt_id=receipt["id"],
        origin=Origin(receipt["origin"]),
        target=receipt["context"]["target"],
        exit_code=receipt.get("returncode"),
    )
    owned = derive_provenance(assignment, captured)
    proposal = Interpretation(
        state=ExecutionState(annotation["state"]),
        target=annotation["target"],
        quote=annotation["quote"],
    )
    candidate = GroundedCandidate(provenance=owned, proposal=proposal)
    corrected = {
        **annotation,
        "basis": owned.basis.value,
        "scope": owned.scope.value,
        "state": candidate.state.value,
        "target": candidate.target,
    }
    result = accept(corrected, case, data["receipts"], data["manifest"])
    return {
        **result,
        "candidate": corrected,
        "semantic_status": candidate.semantic_status,
        "field_changes": {
            k: {"proposed": annotation[k], "source_owned": corrected[k]}
            for k in ("basis", "scope", "state", "target")
            if annotation[k] != corrected[k]
        },
    }


def evaluate(rows, data):
    catalog = {c["id"]: c for c in data["cases"]}
    results = []
    for row in rows:
        if row.get("status") != "valid":
            results.append({"id": row["id"], "status": "prior_failure"})
            continue
        c = catalog[row["case"]]
        candidate = repair(row["annotation"], c, data)
        expected = c["expected"]
        fields_match = candidate["candidate"] is not None and all(
            candidate["candidate"][k] == v for k, v in expected.items()
        )
        results.append(
            {
                "id": row["id"],
                "case": row["case"],
                "arm": row["arm"],
                "status": "evaluated",
                "original_annotation": row["annotation"],
                "before": row["release"],
                "after": candidate,
                "expected_release": c["expected_release"],
                "released_fields_match_reference": fields_match if candidate["released"] else None,
            }
        )
    return results


def controls(data):
    catalog = {c["id"]: c for c in data["cases"]}
    specs = [
        ("wrong_basis", "quoted_report", {"basis": "observed"}, False),
        ("wrong_scope", "progress_report", {"scope": "work"}, False),
        ("wrong_execution_state", "real_exit", {"state": "planned"}, False),
        ("wrong_invocation_target", "real_exit", {"target": "parser.smoke@r8"}, False),
        ("invented_missing_target", "missing_target", {"target": "parser.smoke@r7"}, False),
        ("wrong_narrative_state", "progress_report", {"state": "completed"}, False),
        ("wrong_narrative_target", "quoted_report", {"target": "parser.smoke@r8"}, False),
        ("post_seal_corruption", "quoted_report", {"basis": "observed"}, True),
    ]
    rows = []
    for name, cid, changes, postseal in specs:
        c = copy.deepcopy(catalog[cid])
        if name == "wrong_narrative_target":
            c["targets"] = ["parser.smoke@r8"]
            c["expected_release"] = False
        original = reference(c)
        envelope = sealed(copy.deepcopy(original))
        annotation = {**original, **changes}
        if not postseal:
            envelope = sealed(annotation)
        else:
            envelope["annotation"] = annotation
        before = accept(annotation, c, data["receipts"], data["manifest"])
        after = repair(annotation, c, data)
        if not integrity_ok(envelope):
            before = {"released": False, "reason": "annotation_changed"}
            after = {"released": False, "reason": "annotation_changed", "candidate": None}
        correct = after["candidate"] is not None and all(
            after["candidate"][k] == v for k, v in c["expected"].items()
        )
        rows.append(
            {
                "name": name,
                "before": before,
                "after": after,
                "false_semantic_release": after["released"] and not correct,
                "semantic_gap": name.startswith("wrong_narrative"),
            }
        )
    return rows


def fresh_cases():
    """Code-owned facts and preserved proposals on a separately reviewed fixture deck."""
    rows = json.loads(Path(__file__).with_name("fresh-cases.json").read_text())
    results = []
    for row in rows:
        receipt = CapturedReceipt(
            receipt_id=row["id"],
            origin=Origin(row["origin"]),
            target=row["target"],
            exit_code=row["exit_code"],
        )
        owned = derive_provenance(
            ScopeAssignment(
                scope=Scope(row["scope"]),
                project_id="fresh-fixture",
                policy_id="explicit-fixture-policy",
            ),
            receipt,
        )
        proposal = Interpretation(
            state=ExecutionState(row["proposal_state"]),
            target=row["proposal_target"],
            quote=row["body"],
        )
        candidate = GroundedCandidate(provenance=owned, proposal=proposal)
        results.append(
            {
                "source": row,
                "captured_facts": asdict(owned),
                "unverified_proposal": asdict(proposal),
                "semantic_status": candidate.semantic_status,
                "application_success": "not established",
                "personal_context_eligible": owned.scope == Scope.PERSONAL,
            }
        )
    return results


def run(output, previous=None):
    output.mkdir(parents=True, exist_ok=False)
    if previous:
        raw = (previous / "frozen.json").read_text()
        if digest(raw) != json.loads((previous / "frozen-manifest.json").read_text())["sha256"]:
            raise ValueError("Previous frozen bundle changed")
        data = json.loads(raw)
        rows = json.loads((previous / "answers.json").read_text())
    else:
        data = prepare_previous(output / "reference-sources")
        rows = [
            {
                "id": f"D{i + 1:02}",
                "case": c["id"],
                "arm": "offline-reference",
                "status": "valid",
                "annotation": reference(c),
                "release": accept(reference(c), c, data["receipts"], data["manifest"]),
            }
            for i, c in enumerate(data["cases"])
        ]
    results = evaluate(rows, data)
    write(output / "replay.json", results)
    control_rows = controls(data)
    write(output / "controls.json", control_rows)
    write(output / "fresh.json", fresh_cases())
    summary = {
        "mode": "saved-model-replay" if previous else "offline-reference",
        "rows": len(rows),
        "controls": {
            "count": len(control_rows),
            "incorrect_semantic_releases": sum(r["false_semantic_release"] for r in control_rows),
        },
        "fresh_cases": 8,
        "limitations": (
            "Offline policy replay; not new model responses, "
            "semantic certification or production acceptance."
        ),
        "arms": {},
    }
    for arm in sorted({r["arm"] for r in rows}):
        subset = [r for r in results if r.get("arm") == arm]
        summary["arms"][arm] = {
            "before_released": sum(r["before"]["released"] for r in subset),
            "after_released": sum(r["after"]["released"] for r in subset),
            "expected_instances": sum(r["expected_release"] for r in subset),
            "incorrect_final_fields": sum(
                r["released_fields_match_reference"] is False for r in subset
            ),
        }
    write(output / "summary.json", summary)
    from .viewer import render

    render(output, output / "walkthrough.html")
    print(json.dumps(summary, indent=2))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    run(args.output, args.previous)


if __name__ == "__main__":
    main()
