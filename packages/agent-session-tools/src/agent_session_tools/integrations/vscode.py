"""VSCode integration for session context injection.

Provides functions to export sessions as VSCode snippets and configure workspace settings.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

# Avoid circular import - resolve_session_id will be passed as parameter


def export_session_as_snippet(
    conn: sqlite3.Connection,
    session_id: str,
    workspace_path: str | Path,
    resolve_fn=None,
) -> dict[str, Any]:
    """Export a session as a VSCode snippet.

    Args:
        conn: Database connection
        session_id: Session ID (can be partial)
        workspace_path: Path to VSCode workspace
        resolve_fn: Function to resolve session IDs

    Returns:
        Dict with snippet information
    """
    # Resolve session ID safely (or use as-is if resolve_fn not provided)
    if resolve_fn:
        try:
            resolved_id = resolve_fn(conn, session_id)
        except ValueError as e:
            raise ValueError(f"Session resolution failed: {e}") from e
    else:
        # Try direct lookup first
        session_check = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session_check:
            resolved_id = session_check[0]
        else:
            # Try prefix match
            matches = conn.execute(
                "SELECT id FROM sessions WHERE id LIKE ? LIMIT 1", (f"{session_id}%",)
            ).fetchall()
            if not matches:
                raise ValueError(f"Session not found: {session_id}")
            resolved_id = matches[0][0]

    # Get session info
    session = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (resolved_id,)
    ).fetchone()
    if not session:
        raise ValueError(f"Session not found: {resolved_id}")

    # Get messages ordered by sequence
    messages = conn.execute(
        """
        SELECT role, content, model, timestamp FROM messages
        WHERE session_id = ?
        ORDER BY seq, timestamp
        """,
        (session["id"],),
    ).fetchall()

    if not messages:
        raise ValueError(f"No messages found in session: {resolved_id}")

    # Format the conversation as a readable string
    conversation_parts = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"] or ""

        if role == "user":
            conversation_parts.append(f"## User\n{content}")
        elif role == "assistant":
            conversation_parts.append(f"## Assistant\n{content}")
        else:
            conversation_parts.append(f"## {role}\n{content}")

    conversation_text = "\n\n".join(conversation_parts)

    # Create snippet content
    snippet_content = {
        f"Session Context: {session['project_path'] or 'Unknown'}": {
            "prefix": ["session-context", "agent-context"],
            "body": [
                f"# Session ID: {session['id']}",
                f"# Source: {session['source']}",
                f"# Project: {session['project_path'] or 'Unknown'}",
                f"# Updated: {session['updated_at'] or 'Unknown'}",
                "",
                conversation_text,
                "",
            ],
            "description": f"Agent session context from {session['source']} project {session['project_path'] or 'unknown'}",
        }
    }

    # Write to VSCode snippets file
    workspace = Path(workspace_path)
    vscode_dir = workspace / ".vscode"
    vscode_dir.mkdir(exist_ok=True)

    snippets_file = vscode_dir / "agent-session-contexts.code-snippets"

    # If file exists, load existing snippets and merge
    if snippets_file.exists():
        try:
            with open(snippets_file) as f:
                existing_snippets = json.load(f)
        except (OSError, json.JSONDecodeError):
            existing_snippets = {}
    else:
        existing_snippets = {}

    # Merge new snippet with existing ones
    existing_snippets.update(snippet_content)

    # Write back to file
    with open(snippets_file, "w") as f:
        json.dump(existing_snippets, f, indent=2)

    return {
        "session_id": session["id"],
        "snippets_file": str(snippets_file),
        "snippet_name": f"Session Context: {session['project_path'] or 'Unknown'}",
    }


def create_workspace_settings(
    workspace_path: str | Path, session_db_path: str | Path
) -> str:
    """Create VSCode workspace settings to reference session database.

    Args:
        workspace_path: Path to VSCode workspace
        session_db_path: Path to session database

    Returns:
        Path to settings file
    """
    workspace = Path(workspace_path)
    vscode_dir = workspace / ".vscode"
    vscode_dir.mkdir(exist_ok=True)

    settings_file = vscode_dir / "settings.json"

    # Create relative path for database
    try:
        rel_db_path = Path(session_db_path).relative_to(workspace)
    except ValueError:
        # If not relative, use absolute path
        rel_db_path = Path(session_db_path)

    # Settings to add
    session_settings = {"agentSession.databasePath": str(rel_db_path)}

    # If file exists, load existing settings and merge
    if settings_file.exists():
        try:
            with open(settings_file) as f:
                existing_settings = json.load(f)
        except (OSError, json.JSONDecodeError):
            existing_settings = {}
    else:
        existing_settings = {}

    # Merge settings
    existing_settings.update(session_settings)

    # Write back to file
    with open(settings_file, "w") as f:
        json.dump(existing_settings, f, indent=2)

    return str(settings_file)
