"""Measure scoped queries over 50000 synthetic project-owned sessions; no engine ranking."""

import argparse
import json
import runpy
import statistics
import time
from pathlib import Path

from agent_session_tools.context import records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    helper = runpy.run_path(str(Path(__file__).parents[1] / "agent_context/probe.py"))
    conn, _, _, _, _, _, _ = helper["prepare"](output)
    count = 50000
    conn.executemany(
        "INSERT INTO study_sessions(id,started_at,topic,notes) VALUES (?,'2026-09-01','python',?)",
        [(f"record-{i:06}", "permitted" if i % 2 else "excluded") for i in range(count)],
    )
    conn.executemany(
        "INSERT INTO context_record_owners(id,table_name,row_id,project_id,created_at) "
        "VALUES (?,'study_sessions',?,?,'2026-09-01')",
        [(f"owner-{i}", f"record-{i:06}", "studyloop" if i % 2 else "work") for i in range(count)],
    )
    conn.commit()
    timings = {}
    for label, select in [
        ("permitted_count", "SELECT count(*) FROM study_sessions r WHERE "),
        ("latest_twenty", "SELECT id,notes FROM study_sessions r WHERE "),
    ]:
        elapsed = []
        for _ in range(10):
            start = time.perf_counter()
            clause, params = records.visible_sql(conn, "study_sessions")
            query = select + clause
            if label == "latest_twenty":
                query += " ORDER BY started_at DESC,id DESC LIMIT 20"
            rows = conn.execute(query, params).fetchall()
            conn.rollback()
            elapsed.append((time.perf_counter() - start) * 1000)
            if label == "permitted_count":
                assert rows[0][0] == count // 2
            else:
                assert len(rows) == 20 and all(row["notes"] == "permitted" for row in rows)
        timings[label] = {"median_ms": statistics.median(elapsed), "max_ms": max(elapsed)}
    conn.close()
    report = {
        "rows": count,
        "permitted_rows": count // 2,
        "iterations": 10,
        "includes_policy_resolution": True,
        "includes_process_startup": False,
        "timings": timings,
        "database_bytes": (output / "sessions.db").stat().st_size,
        "limits": "One local synthetic project-only workload, no concurrent writers. "
        "No comparison to per-table columns or another database engine.",
    }
    (output / "results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
