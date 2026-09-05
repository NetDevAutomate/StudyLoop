"""Frozen real-data pilot: local retrieval, bounded gateway answers, mechanical checks."""

import argparse
import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..arbitration_lab.runner import call_gateway
from ..metadata_value.normalization_audit import parse_diagnostic
from .pilot import canonical, embed, prepare, retrieve, write


def coverage(ids, groups):
    """Each group is one required fact; IDs inside it are reviewed alternatives."""
    return {
        "covered": sum(bool(set(ids) & set(group)) for group in groups),
        "required": len(groups),
    }


def assess(answer, pack):
    fields = {"answer", "evidence_status", "citations", "limitations", "next_check"}
    if not isinstance(answer, dict) or set(answer) != fields:
        raise ValueError("Schema mismatch")
    if answer["evidence_status"] not in {"reported_only", "insufficient", "validated"}:
        raise ValueError("Unknown evidence status")
    for key in ("answer", "limitations", "next_check"):
        if not isinstance(answer[key], str) or not answer[key].strip():
            raise ValueError("Empty explanation")
    citations = answer["citations"]
    if not isinstance(citations, list):
        raise ValueError("Invalid citations")
    for c in citations:
        if not isinstance(c, dict) or set(c) != {"id", "quote", "supports"}:
            raise ValueError("Invalid citation")
        if any(not isinstance(value, str) or not value.strip() for value in c.values()):
            raise ValueError("Empty citation field")
    by_id = {r["id"]: r for r in pack}
    checks = [c["id"] in by_id and c["quote"] in by_id[c["id"]]["text"] for c in citations]
    return {
        "citation_count": len(citations),
        "quotes_locatable": sum(checks),
        "bad_quote_or_id_count": len(checks) - sum(checks),
        "unsupported_validation_status": answer["evidence_status"] == "validated"
        and not any(r["kind"] == "authenticated_artifact" for r in pack),
        "semantic_support": "separate_review_required",
    }


def freeze(directory):
    """Run before retrieval inspection; refuse accidental overwrite of a frozen run."""
    destination = directory / "frozen-trial.json"
    if destination.exists() or (directory / "retrieval.json").exists():
        raise ValueError("Use a fresh run directory")
    root = Path(__file__).parent
    files = [directory / n for n in ("corpus.json", "labels.json", "config.json")]
    files.extend([root / "pilot.py", root / "trial.py", root / "PROMPT.md"])
    value = {
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "prompt": (root / "PROMPT.md").read_text(),
        "model": "qwen3-coder",
        "temperature": 0,
        "max_output_tokens": 1500,
        "repeats": 2,
        "seed": 1205,
        "max_requests": 32,
        "label_status": "coordinator-arbitrated development labels, not human gold",
    }
    write(destination, value)
    return value


def answers(directory):
    if (directory / "answers.jsonl").exists():
        raise ValueError("No overwrite or implicit repeat of paid requests")
    frozen = json.loads((directory / "frozen-trial.json").read_text())
    packs = json.loads((directory / "retrieval.json").read_text())
    labels = json.loads((directory / "labels.json").read_text())["groups"]
    requests = [{**p, "repeat": repeat} for repeat in range(2) for p in packs]
    if len(requests) > frozen["max_requests"]:
        raise ValueError("Request cap exceeded")
    random.Random(frozen["seed"]).shuffle(requests)  # nosec B311 - reproducible trial order.
    for i, row in enumerate(requests):
        row["id"] = f"A{i + 1:02}"
    write(directory / "requests.json", requests)

    def execute(request):
        row = {k: request[k] for k in ("id", "question", "arm", "repeat", "pack_tokens")}
        row["coverage"] = coverage(request["ids"], labels[request["question"]])
        try:
            row.update(
                call_gateway(
                    [
                        {"role": "system", "content": frozen["prompt"]},
                        {
                            "role": "user",
                            "content": canonical(
                                {"question": request["query"], "evidence": request["pack"]}
                            ),
                        },
                    ],
                    frozen["model"],
                )
            )
            answer, method = parse_diagnostic(row["text"])
            row.update(answer=answer, parse_method=method)
            row["checks"] = assess(answer, request["pack"])
            row["status"] = "valid"
        except Exception as error:
            row.update(status="failed", error_type=type(error).__name__)
        print(row["id"], row["status"], flush=True)
        return row

    rows = []
    with (
        (directory / "answers.jsonl").open("x") as stream,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        for row in pool.map(execute, requests):
            rows.append(row)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
    write(directory / "answers.json", rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "embed", "freeze", "retrieve", "answers"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.config is None:
            parser.error("prepare requires --config")
        prepare(args.config, args.directory)
    else:
        {"embed": embed, "freeze": freeze, "retrieve": retrieve, "answers": answers}[args.action](
            args.directory
        )


if __name__ == "__main__":
    main()
