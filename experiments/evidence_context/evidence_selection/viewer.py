"""Local replay of actual evidence-replacement drafts; makes no model calls."""

import argparse
import html
import json
from pathlib import Path

from ..retrieval_matrix.pilot import write
from .runner import ARMS


def summarize(directory):
    rows = json.loads((directory / "answers.json").read_text())
    frozen = json.loads((directory / "frozen.json").read_text())
    requests = frozen["requests"]
    result = {
        "calls": len(rows),
        "valid": sum(r["status"] == "valid" for r in rows),
        "scope": "same four development questions; oracle reference selection",
        "arms": {},
        "contexts": [],
    }
    for arm in ARMS:
        chosen = [r for r in rows if r["arm"] == arm]
        costs = [r["cost_usd"] for r in chosen if r.get("cost_usd") is not None]
        result["arms"][arm] = {
            "calls": len(chosen),
            "valid": sum(r["status"] == "valid" for r in chosen),
            "citations": sum(r.get("checks", {}).get("citation_count", 0) for r in chosen),
            "bad_quotes": sum(r.get("checks", {}).get("bad_quote_or_id_count", 0) for r in chosen),
            "validated_status": sum(
                r.get("checks", {}).get("unsupported_validation_status", False) for r in chosen
            ),
            "answer_cost_usd": sum(costs),
            "cost_observed_calls": len(costs),
        }
    result["contexts"] = [
        {k: r[k] for k in ("question", "arm", "pack_tokens", "coverage")}
        for r in requests
        if r["repeat"] == 0
    ]
    return result


def render(directory, output):
    rows = json.loads((directory / "answers.json").read_text())
    frozen = json.loads((directory / "frozen.json").read_text())
    requests = {r["id"]: r for r in frozen["requests"]}
    grade_path = directory / "analyst-grades.json"
    grades = {r["id"]: r for r in json.loads(grade_path.read_text())} if grade_path.exists() else {}
    esc = html.escape
    parts = [
        "<!doctype html><html lang='en'><meta charset='utf-8'>",
        "<title>Stage 14 — Does the missing evidence change the answer?</title>",
        "<style>body{font:17px/1.65 system-ui;max-width:1100px;padding:24px;margin:auto;",
        "color:#183138;background:#fafcfb}details{border-top:1px solid #b8cfcd;margin:16px 0}",
        "summary{padding:12px 0;cursor:pointer;font-weight:650}pre{white-space:pre-wrap;",
        "overflow-wrap:anywhere;font:14px/1.6 ui-monospace;background:#edf4f2;padding:16px}",
        "blockquote{border-left:4px solid #458d87;padding-left:16px;margin-left:0}",
        ".notice{background:#fff0d2;padding:18px}.step{background:#e7f2ef;padding:16px}",
        "select{font:inherit}h1{line-height:1.2}small{color:#49686b}</style>",
        "<h1>Does the missing evidence change the answer?</h1>",
        "<p class='notice'>Private learning replay. These are unaccepted model drafts. ",
        "The reference passages were selected with known labels; this does not prove ",
        "an automatic retriever works. All source claims are conversation reports.</p>",
        "<p class='step'><b>Original context → reviewed results → reviewed results plus ",
        "nearby passages.</b><br>The prompt stays fixed. Compare the answer and the ",
        "specific evidence cited for it—not just the evidence-status label.</p>",
        "<p>Start with Q3. Notice whether cleanup is reported from a result or inferred ",
        "from a plan. Then inspect whether the port correction is in progress or complete.</p>",
        "<label>Question <select id='question'><option value='all'>All questions</option>",
        "<option>Q1</option><option>Q2</option><option>Q3</option><option>Q4</option></select>",
        "</label><details><summary>Measured results and limits</summary><pre>",
        esc(json.dumps(summarize(directory), indent=2)),
        "</pre></details>",
    ]
    for row in sorted(rows, key=lambda r: (r["question"], ARMS.index(r["arm"]), r["repeat"])):
        req = requests[row["id"]]
        answer = row.get("answer", {})
        grade = grades.get(row["id"], {})
        label = f"{row['question']} · {row['arm']} · repeat {row['repeat'] + 1} · {row['id']}"
        parts.extend(
            [
                f"<article data-q='{esc(row['question'])}'><details><summary>",
                esc(label),
                "</summary><h3>",
                esc(req["query"]),
                "</h3><small>",
                str(req["pack_tokens"]),
                " evidence tokens. Analyst assessment: ",
                esc(grade.get("grade", "pending")),
                " (not human ground truth).</small><p>",
                esc(grade.get("reason", "")),
                "</p><h4>Unaccepted model draft</h4><p>",
                esc(answer.get("answer", row.get("text", "No answer"))),
                "</p><p><b>Limitations:</b> ",
                esc(answer.get("limitations", "")),
                "</p><p><b>Next check:</b> ",
                esc(answer.get("next_check", "")),
                "</p>",
            ]
        )
        sources = {p["id"]: p for p in req["pack"]}
        for citation in answer.get("citations", []):
            found = (
                citation["id"] in sources and citation["quote"] in sources[citation["id"]]["text"]
            )
            parts.extend(
                [
                    "<blockquote><b>",
                    esc(citation["id"]),
                    ": ",
                    "exact quote located" if found else "exact quote mismatch",
                    "</b><p>",
                    esc(citation["quote"]),
                    "</p><p>Used to support: ",
                    esc(citation["supports"]),
                    "</p></blockquote>",
                ]
            )
        parts.extend(
            [
                "<details><summary>Exact context supplied</summary><pre>",
                esc(json.dumps(req["pack"], indent=2)),
                "</pre></details>",
                "<details><summary>Frozen scoring facets</summary><pre>",
                esc(json.dumps(frozen["spec"]["rubric"][row["question"]], indent=2)),
                "</pre></details></details></article>",
            ]
        )
    parts.append(
        "<script>document.querySelector('#question').onchange=e=>{document.querySelectorAll("
        "'article').forEach(a=>a.hidden=e.target.value!=='all'&&a.dataset.q!==e.target.value)"
        "}</script></html>"
    )
    with output.open("x") as stream:
        stream.write("".join(parts))
    write(output.with_suffix(".json"), summarize(directory))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.directory, args.output)
