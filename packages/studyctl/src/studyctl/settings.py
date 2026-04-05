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
class ContentConfig:
    """Configuration for the content pipeline (pdf-by-chapters absorption)."""

    base_path: Path = field(default_factory=lambda: Path.home() / "study-materials")
    notebooklm_timeout: int = 900
    inter_episode_gap: int = 30
    default_types: list[str] = field(default_factory=lambda: ["audio"])
    pandoc_path: str = "pandoc"


@dataclass
class LocalLLMConfig:
    """Configuration for a local LLM provider (Ollama, LM Studio)."""

    model: str = ""
    base_url: str = ""


@dataclass
class AgentsConfig:
    """Configuration for AI agent detection and priority."""

    priority: list[str] = field(
        default_factory=lambda: ["claude", "kiro", "gemini", "opencode", "ollama", "lmstudio"]
    )
    ollama: LocalLLMConfig = field(
        default_factory=lambda: LocalLLMConfig(
            model="qwen3-coder",
            base_url="http://localhost:4000",  # LiteLLM proxy (Ollama doesn't speak Anthropic API)
        )
    )
    lmstudio: LocalLLMConfig = field(
        default_factory=lambda: LocalLLMConfig(
            model="qwen3-coder",
            base_url="http://localhost:1234",
        )
    )


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
    content: ContentConfig = field(default_factory=ContentConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)


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

    # Agents configuration
    ag = raw.get("agents", {})
    if ag:
        ollama_raw = ag.get("ollama", {})
        lmstudio_raw = ag.get("lmstudio", {})
        settings.agents = AgentsConfig(
            priority=ag.get(
                "priority", ["claude", "kiro", "gemini", "opencode", "ollama", "lmstudio"]
            ),
            ollama=LocalLLMConfig(
                model=ollama_raw.get("model", "qwen3-coder"),
                base_url=ollama_raw.get("base_url", "http://localhost:4000"),
            ),
            lmstudio=LocalLLMConfig(
                model=lmstudio_raw.get("model", "qwen3-coder"),
                base_url=lmstudio_raw.get("base_url", "http://localhost:1234"),
            ),
        )

    # Content pipeline configuration
    ct = raw.get("content", {})
    if ct:
        settings.content = ContentConfig(
            base_path=Path(ct.get("base_path", "~/study-materials")).expanduser(),
            notebooklm_timeout=ct.get("notebooklm_timeout", 900),
            inter_episode_gap=ct.get("inter_episode_gap", 30),
            default_types=ct.get("default_types", ["audio"]),
            pandoc_path=ct.get("pandoc_path", "pandoc"),
        )

    return settings


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

# AI agent configuration
# Priority order for auto-detection (first installed agent wins)
# Override per-session with: studyctl study "topic" --agent gemini
# Override via env var: STUDYCTL_AGENT=gemini
# agents:
#   priority: [claude, kiro, gemini, opencode, ollama, lmstudio]
#   ollama:
#     model: qwen3-coder                # Model name from 'ollama list'
#     # base_url: http://localhost:4000   # LiteLLM proxy (Ollama needs a translation layer)
#   lmstudio:
#     model: qwen3-coder                # Model loaded in LM Studio
#     # base_url: http://localhost:1234   # Default LM Studio API endpoint

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

# Content pipeline (studyctl content commands)
# content:
#   base_path: ~/study-materials       # Where course directories are stored
#   notebooklm_timeout: 900            # Timeout for generation (seconds)
#   inter_episode_gap: 30              # Seconds between episode generations
#   default_types: [audio]             # Default artifact types to generate
#   pandoc_path: pandoc                # Path to pandoc binary
"""
