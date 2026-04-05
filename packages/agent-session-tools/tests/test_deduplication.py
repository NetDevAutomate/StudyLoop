"""Tests for the deduplication module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.deduplication import (
    DuplicateGroup,
    auto_merge_safe_duplicates,
    calculate_message_similarity,
    find_duplicates,
    list_all_duplicates,
    merge_duplicates,
)
from agent_session_tools.migrations import migrate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db() -> sqlite3.Connection:
    """Create an in-memory DB with full schema + all migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    schema_path = (
        Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
    )
    conn.executescript(schema_path.read_text())
    migrate(conn)
    return conn


def _insert_session(
    conn: sqlite3.Connection,
    id: str,
    source: str = "claude_code",
    project_path: str | None = "/test/project",
    updated_at: str = "2024-01-01T10:00:00",
    content_hash: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sessions (id, source, project_path, created_at, updated_at, content_hash)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (id, source, project_path, updated_at, updated_at, content_hash),
    )
    conn.commit()


def _insert_message(
    conn: sqlite3.Connection,
    id: str,
    session_id: str,
    role: str = "user",
    content: str = "hello world",
    timestamp: str = "2024-01-01T10:00:00",
) -> None:
    conn.execute(
        """
        INSERT INTO messages (id, session_id, role, content, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (id, session_id, role, content, timestamp),
    )
    conn.commit()


def _insert_tag(conn: sqlite3.Connection, session_id: str, tag: str) -> None:
    conn.execute(
        "INSERT INTO session_tags (session_id, tag) VALUES (?, ?)",
        (session_id, tag),
    )
    conn.commit()


def _insert_note(conn: sqlite3.Connection, session_id: str, notes: str) -> None:
    conn.execute(
        "INSERT INTO session_notes (session_id, notes) VALUES (?, ?)",
        (session_id, notes),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# DuplicateGroup dataclass
# ---------------------------------------------------------------------------


class TestDuplicateGroup:
    def test_fields_are_accessible(self):
        g = DuplicateGroup(
            primary_id="a",
            duplicate_ids=["b", "c"],
            similarity_score=0.95,
            detection_method="content_hash",
        )
        assert g.primary_id == "a"
        assert g.duplicate_ids == ["b", "c"]
        assert g.similarity_score == 0.95
        assert g.detection_method == "content_hash"

    def test_equality_by_value(self):
        g1 = DuplicateGroup("a", ["b"], 1.0, "content_hash")
        g2 = DuplicateGroup("a", ["b"], 1.0, "content_hash")
        assert g1 == g2


# ---------------------------------------------------------------------------
# calculate_message_similarity
# ---------------------------------------------------------------------------


class TestCalculateMessageSimilarity:
    def test_identical_content_returns_one(self):
        conn = _make_db()
        _insert_session(conn, "s1")
        _insert_session(conn, "s2")
        words = "python closures are powerful concepts"
        _insert_message(conn, "m1", "s1", content=words)
        _insert_message(conn, "m2", "s2", content=words)

        score = calculate_message_similarity(conn, "s1", "s2")
        assert score == 1.0

    def test_completely_different_content_returns_low_score(self):
        conn = _make_db()
        _insert_session(conn, "s1")
        _insert_session(conn, "s2")
        _insert_message(conn, "m1", "s1", content="alpha beta gamma delta")
        _insert_message(conn, "m2", "s2", content="zeta eta theta iota kappa")

        score = calculate_message_similarity(conn, "s1", "s2")
        assert score == 0.0

    def test_partial_overlap_returns_jaccard(self):
        conn = _make_db()
        _insert_session(conn, "s1")
        _insert_session(conn, "s2")
        # words1 = {a, b, c}, words2 = {b, c, d} → intersection=2, union=4 → 0.5
        _insert_message(conn, "m1", "s1", content="a b c")
        _insert_message(conn, "m2", "s2", content="b c d")

        score = calculate_message_similarity(conn, "s1", "s2")
        assert score == pytest.approx(0.5)

    def test_empty_session_returns_zero(self):
        conn = _make_db()
        _insert_session(conn, "s1")
        _insert_session(conn, "s2")
        # s2 has no messages at all

        score = calculate_message_similarity(conn, "s1", "s2")
        assert score == 0.0

    def test_only_tool_messages_ignored(self):
        conn = _make_db()
        _insert_session(conn, "s1")
        _insert_session(conn, "s2")
        # tool_use and tool_result roles are excluded by the query
        _insert_message(conn, "m1", "s1", role="tool_use", content="read file path")
        _insert_message(conn, "m2", "s2", role="tool_result", content="read file path")

        score = calculate_message_similarity(conn, "s1", "s2")
        assert score == 0.0

    def test_punctuation_stripped_before_comparison(self):
        conn = _make_db()
        _insert_session(conn, "s1")
        _insert_session(conn, "s2")
        # Same word with and without punctuation should normalise to same token
        _insert_message(conn, "m1", "s1", content="hello, world!")
        _insert_message(conn, "m2", "s2", content="hello world")

        score = calculate_message_similarity(conn, "s1", "s2")
        assert score == 1.0

    def test_case_insensitive_comparison(self):
        conn = _make_db()
        _insert_session(conn, "s1")
        _insert_session(conn, "s2")
        _insert_message(conn, "m1", "s1", content="Python Django REST")
        _insert_message(conn, "m2", "s2", content="python django rest")

        score = calculate_message_similarity(conn, "s1", "s2")
        assert score == 1.0

    def test_multiple_messages_combined(self):
        conn = _make_db()
        _insert_session(conn, "s1")
        _insert_session(conn, "s2")
        # s1 has two messages: unique words from each are unioned
        _insert_message(conn, "m1a", "s1", content="alpha beta")
        _insert_message(
            conn, "m1b", "s1", content="gamma delta", timestamp="2024-01-01T10:01:00"
        )
        _insert_message(conn, "m2a", "s2", content="alpha beta gamma delta")

        score = calculate_message_similarity(conn, "s1", "s2")
        assert score == 1.0


# ---------------------------------------------------------------------------
# find_duplicates — content hash strategy
# ---------------------------------------------------------------------------


class TestFindDuplicatesContentHash:
    def test_no_sessions_returns_empty(self):
        conn = _make_db()
        groups = find_duplicates(conn)
        assert groups == []

    def test_no_hash_collisions_returns_empty(self):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="hash1")
        _insert_session(conn, "s2", content_hash="hash2")

        groups = find_duplicates(conn)
        assert groups == []

    def test_null_hash_sessions_not_grouped(self):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash=None)
        _insert_session(conn, "s2", content_hash=None)

        groups = find_duplicates(conn)
        # NULL != NULL in SQL GROUP BY, so no content_hash groups expected
        # (temporal overlap might fire, but same source so it won't)
        hash_groups = [g for g in groups if g.detection_method == "content_hash"]
        assert hash_groups == []

    def test_shared_hash_creates_group(self):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="deadbeef")
        _insert_session(conn, "s2", content_hash="deadbeef")

        groups = find_duplicates(conn)
        hash_groups = [g for g in groups if g.detection_method == "content_hash"]
        assert len(hash_groups) == 1

    def test_content_hash_group_has_score_one(self):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="deadbeef")
        _insert_session(conn, "s2", content_hash="deadbeef")

        groups = find_duplicates(conn)
        hash_groups = [g for g in groups if g.detection_method == "content_hash"]
        assert hash_groups[0].similarity_score == 1.0

    def test_content_hash_group_keeps_first_as_primary(self):
        conn = _make_db()
        # s1 inserted before s2; GROUP_CONCAT order follows insertion/id sort
        _insert_session(conn, "s1", content_hash="deadbeef")
        _insert_session(conn, "s2", content_hash="deadbeef")

        groups = find_duplicates(conn)
        hash_groups = [g for g in groups if g.detection_method == "content_hash"]
        # primary is the first id in the concatenated list
        group = hash_groups[0]
        assert group.primary_id in ("s1", "s2")
        assert len(group.duplicate_ids) == 1

    def test_three_sessions_same_hash(self):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="abc123")
        _insert_session(conn, "s2", content_hash="abc123")
        _insert_session(conn, "s3", content_hash="abc123")

        groups = find_duplicates(conn)
        hash_groups = [g for g in groups if g.detection_method == "content_hash"]
        assert len(hash_groups) == 1
        group = hash_groups[0]
        # One primary + two duplicates
        assert len(group.duplicate_ids) == 2


# ---------------------------------------------------------------------------
# find_duplicates — temporal overlap strategy
# ---------------------------------------------------------------------------


class TestFindDuplicatesTemporalOverlap:
    def test_same_source_never_matches(self):
        conn = _make_db()
        # Same source, same project, within 1 minute → should NOT match
        _insert_session(
            conn,
            "s1",
            source="claude_code",
            project_path="/proj",
            updated_at="2024-01-01T10:00:00",
        )
        _insert_session(
            conn,
            "s2",
            source="claude_code",
            project_path="/proj",
            updated_at="2024-01-01T10:01:00",
        )

        groups = find_duplicates(conn)
        temporal_groups = [
            g for g in groups if g.detection_method == "temporal_overlap"
        ]
        assert temporal_groups == []

    def test_different_source_different_project_no_match(self):
        conn = _make_db()
        _insert_session(
            conn,
            "s1",
            source="claude_code",
            project_path="/proj1",
            updated_at="2024-01-01T10:00:00",
        )
        _insert_session(
            conn,
            "s2",
            source="kiro_cli",
            project_path="/proj2",
            updated_at="2024-01-01T10:01:00",
        )

        groups = find_duplicates(conn)
        temporal_groups = [
            g for g in groups if g.detection_method == "temporal_overlap"
        ]
        assert temporal_groups == []

    def test_null_project_path_excluded(self):
        conn = _make_db()
        _insert_session(
            conn,
            "s1",
            source="claude_code",
            project_path=None,
            updated_at="2024-01-01T10:00:00",
        )
        _insert_session(
            conn,
            "s2",
            source="kiro_cli",
            project_path=None,
            updated_at="2024-01-01T10:01:00",
        )

        groups = find_duplicates(conn)
        temporal_groups = [
            g for g in groups if g.detection_method == "temporal_overlap"
        ]
        assert temporal_groups == []

    def test_far_apart_timestamps_not_matched(self):
        conn = _make_db()
        _insert_session(
            conn,
            "s1",
            source="claude_code",
            project_path="/proj",
            updated_at="2024-01-01T10:00:00",
        )
        _insert_session(
            conn,
            "s2",
            source="kiro_cli",
            project_path="/proj",
            updated_at="2024-01-01T12:00:00",
        )

        groups = find_duplicates(conn)
        temporal_groups = [
            g for g in groups if g.detection_method == "temporal_overlap"
        ]
        assert temporal_groups == []

    def test_close_timestamps_with_similar_content_creates_group(self):
        conn = _make_db()
        _insert_session(
            conn,
            "s1",
            source="claude_code",
            project_path="/proj",
            updated_at="2024-01-01T10:00:00",
        )
        _insert_session(
            conn,
            "s2",
            source="kiro_cli",
            project_path="/proj",
            updated_at="2024-01-01T10:05:00",
        )

        # Identical content → similarity = 1.0 → above any threshold
        content = "python closures decorators context manager"
        _insert_message(conn, "m1", "s1", content=content)
        _insert_message(conn, "m2", "s2", content=content)

        groups = find_duplicates(conn, threshold=0.8)
        temporal_groups = [
            g for g in groups if g.detection_method == "temporal_overlap"
        ]
        assert len(temporal_groups) == 1
        assert temporal_groups[0].detection_method == "temporal_overlap"

    def test_close_timestamps_low_similarity_below_threshold(self):
        conn = _make_db()
        _insert_session(
            conn,
            "s1",
            source="claude_code",
            project_path="/proj",
            updated_at="2024-01-01T10:00:00",
        )
        _insert_session(
            conn,
            "s2",
            source="kiro_cli",
            project_path="/proj",
            updated_at="2024-01-01T10:05:00",
        )

        # Completely different content → similarity = 0.0
        _insert_message(conn, "m1", "s1", content="alpha beta gamma")
        _insert_message(conn, "m2", "s2", content="zeta eta theta iota kappa lambda")

        groups = find_duplicates(conn, threshold=0.8)
        temporal_groups = [
            g for g in groups if g.detection_method == "temporal_overlap"
        ]
        assert temporal_groups == []

    def test_threshold_parameter_respected(self):
        conn = _make_db()
        _insert_session(
            conn,
            "s1",
            source="claude_code",
            project_path="/proj",
            updated_at="2024-01-01T10:00:00",
        )
        _insert_session(
            conn,
            "s2",
            source="kiro_cli",
            project_path="/proj",
            updated_at="2024-01-01T10:05:00",
        )

        # words1={a,b,c,d}, words2={c,d,e,f} → intersection=2, union=6 → ~0.33
        _insert_message(conn, "m1", "s1", content="a b c d")
        _insert_message(conn, "m2", "s2", content="c d e f")

        # High threshold: no match
        groups_high = find_duplicates(conn, threshold=0.8)
        assert not any(g.detection_method == "temporal_overlap" for g in groups_high)

        # Low threshold: match
        groups_low = find_duplicates(conn, threshold=0.3)
        assert any(g.detection_method == "temporal_overlap" for g in groups_low)


# ---------------------------------------------------------------------------
# merge_duplicates
# ---------------------------------------------------------------------------


class TestMergeDuplicates:
    def test_messages_moved_to_primary(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")
        _insert_message(conn, "m1", "primary", content="keep me")
        _insert_message(conn, "m2", "dup", content="move me")

        merge_duplicates(conn, "primary", ["dup"])

        messages = conn.execute(
            "SELECT session_id FROM messages WHERE id = 'm2'"
        ).fetchone()
        assert messages["session_id"] == "primary"

    def test_stats_messages_moved_count(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")
        _insert_message(conn, "m1", "dup", content="move me 1")
        _insert_message(
            conn, "m2", "dup", content="move me 2", timestamp="2024-01-01T10:01:00"
        )

        stats = merge_duplicates(conn, "primary", ["dup"])
        assert stats["messages_moved"] == 2

    def test_duplicate_session_removed(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")

        merge_duplicates(conn, "primary", ["dup"])

        row = conn.execute("SELECT id FROM sessions WHERE id = 'dup'").fetchone()
        assert row is None

    def test_stats_sessions_removed_count(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup1")
        _insert_session(conn, "dup2")

        stats = merge_duplicates(conn, "primary", ["dup1", "dup2"])
        assert stats["sessions_removed"] == 2

    def test_tags_moved_to_primary(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")
        _insert_tag(conn, "dup", "python")
        _insert_tag(conn, "dup", "oop")

        merge_duplicates(conn, "primary", ["dup"])

        tags = {
            row["tag"]
            for row in conn.execute(
                "SELECT tag FROM session_tags WHERE session_id = 'primary'"
            ).fetchall()
        }
        assert "python" in tags
        assert "oop" in tags

    def test_duplicate_tags_removed_from_source(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")
        _insert_tag(conn, "dup", "python")

        merge_duplicates(conn, "primary", ["dup"])

        tags = conn.execute(
            "SELECT tag FROM session_tags WHERE session_id = 'dup'"
        ).fetchall()
        assert tags == []

    def test_overlapping_tags_not_duplicated(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")
        _insert_tag(conn, "primary", "python")
        _insert_tag(conn, "dup", "python")  # same tag

        merge_duplicates(conn, "primary", ["dup"])

        count = conn.execute(
            "SELECT COUNT(*) FROM session_tags WHERE session_id = 'primary' AND tag = 'python'"
        ).fetchone()[0]
        assert count == 1

    def test_notes_merged_when_both_have_notes(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")
        _insert_note(conn, "primary", "primary note")
        _insert_note(conn, "dup", "dup note")

        merge_duplicates(conn, "primary", ["dup"])

        row = conn.execute(
            "SELECT notes FROM session_notes WHERE session_id = 'primary'"
        ).fetchone()
        assert "primary note" in row["notes"]
        assert "dup note" in row["notes"]

    def test_notes_moved_when_primary_has_no_notes(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")
        _insert_note(conn, "dup", "only dup has notes")

        merge_duplicates(conn, "primary", ["dup"])

        row = conn.execute(
            "SELECT notes FROM session_notes WHERE session_id = 'primary'"
        ).fetchone()
        assert row is not None
        assert row["notes"] == "only dup has notes"

    def test_duplicate_notes_removed(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")
        _insert_note(conn, "dup", "dup note")

        merge_duplicates(conn, "primary", ["dup"])

        row = conn.execute(
            "SELECT notes FROM session_notes WHERE session_id = 'dup'"
        ).fetchone()
        assert row is None

    def test_empty_duplicate_list_no_changes(self):
        conn = _make_db()
        _insert_session(conn, "primary")

        stats = merge_duplicates(conn, "primary", [])
        assert stats["messages_moved"] == 0
        assert stats["sessions_removed"] == 0

    def test_returns_dict_with_expected_keys(self):
        conn = _make_db()
        _insert_session(conn, "primary")

        stats = merge_duplicates(conn, "primary", [])
        assert "messages_moved" in stats
        assert "sessions_removed" in stats

    def test_primary_session_preserved(self):
        conn = _make_db()
        _insert_session(conn, "primary")
        _insert_session(conn, "dup")

        merge_duplicates(conn, "primary", ["dup"])

        row = conn.execute("SELECT id FROM sessions WHERE id = 'primary'").fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# list_all_duplicates (output / side-effect focused)
# ---------------------------------------------------------------------------


class TestListAllDuplicates:
    def test_no_duplicates_prints_none_found(self, capsys):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="unique_hash")

        list_all_duplicates(conn)

        out = capsys.readouterr().out
        assert "No duplicates found" in out

    def test_with_duplicates_prints_group_count(self, capsys):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="same")
        _insert_session(conn, "s2", content_hash="same")

        list_all_duplicates(conn)

        out = capsys.readouterr().out
        assert "1 duplicate group" in out

    def test_with_duplicates_prints_primary_id(self, capsys):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="same")
        _insert_session(conn, "s2", content_hash="same")

        list_all_duplicates(conn)

        out = capsys.readouterr().out
        # The primary id should appear somewhere in the output
        assert "Primary:" in out


# ---------------------------------------------------------------------------
# auto_merge_safe_duplicates
# ---------------------------------------------------------------------------


class TestAutoMergeSafeDuplicates:
    def test_no_duplicates_returns_zero_stats(self):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="unique1")
        _insert_session(conn, "s2", content_hash="unique2")

        stats = auto_merge_safe_duplicates(conn)
        assert stats["groups_merged"] == 0
        assert stats["messages_moved"] == 0
        assert stats["sessions_removed"] == 0

    def test_content_hash_duplicates_auto_merged(self, capsys):
        conn = _make_db()
        _insert_session(conn, "s1", content_hash="deadbeef")
        _insert_session(conn, "s2", content_hash="deadbeef")
        _insert_message(conn, "m1", "s1")
        _insert_message(conn, "m2", "s2")

        stats = auto_merge_safe_duplicates(conn, min_similarity=0.95)

        assert stats["groups_merged"] == 1
        assert stats["sessions_removed"] == 1

    def test_below_min_similarity_not_merged(self):
        conn = _make_db()
        _insert_session(
            conn,
            "s1",
            source="claude_code",
            project_path="/proj",
            updated_at="2024-01-01T10:00:00",
        )
        _insert_session(
            conn,
            "s2",
            source="kiro_cli",
            project_path="/proj",
            updated_at="2024-01-01T10:05:00",
        )

        # similarity ~0.33 — below any reasonable min_similarity
        _insert_message(conn, "m1", "s1", content="a b c d")
        _insert_message(conn, "m2", "s2", content="c d e f")

        stats = auto_merge_safe_duplicates(conn, min_similarity=0.95)
        assert stats["groups_merged"] == 0

    def test_returns_dict_with_expected_keys(self):
        conn = _make_db()
        stats = auto_merge_safe_duplicates(conn)
        assert set(stats.keys()) == {
            "groups_merged",
            "messages_moved",
            "sessions_removed",
        }

    def test_multiple_duplicate_groups_all_merged(self, capsys):
        conn = _make_db()
        # Two independent hash collisions
        _insert_session(conn, "a1", content_hash="hash_a")
        _insert_session(conn, "a2", content_hash="hash_a")
        _insert_session(conn, "b1", content_hash="hash_b")
        _insert_session(conn, "b2", content_hash="hash_b")

        stats = auto_merge_safe_duplicates(conn, min_similarity=0.95)

        assert stats["groups_merged"] == 2
        assert stats["sessions_removed"] == 2
