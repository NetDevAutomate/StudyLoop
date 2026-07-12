"""Tests for GET /api/backlog — 3-topic active/parking-lot split."""

from __future__ import annotations

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.settings import MAX_ACTIVE_TOPICS  # noqa: E402
from studyloop.web.app import create_app  # noqa: E402


def _client() -> TestClient:
    return TestClient(create_app(study_dirs=[]))


def test_backlog_splits_active_and_parking_lot(monkeypatch) -> None:
    """More than MAX_ACTIVE_TOPICS pending → first N active, rest parked."""
    pending = [
        {"id": i, "question": f"q{i}", "status": "pending"}
        for i in range(MAX_ACTIVE_TOPICS + 2)
    ]
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.get_parked_topics",
        lambda status="pending": list(pending),
    )
    resp = _client().get("/api/backlog")
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_active"] == MAX_ACTIVE_TOPICS
    assert body["active_count"] == MAX_ACTIVE_TOPICS
    assert body["parking_lot_count"] == 2
    assert len(body["active"]) == MAX_ACTIVE_TOPICS
    # No overlap: active + parking_lot partitions the pending set.
    active_ids = {t["id"] for t in body["active"]}
    parked_ids = {t["id"] for t in body["parking_lot"]}
    assert active_ids.isdisjoint(parked_ids)
    assert active_ids | parked_ids == {t["id"] for t in pending}


def test_backlog_under_limit_has_empty_parking_lot(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.get_parked_topics",
        lambda status="pending": [{"id": 1, "question": "q1", "status": "pending"}],
    )
    body = _client().get("/api/backlog").json()
    assert body["active_count"] == 1
    assert body["parking_lot_count"] == 0
    assert body["parking_lot"] == []


def test_backlog_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.get_parked_topics",
        lambda status="pending": [],
    )
    body = _client().get("/api/backlog").json()
    assert body["active_count"] == 0
    assert body["parking_lot_count"] == 0
