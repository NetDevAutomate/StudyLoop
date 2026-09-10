"""Re-certify gold v2 with reproducible provenance hashes (ruler-amendment-002).

Why this exists: the Stage 2 gold receipt recorded three hashes (``dev.sha256``,
``sealed.sha256``, ``corpus_digest``) computed by an in-session script that was not
preserved. None reproduce from any surviving artefact (384 serialisations tried), so a
result receipt can never *match* them, and the ruler voids on mismatch. The gold DATA is
unchanged (DEV byte-identical to its first commit; SEALED mtime equals the certification
instant; zero gold-session messages newer than authoring). Only the record is re-issued.

Method (every value below is recomputable by anyone holding the two files and the DB):

* ``dev.sha256``     = sha256 of the DEV file's bytes.
* ``sealed.sha256``  = sha256 of the SEALED file's bytes (the file is opened for hashing
                       only; no item is parsed for output, and no id is written anywhere).
* ``corpus_digest.dev``   = ``score.corpus_digest(conn, DEV items)``.
* ``corpus_digest.whole`` = ``score.corpus_digest(conn, DEV items + SEALED items)`` --
                       the domain the ruler's clause names ("every gold cluster").
* Result receipts on DEV must match ``corpus_digest.dev``; the one SEALED receipt must
  match ``corpus_digest.sealed``. Both are recorded so the check is mechanical.

Usage (orchestrator only -- this script reads the SEALED path):
    uv run python recertify_gold.py --sealed <path> --previous <gold-v2-receipt.json> \
        --out ../../docs/architecture/session-memory/receipts/gold-v2-receipt-r2.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sqlite3

from score import _git, _sha_file, corpus_digest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "docs/architecture/session-memory/receipts"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dev", default=str(RECEIPTS / "gold-v2-dev.json"))
    ap.add_argument("--sealed", required=True)
    ap.add_argument("--db", default=str(pathlib.Path.home() / ".config/studyloop/sessions.db"))
    ap.add_argument("--previous", required=True, help="the Stage 2 gold receipt being superseded")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    dev_path, sealed_path = pathlib.Path(args.dev), pathlib.Path(args.sealed).expanduser()
    dev = json.loads(dev_path.read_text())
    sealed_items = json.loads(sealed_path.read_bytes())["items"]  # in-process only
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    whole = list(dev["items"]) + list(sealed_items)
    dev_ids = {it["id"] for it in dev["items"]}
    overlap = sum(1 for it in sealed_items if it["id"] in dev_ids)
    gold_sessions = sorted(
        {s for it in whole for s in it["gold_session_ids"]} | {it["cluster"] for it in whole}
    )
    marks = ",".join("?" * len(gold_sessions))
    newer_sql = (
        f"SELECT count(*) FROM messages WHERE session_id IN ({marks}) "
        "AND timestamp > '2026-09-10T00:17'"
    )

    receipt = {
        "receipt": "gold-v2-recertification",
        "supersedes": {"path": args.previous, "sha256": _sha_file(pathlib.Path(args.previous))},
        "created_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "ruler_commit": _git(
            ROOT,
            "log",
            "-1",
            "--format=%H",
            "--",
            "docs/architecture/session-memory/validation-ruler.md",
        ),
        "amendment": "receipts/ruler-amendment-002.md",
        "method": "see module docstring of scripts/knowledge_proof/recertify_gold.py",
        "dev": {
            "path": str(dev_path.relative_to(ROOT)),
            "sha256": _sha_file(dev_path),
            "items": len(dev["items"]),
            "clusters": len({it["cluster"] for it in dev["items"]}),
            "first_commit": _git(
                ROOT, "log", "--diff-filter=A", "-1", "--format=%H", "--", str(dev_path)
            ),
            "unchanged_since_first_commit": _git(
                ROOT, "diff", "--quiet", "HEAD", "--", str(dev_path)
            )
            == "",
        },
        "sealed": {
            "path": "OUTSIDE REPOSITORY -- never passed to builder agents",
            "sha256": _sha_file(sealed_path),
            "items": len(sealed_items),
            "clusters": len({it["cluster"] for it in sealed_items}),
            "bytes": sealed_path.stat().st_size,
            "mode": oct(sealed_path.stat().st_mode & 0o777),
            "mtime_utc": _dt.datetime.fromtimestamp(sealed_path.stat().st_mtime, _dt.UTC).isoformat(
                timespec="seconds"
            ),
        },
        "dev_sealed_overlap_items": overlap,
        "corpus_digest": {
            "dev": corpus_digest(conn, dev["items"]),
            "sealed": corpus_digest(conn, list(sealed_items)),
            "whole": corpus_digest(conn, whole),
            "function": (
                "scripts/knowledge_proof/score.py::corpus_digest (pinned; unchanged since d83b3b41)"
            ),
            "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
        },
        "drift_check": {
            "gold_sessions": len(gold_sessions),
            "messages_newer_than_stage2_authoring": conn.execute(
                newer_sql, gold_sessions
            ).fetchone()[0],
        },
    }
    out = pathlib.Path(args.out)
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(f"dev.sha256      {receipt['dev']['sha256'][:16]}")
    sealed_sha = receipt["sealed"]["sha256"][:16]
    print(f"sealed.sha256   {sealed_sha}   items {receipt['sealed']['items']}  overlap {overlap}")
    print(f"digest dev      {receipt['corpus_digest']['dev'][:16]}")
    print(f"digest sealed   {receipt['corpus_digest']['sealed'][:16]}")
    print(f"digest whole    {receipt['corpus_digest']['whole'][:16]}")
    print(f"drift           {receipt['drift_check']}")
    print(f"receipt -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
