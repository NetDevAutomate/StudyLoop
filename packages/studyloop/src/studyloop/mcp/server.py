"""FastMCP v1 server for studyloop.

Provides study tools to AI coding assistants via stdio transport.
Register with: ``claude mcp add studyloop-mcp``

The normal server exposes only supported production tools. Exercise tools are
an explicitly gated developer preview: launch ``studyloop-mcp --dev`` (or put
``"--dev"`` in the MCP server's args array) to include them in ``tools/list``.
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from studyloop.db import connect_db
from studyloop.settings import Settings, get_db_path, load_settings

if TYPE_CHECKING:
    import sqlite3


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
    db = connect_db(db_path)

    from studyloop.review_db import ensure_tables

    ensure_tables(db_path)

    settings = load_settings()
    yield AppState(db=db, settings=settings)
    db.close()


def build_mcp(*, dev: bool = False) -> FastMCP:
    """Build a server with the production or explicit developer inventory.

    Args:
        dev: Include developer-preview tools (currently the exercise pipeline).
            False means the tools are absent from discovery, not merely blocked
            when called.
    """
    server = FastMCP("studyloop", lifespan=lifespan)

    from studyloop.mcp.tools import register_tools

    register_tools(server, include_exercises=dev)
    return server


# Import-time server used by unit tests and ordinary `studyloop-mcp`: production
# inventory only. main() builds a separate dev registry only when --dev is set.
mcp = build_mcp()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the StudyLoop MCP server over stdio.")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Expose developer-preview tools (currently: exercises).",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for studyloop-mcp command."""
    args = _parse_args()
    server = build_mcp(dev=True) if args.dev else mcp
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
