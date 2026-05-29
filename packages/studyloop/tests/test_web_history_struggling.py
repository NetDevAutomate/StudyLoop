"""Tests for ``GET /api/history/struggling-topics`` (U10).

Seeds a tmp ``study_progress`` table and patches the helper's
connection factory so the route runs against our test data without
touching the user's real ``sessions.db``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """Populate a tmp sessions.db with struggling / non-struggling rows."""
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
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
        # struggling, in window — counts
        ("id1", "joins", "outer", "struggling",
         now.isoformat(), now.isoformat(), 2, None,
         now.isoformat(), now.isoformat()),
        # second concept, same topic, struggling — should still be ONE topic
        ("id2", "joins", "self-join", "struggling",
         now.isoformat(), now.isoformat(), 3, None,
         now.isoformat(), now.isoformat()),
        # struggling but out of 14d window
        ("id3", "ancient", "old", "struggling",
         (now - timedelta(days=60)).isoformat(),
         (now - timedelta(days=60)).isoformat(), 1, None,
         now.isoformat(), now.isoformat()),
        # learning, in window — must be ignored
        ("id4", "advanced-pandas", "groupby", "learning",
         now.isoformat(), now.isoformat(), 1, None,
         now.isoformat(), now.isoformat()),
        # struggling, in window, different topic
        ("id5", "indexes", "btree", "struggling",
         now.isoformat(), now.isoformat(), 1, None,
         now.isoformat(), now.isoformat()),
    ]
    conn.executemany(
        "INSERT INTO study_progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def client(seeded_db: Path, monkeypatch: MonkeyPatch) -> TestClient:
    """Patch the progress helper's connect factory to use our tmp DB."""
    def _connect_seeded():
        conn = sqlite3.connect(seeded_db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("studyloop.history._connection._connect", _connect_seeded)
    return TestClient(create_app(study_dirs=[]))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStrugglingTopicsRoute:
    def test_returns_distinct_topics_in_window(self, client: TestClient) -> None:
        resp = client.get("/api/history/struggling-topics")
        assert resp.status_code == 200
        data = resp.json()
        topics = {entry["topic"] for entry in data}
        assert topics == {"joins", "indexes"}

    def test_concept_count_aggregates_distinct_concepts(self, client: TestClient) -> None:
        data = client.get("/api/history/struggling-topics").json()
        joins = next(e for e in data if e["topic"] == "joins")
        # joins has TWO distinct concepts (outer, self-join) struggling.
        assert joins["concept_count"] == 2
        # session_count summed across the two rows = 2 + 3 = 5.
        assert joins["session_count"] == 5

    def test_excludes_out_of_window_rows(self, client: TestClient) -> None:
        data = client.get("/api/history/struggling-topics?days=14").json()
        topics = {e["topic"] for e in data}
        assert "ancient" not in topics

    def test_days_query_param_validation(self, client: TestClient) -> None:
        # 0 below the floor of 1.
        assert client.get("/api/history/struggling-topics?days=0").status_code == 422
        # 100 above the ceiling of 90.
        assert client.get("/api/history/struggling-topics?days=100").status_code == 422
