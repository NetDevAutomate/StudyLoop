"""Practice command group."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.learning.practice import verify_practice_task


@click.group("practice")
def practice_group() -> None:
    """Hands-on practice task helpers."""


@practice_group.command("verify")
@click.argument("practice_json", type=click.Path(exists=True, path_type=Path))
@click.option("--task", "task_index", type=int, required=True, help="1-based task index.")
@click.option("--workdir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--run-command", is_flag=True, help="Allow command verification to execute.")
@click.option("--notes", default="", help="Notes/evidence from the practice attempt.")
@click.option("--json", "json_output", is_flag=True, help="Output attempt result as JSON.")
def practice_verify(
    practice_json: Path,
    task_index: int,
    workdir: Path | None,
    run_command: bool,
    notes: str,
    json_output: bool,
) -> None:
    """Verify a practice task and record the attempt."""
    try:
        result = verify_practice_task(
            practice_json,
            task_index=task_index,
            workdir=workdir,
            run_command=run_command,
            notes=notes,
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
    table.add_row("Progress recorded", "yes" if result.progress_recorded else "no")
    console.print(table)
