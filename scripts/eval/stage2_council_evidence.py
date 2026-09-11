"""Stage 2 council evidence: per-question census transitions and gate counters.

Answers the Stage 2 single-seat findings F3, F4 and F5 with artefacts rather
than prose. Everything here reads the live database read-only and the two
committed receipts; it writes one sidecar receipt.

Run from the repo root:
    uv run --group dev python scripts/eval/stage2_council_evidence.py
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from agent_session_tools.eval import K
from agent_session_tools.eval.arms import _frozen_escape_fts_query, build_arm
from agent_session_tools.eval.census import collect_questions
from agent_session_tools.eval.seam import ArmError, Query
from agent_session_tools.retrieval import plan_query

ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "docs/architecture/session-memory/receipts/semantic-layer"
DB = Path.home() / ".config/studyloop/sessions.db"
GOLDEN = "packages/agent-session-tools/tests/golden/session_search_pre_planner.json"


def sessions(arm, question) -> list[str] | str:
    query = Query(text=question.text, exclude_message_ids=frozenset({question.message_id}))
    try:
        return [hit.session_id for hit in arm.search(query, K)]
    except ArmError as exc:
        return f"CRASH:{exc.kind}"


def census_transitions() -> dict:
    """Every eligible question through both arms; classify the pair and the mechanism."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    questions = collect_questions(conn, k=K)
    live, frozen = build_arm("mcp", DB, K), build_arm("frozen", DB, K)
    classes: Counter = Counter()
    transitions: Counter = Counter()
    mechanism: Counter = Counter()
    rows = []
    t0 = time.perf_counter()
    for q in questions:
        f, m = sessions(frozen, q), sessions(live, q)
        f_hit = isinstance(f, list) and q.session_id in f
        m_hit = isinstance(m, list) and q.session_id in m
        if isinstance(f, str):
            cls = "frozen_crash"
        elif f == [] and m:
            cls = "frozen_empty_live_rows"
        elif f == m:
            cls = "identical"
        else:
            cls = "different_lists"
        # Mechanism, read from the frozen code itself, not inferred: what MATCH
        # string did the shipped escape produce for this text?
        escaped = _frozen_escape_fts_query(q.text)
        whole_text_phrase = (
            escaped.startswith('"') and escaped.endswith('"') and " " in escaped and '"' in q.text
        )
        if cls == "frozen_empty_live_rows":
            mechanism["whole_question_as_one_phrase" if whole_text_phrase else "other"] += 1
        classes[cls] += 1
        transitions[(cls, f_hit, m_hit)] += 1
        rows.append(
            {
                "message_id": q.message_id,
                "session_id": q.session_id,
                "source": q.source,
                "class": cls,
                "frozen_hit": f_hit,
                "live_hit": m_hit,
                "frozen_match": escaped if cls != "frozen_crash" else None,
                "live_plan": plan_query(q.text).queries[:1],
            }
        )
    elapsed = time.perf_counter() - t0
    regressions = [r for r in rows if r["frozen_hit"] and not r["live_hit"]]
    return {
        "n": len(rows),
        "elapsed_s": round(elapsed, 1),
        "classes": dict(classes),
        "transitions": {
            f"{c}|frozen_hit={fh}|live_hit={mh}": n for (c, fh, mh), n in transitions.items()
        },
        "frozen_empty_mechanism": dict(mechanism),
        "regressions": len(regressions),
        "regression_ids": [r["message_id"] for r in regressions][:50],
        "hit_at_5": {
            "frozen": round(sum(r["frozen_hit"] for r in rows) / len(rows), 4),
            "live": round(sum(r["live_hit"] for r in rows) / len(rows), 4),
        },
        "per_question": rows,
    }


def gold_counters() -> dict:
    g = json.loads((RECEIPTS / "stage2-gold.json").read_text())
    arms = g["arms"]
    m, c, f = arms["mcp"]["per_item"], arms["cli"]["per_item"], arms["frozen"]["per_item"]
    return {
        "cli_mcp_identical_ordered_lists": sum(1 for k in m if m[k]["ranked"] == c[k]["ranked"]),
        "items": len(m),
        "frozen_crashers": sum(1 for k in f if f[k].get("error_kind")),
        "frozen_crash_and_live_hit_at_5": sum(
            1 for k in f if f[k].get("error_kind") and m[k]["hit"]
        ),
        "moved_outside_crash_class": sorted(
            k
            for k in m
            if not f[k].get("error_kind")
            and (m[k]["rank"], m[k]["hit"]) != (f[k]["rank"], f[k]["hit"])
        ),
    }


def golden_projection(before: str, after: str) -> dict:
    """Project ``message_id`` away and compare the golden at two named commits."""

    def load(rev: str) -> dict:
        text = subprocess.run(
            ["git", "show", f"{rev}:{GOLDEN}"], check=True, capture_output=True, text=True, cwd=ROOT
        ).stdout
        return json.loads(text)

    a, b = load(before), load(after)
    b_projected = json.loads(json.dumps(b))
    b_projected["row_keys"] = [k for k in b_projected["row_keys"] if k != "message_id"]
    for case in b_projected["cases"]:
        for row in case["results"]:
            row.pop("message_id", None)
    return {
        "before": before,
        "after": after,
        "equal_after_projecting_message_id_away": a == b_projected,
        "added_row_key": [k for k in b["row_keys"] if k not in a["row_keys"]],
    }


def main() -> None:
    out = {
        "schema": "studyloop.retrieval-eval/stage2-council-evidence/v1",
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip(),
        "gold_counters": gold_counters(),
        "golden_projection": golden_projection("80ee57bb", "d060d3f2"),
        "census": census_transitions(),
    }
    target = RECEIPTS / "stage2-census-transitions.json"
    target.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    summary = {k: v for k, v in out["census"].items() if k != "per_question"}
    print(
        json.dumps(
            {"gold": out["gold_counters"], "golden": out["golden_projection"], "census": summary},
            indent=1,
        )
    )
    print("receipt ->", target.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
