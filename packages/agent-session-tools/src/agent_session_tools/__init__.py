"""Agent Session Tools - Session management for AI conversation history.

A toolkit for managing AI conversation sessions with token-efficient context reuse.
Supports Claude Code and Kiro CLI session imports with FTS5 search, multiple export
formats, and database maintenance.
"""

from agent_session_tools.config_loader import (
    get_archive_path,
    get_backup_dir,
    get_db_path,
    get_log_path,
    load_config,
)


def _package_version() -> str:
    """Read the version from installed package metadata.

    Derived rather than hardcoded so it cannot drift from ``pyproject.toml``. It
    previously was hardcoded, which meant the 2.x -> 0.1.0 rebase had to be
    applied in two places in this package but only one in ``studyloop`` — the
    asymmetry that motivated this change. Mirrors ``studyloop.__init__``.
    """
    try:
        from importlib.metadata import version

        return version("agent-session-tools")
    except Exception:
        return "0.0.0+unknown"


__version__ = _package_version()
__author__ = "Andy Taylor"

__all__ = [
    "__version__",
    "load_config",
    "get_db_path",
    "get_archive_path",
    "get_backup_dir",
    "get_log_path",
]
