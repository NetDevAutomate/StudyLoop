"""``studyloop brain`` — publish study plans into a second brain.

Every command has a ``--json`` form because an agent drives these
programmatically at wind-down, while the default output stays readable in a
terminal sidebar. Same convention as ``studyloop plan``.

Module-level imports are click, json and the shared console — nothing else.
:mod:`studyloop.second_brain` is imported inside each command body, which is
what keeps ``studyloop --help`` cheap and makes the optionality contract
provable with ``sys.modules`` (see ``tests/test_second_brain_optionality.py``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, NoReturn

import click

from studyloop.cli._shared import console

if TYPE_CHECKING:
    from studyloop.second_brain.core import PublishResult


def _fail(message: str) -> NoReturn:
    """Print an error and exit non-zero, never a traceback.

    Same helper shape as ``cli/_plan.py``: every failure this maps is something
    the learner can act on, so a stack trace would only bury the fix.
    """
    console.print(f"[red]{message}[/red]")
    raise SystemExit(1)


def _publish_payload(
    provider: str, results: list[PublishResult], *, dry_run: bool
) -> dict[str, object]:
    return {
        "provider": provider,
        "operations": [result.to_json_dict() for result in results],
        "dry_run": dry_run,
    }


def _print_publish(results: list[PublishResult]) -> None:
    """Human form: say what changed, what did not, and what was declined.

    "unchanged" is reported rather than hidden because republishing is the
    normal case — a learner who runs this at every wind-down should see that
    nothing was rewritten, not silence that looks like a failure.
    """
    for result in results:
        for path in result.written:
            console.print(f"[green]written[/green]   {path}")
        for path in result.unchanged:
            console.print(f"[dim]unchanged {path}[/dim]")
        for reason in result.skipped:
            console.print(f"[dim]skipped[/dim]   {reason}")
        for warning in result.warnings:
            console.print(f"[yellow]warning[/yellow]   {warning}")


@click.group("brain")
def brain_group() -> None:
    """Publish study plans and today's study to your second brain.

    Off by default. See the Second Brain guide for the options.
    """


@brain_group.command("status")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def status_cmd(as_json: bool) -> None:
    """Report whether a second brain is configured, and what it can do."""
    from studyloop.second_brain import get_backend

    description = get_backend().describe()
    payload = description.to_json_dict()
    if as_json:
        # click.echo, not console.print: Rich soft-wraps long lines, which turns
        # a vault path into a JSON parse error for whichever agent reads this.
        click.echo(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        console.print(f"{key}: {value}")


@brain_group.command("publish")
@click.option(
    "--plan",
    "plan_ids",
    multiple=True,
    metavar="ID",
    help="Publish this plan. Repeatable.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def publish_cmd(plan_ids: tuple[str, ...], as_json: bool) -> None:
    """Publish a projection of a plan into the configured second brain.

    Exits 0 when no second brain is configured: "off" is a state the caller
    asked about, not a failure, and an agent protocol runs this unconditionally.
    """
    from studyloop.second_brain import get_backend
    from studyloop.second_brain.core import SecondBrainError

    backend = get_backend()
    if not plan_ids:
        _fail("Nothing selected. Name a plan: studyloop brain publish --plan <plan-id>")

    results = []
    try:
        for plan_id in plan_ids:
            results.append(backend.publish_plan(plan_id))
    except SecondBrainError as exc:
        _fail(str(exc))

    if as_json:
        click.echo(
            json.dumps(
                _publish_payload(backend.describe().provider, results, dry_run=False),
                indent=2,
            )
        )
        return
    _print_publish(results)


__all__ = ["brain_group"]
