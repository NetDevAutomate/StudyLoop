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
    conn = _open_store_ro(_store_path())

    def arm(_archive: sqlite3.Connection, question: str) -> list[str]:
        return _prose_ranked_sessions(conn, question)[:K]

    return arm


def _dedup_sessions(rows: list[tuple[str]]) -> list[str]:
    """Collapse a ranked row list to distinct session ids, first occurrence wins."""
    seen: list[str] = []
    for (sid,) in rows:
        if sid not in seen:
            seen.append(sid)
    return seen


def _prose_ranked_sessions(conn: sqlite3.Connection, question: str) -> list[str]:
    """The full ``B1_clean`` session ranking (deduped, before the K cut).

    Shared by ``B1_clean`` (which takes the first ``K``) and the fused arm (which needs the
    whole list for reciprocal rank fusion). Ranking is exactly fusion-spec-v1's:
    ``bm25(prose_fts)`` over ``CANDIDATE_ROWS`` event rows, tie-break ``events.id``.
    """
    from learning_memory.store import plan_prose_query

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
    return _dedup_sessions(rows)


CLAIMS_WRITER_PREFIX = "sonnet5/writer-v2/"
RRF_K = 60


def _build_claims_index(store: sqlite3.Connection) -> sqlite3.Connection:
    """In-memory FTS5 index over writer-v2 claims (fusion-spec-v2 ``recall_claims``).

    The store has no claims FTS by design (claims are read through their citations); the arm
    builds its own, read-only against the store, one row per claim with ``rowid`` = the
    claim's rowid so the ranking tie-break is the insertion order.
    """
    mem = sqlite3.connect(":memory:")
    mem.execute(
        "CREATE VIRTUAL TABLE claims_fts USING fts5("
        "title, statement, tags, session_id UNINDEXED, tokenize='porter unicode61')"
    )
    rows = store.execute(
        "SELECT rowid, title, statement, tags, session_id FROM claims "
        "WHERE writer LIKE ? ORDER BY rowid",
        (CLAIMS_WRITER_PREFIX + "%",),
    ).fetchall()
    mem.executemany(
        "INSERT INTO claims_fts(rowid, title, statement, tags, session_id) VALUES (?, ?, ?, ?, ?)",
        [(rid, t or "", s or "", _tags_text(tg), sid) for rid, t, s, tg, sid in rows],
    )
    mem.commit()
    return mem


def _tags_text(raw: object) -> str:
    """Tags are stored as a JSON array string; index them space-joined."""
    import json

    if not raw:
        return ""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return raw
        if isinstance(parsed, list):
            return " ".join(str(t) for t in parsed)
        return raw
    if isinstance(raw, list | tuple):
        return " ".join(str(t) for t in raw)
    return str(raw)


def _claims_ranked_sessions(index: sqlite3.Connection, question: str) -> list[str]:
    """Full ``recall_claims`` session ranking (deduped, before the K cut)."""
    from learning_memory.store import plan_prose_query

    planned = plan_prose_query(question)
    if not planned:
        return []
    rows = index.execute(
        "SELECT session_id FROM claims_fts WHERE claims_fts MATCH ? "
        f"ORDER BY bm25(claims_fts), rowid LIMIT {CANDIDATE_ROWS}",
        (planned,),
    ).fetchall()
    return _dedup_sessions(rows)


def recall_claims() -> Arm:
    """fusion-spec-v2 ``recall_claims``: claims-only FTS over writer-v2 claims.

    Same planner as ``B1_clean``; ``bm25(claims_fts)`` over ``CANDIDATE_ROWS`` claim rows;
    claim → its ``session_id``; dedup first-wins; tie-break bm25 then claim rowid; first ``K``.
    """
    store = _open_store_ro(_store_path())
    index = _build_claims_index(store)

    def arm(_archive: sqlite3.Connection, question: str) -> list[str]:
        return _claims_ranked_sessions(index, question)[:K]

    return arm


def rrf_fuse(ranked_lists: list[list[str]], k: int = RRF_K) -> list[str]:
    """Reciprocal rank fusion, ranks 1-based, every list weight 1.

    Tie-break: higher score; then the session's best rank in the *first* list (the prose arm,
    by construction of the caller); then the session id string. Pure, so it is testable.
    """
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, sid in enumerate(lst, start=1):
            scores[sid] = scores.get(sid, 0.0) + 1.0 / (k + rank)
    first = ranked_lists[0] if ranked_lists else []
    first_rank = {sid: r for r, sid in enumerate(first, start=1)}
    absent = len(first) + 1
    return sorted(scores, key=lambda s: (-scores[s], first_rank.get(s, absent), s))


def B1_clean_plus_claims() -> Arm:  # noqa: N802 - arm names are receipt labels, matched to the spec
    """fusion-spec-v2 ``B1_clean_plus_claims``: RRF (k=60) of ``B1_clean`` and ``recall_claims``.

    Both inputs are the full deduped rankings (before their K cuts); output is the first ``K``
    of the fused order. No rewriting, no drill-down, no thresholds.
    """
    store = _open_store_ro(_store_path())
    index = _build_claims_index(store)

    def arm(_archive: sqlite3.Connection, question: str) -> list[str]:
        prose = _prose_ranked_sessions(store, question)
        claims = _claims_ranked_sessions(index, question)
        return rrf_fuse([prose, claims])[:K]

    return arm


def B1_planner() -> Arm:  # noqa: N802 - arm names are receipt labels, matched to the spec
    """fusion-spec-v1.1 ``B1_planner``: the SHIPPED index with only the planner replaced.

    Control arm that separates two effects bundled in ``B1_clean``: (i) a planner that
    never throws, and (ii) an index that holds prose only. This arm keeps the shipped
    ``messages_fts`` over every archive row (tool echo, duplicates and all), the shipped
    ``bm25(messages_fts)`` ranking, the shipped scope-visibility predicate, the shipped
    200-row candidate budget and first-seen session dedup, and swaps *only* the query text
    for ``plan_prose_query(question)``.

    If ``B1_planner`` ≈ ``B1_clean``, the lift is the planner. If ``B1_planner`` ≈ ``B1``
    on the questions ``B1`` answered, the lift is the clean index.
    """
    import importlib

    from learning_memory.store import plan_prose_query

    visibility_sql = importlib.import_module("agent_session_tools.context.public").visibility_sql

    def arm(archive: sqlite3.Connection, question: str) -> list[str]:
        planned = plan_prose_query(question)
        if not planned:
            return []
        visible, scope_params = visibility_sql(archive, "s.id")
        rows = archive.execute(
            "SELECT s.id FROM messages m JOIN sessions s ON m.session_id = s.id "
            "JOIN messages_fts ON messages_fts.rowid = m.rowid "
            f"WHERE messages_fts MATCH ? AND {visible} "
            "ORDER BY bm25(messages_fts), m.timestamp DESC "
            f"LIMIT {CANDIDATE_ROWS}",
            [planned, *scope_params],
        ).fetchall()
        seen: list[str] = []
        for (sid,) in rows:
            if sid not in seen:
                seen.append(sid)
                if len(seen) == K:
                    break
        return seen

    return arm
