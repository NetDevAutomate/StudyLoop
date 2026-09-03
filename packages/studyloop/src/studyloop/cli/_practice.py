"""Practice command group."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.learning.practice import peek_verification_command, verify_practice_task


@click.group("practice")
def practice_group() -> None:
    """Hands-on practice task helpers."""


@practice_group.command("verify")
@click.argument("practice_json", type=click.Path(exists=True, path_type=Path))
@click.option("--task", "task_index", type=int, required=True, help="1-based task index.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--run-command", is_flag=True, help="Allow command verification to execute.")
@click.option(
    "--yes",
    is_flag=True,
    help=(
        "Confirm running a command-verification task's shell command "
        "without an interactive prompt. Required in non-interactive "
        "contexts (CI, scripts) -- without it, or an interactive y at the "
        "prompt, the command is shown but not run."
    ),
)
@click.option("--notes", default="", help="Notes/evidence from the practice attempt.")
@click.option(
    "--timeout",
    "timeout_seconds",
    type=int,
    default=None,
    help="Command timeout in seconds.",
)
@click.option("--json", "json_output", is_flag=True, help="Output attempt result as JSON.")
def practice_verify(
    practice_json: Path,
    task_index: int,
    workdir: Path | None,
    run_command: bool,
    yes: bool,
    notes: str,
    timeout_seconds: int | None,
    json_output: bool,
) -> None:
    """Verify a practice task and record the attempt.

    A command-verification task's ``verification.command`` comes from a
    practice-deck JSON file -- possibly LLM-authored -- and is treated as
    data to show a human, not an instruction to trust blindly (R-15). With
    ``--run-command``, the resolved command is always printed before
    anything runs; actually running it additionally requires ``--yes`` or an
    interactive ``y`` at the prompt. Without either, nothing executes and
    this command exits with status 2.
    """
    # R-15b (TOCTOU): the string a human confirms, not just a bool, crosses
    # into verify_practice_task -- it reloads the deck itself and refuses to
    # run anything if the freshly-loaded command no longer equals this one,
    # closing the window between showing a command and running it during
    # which the deck file could be rewritten to something else entirely.
    confirmed_command: str | None = None
    if run_command:
        try:
            kind, command = peek_verification_command(practice_json, task_index=task_index)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        if kind == "command" and command:
            console.print(f"Command: {command}")
            # Short-circuits: --yes skips the interactive prompt entirely,
            # and a non-interactive stdin (scripts, CI, CliRunner) skips it
            # too rather than blocking on a read that will never resolve.
            confirmed = yes or (
                sys.stdin.isatty() and click.confirm("Run this command now?", default=False)
            )
            if not confirmed:
                console.print("[yellow]Not confirmed — nothing executed.[/yellow]")
                raise SystemExit(2)
            confirmed_command = command

    try:
        result = verify_practice_task(
            practice_json,
            task_index=task_index,
            workdir=workdir,
            run_command=run_command,
            confirmed_command=confirmed_command,
            notes=notes,
            timeout_seconds=timeout_seconds,
        )
    except (PermissionError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(result.to_json_dict(), indent=2))
        return

    status = "[green]passed[/green]" if result.passed else "[red]needs repair[/red]"
    table = Table(title="Practice Verification")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Result", status)
    table.add_row("Task", f"{result.task_index}: {result.task_prompt}")
    table.add_row("Kind", result.verification_kind)
    if result.command:
        table.add_row("Command", result.command)
        table.add_row("Exit code", str(result.exit_code))
    if result.missing_artifacts:
        table.add_row("Missing artifacts", ", ".join(result.missing_artifacts))
    if result.evidence_prompts:
        table.add_row("Evidence prompts", " | ".join(result.evidence_prompts))
    table.add_row("Progress recorded", "yes" if result.progress_recorded else "no")
    console.print(table)
