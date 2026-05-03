"""Centralized configuration loader for studyctl.

Loads from ~/.config/studyctl/config.yaml with sensible defaults.
All configuration types, topic mapping, and path resolution live here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import yaml

CONFIG_DIR = Path.home() / ".config" / "studyctl"
DEFAULT_DB = CONFIG_DIR / "sessions.db"

_CONFIG_PATH = Path(os.environ.get("STUDYCTL_CONFIG", CONFIG_DIR / "config.yaml"))


class ConfigError(click.ClickException):
    """User-facing error for invalid studyctl configuration."""


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
    study_paths: list[Path] = field(default_factory=list)
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
class PomodoroConfig:
    """Configuration for the Pomodoro timer (web UI + TUI sidebar)."""

    focus: int = 25  # minutes
    short_break: int = 5
    long_break: int = 15
    cycles: int = 4  # long break after this many focus blocks


@dataclass
class AgentsConfig:
    """Configuration for AI agent detection and priority."""

    priority: list[str] = field(
        default_factory=lambda: [
            "claude",
            "kiro",
            "gemini",
            "opencode",
            "codex",
            "ollama",
            "lmstudio",
        ]
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
    custom: dict[str, dict] = field(default_factory=dict)


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
    ttyd_port: int = 7681
    web_port: int = 8567
    browser: str = ""  # empty = system default; or "chrome", "safari", "firefox", "brave"
    pomodoro: PomodoroConfig = field(default_factory=PomodoroConfig)
    lan_username: str = "study"  # username for HTTP Basic Auth when using --lan
    lan_password: str = ""  # password for HTTP Basic Auth when using --lan (empty = auto-generate)


def _path(value: object) -> Path:
    """Coerce a config value to an expanded Path."""
    return Path(str(value)).expanduser()


def get_config_path() -> Path:
    """Return the active studyctl config path.

    ``STUDYCTL_CONFIG`` is resolved lazily so tests and subprocesses can set it
    after module import. ``_CONFIG_PATH`` remains as the fallback compatibility
    hook for existing tests while callers migrate to this public helper.
    """
    if env_path := os.environ.get("STUDYCTL_CONFIG"):
        return Path(env_path).expanduser()
    return _CONFIG_PATH.expanduser()


def get_config_dir() -> Path:
    """Return the active studyctl config directory."""
    return get_config_path().parent


def load_raw_config() -> dict[str, Any]:
    """Load the raw YAML config from the active config path."""
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        loaded = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Invalid YAML in {config_path}. Fix the file or rerun 'studyctl config init'."
        ) from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(
            f"Invalid config in {config_path}: expected a YAML mapping at the top level."
        )
    return loaded


def write_raw_config(data: dict[str, Any]) -> Path:
    """Write raw YAML config to the active config path and return the path."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return config_path


# Top-level scalar fields: (settings_attr, coerce_fn).
# When the YAML key matches settings_attr, the value is coerced and set directly.
_SCALAR_FIELDS: list[tuple[str, object]] = [
    ("obsidian_base", _path),
    ("session_db", _path),
    ("state_dir", _path),
    ("sync_remote", str),
    ("sync_user", str),
    ("ttyd_port", int),
    ("web_port", int),
    ("browser", str),
    ("lan_username", str),
    ("lan_password", str),
]


def _local_llm(raw: dict, default_model: str, default_base_url: str) -> LocalLLMConfig:
    """Build a LocalLLMConfig from a raw dict, falling back to explicit defaults."""
    return LocalLLMConfig(
        model=str(raw.get("model", default_model)),
        base_url=str(raw.get("base_url", default_base_url)),
    )


def load_settings() -> Settings:
    """Load settings from config file, falling back to defaults."""
    settings = Settings()
    raw = load_raw_config()
    if not raw:
        return settings

    # scalar top-level fields -- driven by module-level _SCALAR_FIELDS mapping
    for key, coerce in _SCALAR_FIELDS:
        if key in raw:
            setattr(settings, key, coerce(raw[key]))  # type: ignore[operator]

    # --- topics (bespoke: path resolution relative to obsidian_base) ---------
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

    # --- knowledge_domains (bespoke: nested KnowledgeDomain list) ------------
    kd = raw.get("knowledge_domains", {})
    if kd:
        settings.knowledge_domains = KnowledgeDomainsConfig(
            primary=kd.get("primary", "networking"),
            anchors=kd.get("anchors", []),
            secondary=[
                KnowledgeDomain(domain=s.get("domain", ""), anchors=s.get("anchors", []))
                for s in kd.get("secondary", [])
            ],
        )

    # --- flat sub-config sections: (raw_key, dataclass_type, field_coercions) -
    nlm = raw.get("notebooklm", {})
    if nlm:
        settings.notebooklm = NotebookLMConfig(enabled=bool(nlm.get("enabled", False)))

    pomo = raw.get("pomodoro", {})
    if pomo:
        settings.pomodoro = PomodoroConfig(
            focus=int(pomo.get("focus", 25)),
            short_break=int(pomo.get("short_break", 5)),
            long_break=int(pomo.get("long_break", 15)),
            cycles=int(pomo.get("cycles", 4)),
        )

    ct = raw.get("content", {})
    if ct:
        settings.content = ContentConfig(
            base_path=_path(ct.get("base_path", "~/study-materials")),
            study_paths=[
                p if p.is_absolute() else settings.obsidian_base / p
                for p in (_path(path) for path in ct.get("study_paths", []))
            ],
            notebooklm_timeout=int(ct.get("notebooklm_timeout", 900)),
            inter_episode_gap=int(ct.get("inter_episode_gap", 30)),
            default_types=ct.get("default_types", ["audio"]),
            pandoc_path=str(ct.get("pandoc_path", "pandoc")),
        )

    ag = raw.get("agents", {})
    if ag:
        default_priority = ["claude", "kiro", "gemini", "opencode", "codex", "ollama", "lmstudio"]
        settings.agents = AgentsConfig(
            priority=ag.get("priority", default_priority),
            ollama=_local_llm(ag.get("ollama", {}), "qwen3-coder", "http://localhost:4000"),
            lmstudio=_local_llm(ag.get("lmstudio", {}), "qwen3-coder", "http://localhost:1234"),
            custom=ag.get("custom", {}),
        )

    return settings


# ---------------------------------------------------------------------------
# Path helpers (previously in config.py / config_path.py)
# ---------------------------------------------------------------------------


def get_db_path() -> Path:
    """Get sessions.db path from config, or use default."""
    try:
        data = load_raw_config()
        # Support both old 'database.path' key and new 'session_db' key
        db_str = data.get("session_db", "")
        if not db_str:
            db_str = data.get("database", {}).get("path", "")
        if db_str:
            return Path(db_str).expanduser()
    except (OSError, TypeError, AttributeError):
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
#   priority: [codex, claude, kiro, gemini, opencode, ollama, lmstudio]
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

# Pomodoro timer (web UI + TUI sidebar)
# Adjust focus/break durations and cycle length.
# These are defaults — can also be changed in the web UI per-session.
# pomodoro:
#   focus: 25            # Focus duration in minutes
#   short_break: 5       # Short break in minutes
#   long_break: 15       # Long break in minutes (after 'cycles' focus blocks)
#   cycles: 4            # Number of focus blocks before a long break

# LAN access credentials (for --lan mode)
# Set these to avoid auto-generated passwords each session.
# If lan_password is empty and --lan is used, a random password is generated.
# lan_username: study
# lan_password: your-password-here

# Content pipeline (studyctl content commands)
# content:
#   base_path: ~/study-materials       # Where course directories are stored
#   study_paths: []                    # Extra Obsidian/content source dirs for NotebookLM uploads
#   notebooklm_timeout: 900            # Timeout for generation (seconds)
#   inter_episode_gap: 30              # Seconds between episode generations
#   default_types: [audio]             # Default artifact types to generate
#   pandoc_path: pandoc                # Path to pandoc binary

# Persona evaluation judge (for studyctl eval)
# eval:
#   judge:
#     provider: ollama                    # "ollama" or "openai-compat"
#     base_url: http://localhost:11434    # Ollama default; or LAN IP for remote
#     model: gemma4:26b                  # Recommended: MoE model, 4B active params
#     # api_key_env: EVAL_API_KEY        # For OpenAI-compat providers
"""
