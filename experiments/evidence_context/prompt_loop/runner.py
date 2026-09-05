"""A bounded prompt loop with frozen scoring and an audit after winner selection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..arbitration_lab.runner import assess, call_gateway, prepare

DEV = ("queue", "retry")
AUDIT = ("cache", "storage")
RULES = {
    "queue": {"recommendation": ["insufficient"], "evidence_basis": ["insufficient"]},
    "retry": {"recommendation": ["B"], "evidence_basis": ["artifact_supported"]},
    "cache": {"recommendation": ["B", "conditional"], "evidence_basis": ["reported_only"]},
    "storage": {"recommendation": ["B"], "evidence_basis": ["artifact_supported"]},
}


def score(answer: dict, request: dict) -> dict:
    """Category compliance only: a fabricated rationale can still pass this proxy."""
    checks = assess(answer, request["context"], {})
    integrity = not any(
        checks[k]
        for k in ("unknown_citations", "artifact_basis_without_artifact_citation", "no_citations")
    )
    category = all(answer[k] in values for k, values in RULES[request["case"]].items())
    return {
        "integrity": integrity,
        "development_proxy": integrity and category,
        "semantic_support": "not_automatically_measured",
    }


def run(output: Path, *, live: bool = False, gateway=None) -> dict:
    """Run at most 18 calls; candidates cannot modify scorer, fixtures, or audit."""
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    frozen = prepare(output / "inputs", prompt_version="v2")
    requests = {r["case"]: r for r in frozen["requests"] if r["arm"] == "reference"}
    base = requests["queue"]["messages"][0]["content"]
    ledger = []
    candidates = []
    model = frozen["model"]
    manifest = {
        "mode": "live_synthetic" if live else "scripted_offline_demo",
        "development": DEV,
        "post_selection_audit": AUDIT,
        "independent_holdout": None,
        "max_calls": 18,
        "candidates": 2,
        "repeats": 2,
        "rules": RULES,
        "model": model,
        "scorer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limits": [
            "All four cases were previously seen",
            "Category proxy is not semantic quality",
            "No engine comparison",
            "No learner usefulness measurement",
        ],
    }

    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")

    save("manifest.json", manifest)

    def invoke(messages, *, phase, candidate, case=None):
        if len(ledger) >= manifest["max_calls"]:
            raise RuntimeError("Call budget exhausted")
        row = {"phase": phase, "candidate": candidate, "case": case, "messages": messages}
        ledger.append(row)
        save("ledger.json", ledger)  # Preserve attempted calls even if interrupted.
        try:
            if live:
                response = (gateway or call_gateway)(messages, model)
            elif phase == "propose":
                response = {
                    "text": json.dumps(
                        {
                            "amendment": "Require a measured comparison for performance choices. "
                            "Without one, "
                            "return insufficient for both recommendation and evidence_basis."
                        }
                    )
                }
            else:
                request = requests[case]
                recommendation = RULES[case]["recommendation"][0]
                basis = RULES[case]["evidence_basis"][0]
                if case == "queue" and candidate == "baseline":
                    recommendation, basis = "B", "reported_only"
                answer = {
                    "recommendation": recommendation,
                    "evidence_basis": basis,
                    "conflict_kind": "unresolved",
                    "rationale": "SCRIPTED demonstration.",
                    "alternative": "SCRIPTED alternative",
                    "uncertainty": "Synthetic only",
                    "next_check": "Review the evidence",
                    "citations": [
                        {"id": e["id"], "supports": "SCRIPTED citation"} for e in request["context"]
                    ],
                }
                response = {"text": json.dumps(answer)}
            row.update(response)
            row["parsed"] = json.loads(response["text"])
            row["status"] = "parsed"
        except Exception as error:
            row.update(status="failed", error_type=type(error).__name__)
        save("ledger.json", ledger)
        return row

    def evaluate(candidate, cases, repeats, phase):
        rows = []
        for case in cases:
            for _ in range(repeats):
                messages = [
                    {"role": "system", "content": base + "\n" + candidate["amendment"]},
                    requests[case]["messages"][1],
                ]
                row = invoke(messages, phase=phase, candidate=candidate["id"], case=case)
                try:
                    row["score"] = score(row["parsed"], requests[case])
                except (ValueError, KeyError, TypeError):
                    row["score"] = {"integrity": False, "development_proxy": False}
                rows.append(row)
                save("ledger.json", ledger)
        return {
            "integrity_passes": sum(r["score"]["integrity"] for r in rows),
            "proxy_passes": sum(r["score"]["development_proxy"] for r in rows),
            "total": len(rows),
        }

    winner = {"id": "baseline", "amendment": ""}
    winner["development"] = evaluate(winner, DEV, 2, "development")
    candidates.append(winner)
    save("candidates.json", candidates)
    for index in range(2):
        feedback = [
            {"case": r["case"], "answer": r.get("parsed"), "score": r.get("score")}
            for r in ledger
            if r["phase"] == "development"
        ]
        payload = {
            "base_prompt": base,
            "incumbent_amendment": winner["amendment"],
            "development_cases": [json.loads(requests[c]["messages"][1]["content"]) for c in DEV],
            "development_rules": {c: RULES[c] for c in DEV},
            "feedback": feedback,
        }
        proposal = invoke(
            [
                {
                    "role": "system",
                    "content": "Propose one general evidence-handling prompt amendment. "
                    "Return JSON with exactly one string field amendment, 1 to 1000 characters. "
                    "Preserve the answer schema. No case names, option-specific rules, "
                    "or fixture answers. "
                    "You cannot modify the evaluator. This is synthetic development only.",
                },
                {"role": "user", "content": json.dumps(payload)},
            ],
            phase="propose",
            candidate=f"candidate-{index + 1}",
        )
        parsed = proposal.get("parsed")
        if (
            not isinstance(parsed, dict)
            or set(parsed) != {"amendment"}
            or not isinstance(parsed["amendment"], str)
            or not 1 <= len(parsed["amendment"].strip()) <= 1000
        ):
            proposal["proposal_status"] = "rejected"
            save("ledger.json", ledger)
            continue
        candidate = {"id": proposal["candidate"], "amendment": parsed["amendment"]}
        candidate["development"] = evaluate(candidate, DEV, 2, "development")
        candidates.append(candidate)
        result = candidate["development"]
        if (
            result["integrity_passes"] == result["total"]
            and result["proxy_passes"] > winner["development"]["proxy_passes"]
        ):
            winner = candidate  # Strict improvement: ties keep the incumbent.
        save("candidates.json", candidates)
    # Lock before audit; audit feedback never enters another proposal or selection.
    save("selection.json", {"winner": winner, "basis": "development_proxy_only"})
    audit = {}
    for candidate in candidates[:1] if winner["id"] == "baseline" else [candidates[0], winner]:
        audit[candidate["id"]] = evaluate(candidate, AUDIT, 1, "audit")
    report = {
        "manifest": manifest,
        "winner": winner,
        "candidates": candidates,
        "audit": audit,
        "calls": len(ledger),
        "known_cost_usd": sum(r.get("cost_usd") or 0 for r in ledger),
        "calls_without_cost": sum(r.get("cost_usd") is None for r in ledger),
        "promotion": "not_authorized_by_this_development_experiment",
    }
    save("results.json", report)
    return report
