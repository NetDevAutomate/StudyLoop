"""studyctl CLI — sync, plan, and schedule study sessions.

Split into submodules with LazyGroup for fast startup.
Commands are only imported when invoked.
"""

from __future__ import annotations

import click

from studyctl.cli._lazy import LazyGroup


@click.group(
    cls=LazyGroup,
    lazy_subcommands={
        # _sync.py — Obsidian/NotebookLM sync
        "sync": "studyctl.cli._sync:sync",
        "status": "studyctl.cli._sync:status",
        "audio": "studyctl.cli._sync:audio",
        "topics": "studyctl.cli._sync:topics",
        "dedup": "studyctl.cli._sync:dedup",
        # _state.py — cross-machine state
        "state": "studyctl.cli._state:state_group",
        # _config.py — configuration
        "config": "studyctl.cli._config:config_group",
        # _schedule.py — job scheduling + calendar
        "schedule": "studyctl.cli._schedule:schedule_group",
        "schedule-blocks": "studyctl.cli._schedule:schedule_blocks",
        # _review.py — spaced repetition, progress, teachback, bridges
        "review": "studyctl.cli._review:review",
        "struggles": "studyctl.cli._review:struggles",
        "wins": "studyctl.cli._review:wins",
        "progress": "studyctl.cli._review:progress",
        "resume": "studyctl.cli._review:resume",
        "streaks": "studyctl.cli._review:streaks",
        "progress-map": "studyctl.cli._review:progress_map",
        "teachback": "studyctl.cli._review:teachback",
        "teachback-history": "studyctl.cli._review:teachback_history_cmd",
        "bridge": "studyctl.cli._review:bridge_group",
        # _web.py — web UI, TUI, docs
        "web": "studyctl.cli._web:web",
        "tui": "studyctl.cli._web:tui",
        "docs": "studyctl.cli._web:docs_group",
    },
)
@click.version_option()
def cli() -> None:
    """studyctl — AuDHD study pipeline: Obsidian\u2192NotebookLM sync and study management."""


__all__ = ["cli"]
