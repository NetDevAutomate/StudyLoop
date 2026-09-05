"""``studyloop extract-struggles`` — extract struggle signals into study_progress.

Two modes:
- ``--incremental --session-id X`` : process exactly one session (used by the
  operator-driven reconciliation path). If no session-id is given, ``--harness``
  is required and selects that harness's most recent session.
- ``--full --harness X`` : process sessions from one explicitly selected
  release harness.

``--dry-run`` prints what live extraction would write without touching the DB.
The command requires an explicit live model and never selects a fixture-backed
extractor.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Any

import click

from agent_session_tools.context.legacy import session_ids, session_messages, session_record
from agent_session_tools.context.scope import ScopeError
from studyloop.cli._shared import console
from studyloop.harnesses import RELEASE_HARNESSES, SESSION_SOURCE_BY_HARNESS

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def _get_extractor(model: str):
    """Return the live extractor pinned to the explicitly selected model.

    Imported lazily so ``--help`` and ``--dry-run`` stay cheap and never pull in
    the Bedrock SDK unless extraction actually runs.
    """
    try:
        from studyloop.extractors.llm import extract_struggles
    except ImportError as exc:
        raise click.ClickException(
            "Live extractor unavailable. Install StudyLoop with the Bedrock extra."
        ) from exc
    return partial(extract_struggles, model=model)


def _fetch_messages(conn, session_id: str) -> list[dict[str, Any]]:
    """Return ordered message dicts for a session."""
    rows = session_messages(conn, session_id)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _session_source(conn, session_id: str) -> str | None:
    row = session_record(conn, session_id)
    return row["source"] if row else None


def _most_recent_session(conn, source: str) -> str | None:
    ids = session_ids(conn, source=source, limit=1)
    return ids[0] if ids else None


def _sessions_for_source(conn, source: str, limit: int | None) -> list[str]:
    """Return sessions for one operator-selected release harness.

    study_progress is keyed by (topic, concept), not by session, so 'unprocessed'
    is approximated as every session for the source. Idempotent upsert makes
    re-processing safe, so the worst case is redundant (cheap, deduped) work.
    """
    return session_ids(conn, source=source, limit=limit)


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
    if source is None:
        raise ScopeError("Session unavailable in the configured scope")
    messages: Sequence[dict[str, Any]] = _fetch_messages(conn, session_id)
    if not pre_filter(session_id, source, messages):
        console.print(f"[dim]skip[/dim] {session_id} (source={source}, filtered)")
        return 0
    written = extract_and_write(
        session_id,
        messages,
        extractor_fn,
        dry_run=dry_run,
        connection=conn,
    )
    verb = "would write" if dry_run else "wrote"
    console.print(f"[green]{verb}[/green] {written} row(s) from {session_id}")
    return written


@click.command(name="extract-struggles")
@click.option("--incremental", is_flag=True, help="Process one session from the selected harness.")
@click.option(
    "--full", "full", is_flag=True, help="Process all sessions from the selected harness."
)
@click.option("--session-id", default=None, help="Target session id (with --incremental).")
@click.option(
    "--harness",
    type=click.Choice(RELEASE_HARNESSES),
    default=None,
    help="Harness used to select latest/full sessions when no session id is supplied.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Run the selected model and report results without progress writes.",
)
@click.option(
    "--model",
    required=True,
    envvar="STUDYLOOP_EXTRACTOR_MODEL",
    help="Live Bedrock model ID (or set STUDYLOOP_EXTRACTOR_MODEL).",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Cap sessions processed (with --full).",
)
def extract_struggles_cmd(
    incremental: bool,
    full: bool,
    session_id: str | None,
    dry_run: bool,
    model: str,
    harness: str | None,
    limit: int | None,
) -> None:
    """Extract topics the learner struggled with into study_progress."""
    if full and incremental:
        raise click.UsageError("Use either --full or --incremental, not both.")
    if not full and not incremental:
        # Default to incremental for the hook-friendly common case.
        incremental = True
    if full and session_id:
        raise click.UsageError("--session-id can only be used with --incremental.")
    if harness is None and (full or session_id is None):
        raise click.UsageError(
            "Choose --harness when selecting latest or full sessions, "
            "or provide an explicit --session-id."
        )

    selected_source = SESSION_SOURCE_BY_HARNESS[harness] if harness else None

    from studyloop.history import _connection

    conn = _connection._connect()
    if conn is None:
        raise click.ClickException(
            "Could not open sessions.db (is agent-session-tools installed?)."
        )

    extractor_fn = _get_extractor(model)
    total = 0
    try:
        if incremental:
            target = session_id or _most_recent_session(conn, selected_source or "")
            if not target:
                console.print(f"[yellow]No {selected_source} session found to process.[/yellow]")
                return
            total = _process_one(conn, target, extractor_fn, dry_run=dry_run)
        else:  # full
            targets = _sessions_for_source(conn, selected_source or "", limit)
            if not targets:
                console.print(f"[yellow]No {selected_source} sessions found.[/yellow]")
                return
            for sid in targets:
                total += _process_one(conn, sid, extractor_fn, dry_run=dry_run)
    except ScopeError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        conn.close()

    suffix = " (dry run — nothing written)" if dry_run else ""
    console.print(f"[bold]Total: {total} row(s){suffix}[/bold]")


__all__ = ["extract_struggles_cmd"]
