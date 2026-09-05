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
        # _now.py — shared learning-decision engine
        "now": "studyloop.cli._now:now",
        # _chat_note.py — Socratic note companion context packs
        "chat-note": "studyloop.cli._chat_note:chat_note",
        # _setup.py — first-run setup wizard
        "setup": "studyloop.cli._setup:setup",
        # _install.py — typed installation helpers
        "install": "studyloop.cli._install:install_group",
        # _config.py — configuration
        "config": "studyloop.cli._config:config_group",
        # _review.py — spaced repetition, progress, wins, streaks, bridges
        "review": "studyloop.cli._review:review",
        "struggles": "studyloop.cli._review:struggles",
        # _extract.py — struggle-extraction pipeline (sessions.db -> study_progress)
        "extract-struggles": "studyloop.cli._extract:extract_struggles_cmd",
        "wins": "studyloop.cli._review:wins",
        "progress": "studyloop.cli._review:progress",
        "resume": "studyloop.cli._review:resume",
        "streaks": "studyloop.cli._review:streaks",
        "bridge": "studyloop.cli._review:bridge_group",
        "recap": "studyloop.cli._recap:recap_group",
        "mastery": "studyloop.cli._mastery:mastery_group",
        # _teachback.py — teach-back assessment scoring
        "teachback": "studyloop.cli._teachback:teachback",
        "teachback-history": "studyloop.cli._teachback:teachback_history",
        # _content.py — content pipeline (pdf splitting, NotebookLM, syllabus)
        "content": "studyloop.cli._content:content_group",
        "practice": "studyloop.cli._practice:practice_group",
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
        "self-test": "studyloop.cli._self_test:self_test",
        # _upgrade.py — update check + upgrade apply
        "update": "studyloop.cli._upgrade:update",
        "upgrade": "studyloop.cli._upgrade:upgrade",
        # _backup.py — backup and restore user data
        "backup": "studyloop.cli._backup:backup",
        "restore": "studyloop.cli._backup:restore",
        # _focus.py — focus topics (attention filter) + hot-DB pruning
        "focus": "studyloop.cli._focus:focus_group",
        "prune": "studyloop.cli._focus:prune",
        # _plan.py — structured study plans
        "plan": "studyloop.cli._plan:plan_group",
        # _brain.py — optional second-brain projections (Obsidian, xTiles)
        "brain": "studyloop.cli._brain:brain_group",
        # _exercise.py — the three topic exercise formats and their review pipeline
        "exercise": "studyloop.cli._exercise:exercise_group",
    },
    dev_subcommands={"exercise"},
)
@click.option(
    "--dev",
    is_flag=True,
    help="Expose experimental developer-only commands.",
)
@click.version_option()
def cli(dev: bool) -> None:
    """studyloop — AuDHD study pipeline: content, review, and session tracking."""
    # `dev` is consumed by LazyGroup during help/command resolution. Keeping
    # the value in the callback signature makes Click expose it as a real,
    # documented gate rather than an environment-variable backdoor.
    del dev


__all__ = ["cli"]
