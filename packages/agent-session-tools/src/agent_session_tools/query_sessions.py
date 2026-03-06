#!/usr/bin/env python3
"""Query exported sessions from SQLite database."""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_session_tools.config_loader import get_log_path, load_config
from agent_session_tools.profiles import (
    BUILTIN_PROFILES,
    create_profile,
    delete_profile,
    get_profiles_dir,
    list_profiles,
    load_profile,
)
from agent_session_tools.tokens import TIKTOKEN_AVAILABLE, count_tokens, truncate_to_tokens

# VSCode integration temporarily disabled due to circular import
# from agent_session_tools.integrations.vscode import (
#     create_workspace_settings,
#     export_session_as_snippet,
# )

# Initialize Rich console
console = Console()

# Create Typer app with completion support
app = typer.Typer(
    name="session-query",
    help="Query and search session database.",
    add_completion=True,
    rich_markup_mode="rich",
)

# Sub-app for profiles
profiles_app = typer.Typer(help="Manage export profiles/templates")
app.add_typer(profiles_app, name="profiles")

# Sub-app for vscode integration
vscode_app = typer.Typer(help="VSCode integration commands")
app.add_typer(vscode_app, name="vscode")

# Load configuration
config = load_config()
DB_PATH = Path(config["database"]["path"])

# Setup logging
log_path = get_log_path(config)
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config["logging"]["level"]),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def get_db_size(db_path: Path) -> dict:
    """Get database file size and formatted string."""
    if not db_path.exists():
        return {"bytes": 0, "mb": 0, "formatted": "0 B"}

    size_bytes = db_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)

    # Format for display
    if size_mb < 1:
        formatted = f"{size_bytes / 1024:.2f} KB"
    elif size_mb < 1024:
        formatted = f"{size_mb:.2f} MB"
    else:
        formatted = f"{size_mb / 1024:.2f} GB"

    return {"bytes": size_bytes, "mb": size_mb, "formatted": formatted}


def check_thresholds(size_mb: float) -> dict:
    """Check if database size exceeds thresholds."""
    thresholds = config.get("thresholds", {})
    warning_mb = thresholds.get("warning_mb", 100)
    critical_mb = thresholds.get("critical_mb", 500)

    result = {
        "status": "ok",
        "message": None,
        "warning_mb": warning_mb,
        "critical_mb": critical_mb,
    }

    if size_mb >= critical_mb:
        result["status"] = "critical"
        result["message"] = (
            f"Database size ({size_mb:.2f} MB) exceeds critical threshold ({critical_mb} MB)"
        )
        logger.critical(result["message"])
    elif size_mb >= warning_mb:
        result["status"] = "warning"
        result["message"] = (
            f"Database size ({size_mb:.2f} MB) exceeds warning threshold ({warning_mb} MB)"
        )
        logger.warning(result["message"])
    else:
        result["message"] = f"Database size ({size_mb:.2f} MB) is within acceptable limits"

    return result


def parse_date(date_str: str) -> str:
    """Parse date string to ISO format for SQL queries.

    Supports:
    - ISO format: '2024-01-01' -> '2024-01-01T00:00:00'
    - Relative: 'last-week', 'last-month', 'last-90-days'
    """
    date_str = date_str.lower().strip()

    # Relative dates
    if date_str.startswith("last-"):
        days_map = {
            "last-day": 1,
            "last-week": 7,
            "last-month": 30,
            "last-90-days": 90,
            "last-year": 365,
        }

        if date_str in days_map:
            target_date = datetime.now() - timedelta(days=days_map[date_str])
            return target_date.isoformat()

        # Try parsing 'last-N-days'
        if date_str.startswith("last-") and date_str.endswith("-days"):
            try:
                days = int(date_str[5:-5])  # Extract N from 'last-N-days'
                target_date = datetime.now() - timedelta(days=days)
                return target_date.isoformat()
            except ValueError:
                pass

    # ISO date format (YYYY-MM-DD)
    try:
        parsed = datetime.fromisoformat(date_str)
        return parsed.isoformat()
    except ValueError:
        pass

    # Try parsing as date only
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        return parsed.isoformat()
    except ValueError as err:
        raise ValueError(
            f"Invalid date format: {date_str}. Use YYYY-MM-DD or last-week/last-month/last-N-days"
        ) from err


def build_date_filter(since: str | None = None, before: str | None = None) -> tuple[str, list]:
    """Build SQL WHERE clause for date filtering.

    Returns: (where_clause, params)
    """
    conditions = []
    params = []

    if since:
        since_iso = parse_date(since)
        conditions.append("updated_at >= ?")
        params.append(since_iso)

    if before:
        before_iso = parse_date(before)
        conditions.append("updated_at <= ?")
        params.append(before_iso)

    where_clause = " AND ".join(conditions) if conditions else ""
    return where_clause, params


def escape_fts_query(query: str) -> str:
    """Escape a query string for FTS5 MATCH.

    With porter stemming enabled, we can use simpler queries that match variants.
    For example: "create" will match "created", "creating", "creates".

    Wraps the query in double quotes for phrase search when needed, but allows
    simple word queries to benefit from stemming.
    """
    # Remove any existing quotes
    query = query.strip().strip('"').strip("'")

    # If query contains FTS operators (AND, OR, NOT), use as-is
    if any(op in query.upper() for op in [" AND ", " OR ", " NOT "]):
        return query

    # For simple queries, escape quotes and use as phrase if multi-word
    escaped = query.replace('"', '""')

    # Multi-word queries become phrases
    if " " in escaped:
        return f'"{escaped}"'

    # Single words benefit from stemming without quotes
    return escaped


def resolve_session_id(conn: sqlite3.Connection, user_input: str) -> str:
    """Resolve partial session ID to full ID safely.

    Args:
        conn: Database connection
        user_input: User-provided session ID (partial or full)

    Returns:
        Full session ID

    Raises:
        ValueError: If session not found or ambiguous
    """
    # Try exact match first (fastest)
    exact = conn.execute("SELECT id FROM sessions WHERE id = ?", (user_input,)).fetchone()
    if exact:
        return exact[0]

    # Try prefix match
    matches = conn.execute(
        "SELECT id, source, project_path FROM sessions WHERE id LIKE ? LIMIT 10",
        (f"{user_input}%",),
    ).fetchall()

    if len(matches) == 0:
        raise ValueError(f"No sessions found matching: {user_input}")
    elif len(matches) == 1:
        return matches[0][0]
    else:
        # Multiple matches - show disambiguation
        error_msg = [f"Multiple sessions match '{user_input}':"]
        for i, (session_id, source, project) in enumerate(matches[:5], 1):
            project_short = (project or "Unknown")[:50]
            error_msg.append(f"  {i}. [{source}] {session_id} | {project_short}")

        if len(matches) > 5:
            error_msg.append(f"  ... and {len(matches) - 5} more")

        error_msg.append("\nUse more characters or the full session ID.")
        raise ValueError("\n".join(error_msg))


def search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    since: str | None = None,
    before: str | None = None,
    output_format: str = "table",
) -> None:
    """Full-text search across message content with porter stemming."""
    # Escape the query for FTS5
    fts_query = escape_fts_query(query)

    # Build base query with BM25 ranking for relevance
    base_query = """
        SELECT s.source, s.project_path, s.id as session_id, m.role, m.timestamp,
               substr(m.content, 1, 300) as preview, m.content as full_content,
               bm25(messages_fts) as rank
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        JOIN messages_fts ON messages_fts.rowid = m.rowid
        WHERE messages_fts MATCH ?
    """

    params: list = [fts_query]

    # Add date filtering
    date_filter, date_params = build_date_filter(since, before)
    if date_filter:
        base_query += f" AND ({date_filter.replace('updated_at', 'm.timestamp')})"
        params.extend(date_params)

    # Order by relevance (BM25 score), then timestamp
    base_query += " ORDER BY rank, m.timestamp DESC LIMIT ?"
    params.append(limit)

    results = conn.execute(base_query, params).fetchall()

    if output_format == "json":
        # JSON output
        output = []
        for r in results:
            output.append(
                {
                    "source": r["source"],
                    "project_path": r["project_path"],
                    "session_id": r["session_id"],
                    "role": r["role"],
                    "timestamp": r["timestamp"] or "unknown",
                    "preview": r["preview"],
                    "full_content": r["full_content"],
                }
            )
        print(json.dumps(output, indent=2))

    elif output_format == "markdown":
        # Markdown output
        print("# Search Results\n")
        print(f"**Query:** `{query}`")
        print(f"**Results:** {len(results)}\n")
        print("---\n")

        for i, r in enumerate(results, 1):
            print(f"## Result {i}")
            print(f"- **Source:** {r['source']}")
            print(f"- **Project:** {r['project_path']}")
            print(f"- **Session:** {r['session_id'][:20]}...")
            print(f"- **Role:** {r['role']}")
            print(f"- **Timestamp:** {r['timestamp'] or 'unknown'}")
            print("**Preview:**")
            print(f"```\n{r['preview']}\n```\n")
            print("---\n")

    else:
        # Table output (default)
        for r in results:
            print(f"\n[{r['source']}] {r['project_path']}")
            print(f"  {r['role']} @ {r['timestamp'] or 'unknown'}")
            print(f"  {r['preview']}...")


def list_sessions(
    conn: sqlite3.Connection,
    source: str | None = None,
    limit: int = 20,
    since: str | None = None,
    before: str | None = None,
    output_format: str = "table",
    full_ids: bool = False,
) -> None:
    """List recent sessions."""
    query = "SELECT * FROM sessions WHERE 1=1"
    params: list = []

    if source:
        query += " AND source = ?"
        params.append(source)

    # Add date filtering
    date_filter, date_params = build_date_filter(since, before)
    if date_filter:
        query += f" AND ({date_filter})"
        params.extend(date_params)

    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    results = conn.execute(query, params).fetchall()

    if output_format == "json":
        # JSON output
        output = []
        for s in results:
            output.append(
                {
                    "id": s["id"],
                    "source": s["source"],
                    "project_path": s["project_path"],
                    "git_branch": s["git_branch"],
                    "created_at": s["created_at"],
                    "updated_at": s["updated_at"],
                    "metadata": s["metadata"],
                }
            )
        print(json.dumps(output, indent=2))

    elif output_format == "markdown":
        # Markdown output
        print("# Session List\n")
        print(f"**Total:** {len(results)} sessions\n")
        print("---\n")

        for s in results:
            print(f"## {s['source']} - {s['project_path']}")
            session_id = s["id"] if full_ids else f"{s['id'][:20]}..."
            print(f"- **ID:** `{session_id}`")
            print(f"- **Updated:** {s['updated_at']}")
            if s["git_branch"]:
                print(f"- **Branch:** {s['git_branch']}")
            print()

    else:
        # Table output (default)
        for s in results:
            session_id = s["id"] if full_ids else f"{s['id'][:20]}..."
            print(f"[{s['source']}] {session_id} | {s['project_path']} | {s['updated_at']}")


def show_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Show full session conversation."""
    try:
        resolved_id = resolve_session_id(conn, session_id)
    except ValueError as e:
        print(f"❌ {e}")
        return

    messages = conn.execute(
        """
        SELECT role, content, timestamp FROM messages
        WHERE session_id = ?
        ORDER BY seq, timestamp
    """,
        (resolved_id,),
    ).fetchall()

    if not messages:
        print(f"❌ No messages found in session: {resolved_id}")
        return

    print(f"\n=== Session: {resolved_id} ===")
    for m in messages:
        print(f"\n--- {m['role'].upper()} ({m['timestamp'] or ''}) ---")
        print(m["content"][:2000] if m["content"] else "(empty)")


def stats(conn: sqlite3.Connection, use_rich: bool = False) -> None:
    """Show database statistics."""
    # Database size information
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    size_info = get_db_size(db_path)
    threshold_check = check_thresholds(size_info["mb"])

    if use_rich:
        # Rich TUI output
        # Status color
        status_colors = {"ok": "green", "warning": "yellow", "critical": "red"}
        status_color = status_colors.get(threshold_check["status"], "white")

        # Database overview panel
        overview = Table(show_header=False, box=box.ROUNDED, border_style=status_color)
        overview.add_column("Property", style="cyan")
        overview.add_column("Value", style="white")
        overview.add_row(
            "Size",
            f"[bold]{size_info['formatted']}[/bold] ({size_info['bytes']:,} bytes)",
        )
        overview.add_row(
            "Status",
            f"[bold {status_color}]{threshold_check['status'].upper()}[/bold {status_color}]",
        )
        overview.add_row(
            "Thresholds",
            f"Warning={threshold_check['warning_mb']}MB, Critical={threshold_check['critical_mb']}MB",
        )
        if threshold_check["status"] != "ok":
            overview.add_row(
                "Alert",
                f"[{status_color}]⚠️  {threshold_check['message']}[/{status_color}]",
            )

        console.print(Panel(overview, title="📊 Database Overview", border_style=status_color))

        # Sessions by source
        sessions_table = Table(title="Sessions by Source", box=box.SIMPLE)
        sessions_table.add_column("Source", style="cyan")
        sessions_table.add_column("Count", justify="right", style="green")
        for r in conn.execute("SELECT source, COUNT(*) as cnt FROM sessions GROUP BY source"):
            sessions_table.add_row(r["source"], str(r["cnt"]))
        console.print(sessions_table)

        # Messages by role
        messages_table = Table(title="Messages by Role", box=box.SIMPLE)
        messages_table.add_column("Role", style="cyan")
        messages_table.add_column("Count", justify="right", style="green")
        for r in conn.execute(
            "SELECT role, COUNT(*) as cnt FROM messages GROUP BY role ORDER BY cnt DESC"
        ):
            messages_table.add_row(r["role"], str(r["cnt"]))
        console.print(messages_table)

        # Top projects
        projects_table = Table(title="Top Projects by Message Count", box=box.SIMPLE)
        projects_table.add_column("Project Path", style="cyan", no_wrap=False)
        projects_table.add_column("Messages", justify="right", style="green")
        for r in conn.execute(
            """
            SELECT s.project_path, COUNT(*) as cnt
            FROM messages m JOIN sessions s ON m.session_id = s.id
            GROUP BY s.project_path ORDER BY cnt DESC LIMIT 10
        """
        ):
            projects_table.add_row(r["project_path"], str(r["cnt"]))
        console.print(projects_table)

    else:
        # Original plain text output
        print(f"\n{'=' * 50}")
        print("DATABASE OVERVIEW")
        print(f"{'=' * 50}")
        print(f"Size: {size_info['formatted']} ({size_info['bytes']:,} bytes)")
        print(f"Status: {threshold_check['status'].upper()}")
        print(
            f"Thresholds: Warning={threshold_check['warning_mb']}MB, "
            f"Critical={threshold_check['critical_mb']}MB"
        )
        if threshold_check["status"] != "ok":
            print(f"⚠️  {threshold_check['message']}")

        print(f"\n{'=' * 50}")
        print("SESSIONS BY SOURCE")
        print(f"{'=' * 50}")
        for r in conn.execute("SELECT source, COUNT(*) as cnt FROM sessions GROUP BY source"):
            print(f"  {r['source']}: {r['cnt']}")

        print(f"\n{'=' * 50}")
        print("MESSAGES BY ROLE")
        print(f"{'=' * 50}")
        for r in conn.execute(
            "SELECT role, COUNT(*) as cnt FROM messages GROUP BY role ORDER BY cnt DESC"
        ):
            print(f"  {r['role']}: {r['cnt']}")

        print(f"\n{'=' * 50}")
        print("TOP PROJECTS BY MESSAGE COUNT")
        print(f"{'=' * 50}")
        for r in conn.execute(
            """
            SELECT s.project_path, COUNT(*) as cnt
            FROM messages m JOIN sessions s ON m.session_id = s.id
            GROUP BY s.project_path ORDER BY cnt DESC LIMIT 10
        """
        ):
            print(f"  {r['project_path']}: {r['cnt']}")
        print()


def check_size(db_path: Path) -> int:
    """Check database size against thresholds."""
    size_info = get_db_size(db_path)
    threshold_check = check_thresholds(size_info["mb"])

    print("\nDatabase Size Check")
    print("=" * 50)
    print(f"File: {db_path}")
    print(f"Size: {size_info['formatted']} ({size_info['mb']:.2f} MB)")
    print(f"Status: {threshold_check['status'].upper()}")
    print("\nThresholds:")
    print(f"  Warning:  {threshold_check['warning_mb']} MB")
    print(f"  Critical: {threshold_check['critical_mb']} MB")
    print(f"\n{threshold_check['message']}")

    # Return exit code based on status
    return 0 if threshold_check["status"] == "ok" else 1


def estimate_tokens(text: str, accurate: bool = True) -> int:
    """Count tokens in text.

    Uses tiktoken for accurate counting if available, otherwise estimates.
    """
    return count_tokens(text, accurate=accurate)


def export_context(
    conn: sqlite3.Connection,
    session_id: str,
    format_type: str = "markdown",
    max_tokens: int | None = None,
    last_n: int | None = None,
    include_tools: bool = False,
    only_code: bool = False,
    profile: str | None = None,
) -> None:
    """Export session context in optimized format for reuse."""
    # Resolve session ID safely
    try:
        resolved_id = resolve_session_id(conn, session_id)
    except ValueError as e:
        print(f"❌ {e}")
        return

    # Load profile (optional) and apply defaults
    profile_obj: dict | None = None
    if profile:
        try:
            profile_obj = load_profile(profile)
        except Exception as e:
            print(f"❌ Failed to load profile '{profile}': {e}")
            return

        defaults = profile_obj.get("defaults", {}) if isinstance(profile_obj, dict) else {}
        if max_tokens is None:
            max_tokens = defaults.get("max_tokens")
        if last_n is None:
            last_n = defaults.get("last_n")
        include_tools = bool(include_tools or defaults.get("include_tools", False))
        only_code = bool(only_code or defaults.get("only_code", False))

        # Profile format overrides unless explicitly provided by caller
        if not format_type or format_type == "markdown":
            format_type = str(profile_obj.get("format") or "template")

    # Backwards-compatible default when no profile passed and format_type is unset/None
    if not format_type:
        format_type = "compressed"

    # Get session info
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (resolved_id,)).fetchone()

    if not session:
        print(f"❌ Session not found: {resolved_id}")
        return

    # Get messages
    if last_n:
        # Use subquery to get last N messages, then re-order chronologically
        query = """
            SELECT role, content, model, timestamp, metadata FROM (
                SELECT role, content, model, timestamp, metadata FROM messages
                WHERE session_id = ?
                ORDER BY timestamp DESC, seq DESC
                LIMIT ?
            )
            ORDER BY timestamp ASC, seq ASC
        """
        messages = conn.execute(query, (session["id"], last_n)).fetchall()
    else:
        query = """
            SELECT role, content, model, timestamp, metadata FROM messages
            WHERE session_id = ?
            ORDER BY timestamp, seq
        """
        messages = conn.execute(query, (session["id"],)).fetchall()

    if not messages:
        print(f"❌ No messages found in session: {session_id}")
        return

    # Filter messages by role
    filtered = []
    for msg in messages:
        # Skip tool results unless explicitly requested
        if msg["role"] in ["tool_use", "tool_result"] and not include_tools:
            continue
        # Skip if only_code and message has no code
        if only_code and msg["content"] and "```" not in msg["content"]:
            continue
        filtered.append(msg)

    # Export in requested format (profiles can render full template output)
    if profile_obj and (format_type == "template" or profile_obj.get("template")):
        try:
            output = render_profile(profile_obj, session, filtered)
        except Exception as e:
            print(f"❌ Failed to render profile '{profile_obj.get('name', profile)}': {e}")
            return
    elif format_type == "markdown":
        output = format_markdown(session, filtered, compressed=False)
    elif format_type == "xml":
        output = format_xml(session, filtered)
    elif format_type == "compressed":
        output = format_markdown(session, filtered, compressed=True)
    elif format_type == "summary":
        output = format_summary(session, filtered)
    elif format_type == "context-only":
        output = format_context_only(session, filtered)
    else:
        output = format_markdown(session, filtered, compressed=True)

    # Apply token limit if specified
    if max_tokens:
        tokens = estimate_tokens(output)
        if tokens > max_tokens:
            # Trim output to fit token budget
            char_limit = max_tokens * 4
            output = output[:char_limit]
            output += f"\n\n*[Truncated to fit {max_tokens} token budget]*"
            console.print(f"[yellow]⚠️  Output truncated: {tokens} → {max_tokens} tokens[/yellow]")

    print(output)

    # Show stats
    tokens = estimate_tokens(output)
    console.print(f"\n[dim]Exported {len(filtered)} messages (~{tokens:,} tokens)[/dim]")


def render_profile(profile: dict, session: dict, messages: list) -> str:
    """Render session using profile template with placeholder substitution.

    Supported placeholders:
    - {session_id}, {project_path}, {source}, {updated_at}
    - {messages} - formatted message content
    - {message_count} - number of messages
    """
    template = profile.get("template", "")
    if not template:
        # Fall back to compressed markdown if no template
        return format_markdown(session, messages, compressed=True)

    # Format messages for insertion
    msg_lines = []
    for msg in messages:
        role = msg["role"].upper()
        content = msg.get("content", "")
        if content:
            msg_lines.append(f"**{role}**: {content}")

    # Substitute placeholders
    output = template.format(
        session_id=session.get("id", ""),
        project_path=session.get("project_path", ""),
        source=session.get("source", ""),
        updated_at=session.get("updated_at", ""),
        messages="\n\n".join(msg_lines),
        message_count=len(messages),
    )
    return output


def format_markdown(session: dict, messages: list, compressed: bool = False) -> str:
    """Format session as Markdown."""
    lines = []

    if not compressed:
        lines.append(f"# Session Context: {session['project_path'] or 'Unknown'}")
        lines.append(f"**Session ID:** {session['id'][:16]}...")
        lines.append(f"**Updated:** {session['updated_at'] or 'Unknown'}")
        lines.append(f"**Source:** {session['source']}")
        lines.append("")
    else:
        lines.append(f"# Context: {session['project_path'] or 'Session'}")
        lines.append("")

    for msg in messages:
        role = msg["role"]
        content = msg["content"] or ""

        if role == "user":
            lines.append(f"**Q:** {content}")
            lines.append("")
        elif role == "assistant":
            if compressed:
                # Compress long responses
                if len(content) > 1000 and "```" not in content:
                    # Extract key points (first few sentences)
                    sentences = content.split(". ")[:3]
                    content = ". ".join(sentences) + "..."
                lines.append(f"**A:** {content}")
            else:
                lines.append("### Assistant")
                lines.append(content)
            lines.append("")
        elif role in ["tool_use", "tool_result"]:
            # Only included if --include-tools flag set
            lines.append(f"*[{role}]*")
            lines.append("")

    return "\n".join(lines)


def format_xml(session: dict, messages: list) -> str:
    """Format session as Claude-optimized XML."""
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<session id="{session["id"][:16]}" project="{session["project_path"] or "unknown"}">'
    )
    lines.append("  <metadata>")
    lines.append(f"    <updated>{session['updated_at']}</updated>")
    lines.append(f"    <source>{session['source']}</source>")
    lines.append("  </metadata>")
    lines.append("  <conversation>")

    for msg in messages:
        role = msg["role"]
        content = msg["content"] or ""

        # Escape XML special characters
        content = content.replace("&", "&").replace("<", "<").replace(">", ">")

        if role == "user":
            lines.append('    <turn role="user">')
            lines.append(f"      <content>{content}</content>")
            lines.append("    </turn>")
        elif role == "assistant":
            lines.append('    <turn role="assistant">')
            # Extract code blocks
            if "```" in content:
                parts = content.split("```")
                for i, part in enumerate(parts):
                    if i % 2 == 0:
                        if part.strip():
                            lines.append(f"      <content>{part.strip()}</content>")
                    else:
                        # Code block
                        code_lines = part.split("\n", 1)
                        lang = code_lines[0] if code_lines else ""
                        code = code_lines[1] if len(code_lines) > 1 else ""
                        lines.append(f'      <code language="{lang}">')
                        lines.append(f"{code}")
                        lines.append("      </code>")
            else:
                lines.append(f"      <content>{content}</content>")
            lines.append("    </turn>")

    lines.append("  </conversation>")
    lines.append("</session>")

    return "\n".join(lines)


def format_summary(session: dict, messages: list) -> str:
    """Format as concise summary with key points."""
    lines = []
    lines.append(f"# Session Summary: {session['project_path'] or 'Unknown'}")
    lines.append("")

    # Extract key information
    user_msgs = [m for m in messages if m["role"] == "user"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]

    # Main topic (first user message)
    if user_msgs:
        lines.append(f"**Topic:** {user_msgs[0]['content'][:200]}...")
        lines.append("")

    # Extract code blocks from all messages
    code_blocks = []
    for msg in assistant_msgs:
        if msg["content"] and "```" in msg["content"]:
            # Extract code
            parts = msg["content"].split("```")
            for i in range(1, len(parts), 2):
                code_blocks.append(parts[i])

    if code_blocks:
        lines.append("## Key Code")
        for block in code_blocks[:3]:  # Limit to 3 blocks
            lines.append(f"```{block}```")
            lines.append("")

    # Key points (from assistant messages)
    lines.append("## Key Points")
    for i, msg in enumerate(assistant_msgs[:5], 1):  # Limit to 5 messages
        if msg["content"]:
            # Extract first sentence or two
            content = msg["content"][:300]
            if "```" in content:
                content = content.split("```")[0]  # Text before code
            lines.append(f"{i}. {content.strip()}")
    lines.append("")

    return "\n".join(lines)


def format_context_only(session: dict, messages: list) -> str:
    """Format as context-only (code + technical info)."""
    lines = []
    lines.append(f"# Technical Context: {session['project_path'] or 'Project'}")
    lines.append("")

    # Extract all code blocks
    lines.append("## Code Implementations")
    lines.append("")

    for msg in messages:
        if msg["content"] and "```" in msg["content"]:
            # Extract code blocks
            parts = msg["content"].split("```")
            for i in range(1, len(parts), 2):
                lines.append(f"```{parts[i]}```")
                lines.append("")

    return "\n".join(lines)


def continue_session(
    conn: sqlite3.Connection,
    session_id: str,
    continuation_type: str = "resume",
    max_tokens: int = 8000,
    copy_to_clipboard: bool = False,
) -> None:
    """Generate smart continuation context for resuming work."""
    # Resolve session ID safely
    try:
        resolved_id = resolve_session_id(conn, session_id)
    except ValueError as e:
        print(f"❌ {e}")
        return

    # Get session info
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (resolved_id,)).fetchone()

    if not session:
        print(f"❌ Session not found: {resolved_id}")
        return

    # Get messages (use seq for ordering when timestamps missing)
    messages = conn.execute(
        """
        SELECT * FROM messages
        WHERE session_id = ?
        ORDER BY COALESCE(timestamp, ''), seq
    """,
        (session["id"],),
    ).fetchall()

    if not messages:
        print(f"❌ No messages found in session: {session['id']}")
        return

    if continuation_type == "resume":
        context = _generate_resume_context(session, messages, max_tokens)
    elif continuation_type == "branch":
        context = _generate_branch_context(session, messages, max_tokens)
    elif continuation_type == "summarize":
        context = _generate_summary_context(session, messages, max_tokens)
    else:
        context = _generate_resume_context(session, messages, max_tokens)

    if copy_to_clipboard:
        try:
            import pyperclip

            pyperclip.copy(context)
            print("📋 Context copied to clipboard")
        except ImportError:
            print("⚠️  Install pyperclip for clipboard support: uv add pyperclip")
            print("\nContext (copy manually):")

    print(context)


def _generate_resume_context(session: dict, messages: list, max_tokens: int) -> str:
    """Generate context for resuming where conversation left off."""
    lines = []
    lines.append(f"# Resume Session: {session['project_path'] or 'Unknown'}")
    lines.append("")

    # Get last user request and assistant response
    user_msgs = [m for m in messages if m["role"] == "user"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]

    if user_msgs:
        lines.append("## Last Request")
        lines.append(f"**User:** {user_msgs[-1]['content'][:500]}")
        lines.append("")

    if assistant_msgs:
        lines.append("## Last Response")
        lines.append(f"**Assistant:** {assistant_msgs[-1]['content'][:800]}")
        lines.append("")

    # Extract key artifacts (code, decisions, TODOs)
    code_blocks = []
    todos = []
    decisions = []

    for msg in messages:
        content = msg["content"] or ""

        # Extract code blocks
        if "```" in content:
            parts = content.split("```")
            for i in range(1, len(parts), 2):
                if parts[i].strip():
                    code_blocks.append(parts[i].strip()[:300])

        # Extract TODOs and decisions
        for line in content.split("\n"):
            line_lower = line.lower().strip()
            if any(marker in line_lower for marker in ["todo", "fixme", "next steps"]):
                todos.append(line.strip()[:200])
            elif any(
                marker in line_lower for marker in ["decided", "chosen", "implemented", "using"]
            ):
                decisions.append(line.strip()[:200])

    # Add key context sections
    if code_blocks:
        lines.append("## Key Code")
        for block in code_blocks[-3:]:  # Last 3 code blocks
            lines.append(f"```\n{block}\n```")
        lines.append("")

    if decisions:
        lines.append("## Key Decisions")
        for decision in decisions[-3:]:
            lines.append(f"- {decision}")
        lines.append("")

    if todos:
        lines.append("## Outstanding Items")
        for todo in todos[-3:]:
            lines.append(f"- {todo}")
        lines.append("")

    lines.append("## Continue From Here")
    lines.append("*Ready to continue the conversation with full context above.*")

    # Truncate if needed (use accurate token counting)
    content = "\n".join(lines)
    token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    if token_count > max_tokens:
        content = truncate_to_tokens(
            content, max_tokens, strategy="middle", accurate=TIKTOKEN_AVAILABLE
        )
        token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    result_lines = list(content.split("\n"))
    result_lines.append("")
    result_lines.append(f"*Context: {token_count} tokens*")

    return "\n".join(result_lines)


def _generate_branch_context(session: dict, messages: list, max_tokens: int) -> str:
    """Generate context for branching in a new direction."""
    lines = []
    lines.append(f"# Branch Session: {session['project_path'] or 'Unknown'}")
    lines.append("")
    lines.append("## Previous Work Summary")

    # Summarize what was accomplished
    key_points = []
    for msg in messages:
        if msg["role"] == "assistant" and msg["content"]:
            # Extract first sentence as key point
            first_sentence = msg["content"].split(".")[0].strip()[:150]
            if first_sentence and len(first_sentence) > 20:
                key_points.append(first_sentence)

    for point in key_points[-5:]:  # Last 5 key points
        lines.append(f"- {point}")

    lines.append("")
    lines.append("## Branch Point")
    lines.append("*Starting new direction based on previous work above.*")

    content = "\n".join(lines)
    token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    if token_count > max_tokens:
        content = truncate_to_tokens(content, max_tokens, accurate=TIKTOKEN_AVAILABLE)
        token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    return content + f"\n\n*Context: {token_count} tokens*"


def _generate_summary_context(session: dict, messages: list, max_tokens: int) -> str:
    """Generate high-level summary for fresh start."""
    lines = []
    lines.append(f"# Session Summary: {session['project_path'] or 'Unknown'}")
    lines.append("")

    user_msgs = [m for m in messages if m["role"] == "user"]
    if user_msgs:
        lines.append(f"**Goal:** {user_msgs[0]['content'][:300]}")
        lines.append("")

    # Count outcomes
    lines.append("## Outcomes")
    lines.append(f"- {len(messages)} total messages")
    lines.append(f"- {len([m for m in messages if '```' in (m['content'] or '')])} code blocks")
    lines.append(
        f"- Session duration: {session.get('created_at', '')} to {session.get('updated_at', '')}"
    )

    content = "\n".join(lines)
    token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    return content + f"\n\n*Context: {token_count} tokens*"


# Global database path option
db_option = typer.Option("-d", "--db", help="Database path (default: from config)")


def get_connection(db: Path | None = None) -> sqlite3.Connection:
    """Get database connection."""
    db_path = db if db else DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ==================== Main Commands ====================


@app.command()
def search_cmd(
    query: Annotated[str, typer.Argument(help="Search query")],
    db: Annotated[Path | None, db_option] = None,
    limit: Annotated[int, typer.Option("-n", "--limit", help="Max results")] = 10,
    since: Annotated[
        str | None, typer.Option(help="Filter by date (YYYY-MM-DD or last-week/last-month)")
    ] = None,
    before: Annotated[str | None, typer.Option(help="Filter by date (YYYY-MM-DD)")] = None,
    output_format: Annotated[str, typer.Option("--output-format", help="Output format")] = "table",
) -> None:
    """Full-text search across message content."""
    conn = get_connection(db)
    search(conn, query, limit, since, before, output_format)
    conn.close()


@app.command("list")
def list_cmd(
    db: Annotated[Path | None, db_option] = None,
    source: Annotated[
        str | None,
        typer.Option(
            "-s", "--source", help="Filter by source (claude_code, kiro_cli, gemini_cli, etc.)"
        ),
    ] = None,
    limit: Annotated[int, typer.Option("-n", "--limit", help="Max results")] = 20,
    full: Annotated[bool, typer.Option("-f", "--full", help="Show full session IDs")] = False,
    since: Annotated[
        str | None, typer.Option(help="Filter by date (YYYY-MM-DD or last-week/last-month)")
    ] = None,
    before: Annotated[str | None, typer.Option(help="Filter by date (YYYY-MM-DD)")] = None,
    output_format: Annotated[str, typer.Option("--output-format", help="Output format")] = "table",
) -> None:
    """List recent sessions."""
    conn = get_connection(db)
    list_sessions(conn, source, limit, since, before, output_format, full)
    conn.close()


@app.command()
def show(
    session_id: Annotated[str, typer.Argument(help="Session ID to show")],
    db: Annotated[Path | None, db_option] = None,
) -> None:
    """Show full session conversation."""
    conn = get_connection(db)
    show_session(conn, session_id)
    conn.close()


@app.command()
def stats_cmd(
    db: Annotated[Path | None, db_option] = None,
    tui: Annotated[bool, typer.Option("--tui", help="Use Rich TUI formatting")] = False,
) -> None:
    """Show database statistics."""
    conn = get_connection(db)
    stats(conn, tui)
    conn.close()


@app.command()
def context(
    session_id: Annotated[str, typer.Argument(help="Session ID to export")],
    db: Annotated[Path | None, db_option] = None,
    profile: Annotated[
        str | None,
        typer.Option(help="Use an export profile (e.g., quick-resume, code-focused)"),
    ] = None,
    format_type: Annotated[
        str | None,
        typer.Option(
            "--format", help="Output format (markdown, xml, compressed, summary, context-only)"
        ),
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Limit output to N tokens")
    ] = None,
    last: Annotated[int | None, typer.Option("--last", help="Only export last N messages")] = None,
    include_tools: Annotated[
        bool, typer.Option("--include-tools", help="Include tool use/results")
    ] = False,
    only_code: Annotated[
        bool, typer.Option("--only-code", help="Only messages with code blocks")
    ] = False,
) -> None:
    """Export session context for reuse."""
    conn = get_connection(db)
    export_context(
        conn,
        session_id,
        format_type or "compressed",
        max_tokens,
        last,
        include_tools,
        only_code,
        profile,
    )
    conn.close()


@app.command("continue")
def continue_cmd(
    session_id: Annotated[str, typer.Argument(help="Session ID to continue")],
    db: Annotated[Path | None, db_option] = None,
    continuation_type: Annotated[
        str, typer.Option("--type", help="Continuation type (resume, branch, summarize)")
    ] = "resume",
    max_tokens: Annotated[int, typer.Option("--max-tokens", help="Max tokens for context")] = 8000,
    copy: Annotated[
        bool, typer.Option("--copy", help="Copy to clipboard (requires pyperclip)")
    ] = False,
) -> None:
    """Generate continuation context for resuming work."""
    conn = get_connection(db)
    continue_session(conn, session_id, continuation_type, max_tokens, copy)
    conn.close()


@app.command()
def tag(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    db: Annotated[Path | None, db_option] = None,
    add: Annotated[list[str] | None, typer.Option("--add", help="Tags to add")] = None,
    remove: Annotated[list[str] | None, typer.Option("--remove", help="Tags to remove")] = None,
) -> None:
    """Manage session tags."""
    conn = get_connection(db)

    # Resolve session ID safely
    session = conn.execute(
        "SELECT id FROM sessions WHERE id = ? OR id LIKE ? LIMIT 1",
        (session_id, f"%{session_id}%"),
    ).fetchone()

    if not session:
        print(f"❌ Session not found: {session_id}")
        raise typer.Exit(1)

    resolved_id = session[0]

    if add:
        for t in add:
            conn.execute(
                "INSERT OR IGNORE INTO session_tags (session_id, tag) VALUES (?, ?)",
                (resolved_id, t),
            )
        print(f"✅ Added tags to {resolved_id[:20]}...: {', '.join(add)}")

    if remove:
        for t in remove:
            conn.execute(
                "DELETE FROM session_tags WHERE session_id = ? AND tag = ?", (resolved_id, t)
            )
        print(f"✅ Removed tags from {resolved_id[:20]}...: {', '.join(remove)}")

    # Always show current tags
    current_tags = conn.execute(
        "SELECT tag FROM session_tags WHERE session_id = ? ORDER BY tag", (resolved_id,)
    ).fetchall()

    if current_tags:
        print(f"\n🏷️  Current tags: {', '.join(t[0] for t in current_tags)}")
    else:
        print(f"\n🏷️  No tags set for {resolved_id[:20]}...")

    conn.commit()
    conn.close()


@app.command()
def note(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    db: Annotated[Path | None, db_option] = None,
    text: Annotated[str | None, typer.Option("--text", help="Note text")] = None,
    edit: Annotated[bool, typer.Option("--edit", help="Edit note in $EDITOR")] = False,
) -> None:
    """Manage session notes."""
    import os
    import subprocess
    import tempfile

    conn = get_connection(db)

    # Resolve session ID safely
    session = conn.execute(
        "SELECT id FROM sessions WHERE id = ? OR id LIKE ? LIMIT 1",
        (session_id, f"%{session_id}%"),
    ).fetchone()

    if not session:
        print(f"❌ Session not found: {session_id}")
        raise typer.Exit(1)

    resolved_id = session[0]

    if text:
        conn.execute(
            """
            INSERT OR REPLACE INTO session_notes (session_id, notes, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """,
            (resolved_id, text),
        )
        print(f"✅ Note saved for {resolved_id[:20]}...")

    elif edit:
        current_note = conn.execute(
            "SELECT notes FROM session_notes WHERE session_id = ?", (resolved_id,)
        ).fetchone()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
            if current_note:
                tmp.write(current_note[0])
            tmp.flush()

            editor = os.environ.get("EDITOR", "nano")
            try:
                subprocess.run([editor, tmp.name], check=True)

                with open(tmp.name) as f:
                    new_content = f.read().strip()

                if new_content:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO session_notes (session_id, notes, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """,
                        (resolved_id, new_content),
                    )
                    print(f"✅ Note updated for {resolved_id[:20]}...")

            except subprocess.CalledProcessError:
                print("❌ Editor cancelled or failed")
            finally:
                os.unlink(tmp.name)

    else:
        note_row = conn.execute(
            "SELECT notes, updated_at FROM session_notes WHERE session_id = ?", (resolved_id,)
        ).fetchone()

        if note_row:
            print(f"\n📝 Note for {resolved_id[:20]}... (updated {note_row[1]}):")
            print(f"{note_row[0]}")
        else:
            print(f"\n📝 No note found for {resolved_id[:20]}...")

    conn.commit()
    conn.close()


@app.command("check-size")
def check_size_cmd(
    db: Annotated[Path | None, db_option] = None,
) -> None:
    """Check database size against thresholds."""
    db_path = db if db else DB_PATH
    exit_code = check_size(db_path)
    raise typer.Exit(exit_code)


# ==================== Profiles Sub-App ====================


@profiles_app.command("list")
def profiles_list() -> None:
    """List available profiles."""
    items = list_profiles()
    if not items:
        print("No profiles found.")
        return

    print("Available profiles:")
    for p in items:
        name = p.get("name", "")
        origin = p.get("origin", "unknown")
        desc = p.get("description", "")
        suffix = f" ({origin})"
        print(f"  - {name}{suffix}: {desc}")


@profiles_app.command()
def show_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
) -> None:
    """Show a profile (expanded)."""
    try:
        p = load_profile(name)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(1) from None

    print(f"Name: {p.get('name')}")
    print(f"Description: {p.get('description', '')}")
    print(f"Format: {p.get('format', 'template')}")
    print(f"Defaults: {json.dumps(p.get('defaults', {}), indent=2)}")
    print("\nTemplate:\n")
    print(p.get("template", ""))


@profiles_app.command()
def create(
    name: Annotated[str, typer.Argument(help="New profile name")],
    from_profile: Annotated[
        str | None, typer.Option("--from", help="Base profile to copy from")
    ] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Overwrite if exists")] = False,
    edit: Annotated[
        bool, typer.Option("--edit", help="Open the profile in $EDITOR after creation")
    ] = False,
) -> None:
    """Create a new custom profile."""
    import os
    import subprocess

    try:
        path = create_profile(name, base=from_profile, overwrite=overwrite)
    except Exception as e:
        print(f"❌ Failed to create profile: {e}")
        raise typer.Exit(1) from None

    print(f"✅ Created profile: {path}")

    if edit:
        editor = os.environ.get("EDITOR", "nano")
        try:
            subprocess.run([editor, str(path)], check=True)
        except subprocess.CalledProcessError:
            print("❌ Editor cancelled or failed")
            raise typer.Exit(1) from None


@profiles_app.command()
def delete(
    name: Annotated[str, typer.Argument(help="Profile name")],
) -> None:
    """Delete a custom profile."""
    try:
        delete_profile(name)
    except Exception as e:
        print(f"❌ Failed to delete profile: {e}")
        raise typer.Exit(1) from None
    print(f"✅ Deleted profile: {name}")


@profiles_app.command()
def edit_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
) -> None:
    """Edit an existing custom profile in $EDITOR."""
    import os
    import subprocess

    if name in BUILTIN_PROFILES:
        print(f"❌ Cannot edit built-in profile '{name}'. Create a custom one instead:")
        print(f"   session-query profiles create {name}-custom --from {name} --edit")
        raise typer.Exit(1)

    path = get_profiles_dir() / f"{name}.yaml"
    if not path.exists():
        print(f"❌ Profile not found: {name}")
        print("Create it first:")
        print(f"   session-query profiles create {name} --edit")
        raise typer.Exit(1)

    editor = os.environ.get("EDITOR", "nano")
    try:
        subprocess.run([editor, str(path)], check=True)
    except subprocess.CalledProcessError:
        print("❌ Editor cancelled or failed")
        raise typer.Exit(1) from None

    print(f"✅ Updated profile: {path}")


@profiles_app.command()
def path() -> None:
    """Print the profiles directory path."""
    print(str(get_profiles_dir()))


# ==================== VSCode Sub-App ====================


@vscode_app.command()
def snippet(
    session_id: Annotated[str, typer.Argument(help="Session ID to export")],
    workspace: Annotated[Path, typer.Option("-w", "--workspace", help="VSCode workspace path")],
    db: Annotated[Path | None, db_option] = None,
) -> None:
    """Export session as VSCode snippet."""
    # VSCode integration temporarily disabled
    print("❌ VSCode integration is temporarily disabled due to circular import")
    raise typer.Exit(1)


@vscode_app.command()
def setup(
    workspace: Annotated[Path, typer.Option("-w", "--workspace", help="VSCode workspace path")],
    db_path: Annotated[Path | None, typer.Option("--db-path", help="Session database path")] = None,
    db: Annotated[Path | None, db_option] = None,
) -> None:
    """Setup VSCode workspace for session integration."""
    # VSCode integration temporarily disabled
    print("❌ VSCode integration is temporarily disabled due to circular import")
    raise typer.Exit(1)


# ==================== Main Entry Point ====================


def main() -> int:
    """CLI entry point for session query."""
    app()
    return 0


if __name__ == "__main__":
    app()
