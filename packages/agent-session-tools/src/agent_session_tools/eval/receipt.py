"""The receipt: what a look at the ruler leaves behind.

A receipt binds one set of numbers to the exact database, gold set and code
that produced them. Two things make it checkable rather than decorative:

* ``db.fingerprint`` -- a digest over every session's id, source, *visibility*
  under the current scope policy, and message count. A receipt quoted against
  a database that has moved on is detectable, not plausible.
* ``metrics_sha256`` -- the digest of :func:`stable_view`, which drops the
  clock and every timing. Re-running the same arms on the same corpus
  reproduces the digest exactly; a change in it is a change in *results*, not
  in how busy the machine was.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import RECEIPT_SCHEMA

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .gold import ArmResult, GoldSet

#: Keys stripped from a receipt before its metric digest is taken.
UNSTABLE_KEYS = ("created_utc", "latency_ms", "metrics_sha256", "elapsed_ms")


def db_fingerprint(db_path: Path | str) -> str:
    """Digest of ``(session_id, source, visible, message_count)`` over every session.

    Visibility is the live scope policy's own predicate
    (:func:`agent_session_tools.context.scope.visibility_sql`), so a receipt
    records the corpus the arms could actually see, not the one on disk.
    """
    from agent_session_tools.context.scope import visibility_sql

    path = Path(db_path).expanduser()
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        visible, params = visibility_sql(conn, "s.id")
        rows = conn.execute(
            "SELECT s.id, s.source, CASE WHEN "
            + visible
            + " THEN 1 ELSE 0 END AS visible, COUNT(m.id) AS messages "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id "
            "GROUP BY s.id, s.source",
            params,
        ).fetchall()
    finally:
        conn.close()
    digest = hashlib.sha256()
    for session_id, source, visible_flag, messages in sorted(
        (str(r[0]), str(r[1] or ""), int(r[2]), int(r[3])) for r in rows
    ):
        digest.update(
            f"{session_id}\x1f{source}\x1f{visible_flag}\x1f{messages}\x1e".encode()
        )
    return digest.hexdigest()


def build_receipt(
    *,
    db_path: Path | str,
    gold: GoldSet,
    results: Mapping[str, ArmResult],
    comparisons: Mapping[str, Any] | None = None,
    git_commit: str = "",
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Assemble the receipt for one run of the gold ruler."""
    path = Path(db_path).expanduser()
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit,
        "db": {
            "path": str(path),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "fingerprint": fingerprint
            if fingerprint is not None
            else db_fingerprint(path),
        },
        "gold": gold.describe(),
        "arms": {
            name: {
                "config": result.config,
                "metrics": result.metrics(),
                "errors_by_kind": result.errors_by_kind,
                "latency_ms": result.latency_ms,
                # Per-item scores are kept so a later stage can re-run a paired
                # bootstrap from the receipt alone, without re-querying.
                "per_item": {
                    item_id: score.to_dict()
                    for item_id, score in result.per_item.items()
                },
            }
            for name, result in results.items()
        },
        "comparisons": dict(comparisons or {}),
    }
    receipt["metrics_sha256"] = metrics_sha256(receipt)
    return receipt


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in UNSTABLE_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def stable_view(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """The receipt with the clock and every timing removed -- what the digest covers."""
    stripped = _strip(copy.deepcopy(dict(receipt)))
    return stripped if isinstance(stripped, dict) else {}


def metrics_sha256(receipt: Mapping[str, Any]) -> str:
    """sha256 of the canonical JSON of :func:`stable_view`."""
    return hashlib.sha256(
        json.dumps(stable_view(receipt), sort_keys=True).encode()
    ).hexdigest()


def write_receipt(out_path: Path | str, receipt: Mapping[str, Any]) -> Path:
    """Write the receipt as canonical JSON (sorted keys, two-space indent)."""
    path = Path(out_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return path


__all__ = [
    "UNSTABLE_KEYS",
    "build_receipt",
    "db_fingerprint",
    "metrics_sha256",
    "stable_view",
    "write_receipt",
]
