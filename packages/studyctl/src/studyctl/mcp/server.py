"""FastMCP v1 server for studyctl.

Provides study tools to AI coding assistants via stdio transport.
Register with: ``claude mcp add studyctl-mcp``
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from studyctl.settings import Settings, get_db_path, load_settings


@dataclass
class AppState:
    """Shared state available to all tools via server context."""

    db: sqlite3.Connection
    settings: Settings


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Initialize shared DB connection and settings for tool lifetime."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")

    from studyctl.review_db import ensure_tables

    ensure_tables(db_path)

    settings = load_settings()
    yield AppState(db=db, settings=settings)
    db.close()


mcp = FastMCP("studyctl", lifespan=lifespan)

# Register tools from tools module
from studyctl.mcp.tools import register_tools  # noqa: E402

register_tools(mcp)


def main() -> None:
    """Entry point for studyctl-mcp command."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
