#!/usr/bin/env python3
"""Database maintenance utilities for session database.

This tool provides commands for database optimization, archiving,
schema inspection, and maintenance operations.
"""

import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from agent_session_tools.config_loader import (
    get_backup_dir,
    get_db_path,
    get_log_path,
    load_config,
)
from agent_session_tools.deduplication import (
    auto_merge_safe_duplicates,
    list_all_duplicates,
    merge_duplicates,
)

# Create Typer app with completion support
app = typer.Typer(
    name="session-maint",
    help="Database maintenance utilities for session database.",
    add_completion=True,
    rich_markup_mode="rich",
)

# Load configuration
config = load_config()
DB_PATH = get_db_path(config)

# Setup logging
log_path = get_log_path(config)
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config["logging"]["level"]),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Global database path option
db_option = typer.Option("-d", "--db", help="Database path (default: from config)")
no_backup_option = typer.Option("--no-backup", help="Skip backup creation")


def create_backup(db_path: Path) -> Path:
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = get_backup_dir(config)
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"{db_path.stem}_backup_{timestamp}.db"
    shutil.copy2(db_path, backup_path)

    logger.info(f"Backup created: {backup_path}")
    print(f"✅ Backup created: {backup_path}")
    return backup_path


def _vacuum(db_path: Path, backup: bool = True) -> int:
    """Optimize database and reclaim unused space."""
    print(f"\n{'=' * 50}")
    print("DATABASE VACUUM (OPTIMIZE)")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    # Get initial size
    initial_size = db_path.stat().st_size / (1024 * 1024)
    print(f"Initial size: {initial_size:.2f} MB")

    if backup:
        create_backup(db_path)

    try:
        conn = sqlite3.connect(db_path)
        print("\n🔧 Running VACUUM...")
        conn.execute("VACUUM")
        conn.close()

        # Get final size
        final_size = db_path.stat().st_size / (1024 * 1024)
        saved = initial_size - final_size

        print(f"Final size: {final_size:.2f} MB")
        print(f"Space reclaimed: {saved:.2f} MB ({(saved / initial_size * 100):.1f}%)")
        print("✅ VACUUM completed successfully")

        logger.info(
            f"VACUUM completed: {initial_size:.2f}MB -> {final_size:.2f}MB, saved {saved:.2f}MB"
        )
        return 0

    except Exception as e:
        print(f"❌ VACUUM failed: {e}")
        logger.error(f"VACUUM failed: {e}")
        return 1


def _schema(db_path: Path, detailed: bool = False) -> int:
    """Display database schema (tables, columns, indexes)."""
    print(f"\n{'=' * 50}")
    print("DATABASE SCHEMA")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get all tables
        tables = conn.execute(
            """
            SELECT name, type FROM sqlite_master
            WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
        """
        ).fetchall()

        for table in tables:
            table_name = table["name"]
            table_type = table["type"].upper()

            print(f"\n📊 {table_type}: {table_name}")
            print("-" * 50)

            # Get columns
            columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            print("Columns:")
            for col in columns:
                pk = " [PRIMARY KEY]" if col["pk"] else ""
                notnull = " NOT NULL" if col["notnull"] else ""
                default = f" DEFAULT {col['dflt_value']}" if col["dflt_value"] else ""
                print(f"  • {col['name']}: {col['type']}{pk}{notnull}{default}")

            # Get indexes
            indexes = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='index' AND tbl_name=? AND name NOT LIKE 'sqlite_%'
            """,
                (table_name,),
            ).fetchall()

            if indexes:
                print("Indexes:")
                for idx in indexes:
                    print(f"  • {idx['name']}")

            # Get row count
            count = conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name}").fetchone()
            print(f"Rows: {count['cnt']:,}")

            # Get table size (approximate)
            if detailed:
                size = conn.execute(
                    """
                    SELECT SUM(pgsize) as size FROM dbstat WHERE name=?
                """,
                    (table_name,),
                ).fetchone()
                if size["size"]:
                    size_mb = size["size"] / (1024 * 1024)
                    print(f"Size: {size_mb:.2f} MB")

        # Summary
        total_tables = len([t for t in tables if t["type"] == "table"])
        total_views = len([t for t in tables if t["type"] == "view"])

        print(f"\n{'=' * 50}")
        print(f"Summary: {total_tables} tables, {total_views} views")
        print(f"{'=' * 50}\n")

        conn.close()
        return 0

    except Exception as e:
        print(f"❌ Schema inspection failed: {e}")
        logger.error(f"Schema inspection failed: {e}")
        return 1


def _reindex(db_path: Path, backup: bool = True) -> int:
    """Rebuild full-text search index."""
    print(f"\n{'=' * 50}")
    print("REBUILD FTS INDEX")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    if backup:
        create_backup(db_path)

    try:
        conn = sqlite3.connect(db_path)

        print("🔧 Rebuilding messages_fts index...")
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")

        # Get count
        count = conn.execute("SELECT COUNT(*) as cnt FROM messages_fts").fetchone()

        conn.commit()
        conn.close()

        print(f"✅ FTS index rebuilt successfully ({count[0]:,} entries)")
        logger.info(f"FTS index rebuilt: {count[0]} entries")
        return 0

    except Exception as e:
        print(f"❌ Reindex failed: {e}")
        logger.error(f"Reindex failed: {e}")
        return 1


def _archive(db_path: Path, days: int, backup: bool = True) -> int:
    """Archive sessions older than N days to separate database."""
    print(f"\n{'=' * 50}")
    print(f"ARCHIVE SESSIONS (older than {days} days)")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    archive_path = db_path.parent / f"{db_path.stem}_archive.db"
    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

    try:
        # Source database
        source_conn = sqlite3.connect(db_path)
        source_conn.row_factory = sqlite3.Row

        # Find old sessions
        old_sessions = source_conn.execute(
            """
            SELECT id, project_path, updated_at FROM sessions
            WHERE updated_at < ? OR updated_at IS NULL
        """,
            (cutoff_date,),
        ).fetchall()

        if not old_sessions:
            print(f"✅ No sessions older than {days} days found")
            source_conn.close()
            return 0

        print(f"Found {len(old_sessions)} sessions to archive")
        print(f"Cutoff date: {cutoff_date}")

        if backup:
            create_backup(db_path)

        # Create archive database if needed
        if not archive_path.exists():
            print(f"\n📦 Creating archive database: {archive_path}")
            archive_conn = sqlite3.connect(archive_path)

            # Create tables manually (proper schema)
            archive_conn.execute(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    project_path TEXT,
                    git_branch TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    metadata JSON
                )
            """
            )
            archive_conn.execute(
                """
                CREATE TABLE messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    parent_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT,
                    model TEXT,
                    timestamp TEXT,
                    metadata JSON,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """
            )
            # Create indexes
            archive_conn.execute(
                "CREATE INDEX idx_messages_session ON messages(session_id)"
            )
            archive_conn.execute(
                "CREATE INDEX idx_messages_timestamp ON messages(timestamp)"
            )
            archive_conn.execute("CREATE INDEX idx_sessions_source ON sessions(source)")
            archive_conn.execute(
                "CREATE INDEX idx_sessions_project ON sessions(project_path)"
            )

            # Create FTS table
            archive_conn.execute(
                """
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    content,
                    content='messages',
                    content_rowid='rowid'
                )
            """
            )

            archive_conn.commit()
        else:
            archive_conn = sqlite3.connect(archive_path)

        # Move sessions and messages
        session_ids = [s["id"] for s in old_sessions]
        archived_count = 0
        message_count = 0

        print("\n🔧 Archiving sessions...")
        for session_id in session_ids:
            # Copy session
            session = source_conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()

            if session:
                archive_conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    tuple(session),
                )
                archived_count += 1

            # Copy messages
            messages = source_conn.execute(
                "SELECT * FROM messages WHERE session_id = ?", (session_id,)
            ).fetchall()

            for msg in messages:
                archive_conn.execute(
                    """
                    INSERT OR REPLACE INTO messages
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    tuple(msg),
                )
                message_count += 1

            # Delete from source
            source_conn.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            source_conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

        # Rebuild FTS index in archive
        archive_conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")

        archive_conn.commit()
        source_conn.commit()

        archive_conn.close()
        source_conn.close()

        print(f"✅ Archived {archived_count} sessions ({message_count} messages)")
        print(f"Archive location: {archive_path}")

        logger.info(f"Archived {archived_count} sessions to {archive_path}")
        return 0

    except Exception as e:
        print(f"❌ Archive failed: {e}")
        logger.error(f"Archive failed: {e}")
        return 1


def _delete_old(
    db_path: Path, days: int, confirm: bool = False, backup: bool = True
) -> int:
    """Delete sessions older than N days (requires confirmation)."""
    print(f"\n{'=' * 50}")
    print(f"⚠️  DELETE SESSIONS (older than {days} days)")
    print(f"{'=' * 50}")

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Find old sessions
        old_sessions = conn.execute(
            """
            SELECT id, project_path, updated_at FROM sessions
            WHERE updated_at < ? OR updated_at IS NULL
        """,
            (cutoff_date,),
        ).fetchall()

        if not old_sessions:
            print(f"✅ No sessions older than {days} days found")
            conn.close()
            return 0

        # Count messages
        session_ids = [s["id"] for s in old_sessions]
        placeholders = ",".join("?" * len(session_ids))
        message_count = conn.execute(
            f"SELECT COUNT(*) FROM messages WHERE session_id IN ({placeholders})",
            session_ids,
        ).fetchone()[0]

        print(f"Found {len(old_sessions)} sessions ({message_count} messages)")
        print(f"Cutoff date: {cutoff_date}")
        print("\n⚠️  THIS OPERATION CANNOT BE UNDONE!")

        if not confirm:
            print("\n❌ Operation cancelled. Use --confirm to proceed.")
            conn.close()
            return 1

        if backup:
            create_backup(db_path)

        # Delete messages first (foreign key constraint)
        print("\n🗑️  Deleting messages...")
        conn.execute(
            f"DELETE FROM messages WHERE session_id IN ({placeholders})", session_ids
        )

        # Delete sessions
        print("🗑️  Deleting sessions...")
        conn.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", session_ids)

        conn.commit()
        conn.close()

        print(f"✅ Deleted {len(old_sessions)} sessions ({message_count} messages)")
        logger.info(f"Deleted {len(old_sessions)} old sessions")
        return 0

    except Exception as e:
        print(f"❌ Delete failed: {e}")
        logger.error(f"Delete failed: {e}")
        return 1


def _handle_duplicates(
    db_path: Path,
    threshold: float = 0.8,
    auto_merge: bool = False,
    merge_ids: list[str] | None = None,
) -> int:
    """Handle deduplication commands."""
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        if merge_ids:
            # Manual merge specific sessions
            primary_id = merge_ids[0]
            duplicate_ids = merge_ids[1:]

            print(f"🔄 Merging {len(duplicate_ids)} sessions into {primary_id[:20]}...")
            stats = merge_duplicates(conn, primary_id, duplicate_ids)
            print(
                f"✅ Merged: {stats['messages_moved']} messages moved, "
                f"{stats['sessions_removed']} sessions removed"
            )

        elif auto_merge:
            # Auto-merge high similarity duplicates
            print("🔍 Finding high-similarity duplicates for auto-merge...")
            stats = auto_merge_safe_duplicates(conn, min_similarity=0.95)

            if stats["groups_merged"] > 0:
                print(f"✅ Auto-merged {stats['groups_merged']} duplicate groups")
                print(
                    f"   {stats['messages_moved']} messages moved, "
                    f"{stats['sessions_removed']} sessions removed"
                )
            else:
                print("✅ No high-similarity duplicates found")

        else:
            # List duplicates for review
            print(f"🔍 Scanning for duplicates (threshold: {threshold:.1%})...")
            list_all_duplicates(conn, threshold)

    finally:
        conn.close()

    return 0


# ==================== CLI Commands ====================


@app.command()
def vacuum(
    db: Annotated[Path | None, db_option] = None,
    no_backup: Annotated[bool, no_backup_option] = False,
) -> None:
    """Optimize database and reclaim unused space."""
    db_path = db if db else DB_PATH
    exit_code = _vacuum(db_path, backup=not no_backup)
    raise typer.Exit(exit_code)


@app.command()
def schema(
    db: Annotated[Path | None, db_option] = None,
    detailed: Annotated[
        bool, typer.Option("--detailed", help="Show detailed info including sizes")
    ] = False,
) -> None:
    """Display database schema (tables, columns, indexes)."""
    db_path = db if db else DB_PATH
    exit_code = _schema(db_path, detailed)
    raise typer.Exit(exit_code)


@app.command()
def reindex(
    db: Annotated[Path | None, db_option] = None,
    no_backup: Annotated[bool, no_backup_option] = False,
) -> None:
    """Rebuild full-text search index."""
    db_path = db if db else DB_PATH
    exit_code = _reindex(db_path, backup=not no_backup)
    raise typer.Exit(exit_code)


@app.command()
def archive(
    days: Annotated[
        int, typer.Option("--days", help="Archive sessions older than N days")
    ],
    db: Annotated[Path | None, db_option] = None,
    no_backup: Annotated[bool, no_backup_option] = False,
) -> None:
    """Archive old sessions to separate database."""
    db_path = db if db else DB_PATH
    exit_code = _archive(db_path, days, backup=not no_backup)
    raise typer.Exit(exit_code)


@app.command("delete")
def delete_cmd(
    days: Annotated[
        int, typer.Option("--days", help="Delete sessions older than N days")
    ],
    db: Annotated[Path | None, db_option] = None,
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Confirm deletion (required)")
    ] = False,
    no_backup: Annotated[bool, no_backup_option] = False,
) -> None:
    """Delete old sessions permanently (requires --confirm)."""
    db_path = db if db else DB_PATH
    exit_code = _delete_old(db_path, days, confirm, backup=not no_backup)
    raise typer.Exit(exit_code)


@app.command("find-duplicates")
def find_duplicates(
    db: Annotated[Path | None, db_option] = None,
    threshold: Annotated[
        float, typer.Option("--threshold", help="Similarity threshold (0.0-1.0)")
    ] = 0.8,
    auto_merge: Annotated[
        bool,
        typer.Option(
            "--auto-merge", help="Auto-merge high similarity duplicates (>95%)"
        ),
    ] = False,
    merge_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--merge-ids", help="Manually merge specific session IDs into first ID"
        ),
    ] = None,
) -> None:
    """Find and manage duplicate sessions."""
    db_path = db if db else DB_PATH
    exit_code = _handle_duplicates(db_path, threshold, auto_merge, merge_ids)
    raise typer.Exit(exit_code)


# ==================== Main Entry Point ====================


def main() -> int:
    """CLI entry point for database maintenance."""
    app()
    return 0


if __name__ == "__main__":
    app()
