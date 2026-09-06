"""Measure body verification, SQL calls and VM work on disposable fixture copies."""

import argparse
import json
import os
import statistics
import time
from collections import Counter
from pathlib import Path

from agent_session_tools.context import annotations, records
from agent_session_tools.context.annotation_pages import Reader
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore


def prepare(root, count):
    path = root / f"history-{count}.db"
    conn = records.connect(path)
    conn.execute("INSERT INTO sessions(id,source) VALUES ('history','fixture')")
    conn.commit()
    config = {"memory": {"default_scope": "unclassified"}}
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config))
    os.environ["STUDYLOOP_CONFIG"] = str(config_path)
    os.environ["SESSION_CONTEXT_SCOPE"] = "unclassified"
    apply_policy(conn, ScopePolicy.from_config(config), actor="benchmark", dry_run=False)
    store = ObservationStore(conn)
    previous = []
    with ContextStore(conn)._atomic(), records.policy_guard(conn):
        for n in range(count):
            previous = [
                store.append(
                    kind=annotations.KINDS["note"],
                    subject="history",
                    payload={"notes": f"Correction {n}: fixture result only"},
                    producer="fixture",
                    authority="reported",
                    owner_session_id="history",
                    supersedes=previous,
                )
            ]
    conn.close()
    return path


def full_cached(conn):
    reader = Reader(conn, "history", "note")
    rows = reader.store.sources._rows(
        f"SELECT o.* FROM {reader.join} WHERE {reader.where} ORDER BY o.recorded_at DESC,o.id DESC",
        reader.values,
    )
    checked = [
        reader.store._checked(r, reader.policy, reader.scope, visible_snapshot=reader.visible)
        for r in rows
    ]
    return {
        "verified_bodies": len(checked),
        "returned_versions": len(checked),
        "coverage": "complete",
        "mode": "control_full_history_no_output_packing",
    }


def measure(path, operation, repeats):
    conn = records.connect(path)
    durations = []
    try:
        for _ in range(repeats):
            start = time.perf_counter()
            result = operation(conn)
            durations.append((time.perf_counter() - start) * 1000)
            conn.rollback()
        counts = Counter()
        conn.set_trace_callback(lambda sql: counts.update([sql.split()[0].upper()]))
        operation(conn)
        conn.set_trace_callback(None)
        conn.rollback()
        return {
            "median_ms": round(statistics.median(durations), 3),
            "max_ms": round(max(durations), 3),
            "selects": counts["SELECT"],
            "result": result,
        }
    finally:
        conn.close()


def run(root, *, sizes=(10, 100, 1000), repeats=5):
    results = []
    for count in sizes:
        path = prepare(root, count)
        control = measure(path, full_cached, repeats)

        def bounded(conn):
            value = annotations.view(conn, "history")
            assert value["current_count"] == 1 and value["current_group_complete"]
            return {
                "returned_versions": len(value["versions"]),
                "coverage": value["coverage"],
                "response_bytes": len(
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
                ),
                "vm_steps": value["work"]["vm_steps_observed"],
                "has_more": value["next_cursor"] is not None,
            }

        candidate = measure(path, bounded, repeats)
        results.append(
            {"versions": count, "full_cached_control": control, "bounded_page": candidate}
        )
    return {
        "measurements": results,
        "limits": (
            "Warm synthetic short-note reads. Timings exclude SQL tracing; SELECTs counted "
            "separately. Full control verifies all bodies without output packing, page "
            "returns selected bodies. No semantic equivalence or engine comparison claim."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 100, 1000])
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    result = run(root, sizes=args.sizes)
    (root / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
