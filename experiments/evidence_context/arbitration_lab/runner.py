"""Prepare inspectable prompts; optionally run 12 bounded local-gateway requests."""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from ..store import EvidenceRecord, EvidenceStore, Relationship, canonical_json

FIELDS = {
    "conflict_kind",
    "recommendation",
    "evidence_basis",
    "rationale",
    "alternative",
    "citations",
    "uncertainty",
    "next_check",
}


def assess(answer: dict, context: list[dict], expected: dict) -> dict:
    """Mechanical checks, not semantic entailment or an independent quality judge."""
    if not isinstance(answer, dict) or set(answer) != FIELDS:
        raise ValueError("Answer schema mismatch")
    enums = {
        "conflict_kind": {
            "changed_constraints",
            "correction",
            "unequal_evidence",
            "unresolved",
            "not_established",
        },
        "recommendation": {"A", "B", "conditional", "insufficient"},
        "evidence_basis": {"reported_only", "artifact_supported", "insufficient"},
    }
    for key, choices in enums.items():
        if answer[key] not in choices:
            raise ValueError("Unknown answer category")
    for key in ("rationale", "alternative", "uncertainty", "next_check"):
        if not isinstance(answer[key], str) or not answer[key].strip():
            raise ValueError("Nonempty explanation fields required")
    citations = answer["citations"]
    if not isinstance(citations, list) or any(
        not isinstance(c, dict)
        or set(c) != {"id", "supports"}
        or not isinstance(c["id"], str)
        or not isinstance(c["supports"], str)
        or not c["supports"].strip()
        for c in citations
    ):
        raise ValueError("Citation schema mismatch")
    available = {c["id"]: c for c in context}
    cited = {c["id"] for c in citations}
    unknown = sorted(cited - set(available))
    artifact_cited = any(available[k]["kind"] == "test_artifact" for k in cited & set(available))
    return {
        "unknown_citations": unknown,
        "artifact_basis_without_artifact_citation": answer["evidence_basis"] == "artifact_supported"
        and not artifact_cited,
        "no_citations": not citations,
        "expected_category_matches": {key: answer[key] == value for key, value in expected.items()},
        "semantic_support": "human_review_required",
        "learner_value": "not_measured",
    }


def prepare(
    output: Path, model: str = "qwen3-coder", budget: int = 8000, prompt_version: str = "v1"
) -> dict:
    root = Path(__file__).parent
    data = json.loads((root / "cases.json").read_text())
    if prompt_version not in {"v1", "v2"}:
        raise ValueError("Unknown prompt version")
    prompt = (root / f"PROMPT-{prompt_version}.md").read_text()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    store = EvidenceStore.create(output / "synthetic.db")
    requests = []
    try:
        for case in data["cases"]:
            versions = {}
            catalog = {}
            for evidence in case["evidence"]:
                version = store.add_evidence(
                    EvidenceRecord(
                        message_id=evidence["key"],
                        session_id=case["id"],
                        harness="fixture",
                        project=case["id"],
                        scope="personal",
                        content=evidence["text"],
                        timestamp=data["at"],
                        available_at=data["at"],
                        source_locator="synthetic:" + case["id"] + ":" + evidence["key"],
                    )
                )
                versions[evidence["key"]] = version
                catalog[version] = {
                    "id": "E" + version[:12],
                    "kind": evidence["kind"],
                    "text": evidence["text"],
                    "provenance": "synthetic_fixture",
                    "at": data["at"],
                }
            seed = versions[case["evidence"][0]["key"]]
            for target in list(versions.values())[1:]:
                store.add_relationship(
                    Relationship(
                        seed,
                        target,
                        "contradicts",
                        (store.cite(seed), store.cite(target)),
                        data["at"],
                        origin="asserted",
                        review_state="reviewed",
                        reviewer="synthetic-curator",
                        available_at=data["at"],
                    )
                )
            for arm in ("keyword", "relationships", "reference"):
                if arm == "reference":
                    context = [catalog[versions[k]] for k in case["reference_keys"]]
                else:
                    pack = store.retrieve(
                        case["query"],
                        project=case["id"],
                        scope="personal",
                        as_of=data["at"],
                        max_bytes=20000,
                        neighbor_turns=0,
                        use_relationships=arm == "relationships",
                    )
                    context = [
                        {**catalog[e.version_id], "text": e.citation.text} for e in pack.evidence
                    ]
                # Arm names and expected answers stay out of the identical presentation.
                payload = {
                    "question": case["question"],
                    "constraints": case["constraints"],
                    "evidence": context,
                }
                if len(canonical_json(payload).encode()) > budget:
                    raise ValueError("Context exceeds shared byte ceiling")
                requests.append(
                    {
                        "case": case["id"],
                        "arm": arm,
                        "context": context,
                        "expected": case["expected"],
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": canonical_json(payload)},
                        ],
                    }
                )
    finally:
        store.close()
    random.Random(42).shuffle(requests)  # nosec B311 - reproducible experimental order.
    for i, request in enumerate(requests):
        request["id"] = f"R{i + 1:02d}"
    frozen = {
        "kind": "synthetic",
        "model": model,
        "temperature": 0,
        "max_output_tokens": 1500,
        "context_budget": budget,
        "budget_unit": "utf8_bytes_not_model_tokens",
        "requests": requests,
        "prompt_version": prompt_version,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "dataset_sha256": hashlib.sha256(canonical_json(data).encode()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (output / "frozen.json").write_text(canonical_json(frozen) + "\n")
    (output / "prompt.md").write_text(prompt)
    (output / "blind-review-input.json").write_text(
        canonical_json([{"id": r["id"], "messages": r["messages"]} for r in requests]) + "\n"
    )
    return frozen


def call_gateway(messages: list[dict], model: str) -> dict:
    base = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000").rstrip("/")
    parsed = urlparse(base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.query
    ):
        raise ValueError("Live lab requires a loopback HTTP gateway")
    key = os.environ.get("LITELLM_API_KEY")
    if not key:
        raise ValueError("LITELLM_API_KEY required in environment")
    payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 1500}
    request = urllib.request.Request(
        base + "/v1/chat/completions",
        data=canonical_json(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.perf_counter()
    with opener.open(request, timeout=90) as response:
        result = json.loads(response.read())
        cost = response.headers.get("x-litellm-response-cost")
    return {
        "text": result["choices"][0]["message"]["content"],
        "finish_reason": result["choices"][0].get("finish_reason"),
        "usage": result.get("usage"),
        "cost_usd": float(cost) if cost is not None else None,
        "elapsed_seconds": time.perf_counter() - started,
    }


def run_live(output: Path, frozen: dict) -> dict:
    def execute(request):
        row = {"id": request["id"], "case": request["case"], "arm": request["arm"]}
        try:
            response = call_gateway(request["messages"], frozen["model"])
            row.update(response)
            answer = json.loads(response["text"])
            row["answer"] = answer
            row["checks"] = assess(answer, request["context"], request["expected"])
            row["status"] = "parsed"
        except Exception as error:
            # No exception body: it could include gateway headers or credentials.
            row.update(status="failed", error_type=type(error).__name__)
        return row

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(execute, frozen["requests"]))
    report = {
        "kind": "synthetic_single_model_pilot",
        "model": frozen["model"],
        "results": rows,
        "limits": [
            "No independent quality grading",
            "No real corpus",
            "One sample per condition",
            "Byte ceiling, not matched model-token budget",
            "No semantic entailment score",
        ],
    }
    (output / "results.json").write_text(canonical_json(report) + "\n")
    (output / "blind-review-answers.json").write_text(
        canonical_json(
            [{"id": r["id"], "answer": r.get("answer"), "status": r["status"]} for r in rows]
        )
        + "\n"
    )
    lines = [
        "# Synthetic arbitration pilot",
        "",
        "These are model observations, not independent quality scores.",
        "",
    ]
    for row in sorted(rows, key=lambda r: (r["case"], r["arm"])):
        lines.extend(
            [
                f"## {row['case']} / {row['arm']}",
                "",
                row.get("text") or row.get("error_type", "No text"),
                "",
            ]
        )
    (output / "answers.md").write_text("\n".join(lines))
    return report
