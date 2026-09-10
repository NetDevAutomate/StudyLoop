"""Ingest the whole archive into a learning-memory store, and write a receipt.

    python -m learning_memory.ingest_archive \\
        --db ~/.config/studyloop/sessions.db \\
        --store ~/.local/share/studyloop/knowledge-proof/learning-memory.db \\
        --receipt ~/.local/share/studyloop/knowledge-proof/ingest-archive-v1.json [--fresh]

One transaction per session, failures recorded and stepped over: a corpus-wide run
that dies on session 3,000 tells you nothing about the other 2,879.

The corpus digest is computed by the **ruler's own** ``corpus_digest`` — imported
from ``scripts/knowledge_proof/score.py``, never reimplemented — so the number on
this receipt is comparable with every arm receipt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import pathlib
import sqlite3
import sys
import time
from collections import Counter
from typing import Any

from learning_memory import SCHEMA_VERSION, NoEvidenceError, Store
from learning_memory.adapters.archive import (
    ARCHIVE_ADAPTER_VERSION,
    ARCHIVE_CLASSIFIER_VERSION,
    ArchiveAdapter,
    open_readonly,
)

DEFAULT_DB = pathlib.Path.home() / ".config/studyloop/sessions.db"
DEFAULT_STORE = pathlib.Path.home() / ".local/share/studyloop/knowledge-proof/learning-memory.db"


def _find_repo_file(relative: str) -> pathlib.Path | None:
    """Walk up from this file looking for a worktree-relative path."""
    for parent in pathlib.Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.exists():
            return candidate
    return None


def _load_corpus_digest(
    score_py: pathlib.Path | None, gold: pathlib.Path | None, db: pathlib.Path
) -> dict[str, Any]:
    """Compute the digest with the ruler's pinned function, or say why we could not."""
    result: dict[str, Any] = {
        "function": "scripts/knowledge_proof/score.py::corpus_digest",
        "score_py": str(score_py) if score_py else None,
        "gold": str(gold) if gold else None,
        "value": None,
        "gold_authoring_value": None,
        "note": None,
    }
    if score_py is None or gold is None:
        result["note"] = "score.py or gold not found; digest not computed"
        return result
    spec = importlib.util.spec_from_file_location("_kp_score", score_py)
    if spec is None or spec.loader is None:
        result["note"] = f"could not load {score_py}"
        return result
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = json.loads(gold.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    conn = open_readonly(db)
    try:
        result["value"] = module.corpus_digest(conn, items)
    finally:
        conn.close()
    result["gold_authoring_value"] = payload.get("corpus_digest")
    result["gold_items"] = len(items)
    result["gold_set"] = payload.get("set")
    if result["value"] != result["gold_authoring_value"]:
        result["note"] = (
            "computed over the DEV gold's sessions; differs from the value recorded when "
            "gold v2 was authored, which covered all 175 admitted items (DEV + SEALED). "
            "Reproducing that value would require reading the SEALED gold, which this run "
            "must not do. The immediately following baseline-dev receipt records the same "
            "DEV-only value this run computes."
        )
    return result


def _prepare_store(store_path: pathlib.Path, fresh: bool) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    if store_path.exists():
        if not fresh:
            raise SystemExit(
                f"refusing to write an existing store: {store_path}\n"
                "pass --fresh to replace it (this deletes the file and its WAL)"
            )
        for suffix in ("", "-wal", "-shm"):
            candidate = store_path.with_name(store_path.name + suffix)
            if candidate.exists():
                candidate.unlink()


def _store_bytes(store_path: pathlib.Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for suffix in ("", "-wal", "-shm"):
        candidate = store_path.with_name(store_path.name + suffix)
        sizes[candidate.name] = candidate.stat().st_size if candidate.exists() else 0
    sizes["total"] = sum(value for key, value in sizes.items() if key != "total")
    return sizes


def _integrity_check(store: Store) -> str:
    try:
        store.connection.execute("INSERT INTO prose_fts(prose_fts) VALUES ('integrity-check')")
    except sqlite3.DatabaseError as err:  # pragma: no cover - a real corruption path
        return f"FAILED: {err}"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="legacy sessions.db (read-only)")
    parser.add_argument(
        "--store", default=str(DEFAULT_STORE), help="learning-memory store to write"
    )
    parser.add_argument("--receipt", required=True, help="where to write the receipt JSON")
    parser.add_argument("--fresh", action="store_true", help="replace an existing store")
    parser.add_argument("--limit", type=int, default=0, help="ingest only the first N sessions")
    parser.add_argument(
        "--score-py", default=None, help="override the path to the ruler's score.py"
    )
    parser.add_argument("--gold", default=None, help="override the DEV gold json")
    args = parser.parse_args(argv)

    db = pathlib.Path(args.db).expanduser()
    store_path = pathlib.Path(args.store).expanduser()
    receipt_path = pathlib.Path(args.receipt).expanduser()
    _prepare_store(store_path, args.fresh)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)

    score_py = (
        pathlib.Path(args.score_py).expanduser()
        if args.score_py
        else _find_repo_file("scripts/knowledge_proof/score.py")
    )
    gold = (
        pathlib.Path(args.gold).expanduser()
        if args.gold
        else _find_repo_file("docs/architecture/session-memory/receipts/gold-v2-dev.json")
    )

    started = time.monotonic()
    adapter = ArchiveAdapter.open(db)
    store = Store.connect(store_path)
    store.install()

    ingested: list[str] = []
    rejected: list[dict[str, str]] = []
    dupes = 0
    order = adapter.session_ids()
    if args.limit:
        order = order[: args.limit]

    for session_id in order:
        try:
            parsed = adapter.parse_id(session_id)
            result = store.ingest(parsed)
        except NoEvidenceError as err:
            rejected.append(
                {"session_id": session_id, "reason": "NoEvidenceError", "detail": str(err)}
            )
            continue
        except (sqlite3.Error, KeyError, ValueError) as err:
            rejected.append(
                {
                    "session_id": session_id,
                    "reason": type(err).__name__,
                    "detail": str(err)[:400],
                }
            )
            continue
        ingested.append(session_id)
        dupes += result.exporter_dupes_collapsed

    elapsed = time.monotonic() - started
    conn = store.connection
    kinds = {
        str(row["kind"]): int(row["n"])
        for row in conn.execute(
            "SELECT kind, count(*) AS n FROM events GROUP BY kind ORDER BY n DESC"
        )
    }
    evidence = {
        "total": int(conn.execute("SELECT count(*) AS n FROM evidence").fetchone()["n"]),
        "citable_per_event": int(
            conn.execute(
                "SELECT count(*) AS n FROM evidence WHERE event_id IS NOT NULL"
            ).fetchone()["n"]
        ),
        "native_captures": int(
            conn.execute("SELECT count(*) AS n FROM evidence WHERE event_id IS NULL").fetchone()[
                "n"
            ]
        ),
    }
    per_source = {
        str(row["harness"]): int(row["n"])
        for row in conn.execute(
            "SELECT harness, count(*) AS n FROM sessions GROUP BY harness ORDER BY n DESC, harness"
        )
    }
    integrity = _integrity_check(store)
    lineage_edges = int(conn.execute("SELECT count(*) AS n FROM lineage").fetchone()["n"])
    pending = store.pending_lineage()
    unrecoverable = adapter.unrecoverable_lineage()
    self_referencing = adapter.self_referencing_lineage()
    rejected_counter = Counter(entry["reason"] for entry in rejected)

    receipt = {
        "receipt": "ingest-archive",
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "versions": {
            "schema_version": SCHEMA_VERSION,
            "adapter_version": ARCHIVE_ADAPTER_VERSION,
            "classifier_version": ARCHIVE_CLASSIFIER_VERSION,
        },
        "inputs": {
            "db": str(db),
            "db_bytes": db.stat().st_size if db.exists() else 0,
            "db_opened": "file:...?mode=ro (read-only)",
            "store": str(store_path),
            "limit": args.limit or None,
        },
        "corpus_digest": _load_corpus_digest(score_py, gold, db),
        "sessions": {
            "in_archive": len(adapter.session_ids()),
            "attempted": len(order),
            "ingested": len(ingested),
            "rejected": len(rejected),
            "rejected_by_reason": dict(rejected_counter),
            "rejected_detail": rejected,
        },
        "events_by_kind": kinds,
        "events_total": sum(kinds.values()),
        "exporter_dupes_collapsed": dupes,
        "evidence": evidence,
        "lineage": {
            "edges": lineage_edges,
            "pending": pending,
            "pending_count": len(pending),
            "unrecoverable_count": len(unrecoverable),
            "unrecoverable_sample": unrecoverable[:10],
            "self_referencing_skipped": len(self_referencing),
        },
        "per_source_sessions": per_source,
        "archive_per_source_sessions": adapter.source_counts(),
        "fts_integrity_check": integrity,
        "wall_seconds": round(elapsed, 2),
        "store_bytes": _store_bytes(store_path),
    }

    store.close()
    adapter.close()
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(f"ingested {len(ingested)}/{len(order)} sessions in {elapsed:.1f}s")
    print(f"  events {receipt['events_total']} by kind: {kinds}")
    print(f"  evidence {evidence}   dupes collapsed {dupes}")
    print(
        f"  lineage edges {lineage_edges}, pending {len(pending)}, "
        f"unrecoverable {len(unrecoverable)}"
    )
    print(f"  rejected {len(rejected)} {dict(rejected_counter)}")
    print(f"  fts integrity-check: {integrity}")
    print(f"  receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
