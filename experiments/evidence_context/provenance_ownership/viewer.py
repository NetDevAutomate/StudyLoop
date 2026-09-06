"""Read-only local walkthrough; source text is always escaped."""

import argparse
import json
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(directory, output):
    def read(name):
        return json.loads((directory / name).read_text())

    rows = read("replay.json")
    cards = []
    for row in rows:
        if row["status"] != "evaluated":
            cards.append("<article>" + block(row) + "</article>")
            continue
        after = row["after"]
        cards.append(
            '<article class="case" data-case="'
            + escape(row["case"])
            + '">'
            + "<h3>"
            + escape(row["id"] + " · " + row["case"] + " · " + row["arm"])
            + "</h3>"
            + "<p>Legacy release: "
            + str(row["before"]["released"])
            + " · Source-owned release: "
            + str(after["released"])
            + "</p>"
            + "<details><summary>Original proposal</summary>"
            + block(row["original_annotation"])
            + "</details><details><summary>What code changed, and why</summary>"
            + block(after)
            + "</details></article>"
        )
    options = "".join(
        "<option>" + escape(c) + "</option>"
        for c in sorted({r["case"] for r in rows if "case" in r})
    )
    controls = "".join(
        '<details class="control"><summary>'
        + escape(r["name"])
        + (" · SEMANTIC ERROR REMAINS" if r["false_semantic_release"] else "")
        + "</summary>"
        + block(r)
        + "</details>"
        for r in read("controls.json")
    )
    fresh = "".join(
        '<details class="fresh"><summary>'
        + escape(r["source"]["id"])
        + "</summary>"
        + block(r)
        + "</details>"
        for r in read("fresh.json")
    )
    page = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage 17 · Who owns the labels?</title><style>
body{font:17px/1.6 system-ui;color:#20303a;background:#faf9f5;
max-width:1000px;margin:40px auto;padding:0 22px}
h1,h2,h3{line-height:1.2}article{border-top:2px solid #bdd2d0;padding:22px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 ui-monospace,monospace;
background:#edf1f3;padding:16px;border-radius:8px}
summary{cursor:pointer;padding:10px 0}
select{font:inherit;padding:8px}
.notice{background:#fff0cd;padding:18px;border-radius:10px}
[hidden]{display:none!important}
</style><h1>Who owns the labels?</h1>
<p>Source facts come from capture and explicit configuration.
The original interpretation remains visible.</p>
<p class="notice">This is deterministic replay of saved drafts,
or an offline reference demonstration.
No new model calls occur. The legacy renderer still accepts
two wrong narrative meanings.
Correct metadata does not certify interpretation.</p>
"""
    page += (
        "<details><summary>Measurements and limits</summary>"
        + block(read("summary.json"))
        + "</details>"
    )
    page += (
        '<h2>Before and after</h2><label for="filter">Case </label><select id="filter">'
        '<option value="all">All cases</option>' + options + "</select>" + "".join(cards)
    )
    page += "<h2>Repairs and remaining semantic errors</h2>" + controls
    page += (
        "<h2>Fresh authority boundaries</h2><p>These eight synthetic fixtures "
        "expose source-owned facts separately from unverified proposals. "
        "Command completion never establishes application success.</p>" + fresh
    )
    page += """<script>document.getElementById('filter').addEventListener('change',e=>{
 document.querySelectorAll('.case').forEach(c=>{
 c.hidden=e.target.value!=='all'&&c.dataset.case!==e.target.value;
 });
});</script></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.directory, args.output)


if __name__ == "__main__":
    main()
