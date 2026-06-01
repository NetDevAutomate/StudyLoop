"""CLI wrapper for lightweight studyloop self-tests."""

from __future__ import annotations

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.self_test import SelfTestResult, exit_code_for, results_as_json, run_self_tests

STATUS_ICONS = {
    "pass": "[green]\u2713[/green]",
    "warn": "[yellow]![/yellow]",
    "fail": "[red]\u2717[/red]",
}


def _summary_line(results: list[SelfTestResult]) -> str:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for result in results:
        counts[result.status] += 1

    def label(count: int, singular: str, plural: str) -> str:
        return f"{count} {singular if count == 1 else plural}"

    return (
        "self-test: "
        f"{label(counts['pass'], 'passed', 'passed')}, "
        f"{label(counts['warn'], 'warning', 'warnings')}, "
        f"{label(counts['fail'], 'failure', 'failures')}."
    )


@click.command("self-test")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array.")
@click.option("--quiet", is_flag=True, help="Summary line only.")
@click.pass_context
def self_test(ctx: click.Context, as_json: bool, quiet: bool) -> None:
    """Run lightweight post-install checks."""
    results = run_self_tests()
    exit_code = exit_code_for(results)

    if as_json:
        click.echo(results_as_json(results))
        ctx.exit(exit_code)
        return

    if quiet:
        click.echo(_summary_line(results))
        ctx.exit(exit_code)
        return

    table = Table(title="studyloop self-test", show_lines=False)
    table.add_column("Status", justify="center", width=3)
    table.add_column("Check", style="cyan")
    table.add_column("Details")

    for result in results:
        table.add_row(STATUS_ICONS.get(result.status, "?"), result.name, result.message)

    console.print(table)
    console.print(f"\n{_summary_line(results)}")
    ctx.exit(exit_code)
