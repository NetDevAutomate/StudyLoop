"""Centralized configuration loader for agent-session-tools.

Loads configuration from ~/.config/studyloop/config.yaml and .env.

Note: Both studyloop and agent-session-tools read the SAME config.yaml file.
Each package reads only the sections it needs — studyloop reads topics/content/
knowledge_domains; this package reads database/sync/semantic_search. This is
intentional: the packages are independently publishable, so they must not
import each other's config loaders.
"""

import copy
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Default paths
CONFIG_DIR = Path.home() / ".config" / "studyloop"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

# Fallback defaults
DEFAULT_CONFIG = {
    "database": {
        "path": str(CONFIG_DIR / "sessions.db"),
        "archive_path": str(CONFIG_DIR / "sessions_archive.db"),
        "backup_dir": str(CONFIG_DIR / "backups"),
        # Tiering: complete-history DB (e.g. on an external volume).
        # Empty string = tiering disabled. See tiering.py.
        "full_db_path": "",
        # Sync cadence for the background hot->full sync: "always" (every
        # export/session trigger; record trails the spool by seconds) or
        # "daily" (first trigger of the day only).
        "sync_mode": "always",
        # Auto-snapshot the full DB after a sync when the newest snapshot is
        # older than this many days. 0 = manual snapshots only.
        "snapshot_interval_days": 7,
        # Point-in-time snapshots of the full DB. Empty = fall back to
        # backup_dir. Keep maintenance backups local and snapshots on the
        # same volume as the full DB.
        "snapshot_dir": "",
        # Point-in-time snapshots of the full DB to keep (rotation).
        "snapshot_retention": 7,
        # Timestamped maintenance backups of the hot DB to keep (rotation).
        "backup_retention": 5,
        # Refuse full-copy maintenance backups above this size (MB) — at
        # multi-GB sizes use snapshots of the full DB instead.
        "backup_max_mb": 1024,
    },
    "thresholds": {
        "warning_mb": 100,
        "critical_mb": 500,
    },
    "logging": {
        "enabled": True,
        "path": str(CONFIG_DIR / "sessions.log"),
        "level": "INFO",
    },
    "tui": {
        "theme": "dark",
        "refresh_interval": 5,
        "max_preview_length": 300,
        "syntax_theme": "monokai",
    },
    "semantic_search": {
        # Embedding model to use (see embeddings.py SUPPORTED_MODELS for options)
        # Default: "all-mpnet-base-v2" - reliable with strong semantic understanding
        # Note: nomic-embed-text-v1.5 has compatibility issues with sentence-transformers 5.x
        # Fast option: "all-MiniLM-L6-v2" for testing
        "model": "all-mpnet-base-v2",
        # Hybrid search weights (must sum to 1.0)
        "fts_weight": 0.4,
        "semantic_weight": 0.6,
        # Minimum content length to embed
        "min_content_length": 50,
        # Auto-embed on export
        "auto_embed": True,
    },
    "obsidian": {
        # Feature gate — default OFF; set to true to enable vault export
        "export_enabled": False,
        # Absolute path to the Obsidian vault root (~ expanded at load time)
        "vault_path": str(Path.home() / "Obsidian" / "Personal"),
        # Folder inside vault for agent-generated session notes
        "memory_dir": "AgentMemory",
        # Sub-folder for per-project MOC index notes
        "moc_dir": "AgentMemory/MOC",
        # Inject [[wikilink]]s for matched vault topic notes
        "backlinks": True,
        # "session" | "moc" | "both"
        "granularity": "both",
        # Filename template — supports $date, $source, $slug
        "filename_template": "$date-$source-$slug",
    },
    "excluded_dirs": [
        "CloudStorage",
        ".Encrypted",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        ".tox",
        "dist",
        "build",
        ".eggs",
    ],
}


def expand_path(path_str: str) -> Path:
    """Expand ~ and environment variables in path."""
    return Path(os.path.expanduser(os.path.expandvars(path_str)))


def get_config_file() -> Path:
    """Get the shared studyloop config file path.

    STUDYLOOP_CONFIG is resolved at call time so tests and long-running processes can
    change the active config without re-importing this module.
    """
    if config_path := os.getenv("STUDYLOOP_CONFIG"):
        return expand_path(config_path)
    return CONFIG_FILE


def get_config_dir() -> Path:
    """Get the directory containing the shared studyloop config file."""
    return get_config_file().parent


def get_env_file() -> Path:
    """Get the .env file stored beside the shared studyloop config file."""
    return get_config_dir() / ".env"


def get_endpoints(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Get configured sync endpoints from hosts section.

    Reads the unified 'hosts' config and converts to endpoint format,
    filtering out the local machine (detected by hostname match).
    Falls back to legacy 'endpoints' key for backwards compatibility.
    """
    if config is None:
        config = load_config()

    # New format: derive endpoints from hosts section
    hosts = config.get("hosts", {})
    if hosts:
        import socket

        current_hostname = socket.gethostname().split(".")[0]
        endpoints: dict[str, dict[str, Any]] = {}

        for name, host in hosts.items():
            # Skip the local machine
            if host.get("hostname") == current_hostname:
                continue

            ip_cfg = host.get("ip_address", {})
            if isinstance(ip_cfg, dict):
                ip_address = {
                    "primary_ip": ip_cfg.get("primary", ""),
                    "secondary_ip": ip_cfg.get("secondary", ""),
                }
            else:
                ip_address = {"primary_ip": str(ip_cfg) if ip_cfg else ""}

            endpoints[name] = {
                "username": host.get("user", ""),
                "path": host.get("sessions_db", str(get_config_dir() / "sessions.db")),
                # Tier-aware sync: remote full-history DB path (optional).
                "full_path": host.get("full_db", ""),
                "ip_address": ip_address,
            }

        return endpoints

    # Legacy format: direct endpoints config
    return config.get("endpoints", {})


def _expand_dotted_keys(raw: dict[str, Any]) -> dict[str, Any]:
    """Expand top-level dotted keys into nested mappings.

    In YAML, ``tts.backend: openvox`` is a single flat key named
    ``"tts.backend"`` -- NOT ``tts: {backend: openvox}``. Real user configs
    contain the flat form (the doctor's repair hints used to suggest it
    verbatim), and every consumer reads the nested shape, so the flat key was
    silently ignored.

    Rules: dotted keys merge into the nested tree; on conflict an explicit
    nested value wins over a dotted one (the nested form is authoritative);
    non-dict intermediate values are left alone rather than clobbered.

    DELIBERATE DUPLICATE of ``studyloop.settings._expand_dotted_keys``. The two
    packages are independently publishable and must not import each other's
    config loaders (see the module docstring), but they parse the SAME
    config.yaml, so they have to agree on its syntax. A previous fix changed
    only the studyloop side and claimed it "fixes all 6 consumers at once";
    it missed this loader. ``test_voice_backends.py::
    test_dotted_key_expansion_is_identical_in_both_packages`` asserts the two
    stay behaviourally identical -- change both or neither.
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
                    # An existing non-dict value occupies this path -- the
                    # explicit key wins; drop the dotted variant.
                    break
                child = {}
                node[part] = child
            node = child
        else:
            node.setdefault(parts[-1], value)
    return result


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml with fallbacks.

    Priority order:
    1. Environment variables
    2. ~/.config/studyloop/config.yaml
    3. Local config.json (backwards compatibility)
    4. Built-in defaults
    """
    config = copy.deepcopy(DEFAULT_CONFIG)

    # Load .env file if exists.
    #
    # R-09b: STUDYLOOP_TEST_AGENT_CMD / STUDYLOOP_TEST_ACP_CMD are
    # shell=True-executed test-only escape hatches, honoured unconditionally
    # in studyloop's production session-start paths. studyloop's own package
    # import (studyloop/__init__.py) already refuses to let a `.env` set
    # either one -- it snapshots the STUDYLOOP_TEST_* keys present BEFORE its
    # dotenv load and deletes anything a `.env` added afterward. This loader
    # is a SECOND, independent dotenv load of a `.env` at the SAME path
    # (this package must not import studyloop's config loader, or vice
    # versa -- see the module docstring), and it runs LATER: at web-server
    # startup, via export_sessions.py's module-level load_config() call,
    # reached from studyloop/web/_schema_init.py's prepare_schema() --
    # strictly AFTER studyloop's own scrub already ran. Without the same
    # rule here, a `.env` at this path reintroduces the hatch on every
    # server boot, before the first request is served. DUPLICATE of the
    # rule in studyloop/__init__.py (same reasoning as the DELIBERATE
    # DUPLICATE of _expand_dotted_keys above) -- keep both in sync.
    env_file = get_env_file()
    if env_file.exists():
        pre_dotenv_test_keys = frozenset(
            key for key in os.environ if key.startswith("STUDYLOOP_TEST_")
        )
        load_dotenv(env_file)
        for key in [key for key in os.environ if key.startswith("STUDYLOOP_TEST_")]:
            if key in pre_dotenv_test_keys:
                continue
            del os.environ[key]
            logger.warning(
                "Ignoring %s loaded from %s: STUDYLOOP_TEST_* test hatches are "
                "only honoured when exported in the real process environment, "
                "never when set by a .env file.",
                key,
                env_file,
            )

    # Try loading config.yaml (new location first, then legacy)
    config_file = get_config_file()
    legacy_config = Path.home() / ".config" / "agent_session" / "config.yaml"
    if (
        not os.getenv("STUDYLOOP_CONFIG")
        and not config_file.exists()
        and legacy_config.exists()
    ):
        config_file = legacy_config

    if config_file.exists():
        try:
            with open(config_file) as f:
                yaml_config = yaml.safe_load(f)
                if yaml_config:
                    # Normalise flat `a.b: v` keys to nested form first, so a
                    # user config written in the dotted style is not silently
                    # ignored by the merge below.
                    if isinstance(yaml_config, dict):
                        yaml_config = _expand_dotted_keys(yaml_config)
                    # Deep merge with defaults
                    _deep_merge(config, yaml_config)
        except Exception as e:
            print(f"Warning: Failed to load {config_file}: {e}")

    # Override with environment variables
    if v := os.getenv("DATABASE_PATH"):
        config["database"]["path"] = v
    if v := os.getenv("LOG_LEVEL"):
        config["logging"]["level"] = v
    if v := os.getenv("WARNING_THRESHOLD_MB"):
        config["thresholds"]["warning_mb"] = int(v)
    if v := os.getenv("CRITICAL_THRESHOLD_MB"):
        config["thresholds"]["critical_mb"] = int(v)

    # Expand all paths
    config["database"]["path"] = str(expand_path(config["database"]["path"]))
    config["database"]["archive_path"] = str(
        expand_path(config["database"]["archive_path"])
    )
    config["database"]["backup_dir"] = str(
        expand_path(config["database"]["backup_dir"])
    )
    if config["database"].get("full_db_path"):
        config["database"]["full_db_path"] = str(
            expand_path(config["database"]["full_db_path"])
        )
    if config["database"].get("snapshot_dir"):
        config["database"]["snapshot_dir"] = str(
            expand_path(config["database"]["snapshot_dir"])
        )
    config["logging"]["path"] = str(expand_path(config["logging"]["path"]))

    # Expand obsidian vault_path if the section is present
    if "obsidian" in config and "vault_path" in config["obsidian"]:
        config["obsidian"]["vault_path"] = str(
            expand_path(config["obsidian"]["vault_path"])
        )

    return config


def _deep_merge(base: dict, update: dict) -> None:
    """Deep merge update dict into base dict."""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def get_db_path(config: dict[str, Any] | None = None) -> Path:
    """Get database path from config.

    Precedence: an explicit ``database.path`` config key wins, then
    ``STUDYLOOP_DB``, then the hardcoded default.

    ``STUDYLOOP_DB`` replaces only the hardcoded default so a test run — or a
    subprocess it spawns — cannot fall through to the learner's real
    ``~/.config/studyloop/sessions.db`` and run migrations against it. This
    module resolves the DB independently of ``studyloop.settings``, so it needs
    its own guard; honouring the env var in only one of the two was why the
    real database was still being written during test runs. See
    ``docs/issues/0005-vendor-picker-lists-repo-directories.md``.
    """
    if config is None:
        config = load_config()
    configured = str(config["database"]["path"])
    env_db = os.environ.get("STUDYLOOP_DB")
    if env_db and configured == DEFAULT_CONFIG["database"]["path"]:
        return Path(env_db).expanduser()
    return Path(configured)


def get_archive_path(config: dict[str, Any] | None = None) -> Path:
    """Get archive database path from config."""
    if config is None:
        config = load_config()
    return Path(config["database"]["archive_path"])


def get_backup_dir(config: dict[str, Any] | None = None) -> Path:
    """Get backup directory from config."""
    if config is None:
        config = load_config()
    backup_dir = Path(config["database"]["backup_dir"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def get_log_path(config: dict[str, Any] | None = None) -> Path:
    """Get log file path from config."""
    if config is None:
        config = load_config()
    return Path(config["logging"]["path"])


def get_semantic_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get semantic search configuration.

    Returns:
        Dict with model, fts_weight, semantic_weight, min_content_length, auto_embed
    """
    if config is None:
        config = load_config()
    return config.get("semantic_search", DEFAULT_CONFIG["semantic_search"])


def get_obsidian_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get Obsidian vault-export configuration.

    Returns:
        Dict with export_enabled, vault_path, memory_dir, moc_dir,
        backlinks, granularity, filename_template.
        Falls back to DEFAULT_CONFIG["obsidian"] when the section is absent.
    """
    if config is None:
        config = load_config()
    return config.get("obsidian", DEFAULT_CONFIG["obsidian"])


def get_embedding_model(config: dict[str, Any] | None = None) -> str:
    """Get configured embedding model name.

    Can be overridden with EMBEDDING_MODEL environment variable.
    """
    if v := os.getenv("EMBEDDING_MODEL"):
        return v

    semantic_config = get_semantic_config(config)
    return semantic_config.get("model", "all-mpnet-base-v2")


def ensure_config_dir() -> None:
    """Ensure config directory structure exists."""
    config_dir = get_config_dir()
    config_file = get_config_file()
    env_file = get_env_file()

    config_dir.mkdir(parents=True, exist_ok=True)

    # Create config.yaml if it doesn't exist
    if not config_file.exists():
        with open(config_file, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
        print(f"✅ Created default config: {config_file}")

    # Create .env if it doesn't exist
    if not env_file.exists():
        env_file.touch()
        print(f"✅ Created empty .env: {env_file}")

    # Create backup directory
    backup_dir = expand_path(DEFAULT_CONFIG["database"]["backup_dir"])
    backup_dir.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    # Test the config loader
    ensure_config_dir()
    config = load_config()

    print("\n📋 Configuration Loaded:")
    print(f"  Database: {config['database']['path']}")
    print(f"  Archive: {config['database']['archive_path']}")
    print(f"  Backups: {config['database']['backup_dir']}")
    print(f"  Log: {config['logging']['path']}")
    print(
        f"  Thresholds: {config['thresholds']['warning_mb']}MB / {config['thresholds']['critical_mb']}MB"
    )
    print(f"  TUI Theme: {config['tui']['theme']}")
