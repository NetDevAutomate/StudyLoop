"""studyloop CLI — AuDHD study pipeline.

Split into submodules with LazyGroup for fast startup.
Commands are only imported when invoked.
"""

from __future__ import annotations

import click

from studyloop.cli._lazy import LazyGroup


@click.group(
    cls=LazyGroup,
    lazy_subcommands={
        # _sync.py — Obsidian/NotebookLM sync
        "sync": "studyloop.cli._sync:sync",
        "status": "studyloop.cli._sync:status",
        "audio": "studyloop.cli._sync:audio",
        "topics": "studyloop.cli._sync:topics",
        "dedup": "studyloop.cli._sync:dedup",
        # _setup.py — first-run setup wizard
        "setup": "studyloop.cli._setup:setup",
        # _install.py — typed installation helpers
        "install": "studyloop.cli._install:install_group",
        # _config.py — configuration
        "config": "studyloop.cli._config:config_group",
        # _review.py — spaced repetition, progress, wins, streaks, bridges
        "review": "studyloop.cli._review:review",
        "struggles": "studyloop.cli._review:struggles",
        "wins": "studyloop.cli._review:wins",
        "progress": "studyloop.cli._review:progress",
        "resume": "studyloop.cli._review:resume",
        "streaks": "studyloop.cli._review:streaks",
        "bridge": "studyloop.cli._review:bridge_group",
        # _content.py — content pipeline (pdf splitting, NotebookLM, syllabus)
        "content": "studyloop.cli._content:content_group",
        # _web.py — web UI
        "web": "studyloop.cli._web:web",
        # _session.py — live study session management
        "session": "studyloop.cli._session:session_group",
        "park": "studyloop.cli._session:park",
        "topic": "studyloop.cli._session:topic_cmd",
        # _study.py — unified study session (tmux + agent + sidebar)
        "study": "studyloop.cli._study:study",
        "sidebar": "studyloop.cli._study:sidebar_cmd",
        # _clean.py — cleanup orphaned session artifacts
        "clean": "studyloop.cli._clean:clean",
        # _topics.py — study backlog management
        "backlog": "studyloop.cli._topics:topics_group",
        # _doctor.py — diagnostic health checks
        "doctor": "studyloop.cli._doctor:doctor",
        # _upgrade.py — update check + upgrade apply
        "update": "studyloop.cli._upgrade:update",
        "upgrade": "studyloop.cli._upgrade:upgrade",
        # _backup.py — backup and restore user data
        "backup": "studyloop.cli._backup:backup",
        "restore": "studyloop.cli._backup:restore",
    },
)
@click.version_option()
def cli() -> None:
    """studyloop — AuDHD study pipeline: content, review, and session tracking."""


__all__ = ["cli"]
