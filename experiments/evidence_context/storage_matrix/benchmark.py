"""SQLite versus LadybugDB versus graph projection + SQLite content; private inputs."""

import argparse
import hashlib
import json
import random
import sqlite3
import time
from pathlib import Path


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def size(path):
    return sum(p.stat().st_size for p in path.parent.glob(path.name + "*") if p.is_file())


def build_sql(path, records, edges):
    start = time.perf_counter()
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE message(id TEXT PRIMARY KEY,project TEXT,at TEXT,text TEXT); "
        "CREATE TABLE edge(src TEXT,dst TEXT,kind TEXT,PRIMARY KEY(src,dst,kind)); "
        "CREATE INDEX edge_dst ON edge(dst);"
    )
    con.executemany(
        "INSERT INTO message VALUES (?,?,?,?)",
        [(r["id"], r["project"], r["at"], r["text"]) for r in records],
    )
    con.executemany("INSERT INTO edge VALUES (?,?,?)", edges)
    con.commit()
    return con, time.perf_counter() - start


def build_graph(path, records, edges, projection=False):
    import ladybug as lb

    start = time.perf_counter()
    db = lb.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=1)
    con = lb.Connection(db)
    con.execute(
        "CREATE NODE TABLE M(id STRING PRIMARY KEY,project STRING,at STRING"
        + ("" if projection else ",text STRING")
        + ")"
    )
    con.execute("CREATE REL TABLE Link(FROM M TO M,kind STRING)")
    con.execute("BEGIN TRANSACTION")
    for r in records:
        params = {k: r[k] for k in ("id", "project", "at")}
        if not projection:
            params["text"] = r["text"]
        con.execute("CREATE (:M {" + ", ".join(k + ": $" + k for k in params) + "})", params)
    for src, dst, kind in edges:
        con.execute(
            "MATCH (a:M),(b:M) WHERE a.id=$src AND b.id=$dst CREATE (a)-[:Link {kind:$kind}]->(b)",
            {"src": src, "dst": dst, "kind": kind},
        )
    con.execute("COMMIT")
    con.execute("CHECKPOINT")
    return db, con, time.perf_counter() - start


def sql_query(con, root, depth):
    if depth == 0:
        return con.execute("SELECT id,project,at,text FROM message WHERE id=?", (root,)).fetchall()
    return con.execute(
        "WITH RECURSIVE reach(id,depth) AS (SELECT ?,0 UNION "
        "SELECT edge.dst,reach.depth+1 FROM edge JOIN reach ON edge.src=reach.id "
        "WHERE reach.depth<?) SELECT DISTINCT m.id,m.project,m.at,m.text FROM reach "
        "JOIN message m ON m.id=reach.id WHERE reach.depth>0 ORDER BY m.id",
        (root, depth),
    ).fetchall()


def graph_query(con, root, depth, content=True):
    match = (
        "MATCH (m:M) WHERE m.id=$id"
        if depth == 0
        else f"MATCH (s:M)-[:Link*1..{depth}]->(m:M) WHERE s.id=$id"
    )
    fields = "m.id,m.project,m.at,m.text" if content else "m.id"
    return [
        tuple(row)
        for row in con.execute(
            match + " RETURN DISTINCT " + fields + " ORDER BY m.id", {"id": root}
        )
    ]


def hybrid_query(graph, sql, root, depth):
    ids = [r[0] for r in graph_query(graph, root, depth, False)]
    if not ids:
        return []
    return sql.execute(
        "SELECT id,project,at,text FROM message WHERE id IN ("
        + ",".join("?" for _ in ids)
        + ") ORDER BY id",
        ids,
    ).fetchall()


def quantile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))]


def run(corpus_path, output, scales=(1, 10)):
    import importlib.metadata

    import ladybug as lb

    corpus = json.loads(corpus_path.read_text())
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write(
        output / "frozen.json",
        {
            "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "scales": list(scales),
            "sqlite": sqlite3.sqlite_version,
            "ladybug": importlib.metadata.version("ladybug"),
            "warm_rounds": 5,
            "roots": 40,
            "scope": (
                "all input nodes eligible, links stay within project; "
                "no dynamic auth or concurrent sync"
            ),
        },
    )
    results = []
    for scale in scales:
        records = [{**r, "id": f"{n}:{r['id']}"} for n in range(scale) for r in corpus["records"]]
        edges = [
            (f"{n}:{a}", f"{n}:{b}", kind) for n in range(scale) for a, b, kind in corpus["edges"]
        ]
        directory = output / f"scale-{scale}"
        directory.mkdir()
        sql_path = directory / "content.sqlite"
        graph_path = directory / "full.lbdb"
        projection_path = directory / "projection.lbdb"
        sql, sql_build = build_sql(sql_path, records, edges)
        db, graph, graph_build = build_graph(graph_path, records, edges)
        pdb, projection, projection_build = build_graph(projection_path, records, edges, True)
        print("Built scale", scale, len(records), "nodes", flush=True)
        rng = random.Random(1305)  # nosec B311 - reproducible benchmark order.
        roots = rng.sample(sorted(r["id"] for r in records), min(40, len(records)))
        work = [(root, depth) for root in roots for depth in (0, 1, 2)]
        methods = {
            "sqlite": lambda root, depth, sql=sql: sql_query(sql, root, depth),
            "ladybug": lambda root, depth, graph=graph: graph_query(graph, root, depth),
            "mixed": lambda root, depth, projection=projection, sql=sql: hybrid_query(
                projection, sql, root, depth
            ),
        }
        # Untimed full-result equality check also warms all exact workload queries once.
        equal = True
        cardinalities = []
        for root, depth in work:
            reference = methods["sqlite"](root, depth)
            for name in ("ladybug", "mixed"):
                if methods[name](root, depth) != reference:
                    equal = False
            cardinalities.append(len(reference))
        if not equal:
            raise AssertionError("Engine result mismatch; latency comparison invalid")
        observations = []
        for repeat in range(5):
            order = [(name, root, depth) for name in methods for root, depth in work]
            rng.shuffle(order)
            for name, root, depth in order:
                started = time.perf_counter_ns()
                rows = methods[name](root, depth)
                elapsed = (time.perf_counter_ns() - started) / 1e6
                observations.append(
                    {
                        "engine": name,
                        "depth": depth,
                        "repeat": repeat,
                        "ms": elapsed,
                        "rows": len(rows),
                    }
                )
        latency = {}
        for name in methods:
            latency[name] = {
                str(depth): {
                    "p50_ms": quantile(
                        [
                            r["ms"]
                            for r in observations
                            if r["engine"] == name and r["depth"] == depth
                        ],
                        0.5,
                    ),
                    "p95_ms": quantile(
                        [
                            r["ms"]
                            for r in observations
                            if r["engine"] == name and r["depth"] == depth
                        ],
                        0.95,
                    ),
                }
                for depth in (0, 1, 2)
            }
        graph.close()
        db.close()
        projection.close()
        pdb.close()
        sql.close()
        opens = {}
        started = time.perf_counter()
        s = sqlite3.connect(sql_path)
        s.execute("SELECT COUNT(*) FROM message").fetchone()
        s.close()
        opens["sqlite_ms"] = (time.perf_counter() - started) * 1000
        for name, path in [("ladybug", graph_path), ("projection", projection_path)]:
            started = time.perf_counter()
            d = lb.Database(str(path), buffer_pool_size=128 * 1024 * 1024, max_num_threads=1)
            g = lb.Connection(d)
            list(g.execute("MATCH (m:M) RETURN COUNT(m)"))
            g.close()
            d.close()
            opens[name + "_ms"] = (time.perf_counter() - started) * 1000
        row = {
            "scale": scale,
            "nodes": len(records),
            "edges": len(edges),
            "query_roots": len(roots),
            "equality": equal,
            "build_seconds": {
                "sqlite": sql_build,
                "ladybug": graph_build,
                "mixed": sql_build + projection_build,
            },
            "bytes": {
                "sqlite": size(sql_path),
                "ladybug": size(graph_path),
                "mixed": size(sql_path) + size(projection_path),
            },
            "warm_latency": latency,
            "reopen_plus_count": opens,
            "max_result_rows": max(cardinalities),
            "limits": [
                "Replication preserves topology/degree; not new realistic workloads",
                "No OS page-cache eviction, concurrency, vector index or sync tests",
                "Single process and Python client overhead included",
                "Mixed build cost sums shared SQLite build and edge projection build",
            ],
        }
        results.append(row)
        write(directory / "timings.json", observations)
        write(output / "results.json", results)
        print(row, flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.corpus, args.output)
