"""Agent Session Tools - Session management for AI conversation history.

A toolkit for managing AI conversation sessions with token-efficient context reuse.
Supports Claude Code and Kiro CLI session imports with FTS5 search, multiple export
formats, and database maintenance.
"""

__version__ = "2.0.0"
__author__ = "Andy Taylor"

from agent_session_tools.config_loader import (
    get_archive_path,
    get_backup_dir,
    get_db_path,
    get_log_path,
    load_config,
)

__all__ = [
    "__version__",
    "load_config",
    "get_db_path",
    "get_archive_path",
    "get_backup_dir",
    "get_log_path",
]
