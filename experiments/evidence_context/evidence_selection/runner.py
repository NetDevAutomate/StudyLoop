"""Prepare a private controlled evidence trial; live calls are explicit and bounded."""

import argparse
import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..arbitration_lab.runner import call_gateway
from ..metadata_value.normalization_audit import parse_diagnostic
from ..retrieval_matrix.pilot import canonical, write
from ..retrieval_matrix.trial import assess, coverage

ARMS = ("original", "reviewed_only", "reviewed_plus_original")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_item(record):
    return {k: record[k] for k in ("id", "role", "at", "kind", "text")}


def reference_pack(required, filler, catalog, question, tokenizer, ceiling=1400, cap=6):
    """Required passages may never be silently dropped; filler is budget-limited."""
    pack = []
    seen = set()
    for rid in [*required, *filler]:
        if rid in seen:
            continue
        seen.add(rid)
        record = catalog[rid]
        if record["project"] != question["project"] or record["at"] >= question["asof"]:
            raise ValueError("Ineligible passage")
        item = project_item(record)
        fits = (
            len(pack) < cap
            and len(tokenizer.encode(canonical([*pack, item]), add_special_tokens=False)) <= ceiling
        )
        if not fits:
            if rid in required:
                raise ValueError("Required evidence exceeds the frozen budget")
            continue
        pack.append(item)
    return pack


def prepare(source, spec_path, output, tokenizer=None):
    if tokenizer is None:
        from transformers import AutoTokenizer

        config = json.loads((source / "config.json").read_text())
        tokenizer = AutoTokenizer.from_pretrained(config["tokenizer"], local_files_only=True)
    corpus = json.loads((source / "corpus.json").read_text())
    spec = json.loads(spec_path.read_text())
    previous = json.loads((source / "frozen-trial.json").read_text())
    original = {
        r["question"]: r
        for r in json.loads((source / "retrieval.json").read_text())
        if r["arm"] == "combined"
    }
    labels = json.loads((source / "labels.json").read_text())["groups"]
    catalog = {r["id"]: r for r in corpus["records"]}
    requests = []
    for q in corpus["questions"]:
        baseline = original[q["id"]]
        for arm in ARMS:
            if arm == "original":
                pack = reference_pack([], baseline["ids"], catalog, q, tokenizer)
                if pack != baseline["pack"]:
                    raise ValueError("Original context changed")
            else:
                pack = reference_pack(
                    spec["reference_ids"][q["id"]],
                    baseline["ids"] if arm == "reviewed_plus_original" else [],
                    catalog,
                    q,
                    tokenizer,
                )
            for repeat in range(2):
                requests.append(
                    {
                        "question": q["id"],
                        "query": q["query"],
                        "arm": arm,
                        "repeat": repeat,
                        "pack": pack,
                        "pack_tokens": len(
                            tokenizer.encode(canonical(pack), add_special_tokens=False)
                        ),
                        "coverage": coverage([r["id"] for r in pack], labels[q["id"]]),
                    }
                )
    if len(requests) != 24:
        raise ValueError("Protocol requires four questions and 24 requests")
    random.Random(1405).shuffle(requests)  # nosec B311 - reproducible experimental order.
    for index, request in enumerate(requests):
        request["id"] = f"B{index + 1:02}"
    frozen = {
        "prompt": previous["prompt"],
        "model": previous["model"],
        "temperature": 0,
        "max_output_tokens": 1500,
        "max_calls": 24,
        "spec": spec,
        "requests": requests,
        "source_hashes": {
            n: digest(source / n)
            for n in ("corpus.json", "retrieval.json", "labels.json", "config.json")
        },
        "source_spec_hash": digest(spec_path),
        "runner_hash": digest(Path(__file__)),
    }
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write(output / "frozen.json", frozen)
    write(output / "manifest.json", {"frozen_hash": digest(output / "frozen.json")})
    return frozen


def run_live(output):
    frozen_path = output / "frozen.json"
    manifest = json.loads((output / "manifest.json").read_text())
    if digest(frozen_path) != manifest["frozen_hash"]:
        raise ValueError("Frozen request bundle changed")
    frozen = json.loads(frozen_path.read_text())
    if digest(Path(__file__)) != frozen["runner_hash"]:
        raise ValueError("Runner changed after preparation")
    if len(frozen["requests"]) > frozen["max_calls"]:
        raise ValueError("Call limit exceeded")

    def execute(request):
        row = {
            k: request[k] for k in ("id", "question", "arm", "repeat", "pack_tokens", "coverage")
        }
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
    # Exclusive creation precedes any provider calls; no retries after interrupted trials.
    with (output / "answers.jsonl").open("x") as stream, ThreadPoolExecutor(max_workers=2) as pool:
        for row in pool.map(execute, frozen["requests"]):
            rows.append(row)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
    write(output / "answers.json", rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "live"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.source or not args.spec:
            parser.error("prepare requires --source and --spec")
        result = prepare(args.source, args.spec, args.output)
        print("Prepared", len(result["requests"]), "requests; no model calls made")
    else:
        run_live(args.output)


if __name__ == "__main__":
    main()
