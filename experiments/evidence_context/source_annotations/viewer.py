"""Read-only replay separating annotation measurements from release and integrity."""

import argparse
import json
from pathlib import Path

from ..assertion_gate.viewer import block, escape, read
from .annotation import score
from .capture import resolve, write


def summarize(directory):
    frozen = read(directory, "frozen.json")
    rows = read(directory, "answers.json") if (directory / "answers.json").exists() else []
    controls = read(directory, "controls.json")
    result = {
        "calls": len(rows),
        "annotation": {},
        "release": {},
        "controls": {
            "count": len(controls),
            "ordinary_matches": sum(r["matches"] for r in controls if not r["known_gap"]),
            "known_semantic_failures": sum(not r["matches"] for r in controls if r["known_gap"]),
            "integrity_only_accepts": sum(r["integrity_only_accepts"] for r in controls),
            "source_gate_accepts": sum(r["source_gate_accepts"] for r in controls),
        },
    }
    result["conditions"] = []
    for arm in ("text", "capture"):
        subset = [r for r in rows if r["arm"] == arm]
        valid = [r for r in subset if r["status"] == "valid"]
        result["annotation"][arm] = {
            "responses": len(subset),
            "valid": len(valid),
            "all_fields_match": sum(r["score"]["all_fields_match"] for r in valid),
            "field_matches": {
                k: sum(r["score"]["field_matches"][k] for r in valid)
                for k in ("state", "basis", "target", "scope")
            },
            "quote_bound": sum(r["score"]["quote_bound"] for r in valid),
            "unsupported_basis": sum(r["score"]["unsupported_basis"] for r in valid),
            "state_promotion": sum(r["score"]["state_promotion"] for r in valid),
            "target_invention": sum(r["score"]["target_invention"] for r in valid),
            "cost_usd": round(sum(r.get("cost_usd") or 0 for r in subset), 6),
        }
        result["release"][arm] = {
            "full_capture_justified_instances": sum(c["expected_release"] for c in frozen["cases"])
            * 2,
            "justified_released": sum(
                r["release"]["released"] and r["justified_release_expected"] for r in valid
            ),
            "unexpected_released": sum(
                r["release"]["released"] and not r["justified_release_expected"] for r in valid
            ),
            "released": sum(r["release"]["released"] for r in valid),
        }
        baseline = [
            score(
                {
                    "state": "unknown",
                    "basis": "unknown",
                    "scope": None,
                    "target": None,
                    "quote": c["record"]["text"],
                    "rationale": "Constant unknown baseline",
                },
                c,
                arm,
            )
            for c in frozen["cases"]
        ]
        result["annotation"][arm]["constant_unknown_baseline_per_10_cases"] = {
            k: sum(r["field_matches"][k] for r in baseline)
            for k in ("state", "basis", "target", "scope")
        }
    for r in rows:
        result["conditions"].append(
            {k: r.get(k) for k in ("id", "case", "arm", "repeat", "status", "score", "release")}
        )
    return result


def render(directory, output):
    frozen = read(directory, "frozen.json")
    catalog = {c["id"]: c for c in frozen["cases"]}
    live = (directory / "answers.json").exists()
    rows = read(directory, "answers.json" if live else "reference.json")
    summary = summarize(directory)
    cards = []
    for index, row in enumerate(rows):
        c = catalog[row["case"]]
        receipt, error = resolve(c["record"], frozen["receipts"], frozen["manifest"])
        label = f"{row.get('id', index + 1)} · {c['id']} · {row.get('arm', 'reference')}"
        release = row.get("release", {"text": "Response failed; no release"})
        source = {"body": c["record"]["text"], "capture_error": error, "verified_receipt": receipt}
        cards.append(
            f'<article class="case" data-case="{escape(c["id"])}">'
            f"<h3>{escape(label)}</h3><p>{escape(c['question'])}</p>"
            "<details><summary>1 · Source and captured origin</summary>"
            + block(source)
            + "</details><details><summary>2 · Annotation and rationale</summary>"
            + block(row.get("annotation", row.get("text", "No annotation")))
            + "</details><h4>3 · Source check and unchanged release renderer</h4>"
            + '<p class="release">'
            + escape(release["text"])
            + "</p>"
            + "<details><summary>4 · Expected fields, score and release decision</summary>"
            + block(
                {
                    "expected_by_arm": [e for e in frozen["expectations"] if e["case"] == c["id"]],
                    "score": row.get("score"),
                    "decision": release,
                }
            )
            + "</details></article>"
        )
    options = "".join(f'<option value="{escape(cid)}">{escape(cid)}</option>' for cid in catalog)
    controls = "".join(
        '<details class="control"><summary>'
        + escape(r["name"])
        + (" — SEMANTIC GAP SURVIVES" if r["known_gap"] else "")
        + "</summary>"
        + block(r)
        + "</details>"
        for r in read(directory, "controls.json")
    )
    document = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage 16 · Grounding annotations</title><style>
body{font:17px/1.55 system-ui,sans-serif;color:#20303a;background:#faf9f5;
max-width:1000px;margin:40px auto;padding:0 22px}h1,h2,h3{line-height:1.2}
article{border-top:2px solid #bdd2d0;padding:24px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 ui-monospace,monospace;
background:#edf1f3;padding:16px;border-radius:8px}summary{cursor:pointer;padding:10px 0}
.release{white-space:pre-wrap;border-left:5px solid #188078;padding:12px 20px;background:#e9f4f0}
.notice{background:#fff0cd;padding:18px;border-radius:10px}select{font:inherit;padding:8px}
[hidden]{display:none!important}</style><h1>Where did this label come from?</h1>"""
    document += (
        "<p>"
        + ("Actual 40-call annotation trial" if live else "Offline reference demo — no model calls")
        + "</p>"
    )
    document += (
        "<p>Compare real_exit with quoted_report: identical text, different captured origin.</p>"
    )
    document += '<p class="notice">These local processes emit fixture text. Their receipts prove '
    document += "neither application correctness nor the truth of narrative interpretations. "
    document += "Completed means command execution ended, including a failing command. "
    document += "This does not test installed coding-harness exporters.</p>"
    document += (
        "<details><summary>Frozen annotation prompt</summary>"
        + block(frozen["prompt"])
        + "</details>"
    )
    document += (
        "<details><summary>Annotation measurements (information-available expectations)</summary>"
    )
    document += block(summary["annotation"]) + "</details>"
    document += "<details><summary>Release coverage (a separate adapter measurement)</summary>"
    document += "<p>The text arm lacks origin and scope by construction. Its release loss is not "
    document += (
        "a reasoning failure. Per-field successes and explanation usefulness are different.</p>"
    )
    document += block(summary["release"]) + "</details><h2>Walk through the sources</h2>"
    document += '<label for="filter">Case </label><select id="filter">'
    document += '<option value="all">All cases</option>'
    document += options + "</select>" + "".join(cards)
    document += "<h2>Integrity versus semantic correctness</h2>" + controls
    document += """<script>
document.getElementById('filter').addEventListener('change', e => {
 document.querySelectorAll('.case').forEach(c => {
  c.hidden = e.target.value !== 'all' && c.dataset.case !== e.target.value;
 });
});
</script></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = render(args.directory, args.output)
    write(args.directory / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "conditions"}, indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
