"""``studyloop brain`` — publish study plans into a second brain.

Every command has a ``--json`` form because an agent drives these
programmatically at wind-down, while the default output stays readable in a
terminal sidebar. Same convention as ``studyloop plan``.

Two rules shape the whole surface, both because an agent runs it unattended:

* **Nothing prompts.** A command that waits for input blocks a terminal nobody is
  watching. Where confirmation would be wanted, there is a flag instead
  (``--create``, ``--dry-run``).
* **"Off" is not an error.** ``publish`` and ``pull`` exit 0 when no provider is
  configured, so a wind-down protocol can run them unconditionally. Exit 1 is
  reserved for something the learner can fix, and the message names the fix.

Module-level imports are click, json and the shared console — nothing else.
:mod:`studyloop.second_brain` is imported inside each command body, which keeps
``studyloop --help`` cheap and makes the optionality contract provable with
``sys.modules`` (see ``tests/test_second_brain_optionality.py``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, NoReturn

import click

from studyloop.cli._shared import console

if TYPE_CHECKING:
    from studyloop.second_brain.core import PublishResult

#: Where the guide lives, quoted in messages rather than a URL: the repository
#: path is stable and works offline, which a versioned docs URL does not.
GUIDE = "docs/second-brain.md"


def _fail(message: str) -> NoReturn:
    """Print an error and exit non-zero, never a traceback.

    Same helper shape as ``cli/_plan.py``: every failure this maps is something
    the learner can act on, so a stack trace would only bury the fix.

    ``soft_wrap=True`` because these messages name a command to run. Rich's
    default wrapping breaks a long line mid-command, and a wrapped command cannot
    be copy-pasted -- which defeats the entire point of naming the fix.
    """
    console.print(f"[red]{message}[/red]", soft_wrap=True)
    raise SystemExit(1)


def _publish_payload(
    provider: str, results: list[PublishResult], *, dry_run: bool
) -> dict[str, object]:
    return {
        "provider": provider,
        "operations": [result.to_json_dict() for result in results],
        "dry_run": dry_run,
    }


def _emit(provider: str, results: list[PublishResult], *, dry_run: bool, as_json: bool) -> None:
    """Render one publish outcome, in whichever form was asked for."""
    if as_json:
        click.echo(json.dumps(_publish_payload(provider, results, dry_run=dry_run), indent=2))
        return
    _print_publish(results, dry_run=dry_run)


def _print_publish(results: list[PublishResult], *, dry_run: bool) -> None:
    """Human form: say what changed, what did not, and what was declined.

    "unchanged" is reported rather than hidden because republishing is the normal
    case — a learner who runs this at every wind-down should see that nothing was
    rewritten, not silence that reads as a failure.
    """
    verb = "would write" if dry_run else "written"
    # soft_wrap throughout: a wrapped vault-relative path is not a path the
    # learner can paste into a search box or a shell.
    for result in results:
        for path in result.written:
            console.print(f"[green]{verb}[/green]   {path}", soft_wrap=True)
        for path in result.unchanged:
            console.print(f"[dim]unchanged {path}[/dim]", soft_wrap=True)
        for reason in result.skipped:
            console.print(f"[dim]skipped[/dim]   {reason}", soft_wrap=True)
        for warning in result.warnings:
            console.print(f"[yellow]warning[/yellow]   {warning}", soft_wrap=True)


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

    payload = get_backend().describe().to_json_dict()
    if as_json:
        # click.echo, not console.print: Rich soft-wraps long lines, which turns a
        # vault path into a JSON parse error for whichever agent reads this.
        click.echo(json.dumps(payload, indent=2))
        return
    for key, value in payload.items():
        console.print(f"{key}: {value}", soft_wrap=True)


@brain_group.command("publish")
@click.option(
    "--plan",
    "plan_ids",
    multiple=True,
    metavar="ID",
    help="Publish this plan. Repeatable. Default: every active plan.",
)
@click.option("--all", "publish_all", is_flag=True, help="Publish every plan, any status.")
@click.option("--today", "today_only", is_flag=True, help="Publish only today's note.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Report the notes that would be written, and write nothing.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def publish_cmd(
    plan_ids: tuple[str, ...],
    publish_all: bool,
    today_only: bool,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Publish projections into the configured second brain.

    With no selector: today's note plus every plan whose status is ``active``. A
    wind-down flow should not have to enumerate plans, and a learner asking to
    publish almost never means a draft they abandoned.
    """
    from studyloop.second_brain import get_backend
    from studyloop.second_brain.core import SecondBrainError

    if plan_ids and today_only:
        _fail("--today publishes only today's note; drop --plan, or drop --today.")
    if publish_all and plan_ids:
        _fail("--all publishes every plan; drop --plan, or drop --all.")

    backend = get_backend()
    description = backend.describe()

    if not description.configured:
        # Deliberately exit 0 with a reason rather than failing: an unconfigured
        # feature is a state the caller asked about.
        results = [backend.publish_today()]
        _emit(description.provider, results, dry_run=dry_run, as_json=as_json)
        return

    if not description.supports_publish:
        # Exit 0, not 1. This is not something the learner can fix -- xTiles has no
        # programmatic backend by design -- and this module promises that a wind-down
        # protocol can run `publish` unconditionally. Failing here would break that
        # for every xTiles learner, at the end of every session.
        results = [backend.publish_today()]
        _emit(description.provider, results, dry_run=dry_run, as_json=as_json)
        return

    try:
        selected = _selected_plan_ids(plan_ids, publish_all=publish_all, today_only=today_only)
        if dry_run:
            results = _dry_run_results(backend, selected, today=not plan_ids or today_only)
        else:
            results = _publish(backend, selected, today=not plan_ids or today_only)
    except SecondBrainError as exc:
        _fail(str(exc))

    _emit(description.provider, results, dry_run=dry_run, as_json=as_json)


def _selected_plan_ids(
    plan_ids: tuple[str, ...], *, publish_all: bool, today_only: bool
) -> list[str]:
    if today_only:
        return []
    if plan_ids:
        return list(plan_ids)
    from studyloop.planning import list_plans

    if publish_all:
        return [plan.plan_id for plan in list_plans()]
    return [plan.plan_id for plan in list_plans(status="active")]


def _publish(backend, plan_ids: list[str], *, today: bool) -> list[PublishResult]:
    results: list[PublishResult] = []
    if today:
        results.append(backend.publish_today())
    results.extend(backend.publish_plan(plan_id) for plan_id in plan_ids)
    return results


def _dry_run_results(backend, plan_ids: list[str], *, today: bool) -> list[PublishResult]:
    """Report what a publish WOULD do, without doing it.

    Classified through the SAME ownership and byte-equality checks a real publish
    uses, so `--dry-run` reports `unchanged` for a note that is already current and
    refuses one the learner owns. Reporting every target as "would write" was
    misleading in both directions: it promised writes that would be refused, and
    churn that would not happen.
    """
    return [
        *([backend.plan_dry_run(None)] if today else []),
        *(backend.plan_dry_run(plan_id) for plan_id in plan_ids),
    ]


@brain_group.command("pull")
@click.argument("plan_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def pull_cmd(plan_id: str, as_json: bool) -> None:
    """Print your own notes for a plan. Never writes anything.

    The sibling note is your half of the conversation: StudyLoop owns the
    projection and regenerates it, so your own thinking needs a file it never
    touches. Exits 0 when there is nothing there yet — that is a normal state.
    """
    from studyloop.second_brain import get_backend
    from studyloop.second_brain.core import SecondBrainError

    backend = get_backend()
    try:
        result = backend.pull_notes(plan_id)
    except SecondBrainError as exc:
        _fail(str(exc))

    if as_json:
        click.echo(json.dumps(result.to_json_dict(), indent=2))
        return
    if not result.found:
        for warning in result.warnings:
            console.print(f"[dim]{warning}[/dim]")
        return
    for source in result.sources:
        console.print(f"[dim]{source}[/dim]")
    click.echo(result.notes)


@brain_group.command("enable")
@click.argument("provider", type=click.Choice(["obsidian", "xtiles", "none"]))
@click.option("--vault", "vault", metavar="PATH", help="Vault path (Obsidian).")
@click.option("--folder", "folder", metavar="NAME", help="Folder inside the vault.")
@click.option("--create", is_flag=True, help="Create the vault folder if it is missing.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def enable_cmd(
    provider: str,
    vault: str | None,
    folder: str | None,
    create: bool,
    as_json: bool,
) -> None:
    """Write the ``second_brain`` section into your config.

    Read-modify-write: every other key in the file survives, and so do
    ``second_brain`` sub-keys this command was not asked to change — changing the
    vault must not silently reset a learner's other choices.
    """
    from pathlib import Path

    from studyloop.settings import (
        ConfigError,
        load_raw_config,
        resolve_second_brain,
        write_raw_config,
    )

    raw = load_raw_config()
    section = dict(raw.get("second_brain") or {})
    section["provider"] = provider

    if provider == "obsidian":
        if vault is not None:
            resolved = Path(vault).expanduser()
            if not resolved.is_dir():
                if not create:
                    _fail(
                        f"Vault path does not exist: {resolved}. "
                        "Create it first, or rerun with --create."
                    )
                resolved.mkdir(parents=True, exist_ok=True)
            section["vault_path"] = str(resolved)
        if folder is not None:
            section["folder"] = folder

    raw["second_brain"] = section

    # Validate BEFORE writing. Writing first and checking afterwards left the learner
    # with a broken config file they never edited and no way back -- the check could
    # only report the damage, not prevent it.
    try:
        resolved = resolve_second_brain(raw)
    except ConfigError as exc:
        _fail(f"That would not be a valid configuration, so nothing was written: {exc}")

    if (
        provider == "obsidian"
        and vault is None
        and not raw.get("second_brain", {}).get("vault_path")
    ):
        # A guessed vault is worse than no vault. Without an explicit path the
        # resolution chain bottoms out at a hard-coded ~/Obsidian/Personal, which may
        # be a real vault the learner uses for something else -- and this command's
        # whole job is to record a deliberate choice.
        _fail(
            "No vault is configured, and StudyLoop will not guess one. "
            "Run: studyloop brain enable obsidian --vault <path>"
        )

    path = write_raw_config(raw)

    if as_json:
        click.echo(json.dumps({"config_path": str(path), "second_brain": section}, indent=2))
        return

    console.print(f"Wrote second_brain to {path}", soft_wrap=True)
    if provider == "obsidian":
        # Print the resolved path. A learner who omitted --vault because an older key
        # already named one should be able to see WHICH directory they just authorised.
        console.print(f"Vault: {resolved.vault_path}", soft_wrap=True)
    if provider == "xtiles":
        console.print(
            "xTiles has no programmatic backend: StudyLoop ships prompts and an "
            f"opt-in assistant skill instead. See {GUIDE}.",
            soft_wrap=True,
        )
    elif provider == "obsidian":
        console.print("Publish with: studyloop brain publish")


@brain_group.command("template")
@click.option("--print", "print_name", metavar="NAME", help="Print one template verbatim.")
@click.option("--install", "install", is_flag=True, help="Copy the templates into your vault.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def template_cmd(print_name: str | None, install: bool, as_json: bool) -> None:
    """List, print, or install the Obsidian note templates.

    A note you create from a template is yours: the templates carry no ownership
    marker, so StudyLoop never regenerates anything made from one.
    """
    from studyloop.second_brain.core import SecondBrainError
    from studyloop.second_brain.templates import install_templates, list_templates, read_template

    if print_name and install:
        _fail("Use either --print or --install, not both.")

    if print_name:
        try:
            body = read_template(print_name)
        except SecondBrainError as exc:
            _fail(str(exc))
        # click.echo with nl=False: the template's bytes must come out exactly as
        # packaged, so `--print > file` produces the file itself.
        click.echo(body, nl=False)
        return

    if install:
        from studyloop.settings import load_settings

        config = load_settings().second_brain
        if config.provider != "obsidian":
            _fail(
                "No Obsidian vault is configured, so there is nowhere to install to. "
                "Run: studyloop brain enable obsidian --vault <path>"
            )
        try:
            installed = install_templates(config.vault_path)
        except SecondBrainError as exc:
            _fail(str(exc))
        if as_json:
            click.echo(json.dumps({"installed": installed}, indent=2))
            return
        for path in installed:
            console.print(f"[green]written[/green]   {path}", soft_wrap=True)
        return

    names = list_templates()
    if as_json:
        click.echo(json.dumps({"templates": names}, indent=2))
        return
    for name in names:
        console.print(name)


__all__ = ["brain_group"]
