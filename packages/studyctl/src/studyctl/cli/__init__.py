"""studyctl CLI — AuDHD study pipeline.

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
        # _setup.py — first-run setup wizard
        "setup": "studyctl.cli._setup:setup",
        # _config.py — configuration
        "config": "studyctl.cli._config:config_group",
        # _review.py — spaced repetition, progress, wins, streaks, bridges
        "review": "studyctl.cli._review:review",
        "struggles": "studyctl.cli._review:struggles",
        "wins": "studyctl.cli._review:wins",
        "progress": "studyctl.cli._review:progress",
        "resume": "studyctl.cli._review:resume",
        "streaks": "studyctl.cli._review:streaks",
        "bridge": "studyctl.cli._review:bridge_group",
        # _content.py — content pipeline (pdf splitting, NotebookLM, syllabus)
        "content": "studyctl.cli._content:content_group",
        # _web.py — web UI
        "web": "studyctl.cli._web:web",
        # _session.py — live study session management
        "session": "studyctl.cli._session:session_group",
        "park": "studyctl.cli._session:park",
        "topic": "studyctl.cli._session:topic_cmd",
        # _study.py — unified study session (tmux + agent + sidebar)
        "study": "studyctl.cli._study:study",
        "sidebar": "studyctl.cli._study:sidebar_cmd",
        # _clean.py — cleanup orphaned session artifacts
        "clean": "studyctl.cli._clean:clean",
        # _topics.py — study backlog management
        "backlog": "studyctl.cli._topics:topics_group",
        # _doctor.py — diagnostic health checks
        "doctor": "studyctl.cli._doctor:doctor",
        # _upgrade.py — update check + upgrade apply
        "update": "studyctl.cli._upgrade:update",
        "upgrade": "studyctl.cli._upgrade:upgrade",
        # _backup.py — backup and restore user data
        "backup": "studyctl.cli._backup:backup",
        "restore": "studyctl.cli._backup:restore",
    },
)
@click.version_option()
def cli() -> None:
    """studyctl — AuDHD study pipeline: content, review, and session tracking."""


__all__ = ["cli"]
