"""Centralized configuration loader for studyctl.

Loads from ~/.config/studyctl/config.yaml with sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_CONFIG_PATH = Path(
    os.environ.get("STUDYCTL_CONFIG", Path.home() / ".config" / "studyctl" / "config.yaml")
)


def _get_username() -> str:
    """Get current username safely (works in cron, CI, and non-interactive environments)."""
    try:
        return os.getlogin()
    except OSError:
        import getpass

        return getpass.getuser()


@dataclass
class TopicConfig:
    """Configuration for a single study topic."""

    name: str
    slug: str
    obsidian_path: Path
    notebook_id: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class Settings:
    """Application settings loaded from config file."""

    obsidian_base: Path = field(default_factory=lambda: Path.home() / "Obsidian")
    session_db: Path = field(
        default_factory=lambda: Path.home() / ".config" / "studyctl" / "sessions.db"
    )
    state_dir: Path = field(default_factory=lambda: Path.home() / ".local" / "share" / "studyctl")
    topics: list[TopicConfig] = field(default_factory=list)
    sync_remote: str = ""
    sync_user: str = field(default_factory=lambda: _get_username())


def load_settings() -> Settings:
    """Load settings from config file, falling back to defaults."""
    settings = Settings()
    if not _CONFIG_PATH.exists():
        return settings

    with open(_CONFIG_PATH) as f:
        raw = yaml.safe_load(f) or {}

    if "obsidian_base" in raw:
        settings.obsidian_base = Path(raw["obsidian_base"]).expanduser()
    if "session_db" in raw:
        settings.session_db = Path(raw["session_db"]).expanduser()
    if "state_dir" in raw:
        settings.state_dir = Path(raw["state_dir"]).expanduser()
    if "sync_remote" in raw:
        settings.sync_remote = raw["sync_remote"]
    if "sync_user" in raw:
        settings.sync_user = raw["sync_user"]

    for t in raw.get("topics", []):
        obsidian_path = Path(t.get("obsidian_path", "")).expanduser()
        if not obsidian_path.is_absolute():
            obsidian_path = settings.obsidian_base / t.get("obsidian_path", "")
        settings.topics.append(
            TopicConfig(
                name=t["name"],
                slug=t["slug"],
                obsidian_path=obsidian_path,
                notebook_id=t.get("notebook_id", ""),
                tags=t.get("tags", []),
            )
        )

    return settings


def generate_default_config() -> str:
    """Generate a default config YAML with comments."""
    return """\
# studyctl configuration
# Location: ~/.config/studyctl/config.yaml

# Base path to your Obsidian vault
obsidian_base: ~/Obsidian

# Path to the AI session database
session_db: ~/.config/studyctl/sessions.db

# State directory for sync tracking
state_dir: ~/.local/share/studyctl

# Remote sync configuration (optional)
# sync_remote: your-remote-host
# sync_user: your-username

# Study topics
# Each topic maps to an Obsidian directory and optionally a NotebookLM notebook
topics:
  - name: Python
    slug: python
    obsidian_path: 2-Areas/Study/Python
    # notebook_id: your-notebooklm-notebook-id
    tags: [python, programming]

  - name: SQL
    slug: sql
    obsidian_path: 2-Areas/Study/SQL
    tags: [sql, databases]

  - name: Data Engineering
    slug: data-engineering
    obsidian_path: 2-Areas/Study/Data-Engineering
    tags: [data-engineering, spark, glue]

  - name: AWS Analytics
    slug: aws-analytics
    obsidian_path: 2-Areas/Study/AWS-Analytics
    tags: [aws, analytics, redshift, athena]

# Medication timing (optional — for ADHD stimulant medication awareness)
# Uncomment to enable medication-aware session recommendations
# medication:
#   dose_time: "08:00"        # When you take your medication (24h format)
#   onset_minutes: 30         # Minutes until meds kick in
#   peak_hours: 4             # Hours of peak effectiveness
#   duration_hours: 8         # Total duration before wearing off
"""
