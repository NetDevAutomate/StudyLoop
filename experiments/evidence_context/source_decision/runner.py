"""Frozen 24-call draft comparison and provider-free source-to-policy walkthrough."""

import copy
import hashlib
import html
import json
from pathlib import Path

from ..arbitration_lab.runner import call_gateway
from ..metadata_value.normalization_audit import parse_diagnostic
from ..metadata_value.verify import FIELDS, assess_answer, reference_extraction, verify
from .boundary import EvidenceSnapshot, compare_draft, release, resolve


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def proposal_for(case):
    try:
        proposal = reference_extraction(case["source"]["text"])
    except ValueError:
        proposal = {key: {"value": None, "quote": None} for key in FIELDS}
    edit = case["proposal_edit"]
    if edit:
        proposal[edit["field"]] = {"value": edit["value"], "quote": edit["quote"]}
    return proposal


def snapshot_for(case, proposal):
    return EvidenceSnapshot.freeze(case["source"], case["target"], proposal)


def prepare(output):
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    root = Path(__file__).parent
    cases = json.loads((root / "cases.json").read_text())["cases"]
    labels = json.loads((root / "labels.json").read_text())
    prompt = (root.parent / "metadata_value/ANSWER.md").read_text()
    dependencies = [
        root / name
        for name in (
            "boundary.py",
            "runner.py",
            "cases.json",
            "labels.json",
            "PROTOCOL.md",
            "GRAMMAR.md",
        )
    ]
    dependencies += [
        root.parent / name
        for name in (
            "metadata_value/ANSWER.md",
            "metadata_value/verify.py",
            "metadata_value/normalization_audit.py",
            "decision_contract/policy.py",
            "acceptance_gate/gate.py",
            "arbitration_lab/runner.py",
        )
    ]
    frozen = {
        "cases": cases,
        "labels": labels,
        "answer_prompt": prompt,
        "model": "qwen3-coder",
        "max_calls": 24,
        "proposals": {c["id"]: proposal_for(c) for c in cases},
        "fingerprints": {
            str(p.relative_to(root.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in dependencies
        },
    }
    write(output / "frozen.json", frozen)
    rows = []
    for case in cases:
        snapshot = snapshot_for(case, frozen["proposals"][case["id"]])
        rows.append(
            {
                "case": case["id"],
                "source": case["source"],
                "target": case["target"],
                "proposal": frozen["proposals"][case["id"]],
                "expected": labels["cases"][case["id"]]["expected_choice"],
                "outputs": {
                    mode: release(snapshot, mode) for mode in ("checked_only", "source_adapter")
                },
            }
        )
    write(output / "offline.json", rows)
    render(output / "walkthrough.html", rows, "Offline policy walkthrough; no model answers")
    return frozen


def render(path, rows, title):
    parts = [
        "<!doctype html><html lang='en'><meta charset='utf-8'><title>Stage 11</title>",
        "<style>body{font:18px/1.6 system-ui;max-width:1100px;margin:40px auto;padding:20px}",
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer;padding:12px}",
        "</style><h1>" + html.escape(title) + "</h1>",
        "<p>Synthetic development cases. Policy-rendered outputs are independent of model prose. ",
        "Source correspondence does not authenticate an artifact. Expand a case to compare ",
        "source, target, proposal, release reasons and exact evidence locators.</p>",
    ]
    for row in rows:
        label = row["case"] + (f" / repeat {row['repeat']}" if "repeat" in row else "")
        parts.append(
            "<details><summary>"
            + html.escape(label)
            + "</summary><pre>"
            + html.escape(json.dumps(row, indent=2))
            + "</pre></details>"
        )
    path.write_text("".join(parts) + "</html>\n")


def assess_row(row, case, frozen):
    snapshot = snapshot_for(case, frozen["proposals"][case["id"]])
    expected = frozen["labels"]["cases"][case["id"]]["expected_choice"]
    answer = row.get("answer")
    row["outputs"] = {
        mode: compare_draft(snapshot, {"snapshot_id": snapshot.identity, "answer": answer}, mode)
        for mode in ("checked_only", "source_adapter")
    }
    row["metrics"] = {}
    for mode, output in row["outputs"].items():
        choice = output["decision"]["recommendation"]
        locators = [loc for fact in output["facts"] for loc in fact["basis"]]
        locators += [loc for issue in output["issues"] for loc in issue["basis"]]
        row["metrics"][mode] = {
            "choice": choice,
            "choice_matches": choice == expected,
            "unsupported_choice": choice != "none" and choice != expected,
            "false_block": choice == "none" and expected != "none",
            "locators_resolve": bool(locators) and all(resolve(snapshot, loc) for loc in locators),
            "abstention_has_issue_and_check": choice != "none"
            or bool(output["issues"] and output["decision"]["next_check"]),
        }
    try:
        check = assess_answer(answer, {**case, "expected_choice": expected})
        row["advisory_checks"] = check
        row["metrics"]["advisory"] = {
            "choice": answer["recommendation"],
            "choice_matches": check["choice_matches"],
            "unsupported_choice": check["unsupported_endorsement"],
            "false_block": check["missed_supported_choice"],
        }
    except (ValueError, TypeError, KeyError):
        row["advisory_checks"] = {"invalid_response": True}
        row["metrics"]["advisory"] = {"invalid_response": True}
    return row


def summarize(rows):
    summary = {}
    for mode in ("advisory", "checked_only", "source_adapter"):
        metrics = [row["metrics"][mode] for row in rows]
        summary[mode] = {
            "rows": len(rows),
            "valid_decisions": sum(not m.get("invalid_response") for m in metrics),
        }
        for key in ("choice_matches", "unsupported_choice", "false_block"):
            summary[mode][key] = sum(bool(m.get(key)) for m in metrics)
    return summary


def run_live(output, frozen, gateway=None):
    calls = output / "calls"
    calls.mkdir(exist_ok=False, mode=0o700)
    rows = []
    for repeat in (1, 2):
        cases = frozen["cases"] if repeat == 1 else list(reversed(frozen["cases"]))
        for case in cases:
            if len(rows) >= 24:
                raise ValueError("Call budget exhausted")
            proposal = frozen["proposals"][case["id"]]
            payload = {
                "question": "Which option is justified for this target?",
                "source": case["source"],
                "target": case["target"],
                "metadata": {
                    "state": "checked_against_narrow_log_grammar",
                    "fields": verify(case["source"]["text"], proposal),
                },
            }
            messages = [
                {"role": "system", "content": frozen["answer_prompt"]},
                {"role": "user", "content": json.dumps(payload, sort_keys=True)},
            ]
            row = {
                "case": case["id"],
                "repeat": repeat,
                "messages": messages,
                "status": "attempted",
            }
            path = calls / f"{len(rows):02d}.json"
            rows.append(row)
            write(path, row)
            try:
                row.update((gateway or call_gateway)(messages, frozen["model"]))
                try:
                    json.loads(row["text"])
                    row["strict_json"] = True
                except (ValueError, TypeError):
                    row["strict_json"] = False
                row["answer"], row["parse_method"] = parse_diagnostic(row["text"])
                row["status"] = "parsed"
            except Exception as error:
                row.update(status="failed", error_type=type(error).__name__)
            assess_row(row, case, frozen)
            write(path, row)
    report = {
        "rows": rows,
        "summary": summarize(rows),
        "known_cost_usd": sum(r.get("cost_usd") or 0 for r in rows),
        "calls_without_cost": sum(r.get("cost_usd") is None for r in rows),
        "strict_json_count": sum(bool(r.get("strict_json")) for r in rows),
    }
    write(output / "results.json", report)
    render(output / "answer-replay.html", rows, "Actual advisory drafts and policy outputs")
    return report


def replay(input_directory, output):
    output.mkdir(exist_ok=False, parents=True, mode=0o700)
    frozen = json.loads((input_directory / "frozen.json").read_text())
    report = json.loads((input_directory / "results.json").read_text())
    cases = {case["id"]: case for case in frozen["cases"]}
    rows = [assess_row(copy.deepcopy(row), cases[row["case"]], frozen) for row in report["rows"]]
    write(
        output / "replay.json",
        {
            "summary": summarize(rows),
            "rows": rows,
            "notice": "Current code replay; original observation is unchanged.",
        },
    )
    render(output / "answer-replay.html", rows, "Current-code replay of preserved model drafts")
    return summarize(rows)
