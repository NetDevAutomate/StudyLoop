"""Post-run diagnostic only: preserve strict results and strip one complete JSON fence."""

import argparse
import html
import json
import re
from pathlib import Path

from .verify import assess_answer

FENCE = re.compile(r"```(?:json)?\r?\n(.*?)\r?\n```", re.DOTALL)


def parse_diagnostic(text):
    try:
        return json.loads(text), "original_json"
    except json.JSONDecodeError:
        match = FENCE.fullmatch(text.strip())
        if match is None:
            raise ValueError("Not a single complete JSON fence") from None
        return json.loads(match[1]), "complete_fence_removed"


def audit(directory):
    report = json.loads((directory / "results.json").read_text())
    frozen = json.loads((directory / "frozen.json").read_text())
    cases = {c["id"]: c for c in frozen["cases"]}
    rows = []
    for original in report["rows"]:
        if original["phase"] != "answer":
            continue
        row = {k: original[k] for k in ("case", "arm", "repeat", "status")}
        try:
            answer, method = parse_diagnostic(original["text"])
            row.update(answer=answer, method=method)
            row["checks"] = assess_answer(answer, cases[row["case"]])
        except (ValueError, KeyError, TypeError) as error:
            row.update(error_type=type(error).__name__, checks={"invalid_response": True})
        rows.append(row)
    summary = {}
    for arm in ("raw", "extracted", "candidate", "checked"):
        selected = [r for r in rows if r["arm"] == arm]
        summary[arm] = {
            "answers": len(selected),
            "strict_json_parsed": sum(r["status"] == "parsed" for r in selected),
            "diagnostic_schema_valid": sum(
                not r["checks"].get("invalid_response") for r in selected
            ),
            **{
                key: sum(bool(r["checks"].get(key)) for r in selected)
                for key in ("choice_matches", "unsupported_endorsement", "citations_locatable")
            },
        }
    return {"post_hoc_diagnostic": True, "summary": summary, "rows": rows}


def render(result, path):
    parts = [
        "<!doctype html><html lang='en'><meta charset='utf-8'>",
        "<title>Stage 10 — Actual answer replay</title>",
        "<style>body{font:18px/1.6 system-ui;max-width:1000px;margin:40px auto;padding:20px}",
        "summary{cursor:pointer;padding:10px}pre{white-space:pre-wrap}</style>",
        "<h1>Actual answers: post-run formatting diagnostic</h1>",
        "<p>Only complete Markdown fences were removed. No answers rewritten or rerun. ",
        "These are synthetic draft decisions, not validated recommendations. ",
        "Quote location does not establish that a quote supports a claim.</p>",
        "<pre>" + html.escape(json.dumps(result["summary"], indent=2)) + "</pre>",
    ]
    for row in result["rows"]:
        label = f"{row['case']} / {row['arm']} / repeat {row['repeat']}"
        parts.append(
            "<details><summary>"
            + html.escape(label)
            + "</summary><pre>"
            + html.escape(json.dumps(row, indent=2))
            + "</pre></details>"
        )
    path.write_text("".join(parts) + "</html>\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.input)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    render(result, args.output.with_suffix(".html"))
    print(json.dumps(result["summary"], indent=2))
