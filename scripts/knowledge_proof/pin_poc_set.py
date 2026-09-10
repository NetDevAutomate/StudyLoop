"""Pin the G2 "PoC wind-down set" as a reproducible artefact (ruler-amendment-003).

The ruler binds G2 to "the 348 PoC sessions" -- the blind subset the earlier authoring run
was scored on, defined in its RESULTS-final.md as "updated >= 2026-08-01, >= 10 messages ->
348 sessions". No id list was committed. The run's own frozen corpus snapshot survives at
``~/.local/share/sessionweaver/poc-storage-decision/corpus-20260906-clean.db`` (sha in the
adjacent SHA256SUMS). Re-running the recorded rule against it yields **345**: the snapshot was
passed through ``clean-empty-rows.py`` (deletes empty-content message rows) *after* the 348 was
counted, and three sessions fell below ten messages. Every one of the 345 exists in the live DB
today and 342 are in the learning-memory store (the other 3 are prose-less and were rejected by
the store's citable-evidence invariant).

Two denominators are recorded because the ruler's "sessions with >= 10 messages" was written
when a message could be tool echo; under typed events the same words mean "prose events":

* ``n_messages_ge10``  -- >= 10 archive messages of any role (the ruler's literal wording)
* ``n_prose_ge10``     -- >= 10 ``user``/``assistant_prose`` events in the store

G2 is reported against BOTH; the ruler is not edited.

Usage:
    uv run python pin_poc_set.py \
        --out ../../docs/architecture/session-memory/receipts/poc-set-g2.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import pathlib
import sqlite3

SNAPSHOT = (
    pathlib.Path.home() / ".local/share/sessionweaver/poc-storage-decision/corpus-20260906-clean.db"
)
STORE = pathlib.Path.home() / ".local/share/studyloop/knowledge-proof/learning-memory.db"
LIVE = pathlib.Path.home() / ".config/studyloop/sessions.db"
RULE_SQL = (
    "SELECT s.id FROM sessions s WHERE s.updated_at >= '2026-08-01' "
    "AND (SELECT count(*) FROM messages m WHERE m.session_id = s.id) >= 10 ORDER BY s.id"
)


def _ro(path: pathlib.Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", default=str(SNAPSHOT))
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--live", default=str(LIVE))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    snap_path = pathlib.Path(args.snapshot)
    snap, store, live = _ro(snap_path), _ro(pathlib.Path(args.store)), _ro(pathlib.Path(args.live))
    ids = [r[0] for r in snap.execute(RULE_SQL)]
    in_live = [
        s for s in ids if live.execute("SELECT 1 FROM sessions WHERE id = ?", (s,)).fetchone()
    ]
    in_store = [
        s for s in ids if store.execute("SELECT 1 FROM sessions WHERE id = ?", (s,)).fetchone()
    ]
    prose_ge10 = [
        s
        for s in in_store
        if store.execute(
            "SELECT count(*) FROM events WHERE session_id = ? "
            "AND kind IN ('user', 'assistant_prose')",
            (s,),
        ).fetchone()[0]
        >= 10
    ]
    messages_ge10 = [
        s
        for s in in_live
        if live.execute("SELECT count(*) FROM messages WHERE session_id = ?", (s,)).fetchone()[0]
        >= 10
    ]
    receipt = {
        "receipt": "poc-set-g2",
        "created_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "amendment": "receipts/ruler-amendment-003.md",
        "rule": RULE_SQL,
        "rule_source": (
            "RESULTS-final.md:139 -- 'updated >= 2026-08-01, >= 10 messages -> 348 sessions'"
        ),
        "snapshot": {
            "path": str(snap_path),
            "sha256": hashlib.sha256(snap_path.read_bytes()).hexdigest(),
            "bytes": snap_path.stat().st_size,
        },
        "recorded_count": 348,
        "reproduced_count": len(ids),
        "discrepancy_explained": (
            "snapshot was passed through clean-empty-rows.py after the 348 was counted; "
            "3 sessions fell below 10 messages"
        ),
        "session_ids": ids,
        "set_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
        "present_in_live_db": len(in_live),
        "ingested_in_store": len(in_store),
        "denominators": {
            "n_messages_ge10": len(messages_ge10),
            "n_prose_ge10": len(prose_ge10),
        },
        "prose_ge10_session_ids": prose_ge10,
    }
    out = pathlib.Path(args.out)
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(f"reproduced {len(ids)} (recorded 348); live {len(in_live)}; store {len(in_store)}")
    print(f"denominators: messages>=10 {len(messages_ge10)}  prose>=10 {len(prose_ge10)}")
    print(
        f"set sha256 {receipt['set_sha256'][:16]}  "
        f"snapshot sha256 {receipt['snapshot']['sha256'][:16]}"
    )
    print(f"receipt -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
