"""studyloop doctor — diagnostic health check command."""

from __future__ import annotations

import contextlib
import json

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.doctor.models import VALID_CATEGORIES, CheckResult
from studyloop.installers import (
    InstallError,
    ensure_default_config,
    ensure_review_database,
    ensure_review_directories,
    install_agent_definitions,
    install_workspace_tools,
    require_repo_root,
)


def check_unknown_config_keys() -> list[CheckResult]:
    """Warn about top-level config.yaml keys no consumer reads any more.

    R-34: an unknown or retired key (e.g. ``ttyd_port``, dropped in the ttyd
    retirement) silently does nothing today — ``load_settings()`` only ever
    reads the keys it looks for, so a stale key from an old config is neither
    applied nor reported. This is the report; the fix (deleting the key) is
    the user's. Lives here rather than in ``doctor/config.py`` (owned by a
    different remediation lane, m5, in the same window this was added) —
    the registry below wires it into the same "config" category regardless
    of which module defines it.
    """
    try:
        from studyloop.settings import unknown_top_level_keys

        unknown = unknown_top_level_keys()
    except Exception:
        return []

    if not unknown:
        return []

    keys = ", ".join(unknown)
    return [
        CheckResult(
            "config",
            "unknown_config_keys",
            "warn",
            f"Unknown or retired config.yaml key(s): {keys}. StudyLoop no longer "
            "reads them; they are silently inert.",
            f"Remove {keys} from ~/.config/studyloop/config.yaml.",
            False,
        )
    ]


def _get_registry():
    """Build and return a fully-loaded CheckerRegistry."""
    from studyloop.doctor import CheckerRegistry
    from studyloop.doctor.agents import (
        check_agent_definitions,
        check_agent_smoke_tests,
    )
    from studyloop.doctor.config import (
        check_active_topic_limit,
        check_obsidian_export,
        check_obsidian_vault,
        check_pandoc,
        check_review_directories,
    )
    from studyloop.doctor.core import (
        check_agent_session_tools,
        check_config_file,
        check_python_version,
        check_studyloop_installed,
    )
    from studyloop.doctor.database import check_review_db, check_sessions_db
    from studyloop.doctor.deps import check_optional_deps
    from studyloop.doctor.harness import check_harness_export
    from studyloop.doctor.voice import check_voice_readiness

    registry = CheckerRegistry()
    for fn in [
        check_python_version,
        check_studyloop_installed,
        check_agent_session_tools,
        check_config_file,
    ]:
        registry.register("core")(fn)
    for fn in [check_review_db, check_sessions_db]:
        registry.register("database")(fn)
    config_checks = [
        check_active_topic_limit,
        check_review_directories,
        check_pandoc,
        check_unknown_config_keys,
    ]
    # Obsidian is an OPT-IN integration, so its checks are registered only when
    # the config actually mentions it. A user who never had Obsidian should not
    # see two rows about software they do not own -- the setup wizard no longer
    # asks about it, so reporting on it would be reporting on nothing.
    from studyloop.settings import load_raw_config

    with contextlib.suppress(Exception):
        raw = load_raw_config()
        if raw.get("obsidian") or raw.get("obsidian_base"):
            config_checks.insert(0, check_obsidian_vault)
            config_checks.insert(1, check_obsidian_export)
    for fn in config_checks:
        registry.register("config")(fn)
    registry.register("deps")(check_optional_deps)
    # check_system_binaries (bin_ttyd) is gone: ADR-0005 retired the ttyd
    # browser surface, so reporting ttyd's absence is noise with no signal.
    registry.register("agents")(check_agent_definitions)
    registry.register("agents")(check_agent_smoke_tests)
    registry.register("harness")(check_harness_export)
    # check_pypi_versions is deliberately NOT registered. Nothing is published
    # yet, so it can only ever report "no release found", which is noise on
    # every run. The module is retained for when a release exists.
    registry.register("voice")(check_voice_readiness)
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
        summary += f" Run 'studyloop doctor --fix' to fix {auto_fixable} issues."
    return summary


def _apply_fixes(results: list[CheckResult]) -> list[str]:
    """Apply safe automatic fixes for the provided results."""
    actions: list[str] = []

    def needs(category: str, name: str | None = None) -> bool:
        return any(
            r.category == category
            and (name is None or r.name == name)
            and r.status in ("warn", "fail")
            and r.fix_auto
            for r in results
        )

    if needs("core", "config_file"):
        path = ensure_default_config()
        actions.append(f"created config: {path}")

    if needs("core", "agent_session_tools"):
        repo_root = require_repo_root()
        install_workspace_tools(repo_root, sync_workspace=True, force=True)
        actions.append("reinstalled workspace tools")

    if any(
        r.category == "config"
        and r.name.startswith("review_dir_")
        and r.status in ("warn", "fail")
        and r.fix_auto
        for r in results
    ):
        created = ensure_review_directories()
        actions.append(f"ensured review directories ({len(created)} created)")

    if needs("database", "review_db"):
        db_path = ensure_review_database()
        actions.append(f"migrated review DB: {db_path}")

    if needs("database", "sessions_fts"):
        # Call the library directly rather than shelling out to
        # `session-maint fts-check --fix`. Shelling out is what left the remedy
        # printed but unexecuted, and it would depend on that console script
        # being on PATH inside whatever environment doctor happens to run in.
        import sqlite3

        from agent_session_tools.tiering import repair_fts
        from studyloop.doctor.database import _get_sessions_db_path

        with sqlite3.connect(_get_sessions_db_path()) as conn:
            integrity = repair_fts(conn)
        actions.append(
            f"repaired FTS index: {integrity.fts_rows:,} rows for "
            f"{integrity.messages_with_content:,} messages"
        )

    if any(r.category == "agents" and r.status in ("warn", "fail") and r.fix_auto for r in results):
        repo_root = require_repo_root()
        summary = install_agent_definitions(repo_root)
        changed = sum(summary.values())
        actions.append(f"refreshed agent definitions ({changed} changes)")

    if needs("harness"):
        # The session-export steering mandate + Claude Stop hook are deployed
        # by install_agent_definitions (mandate + hook merge). Run it directly
        # so the harness fix works even when the agents category is clean.
        from studyloop.installers import install_claude_stop_hook, install_session_db_mandate

        repo_root = require_repo_root()
        mandate = sum(install_session_db_mandate(repo_root).values())
        hook = install_claude_stop_hook()
        actions.append(f"wired session-export ({mandate} steering mandate(s), {hook} Claude hook)")

    if any(
        r.category == "updates" and r.status in ("warn", "fail") and r.fix_auto for r in results
    ):
        from studyloop.cli._upgrade import _detect_package_manager, _upgrade_packages

        manager = _detect_package_manager()
        if not _upgrade_packages(manager, dry_run=False):
            msg = "package upgrade failed"
            raise InstallError(msg)
        actions.append(f"upgraded packages via {manager}")

    return actions


@click.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array")
@click.option("--quiet", is_flag=True, help="Summary line only")
@click.option("--fix", is_flag=True, help="Apply safe automatic fixes before reporting.")
@click.option(
    "--category",
    type=click.Choice(sorted(VALID_CATEGORIES)),
    default=None,
    help="Check specific category",
)
@click.pass_context
def doctor(
    ctx: click.Context,
    as_json: bool,
    quiet: bool,
    fix: bool,
    category: str | None,
) -> None:
    """Check installation health and report issues."""
    registry = _get_registry()

    results = registry.run_category(category) if category else registry.run_all()
    applied: list[str] = []
    if fix:
        try:
            applied = _apply_fixes(results)
        except (InstallError, click.ClickException) as exc:
            raise click.ClickException(str(exc)) from exc
        if applied:
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
    if applied:
        console.print("[bold green]Applied fixes:[/bold green]")
        for action in applied:
            console.print(f"  {action}")
        console.print()

    table = Table(title="studyloop doctor", show_lines=False)
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
