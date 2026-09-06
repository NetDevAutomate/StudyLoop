"""Frozen old/new prompt probe plus a provider-free explanatory walkthrough."""

import hashlib
import html
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..arbitration_lab.runner import assess as assess_legacy
from ..arbitration_lab.runner import call_gateway
from .policy import assess, derive


def choice(sufficiency, recommendation):
    return {"insufficient": "abstain", "conditional": "conditional"}.get(
        sufficiency, recommendation
    )


def prepare(output):
    root = Path(__file__).parent
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    data = json.loads((root / "cases.json").read_text())
    expected = json.loads((root / "expected.json").read_text())
    prompts = {
        "legacy": (root.parent / "arbitration_lab" / "PROMPT-v2.md").read_text(),
        "contract": (root / "PROMPT.md").read_text(),
    }
    requests = []
    for case in data["cases"]:
        evidence = [
            {**s, "kind": "test_artifact" if s["provenance"] == "artifact" else "agent_report"}
            for s in case["sources"]
        ]
        payload = {
            "question": case["question"],
            "constraints": {"target": case["target"], "decision_mode": case["decision_mode"]},
            "evidence": evidence,
            "scenario": "synthetic_fixture_not_real_validation",
        }
        for arm, prompt in prompts.items():
            requests.append(
                {
                    "case": case["id"],
                    "arm": arm,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload, sort_keys=True)},
                    ],
                }
            )
    frozen = {
        "data": data,
        "expected": expected,
        "requests": requests,
        "model": "qwen3-coder",
        "kind": "synthetic_contract_probe",
        "independent_holdout": False,
        "max_calls": 16,
        "temperature": 0,
        "max_output_tokens": 1500,
        "fingerprints": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("cases.json", "expected.json", "PROMPT.md", "policy.py", "runner.py")
        },
    }
    (output / "frozen.json").write_text(json.dumps(frozen, indent=2) + "\n")
    reference = [{"case": c["id"], "answer": derive(c)} for c in data["cases"]]
    (output / "reference.json").write_text(json.dumps(reference, indent=2) + "\n")
    render(output, reference)
    return frozen


def render(output, reference):
    sections = []
    for item in reference:
        decision = item["answer"]["decision"]
        rows = "".join(
            "<tr>"
            + "".join(
                f"<td>{html.escape(row[k])}</td>"
                for k in ("id", "provenance", "applicability", "reason")
            )
            + "</tr>"
            for row in item["answer"]["source_assessments"]
        )
        paragraphs = "".join(
            f"<p><b>{key.replace('_', ' ').title()}:</b> {html.escape(decision[key])}</p>"
            for key in ("reason_code", "explanation", "limitation", "next_check")
        )
        sections.append(
            f"<details><summary>{html.escape(item['case'])}: "
            f"{decision['sufficiency']} / {decision['recommendation']}</summary>"
            "<table><tr><th>Source</th><th>Provenance</th><th>Applicability</th><th>Why</th></tr>"
            f"{rows}</table>{paragraphs}<p>Decision basis: "
            f"{', '.join(decision['basis_ids'])}</p></details>"
        )
    page = (Path(__file__).parent / "walkthrough-header.html").read_text()
    (output / "walkthrough.html").write_text(page + "".join(sections) + "</html>\n")


def run_live(output, frozen, gateway=None):
    cases = {c["id"]: c for c in frozen["data"]["cases"]}
    if len(frozen["requests"]) > 16:
        raise ValueError("Exceeded fixed probe size")
    ledger_dir = output / "calls"
    ledger_dir.mkdir(exist_ok=False, mode=0o700)

    def execute(pair):
        index, request = pair
        path = ledger_dir / f"{index:02d}.json"
        row = {"case": request["case"], "arm": request["arm"], "status": "attempted"}
        path.write_text(json.dumps(row) + "\n")
        try:
            response = (gateway or call_gateway)(request["messages"], frozen["model"])
            row.update(response)
            answer = json.loads(response["text"])
            row["answer"] = answer
            case, expected = cases[request["case"]], frozen["expected"][request["case"]]
            target_choice = choice(expected["sufficiency"], expected["recommendation"])
            if request["arm"] == "contract":
                row["checks"] = assess(answer, case, expected)
                actual = choice(
                    answer["decision"]["sufficiency"], answer["decision"]["recommendation"]
                )
            else:
                evidence = json.loads(request["messages"][1]["content"])["evidence"]
                row["checks"] = assess_legacy(answer, evidence, {})
                actual = {"insufficient": "abstain"}.get(
                    answer["recommendation"], answer["recommendation"]
                )
            row["choice_matches"] = actual == target_choice
            row["status"] = "parsed"
        except Exception as error:
            row.update(status="failed", error_type=type(error).__name__)
        path.write_text(json.dumps(row, indent=2) + "\n")
        return row

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(execute, enumerate(frozen["requests"])))
    report = {
        "kind": "synthetic_single_sample_per_condition",
        "model": frozen["model"],
        "rows": rows,
        "known_cost_usd": sum(r.get("cost_usd") or 0 for r in rows),
        "calls_without_cost": sum(r.get("cost_usd") is None for r in rows),
        "limits": [
            "No independent holdout",
            "Choice matching is not answer quality",
            "Metadata is authored; authenticity not verified",
            "Prompt and schema both change",
            "No production promotion or database-engine comparison",
        ],
    }
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
