"""``studyloop extract-struggles`` — extract struggle signals into study_progress.

Two modes:
- ``--incremental --session-id X`` : process exactly one session (used by the
  per-harness session-end hooks).  If no session-id is given, falls back to the
  most-recently-updated kiro_cli session.
- ``--full`` : process every kiro_cli session that has no study_progress rows
  yet (the backfill / reconcile path).

``--dry-run`` prints what would be written without touching the DB.

The actual LLM extractor is wired in a later phase; this command currently uses
the stub extractor so the plumbing is fully testable with zero API cost.  The
``--llm`` flag is reserved for when the real extractor lands.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import click

from studyloop.cli._shared import console

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def _get_extractor(use_llm: bool):
    """Return the extractor function for the selected backend.

    Imported lazily so ``--help`` and ``--dry-run`` stay cheap and never pull in
    httpx / LLM machinery unless actually extracting with the real backend.
    """
    if use_llm:
        try:
            from studyloop.extractors.llm import extract_struggles
        except ImportError as exc:  # llm.py lands in a later phase
            raise click.ClickException(
                "LLM extractor not available yet — run without --llm to use the stub."
            ) from exc
        return extract_struggles
    from studyloop.extractors.stub import extract_struggles

    return extract_struggles


def _fetch_messages(conn, session_id: str) -> list[dict[str, Any]]:
    """Return ordered message dicts for a session."""
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY seq",
        (session_id,),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _session_source(conn, session_id: str) -> str | None:
    row = conn.execute("SELECT source FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row["source"] if row else None


def _most_recent_kiro_session(conn) -> str | None:
    row = conn.execute(
        "SELECT id FROM sessions WHERE source = 'kiro_cli' ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def _unprocessed_kiro_sessions(conn, limit: int | None) -> list[str]:
    """kiro_cli sessions that have no study_progress rows derived from them.

    study_progress is keyed by (topic, concept), not by session, so 'unprocessed'
    is approximated as: every kiro_cli session.  Idempotent upsert makes
    re-processing safe, so the worst case is redundant (cheap, deduped) work.
    """
    sql = "SELECT id FROM sessions WHERE source = 'kiro_cli' ORDER BY updated_at DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [r["id"] for r in conn.execute(sql).fetchall()]


def _process_one(
    conn,
    session_id: str,
    extractor_fn,
    *,
    dry_run: bool,
) -> int:
    """Pre-filter then extract+write a single session.  Returns rows written."""
    from studyloop.extractors.pipeline import extract_and_write, pre_filter

    source = _session_source(conn, session_id)
    messages: Sequence[dict[str, Any]] = _fetch_messages(conn, session_id)
    if not pre_filter(session_id, source, messages):
        console.print(f"[dim]skip[/dim] {session_id} (source={source}, filtered)")
        return 0
    written = extract_and_write(session_id, messages, extractor_fn, dry_run=dry_run)
    verb = "would write" if dry_run else "wrote"
    console.print(f"[green]{verb}[/green] {written} row(s) from {session_id}")
    return written


@click.command(name="extract-struggles")
@click.option(
    "--incremental", is_flag=True, help="Process one session (default: most recent kiro)."
)
@click.option("--full", "full", is_flag=True, help="Process all kiro_cli sessions (backfill).")
@click.option("--session-id", default=None, help="Target session id (with --incremental).")
@click.option("--dry-run", is_flag=True, help="Print what would be written; do not write.")
@click.option("--llm", "use_llm", is_flag=True, help="Use the LLM extractor (default: stub).")
@click.option("--limit", type=int, default=None, help="Cap sessions processed (with --full).")
def extract_struggles_cmd(
    incremental: bool,
    full: bool,
    session_id: str | None,
    dry_run: bool,
    use_llm: bool,
    limit: int | None,
) -> None:
    """Extract topics the learner struggled with into study_progress."""
    if full and incremental:
        raise click.UsageError("Use either --full or --incremental, not both.")
    if not full and not incremental:
        # Default to incremental for the hook-friendly common case.
        incremental = True

    from studyloop.history import _connection

    conn = _connection._connect()
    if conn is None:
        raise click.ClickException(
            "Could not open sessions.db (is agent-session-tools installed?)."
        )

    extractor_fn = _get_extractor(use_llm)
    total = 0
    try:
        if incremental:
            target = session_id or _most_recent_kiro_session(conn)
            if not target:
                console.print("[yellow]No kiro_cli session found to process.[/yellow]")
                return
            total = _process_one(conn, target, extractor_fn, dry_run=dry_run)
        else:  # full
            targets = _unprocessed_kiro_sessions(conn, limit)
            if not targets:
                console.print("[yellow]No kiro_cli sessions found.[/yellow]")
                return
            for sid in targets:
                total += _process_one(conn, sid, extractor_fn, dry_run=dry_run)
    finally:
        conn.close()

    suffix = " (dry run — nothing written)" if dry_run else ""
    console.print(f"[bold]Total: {total} row(s){suffix}[/bold]")


__all__ = ["extract_struggles_cmd"]
