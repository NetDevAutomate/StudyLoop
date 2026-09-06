"""Session deduplication system for preventing duplicate imports."""

import json
import sqlite3
from dataclasses import dataclass

from .context.provenance import Scope
from .context.records import policy_guard
from .context.response import read_boundary
from .context.scope import ScopeError, active_policy, visibility_sql
from .context.store import ContextStore


class ProtectedMergeError(ValueError):
    """Similarity cannot authorize changing an owned source identity."""


@dataclass
class DuplicateGroup:
    """Group of duplicate sessions."""

    primary_id: str
    duplicate_ids: list[str]
    similarity_score: float
    detection_method: str


def find_duplicates(
    conn: sqlite3.Connection, threshold: float = 0.8
) -> list[DuplicateGroup]:
    """Find potential duplicate sessions.

    Args:
        conn: Database connection
        threshold: Similarity threshold (0.0-1.0)

    Returns:
        List of duplicate groups
    """
    groups = []

    # Strategy 1: Exact content hash matches
    visible, params = visibility_sql(conn, "s.id")
    content_duplicates = conn.execute(
        f"""
        SELECT content_hash, json_group_array(id) as session_ids, COUNT(*) as count
        FROM sessions s
        WHERE content_hash IS NOT NULL AND {visible}
        GROUP BY content_hash
        HAVING count > 1
    """,
        params,
    ).fetchall()

    for row in content_duplicates:
        ids = sorted(json.loads(row["session_ids"]))
        groups.append(
            DuplicateGroup(
                primary_id=ids[0],  # Keep first by ID
                duplicate_ids=ids[1:],
                similarity_score=1.0,
                detection_method="content_hash",
            )
        )

    # Strategy 2: Temporal overlap (same project, different sources, close timestamps)
    visible1, params1 = visibility_sql(conn, "s1.id")
    visible2, params2 = visibility_sql(conn, "s2.id")
    temporal_candidates = conn.execute(
        f"""
        SELECT s1.id as id1, s2.id as id2, s1.project_path, s1.updated_at, s2.updated_at
        FROM sessions s1
        JOIN sessions s2 ON s1.project_path = s2.project_path
        WHERE ({visible1}) AND ({visible2}) AND s1.source != s2.source
        AND s1.id < s2.id  -- Avoid duplicates in results
        AND s1.project_path IS NOT NULL
        AND ABS(JULIANDAY(s1.updated_at) - JULIANDAY(s2.updated_at)) * 24 * 60 < 15  -- Within 15 minutes
    """,
        [*params1, *params2],
    ).fetchall()

    for row in temporal_candidates:
        similarity = calculate_message_similarity(conn, row["id1"], row["id2"])
        if similarity >= threshold:
            groups.append(
                DuplicateGroup(
                    primary_id=row["id1"],
                    duplicate_ids=[row["id2"]],
                    similarity_score=similarity,
                    detection_method="temporal_overlap",
                )
            )

    return groups


def calculate_message_similarity(
    conn: sqlite3.Connection, session1: str, session2: str
) -> float:
    """Calculate Jaccard similarity between two sessions' message content.

    Args:
        conn: Database connection
        session1: First session ID
        session2: Second session ID

    Returns:
        Similarity score (0.0-1.0)
    """

    visible, params = visibility_sql(conn, "s.id")
    for sid in (session1, session2):
        if not conn.execute(
            "SELECT 1 FROM sessions s WHERE s.id=? AND " + visible, [sid, *params]
        ).fetchone():
            raise ScopeError("Duplicate candidate unavailable in current scope")

    def get_content_words(session_id: str) -> set[str]:
        """Extract unique words from session messages."""
        messages = conn.execute(
            "SELECT m.content FROM messages m JOIN sessions s ON s.id=m.session_id "
            "WHERE s.id=? AND m.role IN ('user','assistant') AND " + visible,
            [session_id, *params],
        ).fetchall()

        words = set()
        for msg in messages:
            if msg[0]:  # content is not null
                # Simple word extraction (could be improved with NLP)
                content_words = msg[0].lower().split()
                words.update(word.strip('.,!?()[]{}":;') for word in content_words)

        return words

    words1 = get_content_words(session1)
    words2 = get_content_words(session2)

    if not words1 or not words2:
        return 0.0

    # Jaccard similarity: intersection / union
    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def _check_legacy_merge(conn, primary_id, duplicate_ids):
    ids = [primary_id, *duplicate_ids]
    if len(ids) != len(set(ids)):
        raise ValueError("Primary and duplicate IDs must be distinct")
    visible, params = visibility_sql(conn, "s.id")
    for sid in ids:
        if not conn.execute(
            "SELECT 1 FROM sessions s WHERE s.id=? AND " + visible, [sid, *params]
        ).fetchone():
            raise ScopeError("Duplicate candidate unavailable in current scope")
    if active_policy().request_scope() != Scope.UNCLASSIFIED:
        raise ProtectedMergeError(
            "Physical merge is unavailable for classified sessions; keep source identities"
        )
    # Only the legacy messages/notes/tags operation is supported. Any owned or
    # dependent record makes physical consolidation unsafe, even in unclassified.
    protected = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "(name GLOB 'context_*' OR name IN ('study_sessions','session_learning_metadata','file_references'))"
        )
    ]
    placeholders = ",".join("?" for _ in ids)
    for table in protected:
        quoted = '"' + table.replace('"', '""') + '"'
        columns = {r[1] for r in conn.execute(f"PRAGMA table_info({quoted})")}
        if (
            "session_id" in columns
            and conn.execute(
                f"SELECT 1 FROM {quoted} WHERE session_id IN ({placeholders}) LIMIT 1",
                ids,
            ).fetchone()
        ):
            raise ProtectedMergeError(
                "Physical merge is unavailable for owned or provenance-bound sessions; keep source identities"
            )


def merge_duplicates(
    conn: sqlite3.Connection, primary_id: str, duplicate_ids: list[str]
) -> dict:
    """Atomically merge legacy unclassified rows only; never reparent evidence."""
    with ContextStore(conn)._atomic(), policy_guard(conn):
        _check_legacy_merge(conn, primary_id, duplicate_ids)
        return _merge_legacy_rows(conn, primary_id, duplicate_ids)


def _merge_legacy_rows(
    conn: sqlite3.Connection, primary_id: str, duplicate_ids: list[str]
) -> dict:
    """Merge duplicate sessions into the primary session.

    Args:
        conn: Database connection
        primary_id: ID of session to keep
        duplicate_ids: IDs of sessions to merge into primary

    Returns:
        Dict with merge statistics
    """
    stats = {"messages_moved": 0, "sessions_removed": 0}

    for dup_id in duplicate_ids:
        # Move messages to primary session (update session_id)
        moved = conn.execute(
            """
            UPDATE messages
            SET session_id = ?
            WHERE session_id = ?
        """,
            (primary_id, dup_id),
        ).rowcount

        stats["messages_moved"] += moved

        # Move tags to primary session
        conn.execute(
            """
            INSERT OR IGNORE INTO session_tags (session_id, tag, created_at)
            SELECT ?, tag, created_at
            FROM session_tags
            WHERE session_id = ?
        """,
            (primary_id, dup_id),
        )

        # Remove duplicate tags
        conn.execute("DELETE FROM session_tags WHERE session_id = ?", (dup_id,))

        # Move notes (merge with existing notes if needed)
        existing_note = conn.execute(
            "SELECT notes FROM session_notes WHERE session_id = ?", (primary_id,)
        ).fetchone()

        duplicate_note = conn.execute(
            "SELECT notes FROM session_notes WHERE session_id = ?", (dup_id,)
        ).fetchone()

        if duplicate_note and duplicate_note[0]:
            if existing_note and existing_note[0]:
                # Merge notes
                merged_notes = f"{existing_note[0]}\n\n---\n\n{duplicate_note[0]}"
            else:
                merged_notes = duplicate_note[0]

            conn.execute(
                """
                INSERT OR REPLACE INTO session_notes (session_id, notes, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
                (primary_id, merged_notes),
            )

        # Remove duplicate note
        conn.execute("DELETE FROM session_notes WHERE session_id = ?", (dup_id,))

        # Remove duplicate session
        conn.execute("DELETE FROM sessions WHERE id = ?", (dup_id,))
        stats["sessions_removed"] += 1

    return stats


def list_all_duplicates(conn: sqlite3.Connection, threshold: float = 0.8) -> None:
    """Release the complete review only after validating its access snapshot."""
    owned_read = not conn.in_transaction
    try:
        with read_boundary():
            output = _format_duplicates(conn, threshold)
    finally:
        if owned_read:
            conn.rollback()
    print(output, end="")


def _format_duplicates(conn: sqlite3.Connection, threshold: float = 0.8) -> str:
    """List all potential duplicates for review.

    Args:
        conn: Database connection
        threshold: Similarity threshold for reporting
    """
    groups = find_duplicates(conn, threshold)

    if not groups:
        return "✅ No duplicates found\n"

    lines = []
    lines.append(f"\n🔍 Found {len(groups)} duplicate groups:")

    for i, group in enumerate(groups, 1):
        lines.append(f"\n{i}. Primary: {group.primary_id}")
        lines.append(f"   Duplicates: {len(group.duplicate_ids)}")
        lines.append(f"   Method: {group.detection_method}")
        lines.append(f"   Similarity: {group.similarity_score:.1%}")

        # Show session details
        primary_session = conn.execute(
            "SELECT source, project_path, updated_at FROM sessions WHERE id = ?",
            (group.primary_id,),
        ).fetchone()

        if primary_session:
            lines.append(
                f"   Primary: [{primary_session['source']}] {primary_session['project_path']} ({primary_session['updated_at']})"
            )

        for dup_id in group.duplicate_ids[:3]:  # Show first 3
            dup_session = conn.execute(
                "SELECT source, project_path, updated_at FROM sessions WHERE id = ?",
                (dup_id,),
            ).fetchone()
            if dup_session:
                lines.append(
                    f"   Duplicate: [{dup_session['source']}] {dup_session['project_path']} ({dup_session['updated_at']})"
                )

        if len(group.duplicate_ids) > 3:
            lines.append(f"   ... and {len(group.duplicate_ids) - 3} more")

    return "\n".join(lines) + "\n"


def auto_merge_safe_duplicates(
    conn: sqlite3.Connection, min_similarity: float = 0.95
) -> dict:
    """Automatically merge very high similarity duplicates.

    Args:
        conn: Database connection
        min_similarity: Minimum similarity to auto-merge (default 0.95)

    Returns:
        Merge statistics
    """
    total_stats = {
        "groups_merged": 0,
        "messages_moved": 0,
        "sessions_removed": 0,
        "groups_protected": 0,
    }
    with ContextStore(conn)._atomic(), policy_guard(conn):
        groups = find_duplicates(conn, min_similarity)
        consumed = set()
        for group in groups:
            ids = {group.primary_id, *group.duplicate_ids}
            if group.similarity_score < min_similarity or consumed & ids:
                continue
            try:
                stats = merge_duplicates(conn, group.primary_id, group.duplicate_ids)
            except ProtectedMergeError:
                total_stats["groups_protected"] += 1
                continue
            consumed.update(ids)
            total_stats["groups_merged"] += 1
            total_stats["messages_moved"] += stats["messages_moved"]
            total_stats["sessions_removed"] += stats["sessions_removed"]
    return total_stats
