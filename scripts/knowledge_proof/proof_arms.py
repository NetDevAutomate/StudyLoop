"""Feature arms for ``score.py`` (``--feature proof_arms:<name>``).

Every arm here is declared in ``receipts/fusion-spec-v<N>.md`` *before* its first DEV
look; the docstring of each factory names the spec version it implements so a receipt
can be checked against the declaration mechanically.

Arms that read ``learning-memory.db`` open their own read-only connection and ignore
the archive connection ``score.py`` passes in: the harness's contract is
``Arm = Callable[[sqlite3.Connection, str], list[str]]`` and the store is a different
database from the gold's corpus. Session ids are identical across the two (ADR-0011 §6),
which is what makes the same gold score both.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
from collections.abc import Callable

Arm = Callable[[sqlite3.Connection, str], list[str]]

K = 5
CANDIDATE_ROWS = 200
STORE_ENV = "KNOWLEDGE_PROOF_STORE"
DEFAULT_STORE = pathlib.Path.home() / ".local/share/studyloop/knowledge-proof/learning-memory.db"


def _store_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get(STORE_ENV, str(DEFAULT_STORE)))


def _open_store_ro(path: pathlib.Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"learning-memory store not found: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def B1_clean() -> Arm:  # noqa: N802 - arm names are receipt labels, matched to the spec
    """fusion-spec-v1 ``B1_clean``: prose-only FTS over the archive-ingested store.

    Planner = ``learning_memory.store.plan_prose_query`` (phrase-quote every token, OR-join,
    strip control/surrogate code points); ranking = ``bm25(prose_fts)`` over
    ``CANDIDATE_ROWS`` event rows; dedup by session id, first occurrence wins;
    tie-break bm25 then ``events.id``; exactly the first ``K`` distinct session ids.
    """
    from learning_memory.store import plan_prose_query

    conn = _open_store_ro(_store_path())

    def arm(_archive: sqlite3.Connection, question: str) -> list[str]:
        planned = plan_prose_query(question)
        if not planned:
            return []
        rows = conn.execute(
            "SELECT e.session_id FROM prose_fts "
            "JOIN events AS e ON e.id = prose_fts.rowid "
            "WHERE prose_fts MATCH ? "
            "ORDER BY bm25(prose_fts), e.id "
            f"LIMIT {CANDIDATE_ROWS}",
            (planned,),
        ).fetchall()
        seen: list[str] = []
        for (sid,) in rows:
            if sid not in seen:
                seen.append(sid)
                if len(seen) == K:
                    break
        return seen

    return arm
