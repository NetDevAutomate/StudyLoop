"""Offline contract demo and optional bounded live assertion-selection trial."""

import argparse
import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..arbitration_lab.runner import call_gateway
from ..metadata_value.normalization_audit import parse_diagnostic
from ..retrieval_matrix.pilot import canonical, write
from .fixtures import cases
from .gate import release
from .probes import claim
from .probes import run as run_probes


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(case, arm):
    records = []
    for r in case["assertions"]:
        record = {"assertion_id": r["id"], "text": r["source"]}
        if arm == "annotated":
            record["reviewed_metadata"] = {
                k: r[k] for k in ("scope", "project", "target", "state", "basis", "superseded_by")
            }
        records.append(record)
    return {
        "question": case["question"],
        "scope": case["scope"],
        "project": case["project"],
        "requested_targets": case["targets"],
        "records": records,
    }


def prepare(output, data=None):
    data = cases() if data is None else data
    if len(data) != 8:
        raise ValueError("Protocol requires eight cases")
    root = Path(__file__).parent
    requests = [
        {"case": c["id"], "arm": arm, "repeat": repeat, "payload": payload(c, arm)}
        for c in data
        for arm in ("raw", "annotated")
        for repeat in range(2)
    ]
    random.Random(1505).shuffle(requests)  # nosec B311 - reproducible trial order.
    for index, req in enumerate(requests):
        req["id"] = f"C{index + 1:02}"
    frozen = {
        "cases": data,
        "requests": requests,
        "prompt": (root / "PROMPT.md").read_text(),
        "model": "qwen3-coder",
        "max_calls": 32,
        "source_hashes": {
            n: digest(root / n)
            for n in ("runner.py", "gate.py", "fixtures.py", "probes.py", "PROMPT.md")
        },
    }
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write(output / "frozen.json", frozen)
    write(output / "manifest.json", {"frozen_hash": digest(output / "frozen.json")})
    write(output / "probes.json", run_probes())
    reference = []
    for c in data:
        draft = {
            "claims": [claim(r) for r in c["assertions"] if r["id"] in c["expected_ids"]],
            "answer": "Offline reference demonstration, not model output.",
        }
        reference.append({"case": c["id"], "gate": release(draft, c)})
    write(output / "reference.json", reference)
    return frozen


def live(output):
    root = Path(__file__).parent
    if (
        digest(output / "frozen.json")
        != json.loads((output / "manifest.json").read_text())["frozen_hash"]
    ):
        raise ValueError("Frozen bundle changed")
    frozen = json.loads((output / "frozen.json").read_text())
    if any(digest(root / n) != value for n, value in frozen["source_hashes"].items()):
        raise ValueError("Frozen source changed")
    if len(frozen["requests"]) > frozen["max_calls"]:
        raise ValueError("Call cap exceeded")
    catalog = {c["id"]: c for c in frozen["cases"]}

    def execute(req):
        row = {k: req[k] for k in ("id", "case", "arm", "repeat")}
        try:
            row.update(
                call_gateway(
                    [
                        {"role": "system", "content": frozen["prompt"]},
                        {"role": "user", "content": canonical(req["payload"])},
                    ],
                    frozen["model"],
                )
            )
            draft, method = parse_diagnostic(row["text"])
            row.update(draft=draft, parse_method=method)
            c = catalog[req["case"]]
            row["gate"] = release(draft, c)
            accepted = {r["assertion_id"] for r in row["gate"]["accepted"]}
            row["omitted_justified_ids"] = sorted(set(c["expected_ids"]) - accepted)
            row["unexpected_accepted_ids"] = sorted(accepted - set(c["expected_ids"]))
            row["status"] = "valid"
        except Exception as error:
            row.update(status="failed", error_type=type(error).__name__)
        print(row["id"], row["status"], flush=True)
        return row

    rows = []
    with (output / "answers.jsonl").open("x") as stream, ThreadPoolExecutor(max_workers=2) as pool:
        for row in pool.map(execute, frozen["requests"]):
            rows.append(row)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
    write(output / "answers.json", rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--live", action="store_true", help="Make up to 32 paid gateway calls")
    args = parser.parse_args()
    data = json.loads(args.cases.read_text()) if args.cases else None
    prepare(args.output, data)
    if args.live:
        live(args.output)
    print("Prepared contract demo at", args.output)


if __name__ == "__main__":
    main()
