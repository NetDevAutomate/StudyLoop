"""Replay private real answers locally and export body-free aggregate measurements."""

import argparse
import html
import json
from pathlib import Path

from .pilot import ARMS, canonical, write
from .trial import coverage


def summarize(directory):
    rows = json.loads((directory / "answers.json").read_text())
    packs = json.loads((directory / "retrieval.json").read_text())
    labels = json.loads((directory / "labels.json").read_text())["groups"]
    report = {
        "answers": len(rows),
        "valid": sum(r["status"] == "valid" for r in rows),
        "units": "4 development questions; repeats are not independent cases",
        "arms": {},
        "coverage": [],
        "embedding": {},
    }
    embedding = json.loads((directory / "embedding.json").read_text())
    report["embedding"] = {k: embedding[k] for k in ("dimensions", "seconds", "records")}
    for p in packs:
        report["coverage"].append(
            {
                "question": p["question"],
                "arm": p["arm"],
                **coverage(p["ids"], labels[p["question"]]),
            }
        )
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        contexts = [p for p in packs if p["arm"] == arm]
        quotes = sum(r.get("checks", {}).get("citation_count", 0) for r in selected)
        bad = sum(r.get("checks", {}).get("bad_quote_or_id_count", 0) for r in selected)
        costs = [r["cost_usd"] for r in selected if r.get("cost_usd") is not None]
        report["arms"][arm] = {
            "calls": len(selected),
            "valid": sum(r["status"] == "valid" for r in selected),
            "mean_context_tokens": sum(p["pack_tokens"] for p in contexts) / len(contexts),
            "citations": quotes,
            "unlocatable_quotes": bad,
            "unsupported_validation_status": sum(
                r.get("checks", {}).get("unsupported_validation_status", False) for r in selected
            ),
            "negative_control_insufficient": sum(
                r["question"] == "Q4"
                and r.get("answer", {}).get("evidence_status") == "insufficient"
                for r in selected
            ),
            "gateway_reported_answer_cost_usd": sum(costs),
            "calls_with_cost": len(costs),
            "mean_answer_seconds": sum(r.get("elapsed_seconds", 0) for r in selected)
            / len(selected),
        }
    report["warning"] = "Category conformance and quote location are not semantic validation."
    return report


def render(directory, output):
    report = summarize(directory)
    rows = json.loads((directory / "answers.json").read_text())
    requests = {r["id"]: r for r in json.loads((directory / "requests.json").read_text())}
    labels = json.loads((directory / "labels.json").read_text())["groups"]
    corpus = json.loads((directory / "corpus.json").read_text())
    catalog = {r["id"]: r for r in corpus["records"]}
    esc = html.escape
    body = [
        "<!doctype html><html lang='en'><meta charset='utf-8'>",
        "<title>Stage 12: real context and answer replay</title>",
        "<style>body{font:17px/1.6 system-ui;max-width:1100px;margin:30px auto;padding:20px;",
        "background:#f8faf8;color:#172d35}summary{cursor:pointer;font-weight:650;padding:12px}",
        "details{border-top:1px solid #c9d5d8;margin:12px 0}pre{white-space:pre-wrap;",
        "overflow-wrap:anywhere;font:14px/1.5 ui-monospace;background:#edf2f2;padding:14px}",
        "blockquote{border-left:4px solid #519086;padding-left:16px}select{font:inherit}",
        ".bad{color:#9a3423}.notice{padding:16px;background:#fff1d7}</style>",
        "<h1>Which context helped—and what did the answer do with it?</h1>",
        "<p class='notice'>Private transcript replay. These are real development cases, ",
        "not a held-out quality score. All evidence is conversation reports. ",
        "An exact quote can still support the wrong conclusion.</p>",
        "<p>Start with Q3. Compare the retrieved plan against the missed results. ",
        "Then inspect the answer's claim and its exact supporting quote.</p>",
        "<label>Question <select id='filter'><option value='all'>All</option>",
        "<option>Q1</option><option>Q2</option><option>Q3</option><option>Q4</option>",
        "</select></label><details><summary>Mechanical measurements</summary><pre>",
        esc(json.dumps(report, indent=2)),
        "</pre></details>",
    ]
    for r in sorted(rows, key=lambda x: (x["question"], x["arm"], x["repeat"])):
        req = requests[r["id"]]
        answer = r.get("answer", {})
        label = f"{r['question']} · {r['arm']} · repeat {r['repeat'] + 1} · {r['id']}"
        body.extend(
            [
                f"<article data-q='{r['question']}'><details><summary>",
                esc(label),
                "</summary><h3>",
                esc(req["query"]),
                "</h3><p>",
                esc(answer.get("answer", "Invalid answer")),
                "</p><p><b>Limitations:</b> ",
                esc(answer.get("limitations", "")),
                "</p><p><b>Next check:</b> ",
                esc(answer.get("next_check", "")),
                "</p>",
            ]
        )
        by_id = {p["id"]: p for p in req["pack"]}
        for c in answer.get("citations", []):
            found = c["id"] in by_id and c["quote"] in by_id[c["id"]]["text"]
            body.extend(
                [
                    "<blockquote><b>",
                    esc(c["id"]),
                    " — ",
                    "exact quote found" if found else "QUOTE DOES NOT MATCH EXACTLY",
                    "</b><p>",
                    esc(c["quote"]),
                    "</p><p>Claim: ",
                    esc(c["supports"]),
                    "</p></blockquote>",
                ]
            )
        body.extend(
            [
                "<details><summary>What the model actually received</summary><pre>",
                esc(json.dumps(req["pack"], indent=2)),
                "</pre></details>",
                "<details><summary>Required facts and missed passages</summary>",
            ]
        )
        for group in labels[r["question"]]:
            matched = bool(set(group) & set(req["ids"]))
            body.extend(
                [
                    "<p><b>",
                    "COVERED" if matched else "MISSED",
                    "</b></p><pre>",
                    esc(
                        canonical(
                            [
                                {
                                    k: catalog[i][k]
                                    for k in ("id", "message", "start", "end", "text")
                                }
                                for i in group
                            ]
                        )
                    ),
                    "</pre>",
                ]
            )
        body.append("</details></details></article>")
    body.append(
        "<script>document.querySelector('#filter').onchange=e=>{document.querySelectorAll("
        "'article').forEach(a=>a.hidden=e.target.value!=='all'&&a.dataset.q!==e.target.value)"
        "}</script></html>"
    )
    with output.open("x") as stream:
        stream.write("".join(body))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = render(args.directory, args.output)
    write(args.output.with_suffix(".json"), result)
    print(json.dumps(result, indent=2))
