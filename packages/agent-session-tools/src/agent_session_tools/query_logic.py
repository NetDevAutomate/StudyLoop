"""Business logic for querying sessions — no CLI concerns."""

import json
import logging
import sqlite3
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_session_tools.config_loader import get_log_path, load_config
from agent_session_tools.formatters import (
    format_context_only,
    format_markdown,
    format_summary,
    format_xml,
    render_profile,
)
from agent_session_tools.profiles import load_profile
from agent_session_tools.query_utils import (
    build_date_filter,
    check_thresholds,
    escape_fts_query,
    get_db_size,
    resolve_session_id,
)
from agent_session_tools.tokens import (
    TIKTOKEN_AVAILABLE,
    count_tokens,
    truncate_to_tokens,
)

# Initialize Rich console
console = Console()

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


def get_connection(db: Path | None = None) -> sqlite3.Connection:
    """Get database connection."""
    db_path = db if db else DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


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
            print(
                f"[{s['source']}] {session_id} | {s['project_path']} | {s['updated_at']}"
            )


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
    threshold_check = check_thresholds(size_info["mb"], config)

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

        console.print(
            Panel(overview, title="📊 Database Overview", border_style=status_color)
        )

        # Sessions by source
        sessions_table = Table(title="Sessions by Source", box=box.SIMPLE)
        sessions_table.add_column("Source", style="cyan")
        sessions_table.add_column("Count", justify="right", style="green")
        for r in conn.execute(
            "SELECT source, COUNT(*) as cnt FROM sessions GROUP BY source"
        ):
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
        for r in conn.execute(
            "SELECT source, COUNT(*) as cnt FROM sessions GROUP BY source"
        ):
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
    threshold_check = check_thresholds(size_info["mb"], config)

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

        defaults = (
            profile_obj.get("defaults", {}) if isinstance(profile_obj, dict) else {}
        )
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
    session = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (resolved_id,)
    ).fetchone()

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
            print(
                f"❌ Failed to render profile '{profile_obj.get('name', profile)}': {e}"
            )
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
            console.print(
                f"[yellow]⚠️  Output truncated: {tokens} → {max_tokens} tokens[/yellow]"
            )

    print(output)

    # Show stats
    tokens = estimate_tokens(output)
    console.print(
        f"\n[dim]Exported {len(filtered)} messages (~{tokens:,} tokens)[/dim]"
    )


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
    session = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (resolved_id,)
    ).fetchone()

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
                marker in line_lower
                for marker in ["decided", "chosen", "implemented", "using"]
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
    lines.append(
        f"- {len([m for m in messages if '```' in (m['content'] or '')])} code blocks"
    )
    lines.append(
        f"- Session duration: {session.get('created_at', '')} to {session.get('updated_at', '')}"
    )

    content = "\n".join(lines)
    token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    return content + f"\n\n*Context: {token_count} tokens*"
