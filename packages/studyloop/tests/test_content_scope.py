"""Tests for the scope resolver (U3).

Builds a tmp-dir fixture vault and an in-memory study_progress table.
No HTTP, no external services -- pure-function resolver.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from studyloop.content.scope import (
    ResolvedSource,
    ScopeRequest,
    ScopeResolutionError,
    resolve_scope,
)
from studyloop.settings import ContentConfig, Settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Build a small course-shaped vault.

    Layout matches the user's actual ``Study/`` (per session
    investigation 2026-05-28): courses by provider, sections inside.

        Study/
          DataCamp/
            advanced-pandas/
              chapter-1.md
              chapter-2.md
            joins/
              joins-intro.md
            assets/   <-- non-source dir, should be skipped
              image.png
            flashcards/   <-- output dir, must be skipped
              old-deck.json
          ZTM/
            empty/         <-- empty subdir, skipped silently
    """
    study = tmp_path / "Study"
    dc = study / "DataCamp"
    (dc / "advanced-pandas").mkdir(parents=True)
    (dc / "advanced-pandas" / "chapter-1.md").write_text(
        "# Advanced Pandas - Chapter 1\n\nGroupby aggregations and pivot tables.",
        encoding="utf-8",
    )
    (dc / "advanced-pandas" / "chapter-2.md").write_text(
        "# Advanced Pandas - Chapter 2\n\nMultiIndex and stack/unstack.",
        encoding="utf-8",
    )
    (dc / "joins").mkdir()
    (dc / "joins" / "joins-intro.md").write_text(
        "# Joins\n\nINNER, LEFT, RIGHT, FULL OUTER. When to use each.",
        encoding="utf-8",
    )
    (dc / "assets").mkdir()
    (dc / "assets" / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (dc / "flashcards").mkdir()
    (dc / "flashcards" / "old-deck.json").write_text("{}", encoding="utf-8")

    ztm = study / "ZTM"
    (ztm / "empty").mkdir(parents=True)

    return study


@pytest.fixture
def settings(vault: Path, tmp_path: Path) -> Settings:
    """Settings pointing at the fixture vault and a tmp sessions.db."""
    s = Settings()
    s.content = ContentConfig(base_path=vault)
    s.session_db = tmp_path / "sessions.db"
    return s


@pytest.fixture
def db_with_progress(tmp_path: Path) -> Path:
    """Populated sessions.db with a known set of struggling/learning rows."""
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE study_progress (
            id TEXT PRIMARY KEY,
            topic TEXT,
            concept TEXT,
            confidence TEXT,
            first_seen TEXT,
            last_seen TEXT,
            session_count INTEGER,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    now = datetime.now(UTC)
    rows = [
        # struggling, in window
        (
            "id1",
            "joins",
            "outer join",
            "struggling",
            now.isoformat(),
            now.isoformat(),
            1,
            None,
            now.isoformat(),
            now.isoformat(),
        ),
        # struggling, out of window (60 days ago)
        (
            "id2",
            "ancient",
            "old concept",
            "struggling",
            (now - timedelta(days=60)).isoformat(),
            (now - timedelta(days=60)).isoformat(),
            1,
            None,
            now.isoformat(),
            now.isoformat(),
        ),
        # learning (not struggling) -- should NOT match
        (
            "id3",
            "advanced-pandas",
            "groupby",
            "learning",
            now.isoformat(),
            now.isoformat(),
            1,
            None,
            now.isoformat(),
            now.isoformat(),
        ),
        # second concept on the same topic, struggling -- should still
        # produce ONE topic row in DISTINCT result
        (
            "id4",
            "joins",
            "self join",
            "struggling",
            now.isoformat(),
            now.isoformat(),
            1,
            None,
            now.isoformat(),
            now.isoformat(),
        ),
    ]
    conn.executemany(
        "INSERT INTO study_progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------------------
# course scope
# ---------------------------------------------------------------------------


class TestCourseScope:
    def test_resolves_each_section_subdir_into_one_source(
        self, settings: Settings
    ) -> None:
        req = ScopeRequest(kind="course", course="DataCamp")
        sources = resolve_scope(req, settings)
        # Two real sections -- assets/ skipped (no md), flashcards/ skipped
        # (output dir reserved).
        identifiers = sorted(s.identifier for s in sources)
        assert identifiers == ["advanced-pandas", "joins"]

    def test_concatenates_chapter_files_within_a_section(
        self, settings: Settings
    ) -> None:
        req = ScopeRequest(kind="course", course="DataCamp")
        sources = resolve_scope(req, settings)
        adv = next(s for s in sources if s.identifier == "advanced-pandas")
        assert "Chapter 1" in adv.markdown_text
        assert "Chapter 2" in adv.markdown_text

    def test_missing_course_dir_raises(self, settings: Settings) -> None:
        req = ScopeRequest(kind="course", course="DoesNotExist")
        with pytest.raises(ScopeResolutionError, match="Course directory not found"):
            resolve_scope(req, settings)

    def test_course_with_only_empty_subdirs_raises(self, settings: Settings) -> None:
        req = ScopeRequest(kind="course", course="ZTM")
        with pytest.raises(ScopeResolutionError, match="no readable section markdown"):
            resolve_scope(req, settings)


# ---------------------------------------------------------------------------
# section scope
# ---------------------------------------------------------------------------


class TestSectionScope:
    def test_resolves_named_section(self, settings: Settings) -> None:
        req = ScopeRequest(kind="section", course="DataCamp", section="joins")
        sources = resolve_scope(req, settings)
        assert len(sources) == 1
        assert sources[0].identifier == "joins"
        assert "INNER" in sources[0].markdown_text

    def test_missing_section_raises(self, settings: Settings) -> None:
        req = ScopeRequest(
            kind="section", course="DataCamp", section="not-a-real-section"
        )
        with pytest.raises(ScopeResolutionError, match="Section not found"):
            resolve_scope(req, settings)

    def test_reserved_output_section_name_rejected(
        self, settings: Settings
    ) -> None:
        req = ScopeRequest(kind="section", course="DataCamp", section="flashcards")
        with pytest.raises(ScopeResolutionError, match="reserved for generated"):
            resolve_scope(req, settings)


# ---------------------------------------------------------------------------
# topic_struggles scope
# ---------------------------------------------------------------------------


class TestTopicStrugglesScope:
    def test_resolves_struggling_topic_in_window_to_matching_section(
        self, settings: Settings, db_with_progress: Path
    ) -> None:
        # 'joins' is struggling in window AND matches DataCamp/joins/
        req = ScopeRequest(kind="topic_struggles", course="DataCamp", window_days=14)
        sources = resolve_scope(req, settings, db_path=db_with_progress)
        # Only joins should resolve -- 'advanced-pandas' is 'learning'
        # not 'struggling', and 'ancient' is out of window.
        assert [s.identifier for s in sources] == ["joins"]

    def test_specific_topic_slug_filter_narrows_result(
        self, settings: Settings, db_with_progress: Path
    ) -> None:
        req = ScopeRequest(
            kind="topic_struggles",
            course="DataCamp",
            window_days=14,
            topic_slug="joins",
        )
        sources = resolve_scope(req, settings, db_path=db_with_progress)
        assert len(sources) == 1

    def test_no_struggling_in_window_raises(
        self, settings: Settings, db_with_progress: Path
    ) -> None:
        # 1-day window excludes the recent 'joins' rows IF they happen
        # to be older than 1 day; but our fixture stamped them at
        # ``now`` so we use a tighter test: filter by an unknown topic.
        req = ScopeRequest(
            kind="topic_struggles",
            course="DataCamp",
            window_days=14,
            topic_slug="not-a-real-topic",
        )
        with pytest.raises(ScopeResolutionError, match="No struggling topics"):
            resolve_scope(req, settings, db_path=db_with_progress)

    def test_invalid_window_days_rejected(
        self, settings: Settings, db_with_progress: Path
    ) -> None:
        req = ScopeRequest(kind="topic_struggles", course="DataCamp", window_days=0)
        with pytest.raises(ScopeResolutionError, match="window_days must be"):
            resolve_scope(req, settings, db_path=db_with_progress)

    def test_missing_db_returns_empty_then_raises_empty(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        # No file at the db path. The query helper returns []; the
        # outer resolver then raises "No struggling topics" which is
        # the right user-facing message ("you have nothing to generate
        # for"), not a database error.
        ghost = tmp_path / "does-not-exist.db"
        req = ScopeRequest(kind="topic_struggles", course="DataCamp", window_days=14)
        with pytest.raises(ScopeResolutionError, match="No struggling topics"):
            resolve_scope(req, settings, db_path=ghost)


# ---------------------------------------------------------------------------
# resolver-level
# ---------------------------------------------------------------------------


class TestResolvedSourceShape:
    def test_returns_resolved_source_instances(self, settings: Settings) -> None:
        req = ScopeRequest(kind="course", course="DataCamp")
        sources = resolve_scope(req, settings)
        for s in sources:
            assert isinstance(s, ResolvedSource)
            assert s.identifier and s.title and s.markdown_text
