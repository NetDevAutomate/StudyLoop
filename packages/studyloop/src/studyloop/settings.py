"""Centralized configuration loader for studyloop.

Loads from ~/.config/studyloop/config.yaml with sensible defaults.
All configuration types, topic mapping, and path resolution live here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import yaml

CONFIG_DIR = Path.home() / ".config" / "studyloop"
LEGACY_CONFIG_DIR = Path.home() / ".config" / "studyctl"
DEFAULT_DB = CONFIG_DIR / "sessions.db"
DEFAULT_STATE_DIR = Path.home() / ".local" / "share" / "studyloop"
MAX_ACTIVE_TOPICS = 3

_CONFIG_PATH = Path(os.environ.get("STUDYLOOP_CONFIG", CONFIG_DIR / "config.yaml"))
_MIGRATION_CHECKED = False


def _default_session_db() -> Path:
    """Resolve the session DB default, honouring ``STUDYLOOP_DB``.

    Same fallback semantics as :func:`get_db_path` — an explicit config key
    still wins, because it is applied after the dataclass is constructed.

    This exists because the session DB path is resolved in three independent
    places: :func:`get_db_path`, this field (read by
    ``history/_connection.py``), and
    ``agent_session_tools.config_loader.get_db_path``. All three must honour
    the override or a test run reaches the learner's real database through
    whichever one was missed. See
    ``docs/issues/0005-vendor-picker-lists-repo-directories.md``.
    """
    if env_db := os.environ.get("STUDYLOOP_DB"):
        return Path(env_db).expanduser()
    return DEFAULT_DB


def _default_state_dir() -> Path:
    """Resolve the state directory, honouring ``STUDYLOOP_STATE_DIR``.

    Read at call time rather than import time so a test (or a subprocess it
    spawns) can redirect writable state away from the learner's real
    ``~/.local/share/studyloop``. Caches persisted there are trusted on read,
    so a leaked test artefact becomes a production defect — see
    ``docs/issues/0005-vendor-picker-lists-repo-directories.md``.
    """
    if env_dir := os.environ.get("STUDYLOOP_STATE_DIR"):
        return Path(env_dir).expanduser()
    return DEFAULT_STATE_DIR


def _maybe_migrate_legacy_config() -> None:
    """One-shot copy ~/.config/studyctl/ -> ~/.config/studyloop/ on first run.

    Runs at most once per process. Only activates when the legacy dir exists
    and the new dir does not — no data is overwritten. The legacy dir is
    left in place for rollback; callers can delete it manually later.
    """
    global _MIGRATION_CHECKED
    if _MIGRATION_CHECKED:
        return
    _MIGRATION_CHECKED = True

    if os.environ.get("STUDYLOOP_SKIP_LEGACY_MIGRATION"):
        return
    if CONFIG_DIR.exists():
        return
    if not LEGACY_CONFIG_DIR.exists():
        return

    try:
        import shutil as _shutil

        _shutil.copytree(LEGACY_CONFIG_DIR, CONFIG_DIR, dirs_exist_ok=False)
    except OSError:
        # Migration is best-effort. If copy fails, leave both dirs alone and
        # let the user resolve manually. Silent failure is safer than raising
        # on every CLI invocation.
        return


class ConfigError(click.ClickException):
    """User-facing error for invalid studyloop configuration."""


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
    study_paths: list[Path] = field(
        default_factory=lambda: [Path.home() / "Obsidian" / "Personal" / "Study"]
    )
    notebooklm_timeout: int = 900
    inter_episode_gap: int = 30
    default_types: list[str] = field(default_factory=lambda: ["audio"])
    pandoc_path: str = "pandoc"


@dataclass
class PomodoroConfig:
    """Configuration for the Pomodoro timer (web UI + TUI sidebar)."""

    focus: int = 25  # minutes
    short_break: int = 5
    long_break: int = 15
    cycles: int = 4  # long break after this many focus blocks


@dataclass
class OllamaBackendConfig:
    """Ollama-specific settings for the card generator."""

    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:7b"


@dataclass
class BedrockBackendConfig:
    """AWS Bedrock-specific settings for the card generator.

    ``profile`` is tried first; if the profile is missing or the call
    fails with a credential error, ``profile_fallback`` is tried. This
    makes the same config portable across machines where one has the
    prod profile and another only has a local / dev profile. Set the
    fallback to an empty string to disable fallback.

    ``fallback_region`` + ``fallback_model`` enable cross-region
    failover on ``ThrottlingException``. If capacity in the primary
    region (e.g. ``us-east-1``) is exhausted, the generator retries the
    same request once in the secondary region (e.g. ``eu-west-1``)
    using the region-matched inference profile. Leave both empty to
    disable the cross-region fallback.
    """

    # Inference profile ID on Bedrock (cross-region endpoint). Sonnet 4.6
    # is only invokable via an inference profile, not by the raw model ID.
    model: str = "us.anthropic.claude-sonnet-4-6"
    region: str = "us-east-1"
    profile: str = "bedrock-prod"
    profile_fallback: str = "bedrock-local"
    # Bedrock Converse API's maxTokens. Flashcard / quiz outputs rarely
    # exceed 4k tokens; 8k gives headroom for quiz decks.
    max_tokens: int = 8000
    # Optional region fallback on ThrottlingException. If both are set,
    # a throttled call in ``region``/``model`` retries once in
    # ``fallback_region`` using ``fallback_model``.
    fallback_region: str = "eu-west-1"
    fallback_model: str = "eu.anthropic.claude-sonnet-4-6"


@dataclass
class CardGeneratorConfig:
    """Configuration for the local card generator (flashcards + quizzes).

    Wired by ``content.generators.get_generator()``. The ``backend`` field
    selects which provider-specific sub-config is used. Providers that
    aren't the active backend are still loaded with defaults so switching
    backends is a one-line config change.
    """

    # Default to Ollama -- fully offline, zero-cost, no credential setup.
    # Set ``backend: bedrock`` in config.yaml for higher-quality cards
    # via Claude on AWS Bedrock (requires AWS credentials). Or use
    # ``openai_compat`` / ``anthropic_compat`` with a ``provider`` slug
    # from content/generators/provider_profiles.py for OpenAI,
    # OpenRouter, Gemini, or Anthropic.
    backend: str = "ollama"
    # Registry slug for ``*_compat`` backends. Empty for legacy backends
    # (ollama, bedrock) -- they ignore this field.
    provider: str = ""
    # Curated model id within the chosen provider's profile. Empty
    # defaults to the profile's first cheap-tier entry.
    model: str = ""
    # Low temperature -- flashcards want deterministic factual output,
    # not creative variance. Applies to every backend.
    temperature: float = 0.1
    # Retries on JSON parse / schema validation failure. Transport errors
    # do not retry (backend dead = backend dead).
    max_retries: int = 2
    # HTTP / SDK request timeout in seconds. 14B-class models can be slow
    # on cold start; 180 s gives head-room without hanging the CLI.
    request_timeout: float = 180.0
    # Concurrency for multi-source generation. One worker per source file.
    # Bedrock throttles around 4 concurrent Converse calls per account;
    # Ollama serialises at the model level anyway.
    max_workers: int = 4
    # Per-backend sub-configs. Only the one matching ``backend`` is used
    # at runtime, but all are loaded so switching backends is config-only.
    ollama: OllamaBackendConfig = field(default_factory=OllamaBackendConfig)
    bedrock: BedrockBackendConfig = field(default_factory=BedrockBackendConfig)


@dataclass
class ObsidianConfig:
    """Configuration for the Obsidian vault session-memory export."""

    export_enabled: bool = False
    vault_path: Path = field(default_factory=lambda: Path.home() / "Obsidian" / "Personal")
    memory_dir: str = "AgentMemory"
    moc_dir: str = "AgentMemory/MOC"
    backlinks: bool = True
    granularity: str = "both"


@dataclass
class AgentsConfig:
    """Configuration for AI agent detection and priority."""

    priority: list[str] = field(
        default_factory=lambda: [
            "kiro",
            "codex",
            "claude",
            "opencode",
            "pi",
        ]
    )
    custom: dict[str, dict] = field(default_factory=dict)


@dataclass
class Settings:
    """Application settings loaded from config file."""

    obsidian_base: Path = field(default_factory=lambda: Path.home() / "Obsidian")
    #: Where the user's study notes live. The modern, Obsidian-neutral key.
    #: Empty means "no notes folder configured", which is a supported state: a
    #: learner with no notes uses their study sessions as the source instead.
    #: `notes_base()` resolves this against the legacy `obsidian_base`, so the
    #: internal field above deliberately keeps its name -- renaming it would
    #: touch every topic-path consumer for no user-visible gain.
    notes_path: Path | None = None
    session_db: Path = field(default_factory=_default_session_db)
    state_dir: Path = field(default_factory=_default_state_dir)
    topics: list[TopicConfig] = field(default_factory=list)
    sync_remote: str = ""
    sync_user: str = field(default_factory=lambda: _get_username())
    knowledge_domains: KnowledgeDomainsConfig = field(default_factory=KnowledgeDomainsConfig)
    notebooklm: NotebookLMConfig = field(default_factory=NotebookLMConfig)
    content: ContentConfig = field(default_factory=ContentConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    card_generator: CardGeneratorConfig = field(default_factory=CardGeneratorConfig)
    ttyd_port: int = 7681
    web_port: int = 8567
    browser: str = ""  # empty = system default; or "chrome", "safari", "firefox", "brave"
    pomodoro: PomodoroConfig = field(default_factory=PomodoroConfig)
    lan_username: str = "study"  # username for HTTP Basic Auth when using --lan
    lan_password: str = ""  # password for HTTP Basic Auth when using --lan (empty = auto-generate)
    obsidian: ObsidianConfig = field(default_factory=ObsidianConfig)


def _path(value: object) -> Path:
    """Coerce a config value to an expanded Path."""
    return Path(str(value)).expanduser()


def get_config_path() -> Path:
    """Return the active studyloop config path.

    ``STUDYLOOP_CONFIG`` is resolved lazily so tests and subprocesses can set it
    after module import. ``_CONFIG_PATH`` remains as the fallback compatibility
    hook for existing tests while callers migrate to this public helper.
    """
    if env_path := os.environ.get("STUDYLOOP_CONFIG"):
        return Path(env_path).expanduser()
    return _CONFIG_PATH.expanduser()


def get_config_dir() -> Path:
    """Return the active studyloop config directory."""
    return get_config_path().parent


def _expand_dotted_keys(raw: dict[str, Any]) -> dict[str, Any]:
    """Expand top-level dotted keys into nested mappings.

    In YAML, ``tts.backend: openvox`` is a single flat key named
    ``"tts.backend"`` — NOT ``tts: {backend: openvox}``. Real user configs
    contain the flat form (the doctor's repair hints used to suggest it
    verbatim), and every consumer reads the nested shape, so the flat key was
    silently ignored. Normalising here fixes all consumers at once.

    Rules: dotted keys merge into the nested tree; on conflict an explicit
    nested value wins over a dotted one (the nested form is authoritative);
    non-dict intermediate values are left alone rather than clobbered.
    """
    result: dict[str, Any] = {k: v for k, v in raw.items() if "." not in str(k)}
    for key, value in raw.items():
        if "." not in str(key):
            continue
        parts = str(key).split(".")
        node = result
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                if part in node:
                    # An existing non-dict value occupies this path — the
                    # explicit key wins; drop the dotted variant.
                    break
                child = {}
                node[part] = child
            node = child
        else:
            node.setdefault(parts[-1], value)
    return result


def load_raw_config() -> dict[str, Any]:
    """Load the raw YAML config from the active config path.

    Top-level dotted keys (``tts.backend: x``) are expanded to nested
    mappings (``tts: {backend: x}``); explicit nested values win on conflict.
    """
    _maybe_migrate_legacy_config()
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        loaded = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Invalid YAML in {config_path}. Fix the file or rerun 'studyloop config init'."
        ) from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(
            f"Invalid config in {config_path}: expected a YAML mapping at the top level."
        )
    return _expand_dotted_keys(loaded)


def resolve_study_dirs() -> list[str]:
    """Resolve the directories the review panels scan for decks.

    The web/MCP layers read decks from ``review.directories``; the content
    generator WRITES them under ``content.base_path``. These are two separate
    config keys that MUST agree, but a typical config sets only ``content``
    (the generator's root) and omits ``review`` entirely — so the panels were
    handed ``[]`` and showed nothing, even though decks were on disk.

    Resolution order:
      1. ``review.directories`` when explicitly set (verbatim — power users
         may point the panels at extra roots).
      2. Fallback to ``content.base_path`` (the generator's write root), so a
         freshly generated deck is discoverable with zero extra config.

    Always returns at least one entry (the default ``content.base_path`` when
    nothing is configured) so the panels have a root to scan on a fresh install.
    """
    raw = load_raw_config()
    # A bare ``review:`` key parses to None, not {} — guard with ``or {}``.
    review_dirs = (raw.get("review") or {}).get("directories") or []
    if isinstance(review_dirs, str):
        review_dirs = [review_dirs]  # scalar → single dir, not per-char explosion
    if review_dirs:
        return [str(d) for d in review_dirs]
    base_path = load_settings().content.base_path
    return [str(Path(base_path).expanduser())]


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
    ("notes_path", _path),
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


def _slugify_topic_name(name: str) -> str:
    """Create a stable slug for legacy topic names."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "topic"


def _topic_tags(raw: object) -> list[str]:
    """Normalize a topic's tag field to a list of strings."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(tag) for tag in raw]
    return [str(raw)]


def _default_topic_path(settings: Settings, name: str) -> Path:
    """Default path for legacy/minimal topics."""
    personal_vault_study = settings.obsidian_base / "Study" / name
    nested_personal_study = settings.obsidian_base / "Personal" / "Study" / name
    if personal_vault_study.exists():
        return personal_vault_study
    if nested_personal_study.exists():
        return nested_personal_study
    if settings.obsidian_base.name.lower() == "personal":
        return personal_vault_study
    return nested_personal_study


def notes_base(settings: Settings) -> Path:
    """Return the root that relative topic paths resolve against.

    Read order is modern-first: ``notes_path`` wins, then legacy
    ``obsidian_base``. Keeping both readable means an existing config keeps
    working untouched -- the setup wizard writes ``notes_path`` beside
    ``obsidian_base`` rather than replacing it, and never deletes the legacy key.
    """
    return settings.notes_path or settings.obsidian_base


def _topic_from_raw(raw: object, settings: Settings, position: int) -> TopicConfig | None:
    """Parse one raw topic entry.

    The modern schema is a mapping. Older configs used bare strings such as
    ``topics: [Python, SQL]``; support them so config loading does not crash.
    """
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            return None
        slug = _slugify_topic_name(name)
        return TopicConfig(
            name=name,
            slug=slug,
            obsidian_path=_default_topic_path(settings, name),
            tags=[slug],
        )

    if not isinstance(raw, dict):
        raise ConfigError(
            f"Invalid topic at position {position}: expected a mapping or topic name."
        )

    raw_name = raw.get("name", "")
    name = str(raw_name).strip()
    if not name:
        raise ConfigError(f"Invalid topic at position {position}: missing 'name'.")

    slug = str(raw.get("slug") or _slugify_topic_name(name))
    # Modern `notes_path` first, then legacy `obsidian_path`. The TopicConfig
    # field is still called obsidian_path on purpose: renaming it would ripple
    # through every consumer of topic paths without changing behaviour.
    raw_topic_path = raw.get("notes_path") or raw.get("obsidian_path") or f"Personal/Study/{name}"
    obsidian_path = Path(str(raw_topic_path)).expanduser()
    if not obsidian_path.is_absolute():
        obsidian_path = notes_base(settings) / str(raw_topic_path)

    return TopicConfig(
        name=name,
        slug=slug,
        obsidian_path=obsidian_path,
        notebook_id=str(raw.get("notebook_id", "")),
        tags=_topic_tags(raw.get("tags", [])),
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

    # --- topics (bespoke: legacy support + path resolution) -----------------
    raw_topics = raw.get("topics", [])
    if raw_topics is None:
        raw_topics = []
    if not isinstance(raw_topics, list):
        raise ConfigError("Invalid config: 'topics' must be a list.")
    for index, raw_topic in enumerate(raw_topics[:MAX_ACTIVE_TOPICS], start=1):
        topic = _topic_from_raw(raw_topic, settings, index)
        if topic is not None:
            settings.topics.append(topic)

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

    obs = raw.get("obsidian", {})
    if obs:
        # vault_path defaults to settings.obsidian_base when absent from the section
        raw_vault = obs.get("vault_path", None)
        vault_path = _path(raw_vault) if raw_vault is not None else settings.obsidian_base
        settings.obsidian = ObsidianConfig(
            export_enabled=bool(obs.get("export_enabled", False)),
            vault_path=vault_path,
            memory_dir=str(obs.get("memory_dir", "AgentMemory")),
            moc_dir=str(obs.get("moc_dir", "AgentMemory/MOC")),
            backlinks=bool(obs.get("backlinks", True)),
            granularity=str(obs.get("granularity", "both")),
        )
    else:
        # No obsidian: section at all — still align vault_path with obsidian_base
        settings.obsidian = ObsidianConfig(vault_path=settings.obsidian_base)

    ct = raw.get("content") or {}
    if ct:
        content_defaults = ContentConfig()
        raw_study_paths = ct.get("study_paths", content_defaults.study_paths)
        # A scalar study_paths (single path string) must not be iterated
        # per-character — coerce to a one-element list first.
        if isinstance(raw_study_paths, str):
            raw_study_paths = [raw_study_paths]
        settings.content = ContentConfig(
            base_path=_path(ct.get("base_path", "~/study-materials")),
            study_paths=[
                p if p.is_absolute() else settings.obsidian_base / p
                for p in (_path(path) for path in raw_study_paths)
            ],
            notebooklm_timeout=int(ct.get("notebooklm_timeout", 900)),
            inter_episode_gap=int(ct.get("inter_episode_gap", 30)),
            default_types=ct.get("default_types", ["audio"]),
            pandoc_path=str(ct.get("pandoc_path", "pandoc")),
        )

    ag = raw.get("agents", {})
    if ag:
        from studyloop.harnesses import RELEASE_HARNESSES

        default_priority = ["kiro", "codex", "claude", "opencode", "pi"]
        custom = ag.get("custom", {})
        admitted = set(RELEASE_HARNESSES) | set(custom)
        configured_priority = ag.get("priority", default_priority)
        settings.agents = AgentsConfig(
            priority=[name for name in configured_priority if name in admitted],
            custom=custom,
        )

    cg = raw.get("card_generator", {})
    if cg:
        defaults = CardGeneratorConfig()
        ollama_raw = cg.get("ollama", {})
        bedrock_raw = cg.get("bedrock", {})
        settings.card_generator = CardGeneratorConfig(
            backend=str(cg.get("backend", defaults.backend)),
            provider=str(cg.get("provider", defaults.provider)),
            model=str(cg.get("model", defaults.model)),
            temperature=float(cg.get("temperature", defaults.temperature)),
            max_retries=int(cg.get("max_retries", defaults.max_retries)),
            request_timeout=float(cg.get("request_timeout", defaults.request_timeout)),
            max_workers=int(cg.get("max_workers", defaults.max_workers)),
            ollama=OllamaBackendConfig(
                base_url=str(ollama_raw.get("base_url", defaults.ollama.base_url)),
                model=str(ollama_raw.get("model", defaults.ollama.model)),
            ),
            bedrock=BedrockBackendConfig(
                model=str(bedrock_raw.get("model", defaults.bedrock.model)),
                region=str(bedrock_raw.get("region", defaults.bedrock.region)),
                profile=str(bedrock_raw.get("profile", defaults.bedrock.profile)),
                profile_fallback=str(
                    bedrock_raw.get("profile_fallback", defaults.bedrock.profile_fallback)
                ),
                max_tokens=int(bedrock_raw.get("max_tokens", defaults.bedrock.max_tokens)),
                fallback_region=str(
                    bedrock_raw.get("fallback_region", defaults.bedrock.fallback_region)
                ),
                fallback_model=str(
                    bedrock_raw.get("fallback_model", defaults.bedrock.fallback_model)
                ),
            ),
        )

    return settings


# ---------------------------------------------------------------------------
# Path helpers (previously in config.py / config_path.py)
# ---------------------------------------------------------------------------


def get_db_path() -> Path:
    """Get sessions.db path from config, the environment, or the default.

    Precedence: an explicit ``session_db`` / ``database.path`` config key wins,
    then ``STUDYLOOP_DB``, then ``DEFAULT_DB``.

    ``STUDYLOOP_DB`` replaces only the *hardcoded default*, deliberately. It
    exists so a test run — or any subprocess a test spawns — cannot fall
    through to the learner's real ``sessions.db`` and run migrations against
    it. Letting it outrank an explicit config key would break the legitimate
    pattern of a test writing its own config, so it does not.
    """
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
    if env_db := os.environ.get("STUDYLOOP_DB"):
        return Path(env_db).expanduser()
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
# studyloop configuration
# Location: ~/.config/studyloop/config.yaml

# Base path to your Obsidian vault
obsidian_base: ~/Obsidian

# Path to the AI session database
session_db: ~/.config/studyloop/sessions.db

# State directory for sync tracking
state_dir: ~/.local/share/studyloop

# Remote sync configuration (optional)
# sync_remote: your-remote-host
# sync_user: your-username

# Study topics
# Keep active topics to three or fewer. Put extra ideas in the study backlog
# with: studyloop backlog add "topic to revisit"
# Each active topic maps to an Obsidian directory and optionally a NotebookLM notebook.
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

# AI agent configuration
# Priority order for auto-detection (first installed agent wins)
# Override per-session with: studyloop study "topic" --agent kiro
# Override via env var: STUDYLOOP_AGENT=kiro
# agents:
#   priority: [kiro, codex, claude, opencode, pi]
# Medication timing (optional — for ADHD stimulant medication awareness)
# Uncomment to enable medication-aware session recommendations
# medication:
#   dose_time: "08:00"        # When you take your medication (24h format)
#   onset_minutes: 30         # Minutes until meds kick in
#   peak_hours: 4             # Hours of peak effectiveness
#   duration_hours: 8         # Total duration before wearing off

# Google NotebookLM integration (optional)
# Run 'studyloop config init' for interactive setup
# notebooklm:
#   enabled: true

# Knowledge domains for concept bridging (optional)
# Run 'studyloop config init' for interactive setup
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

# Content pipeline (studyloop content commands)
# content:
#   base_path: ~/study-materials       # Where course directories are stored
#   study_paths:
#     - ~/Obsidian/Personal/Study      # Default study material source directory
#   notebooklm_timeout: 900            # Timeout for generation (seconds)
#   inter_episode_gap: 30              # Seconds between episode generations
#   default_types: [audio]             # Default artifact types to generate
#   pandoc_path: pandoc                # Path to pandoc binary

# Persona evaluation judge (for studyloop eval)
# eval:
#   judge:
#     provider: ollama                    # "ollama" or "openai-compat"
#     base_url: http://localhost:11434    # Ollama default; or LAN IP for remote
#     model: gemma4:26b                  # Recommended: MoE model, 4B active params
#     # api_key_env: EVAL_API_KEY        # For OpenAI-compat providers
"""
