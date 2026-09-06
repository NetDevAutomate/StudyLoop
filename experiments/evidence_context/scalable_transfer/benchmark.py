"""Paired fresh-process projection diagnostic; no engine or answer-quality ranking."""

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory


def worker(mode, messages):
    from agent_session_tools.context import records
    from agent_session_tools.context.scope import ScopePolicy, apply_policy
    from agent_session_tools.context.store import _json
    from agent_session_tools.replication.policy import (
        PeerPolicy,
        ReplicaError,
        hello,
        negotiate,
        open_read,
    )
    from agent_session_tools.replication.snapshot import export_snapshot, export_staged

    with TemporaryDirectory(prefix="stage39-projection-") as folder:
        root, nodes = Path(folder), {}
        for name, peer in (("a", "b"), ("b", "a")):
            path = root / name
            path.mkdir()
            db = path / "sessions.db"
            config = {
                "database": {"path": str(db)},
                "logging": {"path": str(path / "log"), "level": "WARNING"},
                "memory": {
                    "default_scope": "personal",
                    "projects": {"study": {"scope": "personal", "roots": [str(path / "project")]}},
                    "sync": {"node_id": name, "peers": {peer: {"allowed_scopes": ["personal"]}}},
                },
            }
            cfg = path / "config.json"
            cfg.write_text(json.dumps(config))
            os.environ["STUDYLOOP_CONFIG"] = str(cfg)
            os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
            with closing(records.connect(db)) as conn:
                apply_policy(
                    conn,
                    ScopePolicy.from_config(config),
                    actor="fictional projection diagnostic",
                    dry_run=False,
                )
                if name == "a":
                    conn.execute("INSERT INTO sessions(id,source) VALUES ('large-history','codex')")
                    conn.execute(
                        "INSERT INTO context_session_projects "
                        "VALUES ('large-history','study','explicit')"
                    )
                    conn.executemany(
                        "INSERT INTO messages(id,session_id,role,content) "
                        "VALUES (?,'large-history','user',?)",
                        (
                            (f"message-{i:06d}", "fictional bounded scale data " * 600)
                            for i in range(messages)
                        ),
                    )
                    conn.commit()
            nodes[name] = (db, config, cfg)
        a, b = nodes["a"], nodes["b"]
        os.environ["STUDYLOOP_CONFIG"] = str(a[2])
        with closing(open_read(a[0])) as ca, closing(open_read(b[0])) as cb:
            plan = negotiate(
                hello(ca, PeerPolicy.from_config(a[1], "b")),
                hello(cb, PeerPolicy.from_config(b[1], "a")),
            )
            raw = ca.execute("SELECT sum(length(CAST(content AS BLOB))) FROM messages").fetchone()[
                0
            ]
        started = time.perf_counter()
        try:
            if mode == "staged":
                with export_staged(a[0], a[1], plan, "personal") as snapshot:
                    encoded = snapshot.encoded_bytes
            else:
                snapshot = export_snapshot(a[0], a[1], plan, "personal")
                encoded = len(_json(snapshot).encode())
            outcome = {"exported_bytes": encoded}
        except ReplicaError as exc:
            outcome = {"refused": str(exc)}
        elapsed = time.perf_counter() - started
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "mode": mode,
            "messages": messages,
            "raw_message_bytes": raw,
            **outcome,
            "projection_seconds": elapsed,
            "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--sizes", type=int, nargs="+", default=[512, 3072])
    parser.add_argument("--worker", choices=["snapshot", "staged"])
    parser.add_argument("--messages", type=int, default=3072)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker, args.messages)))
        return
    if (
        args.output is None
        or args.output.exists()
        or any(not 1 <= size <= 10000 for size in args.sizes)
    ):
        parser.error("Supply a fresh output directory and sizes between1and10000")
    args.output.mkdir(parents=True)
    rows = []
    for size in args.sizes:
        for mode in ("snapshot", "staged"):
            result = subprocess.run(
                [
                    str(args.python),
                    "-I",
                    str(Path(__file__).resolve()),
                    "--worker",
                    mode,
                    "--messages",
                    str(size),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            rows.append(json.loads(result.stdout))
    data = {
        "rows": rows,
        "limits": (
            "One fresh process per cell. Fictional legacy message rows, no native evidence "
            "copies; actual native/SSH lifecycle is a separate lesson. Peak RSS includes "
            "fixture creation. Times cover projection and encoded-size measurement, "
            "excluding transport/receiver. No engine or semantic quality comparison."
        ),
    }
    (args.output / "results.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data))


if __name__ == "__main__":
    main()
