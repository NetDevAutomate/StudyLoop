"""studyctl doctor — diagnostic health check command."""

from __future__ import annotations

import json

import click
from rich.table import Table

from studyctl.cli._shared import console
from studyctl.doctor.models import VALID_CATEGORIES, CheckResult


def _get_registry():
    """Build and return a fully-loaded CheckerRegistry."""
    from studyctl.doctor import CheckerRegistry
    from studyctl.doctor.agents import (
        check_agent_definitions,
        check_agent_smoke_tests,
        check_local_llm_servers,
    )
    from studyctl.doctor.config import (
        check_obsidian_vault,
        check_pandoc,
        check_review_directories,
        check_tmux_resurrect,
    )
    from studyctl.doctor.core import (
        check_agent_session_tools,
        check_config_file,
        check_python_version,
        check_studyctl_installed,
    )
    from studyctl.doctor.database import check_review_db, check_sessions_db
    from studyctl.doctor.deps import check_optional_deps
    from studyctl.doctor.updates import check_pypi_versions

    registry = CheckerRegistry()
    for fn in [
        check_python_version,
        check_studyctl_installed,
        check_agent_session_tools,
        check_config_file,
    ]:
        registry.register("core")(fn)
    for fn in [check_review_db, check_sessions_db]:
        registry.register("database")(fn)
    for fn in [check_obsidian_vault, check_review_directories, check_pandoc, check_tmux_resurrect]:
        registry.register("config")(fn)
    registry.register("deps")(check_optional_deps)
    registry.register("agents")(check_agent_definitions)
    registry.register("agents")(check_agent_smoke_tests)
    registry.register("agents")(check_local_llm_servers)
    registry.register("updates")(check_pypi_versions)
    return registry


STATUS_ICONS = {
    "pass": "[green]\u2713[/green]",
    "warn": "[yellow]![/yellow]",
    "fail": "[red]\u2717[/red]",
    "info": "[blue]i[/blue]",
}


def _compute_exit_code(results: list[CheckResult]) -> int:
    # Core failures that cannot be auto-fixed are critical (exit 2)
    has_critical_core_fail = any(
        r.category == "core" and r.status == "fail" and not r.fix_auto for r in results
    )
    if has_critical_core_fail:
        return 2
    has_fail = any(r.status == "fail" for r in results)
    has_auto_warn = any(r.status == "warn" and r.fix_auto for r in results)
    if has_fail or has_auto_warn:
        return 1
    return 0


def _summary_line(results: list[CheckResult]) -> str:
    counts: dict[str, int] = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for r in results:
        counts[r.status] += 1
    auto_fixable = sum(1 for r in results if r.fix_auto and r.status in ("warn", "fail"))
    parts = []
    if counts["pass"]:
        parts.append(f"{counts['pass']} passed")
    if counts["warn"]:
        parts.append(f"{counts['warn']} warnings")
    if counts["fail"]:
        parts.append(f"{counts['fail']} failures")
    if counts["info"]:
        parts.append(f"{counts['info']} info")
    summary = ", ".join(parts) + "."
    if auto_fixable:
        summary += f" Run 'studyctl upgrade' to fix {auto_fixable} issues."
    return summary


@click.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array")
@click.option("--quiet", is_flag=True, help="Summary line only")
@click.option(
    "--category",
    type=click.Choice(sorted(VALID_CATEGORIES)),
    default=None,
    help="Check specific category",
)
@click.pass_context
def doctor(ctx: click.Context, as_json: bool, quiet: bool, category: str | None) -> None:
    """Check installation health and report issues."""
    registry = _get_registry()

    results = registry.run_category(category) if category else registry.run_all()

    exit_code = _compute_exit_code(results)

    if as_json:
        click.echo(json.dumps([r.to_dict() for r in results], indent=2))
        ctx.exit(exit_code)
        return

    if quiet:
        click.echo(_summary_line(results))
        ctx.exit(exit_code)
        return

    # Rich table output grouped by category
    table = Table(title="studyctl doctor", show_lines=False)
    table.add_column("Status", justify="center", width=3)
    table.add_column("Check", style="cyan")
    table.add_column("Details")
    table.add_column("Fix", style="dim")

    current_category = None
    for r in results:
        if r.category != current_category:
            if current_category is not None:
                table.add_section()
            current_category = r.category
        icon = STATUS_ICONS.get(r.status, "?")
        fix_col = r.fix_hint if r.fix_hint else ""
        table.add_row(icon, f"[bold]{r.category}[/bold]/{r.name}", r.message, fix_col)

    console.print(table)
    console.print(f"\n{_summary_line(results)}")
    ctx.exit(exit_code)
