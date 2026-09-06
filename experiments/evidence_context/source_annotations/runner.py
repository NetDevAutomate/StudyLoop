"""Freeze local captures and optionally execute forty bounded annotation calls."""

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..arbitration_lab.runner import call_gateway
from ..metadata_value.normalization_audit import parse_diagnostic
from .annotation import accept, score, validate
from .capture import canonical, digest, resolve, write
from .fixtures import build
from .probes import reference
from .probes import run as run_probes


def payload(case, arm, data):
    value = {
        "question": case["question"],
        "requested_scope": case["scope"],
        "requested_targets": case["targets"],
        "record": {"id": "E1", "text": case["record"]["text"]},
    }
    if arm == "capture":
        receipt, error = resolve(case["record"], data["receipts"], data["manifest"])
        value["capture_verification"] = {
            "status": "verified" if not error else "unavailable",
            "reason": error,
        }
        if receipt:
            value["capture_envelope"] = receipt
    return value


def source_hashes():
    root = Path(__file__).parent
    own = ("runner.py", "capture.py", "fixtures.py", "annotation.py", "probes.py", "PROMPT.md")
    shared = (
        "../assertion_gate/gate.py",
        "../assertion_gate/fixtures.py",
        "../arbitration_lab/runner.py",
        "../metadata_value/normalization_audit.py",
    )
    return {name: digest((root / name).read_text()) for name in own + shared}


def prepare(output):
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    data = build(output / "artifacts")
    requests = [
        {"case": c["id"], "arm": arm, "repeat": repeat, "payload": payload(c, arm, data)}
        for c in data["cases"]
        for arm in ("text", "capture")
        for repeat in range(2)
    ]
    random.Random(1605).shuffle(requests)  # nosec B311 - reproducible trial order.
    for i, r in enumerate(requests):
        r["id"] = f"A{i + 1:02}"
    expected = [
        {
            "case": c["id"],
            "arm": arm,
            "fields": {
                **c["expected"],
                **({"basis": "unknown", "scope": None} if arm == "text" else {}),
            },
        }
        for c in data["cases"]
        for arm in ("text", "capture")
    ]
    frozen = {
        **data,
        "requests": requests,
        "expectations": expected,
        "max_calls": 40,
        "model": "qwen3-coder",
        "temperature": 0,
        "provider_seed": None,
        "prompt": (Path(__file__).parent / "PROMPT.md").read_text(),
        "source_hashes": source_hashes(),
    }
    write(output / "frozen.json", frozen)
    write(output / "frozen-manifest.json", {"sha256": digest((output / "frozen.json").read_text())})
    write(output / "controls.json", run_probes(data))
    write(
        output / "reference.json",
        [
            {
                "case": c["id"],
                "annotation": reference(c),
                "release": accept(reference(c), c, data["receipts"], data["manifest"]),
            }
            for c in data["cases"]
        ],
    )
    return frozen


def live(output):
    raw = (output / "frozen.json").read_text()
    if digest(raw) != json.loads((output / "frozen-manifest.json").read_text())["sha256"]:
        raise ValueError("Frozen bundle changed")
    frozen = json.loads(raw)
    if source_hashes() != frozen["source_hashes"]:
        raise ValueError("Executing source changed")
    if len(frozen["requests"]) != 40 or frozen["max_calls"] != 40:
        raise ValueError("Call cap invalid")
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
            annotation, method = parse_diagnostic(row["text"])
            validate(annotation)
            row.update(annotation=annotation, parse_method=method)
            case = catalog[req["case"]]
            row["score"] = score(annotation, case, req["arm"])
            row["release"] = accept(annotation, case, frozen["receipts"], frozen["manifest"])
            row["justified_release_expected"] = case["expected_release"]
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
    parser.add_argument("--live", action="store_true", help="Allow up to 40 paid gateway calls")
    args = parser.parse_args()
    prepare(args.output)
    if args.live:
        live(args.output)
    from .viewer import render

    render(args.output, args.output / "walkthrough.html")
    print(args.output / "walkthrough.html")


if __name__ == "__main__":
    main()
