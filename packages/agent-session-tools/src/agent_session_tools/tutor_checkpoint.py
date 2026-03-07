#!/usr/bin/env python3
"""Record study mentoring progress to sessions.db."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from agent_session_tools.config_loader import get_db_path


def record_checkpoint(
    skill: Annotated[
        str, typer.Argument(help="Skill/topic studied (e.g., python-abc-vs-protocol)")
    ],
    notes: Annotated[str, typer.Option(help="Optional notes about the session")] = "",
):
    """Record a code mentoring checkpoint."""
    db_path = get_db_path()
    session_id = f"mentor-{uuid.uuid4().hex}"
    timestamp = datetime.now().isoformat()

    conn = sqlite3.connect(db_path)
    conn.isolation_level = None  # Autocommit mode
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        conn.execute("BEGIN")

        # Create session
        metadata_json = json.dumps({"skill": skill, "type": "code"})

        conn.execute(
            """INSERT INTO sessions (id, source, project_path, created_at, updated_at, metadata, session_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                "study_mentor",
                str(Path.cwd()),
                timestamp,
                timestamp,
                metadata_json,
                "study",
            ),
        )

        # Create checkpoint message
        content = f"Study checkpoint: {skill}"
        if notes:
            content += f"\n\nNotes: {notes}"

        conn.execute(
            """INSERT INTO messages (id, session_id, role, content, timestamp, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                f"msg-{uuid.uuid4().hex}",
                session_id,
                "assistant",
                content,
                timestamp,
                json.dumps({"checkpoint": True}),
            ),
        )

        conn.commit()
        typer.echo(f"✓ Recorded: {skill}")

        # Auto-sync to configured remote endpoints
        try:
            import contextlib
            import subprocess

            from agent_session_tools.config_loader import get_endpoints

            for endpoint_name in get_endpoints():
                with contextlib.suppress(FileNotFoundError, subprocess.TimeoutExpired):
                    subprocess.run(
                        ["session-sync", "push", endpoint_name],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=15,
                    )
        except Exception:
            pass  # config not available or no endpoints
    except sqlite3.IntegrityError as e:
        conn.rollback()
        typer.echo(f"✗ Database constraint error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        conn.rollback()
        typer.echo(f"✗ Unexpected error: {e}", err=True)
        import traceback

        traceback.print_exc()
        raise typer.Exit(1) from None
    finally:
        conn.close()


def main():
    """Entry point for the CLI."""
    typer.run(record_checkpoint)


if __name__ == "__main__":
    main()
