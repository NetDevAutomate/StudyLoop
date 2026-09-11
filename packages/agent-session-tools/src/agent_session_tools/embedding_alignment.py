"""Alignment accounting for ``message_embeddings``.

A vector index has states the FTS index cannot have, so the FTS pair
(``tiering.fts_integrity`` / ``tiering.repair_fts``) does not transfer as is.
This module is the embeddings analogue with five counts instead of one:

* **missing** -- an eligible message (admitted source, prose role, long enough
  to embed) with no vector for the configured model. The backlog; only the
  embed job (``embedding_store.embed``) can reduce it because it needs the model.
* **orphaned** -- a vector whose message is gone. Impossible with migration 48's
  delete trigger; counted anyway because the invariant is proved, not assumed.
* **stale** -- a vector whose ``content_sha256`` is not the hash of the message's
  current content. Impossible with the content trigger for the same reason.
* **model_mismatch** -- a vector embedded by another model or dimension than the
  configured one; comparing it byte-wise with the configured model's vectors
  would be silently wrong, so it is reported and swept, never compared.
* **hidden** -- a vector for a message whose session is no longer admitted
  (source retired after embedding). Hidden rows are never returned by product
  reads; their vectors are an egress the read predicate cannot see, so they go.

Everything except ``missing`` is repaired by :func:`sweep` with plain SQL.
Nothing here loads a model or the ``sqlite-vec`` extension, so the doctor can
run on any connection.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass

from .sources import SUPPORTED_SOURCES

#: Roles whose text is worth a vector. Tool traffic is code and payloads.
ELIGIBLE_ROLES: tuple[str, ...] = ("user", "assistant")

#: Below this many characters a message is a fragment ("ok", "yes", "thanks").
DEFAULT_MIN_CONTENT_LENGTH = 50

_SHA256_FUNCTION = "studyloop_sha256"


def content_sha256(text: str) -> str:
    """The hash stored beside every vector: SHA-256 of the exact message text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def register_sha256(conn: sqlite3.Connection) -> None:
    """Expose :func:`content_sha256` to SQL so stale rows are a WHERE clause.

    Idempotent per connection: SQLite refuses to redefine a function while the
    connection still holds prepared statements that use it, so a second call on
    the same connection must be a no-op rather than a re-registration.
    """
    already = conn.execute(
        "SELECT 1 FROM pragma_function_list WHERE name = ?", (_SHA256_FUNCTION,)
    ).fetchone()
    if already:
        return
    conn.create_function(
        _SHA256_FUNCTION, 1, lambda text: content_sha256(text or ""), deterministic=True
    )


def eligible_predicate(
    *, min_content_length: int = DEFAULT_MIN_CONTENT_LENGTH
) -> tuple[str, list[object]]:
    """SQL predicate over ``messages m JOIN sessions s`` selecting embeddable rows.

    Returned as a fragment plus bound values so the embed job and the doctor
    cannot disagree about what "eligible" means.
    """
    sources = sorted(SUPPORTED_SOURCES)
    roles = list(ELIGIBLE_ROLES)
    sql = (
        f"s.source IN ({','.join('?' for _ in sources)}) "
        f"AND m.role IN ({','.join('?' for _ in roles)}) "
        "AND m.content IS NOT NULL AND length(m.content) >= ?"
    )
    return sql, [*sources, *roles, min_content_length]


@dataclass(frozen=True, slots=True)
class AlignmentReport:
    """The five alignment counts for one configured model, plus the totals behind them."""

    model: str
    dim: int | None
    min_content_length: int
    eligible: int
    embedded: int
    missing: int
    orphaned: int
    stale: int
    model_mismatch: int
    hidden: int
    rows: int

    @property
    def aligned(self) -> bool:
        """True when every vector describes a live, admitted, unchanged message of the right model."""
        return (
            self.orphaned == 0
            and self.stale == 0
            and self.model_mismatch == 0
            and self.hidden == 0
        )

    @property
    def complete(self) -> bool:
        """Aligned and with no backlog."""
        return self.aligned and self.missing == 0

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "aligned": self.aligned, "complete": self.complete}


def _mismatch_clause(dim: int | None) -> tuple[str, list[object]]:
    if dim is None:
        return "e.model != ?", []
    return "(e.model != ? OR e.dim != ?)", [dim]


def alignment_report(
    conn: sqlite3.Connection,
    *,
    model: str,
    dim: int | None = None,
    min_content_length: int = DEFAULT_MIN_CONTENT_LENGTH,
) -> AlignmentReport:
    """Count the five alignment states for ``model`` on ``conn`` (read-only)."""
    register_sha256(conn)
    eligible_sql, eligible_params = eligible_predicate(
        min_content_length=min_content_length
    )
    sources = sorted(SUPPORTED_SOURCES)
    source_placeholders = ",".join("?" for _ in sources)

    eligible = conn.execute(
        f"SELECT COUNT(*) FROM messages m JOIN sessions s ON s.id = m.session_id "
        f"WHERE {eligible_sql}",
        eligible_params,
    ).fetchone()[0]
    missing = conn.execute(
        f"SELECT COUNT(*) FROM messages m JOIN sessions s ON s.id = m.session_id "
        f"WHERE {eligible_sql} AND NOT EXISTS ("
        "SELECT 1 FROM message_embeddings e WHERE e.message_id = m.id AND e.model = ?)",
        [*eligible_params, model],
    ).fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM message_embeddings").fetchone()[0]
    orphaned = conn.execute(
        "SELECT COUNT(*) FROM message_embeddings e "
        "WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.id = e.message_id)"
    ).fetchone()[0]
    stale = conn.execute(
        "SELECT COUNT(*) FROM message_embeddings e JOIN messages m ON m.id = e.message_id "
        f"WHERE e.content_sha256 != {_SHA256_FUNCTION}(m.content)"
    ).fetchone()[0]
    mismatch_sql, mismatch_params = _mismatch_clause(dim)
    model_mismatch = conn.execute(
        f"SELECT COUNT(*) FROM message_embeddings e WHERE {mismatch_sql}",
        [model, *mismatch_params],
    ).fetchone()[0]
    hidden = conn.execute(
        "SELECT COUNT(*) FROM message_embeddings e "
        "JOIN messages m ON m.id = e.message_id JOIN sessions s ON s.id = m.session_id "
        f"WHERE s.source NOT IN ({source_placeholders})",
        sources,
    ).fetchone()[0]
    return AlignmentReport(
        model=model,
        dim=dim,
        min_content_length=min_content_length,
        eligible=eligible,
        embedded=eligible - missing,
        missing=missing,
        orphaned=orphaned,
        stale=stale,
        model_mismatch=model_mismatch,
        hidden=hidden,
        rows=rows,
    )


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Rows deleted per alignment state by :func:`sweep`."""

    orphaned: int
    stale: int
    model_mismatch: int
    hidden: int

    @property
    def deleted(self) -> int:
        return self.orphaned + self.stale + self.model_mismatch + self.hidden

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "deleted": self.deleted}


def sweep(
    conn: sqlite3.Connection,
    *,
    model: str,
    dim: int | None = None,
    model_mismatch: bool = True,
) -> SweepResult:
    """Delete every misaligned vector (everything but the backlog), in one transaction.

    Vectors are derived data regenerated by the embed job, so deleting a wrong
    one loses nothing but the time to recompute it; keeping it would be the
    loss (a stale or hidden vector answers a question the message no longer
    asks). ``model_mismatch=False`` leaves another model's rows alone: removing
    them is a choice (``session-maint embed --replace-model``); the other three
    states are never a choice. The caller commits.
    """
    register_sha256(conn)
    sources = sorted(SUPPORTED_SOURCES)
    source_placeholders = ",".join("?" for _ in sources)
    orphaned = conn.execute(
        "DELETE FROM message_embeddings WHERE message_id NOT IN (SELECT id FROM messages)"
    ).rowcount
    stale = conn.execute(
        "DELETE FROM message_embeddings WHERE rowid IN ("
        "SELECT e.rowid FROM message_embeddings e JOIN messages m ON m.id = e.message_id "
        f"WHERE e.content_sha256 != {_SHA256_FUNCTION}(m.content))"
    ).rowcount
    mismatched = 0
    if model_mismatch:
        mismatch_sql, mismatch_params = _mismatch_clause(dim)
        mismatched = conn.execute(
            "DELETE FROM message_embeddings WHERE rowid IN ("
            f"SELECT e.rowid FROM message_embeddings e WHERE {mismatch_sql})",
            [model, *mismatch_params],
        ).rowcount
    hidden = conn.execute(
        "DELETE FROM message_embeddings WHERE rowid IN ("
        "SELECT e.rowid FROM message_embeddings e "
        "JOIN messages m ON m.id = e.message_id JOIN sessions s ON s.id = m.session_id "
        f"WHERE s.source NOT IN ({source_placeholders}))",
        sources,
    ).rowcount
    return SweepResult(
        orphaned=orphaned, stale=stale, model_mismatch=mismatched, hidden=hidden
    )


def missing_messages(
    conn: sqlite3.Connection,
    *,
    model: str,
    min_content_length: int = DEFAULT_MIN_CONTENT_LENGTH,
    limit: int | None = None,
) -> list[tuple[str, str]]:
    """``(message_id, content)`` for eligible messages with no vector for ``model``.

    Ordered by message rowid so repeated bounded runs make progress in one
    direction. The embed job re-reads the content inside its write transaction
    and hashes what it actually embedded; this list only chooses candidates.
    """
    eligible_sql, eligible_params = eligible_predicate(
        min_content_length=min_content_length
    )
    sql = (
        "SELECT m.id, m.content FROM messages m JOIN sessions s ON s.id = m.session_id "
        f"WHERE {eligible_sql} AND NOT EXISTS ("
        "SELECT 1 FROM message_embeddings e WHERE e.message_id = m.id AND e.model = ?) "
        "ORDER BY m.rowid"
    )
    params: list[object] = [*eligible_params, model]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [(row[0], row[1]) for row in conn.execute(sql, params)]
