"""Focus and prune commands — attention filtering and hot-DB size management.

``studyloop focus``  — declare the (max 3) topics you're actively studying.
``studyloop prune``  — trim old sessions from the local DB, but only those
                       verified present in the configured full DB.
"""

from __future__ import annotations

import click

from studyloop.cli._shared import console


@click.group("focus", invoke_without_command=True)
@click.pass_context
def focus_group(ctx: click.Context) -> None:
    """Show or set your current focus topics (max 3).

    Focus shapes what 'studyloop now' and review sessions recommend.
    It never deletes data — that's 'studyloop prune', which is age-based.
    """
    if ctx.invoked_subcommand is not None:
        return

    from studyloop.focus import STALE_AFTER_DAYS, get_focus

    state = get_focus()
    if not state.is_set:
        console.print("[yellow]No focus topics set.[/yellow]")
        console.print("  Suggestions:  [bold]studyloop focus suggest[/bold]")
        console.print('  Set:          [bold]studyloop focus set "python" "sql"[/bold]')
        return

    console.print("[bold]Current focus:[/bold]")
    for topic in state.topics:
        console.print(f"  ◆ {topic}")
    if state.updated:
        console.print(f"\n  [dim]Confirmed: {state.updated}[/dim]")
    if state.is_stale:
        console.print(
            f"\n[yellow]Focus is over {STALE_AFTER_DAYS} days old — still "
            "accurate?[/yellow] Reconfirm with [bold]studyloop focus set ...[/bold]"
        )


@focus_group.command("set")
@click.argument("topics", nargs=-1, required=True)
@click.option(
    "--days",
    default=30,
    show_default=True,
    help="Refocus window: pull focus history newer than N days, prune non-focus older than N days.",
)
@click.option(
    "--no-refocus",
    is_flag=True,
    help="Only save focus topics; skip the pull/prune data movement.",
)
def focus_set(topics: tuple[str, ...], days: int, no_refocus: bool) -> None:
    """Set focus topics (1-3). Replaces the current focus.

    Saving is followed by the refocus data movement: focus-topic
    conversations from the last N days are pulled from the full DB into the
    local DB, then non-focus sessions older than N days are pruned (under
    the verify-in-full safety invariant). If the full DB is unreachable the
    focus still saves and the movement is deferred — run
    'studyloop focus apply' later.

    Example: studyloop focus set "python" "sql window functions"
    """
    from studyloop.focus import set_focus

    try:
        path = set_focus(list(topics))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    console.print("[bold green]Focus updated:[/bold green]")
    for topic in topics:
        console.print(f"  ◆ {topic}")
    console.print(f"  [dim]Saved to {path}[/dim]")

    if no_refocus:
        console.print("[dim]Data movement skipped (--no-refocus).[/dim]")
        return
    _apply_refocus(days)


@focus_group.command("apply")
@click.option(
    "--days",
    default=30,
    show_default=True,
    help="Refocus window (see 'focus set --help').",
)
@click.option("--dry-run", is_flag=True, help="Preview the data movement only.")
def focus_apply(days: int, dry_run: bool) -> None:
    """Run/retry the refocus data movement for the saved focus topics.

    Use after 'focus set' was deferred (external volume unmounted), or to
    re-pull focus history at any time.
    """
    from studyloop.focus import get_focus

    state = get_focus()
    if not state.is_set:
        console.print("[yellow]No focus topics set — nothing to apply.[/yellow]")
        raise SystemExit(1)
    _apply_refocus(days, dry_run=dry_run)


def _apply_refocus(days: int, dry_run: bool = False) -> None:
    """Shared refocus runner: pull focus history, prune stale non-focus."""
    from studyloop.focus import get_focus

    try:
        from agent_session_tools.tiering import refocus
    except ImportError:
        console.print(
            "[dim]agent-session-tools not installed — focus saved, "
            "no data movement available.[/dim]"
        )
        return

    topics = get_focus().topics
    try:
        stats = refocus(topics, days=days, dry_run=dry_run)
    except ValueError:
        # Tiering not configured — focus is still a useful attention filter.
        console.print(
            "[dim]No full DB configured (database.full_db_path) — focus saved, "
            "data movement skipped.[/dim]"
        )
        return
    except FileNotFoundError as exc:
        console.print(f"[yellow]Deferred: {exc}[/yellow]")
        return

    tag = " (dry run)" if dry_run else ""
    console.print(f"\n[bold]Refocus{tag}:[/bold]")
    console.print(f"  Pulled from full DB:   {stats.pulled_sessions} session(s)")
    console.print(f"  Kept (match focus):    {stats.kept_in_focus} session(s)")
    if stats.prune:
        console.print(
            f"  Pruned (old, no match): {stats.prune.sessions_deleted}"
            f"{' (would prune ' + str(stats.prune.verified) + ')' if dry_run else ''}"
        )
        if stats.prune.skipped_unverified:
            console.print(
                f"  [yellow]Skipped {stats.prune.skipped_unverified} not yet in "
                "full DB — run 'session-maint sync-full'.[/yellow]"
            )


@focus_group.command("suggest")
@click.option("--days", default=30, show_default=True, help="Look-back window.")
def focus_suggest(days: int) -> None:
    """Suggest focus topics from recent sessions, struggles, and config.

    Review the suggestions, then confirm with 'studyloop focus set ...'.
    Designed to be run by your AI mentor during DB maintenance — the agent
    proposes, you decide.
    """
    from studyloop.focus import get_focus, suggest_focus

    suggestions = suggest_focus(days=days)
    if not suggestions:
        console.print("[dim]No study evidence found to suggest from yet.[/dim]")
        return

    console.print(f"[bold]Focus suggestions[/bold] (last {days} days):\n")
    for i, (topic, evidence) in enumerate(suggestions, 1):
        console.print(f"  {i}. [cyan]{topic}[/cyan] — [dim]{evidence}[/dim]")

    current = get_focus()
    if current.is_set:
        console.print(f"\n  [dim]Current focus: {', '.join(current.topics)}[/dim]")
    console.print('\nConfirm up to 3 with: [bold]studyloop focus set "topic1" "topic2"[/bold]')


@focus_group.command("clear")
def focus_clear() -> None:
    """Clear all focus topics."""
    from studyloop.focus import clear_focus

    clear_focus()
    console.print("[green]Focus cleared.[/green]")


@click.command("prune")
@click.option("--days", default=30, show_default=True, help="Prune sessions older than N days.")
@click.option(
    "--apply",
    "apply_",
    is_flag=True,
    help="Actually delete. Without this flag, prune only previews (dry run).",
)
@click.option("--no-vacuum", is_flag=True, help="Skip VACUUM after pruning.")
def prune(days: int, apply_: bool, no_vacuum: bool) -> None:
    """Trim old sessions from the local sessions DB (small-drive machines).

    Safety invariant: a session is only deleted when the configured full DB
    (database.full_db_path in config.yaml) holds the same session with a
    matching content hash and at least as many messages. Unverified sessions
    are skipped and reported. Learning data (progress, concepts, reviews) is
    never touched.
    """
    try:
        from agent_session_tools.tiering import prune_hot
    except ImportError:
        console.print(
            "[red]agent-session-tools is not installed.[/red] Run: studyloop install tools"
        )
        raise SystemExit(1) from None

    dry_run = not apply_
    mode = "[yellow](dry run — pass --apply to delete)[/yellow]" if dry_run else ""
    console.print(f"[bold]Pruning sessions older than {days} days[/bold] {mode}\n")

    try:
        stats = prune_hot(days=days, dry_run=dry_run, vacuum=not no_vacuum)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    console.print(f"  Candidates:               {stats.candidates}")
    console.print(f"  Verified in full DB:      {stats.verified}")
    if stats.skipped_unverified:
        console.print(f"  [yellow]Skipped (not in full DB): {stats.skipped_unverified}[/yellow]")
        console.print("  [dim]Run 'session-maint sync-full' to back them up first.[/dim]")
    if dry_run:
        console.print(
            f"\nWould delete [bold]{stats.verified}[/bold] session(s) "
            f"({stats.messages_deleted:,} messages)."
        )
    else:
        console.print(
            f"\n[green]Deleted {stats.sessions_deleted} session(s) "
            f"({stats.messages_deleted:,} messages), "
            f"reclaimed {stats.reclaimed_mb:.1f} MB.[/green]"
        )
