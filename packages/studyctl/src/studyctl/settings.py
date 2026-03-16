"""Centralized configuration loader for studyctl.

Loads from ~/.config/studyctl/config.yaml with sensible defaults.
All configuration types, topic mapping, and path resolution live here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".config" / "studyctl"
DEFAULT_DB = CONFIG_DIR / "sessions.db"

_CONFIG_PATH = Path(os.environ.get("STUDYCTL_CONFIG", CONFIG_DIR / "config.yaml"))

# File extensions we sync as sources
SYNCABLE_EXTENSIONS = {".md", ".pdf", ".txt"}

# Skip patterns -- files/dirs that are never worth syncing
SKIP_PATTERNS = {
    ".space",
    ".checkpoint.json",
    "def.json",
    ".obsidian",
    "node_modules",
    "__pycache__",
}

# Files that are low-value noise (Obsidian metadata, empty templates, etc.)
SKIP_FILENAMES = {
    "Courses.md",  # Index file, not content
}

# Minimum file size to sync (skip empty/stub files)
MIN_FILE_SIZE = 100  # bytes


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
class KnowledgeDomain:
    """Configuration for a knowledge domain used in concept bridging."""

    domain: str
    anchors: list[str] = field(default_factory=list)


@dataclass
class KnowledgeDomainsConfig:
    """Configuration for the knowledge bridging system."""

    primary: str = "networking"
    anchors: list[dict[str, str | int]] = field(default_factory=list)
    secondary: list[KnowledgeDomain] = field(default_factory=list)


@dataclass
class NotebookLMConfig:
    """Configuration for Google NotebookLM integration."""

    enabled: bool = False


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
    knowledge_domains: KnowledgeDomainsConfig = field(default_factory=KnowledgeDomainsConfig)
    notebooklm: NotebookLMConfig = field(default_factory=NotebookLMConfig)


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

    # Knowledge domains configuration
    kd = raw.get("knowledge_domains", {})
    if kd:
        settings.knowledge_domains = KnowledgeDomainsConfig(
            primary=kd.get("primary", "networking"),
            anchors=kd.get("anchors", []),
            secondary=[
                KnowledgeDomain(
                    domain=s.get("domain", ""),
                    anchors=s.get("anchors", []),
                )
                for s in kd.get("secondary", [])
            ],
        )

    # NotebookLM configuration
    nlm = raw.get("notebooklm", {})
    if nlm:
        settings.notebooklm = NotebookLMConfig(
            enabled=bool(nlm.get("enabled", False)),
        )

    return settings


# ---------------------------------------------------------------------------
# Topic mapping (previously in config.py)
# ---------------------------------------------------------------------------


@dataclass
class Topic:
    """A study topic maps to one NotebookLM notebook."""

    name: str
    display_name: str
    notebook_id: str | None  # Pre-mapped to existing NotebookLM notebook
    obsidian_paths: list[Path]
    tags: list[str] = field(default_factory=list)


def get_topics() -> list[Topic]:
    """Load topics from settings, falling back to defaults (without notebook IDs)."""
    settings = load_settings()
    if settings.topics:
        return [
            Topic(
                name=t.slug,
                display_name=t.name,
                notebook_id=t.notebook_id or None,
                obsidian_paths=[t.obsidian_path],
                tags=t.tags,
            )
            for t in settings.topics
        ]

    # Compute paths from settings for defaults
    obsidian_base = settings.obsidian_base
    obsidian_courses = obsidian_base / "Personal" / "2-Areas" / "Study" / "Courses"
    obsidian_mentoring = obsidian_base / "Personal" / "2-Areas" / "Study" / "Mentoring"

    return [
        Topic(
            name="python",
            display_name="Python Study",
            notebook_id=None,
            obsidian_paths=[obsidian_courses / "ArjanCodes", obsidian_mentoring / "Python"],
            tags=["python", "patterns", "oop", "architecture"],
        ),
        Topic(
            name="sql",
            display_name="SQL & Database Design",
            notebook_id=None,
            obsidian_paths=[obsidian_courses / "DataCamp", obsidian_mentoring / "Databases"],
            tags=["sql", "postgresql", "athena", "redshift", "database"],
        ),
        Topic(
            name="data-engineering",
            display_name="Data Engineering",
            notebook_id=None,
            obsidian_paths=[
                obsidian_courses / "ZTM" / "transcripts" / "data-engineering-bootcamp",
                obsidian_mentoring / "Data-Engineering",
            ],
            tags=["etl", "spark", "glue", "airflow", "dbt", "pipeline", "lakehouse"],
        ),
        Topic(
            name="aws-analytics",
            display_name="AWS Analytics Services",
            notebook_id=None,
            obsidian_paths=[
                obsidian_courses / "ZTM" / "Ai-Engineering-Aws-Sagemaker",
                obsidian_mentoring / "AWS",
            ],
            tags=["athena", "redshift", "glue", "sagemaker", "lake-formation", "emr"],
        ),
    ]


# ---------------------------------------------------------------------------
# Path helpers (previously in config.py / config_path.py)
# ---------------------------------------------------------------------------


def get_db_path() -> Path:
    """Get sessions.db path from config, or use default."""
    config_file = _CONFIG_PATH
    if config_file.exists():
        try:
            data = yaml.safe_load(config_file.read_text()) or {}
            # Support both old 'database.path' key and new 'session_db' key
            db_str = data.get("session_db", "")
            if not db_str:
                db_str = data.get("database", {}).get("path", "")
            if db_str:
                return Path(db_str).expanduser()
        except Exception:
            pass
    return DEFAULT_DB


def get_state_dir() -> Path:
    """Get state directory from settings."""
    return load_settings().state_dir


def get_state_file() -> Path:
    """Get state file path from settings."""
    return get_state_dir() / "state.json"


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

# Google NotebookLM integration (optional)
# Run 'studyctl config init' for interactive setup
# notebooklm:
#   enabled: true

# Knowledge domains for concept bridging (optional)
# Run 'studyctl config init' for interactive setup
# knowledge_domains:
#   primary: networking
#   anchors:
#     - concept: "ECMP load balancing"
#       comfort: 10
#     - concept: "BGP route propagation"
#       comfort: 9
#   secondary:
#     - domain: cooking
#       anchors: ["mise en place", "flavour balancing"]
"""
