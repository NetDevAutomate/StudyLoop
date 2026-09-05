"""Offline walkthrough of source, model claim, code release and trust-gap controls."""

import argparse
import html
import json
from pathlib import Path


def read(directory, name):
    return json.loads((directory / name).read_text())


def escape(value):
    return html.escape(str(value))


def block(value):
    return "<pre>" + escape(json.dumps(value, indent=2, ensure_ascii=False)) + "</pre>"


def summarize(directory):
    frozen = read(directory, "frozen.json")
    rows = read(directory, "answers.json") if (directory / "answers.json").exists() else []
    summary = {"calls": len(rows), "arms": {}, "cases": []}
    for arm in ("raw", "annotated"):
        subset = [r for r in rows if r["arm"] == arm]
        valid = [r for r in subset if r["status"] == "valid"]
        summary["arms"][arm] = {
            "responses": len(subset),
            "valid": len(valid),
            "all_expected_ids_released": sum(
                not r["omitted_justified_ids"] and not r["unexpected_accepted_ids"] for r in valid
            ),
            "omitted_ids": sum(len(r["omitted_justified_ids"]) for r in valid),
            "unexpected_ids": sum(len(r["unexpected_accepted_ids"]) for r in valid),
            "blocked_claims": sum(len(r["gate"]["blocked"]) for r in valid),
            "cost_usd": round(sum(r.get("cost_usd") or 0 for r in subset), 6),
        }
    for c in frozen["cases"]:
        entry = {"case": c["id"], "expected_ids": c["expected_ids"], "conditions": []}
        for r in rows:
            if r["case"] != c["id"]:
                continue
            entry["conditions"].append(
                {
                    "id": r["id"],
                    "arm": r["arm"],
                    "repeat": r["repeat"],
                    "status": r["status"],
                    "accepted": [a["assertion_id"] for a in r.get("gate", {}).get("accepted", [])],
                    "blocked": [a["reason"] for a in r.get("gate", {}).get("blocked", [])],
                    "omitted": r.get("omitted_justified_ids"),
                }
            )
        summary["cases"].append(entry)
    probes = read(directory, "probes.json")
    summary["controls"] = {
        "total": len(probes),
        "ordinary_matches": sum(r["matches"] for r in probes if not r["trust_gap"]),
        "declared_semantic_gaps": sum(not r["matches"] for r in probes if r["trust_gap"]),
        "advisory_prose_leaks": sum(r["advisory_prose_leaked"] for r in probes),
    }
    return summary


def render(directory, output):
    frozen = read(directory, "frozen.json")
    catalog = {c["id"]: c for c in frozen["cases"]}
    summary = summarize(directory)
    live_path = directory / "answers.json"
    rows = (
        read(directory, "answers.json") if live_path.exists() else read(directory, "reference.json")
    )
    mode = "Actual model trial" if live_path.exists() else "Offline reference demo — no model calls"
    cards = []
    for index, r in enumerate(rows):
        c = catalog[r["case"]]
        gate = r.get("gate", {})
        labels = f"{r.get('id', index + 1)} · {r['case']} · {r.get('arm', 'reference')}"
        sources = "".join(
            "<details><summary>"
            + escape(a["id"])
            + " source and reviewed labels</summary>"
            + block(a)
            + "</details>"
            for a in c["assertions"]
        )
        rendered = escape(gate.get("text", "No release: response failed."))
        qualification = escape(gate.get("qualification", ""))
        diagnostics = {
            "gate": gate,
            "omitted": r.get("omitted_justified_ids"),
            "status": r.get("status", "reference"),
        }
        cards.append(
            f'<article class="case" data-case="{escape(c["id"])}">'
            f"<h3>{escape(labels)}</h3><p>{escape(c['question'])}</p>"
            f'<p class="muted">{escape(c["provenance"])}; expected IDs: '
            f"{escape(c['expected_ids'])}</p><details><summary>1 · Inspect evidence</summary>"
            f"{sources}</details><details><summary>2 · Inspect model draft (advisory)</summary>"
            f"{block(r.get('draft', 'Offline reference, not a model draft'))}"
            f"{block(r.get('text', ''))}</details>"
            f'<h4>3 · Code-owned release</h4><p class="release">{rendered}</p>'
            f'<p class="muted">{qualification}</p>'
            f"<details><summary>4 · Accepted, blocked and omitted claims</summary>"
            f"{block(diagnostics)}"
            f"</details></article>"
        )
    probes = "".join(
        '<details class="probe"><summary>'
        + escape(r["name"])
        + (" — KNOWN TRUST GAP" if r["trust_gap"] else "")
        + "</summary>"
        + block(r)
        + "</details>"
        for r in read(directory, "probes.json")
    )
    options = "".join(f'<option value="{escape(cid)}">{escape(cid)}</option>' for cid in catalog)
    document = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage 15 · Evidence claims</title>
<style>
body{font:17px/1.55 system-ui,sans-serif;color:#202c39;background:#faf9f5;
max-width:1000px;margin:40px auto;padding:0 22px}
h1,h2,h3{line-height:1.2}h1{font-size:2.2rem}article{border-top:2px solid #bdd2d0;padding:24px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;
font:14px/1.5 ui-monospace,monospace;
background:#edf1f3;padding:16px;border-radius:8px}
summary{cursor:pointer;padding:10px 0}details details{margin-left:20px}
.muted{color:#536575;font-size:.92em}
.release{white-space:pre-wrap;border-left:5px solid #188078;padding:12px 20px;background:#e9f4f0}
.notice{background:#fff0cd;padding:18px;border-radius:10px}select{font:inherit;padding:8px;max-width:100%}
[hidden]{display:none!important}
</style><h1>What does the evidence actually establish?</h1>"""
    document += f"<p>{escape(mode)}</p>"
    document += "<p>Follow source → typed claim → code check → attributed statement. "
    document += "Start with separate_events.</p>"
    document += '<p class="notice">This gate checks agreement with reviewed labels. '
    document += "It does not prove those labels, "

    document += (
        "the event, or tool authenticity. Simulated observed fixtures are labelled examples. "
    )
    document += "The two forgery controls below deliberately demonstrate this limit.</p>"
    document += (
        "<details><summary>Read the frozen prompt</summary>"
        + block(frozen["prompt"])
        + "</details>"
    )
    document += "<details><summary>Measurements and interpretation limits</summary>"
    document += "<p>Raw identical-text cases omit "
    document += "the information needed to distinguish their bases. "
    document += "Annotated cases disclose the expected labels. "
    document += (
        "Counts measure conditional conformance, not general reasoning accuracy.</p>"
        + block(summary)
        + "</details>"
    )
    document += (
        '<h2>Walk through the cases</h2><label for="filter">Case </label><select id="filter">'
    )
    document += '<option value="all">All cases</option>' + options + "</select>" + "".join(cards)
    document += "<h2>Boundary and forgery controls</h2>" + probes
    document += """<script>
const filter = document.getElementById('filter');
filter.addEventListener('change', () => {
 document.querySelectorAll('.case').forEach(card => {
  card.hidden = filter.value !== 'all' && card.dataset.case !== filter.value;
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
    print(json.dumps(summary, indent=2))
    print("Walkthrough:", args.output)


if __name__ == "__main__":
    main()
