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


# ---------------------------------------------------------------------------
# POST /api/backlog/park — quick-park brain-dump
# ---------------------------------------------------------------------------


def test_park_happy_path(monkeypatch) -> None:
    captured: dict = {}

    def _fake_park(question, **kw):
        captured["question"] = question
        captured.update(kw)
        return 42

    monkeypatch.setattr("studyloop.web.routes.backlog.park_topic", _fake_park)
    resp = _client().post("/api/backlog/park", json={"question": "  What is MVCC?  "})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "id": 42}
    assert captured["question"] == "What is MVCC?"  # stripped
    assert captured["created_by"] == "web"
    assert captured["source"] == "parked"


def test_park_with_tech_area_and_context(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.park_topic",
        lambda q, **kw: captured.update({"q": q, **kw}) or 7,
    )
    resp = _client().post(
        "/api/backlog/park",
        json={"question": "CTE vs subquery", "tech_area": "SQL", "context": "during flashcards"},
    )
    assert resp.status_code == 200
    assert captured["tech_area"] == "SQL"
    assert captured["context"] == "during flashcards"


def test_park_failure_returns_500(monkeypatch) -> None:
    monkeypatch.setattr("studyloop.web.routes.backlog.park_topic", lambda q, **kw: None)
    resp = _client().post("/api/backlog/park", json={"question": "x"})
    assert resp.status_code == 500


def test_park_empty_question_rejected() -> None:
    resp = _client().post("/api/backlog/park", json={"question": ""})
    assert resp.status_code == 422  # pydantic min_length


# ---------------------------------------------------------------------------
# GET /api/session/last — resume source
# ---------------------------------------------------------------------------


def test_session_last_returns_latest_row(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.history.sessions.get_last_study_session",
        lambda: {
            "topic": "Python decorators",
            "topic_slug": "python",
            "energy_level": "medium",
            "started_at": "2026-07-12T10:00:00",
            "ended_at": "2026-07-12T10:45:00",
        },
    )
    body = _client().get("/api/session/last").json()
    assert body["topic"] == "Python decorators"
    assert body["energy_level"] == "medium"


def test_session_last_empty_when_no_history(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.history.sessions.get_last_study_session", lambda: None
    )
    assert _client().get("/api/session/last").json() == {}


# ---------------------------------------------------------------------------
# POST /api/backlog/demote — free a 3-topic slot (park-first friction modal)
# ---------------------------------------------------------------------------


def test_demote_happy_path(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.demote_parked_topic",
        lambda pid: captured.update({"id": pid}) or True,
    )
    resp = _client().post("/api/backlog/demote", json={"id": 7})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert captured["id"] == 7


def test_demote_failure_returns_500(monkeypatch) -> None:
    monkeypatch.setattr(
        "studyloop.web.routes.backlog.demote_parked_topic", lambda pid: False
    )
    assert _client().post("/api/backlog/demote", json={"id": 7}).status_code == 500
