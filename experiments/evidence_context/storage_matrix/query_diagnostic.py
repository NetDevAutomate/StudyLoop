"""Post-run SQL plan diagnostic. Preserve the original benchmark unchanged."""

import argparse
import json
import random
import sqlite3
import time
from pathlib import Path

from .benchmark import quantile, sql_query, write

SQL = (
    "WITH RECURSIVE reach(id,depth) AS (SELECT ?,0 UNION "
    "SELECT edge.dst,reach.depth+1 FROM edge JOIN reach ON edge.src=reach.id "
    "WHERE reach.depth<?) SELECT m.id,m.project,m.at,m.text FROM message m "
    "WHERE m.id IN (SELECT id FROM reach WHERE depth>0) ORDER BY m.id"
)


def indexed_query(con, root, depth):
    if depth == 0:
        return sql_query(con, root, depth)
    return con.execute(SQL, (root, depth)).fetchall()


def run(directory):
    output = directory / "query-diagnostic.json"
    if output.exists():
        raise ValueError("Preserve the diagnostic; use a new run for replication")
    results = []
    for scale in (1, 10):
        path = directory / f"scale-{scale}" / "content.sqlite"
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        ids = sorted(r[0] for r in con.execute("SELECT id FROM message"))
        rng = random.Random(1305)  # nosec B311 - reproducible benchmark order.
        roots = rng.sample(ids, min(40, len(ids)))
        work = [(root, depth) for root in roots for depth in (0, 1, 2)]
        for root, depth in work:
            assert indexed_query(con, root, depth) == sql_query(con, root, depth)
        observations = []
        for repeat in range(5):
            jobs = [(name, root, depth) for name in ("original", "indexed") for root, depth in work]
            rng.shuffle(jobs)
            for name, root, depth in jobs:
                start = time.perf_counter_ns()
                rows = (sql_query if name == "original" else indexed_query)(con, root, depth)
                observations.append(
                    {
                        "variant": name,
                        "depth": depth,
                        "repeat": repeat,
                        "ms": (time.perf_counter_ns() - start) / 1e6,
                        "rows": len(rows),
                    }
                )
        plan = con.execute("EXPLAIN QUERY PLAN " + SQL, (roots[0], 2)).fetchall()
        con.close()
        result = {"scale": scale, "equality": True, "indexed_plan": plan, "latency": {}}
        for name in ("original", "indexed"):
            result["latency"][name] = {}
            for depth in (0, 1, 2):
                values = [
                    r["ms"] for r in observations if r["variant"] == name and r["depth"] == depth
                ]
                result["latency"][name][str(depth)] = {
                    "p50_ms": quantile(values, 0.5),
                    "p95_ms": quantile(values, 0.95),
                }
        results.append(result)
        write(directory / f"scale-{scale}" / "diagnostic-timings.json", observations)
    write(
        output,
        {
            "post_hoc": True,
            "results": results,
            "limit": "Paired SQL diagnostic, not rerun graph comparison or holdout.",
        },
    )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().directory), indent=2))
