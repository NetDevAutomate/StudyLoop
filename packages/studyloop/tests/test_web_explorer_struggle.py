"""Tests for POST /api/history/struggling-topics (Phase 5).

Verifies that marking a lesson section as a struggle:
  - writes an explicitly owned observation with confidence='struggling'
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
    """Create a fresh DB with all migrations, including observation ownership."""
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
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr("studyloop.history._connection._connect", _connect_migrated)
    return TestClient(create_app(study_dirs=[]))


def _progress_rows(db: Path) -> list[dict]:
    from studyloop.history import observations

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        assert conn.execute("SELECT count(*) FROM study_progress").fetchone()[0] == 0
        return observations.rows(conn)
    finally:
        conn.close()


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
        row = next(r for r in _progress_rows(migrated_db) if r["concept"] == "intro-to-pipelines")
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

        row = next(r for r in _progress_rows(migrated_db) if r["concept"] == "lesson-1-basics")
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

        rows = _progress_rows(migrated_db)
        # Two explicit reports yield one current assessment and retained history.
        assert len(rows) == 1
        assert rows[0]["session_count"] == 2
