#!/usr/bin/env python3
"""Query exported sessions from SQLite database — CLI entry points only."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from agent_session_tools.profiles import (
    BUILTIN_PROFILES,
    create_profile,
    delete_profile,
    get_profiles_dir,
    list_profiles,
    load_profile,
)
from agent_session_tools.query_logic import (
    check_size,
    continue_session,
    export_context,
    get_connection,
    get_default_db_path,
    list_sessions,
    search,
    show_session,
    stats,
)

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

# Global database path option
db_option = typer.Option("-d", "--db", help="Database path (default: from config)")


# ==================== Main Commands ====================


@app.command()
def search_cmd(
    query: Annotated[str, typer.Argument(help="Search query")],
    db: Annotated[Path | None, db_option] = None,
    limit: Annotated[int, typer.Option("-n", "--limit", help="Max results")] = 10,
    since: Annotated[
        str | None,
        typer.Option(help="Filter by date (YYYY-MM-DD or last-week/last-month)"),
    ] = None,
    before: Annotated[
        str | None, typer.Option(help="Filter by date (YYYY-MM-DD)")
    ] = None,
    output_format: Annotated[
        str, typer.Option("--output-format", help="Output format")
    ] = "table",
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
            "-s",
            "--source",
            help="Filter by source (claude_code, kiro_cli, gemini_cli, etc.)",
        ),
    ] = None,
    limit: Annotated[int, typer.Option("-n", "--limit", help="Max results")] = 20,
    full: Annotated[
        bool, typer.Option("-f", "--full", help="Show full session IDs")
    ] = False,
    since: Annotated[
        str | None,
        typer.Option(help="Filter by date (YYYY-MM-DD or last-week/last-month)"),
    ] = None,
    before: Annotated[
        str | None, typer.Option(help="Filter by date (YYYY-MM-DD)")
    ] = None,
    output_format: Annotated[
        str, typer.Option("--output-format", help="Output format")
    ] = "table",
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
            "--format",
            help="Output format (markdown, xml, compressed, summary, context-only)",
        ),
    ] = None,
    max_tokens: Annotated[
        int | None, typer.Option("--max-tokens", help="Limit output to N tokens")
    ] = None,
    last: Annotated[
        int | None, typer.Option("--last", help="Only export last N messages")
    ] = None,
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
        str,
        typer.Option("--type", help="Continuation type (resume, branch, summarize)"),
    ] = "resume",
    max_tokens: Annotated[
        int, typer.Option("--max-tokens", help="Max tokens for context")
    ] = 8000,
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
    remove: Annotated[
        list[str] | None, typer.Option("--remove", help="Tags to remove")
    ] = None,
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
                "DELETE FROM session_tags WHERE session_id = ? AND tag = ?",
                (resolved_id, t),
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
            "SELECT notes, updated_at FROM session_notes WHERE session_id = ?",
            (resolved_id,),
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
    db_path = db if db else get_default_db_path()
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
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Overwrite if exists")
    ] = False,
    edit: Annotated[
        bool, typer.Option("--edit", help="Open the profile in $EDITOR after creation")
    ] = False,
) -> None:
    """Create a new custom profile."""
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


# ==================== Main Entry Point ====================


def main() -> int:
    """CLI entry point for session query."""
    app()
    return 0


if __name__ == "__main__":
    app()
