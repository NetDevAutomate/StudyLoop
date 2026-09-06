"""Measure projection work separately from its bounded response size.

Synthetic SQL setup is outside timing; this does not benchmark capture/writes.
Run with an installed Python to avoid treating editable imports as wheel proof.
"""

import argparse
import json
import os
import statistics
import time
from pathlib import Path

from agent_session_tools.context import records
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from studyloop.learning.mastery import agent_concept_context


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    db = output / "sessions.db"
    config = {
        "database": {"path": str(db)},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": [str(output / "personal")]},
                "work": {"scope": "work", "roots": [str(output / "work")]},
            },
        },
    }
    path = output / "config.json"
    path.write_text(json.dumps(config))
    os.environ.update(
        STUDYLOOP_CONFIG=str(path), STUDYLOOP_DB=str(db), SESSION_CONTEXT_SCOPE="personal"
    )
    conn = records.connect(db)
    apply_policy(conn, ScopePolicy.from_config(config), actor="benchmark", dry_run=False)
    measured = []
    previous = 0
    for size in (100, 1000, 5000):
        for i in range(previous, size):
            for scope in ("work", "personal"):
                cur = conn.execute(
                    "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,"
                    "target_domain,structural_mapping) VALUES (?,?,?,?,?)",
                    (
                        f"{scope} routing {i}",
                        "networking",
                        f"closures {i}",
                        "python",
                        "Fictional mapping",
                    ),
                )
                conn.execute(
                    "INSERT INTO context_record_owners VALUES (?,?,?,?,?,?,?)",
                    (
                        f"{scope}-{i}",
                        "knowledge_bridges",
                        str(cur.lastrowid),
                        None,
                        scope,
                        None,
                        "2026-09-06",
                    ),
                )
        conn.commit()
        samples = []
        for _ in range(5):
            before = time.perf_counter()
            result = agent_concept_context("python")
            samples.append((time.perf_counter() - before) * 1000)
            assert result["edge_count_total"] == size
            assert "work routing" not in json.dumps(result)
            assert len(json.dumps(result, ensure_ascii=False).encode()) <= 32768
        measured.append(
            {
                "visible": size,
                "excluded": size,
                "repeats": 5,
                "median_ms": round(statistics.median(samples), 3),
                "max_ms": round(max(samples), 3),
                "returned_edges": len(result["edges"]),
                "coverage": result["coverage"],
            }
        )
        previous = size
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    return {
        "measurements": measured,
        "limits": (
            "Direct installed helper, synthetic short bridges, sequential warm runs; "
            "includes all-visible projection and packing, excludes transport and startup. "
            "Output is bounded; query work is not."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = run(args.output.resolve())
    (args.output / "results.json").write_text(json.dumps(data, indent=2))
    print(json.dumps(data))
