"""Shared config path resolution for studyctl."""

from __future__ import annotations

from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "studyctl"
DEFAULT_DB = CONFIG_DIR / "sessions.db"


def get_db_path() -> Path:
    """Get sessions.db path from config, or use default."""
    import yaml

    config_file = CONFIG_DIR / "config.yaml"
    if config_file.exists():
        try:
            data = yaml.safe_load(config_file.read_text()) or {}
            db_str = data.get("database", {}).get("path", "")
            if db_str:
                return Path(db_str).expanduser()
        except Exception:
            pass
    return DEFAULT_DB
