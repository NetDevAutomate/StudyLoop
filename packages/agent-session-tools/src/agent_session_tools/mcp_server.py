"""MCP server for session-db — universal AI tool integration.

Exposes session database as MCP tools via stdio transport.
Any MCP-compatible AI tool (Claude Code, Kiro, Gemini CLI, OpenCode)
can search, browse, and retrieve session context through this server.

Usage:
    session-db-mcp              # Start the server (stdio)
    fastmcp dev mcp_server.py   # Interactive browser inspector

Registration in AI tool configs:
    {"mcpServers": {"session-db": {"command": "session-db-mcp"}}}

Architecture: This module imports FROM the core query/config layers —
the core layers never import from here (one-way import rule).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

try:
    from fastmcp import FastMCP

    _HAS_FASTMCP = True
except ImportError:
    _HAS_FASTMCP = False


def _get_db_path() -> Path:
    """Resolve database path from config."""
    from agent_session_tools.config_loader import get_db_path, load_config

    return get_db_path(load_config())


def _get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a read-only database connection with Row factory."""
    path = db_path or _get_db_path()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


def _create_server() -> FastMCP:
    """Create and configure the MCP server with all tools."""
    mcp = FastMCP(
        "session-db",
        instructions=(
            "Search and retrieve AI coding sessions across all tools. "
            "Use session_search to find relevant sessions, session_list to browse, "
            "session_context to get token-efficient excerpts for reuse."
        ),
    )

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    def session_search(
        query: str,
        limit: int = 10,
        source: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search sessions by keyword using full-text search.

        Returns matching messages with session context. Use session_context()
        to retrieve full token-efficient excerpts from interesting results.

        Args:
            query: Search terms (supports AND, OR, NOT operators)
            limit: Maximum results to return (default 10)
            source: Filter by tool source (claude, kiro, gemini, opencode, etc.)
            project: Filter by project path substring
        """
        conn = _get_connection()
        try:
            from agent_session_tools.query_utils import escape_fts_query

            fts_query = escape_fts_query(query)

            sql = """
                SELECT s.id as session_id, s.source, s.project_path,
                       s.updated_at, m.role, m.timestamp,
                       substr(m.content, 1, 300) as preview
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                JOIN messages_fts ON messages_fts.rowid = m.rowid
                WHERE messages_fts MATCH ?
            """
            params: list[Any] = [fts_query]

            if source:
                sql += " AND s.source = ?"
                params.append(source)
            if project:
                sql += " AND s.project_path LIKE ?"
                params.append(f"%{project}%")

            sql += " ORDER BY bm25(messages_fts), m.timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    def session_list(
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """List sessions chronologically.

        Returns lightweight summaries (id, date, source, project) without full content.
        Use session_show() or session_context() for details.

        Args:
            limit: Maximum sessions to return (default 20)
            offset: Skip first N sessions for pagination
            source: Filter by tool source
            project: Filter by project path substring
        """
        conn = _get_connection()
        try:
            sql = """
                SELECT id, source, project_path, git_branch,
                       created_at, updated_at, session_type
                FROM sessions WHERE 1=1
            """
            params: list[Any] = []

            if source:
                sql += " AND source = ?"
                params.append(source)
            if project:
                sql += " AND project_path LIKE ?"
                params.append(f"%{project}%")

            sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    def session_show(session_id: str) -> dict[str, Any]:
        """Return full session content including all messages.

        Args:
            session_id: Full or partial session ID (prefix match supported)
        """
        conn = _get_connection()
        try:
            from agent_session_tools.query_utils import resolve_session_id

            resolved_id = resolve_session_id(conn, session_id)

            session = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (resolved_id,)
            ).fetchone()
            if not session:
                return {"error": f"Session not found: {session_id}"}

            messages = conn.execute(
                """SELECT id, role, content, model, timestamp, metadata
                   FROM messages WHERE session_id = ?
                   ORDER BY seq, timestamp""",
                (resolved_id,),
            ).fetchall()

            return {
                "session": _row_to_dict(session),
                "messages": [_row_to_dict(m) for m in messages],
                "message_count": len(messages),
            }
        except ValueError as e:
            return {"error": str(e)}
        finally:
            conn.close()

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    def session_context(
        session_id: str,
        format: str = "compressed",
        max_tokens: int = 4000,
    ) -> str:
        """Return a token-efficient context excerpt from a session.

        Use this to retrieve session content optimized for injection into
        an AI conversation. Much cheaper than session_show() for large sessions.

        Args:
            session_id: Full or partial session ID
            format: Output format — compressed (~35% tokens), summary (~20%),
                    context_only (~25% code blocks only), markdown (full), xml (structured)
            max_tokens: Maximum token budget (default 4000)
        """
        conn = _get_connection()
        try:
            from agent_session_tools.formatters import (
                format_context_only,
                format_markdown,
                format_summary,
                format_xml,
            )
            from agent_session_tools.query_logic import estimate_tokens
            from agent_session_tools.query_utils import resolve_session_id

            resolved_id = resolve_session_id(conn, session_id)

            session = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (resolved_id,)
            ).fetchone()
            if not session:
                return f"Session not found: {session_id}"

            messages = conn.execute(
                """SELECT role, content, model, timestamp, metadata
                   FROM messages WHERE session_id = ?
                   ORDER BY seq, timestamp""",
                (resolved_id,),
            ).fetchall()

            if not messages:
                return f"No messages in session: {session_id}"

            # Filter out tool messages for cleaner context
            filtered = [
                m for m in messages if m["role"] not in ("tool_use", "tool_result")
            ]

            # Format using existing formatters
            session_dict = _row_to_dict(session)
            if format == "markdown":
                output = format_markdown(session_dict, filtered, compressed=False)
            elif format == "xml":
                output = format_xml(session_dict, filtered)
            elif format == "summary":
                output = format_summary(session_dict, filtered)
            elif format == "context_only":
                output = format_context_only(session_dict, filtered)
            else:  # compressed (default)
                output = format_markdown(session_dict, filtered, compressed=True)

            # Apply token limit
            if max_tokens:
                tokens = estimate_tokens(output)
                if tokens > max_tokens:
                    char_limit = max_tokens * 4
                    output = output[:char_limit]
                    output += f"\n\n[Truncated to fit {max_tokens} token budget]"

            return output
        except ValueError as e:
            return f"Error: {e}"
        finally:
            conn.close()

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    def session_stats() -> dict[str, Any]:
        """Return database statistics.

        Includes total sessions, messages, sources breakdown, date range,
        and storage size.
        """
        conn = _get_connection()
        try:
            db_path = _get_db_path()

            total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

            sources = conn.execute(
                "SELECT source, COUNT(*) as count FROM sessions "
                "GROUP BY source ORDER BY count DESC"
            ).fetchall()

            date_range = conn.execute(
                "SELECT MIN(created_at) as earliest, MAX(updated_at) as latest "
                "FROM sessions"
            ).fetchone()

            size_bytes = db_path.stat().st_size if db_path.exists() else 0
            size_mb = round(size_bytes / (1024 * 1024), 2)

            return {
                "total_sessions": total_sessions,
                "total_messages": total_messages,
                "sources": [{"source": r[0], "count": r[1]} for r in sources],
                "date_range": {
                    "earliest": date_range[0] if date_range else None,
                    "latest": date_range[1] if date_range else None,
                },
                "storage": {
                    "bytes": size_bytes,
                    "mb": size_mb,
                },
            }
        finally:
            conn.close()

    @mcp.tool(
        annotations={"destructiveHint": True},
    )
    def session_clean(
        session_id: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Scrub secrets from sessions. Returns findings report.

        Detects API keys, tokens, credentials, and replaces them with
        format-preserving placeholders. Writes audit trail to scrub_log.

        WARNING: When dry_run=False, changes are IRREVERSIBLE.

        Args:
            session_id: Scrub only this session (default: all sessions)
            dry_run: If True (default), report findings without modifying data
        """
        # Use a writable connection for clean
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        try:
            from agent_session_tools.migrations import migrate
            from agent_session_tools.scrubber import ScrubReport, create_scrubber

            migrate(conn)
            scrubber = create_scrubber()
            report = ScrubReport()

            query = (
                "SELECT id, session_id, content FROM messages WHERE content IS NOT NULL"
            )
            params: list[str] = []
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)

            rows = conn.execute(query, params).fetchall()

            updates: list[tuple[str, str]] = []
            audit_entries: list[tuple[str, str, str, str]] = []

            for msg_id, sess_id, content in rows:
                result = scrubber.scrub(content)
                report.add(result)
                if result.scrubbed:
                    updates.append((result.text, msg_id))
                    for finding in result.findings:
                        audit_entries.append(
                            (sess_id, msg_id, finding["type"], finding["placeholder"])
                        )

            response: dict[str, Any] = {
                "messages_scanned": report.messages_scanned,
                "messages_with_secrets": report.messages_with_secrets,
                "total_findings": report.total_findings,
                "findings_by_type": report.findings_by_type,
                "dry_run": dry_run,
            }

            if not dry_run and updates:
                conn.execute("BEGIN")
                conn.executemany(
                    "UPDATE messages SET content = ? WHERE id = ?", updates
                )
                conn.executemany(
                    "INSERT INTO scrub_log "
                    "(session_id, message_id, entity_type, placeholder) "
                    "VALUES (?, ?, ?, ?)",
                    audit_entries,
                )
                conn.commit()
                response["messages_updated"] = len(updates)

            return response
        finally:
            conn.close()

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    def session_hotspots(
        project: str | None = None,
        days: int = 7,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """File access frequency across sessions. Shows which files are most discussed."""
        conn = _get_connection()
        try:
            from agent_session_tools.file_hotspots import get_hotspots

            return get_hotspots(
                conn, project=project, since_days=days or None, limit=limit
            )
        finally:
            conn.close()

    return mcp


# Module-level server instance (created on import for FastMCP CLI compatibility)
if _HAS_FASTMCP:
    mcp = _create_server()


def main():
    """Entry point for session-db-mcp."""
    if not _HAS_FASTMCP:
        print(
            "FastMCP is required for the MCP server.\n"
            "Install with: uv tool install agent-session-tools"
        )
        raise SystemExit(1)

    mcp.run()


if __name__ == "__main__":
    main()
