"""``studyloop module`` -- optional-module lifecycle: check, new, add, list, remove.

Module-contract v1 (proposal §7), lane C. :data:`module_group` is a Click group that is
**exported, not registered**: lane W adds the one ``"module": "studyloop.cli._module:module_group"``
line to ``cli/__init__.py`` at assembly. Tests drive the group object directly with
``click.testing.CliRunner``.

Every command here reads module content as data. Nothing a module ships is imported or run:
``check`` is static, ``new`` writes files, and ``add``/``list``/``remove`` operate on the
snapshot store and ``modules.lock.json`` only (see ``studyloop.modules.store``).

Exit codes: ``check`` exits 0 when the module conforms, 1 on any finding, 2 when the path is
not a directory; ``add`` exits 1 when the module fails ``check`` (nothing is written).
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from studyloop.modules.check import CheckReport, check_module
from studyloop.modules.scaffold import ScaffoldError, scaffold_module
from studyloop.modules.store import ModuleCheckError, ModuleStore, StoreError


@click.group("module")
def module_group() -> None:
    """Optional learning modules: check conformance, scaffold, install, list, remove.

    A module is a directory of data (module.yaml, decks/*.json, scripts/, mentor/brief.md)
    that StudyLoop validates against contract rules MC001-MC016 and never imports or
    executes. Install from a local path only; StudyLoop makes no network access here.
    """


def _print_report(report: CheckReport, module_path: Path, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2))
        return
    # click.echo, not the rich console: a finding line is grep material for CI and a path
    # must not be wrapped at 80 columns when stdout is a pipe.
    if report.ok:
        click.echo(f"{click.style('ok', fg='green')} {module_path}: conforms to module contract v1")
        return
    for finding in report.findings:
        where = finding.path or "."
        if finding.line is not None:
            where = f"{where}:{finding.line}"
        click.echo(f"{click.style(finding.rule_id, fg='red')} {where}: {finding.message}")
    plural = "finding" if len(report.findings) == 1 else "findings"
    click.echo(click.style(f"{len(report.findings)} {plural} in {module_path}", fg="red"))


@module_group.command("check")
@click.argument("path", type=click.Path(path_type=Path))
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit {ok, findings[{rule_id,message,path,line}]} for CI.",
)
def module_check(path: Path, as_json: bool) -> None:
    """Check the module at PATH against conformance rules MC001-MC016.

    Reports each failure with its rule id, file and line (line is null for a file-level
    fault such as a missing file). Exit 0 when the module conforms, 1 on any finding,
    2 when PATH is not a directory. Nothing in the module is executed.
    """
    if not path.is_dir():
        raise click.UsageError(f"{path} is not a directory")
    report = check_module(path)
    _print_report(report, path, as_json)
    if not report.ok:
        raise SystemExit(1)


@module_group.command("new")
@click.argument("module_id")
@click.option(
    "--dir",
    "parent",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Parent directory for the new module (default: the current directory).",
)
@click.option("--title", default=None, help="Module title (default: derived from MODULE_ID).")
@click.option(
    "--topic", default="shell", show_default=True, help="One tech area, as topics use it."
)
@click.option("--author", default="Module author", show_default=True, help="Maintainer name.")
def module_new(
    module_id: str, parent: Path | None, title: str | None, topic: str, author: str
) -> None:
    """Scaffold a new module MODULE_ID that passes `studyloop module check`.

    Writes module.yaml, one deck with an offline echo-based drill (scripts/check.sh
    exits 0 with no network, Docker or kind), mentor/brief.md, README.md with the four
    required sections, LICENSE, CHANGELOG.md and tests/check.sh into ./MODULE_ID (or
    --dir/MODULE_ID). The destination must not exist or must be empty.
    """
    destination = (parent or Path.cwd()) / module_id
    try:
        scaffold_module(destination, module_id, title=title, topic=topic, author=author)
    except ScaffoldError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{click.style('created', fg='green')} {destination}")
    click.echo(f"next: studyloop module check {destination}")


@module_group.command("add")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Print the lockfile entry as JSON.")
def module_add(path: Path, as_json: bool) -> None:
    """Install the module at PATH from a local directory into an immutable snapshot.

    Runs `studyloop module check PATH` first and refuses on any finding: nothing is
    written and modules.lock.json is left exactly as it was (exit 1). On success the
    module is copied into StudyLoop's config directory under modules/snapshots/<digest>
    (files read-only) and recorded in modules.lock.json with its id, version, content
    digest and -- when PATH is inside a git checkout -- the origin URL and HEAD sha, read
    locally with no fetch. No network access occurs. Re-adding an id replaces its entry.
    """
    if not path.is_dir():
        raise click.UsageError(f"{path} is not a directory")
    store = ModuleStore()
    try:
        entry = store.add(path)
    except ModuleCheckError as exc:
        _print_report(exc.report, path, as_json)
        if not as_json:
            click.echo(
                click.style("not installed: fix the findings and run module add again", fg="red")
            )
        raise SystemExit(1) from exc
    except StoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(entry.to_dict(), indent=2))
        return
    click.echo(
        f"{click.style('installed', fg='green')} {entry.id} {entry.version} ({entry.digest})"
    )
    click.echo(f"snapshot: {entry.snapshot}")
    if entry.git_sha:
        click.echo(f"git: {entry.git_remote or '(no remote)'} @ {entry.git_sha}")
    click.echo(f"lockfile: {store.lockfile}")


@module_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print the lockfile entries as a JSON list.")
def module_list(as_json: bool) -> None:
    """List installed modules from modules.lock.json (the lockfile is the only source)."""
    store = ModuleStore()
    try:
        entries = store.entries()
    except StoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps([entry.to_dict() for entry in entries], indent=2))
        return
    if not entries:
        click.echo("no modules installed (studyloop module add <path> installs one)")
        return
    width = max(len(entry.id) for entry in entries)
    for entry in entries:
        digest = entry.digest.removeprefix("sha256:")[:12]
        click.echo(f"{entry.id:<{width}}  {entry.version:<10} {digest}  {entry.snapshot}")


@module_group.command("remove")
@click.argument("module_id")
def module_remove(module_id: str) -> None:
    """Remove MODULE_ID from modules.lock.json and delete its snapshot.

    Idempotent: removing an id that is not installed is not an error (exit 0) and
    leaves the lockfile untouched.
    """
    store = ModuleStore()
    try:
        removed = store.remove(module_id)
    except StoreError as exc:
        raise click.ClickException(str(exc)) from exc
    if removed:
        click.echo(f"{click.style('removed', fg='green')} {module_id}")
    else:
        click.echo(f"{module_id} is not installed; nothing to remove")
