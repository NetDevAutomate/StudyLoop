"""Session deduplication system for preventing duplicate imports."""

import sqlite3
from dataclasses import dataclass


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
    content_duplicates = conn.execute("""
        SELECT content_hash, GROUP_CONCAT(id) as session_ids, COUNT(*) as count
        FROM sessions
        WHERE content_hash IS NOT NULL
        GROUP BY content_hash
        HAVING count > 1
    """).fetchall()

    for row in content_duplicates:
        ids = row["session_ids"].split(",")
        groups.append(
            DuplicateGroup(
                primary_id=ids[0],  # Keep first by ID
                duplicate_ids=ids[1:],
                similarity_score=1.0,
                detection_method="content_hash",
            )
        )

    # Strategy 2: Temporal overlap (same project, different sources, close timestamps)
    temporal_candidates = conn.execute("""
        SELECT s1.id as id1, s2.id as id2, s1.project_path, s1.updated_at, s2.updated_at
        FROM sessions s1
        JOIN sessions s2 ON s1.project_path = s2.project_path
        WHERE s1.source != s2.source
        AND s1.id < s2.id  -- Avoid duplicates in results
        AND s1.project_path IS NOT NULL
        AND ABS(JULIANDAY(s1.updated_at) - JULIANDAY(s2.updated_at)) * 24 * 60 < 15  -- Within 15 minutes
    """).fetchall()

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

    def get_content_words(session_id: str) -> set[str]:
        """Extract unique words from session messages."""
        messages = conn.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role IN ('user', 'assistant')",
            (session_id,),
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


def merge_duplicates(
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

    conn.commit()
    return stats


def list_all_duplicates(conn: sqlite3.Connection, threshold: float = 0.8) -> None:
    """List all potential duplicates for review.

    Args:
        conn: Database connection
        threshold: Similarity threshold for reporting
    """
    groups = find_duplicates(conn, threshold)

    if not groups:
        print("✅ No duplicates found")
        return

    print(f"\n🔍 Found {len(groups)} duplicate groups:")

    for i, group in enumerate(groups, 1):
        print(f"\n{i}. Primary: {group.primary_id}")
        print(f"   Duplicates: {len(group.duplicate_ids)}")
        print(f"   Method: {group.detection_method}")
        print(f"   Similarity: {group.similarity_score:.1%}")

        # Show session details
        primary_session = conn.execute(
            "SELECT source, project_path, updated_at FROM sessions WHERE id = ?",
            (group.primary_id,),
        ).fetchone()

        if primary_session:
            print(
                f"   Primary: [{primary_session['source']}] {primary_session['project_path']} ({primary_session['updated_at']})"
            )

        for dup_id in group.duplicate_ids[:3]:  # Show first 3
            dup_session = conn.execute(
                "SELECT source, project_path, updated_at FROM sessions WHERE id = ?",
                (dup_id,),
            ).fetchone()
            if dup_session:
                print(
                    f"   Duplicate: [{dup_session['source']}] {dup_session['project_path']} ({dup_session['updated_at']})"
                )

        if len(group.duplicate_ids) > 3:
            print(f"   ... and {len(group.duplicate_ids) - 3} more")


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
    groups = find_duplicates(conn, min_similarity)
    total_stats = {"groups_merged": 0, "messages_moved": 0, "sessions_removed": 0}

    for group in groups:
        if group.similarity_score >= min_similarity:
            stats = merge_duplicates(conn, group.primary_id, group.duplicate_ids)
            total_stats["groups_merged"] += 1
            total_stats["messages_moved"] += stats["messages_moved"]
            total_stats["sessions_removed"] += stats["sessions_removed"]

            print(
                f"✅ Merged {len(group.duplicate_ids)} duplicates into {group.primary_id[:20]}..."
            )

    return total_stats
