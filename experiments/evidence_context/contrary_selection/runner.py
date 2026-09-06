"""Compare fixed packing policies on the same authorized synthetic evidence."""

import argparse
import json
import os
import sqlite3
from dataclasses import replace
from pathlib import Path

from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.public import open_context
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.selection import POLICIES, EvidencePool, select, size
from agent_session_tools.context.store import ContextStore, NativeSource

from ..assertion_gate.viewer import block, escape
from ..native_capture.runner import database

CASES = [
    {"name": "two_slots", "lexical": 12, "sources": 2, "budget": 16384, "contrary": 1},
    {"name": "three_slots", "lexical": 12, "sources": 3, "budget": 16384, "contrary": 1},
    {"name": "six_slots", "lexical": 12, "sources": 6, "budget": 32768, "contrary": 1},
    {"name": "byte_pressure", "lexical": 12, "sources": 12, "budget": 8192, "contrary": 1},
    {"name": "larger_byte_budget", "lexical": 12, "sources": 12, "budget": 12288, "contrary": 1},
    {
        "name": "long_quotes",
        "lexical": 10,
        "sources": 8,
        "budget": 16384,
        "contrary": 1,
        "long": True,
    },
    {
        "name": "multi_source_group",
        "lexical": 10,
        "sources": 4,
        "budget": 32768,
        "contrary": 1,
        "extra": 2,
    },
    {
        "name": "group_cannot_fit",
        "lexical": 10,
        "sources": 3,
        "budget": 32768,
        "contrary": 1,
        "extra": 2,
    },
    {"name": "several_contrary", "lexical": 12, "sources": 3, "budget": 32768, "contrary": 5},
    {
        "name": "proposed_correction",
        "lexical": 12,
        "sources": 2,
        "budget": 16384,
        "contrary": 1,
        "relation": "corrects",
    },
    {"name": "no_proposed_relation", "lexical": 12, "sources": 3, "budget": 16384, "contrary": 0},
    {"name": "all_fit", "lexical": 2, "sources": 12, "budget": 32768, "contrary": 1},
]


def prepare(root, case):
    config = {
        "database": {"path": str(root / "sessions.db")},
        "memory": {
            "default_scope": "personal",
            "projects": {"lesson": {"scope": "personal", "roots": ["/fixture/lesson"]}},
        },
    }
    (root / "config.json").write_text(json.dumps(config))
    os.environ["STUDYLOOP_CONFIG"] = str(root / "config.json")
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    conn = database(root / "sessions.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO sessions(id,source,project_path) VALUES ('s','codex','/fixture/lesson')"
    )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(config), actor="lesson", dry_run=False)
    store = ContextStore(conn)
    base = NativeSource(
        session_id="s",
        native_key="anchor",
        harness="codex",
        native_kind="message:assistant",
        native_locator="fixture.jsonl#line/1",
        parser_version="fixture",
        machine_id="fictional-machine",
        body="cache",
        origin=Origin.CONVERSATION,
        recorded_at="2026-09-01T12:00:00Z",
    )
    anchor = store.capture(base)
    bodies = {anchor: base.body}
    for i in range(case["lexical"] - 1):
        value = replace(base, native_key=f"lexical-{i}", body="cache " + "detail " * 160)
        bodies[store.capture(value)] = value.body
    supporting = []
    for i in range(case.get("extra", 0)):
        value = replace(base, native_key=f"support-{i}", body=f"Additional source {i}.")
        eid = store.capture(value)
        bodies[eid] = value.body
        supporting.append(eid)
    opponents = []
    for i in range(case["contrary"]):
        value = replace(
            base,
            native_key=f"contrary-{i}",
            harness="kiro_cli",
            body=f"Alternative {i}: " + "relationship " * (130 if case.get("long") else 3),
        )
        eid = store.capture(value)
        bodies[eid] = value.body
        opponents.append(eid)
    with open_context(root / "sessions.db", write=True) as context:

        def propose(ids, statement):
            return context.propose(
                statement=statement,
                state="unknown",
                target=None,
                producer="fixture",
                citations=[
                    {"evidence_id": eid, "start": 0, "end": len(bodies[eid]), "quote": bodies[eid]}
                    for eid in ids
                ],
            )["assertion_id"]

        first = propose([anchor], "Original recommendation") if opponents else None
        for i, eid in enumerate(opponents):
            second = propose([eid, *supporting], f"Proposed alternative {i}")
            context.relate(second, first, case.get("relation", "contradicts"), producer="fixture")
    with open_context(root / "sessions.db") as context:
        envelope = context.search("cache", max_sources=40, budget_bytes=131072)
    assert envelope["coverage"]["limits_reached"] == []
    sources = {s["id"]: s for s in envelope["sources"]}
    # Reapply the database's lexical ranking; packing order is the variable under test.
    lexical = [
        row[0]
        for row in conn.execute(
            "SELECT e.id FROM context_evidence_fts f JOIN context_evidence e ON e.rowid=f.rowid "
            "WHERE context_evidence_fts MATCH 'cache' ORDER BY bm25(context_evidence_fts),e.id"
        )
    ]
    assert lexical[0] == anchor
    conn.close()
    base_envelope = {
        k: v
        for k, v in envelope.items()
        if k
        not in {
            "sources",
            "assertions",
            "relationships",
            "snapshot_id",
            "response_bytes",
            "selection_policy",
            "context_status",
            "conflict_review",
        }
    }
    pool = EvidencePool(
        base_envelope,
        sources,
        lexical,
        [],
        {a["id"]: a for a in envelope["assertions"]},
        envelope["relationships"],
        set(),
    )
    return pool, bodies


def run(output):
    previous = {key: os.environ.get(key) for key in ("STUDYLOOP_CONFIG", "SESSION_CONTEXT_SCOPE")}
    rows = []
    try:
        for case in CASES:
            root = output / case["name"]
            root.mkdir()
            pool, bodies = prepare(root, case)
            outputs = {}
            for policy in POLICIES:
                pack = select(pool, case["sources"], case["budget"], policy=policy)
                ids = {s["id"] for s in pack["sources"]}
                aids = {a["id"] for a in pack["assertions"]}
                assert size(pack) <= case["budget"]
                assert len(ids) <= case["sources"]
                for source in pack["sources"]:
                    c = source["citation"]
                    assert bodies[source["id"]][c["start"] : c["end"]] == c["quote"]
                for edge in pack["relationships"]:
                    assert {edge["from_assertion"], edge["to_assertion"]} <= aids
                for assertion in pack["assertions"]:
                    assert {c["evidence_id"] for c in assertion["citations"]} <= ids
                outputs[policy] = {
                    "contrary_groups": len(pack["relationships"]),
                    "lexical_sources": len(ids.intersection(pool.lexical_ids)),
                    "anchor_retained": pool.lexical_ids[0] in ids,
                    "response_bytes": size(pack),
                    "status": pack["context_status"],
                    "conflict_review": pack["conflict_review"],
                    "limits": pack["coverage"]["limits_reached"],
                }
                (root / f"{policy}.json").write_text(json.dumps(pack, indent=2))
            rows.append({"case": case, "results": outputs})
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    report = {
        "cases": rows,
        "claims": {
            "semantic_accuracy": "not_measured",
            "relation_labels": "synthetic_unverified_proposals",
            "comparison": "same discovered evidence; full group dependencies; fixed budgets",
        },
    }
    (output / "results.json").write_text(json.dumps(report, indent=2))
    table = "".join(
        "<tr><td>"
        + escape(row["case"]["name"].replace("_", " "))
        + "</td>"
        + "".join(
            f"<td>{row['results'][p]['contrary_groups']} / "
            f"{row['results'][p]['lexical_sources']}</td>"
            for p in POLICIES
        )
        + "</tr>"
        for row in rows
    )
    html = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage24 · Keeping both sides</title><style>"
        "body{font:18px/1.6 system-ui;max-width:1050px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}table{width:100%;border-collapse:collapse}"
        "th,td{text-align:left;padding:.5rem;border-bottom:1px solid #cadbd5;"
        "overflow-wrap:anywhere}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 monospace}"
        "</style><h1>Keeping both sides in a limited context</h1>"
        "<p>Each cell shows complete proposed disagreement groups / lexical sources.</p>"
        "<p>The labels are fictional. More returned relationships "
        "does not establish better answers.</p>"
        "<table><tr><th>Case</th>"
        + "<th>Lexical first</th><th>20% reserve</th><th>Complete groups</th>"
        + "</tr>"
        + table
        + "</table><details><summary>Inspect every measurement</summary>"
        + block(report)
        + "</details></html>"
    )
    (output / "walkthrough.html").write_text(html)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = run(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": len(result["cases"]),
                "groups_retained": {
                    policy: sum(
                        row["results"][policy]["contrary_groups"] for row in result["cases"]
                    )
                    for policy in POLICIES
                },
            }
        )
    )


if __name__ == "__main__":
    main()
