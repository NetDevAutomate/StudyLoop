"""Tests for POST /api/history/struggling-topics (Phase 5).

Verifies that marking a lesson section as a struggle:
  - writes a study_progress row with confidence='struggling'
  - persists provenance (source_course, source_section, created_by='web')
  - surfaces via GET /api/history/struggling-topics?days=90
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from studyloop.web.app import create_app

if TYPE_CHECKING:
    from pytest import MonkeyPatch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCHEMA_PATH = (
    Path(__file__).parents[2]  # packages/
    / "agent-session-tools"
    / "src"
    / "agent_session_tools"
    / "schema.sql"
)


@pytest.fixture
def migrated_db(tmp_path: Path) -> Path:
    """Create a fresh DB bootstrapped with base schema + all migrations (incl. v22)."""
    from agent_session_tools.migrations import migrate

    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    migrate(conn)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def client(migrated_db: Path, monkeypatch: MonkeyPatch) -> TestClient:
    """Wire the history helpers to our migrated tmp DB."""

    def _connect_migrated():
        conn = sqlite3.connect(migrated_db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("studyloop.history._connection._connect", _connect_migrated)
    return TestClient(create_app(study_dirs=[]))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPostStrugglingTopic:
    def test_post_returns_ok_true(self, client: TestClient) -> None:
        resp = client.post(
            "/api/history/struggling-topics",
            json={
                "course": "deeplearning-ai/mlops-course",
                "section": "intro-to-pipelines",
                "publisher": "deeplearning-ai",
                "note": "confused about DAG vs pipeline distinction",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_post_writes_struggling_row_to_db(self, client: TestClient, migrated_db: Path) -> None:
        client.post(
            "/api/history/struggling-topics",
            json={
                "course": "deeplearning-ai/mlops-course",
                "section": "intro-to-pipelines",
                "publisher": "deeplearning-ai",
            },
        )
        conn = sqlite3.connect(migrated_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT confidence, source_course, source_section, source_publisher, created_by "
            "FROM study_progress WHERE topic = ? AND concept = ?",
            ("intro-to-pipelines", "intro-to-pipelines"),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["confidence"] == "struggling"
        assert row["source_course"] == "deeplearning-ai/mlops-course"
        assert row["source_section"] == "intro-to-pipelines"
        assert row["source_publisher"] == "deeplearning-ai"
        assert row["created_by"] == "web"

    def test_post_without_publisher_still_writes(
        self, client: TestClient, migrated_db: Path
    ) -> None:
        resp = client.post(
            "/api/history/struggling-topics",
            json={"course": "fast-ai/practical-dl", "section": "lesson-1-basics"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        conn = sqlite3.connect(migrated_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT source_publisher FROM study_progress WHERE concept = ?",
            ("lesson-1-basics",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["source_publisher"] is None

    def test_post_surfaces_via_get_endpoint(self, client: TestClient) -> None:
        """Row written by POST must appear in GET struggling-topics."""
        client.post(
            "/api/history/struggling-topics",
            json={
                "course": "deeplearning-ai/mlops-course",
                "section": "feature-store",
                "publisher": "deeplearning-ai",
            },
        )
        resp = client.get("/api/history/struggling-topics?days=90")
        assert resp.status_code == 200
        topics = {entry["topic"] for entry in resp.json()}
        assert "feature-store" in topics

    def test_post_missing_required_fields_returns_422(self, client: TestClient) -> None:
        # Missing 'section'.
        resp = client.post(
            "/api/history/struggling-topics",
            json={"course": "deeplearning-ai/mlops-course"},
        )
        assert resp.status_code == 422

    def test_post_missing_course_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/history/struggling-topics",
            json={"section": "lesson-1"},
        )
        assert resp.status_code == 422

    def test_duplicate_post_increments_session_count(
        self, client: TestClient, migrated_db: Path
    ) -> None:
        """A second POST to the same course/section bumps session_count, not duplicates."""
        payload = {"course": "fast-ai/practical-dl", "section": "lesson-1-basics"}
        client.post("/api/history/struggling-topics", json=payload)
        client.post("/api/history/struggling-topics", json=payload)

        conn = sqlite3.connect(migrated_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT COUNT(*) AS cnt, MAX(session_count) AS sc "
            "FROM study_progress WHERE topic = ? AND concept = ?",
            ("lesson-1-basics", "lesson-1-basics"),
        ).fetchone()
        conn.close()
        # Only one row (upsert on uuid5 id), with session_count = 2.
        assert rows["cnt"] == 1
        assert rows["sc"] == 2
