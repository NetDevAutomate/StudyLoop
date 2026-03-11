"""Centralized configuration loader for agent-session-tools.

Loads configuration from ~/.config/studyctl/config.yaml and .env
Provides backwards compatibility with local config.json
"""

import copy
import json
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Default paths
CONFIG_DIR = Path.home() / ".config" / "studyctl"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"
LOCAL_CONFIG = Path(__file__).parent / "config.json"

# Fallback defaults
DEFAULT_CONFIG = {
    "database": {
        "path": str(CONFIG_DIR / "sessions.db"),
        "archive_path": str(CONFIG_DIR / "sessions_archive.db"),
        "backup_dir": str(CONFIG_DIR / "backups"),
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
                "path": host.get("sessions_db", str(CONFIG_DIR / "sessions.db")),
                "ip_address": ip_address,
            }

        return endpoints

    # Legacy format: direct endpoints config
    return config.get("endpoints", {})


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml with fallbacks.

    Priority order:
    1. Environment variables
    2. ~/.config/studyctl/config.yaml
    3. Local config.json (backwards compatibility)
    4. Built-in defaults
    """
    config = copy.deepcopy(DEFAULT_CONFIG)

    # Load .env file if exists
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)

    # Try loading config.yaml (new location first, then legacy)
    config_file = CONFIG_FILE
    legacy_config = Path.home() / ".config" / "agent_session" / "config.yaml"
    if not config_file.exists() and legacy_config.exists():
        config_file = legacy_config

    if config_file.exists():
        try:
            with open(config_file) as f:
                yaml_config = yaml.safe_load(f)
                if yaml_config:
                    # Deep merge with defaults
                    _deep_merge(config, yaml_config)
        except Exception as e:
            print(f"Warning: Failed to load {config_file}: {e}")

    # Backwards compatibility: try local config.json
    elif LOCAL_CONFIG.exists():
        try:
            with open(LOCAL_CONFIG) as f:
                json_config = json.load(f)
                if "thresholds" in json_config:
                    config["thresholds"].update(json_config["thresholds"])
        except Exception as e:
            print(f"Warning: Failed to load {LOCAL_CONFIG}: {e}")

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
    config["logging"]["path"] = str(expand_path(config["logging"]["path"]))

    return config


def _deep_merge(base: dict, update: dict) -> None:
    """Deep merge update dict into base dict."""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def get_db_path(config: dict[str, Any] | None = None) -> Path:
    """Get database path from config."""
    if config is None:
        config = load_config()
    return Path(config["database"]["path"])


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
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Create config.yaml if it doesn't exist
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
        print(f"✅ Created default config: {CONFIG_FILE}")

    # Create .env if it doesn't exist
    if not ENV_FILE.exists():
        ENV_FILE.touch()
        print(f"✅ Created empty .env: {ENV_FILE}")

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
