"""Fresh-process diagnostic of permanent cleanup across two fictional stores."""

import argparse
import json
import os
import resource
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory


def worker(count):
    from agent_session_tools.context import managed_history, records

    with TemporaryDirectory(prefix="stage40-controls-") as folder:
        root = Path(folder)
        hot, full = root / "sessions.db", root / "full.db"
        cfg = root / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "database": {"path": str(hot), "full_db_path": str(full)},
                    "logging": {"path": str(root / "log"), "level": "WARNING"},
                    "memory": {"default_scope": "unclassified"},
                }
            )
        )
        os.environ["STUDYLOOP_CONFIG"] = str(cfg)
        os.environ["SESSION_CONTEXT_SCOPE"] = "unclassified"
        with closing(records.connect(hot)) as conn:
            conn.executemany(
                "INSERT INTO sessions(id,source) VALUES (?,'fixture')",
                ((f"session-{i}",) for i in range(count)),
            )
            conn.executemany(
                "INSERT INTO messages(id,session_id,role,content) VALUES (?,?,'user',?)",
                ((f"message-{i}", f"session-{i}", "fictional body") for i in range(count)),
            )
            conn.commit()
            with closing(sqlite3.connect(full)) as dst:
                conn.backup(dst)
            # Model already-authorized permanent intent; setup is outside timing.
            conn.executemany(
                "INSERT INTO context_tombstones VALUES (?,?,'fixture')",
                ((f"session-{i}", f"deletion-{i}") for i in range(count)),
            )
            conn.commit()
        started = time.perf_counter()
        result = managed_history.reconcile_full()
        elapsed = time.perf_counter() - started
        assert result["complete"], result
        for path in (hot, full):
            with closing(sqlite3.connect(path)) as conn:
                assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
                assert conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0] == 0
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "sessions_per_store": count,
            "cleanup_seconds": elapsed,
            "closure_rounds": result["closure_rounds"],
            "peak_process_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
            "both_stores_empty": True,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 5000])
    parser.add_argument("--worker", type=int)
    args = parser.parse_args()
    if args.worker is not None:
        if not 1 <= args.worker <= 10000:
            parser.error("Worker count must be between 1 and 10000")
        print(json.dumps(worker(args.worker)))
        return
    if args.output is None or args.output.exists():
        parser.error("Supply a fresh output directory")
    args.output.mkdir(parents=True)
    rows = []
    for count in args.sizes:
        child = subprocess.run(
            [str(args.python), "-I", str(Path(__file__).resolve()), "--worker", str(count)],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
        rows.append(json.loads(child.stdout))
    result = {
        "rows": rows,
        "limits": (
            "One fresh process per cell, fictional legacy rows, all sessions retired. "
            "Time includes two-store reconciliation and canonical/full compaction; "
            "peak RSS includes fixture setup. No native evidence, network, engine ranking "
            "or semantic usefulness comparison. Bounds are refusals, not a latency guarantee."
        ),
    }
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
