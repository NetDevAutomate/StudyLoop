"""Post-hoc diagnosis of saved synthetic responses; no gateway or database writes.

The strict pilot remains authoritative for end-to-end acceptance. This diagnostic
may unwrap one complete Markdown JSON fence to inspect labels and quote bindings.
It does not accept reviews into memory or certify semantic correctness.
"""

import argparse
import json
import re
from pathlib import Path


def audit(directory: Path) -> dict:
    frozen = json.loads((directory / "frozen.json").read_text())
    cases = {case["case_id"]: case for case in frozen["cases"]}
    responses = json.loads((directory / "model-responses.json").read_text())
    rows = []
    for response in responses:
        row = {"model": response["model"], "diagnostic_only": True}
        try:
            raw = response["response"]
            if raw["finish_reason"] != "stop":
                raise ValueError("Unfinished response")
            text = raw["text"].strip()
            fenced = re.fullmatch(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
            row["single_json_fence_removed"] = fenced is not None
            parsed = json.loads(fenced[1] if fenced else text)
            if not isinstance(parsed, dict) or set(parsed) != {"reviews"}:
                raise ValueError("Wrong response fields")
            items = parsed["reviews"]
            if len(items) != len(cases) or {r["case_id"] for r in items} != cases.keys():
                raise ValueError("Missing or duplicate cases")
            labels = []
            for item in items:
                case = cases[item["case_id"]]
                allowed = {s["citation"]["evidence_id"]: s["citation"] for s in case["sources"]}
                bound = bool(item["citations"])
                for citation in item["citations"]:
                    source = allowed.get(citation["evidence_id"])
                    start, end = citation["start"], citation["end"]
                    bound &= bool(
                        source
                        and type(start) is int
                        and type(end) is int
                        and 0 <= start < end <= len(source["quote"])
                        and source["quote"][start:end] == citation["quote"]
                    )
                labels.append(
                    {
                        "case_id": item["case_id"],
                        "verdict": item["verdict"],
                        "within_predeclared_range": item["verdict"] in case["accepted_verdicts"],
                        "quotes_bound_to_supplied_case": bound,
                    }
                )
            row["labels"] = labels
        except (KeyError, ValueError, TypeError) as error:
            row["error_type"] = type(error).__name__
        rows.append(row)
    return {
        "post_hoc": True,
        "new_gateway_calls": 0,
        "database_writes": 0,
        "strict_pilot_results_unchanged": True,
        "semantic_certification": "not_established",
        "records": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), indent=2))


if __name__ == "__main__":
    main()
